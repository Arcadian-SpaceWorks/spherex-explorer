"""TEST DATA: every FITS file here is synthetic, generated in the test. No real observations.

Covers the pure comparison module: loading, the common grid, alignment, masks, validation rules,
the difference image and recovery of an injected point source at the right sky position.
"""
import math

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS

from backend.app.analysis.compare import (
    ComparisonNotAllowed, Frame, FrameError, align, common_grid, cutout_size_for_grid, difference,
    load_frame, overlap_fraction, validate,
)

RA, DEC, SIZE = 10.6847, 41.2687, 0.3
SCALE = 6.15
TARGET = SkyCoord(RA * u.deg, DEC * u.deg)
# Synthetic "stars" (TEST DATA), given as sky offsets in arcsec (east, north) from the target.
STARS = [(0, 0, 400.), (-180, 120, 150.), (240, -90, 120.), (60, 300, 90.), (-300, -260, 110.)]
SIGMA_ARCSEC = 9.0  # About 1.5 pixels.
# An extended, galaxy-like core at the target (sigma 90 arcsec), as in M31.
GALAXY_CORE = (0, 0, 60., 90.)


def star_coords(stars):
    return [(TARGET.spherical_offsets_by(star[0] * u.arcsec, star[1] * u.arcsec), star[2],
             star[3] if len(star) > 3 else SIGMA_ARCSEC) for star in stars]


def detector_wcs(shape, rotation_deg=0.0, shift_px=(0.0, 0.0)):
    """Detector-like TAN WCS with the target near (not at) the image centre."""
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ['RA---TAN', 'DEC--TAN']
    wcs.wcs.crval = [RA, DEC]
    wcs.wcs.crpix = [(shape[1] + 1) / 2 + shift_px[0], (shape[0] + 1) / 2 + shift_px[1]]
    theta = math.radians(rotation_deg)
    step = SCALE / 3600
    wcs.wcs.cd = [[-step * math.cos(theta), step * math.sin(theta)],
                  [step * math.sin(theta), step * math.cos(theta)]]
    wcs.wcs.radesys = 'ICRS'
    return wcs


def render(wcs, shape, stars=STARS, background=2.0):
    ys, xs = np.mgrid[0:shape[0], 0:shape[1]]
    sky = wcs.pixel_to_world(xs, ys)
    image = np.full(shape, background)
    for coord, amplitude, sigma in star_coords(stars):
        separation = sky.separation(coord).arcsec
        image += amplitude * np.exp(-separation ** 2 / (2 * sigma ** 2))
    return image


def write_frame(path, wcs, data, *, detector=1, date='2026-01-01T00:00:00', obs_id='TEST-DATA-A',
                wavelength=0.895, bandwidth=0.01, flags=None, zodi=None):
    """Write a SPHEREx-like multi-extension FITS file (TEST DATA)."""
    primary = fits.PrimaryHDU()
    primary.header['ORIGIN'] = 'TEST DATA (synthetic)'
    image = fits.ImageHDU(data=data.astype(np.float32), name='IMAGE')
    image.header.update(wcs.to_header())
    image.header.update({'BUNIT': 'MJy/sr', 'DETECTOR': detector, 'DATE-OBS': date,
                         'TIMESYS': 'UTC', 'OBSID': obs_id})
    hdus = [primary, image,
            fits.ImageHDU(data=np.zeros(data.shape, np.int32) if flags is None else flags, name='FLAGS'),
            fits.ImageHDU(data=np.full(data.shape, .15, np.float32) if zodi is None else zodi, name='ZODI')]
    if wavelength is not None:
        ny, nx = data.shape
        values = np.array([[[wavelength, bandwidth]] * 2] * 2)
        hdus.append(fits.BinTableHDU.from_columns([
            fits.Column(name='X', format='2D', array=[[1., nx]]),
            fits.Column(name='Y', format='2D', array=[[1., ny]]),
            fits.Column(name='VALUES', format='8D', dim='(2,2,2)', array=[values])], name='WCS-WAVE'))
        for axis, ctype, column in [(1, 'WAVE-TAB', 'X'), (2, 'BAND-TAB', 'Y')]:
            image.header.update({f'CTYPE{axis}W': ctype, f'CUNIT{axis}W': 'um', f'CRPIX{axis}W': 1.,
                                 f'CRVAL{axis}W': 1., f'CDELT{axis}W': 1., f'PS{axis}_0W': 'WCS-WAVE',
                                 f'PS{axis}_1W': 'VALUES', f'PS{axis}_2W': column, f'PV{axis}_1W': 1,
                                 f'PV{axis}_3W': axis})
        image.header['WCSAXESW'] = 2
    fits.HDUList(hdus).writeto(path)
    return path


