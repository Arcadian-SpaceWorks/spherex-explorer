"""Compare two SPHEREx frames in time or in wavelength. Pure functions: no network, no file writes.

Frames can come from IRSA image-server cutouts or from full detector files cut locally; both are
read the same way. The wavelength at the target is read on the file's own pixel grid before any
local cut, because astropy's Cutout2D does not carry the spectral ("W") WCS.

Scientific limits, kept deliberately: a difference image is only produced for frames of the same
detector, taken at least an hour apart, at nearly the same target wavelength and with enough
overlap. Frames at different wavelengths are only shown side by side or blinked. Nothing here
claims motion, variability or discoveries.
"""
from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
import warnings

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.nddata import Cutout2D
from astropy.nddata.utils import NoOverlapError
from astropy.time import Time
from astropy.wcs import WCS
from reproject import reproject_interp

from ..fits_image import BAD_FLAGS, celestial_wcs, finite, science_hdu, wavelength_at

SPHEREX_PIXEL_SCALE_ARCSEC = 6.15
# A north-up square grid is rotated relative to a detector-aligned cutout. A cutout of
# size * sqrt(2) (plus a small margin for interpolation) always covers the whole grid.
GRID_COVER_FACTOR = math.sqrt(2) * 1.03
IRSA_MAX_CUTOUT_DEG = 1.0
MODES = ('time', 'wavelength')


class FrameError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ComparisonNotAllowed(ValueError):
    pass


@dataclass(frozen=True)
class CompareSettings:
    max_wavelength_delta_um: float = 0.02
    min_time_separation_hours: float = 1.0
    max_simultaneous_hours: float = 1.0
    min_overlap: float = 0.90
    core_box_px: int = 20
    max_pixels: int = 8_000_000


DEFAULT_SETTINGS = CompareSettings()


@dataclass
class Frame:
    """One cutout around the target. `data` is NaN wherever `valid` is False."""
    data: np.ndarray
    valid: np.ndarray
    wcs: WCS
    target_pixel: tuple
    obs_id: str | None
    detector: int | None
    observed_at_utc: str | None
    mjd: float | None
    wavelength_um: float | None
    bandwidth_um: float | None
    zodi: np.ndarray | None = None
    provenance: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)

    @property
    def band(self):
        return f'SPHEREx-D{self.detector}' if self.detector is not None else None

    def summary(self):
        return {'obs_id': self.obs_id, 'band': self.band, 'detector': self.detector,
                'observed_at_utc': self.observed_at_utc, 'mjd': self.mjd,
                'wavelength_um': self.wavelength_um, 'bandwidth_um': self.bandwidth_um,
                'diagnostics': dict(self.diagnostics), 'provenance': dict(self.provenance)}


@dataclass(frozen=True)
class Grid:
    wcs: WCS
    shape: tuple
    ra: float
    dec: float
    size_deg: float
    pixel_scale_arcsec: float

    def summary(self):
        return {'projection': 'TAN', 'north_up': True, 'ra': self.ra, 'dec': self.dec,
                'size_deg': self.size_deg, 'pixel_scale_arcsec': self.pixel_scale_arcsec,
                'shape': list(self.shape)}


@dataclass
class AlignedFrame:
    frame: Frame
    data: np.ndarray
    valid: np.ndarray


@dataclass(frozen=True)
class Reason:
    code: str
    severity: str  # 'info' | 'warn' | 'reject'
    detail: str
    values: dict = field(default_factory=dict)

    def to_dict(self):
        return {'code': self.code, 'severity': self.severity, 'detail': self.detail, 'values': dict(self.values)}


@dataclass(frozen=True)
class Validation:
    mode: str
    decision: str  # 'ACCEPT' | 'WARN' | 'REJECT'
    reasons: tuple
    difference_allowed: bool
    wavelength_delta_um: float | None
    time_separation_hours: float | None
    overlap_fraction: float | None

    def to_dict(self):
        return {'mode': self.mode, 'decision': self.decision, 'difference_allowed': self.difference_allowed,
                'wavelength_delta_um': self.wavelength_delta_um,
                'time_separation_hours': self.time_separation_hours,
                'overlap_fraction': self.overlap_fraction,
                'reasons': [reason.to_dict() for reason in self.reasons]}


@dataclass
class Difference:
    data: np.ndarray  # b - scale * a - offset, NaN outside the shared valid area
    valid: np.ndarray
    offset: float
    scale: float
    scale_matched: bool
    robust_noise: float
    overlap_fraction: float
    n_pixels: int

    def diagnostics(self):
        return {'offset': self.offset, 'scale': self.scale, 'scale_matched': self.scale_matched,
                'robust_noise': self.robust_noise, 'overlap_fraction': self.overlap_fraction,
                'n_pixels': self.n_pixels}


