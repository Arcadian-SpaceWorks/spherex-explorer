"""Measure how far, and how fast, one object moved between two aligned comparison images.

Pure functions on the comparison grid (north-up TAN, about 6.15" per pixel): no network, no files.
A click is refined to an intensity-weighted centroid, converted to ICRS through the grid WCS,
and the two positions give the shift, its direction and the apparent motion with uncertainties.

Scientific limits, kept deliberately: each position carries a statistical error from the pixel
noise plus an assumed per-image registration floor (resampling and WCS differences between
images). A shift is reported with its significance; nothing is called a detection or a discovery.
"""
from dataclasses import dataclass
import math

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord

# Per-image position floor on the comparison grid (resampling and WCS differences between images).
# Unsaturated: the comet 3I/ATLAS measured against IRSA's predictions agrees within this floor.
REGISTRATION_FLOOR_ARCSEC = 1.0
# Saturated cores (OVERFLOW): the 21 Barnard's Star demo frames, each centroided without saturated
# pixels in a 13 x 13 box, scatter by 2.6" (rms) around their Gaia DR3 positions.
SATURATED_FLOOR_ARCSEC = 2.6
MIN_SNR = 5.0
SEARCH_RADIUS_PX = 4      # A click may be up to about 25" from the object.
CENTROID_HALF_PX = 3      # 7 x 7 pixel centroid box.
SATURATED_HALF_PX = 6     # 13 x 13 box: a saturated core carries no position, its wings do.
BACKGROUND_PX = (6, 10)   # Annulus for the local background and noise.
# Bits that describe the pixel rather than a problem with it.
INFORMATIONAL_FLAGS = {'SOURCE', 'REFERENCE', 'FULLSAMPLE'}
FLAG_ADVICE = {
    'OVERFLOW': 'saturated pixels: the centroid of a saturated core can be biased by 1-2"',
    'NONLINEAR': 'pixels in the nonlinear range',
    'PERSIST': 'possible persistence from an earlier bright source',
    'GHOST': 'possible optical ghost', 'GHOST_FPA': 'possible optical ghost', 'GHOST_EXT': 'possible optical ghost',
    'TRANSIENT': 'pixels flagged as transient by the pipeline (often cosmic rays)',
    'OUTLIER': 'outlier pixels', 'HOT': 'hot pixels', 'COLD': 'cold pixels', 'HALO': 'bright-star halo',
    'BLOOM': 'charge bloom', 'SNOWBALL': 'snowball event', 'SUR_ERROR': 'ramp-fit error',
}


class MeasureError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Centroid:
    x: float            # Grid pixel, 0-based, WCS order (row 0 is the southern edge).
    y: float
    sigma_px: float     # Statistical error per axis.
    peak_snr: float
    shift_px: float     # Distance from the click.
    masked_in_box: int  # Masked pixels inside the centroid box.


def _ring(shape, x, y, inner, outer):
    yy, xx = np.indices(shape)
    r = np.hypot(xx - x, yy - y)
    return (r >= inner) & (r <= outer)


