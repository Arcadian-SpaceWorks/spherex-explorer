"""Spectrum engine tests. No network: remote exposures are synthetic files served by a fake
range-request session; archive answers are injected. Synthetic data never reaches the app."""
import math
import time

import numpy as np
import pytest
import requests
from astropy.io import fits
from astropy.wcs import WCS
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.spectrum import analysis, archive, moving, photometry, remote
from backend.app.spectrum.api import get_spectrum_service
from backend.app.spectrum.service import SpectrumService

RA, DEC = 150.0, 20.0
SIZE = 120
PIXEL_SR = (6.15 / 206264.806) ** 2
URI = 'ibe/data/spherex/qr2/level2/2025W30_1A/l2b-v1/3/level2_2025W30_1A_0001_1D3_spx_l2b-v1.fits'


def star(shape, x, y, flux_mjy, sigma=0.9):
    """Gaussian source of a known total flux, as surface brightness in MJy/sr."""
    yy, xx = np.indices(shape, dtype=float)
    profile = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2))
    return profile / profile.sum() * flux_mjy / (PIXEL_SR * 1e9)


def exposure_bytes(flux_mjy=20.0, background=0.4, compress_flags=False, flags=None, rng_seed=1):
    """A file with the HDU order and keywords of a real Level 2 product (small detector)."""
    rng = np.random.default_rng(rng_seed)
    wcs = WCS(naxis=2)
    wcs.wcs.ctype, wcs.wcs.crpix, wcs.wcs.crval = ['RA---TAN', 'DEC--TAN'], [60.3, 61.7], [RA, DEC]
    wcs.wcs.cdelt = [-6.15 / 3600, 6.15 / 3600]
    x, y = wcs.all_world2pix([[RA, DEC]], 0)[0]
    noise = 0.004
    data = (background + star((SIZE, SIZE), x, y, flux_mjy) + rng.normal(0, noise, (SIZE, SIZE))).astype('>f4')
    science = fits.ImageHDU(data=data, name='IMAGE')
    science.header.update(wcs.to_header())
    science.header.update({'BUNIT': 'MJy / sr', 'DETECTOR': 3, 'OBSID': '2025W30_1A_0001_1', 'MJD-OBS': 60880.5})
    for key, value in {'WCSAXESW': 2, 'CRPIX1W': 1.0, 'CRPIX2W': 1.0, 'CDELT1W': 1, 'CDELT2W': 1, 'CUNIT1W': 'um', 'CUNIT2W': 'um',
                       'CTYPE1W': 'WAVE-TAB', 'CTYPE2W': 'WAVE-TAB', 'CRVAL1W': 1, 'CRVAL2W': 1, 'PV1_3W': 1, 'PV2_3W': 2,
                       'PS1_0W': 'WCS-WAVE', 'PS2_0W': 'WCS-WAVE', 'PS1_1W': 'VALUES', 'PS2_1W': 'VALUES',
                       'PS1_2W': 'X', 'PS2_2W': 'Y'}.items():
        science.header[key] = value
    flag_data = np.zeros((SIZE, SIZE), dtype=np.int32) if flags is None else flags
    flag_hdu = (fits.CompImageHDU(data=flag_data, name='FLAGS', compression_type='RICE_1', tile_shape=(1, SIZE))
                if compress_flags else fits.ImageHDU(data=flag_data, name='FLAGS'))
    nodes = np.array([1, SIZE], dtype=np.int32)
    values = np.zeros((2, 2, 2), dtype=np.float32)  # [y, x, (wavelength, bandwidth)]: wavelength rises with y
    values[0, :, 0], values[1, :, 0], values[:, :, 1] = 2.0, 2.4, 0.05
    wave = fits.BinTableHDU.from_columns([fits.Column('X', '2J', dim='(2)', array=[nodes]), fits.Column('Y', '2J', dim='(2)', array=[nodes]),
                                          fits.Column('VALUES', '8E', dim='(2,2,2)', array=[values])], name='WCS-WAVE')
    hdul = fits.HDUList([fits.PrimaryHDU(), science, flag_hdu,
                         fits.ImageHDU(data=np.full((SIZE, SIZE), noise ** 2, dtype='>f4'), name='VARIANCE'),
                         fits.ImageHDU(data=np.full((SIZE, SIZE), background, dtype='>f4'), name='ZODI'),
                         fits.ImageHDU(data=np.zeros((2, 5, 5), dtype='>f4'), name='PSF'), wave])
    import io
    buffer = io.BytesIO()
    hdul.writeto(buffer)
    return buffer.getvalue(), (float(x), float(y))