def cutout_size_for_grid(size_deg):
    """Cutout width (degrees) that fully covers a north-up grid of `size_deg`, capped at IRSA's limit."""
    return min(IRSA_MAX_CUTOUT_DEG, size_deg * GRID_COVER_FACTOR)


def _sha256(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _observed(keyword):
    stamp = keyword('DATE-OBS')
    if stamp:
        try:
            time = Time(str(stamp), format='isot', scale='utc')
            return time.isot, float(time.mjd)
        except ValueError:
            pass
    mjd = finite(keyword('MJD-OBS'))
    if mjd is not None:
        time = Time(mjd, format='mjd', scale='utc')
        return time.isot, float(mjd)
    return None, None


def _box(x, y, size):
    """Slices of a size x size box centred on pixel (x, y), clipped at the array start."""
    cx, cy, half = int(round(x)), int(round(y)), size // 2
    return slice(max(cy - half, 0), max(cy + half, 0)), slice(max(cx - half, 0), max(cx + half, 0))


def load_frame(path, ra, dec, size_deg, *, source='file', settings=DEFAULT_SETTINGS):
    """Read one SPHEREx FITS file and cut `size_deg` around (ra, dec).

    `source` labels where the file came from ('irsa_cutout', 'local_cutout', ...) and is only
    recorded in provenance. Diagnostics are measured on the raw IMAGE (no zodi subtraction):
    sky level (5th percentile), zodi model median and the median of a core box centred on the target.
    """
    if not (math.isfinite(ra) and math.isfinite(dec) and 0 <= ra < 360 and -90 <= dec <= 90):
        raise FrameError('invalid_target', 'Invalid ICRS target coordinates.')
    if not (math.isfinite(size_deg) and 0 < size_deg <= IRSA_MAX_CUTOUT_DEG * 2):
        raise FrameError('invalid_size', 'Invalid cutout size.')
    target = SkyCoord(ra * u.deg, dec * u.deg, frame='icrs')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        with fits.open(path, memmap=False) as hdul:
            _, hdu = science_hdu(hdul, settings.max_pixels)
            try:
                wcs = celestial_wcs(hdu, hdul)
            except Exception as exc:
                raise FrameError('wcs_unavailable', 'This file has no usable celestial WCS.') from exc
            x, y = (float(value) for value in wcs.world_to_pixel(target))
            height, width = hdu.shape
            if not (np.isfinite([x, y]).all() and -.5 <= x < width - .5 and -.5 <= y < height - .5):
                raise FrameError('target_outside', 'The target is outside this image.')
            spectral = wavelength_at(hdu, hdul, x, y)
            data = np.asarray(hdu.data, dtype=np.float64)
            valid = np.isfinite(data)
            if 'FLAGS' in hdul and hdul['FLAGS'].shape == data.shape and np.issubdtype(hdul['FLAGS'].data.dtype, np.integer):
                valid &= (hdul['FLAGS'].data & BAD_FLAGS) == 0
            zodi = None
            if 'ZODI' in hdul and hdul['ZODI'].shape == data.shape:
                zodi = np.asarray(hdul['ZODI'].data, dtype=np.float64)

            def keyword(name):
                return hdu.header.get(name, hdul[0].header.get(name))
            obs_id = keyword('OBSID')
            detector = finite(keyword('DETECTOR'))
            observed_at_utc, mjd = _observed(keyword)

        cut_options = dict(position=target, size=size_deg * u.deg, wcs=wcs, mode='partial')
        try:
            cut = Cutout2D(np.where(valid, data, np.nan), fill_value=np.nan, **cut_options)
            valid_cut = Cutout2D(valid.astype(np.float32), fill_value=0, **cut_options).data > .5
            zodi_cut = Cutout2D(zodi, fill_value=np.nan, **cut_options).data if zodi is not None else None
        except NoOverlapError as exc:
            raise FrameError('target_outside', 'The requested cutout does not overlap this image.') from exc

    tx, ty = (float(value) for value in cut.to_cutout_position((x, y)))
    cut_data = np.where(valid_cut, cut.data, np.nan)
    good = cut_data[valid_cut]
    core = cut_data[_box(tx, ty, settings.core_box_px)]
    diagnostics = {
        'sky_level': float(np.percentile(good, 5)) if good.size else None,
        'zodi_median': float(np.nanmedian(zodi_cut)) if zodi_cut is not None and np.isfinite(zodi_cut).any() else None,
        'core_median': float(np.nanmedian(core)) if np.isfinite(core).any() else None,
        'core_box_px': settings.core_box_px,
        'valid_fraction': float(valid_cut.mean()),
        'measured_on': 'raw IMAGE cutout (no zodi subtraction)',
    }
    provenance = {'source': source, 'file_name': Path(path).name, 'sha256': _sha256(path),
                  'cutout_deg': size_deg, 'wavelength_source': spectral['source'] if spectral else None}
    return Frame(data=cut_data, valid=valid_cut, wcs=cut.wcs, target_pixel=(tx, ty), obs_id=obs_id,
                 detector=int(detector) if detector is not None else None,
                 observed_at_utc=observed_at_utc, mjd=mjd,
                 wavelength_um=spectral['wavelength_um'] if spectral else None,
                 bandwidth_um=spectral['bandwidth_um'] if spectral else None,
                 zodi=zodi_cut, provenance=provenance, diagnostics=diagnostics)


def common_grid(ra, dec, size_deg, pixel_scale_arcsec=SPHEREX_PIXEL_SCALE_ARCSEC):
    """North-up, east-left TAN grid centred on the target, at roughly SPHEREx's native pixel scale."""
    if not (math.isfinite(ra) and math.isfinite(dec) and 0 <= ra < 360 and -90 <= dec <= 90):
        raise ValueError('Invalid ICRS target coordinates')
    if not (math.isfinite(size_deg) and size_deg > 0 and math.isfinite(pixel_scale_arcsec) and pixel_scale_arcsec > 0):
        raise ValueError('Invalid grid size or pixel scale')
    n = max(1, round(size_deg * 3600 / pixel_scale_arcsec))
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ['RA---TAN', 'DEC--TAN']
    wcs.wcs.crval = [ra, dec]
    wcs.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]  # FITS pixels are 1-based: the array centre is the target.
    wcs.wcs.cdelt = [-pixel_scale_arcsec / 3600, pixel_scale_arcsec / 3600]
    wcs.wcs.cunit = ['deg', 'deg']
    wcs.wcs.radesys = 'ICRS'
    return Grid(wcs=wcs, shape=(n, n), ra=ra, dec=dec, size_deg=size_deg, pixel_scale_arcsec=pixel_scale_arcsec)


