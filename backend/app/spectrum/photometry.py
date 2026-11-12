"""Forced aperture photometry on one SPHEREx Level 2 exposure.

A SPHEREx exposure is not an image at one wavelength: a linear variable filter makes the
wavelength change across the detector, so a source is seen at ONE wavelength per exposure, set by
where it falls. Measuring the same sky position in every exposure therefore builds its spectrum.

Method (deliberately simple and stated in every response):
  * circular aperture of radius 2.5 px (15.4 arcsec) centred on the requested position, with
    sub-pixel edge weights; no recentring, so a non-detection stays a non-detection;
  * local background = sigma-clipped median of the pixels 6 to 12 px from the target that lie in
    the 9 detector rows around it. This removes zodiacal light and smooth diffuse emission without
    the ZODI model. Staying in the target's rows keeps the background at nearly the target's own
    wavelength (the filter's wavelength changes along detector columns) and keeps remote reads small;
  * uncertainty = pipeline VARIANCE summed in the aperture plus the background-estimate term;
  * no aperture correction (the flux in the PSF wings outside 2.5 px is not added back).
"""
import math
import warnings

import numpy as np
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_area

from ..fits_image import wavelength_at, wcs_header

APERTURE_PX, ANNULUS_IN_PX, ANNULUS_OUT_PX = 2.5, 6.0, 12.0
HALF_X, HALF_Y = 13, 4  # stamp half-sizes in pixels (columns, rows)
SUBSAMPLE = 5

FLAG_NAMES = {0: 'TRANSIENT', 1: 'OVERFLOW', 2: 'SUR_ERROR', 6: 'NONFUNC', 7: 'DICHROIC', 9: 'MISSING_DATA',
              10: 'HOT', 11: 'COLD', 12: 'FULLSAMPLE', 14: 'PHANMISS', 15: 'NONLINEAR', 17: 'PERSIST',
              19: 'OUTLIER', 20: 'CROSSTALK', 21: 'SOURCE', 22: 'GHOST', 23: 'GHOST_FPA', 24: 'GHOST_EXT',
              25: 'STREAK', 26: 'BLOOM', 27: 'SNOWBALL', 28: 'HALO'}


def _mask(*bits):
    return sum(1 << bit for bit in bits)


# A pixel with any of these inside the aperture makes the measurement unusable.
REJECT = _mask(0, 1, 2, 6, 7, 9, 10, 11, 15, 17, 25, 26, 27, 28)
# Kept, but reported: the flux may be contaminated. OUTLIER (bit 19) is here and not in REJECT
# because the pipeline sets it on anything that differs from the static sky, which includes
# exactly the sources of interest: comets, asteroids and objects that changed brightness.
WARN = _mask(14, 19, 20, 22, 23, 24)
# Not used for the background estimate. SOURCE (bit 21) is deliberately allowed: in crowded fields
# it covers nearly every pixel, and the sigma clipping already removes neighbouring stars.
BACKGROUND_EXCLUDE = REJECT | WARN


def flag_names(value):
    return [name for bit, name in FLAG_NAMES.items() if value & (1 << bit)]


def aperture_weights(shape, x, y, radius):
    """Fraction of each pixel inside a circle, by SUBSAMPLE x SUBSAMPLE sub-pixels."""
    offsets = (np.arange(SUBSAMPLE) + .5) / SUBSAMPLE - .5
    yy, xx = np.indices(shape, dtype=float)
    inside = np.zeros(shape)
    for dy in offsets:
        for dx in offsets:
            inside += np.hypot(xx + dx - x, yy + dy - y) <= radius
    return inside / SUBSAMPLE ** 2


def clipped_background(values):
    """Sigma-clipped median and robust scatter of background pixels."""
    values = values[np.isfinite(values)]
    for _ in range(5):
        if values.size < 20:
            break
        median = np.median(values)
        sigma = 1.4826 * np.median(np.abs(values - median))
        if sigma <= 0:
            break
        keep = np.abs(values - median) <= 3 * sigma
        if keep.all():
            break
        values = values[keep]
    if values.size < 20:
        return None
    median = float(np.median(values))
    return median, float(1.4826 * np.median(np.abs(values - median))), int(values.size)