def refine_centroid(data, valid, x, y, half=CENTROID_HALF_PX):
    """Intensity-weighted centroid of the brightest object within SEARCH_RADIUS_PX of (x, y),
    in a (2*half+1)^2 box. Pixels where `valid` is False are ignored."""
    data = np.where(valid, np.asarray(data, dtype=np.float64), np.nan)
    height, width = data.shape
    if not (0 <= x < width and 0 <= y < height):
        raise MeasureError('click_outside', 'The click is outside the image.')
    ring = _ring(data.shape, x, y, *BACKGROUND_PX) & np.isfinite(data)
    if ring.sum() < 20:
        raise MeasureError('no_background', 'Too few valid pixels around the click to estimate the background.')
    background = float(np.median(data[ring]))
    noise = float(1.4826 * np.median(np.abs(data[ring] - background)))
    if not noise > 0:
        raise MeasureError('no_background', 'The background noise around the click could not be estimated.')
    search = (_ring(data.shape, x, y, 0, SEARCH_RADIUS_PX)) & np.isfinite(data)
    if not search.any():
        raise MeasureError('no_source', 'No valid pixels near the click.')
    peak_index = np.nanargmax(np.where(search, data, -np.inf))
    cy, cx = (float(v) for v in np.unravel_index(peak_index, data.shape))
    peak_snr = (float(data.flat[peak_index]) - background) / noise
    if peak_snr < MIN_SNR:
        raise MeasureError('no_source', f'No clear object within {SEARCH_RADIUS_PX * 6.15:.0f}" of the click '
                                        f'(brightest pixel is {peak_snr:.1f} times the noise; at least {MIN_SNR:.0f} is needed).')
    masked = 0
    for _ in range(5):
        x0, y0 = int(round(cx)), int(round(cy))
        rows = slice(max(y0 - half, 0), min(y0 + half + 1, height))
        cols = slice(max(x0 - half, 0), min(x0 + half + 1, width))
        box = data[rows, cols] - background
        masked = int((~np.isfinite(box)).sum())
        weights = np.clip(np.nan_to_num(box, nan=0.0), 0, None)
        total = float(weights.sum())
        if not total > 0:
            raise MeasureError('no_source', 'The object near the click has no flux above the background.')
        yy, xx = np.mgrid[rows, cols]
        nx, ny = float((weights * xx).sum() / total), float((weights * yy).sum() / total)
        moved = math.hypot(nx - cx, ny - cy)
        cx, cy = nx, ny
        if moved < 1e-3:
            break
    good = np.isfinite(box)
    sigma_x = math.sqrt(float((((xx - cx) ** 2)[good]).sum()) * noise ** 2) / total
    sigma_y = math.sqrt(float((((yy - cy) ** 2)[good]).sum()) * noise ** 2) / total
    return Centroid(x=cx, y=cy, sigma_px=float(max(sigma_x, sigma_y)), peak_snr=float(peak_snr),
                    shift_px=math.hypot(cx - x, cy - y), masked_in_box=masked)


def measure_position(data, valid, flags, flag_names, x, y):
    """Centroid near a click, switching to the saturated-star method when OVERFLOW pixels are in
    the core. Returns (Centroid, floor_arcsec, method, flag names, warnings)."""
    c = refine_centroid(data, valid, x, y)
    overflow = next((bit for bit, name in flag_names.items() if name == 'OVERFLOW'), 1)
    x0, y0 = int(round(c.x)), int(round(c.y))
    core = flags[max(y0 - CENTROID_HALF_PX, 0):y0 + CENTROID_HALF_PX + 1, max(x0 - CENTROID_HALF_PX, 0):x0 + CENTROID_HALF_PX + 1]
    saturated = bool(core.size and ((core >> overflow) & 1).any())
    floor, method = REGISTRATION_FLOOR_ARCSEC, f'{2 * CENTROID_HALF_PX + 1}x{2 * CENTROID_HALF_PX + 1} pixel centroid'
    if saturated:
        c = refine_centroid(data, valid & (((flags >> overflow) & 1) == 0), x, y, half=SATURATED_HALF_PX)
        floor = SATURATED_FLOOR_ARCSEC
        method = (f'saturated core: {2 * SATURATED_HALF_PX + 1}x{2 * SATURATED_HALF_PX + 1} pixel centroid of the '
                  'wings, saturated pixels excluded')
    names, warnings = flags_near(flags, flag_names, c.x, c.y)
    if saturated:
        warnings = [w for w in warnings if not w.startswith('OVERFLOW')]
        warnings.insert(0, f'Saturated object: its position uses the wings, with a {floor}" uncertainty floor per image')
    return c, floor, method, names, warnings


def flags_near(flags, flag_names, x, y, half=1):
    """Names of FLAGS bits set within (2*half+1)^2 pixels of the centroid, and warnings for them."""
    x0, y0 = int(round(x)), int(round(y))
    box = flags[max(y0 - half, 0):y0 + half + 1, max(x0 - half, 0):x0 + half + 1]
    bits = int(np.bitwise_or.reduce(box.ravel())) if box.size else 0
    names = [flag_names.get(bit, f'bit {bit}') for bit in range(63) if bits >> bit & 1]
    warnings = [f'{name}: {FLAG_ADVICE.get(name, "flagged pixels")}' for name in names if name not in INFORMATIONAL_FLAGS]
    return names, warnings