def align(frames, grid):
    """Resample frames onto `grid` (bilinear). A grid pixel is valid only if every input pixel it
    interpolates from is valid, so NaN and flagged pixels never leak into neighbours."""
    aligned = []
    for frame in frames:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            data, footprint = reproject_interp((np.where(frame.valid, frame.data, np.nan), frame.wcs), grid.wcs,
                                               shape_out=grid.shape, order='bilinear')
            coverage = reproject_interp((frame.valid.astype(np.float64), frame.wcs), grid.wcs,
                                        shape_out=grid.shape, order='bilinear', return_footprint=False)
        valid = (footprint > 0) & np.isfinite(data) & (np.nan_to_num(coverage) >= 1 - 1e-6)
        aligned.append(AlignedFrame(frame=frame, data=np.where(valid, data, np.nan), valid=valid))
    return aligned


def overlap_fraction(a, b):
    """Fraction of the grid where both aligned frames have valid data."""
    return float((a.valid & b.valid).mean())


def validate(a, b, mode, *, overlap=None, settings=DEFAULT_SETTINGS):
    """Decide whether two frames may be compared. Returns ACCEPT / WARN / REJECT with reasons.

    time: same detector, >= 1 h apart, target wavelengths within 0.02 um, overlap >= 90%.
          A wavelength mismatch is a WARN (blink only); the other failures are REJECT.
    wavelength: same exposure or within 1 h, at different wavelengths. Never a difference image.
    """
    if mode not in MODES:
        raise ValueError(f'mode must be one of {MODES}')
    reasons = []

    def add(code, severity, detail, **values):
        reasons.append(Reason(code, severity, detail, values))

    hours = abs(a.mjd - b.mjd) * 24 if a.mjd is not None and b.mjd is not None else None
    delta = (abs(a.wavelength_um - b.wavelength_um)
             if a.wavelength_um is not None and b.wavelength_um is not None else None)
    same_exposure = bool(a.obs_id) and a.obs_id == b.obs_id
    limit = settings.max_wavelength_delta_um

    if mode == 'time':
        if a.detector is None or b.detector is None or a.detector != b.detector:
            add('band_mismatch', 'reject', 'Time comparison needs two images from the same detector.',
                band_a=a.band, band_b=b.band)
        if hours is None:
            add('time_unknown', 'reject', 'An observation time is missing.')
        elif hours < settings.min_time_separation_hours:
            add('too_close_in_time', 'reject',
                f'The images are {hours:.2f} h apart; at least {settings.min_time_separation_hours:g} h is required.',
                hours=hours, minimum_hours=settings.min_time_separation_hours)
        if delta is None:
            add('wavelength_unknown', 'warn', 'The wavelength at the target is unknown for at least one image; '
                'brightness cannot be compared directly. Blink only.')
        elif delta > limit:
            add('wavelength_mismatch', 'warn',
                f'The target was seen at wavelengths {delta:.3f} um apart (limit {limit:g} um). '
                'Brightness differences may come from wavelength, not time. Blink only.',
                delta_um=delta, limit_um=limit)
        else:
            add('wavelength_match', 'info', f'Target wavelengths agree within {delta:.3f} um.',
                delta_um=delta, limit_um=limit)
        if overlap is None:
            add('overlap_not_measured', 'warn', 'Overlap has not been measured yet.')
        elif overlap <= 0:
            add('no_overlap', 'reject', 'The images share no valid pixels.', overlap=overlap)
        elif overlap < settings.min_overlap:
            add('low_overlap', 'reject',
                f'Only {overlap:.0%} of the area is valid in both images (minimum {settings.min_overlap:.0%}). '
                'Side by side and blink only.', overlap=overlap, minimum=settings.min_overlap)
    else:
        if not (same_exposure or (hours is not None and hours <= settings.max_simultaneous_hours)):
            add('not_simultaneous', 'reject',
                'Wavelength comparison needs the same exposure or images within '
                f'{settings.max_simultaneous_hours:g} h of each other.', hours=hours)
        if delta is None:
            add('wavelength_unknown', 'warn', 'The wavelength at the target is unknown for at least one image.')
        elif delta <= limit:
            add('same_wavelength', 'reject', f'The images are at the same wavelength (within {limit:g} um); '
                'use time mode instead.', delta_um=delta, limit_um=limit)
        if overlap is None:
            add('overlap_not_measured', 'warn', 'Overlap has not been measured yet.')
        elif overlap <= 0:
            add('no_overlap', 'reject', 'The images share no valid pixels.', overlap=overlap)
        elif overlap < settings.min_overlap:
            add('low_overlap', 'warn', f'Only {overlap:.0%} of the area is valid in both images.',
                overlap=overlap, minimum=settings.min_overlap)
        add('no_cross_wavelength_difference', 'info',
            'Images at different wavelengths are shown side by side or blinked, never subtracted.')

    worst = max((('info', 'warn', 'reject').index(reason.severity) for reason in reasons), default=0)
    decision = ('ACCEPT', 'WARN', 'REJECT')[worst]
    return Validation(mode=mode, decision=decision, reasons=tuple(reasons),
                      difference_allowed=mode == 'time' and decision == 'ACCEPT',
                      wavelength_delta_um=delta, time_separation_hours=hours, overlap_fraction=overlap)