class RangeSession:
    """Answers HTTP range requests from in-memory files, like the S3 mirror."""

    def __init__(self, files):
        self.files, self.requests, self.bytes = files, 0, 0

    def get(self, url, headers, timeout, allow_redirects):
        assert allow_redirects is False and url.startswith(remote.MIRROR)
        self.requests += 1
        body = self.files.get(url)
        response = requests.Response()
        if body is None:
            response.status_code = 404
            return response
        spec = headers['Range'].removeprefix('bytes=')
        if spec.startswith('-'):
            start, stop = len(body) - int(spec[1:]), len(body)
        else:
            start, stop = (int(part) for part in spec.split('-'))
            stop = min(stop + 1, len(body))
        response.status_code, response._content = 206, body[start:stop]
        response.headers['Content-Range'] = f'bytes {start}-{stop - 1}/{len(body)}'
        self.bytes += stop - start
        return response


# -- photometry ---------------------------------------------------------------------------------

def test_aperture_recovers_a_known_flux_and_ignores_bad_pixels_outside_the_aperture():
    image = 0.4 + star((9, 27), 13.2, 4.1, 20.0)
    image[0, 0] = np.nan  # Far from the aperture: must not poison the sum.
    result = photometry.measure(image, np.full(image.shape, 1e-6), None, 13.2, 4.1, PIXEL_SR)
    assert result['status'] == 'ok'
    inside = 1 - math.exp(-2.5 ** 2 / (2 * 0.9 ** 2))  # Fraction of this Gaussian inside 2.5 px: no aperture correction
    assert result['flux_mjy'] == pytest.approx(20.0 * inside, rel=0.02)
    assert result['background_mjy_sr'] == pytest.approx(0.4, abs=1e-3) and result['flux_err_mjy'] > 0


def noisy(image, seed=3):
    return image + np.random.default_rng(seed).normal(0, 0.002, image.shape)


def test_flagged_saturated_and_edge_measurements_give_no_flux():
    image = noisy(0.4 + star((9, 27), 13, 4, 20.0))
    flags = np.zeros(image.shape, dtype=np.int32)
    flags[4, 13] = 1 << 1  # OVERFLOW in the aperture
    assert photometry.measure(image, None, flags, 13, 4, PIXEL_SR) == {'flags': 2, 'flag_names': ['OVERFLOW'], 'status': 'saturated'}
    flags[4, 13] = 1 << 0
    assert photometry.measure(image, None, flags, 13, 4, PIXEL_SR)['status'] == 'flagged'
    assert photometry.measure(image, None, None, 3, 4, PIXEL_SR) == {'status': 'edge'}
    flags[4, 13] = 1 << 19  # OUTLIER marks moving and changing sources: kept, but named
    kept = photometry.measure(image, None, flags, 13, 4, PIXEL_SR)
    assert kept['status'] == 'ok' and kept['flag_names'] == ['OUTLIER'] and kept['error_source'] == 'sky_scatter'


def test_source_flag_does_not_remove_the_background_in_crowded_fields():
    image = noisy(0.4 + star((9, 27), 13, 4, 5.0))
    flags = np.full(image.shape, 1 << 21, dtype=np.int32)
    assert photometry.measure(image, None, flags, 13, 4, PIXEL_SR)['status'] == 'ok'


# -- remote range reads -------------------------------------------------------------------------