def compass(position_angle_deg):
    names = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west']
    return names[int(((position_angle_deg % 360) + 22.5) // 45) % 8]


def motion(position_a, position_b, sigma_a_arcsec, sigma_b_arcsec, mjd_a, mjd_b):
    """Shift from A to B on the sky, its direction and the apparent motion, with 1-sigma errors."""
    a, b = (SkyCoord(ra * u.deg, dec * u.deg, frame='icrs') for ra, dec in (position_a, position_b))
    shift = float(a.separation(b).to_value(u.arcsec))
    d_ra, d_dec = (float(v.to_value(u.arcsec)) for v in a.spherical_offsets_to(b))
    sigma = math.hypot(sigma_a_arcsec, sigma_b_arcsec)
    out = {'shift_arcsec': shift, 'shift_sigma_arcsec': sigma, 'significance': shift / sigma if sigma > 0 else None,
           'd_ra_cosdec_arcsec': d_ra, 'd_dec_arcsec': d_dec,
           'position_angle_deg': float(a.position_angle(b).to_value(u.deg)) if shift > 0 else None,
           'time_hours': None, 'rate_arcsec_per_hour': None, 'rate_arcsec_per_year': None,
           'rate_sigma_arcsec_per_hour': None, 'rate_sigma_arcsec_per_year': None}
    out['direction'] = compass(out['position_angle_deg']) if out['position_angle_deg'] is not None else None
    if mjd_a is not None and mjd_b is not None:
        hours = (mjd_b - mjd_a) * 24
        out['time_hours'] = hours
        if abs(hours) >= 1 / 60:
            years = abs(hours) / (24 * 365.25)
            out.update(rate_arcsec_per_hour=shift / abs(hours), rate_sigma_arcsec_per_hour=sigma / abs(hours),
                       rate_arcsec_per_year=shift / years, rate_sigma_arcsec_per_year=sigma / years)
    return out


def summary_text(result, predicted=None):
    """One plain-language sentence about what the two clicks show."""
    shift, sigma, significance = result['shift_arcsec'], result['shift_sigma_arcsec'], result['significance'] or 0
    if result['rate_arcsec_per_hour'] is None:
        return (f'Shift {shift:.1f} ± {sigma:.1f}". Both images are from the same moment, so a shift here reflects '
                'how the two images line up, not motion.')
    if significance < 2:
        text = (f'No significant shift: the object moved less than about {3 * sigma:.1f}" '
                f'in {abs(result["time_hours"]) / 24:.1f} days.')
    elif significance < 3:
        text = (f'Shift of {shift:.1f} ± {sigma:.1f}" toward the {result["direction"]}, only {significance:.1f} times its '
                'uncertainty: a hint of motion, not significant from this pair alone.')
    else:
        text = (f'Shift of {shift:.1f} ± {sigma:.1f}" toward the {result["direction"]} ({significance:.0f} times its '
                'uncertainty): consistent with real motion, but a measurement from two images, not a confirmed detection.')
    if predicted:
        text += ' ' + predicted['agreement']
    return text


def compare_with_prediction(measured, predicted_a, predicted_b, sigma_a, sigma_b, source):
    """How the measured shift compares with the predicted positions of the object in A and B."""
    pa = SkyCoord(predicted_a[0] * u.deg, predicted_a[1] * u.deg)
    pb = SkyCoord(predicted_b[0] * u.deg, predicted_b[1] * u.deg)
    p_ra, p_dec = (float(v.to_value(u.arcsec)) for v in pa.spherical_offsets_to(pb))
    p_shift = float(pa.separation(pb).to_value(u.arcsec))
    residual = math.hypot(measured['d_ra_cosdec_arcsec'] - p_ra, measured['d_dec_arcsec'] - p_dec)
    sigma = math.hypot(sigma_a, sigma_b)
    k = residual / sigma if sigma > 0 else math.inf
    out = {'source': source, 'shift_arcsec': p_shift, 'd_ra_cosdec_arcsec': p_ra, 'd_dec_arcsec': p_dec,
           'position_angle_deg': float(pa.position_angle(pb).to_value(u.deg)) if p_shift > 0 else None,
           'residual_arcsec': residual, 'residual_sigma': k}
    hours = measured['time_hours']
    if hours and abs(hours) >= 1 / 60:
        out['rate_arcsec_per_hour'] = p_shift / abs(hours)
        out['rate_arcsec_per_year'] = p_shift / (abs(hours) / (24 * 365.25))
    out['agreement'] = (f'The predicted shift is {p_shift:.1f}"; the measured shift differs from it by {residual:.1f}" '
                        f'({k:.1f} times the uncertainty), ' + ('which agrees with the prediction.' if k <= 3 else
                                                               'more than the uncertainty allows: check the clicks and flags.'))
    return out