def difference(a, b, validation, *, match_scale=False, settings=DEFAULT_SETTINGS):
    """b - scale * a - offset on the shared valid area. Only for an ACCEPTed time comparison.

    The offset is the median of the raw difference (a robust background match). With
    `match_scale`, the scale is the ratio of background-subtracted medians in a core box at the
    grid centre (the target); if that ratio cannot be measured, scale stays 1 and is reported so.
    """
    if not validation.difference_allowed:
        raise ComparisonNotAllowed(f'A difference image is not allowed for this pair ({validation.decision}).')
    if a.data.shape != b.data.shape:
        raise ValueError('Frames must be aligned to the same grid')
    both = a.valid & b.valid
    if both.sum() < 2:
        raise ComparisonNotAllowed('The images share too few valid pixels.')
    scale, scale_matched = 1.0, False
    if match_scale:
        n_y, n_x = a.data.shape
        core_mask = np.zeros_like(both)
        core_mask[_box((n_x - 1) / 2, (n_y - 1) / 2, settings.core_box_px)] = True
        core_mask &= both
        if core_mask.any():
            numerator = np.median(b.data[core_mask]) - np.median(b.data[both])
            denominator = np.median(a.data[core_mask]) - np.median(a.data[both])
            if math.isfinite(numerator) and math.isfinite(denominator) and numerator > 0 and denominator > 0:
                scale, scale_matched = float(numerator / denominator), True
    raw = b.data - scale * a.data
    offset = float(np.median(raw[both]))
    result = np.where(both, raw - offset, np.nan)
    values = result[both]
    noise = float(1.4826 * np.median(np.abs(values - np.median(values))))
    return Difference(data=result, valid=both, offset=offset, scale=scale, scale_matched=scale_matched,
                      robust_noise=noise, overlap_fraction=float(both.mean()), n_pixels=int(both.sum()))