@pytest.mark.parametrize('compress_flags', [False, True])
def test_remote_measurement_matches_the_whole_file_and_reads_little(compress_flags):
    flags = np.zeros((SIZE, SIZE), dtype=np.int32)
    flags[5, 5] = 1 << 6
    body, (x, y) = exposure_bytes(compress_flags=compress_flags, flags=flags)
    session = RangeSession({remote.mirror_url(URI): body})
    result = remote.measure_remote(session, URI, RA, DEC)
    with fits.open(__import__('io').BytesIO(body)) as hdul:
        local = photometry.measure_hdul(hdul, RA, DEC)
    assert result['status'] == 'ok' and result['flux_mjy'] == pytest.approx(20.0, rel=0.04)
    for key in ('flux_mjy', 'flux_err_mjy', 'wavelength_um', 'bandwidth_um', 'x', 'y'):
        assert result[key] == pytest.approx(local[key], rel=1e-6)
    assert result['wavelength_um'] == pytest.approx(2.0 + 0.4 * y / (SIZE - 1), abs=1e-3)
    assert (result['obs_id'], result['detector'], result['mjd']) == ('2025W30_1A_0001_1', 3, 60880.5)
    assert result['bytes_read'] == session.bytes < len(body)


def test_remote_flags_are_honoured_through_the_compressed_reader():
    flags = np.zeros((SIZE, SIZE), dtype=np.int32)
    body, (x, y) = exposure_bytes()
    flags[int(round(y)), int(round(x))] = 1 << 1
    body, _ = exposure_bytes(compress_flags=True, flags=flags)
    result = remote.measure_remote(RangeSession({remote.mirror_url(URI): body}), URI, RA, DEC)
    assert result['status'] == 'saturated' and 'flux_mjy' not in result


def test_remote_reports_positions_off_the_detector_and_missing_files():
    body, _ = exposure_bytes()
    session = RangeSession({remote.mirror_url(URI): body})
    assert remote.measure_remote(session, URI, RA + 5, DEC)['status'] == 'outside'
    with pytest.raises(remote.RemoteError):
        remote.measure_remote(RangeSession({}), URI, RA, DEC)


@pytest.mark.parametrize('uri', ['', 'https://example.org/x.fits', 'ibe/data/spherex/qr2/level2/../../secret.fits',
                                 'ibe/data/wise/x.fits', 'ibe/data/spherex/qr2/level1/a.fits'])
def test_only_archive_level2_paths_are_read(uri):
    with pytest.raises(remote.RemoteError):
        remote.mirror_url(uri)


def test_unexpected_extension_order_is_refused_not_guessed():
    body, _ = exposure_bytes()
    with fits.open(__import__('io').BytesIO(body)) as hdul:
        swapped = fits.HDUList([hdul[0], hdul[1], hdul[3], hdul[2], hdul[4], hdul[5], hdul[6]])
        import io
        buffer = io.BytesIO()
        swapped.writeto(buffer)
    with pytest.raises(remote.RemoteError):
        remote.measure_remote(RangeSession({remote.mirror_url(URI): buffer.getvalue()}), URI, RA, DEC)


# -- analysis -----------------------------------------------------------------------------------

def spectrum(shape=lambda w: 1.0, mjd=60900.0, level=10.0, noise=0.01, seed=0, step=0.012):
    rng = np.random.default_rng(seed)
    points = []
    for detector, low, high in ((1, 0.75, 1.11), (2, 1.11, 1.64), (3, 1.64, 2.42), (4, 2.42, 3.82), (5, 3.82, 4.42), (6, 4.42, 5.0)):
        for index, wavelength in enumerate(np.arange(low + 0.004, high, step)):
            flux = level * shape(wavelength) * (1 + rng.normal(0, noise))
            points.append({'status': 'ok', 'wavelength_um': float(wavelength), 'flux_mjy': float(flux), 'flux_err_mjy': level * noise,
                           'detector': detector, 'mjd': mjd + index * 0.01})
    return points


def by_id(results):
    return {item['id']: item for item in results}


def test_ice_bands_are_measured_and_a_featureless_spectrum_reports_nothing():
    def icy(wavelength):
        return 1 - 0.5 * math.exp(-((wavelength - 4.27) / 0.03) ** 2) - 0.4 * math.exp(-((wavelength - 3.05) / 0.12) ** 2)
    found = by_id(analysis.measure_features(spectrum(icy)))
    assert found['co2']['status'] == 'detected' and found['co2']['kind'] == 'absorption'
    assert found['co2']['optical_depth'] == pytest.approx(-math.log(1 - 0.37), abs=0.2)
    assert found['h2o_ice']['status'] == 'detected' and found['h2o_ice']['strength'] == pytest.approx(0.33, abs=0.08)
    assert 'co_gas' not in found and 'h2o_gas' not in found  # comet gas is not tested on fixed sources
    flat = analysis.measure_features(spectrum())
    assert [item['status'] for item in flat] == ['not_detected'] * len(flat)