def make_file(tmp_path, name, *, shape=(300, 300), rotation=0.0, shift=(0.0, 0.0), stars=STARS, **kwargs):
    wcs = detector_wcs(shape, rotation, shift)
    data = kwargs.pop('data', None)
    return write_frame(tmp_path / name, wcs, render(wcs, shape, stars) if data is None else data, **kwargs)


def load(path, size=None):
    return load_frame(path, RA, DEC, size or cutout_size_for_grid(SIZE), source='test_data')


def grid_pixel(grid, coord):
    return tuple(float(value) for value in grid.wcs.world_to_pixel(coord))


def centroid(image, x, y, half=4):
    xi, yi = int(round(x)), int(round(y))
    box = image[yi - half:yi + half + 1, xi - half:xi + half + 1]
    weights = np.clip(box - np.nanmedian(image), 0, None)
    ys, xs = np.mgrid[yi - half:yi + half + 1, xi - half:xi + half + 1]
    return float((weights * xs).sum() / weights.sum()), float((weights * ys).sum() / weights.sum())


def test_common_grid_is_north_up_and_centred_on_the_target():
    grid = common_grid(RA, DEC, SIZE)
    assert grid.shape == (176, 176)  # 0.3 deg at 6.15 arcsec, the size of real SPHEREx cutouts.
    centre = (np.array(grid.shape) - 1) / 2
    assert grid.wcs.pixel_to_world(*centre).separation(TARGET).arcsec < 1e-6
    north = grid.wcs.pixel_to_world(centre[1], centre[0] + 10)
    east = grid.wcs.pixel_to_world(centre[1] - 10, centre[0])
    assert north.dec.deg > DEC and abs(north.ra.deg - RA) < 1e-9
    assert east.ra.deg > RA
    assert grid.summary()['north_up'] is True
    with pytest.raises(ValueError):
        common_grid(RA, DEC, 0)


def test_load_frame_cuts_a_full_file_and_reads_identity_wavelength_and_diagnostics(tmp_path):
    path = make_file(tmp_path, 'full.fits', shape=(400, 400), shift=(30, -20), detector=1,
                     date='2026-01-01T06:00:00', obs_id='TEST-DATA-FULL', wavelength=0.895)
    frame = load_frame(path, RA, DEC, SIZE, source='local_cutout')
    assert frame.data.shape in {(175, 175), (176, 176), (177, 177)}  # Cut locally from the 400 px file.
    assert frame.band == 'SPHEREx-D1' and frame.obs_id == 'TEST-DATA-FULL'
    assert frame.observed_at_utc.startswith('2026-01-01T06:00:00')
    assert frame.wavelength_um == pytest.approx(0.895) and frame.bandwidth_um == pytest.approx(0.01)
    assert frame.diagnostics['zodi_median'] == pytest.approx(0.15)
    assert frame.diagnostics['core_median'] > frame.diagnostics['sky_level'] >= 2.0
    assert frame.provenance['source'] == 'local_cutout' and len(frame.provenance['sha256']) == 64
    tx, ty = frame.target_pixel
    assert frame.wcs.pixel_to_world(tx, ty).separation(TARGET).arcsec < .01


def test_load_frame_rejects_a_target_outside_the_image(tmp_path):
    wcs = detector_wcs((100, 100))
    wcs.wcs.crval = [RA + 5, DEC]
    path = write_frame(tmp_path / 'elsewhere.fits', wcs, np.ones((100, 100)))
    with pytest.raises(FrameError) as error:
        load(path)
    assert error.value.code == 'target_outside'


def test_missing_spectral_wcs_gives_unknown_wavelength_not_a_guess(tmp_path):
    frame = load(make_file(tmp_path, 'nowave.fits', wavelength=None))
    assert frame.wavelength_um is None and frame.provenance['wavelength_source'] is None


@pytest.mark.parametrize('rotation, shift', [(0.0, (3.4, -2.7)), (35.0, (-6.2, 4.9)), (-62.0, (11.3, 8.1))])
def test_rotated_and_shifted_frames_align_to_under_half_a_pixel(tmp_path, rotation, shift):
    frame = load(make_file(tmp_path, 'rot.fits', rotation=rotation, shift=shift))
    grid = common_grid(RA, DEC, SIZE)
    (aligned,) = align([frame], grid)
    for coord, _, _ in star_coords(STARS):
        expected = grid_pixel(grid, coord)
        measured = centroid(aligned.data, *expected)
        assert math.dist(measured, expected) < 0.5


def test_rotated_cutout_needs_the_cover_margin_to_fill_the_grid(tmp_path):
    path = make_file(tmp_path, 'rot45.fits', rotation=45.0)
    grid = common_grid(RA, DEC, SIZE)
    with_margin, = align([load(path)], grid)
    exact, = align([load(path, size=SIZE)], grid)
    assert with_margin.valid.mean() > .99
    assert exact.valid.mean() < .9  # A rotated 0.3 deg cutout leaves the grid corners empty.


