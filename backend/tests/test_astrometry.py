"""TEST DATA: synthetic stars on a comparison grid. Centroids, flags and motion arithmetic."""
import math

import numpy as np
import pytest

from backend.app.analysis import astrometry
from backend.app.analysis.astrometry import MeasureError, compare_with_prediction, measure_position, motion, refine_centroid

N = 60
NAMES = {0: 'TRANSIENT', 1: 'OVERFLOW', 19: 'OUTLIER', 21: 'SOURCE'}


def star(x, y, peak=500.0, sigma=1.3, noise=1.0, seed=1):
    rng = np.random.default_rng(seed)
    yy, xx = np.indices((N, N))
    return 10 + peak * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2)) + rng.normal(0, noise, (N, N))


def test_a_click_near_a_star_is_refined_to_its_centre():
    data = star(30.3, 25.7)
    c = refine_centroid(data, np.ones_like(data, bool), 32.0, 24.0)  # About 2.4 pixels off.
    assert c.x == pytest.approx(30.3, abs=0.05) and c.y == pytest.approx(25.7, abs=0.05)
    assert c.peak_snr > 300 and 0 < c.sigma_px < 0.05 and c.shift_px == pytest.approx(math.hypot(1.7, 1.7), abs=0.1)


def test_empty_sky_is_refused_rather_than_measured():
    data = star(30, 30, peak=0.0)
    with pytest.raises(MeasureError, match='No clear object') as caught:
        refine_centroid(data, np.ones_like(data, bool), 30, 30)
    assert caught.value.code == 'no_source'
    with pytest.raises(MeasureError, match='outside'):
        refine_centroid(data, np.ones_like(data, bool), -3, 30)


def test_a_saturated_core_switches_to_the_wings_and_a_larger_floor():
    data = star(30.4, 30.2, peak=5000.0)
    flags = np.zeros((N, N), dtype=np.int64)
    flags[29:32, 29:32] |= 1 << 1          # OVERFLOW core.
    data[29:32, 29:32] = 900.0             # Clipped values carry no position.
    c, floor, method, names, warnings = measure_position(data, np.ones_like(data, bool), flags, NAMES, 30, 30)
    assert floor == astrometry.SATURATED_FLOOR_ARCSEC and 'saturated pixels excluded' in method
    assert 'OVERFLOW' in names and warnings[0].startswith('Saturated object')
    # Excluding an off-centre saturated core biases the wings' centroid; the bias stays inside the floor.
    error_arcsec = math.hypot(c.x - 30.4, c.y - 30.2) * 6.15
    assert error_arcsec < astrometry.SATURATED_FLOOR_ARCSEC


def test_flags_near_the_centre_become_plain_warnings_but_source_is_informational():
    data = star(30, 30)
    flags = np.zeros((N, N), dtype=np.int64)
    flags[30, 30] = (1 << 19) | (1 << 21)
    _, floor, _, names, warnings = measure_position(data, np.ones_like(data, bool), flags, NAMES, 30, 30)
    assert floor == astrometry.REGISTRATION_FLOOR_ARCSEC
    assert names == ['OUTLIER', 'SOURCE'] and warnings == ['OUTLIER: outlier pixels']


def test_motion_direction_rate_and_significance():
    # 10" north over one year, positions known to 2" each.
    dec = 4.77
    result = motion((269.446, dec), (269.446, dec + 10 / 3600), 2.0, 2.0, 60900.0, 60900.0 + 365.25)
    assert result['shift_arcsec'] == pytest.approx(10.0, abs=1e-6)
    assert result['position_angle_deg'] == pytest.approx(0.0, abs=1e-6) and result['direction'] == 'north'
    assert result['rate_arcsec_per_year'] == pytest.approx(10.0, rel=1e-4)
    assert result['shift_sigma_arcsec'] == pytest.approx(math.sqrt(8)) and result['significance'] == pytest.approx(10 / math.sqrt(8))
    east = motion((10.0, 0.0), (10.0 + 30 / 3600, 0.0), 1.0, 1.0, 60000.0, 60000.125)
    assert east['direction'] == 'east' and east['rate_arcsec_per_hour'] == pytest.approx(10.0, rel=1e-6)


def test_same_moment_has_no_rate_and_says_so():
    result = motion((10.0, 0.0), (10.0, 1 / 3600), 1.0, 1.0, 60000.0, 60000.0)
    assert result['rate_arcsec_per_hour'] is None
    assert 'same moment' in astrometry.summary_text(result)


def test_small_shifts_are_reported_as_limits_not_motion():
    result = motion((10.0, 0.0), (10.0, 2 / 3600), 2.0, 2.0, 60000.0, 60100.0)
    assert astrometry.summary_text(result).startswith('No significant shift')
    hint = motion((10.0, 0.0), (10.0, 7 / 3600), 2.0, 2.0, 60000.0, 60100.0)  # 2.5 sigma.
    assert 'a hint of motion, not significant from this pair alone' in astrometry.summary_text(hint)


def test_prediction_agreement_and_disagreement():
    measured = motion((10.0, 0.0), (10.0, 10 / 3600), 1.0, 1.0, 60000.0, 60365.25)
    agree = compare_with_prediction(measured, (10.0, 0.0), (10.0, 10.5 / 3600), 1.0, 1.0, 'https://example.test/')
    assert agree['residual_arcsec'] == pytest.approx(0.5, abs=1e-3) and 'agrees with the prediction' in agree['agreement']
    off = compare_with_prediction(measured, (10.0, 0.0), (10.0, 20 / 3600), 1.0, 1.0, 'https://example.test/')
    assert off['residual_sigma'] > 3 and 'check the clicks' in off['agreement']