def measure(image, variance, flags, x, y, pixel_area_sr):
    """Photometry on a stamp. `x`, `y` are zero-based stamp coordinates of the target.

    `image` is in MJy/sr, `variance` in (MJy/sr)^2. Returns flux density in mJy, or a result with
    `status` explaining why no flux is given. Never fills in a value that was not measured.
    """
    image = np.asarray(image, dtype=float)
    height, width = image.shape
    if not (ANNULUS_OUT_PX <= x <= width - 1 - ANNULUS_OUT_PX and HALF_Y - .5 <= y <= height - .5 - HALF_Y):
        return {'status': 'edge'}
    flags = np.zeros(image.shape, dtype=np.int64) if flags is None else np.asarray(flags).astype(np.int64)
    weights = aperture_weights(image.shape, x, y, APERTURE_PX)
    aperture = weights > 0
    yy, xx = np.indices(image.shape, dtype=float)
    radius = np.hypot(xx - x, yy - y)
    aperture_flags = int(np.bitwise_or.reduce(flags[aperture]))
    result = {'flags': aperture_flags, 'flag_names': flag_names(aperture_flags & (REJECT | WARN))}
    if aperture_flags & REJECT or not np.isfinite(image[aperture]).all():
        saturated = bool(aperture_flags & _mask(1, 15, 26))
        return {**result, 'status': 'saturated' if saturated else 'flagged'}
    annulus = ((radius >= ANNULUS_IN_PX) & (radius <= ANNULUS_OUT_PX) & (np.abs(yy - y) <= HALF_Y + .5)
               & ((flags & BACKGROUND_EXCLUDE) == 0))
    background = clipped_background(image[annulus])
    if background is None:
        return {**result, 'status': 'no_background'}
    level, scatter, used = background
    to_mjy = pixel_area_sr * 1e9  # MJy/sr x sr = MJy; x 1e9 = mJy
    flux = float(np.sum(weights[aperture] * (image[aperture] - level))) * to_mjy
    area = float(weights.sum())
    pipeline = 0.0
    if variance is not None:
        var = np.asarray(variance, dtype=float)[aperture]
        if np.isfinite(var).all() and (var >= 0).all():
            pipeline = float(np.sum(weights[aperture] ** 2 * var))
        else:
            variance = None
    # Background term: uncertainty of the median over `used` pixels, applied to the whole aperture.
    background_term = area ** 2 * (math.pi / 2) * scatter ** 2 / used
    # Without a usable VARIANCE plane, fall back to the measured sky scatter per aperture pixel.
    noise = pipeline if variance is not None else float(np.sum(weights ** 2)) * scatter ** 2
    error = math.sqrt(noise + background_term) * to_mjy
    if not math.isfinite(flux) or not math.isfinite(error) or error <= 0:
        return {**result, 'status': 'invalid'}
    return {**result, 'status': 'ok', 'flux_mjy': flux, 'flux_err_mjy': error,
            'background_mjy_sr': level, 'background_scatter_mjy_sr': scatter,
            'error_source': 'variance' if variance is not None else 'sky_scatter'}


def spatial_wcs(header, hdul=None):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        wcs = WCS(wcs_header(header), fobj=hdul)
    if not wcs.has_celestial:
        raise ValueError('No celestial WCS')
    return wcs.celestial


def locate(header, hdul, ra, dec):
    """Zero-based pixel position of (ra, dec) and the pixel solid angle there."""
    wcs = spatial_wcs(header, hdul)
    x, y = wcs.all_world2pix([[ra, dec]], 0, quiet=True)[0]
    return float(x), float(y), float(proj_plane_pixel_area(wcs)) * (math.pi / 180) ** 2


def window(x, y, width, height):
    """Row and column slices of the stamp needed around pixel (x, y), clipped to the detector."""
    cx, cy = int(round(x)), int(round(y))
    return (slice(max(0, cy - HALF_Y), min(height, cy + HALF_Y + 1)),
            slice(max(0, cx - HALF_X), min(width, cx + HALF_X + 1)))


def measure_hdul(hdul, ra, dec):
    """Photometry of (ra, dec) in an opened SPHEREx MEF (a full exposure or an IRSA cutout)."""
    hdu = hdul['IMAGE']
    x, y, area = locate(hdu.header, hdul, ra, dec)
    height, width = hdu.shape
    if not (np.isfinite([x, y]).all() and 0 <= x < width and 0 <= y < height):
        return {'status': 'outside'}
    rows, columns = window(x, y, width, height)
    x0, y0 = columns.start, rows.start
    window_ = (rows, columns)

    def plane(name):
        if name not in hdul or hdul[name].shape != hdu.shape:
            return None
        return hdul[name].data[window_]

    result = measure(hdu.data[window_], plane('VARIANCE'), plane('FLAGS'), x - x0, y - y0, area)
    spectral = wavelength_at(hdu, hdul, x, y)
    if spectral is None:
        return {**result, 'status': 'no_wavelength'} if result['status'] == 'ok' else result
    return {**result, 'x': x, 'y': y, 'wavelength_um': spectral['wavelength_um'],
            'bandwidth_um': spectral['bandwidth_um']}