def test_nan_edges_and_flagged_pixels_are_masked_not_interpolated(tmp_path):
    shape = (300, 300)
    wcs = detector_wcs(shape, 20.0)
    data = render(wcs, shape)
    data[:, :110] = np.nan  # Empty detector edge.
    flags = np.zeros(shape, np.int32)
    flags[150:156, 150:156] = 1 << 6  # NONFUNC block next to the target.
    frame = load(write_frame(tmp_path / 'edges.fits', wcs, data, flags=flags))
    grid = common_grid(RA, DEC, SIZE)
    (aligned,) = align([frame], grid)
    assert np.isfinite(aligned.data[aligned.valid]).all()
    assert np.isnan(aligned.data[~aligned.valid]).all()
    assert .2 < aligned.valid.mean() < .9
    flagged_sky = wcs.pixel_to_world(152.5, 152.5)
    fx, fy = (int(round(v)) for v in grid_pixel(grid, flagged_sky))
    assert not aligned.valid[fy, fx]
    edge_sky = wcs.pixel_to_world(50, 150)
    ex, ey = (int(round(v)) for v in grid_pixel(grid, edge_sky))
    if 0 <= ex < grid.shape[1] and 0 <= ey < grid.shape[0]:
        assert not aligned.valid[ey, ex]


def fake_frame(*, detector=1, mjd=61040.0, wavelength=0.895, obs_id='TEST-DATA-A'):
    return Frame(data=np.zeros((2, 2)), valid=np.ones((2, 2), bool), wcs=WCS(naxis=2), target_pixel=(0, 0),
                 obs_id=obs_id, detector=detector, observed_at_utc=None, mjd=mjd,
                 wavelength_um=wavelength, bandwidth_um=None)


DAY = 1.0


@pytest.mark.parametrize('b, mode, overlap, decision, codes', [
    (dict(mjd=61040 + 190 * DAY, wavelength=0.893, obs_id='TEST-DATA-B'), 'time', .97, 'ACCEPT', {'wavelength_match'}),
    (dict(mjd=61040 + 0.5 / 24, wavelength=0.895, obs_id='TEST-DATA-B'), 'time', .97, 'REJECT', {'too_close_in_time'}),
    (dict(mjd=61040 - 175 * DAY, wavelength=0.750, obs_id='TEST-DATA-B'), 'time', .97, 'WARN', {'wavelength_mismatch'}),
    (dict(mjd=61040 + 190 * DAY, wavelength=0.893, obs_id='TEST-DATA-B'), 'time', .80, 'REJECT', {'low_overlap'}),
    (dict(mjd=61040 + 190 * DAY, wavelength=0.893, obs_id='TEST-DATA-B'), 'time', 0.0, 'REJECT', {'no_overlap'}),
    (dict(detector=4, mjd=61040 + 190 * DAY, wavelength=2.98, obs_id='TEST-DATA-B'), 'time', .97, 'REJECT', {'band_mismatch'}),
    (dict(mjd=61040 + 190 * DAY, wavelength=None, obs_id='TEST-DATA-B'), 'time', .97, 'WARN', {'wavelength_unknown'}),
    (dict(mjd=61040 + 190 * DAY, wavelength=0.893, obs_id='TEST-DATA-B'), 'time', None, 'WARN', {'overlap_not_measured'}),
    (dict(mjd=None, wavelength=0.893, obs_id='TEST-DATA-B'), 'time', .97, 'REJECT', {'time_unknown'}),
    (dict(detector=4, wavelength=2.98), 'wavelength', .95, 'ACCEPT', {'no_cross_wavelength_difference'}),
    (dict(detector=4, mjd=61040 + 2 * DAY, wavelength=2.98, obs_id='TEST-DATA-B'), 'wavelength', .95, 'REJECT', {'not_simultaneous'}),
    (dict(detector=2, wavelength=0.90), 'wavelength', .95, 'REJECT', {'same_wavelength'}),
    (dict(detector=4, wavelength=2.98), 'wavelength', .70, 'WARN', {'low_overlap'}),
])
def test_validation_rules(b, mode, overlap, decision, codes):
    result = validate(fake_frame(), fake_frame(**b), mode, overlap=overlap)
    assert result.decision == decision
    assert codes <= {reason.code for reason in result.reasons}
    assert result.difference_allowed == (mode == 'time' and decision == 'ACCEPT')
    payload = result.to_dict()
    assert payload['decision'] == decision and all({'code', 'severity', 'detail', 'values'} <= set(r) for r in payload['reasons'])


