"""Controlled engineering injections, never real astronomical discoveries."""
import numpy as np
import pytest
from backend.app.analysis.compare import Frame, align, common_grid, overlap_fraction, validate
from backend.app.analysis.detection import DetectionEvidence, detect_changes

EVIDENCE = DetectionEvidence('MJy/sr', True, True, True, True)


def pair(change=None, shift=0):
    grid = common_grid(10, 40, .17)
    shape = grid.shape
    y, x = np.indices(shape)
    rng = np.random.default_rng(83)
    star = 30 * np.exp(-((x-45)**2+(y-50)**2)/8)
    a = star + rng.normal(0, 1, shape)
    b = star + rng.normal(0, 1, shape) + 7
    if change == 'bright':
        b += 25 * np.exp(-((x-45)**2+(y-50)**2)/8)
    if change == 'transient':
        b += 25 * np.exp(-((x-65)**2+(y-60)**2)/8)
    if change == 'moving':
        b -= star
        b += 30 * np.exp(-((x-51)**2+(y-50)**2)/8)
    if change == 'bad':
        a[30, 30] = np.nan
        b[30, 30] = 1e6
    frames = []
    for i, data in enumerate((a, b)):
        wcs = grid.wcs.deepcopy()
        if i and shift:
            # Consistent WCS translation and integer pixel translation of the sky.
            wcs.wcs.crpix += [shift, 0]
            data = np.roll(data, shift, axis=1)
        frames.append(Frame(data, np.isfinite(data), wcs, (50, 50), f'SYNTHETIC-{i}', 1,
                            f'2026-01-0{i+1}T00:00:00', 60000+i, 1., .01))
    aa, bb = align(frames, grid)
    check = validate(*frames, 'time', overlap=overlap_fraction(aa, bb))
    return aa, bb, grid, check


def test_no_change_background_offset_and_mask():
    for change in (None, 'bad'):
        r = detect_changes(*pair(change), EVIDENCE)
        assert r['status'] == 'screened'
        assert r['candidates'] == []
        assert abs(r['statistics']['background_offset'] - 7) < .1


@pytest.mark.parametrize('kind,xy', [('bright', (45, 50)), ('transient', (65, 60))])
def test_injected_residual_location_and_amplitude(kind, xy):
    r = detect_changes(*pair(kind), EVIDENCE)
    assert len(r['candidates']) == 1
    c = r['candidates'][0]
    assert np.hypot(c['x']-xy[0], c['y']-xy[1]) < .6
    assert abs(c['peak_residual'] - 25) < 4
    assert c['uncertainty'] is None
    assert c['empirical_score'] > 6


def test_motion_is_two_residuals_not_a_motion_measurement():
    r = detect_changes(*pair('moving'), EVIDENCE)
    assert len(r['candidates']) == 2
    assert {np.sign(c['peak_residual']) for c in r['candidates']} == {-1, 1}
    assert all('angular_rate' not in c for c in r['candidates'])


def test_wcs_shift_stationary_sources():
    a, b, grid, check = pair(shift=2)
    assert check.difference_allowed
    assert np.hypot(*(np.array(np.unravel_index(np.nanargmax(a.data), a.data.shape)) -
                       np.array(np.unravel_index(np.nanargmax(b.data), b.data.shape)))) <= 1
    assert detect_changes(a, b, grid, check, EVIDENCE)['candidates'] == []


@pytest.mark.parametrize('field', ['calibration_verified', 'psf_verified', 'registration_verified', 'spatial_spectral_response_verified'])
def test_missing_scientific_evidence_blocks(field):
    values = dict(units='MJy/sr', calibration_verified=True, psf_verified=True,
                  registration_verified=True, spatial_spectral_response_verified=True)
    values[field] = False
    result = detect_changes(*pair('transient'), DetectionEvidence(**values))
    assert result['status'] == 'unavailable'
    assert not result['candidates']


def test_spectral_and_overlap_failure():
    a, b, grid, _ = pair('transient')
    b.frame.wavelength_um = 2.
    for overlap in (0, 1):
        check = validate(a.frame, b.frame, 'time', overlap=overlap)
        assert detect_changes(a, b, grid, check, EVIDENCE)['status'] == 'unavailable'


def test_noise_change_has_no_candidates():
    a, b, grid, check = pair()
    b.data += np.random.default_rng(92).normal(0, 4, b.data.shape)
    assert detect_changes(a, b, grid, check, EVIDENCE)['candidates'] == []


def test_psf_mismatch_and_saturation_require_evidence():
    from scipy.ndimage import gaussian_filter
    a, b, grid, check = pair()
    b.data = gaussian_filter(b.data, 2)
    b.data[50, 45] = 1e8
    result = detect_changes(a, b, grid, check)
    assert result['status'] == 'unavailable'
    assert not result['candidates']