def test_a_band_that_bottoms_out_gives_a_lower_limit_on_optical_depth():
    result = by_id(analysis.measure_features(spectrum(lambda w: 1e-4 if 2.85 < w < 3.3 else 1.0)))['h2o_ice']
    assert result['status'] == 'detected' and result['optical_depth_is_lower_limit'] is True
    assert result['optical_depth'] == pytest.approx(-math.log(0.02), abs=0.01)


def test_a_line_in_a_side_window_does_not_fake_absorption():
    # A redshifted emission line at 4.38 µm (inside CO2's right continuum window), as in a z = 1.34 quasar.
    result = by_id(analysis.measure_features(spectrum(lambda w: 1 + 0.6 * math.exp(-((w - 4.385) / 0.03) ** 2))))['co2']
    assert result['status'] == 'not_detected' and result['stands_out_from_both_sides'] is False


def test_one_contaminated_exposure_cannot_create_a_band():
    points = spectrum()
    core = [point for point in points if 1.262 <= point['wavelength_um'] <= 1.302]
    core[0]['flux_mjy'] *= 30  # A background star under a moving target, or a cosmic ray.
    assert by_id(analysis.measure_features(points))['pa_beta']['status'] == 'not_detected'


def test_comets_are_tested_for_gas_emission_only():
    def comet(wavelength):
        return 1 + 40 * math.exp(-((wavelength - 4.26) / 0.035) ** 2) + 2 * math.exp(-((wavelength - 4.67) / 0.07) ** 2)
    found = by_id(analysis.measure_features(spectrum(comet), moving=True))
    assert set(found) == {'co2', 'co_gas', 'h2o_gas'}
    assert found['co2']['kind'] == found['co_gas']['kind'] == 'emission' and found['h2o_gas']['status'] == 'not_detected'


def test_too_few_exposures_is_not_measurable_rather_than_absent():
    sparse = [point for point in spectrum() if not 4.2 < point['wavelength_um'] < 4.33]
    assert by_id(analysis.measure_features(sparse))['co2']['status'] == 'not_measurable'