def test_validation_rejects_unknown_mode():
    with pytest.raises(ValueError):
        validate(fake_frame(), fake_frame(), 'motion')


def aligned_pair(tmp_path, data_b=None, *, rotation_b=25.0, stars=STARS, stars_b=None, noise=0.0):
    shape = (300, 300)
    rng = np.random.default_rng(31)  # Seeded TEST DATA noise.
    wcs_a = detector_wcs(shape, 0.0, (2.2, -1.6))
    path_a = write_frame(tmp_path / 'a.fits', wcs_a, render(wcs_a, shape, stars) + rng.normal(0, noise, shape),
                         obs_id='TEST-DATA-A', date='2026-01-01T00:00:00')
    stars_b = stars if stars_b is None else stars_b
    wcs_b = detector_wcs(shape, rotation_b, (-3.1, 4.4))
    data = render(wcs_b, shape, stars_b) if data_b is None else data_b(wcs_b)
    path_b = write_frame(tmp_path / 'b.fits', wcs_b, data + rng.normal(0, noise, shape),
                         obs_id='TEST-DATA-B', date='2026-07-10T00:00:00', wavelength=0.893)
    grid = common_grid(RA, DEC, SIZE)
    a, b = align([load(path_a), load(path_b)], grid)
    check = validate(a.frame, b.frame, 'time', overlap=overlap_fraction(a, b))
    return grid, a, b, check


def test_identical_frames_give_a_zero_difference(tmp_path):
    shape = (300, 300)
    wcs = detector_wcs(shape, 30.0, (1.7, -2.3))
    data = render(wcs, shape)
    paths = [write_frame(tmp_path / f'{name}.fits', wcs, data, obs_id=f'TEST-DATA-{name}', date=date)
             for name, date in [('A', '2026-01-01T00:00:00'), ('B', '2026-07-10T00:00:00')]]
    grid = common_grid(RA, DEC, SIZE)
    a, b = align([load(path) for path in paths], grid)
    check = validate(a.frame, b.frame, 'time', overlap=overlap_fraction(a, b))
    assert check.decision == 'ACCEPT', check.to_dict()
    result = difference(a, b, check)
    assert np.nanmax(np.abs(result.data)) < 1e-9 * np.nanmax(a.data)
    assert result.robust_noise == 0 and result.offset == 0


def test_same_sky_at_a_different_pointing_leaves_only_interpolation_residuals(tmp_path):
    grid, a, b, check = aligned_pair(tmp_path)
    assert check.decision == 'ACCEPT', check.to_dict()
    result = difference(a, b, check)
    peak = np.nanmax(a.data)
    # Bilinear resampling of a ~1.5 px wide star at two rotations differs by a few percent at its
    # peak. This bounds what a difference image can show without a real change in the sky.
    assert np.nanmax(np.abs(result.data)) < .06 * peak
    assert result.robust_noise < 1e-3 * peak
    assert result.overlap_fraction > .99


def test_background_offset_and_scale_are_removed(tmp_path):
    scene = STARS + [GALAXY_CORE]
    grid, a, b, check = aligned_pair(tmp_path, lambda wcs: 1.3 * render(wcs, (300, 300), scene) + 5.0, stars=scene)
    plain = difference(a, b, check)
    matched = difference(a, b, check, match_scale=True)
    assert matched.scale_matched and matched.scale == pytest.approx(1.3, rel=.02)
    assert np.nanmax(np.abs(matched.data)) < .2 * np.nanmax(np.abs(plain.data))
    assert plain.scale == 1.0 and not plain.scale_matched


def test_difference_is_refused_unless_the_pair_is_accepted():
    for b, mode in [(dict(wavelength=0.75, mjd=61200), 'time'), (dict(detector=4, wavelength=2.98), 'wavelength')]:
        check = validate(fake_frame(), fake_frame(**b), mode, overlap=.97)
        with pytest.raises(ComparisonNotAllowed):
            difference(None, None, check)


def test_injected_point_source_is_found_at_the_right_sky_position(tmp_path):
    injected = (150.0, -110.0, 300.0)  # TEST DATA: a source present only in frame B.
    grid, a, b, check = aligned_pair(tmp_path, stars_b=STARS + [injected], noise=1.0)
    result = difference(a, b, check)
    assert .5 < result.robust_noise < 2  # Noise of two resampled frames, not zero.
    y, x = np.unravel_index(np.nanargmax(result.data), result.data.shape)
    found = grid.wcs.pixel_to_world(x, y)
    expected = TARGET.spherical_offsets_by(injected[0] * u.arcsec, injected[1] * u.arcsec)
    assert found.separation(expected).arcsec < SCALE  # Within one grid pixel.
    assert result.data[y, x] > 20 * result.robust_noise