def test_seasons_and_brightness_change_are_compared_at_matching_wavelengths():
    red = lambda wavelength: wavelength ** 2  # A steep spectrum must not look like variability.
    steady = spectrum(red, 60900, seed=1) + spectrum(red, 61080, seed=2)
    summary = analysis.summarise(steady)
    assert [season['measured'] for season in summary['seasons']] == [len(steady) // 2] * 2
    assert summary['variability']['status'] == 'steady' and summary['variability']['amplitude'] < 0.02
    assert summary['features'] and summary['binned'] and not summary['mixed_seasons']
    icy = lambda wavelength: red(wavelength) * (1 - 0.5 * math.exp(-((wavelength - 4.27) / 0.03) ** 2))
    changed = spectrum(icy, 60900, seed=1) + spectrum(icy, 61080, level=13.0, seed=2)
    summary = analysis.summarise(changed)
    change = summary['variability']
    assert change['status'] == 'variable' and change['amplitude'] == pytest.approx(0.3, abs=0.03)
    # A moderate change: seasons are scaled to the reference season, then analysed together.
    assert summary['seasons_scaled'] and not summary['mixed_seasons'] and len(summary['features_by_season']) == 2
    assert by_id(summary['features'])['co2']['status'] == 'detected' and by_id(summary['features'])['co2']['strength'] == pytest.approx(0.3, abs=0.1)
    assert {point['flux_mjy'] for point in changed} == {point['flux_mjy'] for point in spectrum(icy, 60900, seed=1) + spectrum(icy, 61080, level=13.0, seed=2)}
    # A large change: the mixed spectrum is withheld and each season stands alone.
    summary = analysis.summarise(spectrum(red, 60900, seed=1) + spectrum(red, 61080, level=40.0, seed=2))
    assert summary['mixed_seasons'] and summary['features'] == [] and summary['binned'] == [] and not summary['seasons_scaled']


def test_summary_counts_rejections_and_handles_no_usable_points():
    points = [{'status': 'saturated', 'mjd': 60900.0}, {'status': 'flagged', 'mjd': 60900.1}]
    summary = analysis.summarise(points)
    assert summary['counts'] == {'saturated': 1, 'flagged': 1} and 'median_snr' not in summary
    assert summary['variability']['status'] == 'not_measurable'


# -- archive helpers ----------------------------------------------------------------------------

def test_archive_rows_are_validated_and_deep_fields_are_sampled_evenly():
    did = 'ivo://irsa.ipac/spherex_qr2?2025W30_1A_0001_1/D3'
    row = {'uri': URI, 'obs_publisher_did': did, 'energy_bandpassname': 'SPHEREx-D3', 'time_bounds_lower': '60880.5'}
    item = archive.exposure(row, RA, DEC)
    assert (item['obs_id'], item['collection'], item['band'], item['t_min']) == ('2025W30_1A_0001_1', 'spherex_qr2', 'SPHEREx-D3', 60880.5)
    assert archive.exposure({**row, 'uri': 'https://example.org/evil.fits'}, RA, DEC) is None
    assert archive.exposure({**row, 'obs_publisher_did': "x' OR 1=1"}, RA, DEC) is None
    many = [{**item, 'band': f'SPHEREx-D{1 + index % 6}', 't_min': 60000 + index, 'uri': f'{index}'} for index in range(6000)]
    chosen, truncated = archive.subsample(many, 600)
    assert truncated and len(chosen) == 600 and {entry['band'] for entry in chosen} == {f'SPHEREx-D{n}' for n in range(1, 7)}
    assert chosen[0]['t_min'] < 60010 and chosen[-1]['t_min'] > 65990
    assert archive.subsample(many[:10], 600) == (many[:10], False)
    with pytest.raises(ValueError):
        archive.exposures_at(float('nan'), 0)


def test_comet_exposures_use_the_official_positions_and_archive_paths():
    exposures = moving.comet_exposures(lookup=lambda missing: [])
    rows = moving.comet_rows()
    assert len(rows) == 259 and 0 < len(exposures) <= len(rows)
    first = exposures[0]
    assert (first['ra'], first['dec']) == rows[first['obs_publisher_did']][:2] and remote.URI.match(first['uri'])
    assert first['obs_id'] in first['uri']


# -- service and API ----------------------------------------------------------------------------

def fake_exposures(count=40):
    return [{'uri': f'{URI}#{index}', 'ra': RA, 'dec': DEC, 'obs_publisher_did': f'did{index}', 'obs_id': f'obs{index}',
             'band': 'SPHEREx-D5', 'collection': 'spherex_qr2', 't_min': 60900 + index * 0.01} for index in range(count)]


def fake_reader(session, uri, ra, dec):
    index = int(uri.rpartition('#')[2])
    if index == 0:
        raise remote.RemoteError('missing')
    if index == 1:
        return {'status': 'saturated', 'flags': 2, 'flag_names': ['OVERFLOW'], 'detector': 5, 'bytes_read': 10}
    wavelength = 3.9 + 0.5 * index / 40
    flux = 10 * (1 - 0.6 * math.exp(-((wavelength - 4.27) / 0.03) ** 2))
    return {'status': 'ok', 'wavelength_um': wavelength, 'bandwidth_um': 0.04, 'flux_mjy': flux, 'flux_err_mjy': 0.05,
            'flags': 0, 'flag_names': [], 'detector': 5, 'mjd': 60900 + index * 0.01, 'bytes_read': 1000}


def wait(service, job_id):
    for _ in range(200):
        job = service.get(job_id)
        if job['state'] in ('done', 'failed'):
            return job
        time.sleep(0.02)
    raise AssertionError('job did not finish')


def test_service_runs_a_job_keeps_failures_as_points_and_reuses_results(tmp_path):
    calls = []
    service = SpectrumService(find=lambda ra, dec: calls.append((ra, dec)) or fake_exposures(), reader=fake_reader, cache_dir=tmp_path, workers=4)
    job_id = service.start(RA, DEC)
    job = wait(service, job_id)
    assert job['state'] == 'done' and job['done'] == job['total'] == 40 and job['megabytes_read'] == 0.0
    assert job['analysis']['counts'] == {'ok': 38, 'unavailable': 1, 'saturated': 1}
    co2 = by_id(job['analysis']['features'])['co2']
    assert co2['status'] == 'detected' and co2['kind'] == 'absorption'
    assert all(set(point) >= {'wavelength_um', 'flux_mjy', 'status', 'utc', 'epoch'} for point in job['points'])
    assert service.start(RA, DEC) == job_id and len(calls) == 1  # Same request: same job.
    again = SpectrumService(find=lambda ra, dec: pytest.fail('cache not used'), reader=fake_reader, cache_dir=tmp_path)
    cached = again.get(again.start(RA, DEC))
    assert cached['state'] == 'done' and cached['done'] == 40 and 'cache' in cached['message']


def test_service_reports_archive_failure_and_empty_coverage(tmp_path):
    from backend.app.irsa import IRSAUnavailable

    def down(ra, dec):
        raise IRSAUnavailable('IRSA TAP could not be reached or timed out. Please retry.')
    service = SpectrumService(find=down, reader=fake_reader, cache_dir=tmp_path)
    failed = wait(service, service.start(RA, DEC))
    assert failed['state'] == 'failed' and 'IRSA' in failed['message'] and failed['points'] == []
    empty = SpectrumService(find=lambda ra, dec: [], reader=fake_reader, cache_dir=tmp_path / 'other')
    done = wait(empty, empty.start(RA, DEC))
    assert done['state'] == 'done' and done['total'] == 0 and 'no public exposure' in done['message']


@pytest.fixture
def client(tmp_path):
    service = SpectrumService(find=lambda ra, dec: fake_exposures(), reader=fake_reader, cache_dir=tmp_path, workers=4)
    app.dependency_overrides[get_spectrum_service] = lambda: service
    yield TestClient(app), service
    app.dependency_overrides.pop(get_spectrum_service, None)


def test_api_starts_polls_and_exports_a_spectrum(client):
    http, service = client
    started = http.post('/api/spectrum', json={'ra': RA, 'dec': DEC})
    assert started.status_code == 202
    job_id = started.json()['id']
    wait(service, job_id)
    body = http.get(f'/api/spectrum/{job_id}').json()
    assert body['state'] == 'done' and body['request'] == {'kind': 'position', 'ra': RA, 'dec': DEC, 'limit': 600}
    assert 'No aperture correction' in ' '.join(body['method']['limits'])
    exported = http.get(f'/api/spectrum/{job_id}/csv')
    assert exported.headers['content-type'].startswith('text/csv') and '# photometry: Forced circular aperture' in exported.text
    rows = [line for line in exported.text.splitlines() if not line.startswith('#')]
    assert rows[0].startswith('obs_id,detector,mjd') and len(rows) == 41 and ',saturated,' in exported.text
    assert http.get('/api/spectrum/unknown').status_code == 404


@pytest.mark.parametrize('body', [{}, {'ra': 10}, {'ra': 10, 'dec': 95}, {'ra': 10, 'dec': 5, 'target': '3i-atlas'},
                                  {'target': 'planet-x'}, {'ra': 10, 'dec': 5, 'limit': 100000}, {'ra': 'nan', 'dec': 0}])
def test_api_rejects_invalid_requests(client, body):
    assert client[0].post('/api/spectrum', json=body).status_code == 422


def test_api_describes_bands_and_method():
    body = TestClient(app).get('/api/spectrum/features').json()
    assert {'h2o_ice', 'co2', 'co', 'pah'} <= {feature['id'] for feature in body['features']}
    assert body['thresholds'] == {'sigma': 5.0, 'strength': 0.08, 'variability': 0.08, 'season_gap_days': 20}
    assert body['moving_targets'][0]['id'] == '3i-atlas'


def test_preloaded_comet_spectrum_shows_carbon_dioxide_gas_offline():
    """Real SPHEREx data from the demo bundle: 3I/ATLAS on 14 December 2025."""
    response = TestClient(app).get('/api/spectrum/demo/3i-atlas')
    if response.status_code == 503:
        pytest.skip('demo bundle is not installed')
    body = response.json()
    assert body['request']['tracked'] is True and body['analysis']['counts'].get('ok', 0) >= 15
    co2 = by_id(body['analysis']['features'])['co2']
    assert co2['status'] == 'detected' and co2['kind'] == 'emission' and co2['strength'] > 10
    assert TestClient(app).get('/api/spectrum/demo/not-a-target').status_code == 404
