"""TEST DATA: POST /api/compare end to end with synthetic FITS files and a fake downloader.

No network. The real ImageService (cache, locks, FITS worker) and the real comparison worker run.
"""
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.nddata import Cutout2D
from astropy.wcs import WCS
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.compare_api import get_compare_service
from backend.app.compare_service import CompareCacheSettings, CompareService
from backend.app.image_download import ImageError, ImageSettings, add_cutout_query
from backend.app.image_service import ImageService
from backend.app.main import app
from test_compare import DEC, RA, detector_wcs, render, write_frame

BASE = 'https://irsa.ipac.caltech.edu/ibe/data/spherex/qr2/level2/TEST-DATA-{}.fits'
SHAPE = (300, 300)


def irsa_like_cutout(source, destination, ra, dec, size_deg):
    """Imitate IRSA's image-server cutout: same pixel box from every image extension, celestial
    WCS shifted, and the wavelength lookup kept in raw detector coordinates (CRPIXnW shifted)."""
    with fits.open(source) as hdul:
        image = hdul['IMAGE']
        cut = Cutout2D(image.data, SkyCoord(ra * u.deg, dec * u.deg), size_deg * u.deg,
                       wcs=WCS(image.header).celestial, mode='trim')
        rows, cols = cut.slices_original
        hdus = [hdul[0].copy()]
        for hdu in hdul[1:]:
            if isinstance(hdu, fits.ImageHDU) and hdu.shape == image.shape:
                copy = fits.ImageHDU(data=hdu.data[rows, cols], header=hdu.header.copy(), name=hdu.name)
                if hdu.name == 'IMAGE':
                    copy.header.update(cut.wcs.to_header())
                    for axis, start in ((1, cols.start), (2, rows.start)):
                        if f'CRPIX{axis}W' in copy.header:
                            copy.header[f'CRPIX{axis}W'] -= start
                hdus.append(copy)
            else:
                hdus.append(hdu.copy())
        fits.HDUList(hdus).writeto(destination, overwrite=True)


class MapDownloader:
    """Serves a local synthetic file per access URL (cut like IRSA) and records requested cutouts."""
    def __init__(self, files):
        self.files, self.calls = files, []

    def download(self, url, destination, cutout=None):
        self.calls.append((url, cutout))
        if cutout is None:
            shutil.copyfile(self.files[url], destination)
            return url
        irsa_like_cutout(self.files[url], destination, *cutout)
        return add_cutout_query(url, *cutout)


@pytest.fixture
def setup(tmp_path):
    def frame(name, rotation, **kwargs):
        wcs = detector_wcs(SHAPE, rotation, (1.5, -2.0))
        return write_frame(tmp_path / f'{name}.fits', wcs, render(wcs, SHAPE), **kwargs)
    files = {
        BASE.format('D1-JAN'): frame('d1jan', 0.0, obs_id='TEST-DATA-JAN', date='2026-01-01T00:00:00', wavelength=0.895),
        BASE.format('D1-JUL'): frame('d1jul', 30.0, obs_id='TEST-DATA-JUL', date='2026-07-10T00:00:00', wavelength=0.893),
        BASE.format('D1-JUL25'): frame('d1jul25', 10.0, obs_id='TEST-DATA-JUL25', date='2025-07-09T00:00:00', wavelength=0.750),
        BASE.format('D4-JAN'): frame('d4jan', 0.0, obs_id='TEST-DATA-JAN', date='2026-01-01T00:00:00', wavelength=2.98, detector=4),
    }
    downloader = MapDownloader(files)
    images = ImageService(ImageSettings(cache_dir=tmp_path / 'cache', max_bytes=8 * 1024 * 1024, cache_entries=4,
                                        cache_ttl=600, cutout_cache_entries=4), downloader)
    service = CompareService(images, CompareCacheSettings(cache_dir=tmp_path / 'compare', entries=3, ttl=600))
    app.dependency_overrides[get_compare_service] = lambda: service
    try:
        yield TestClient(app), downloader, images, service
    finally:
        app.dependency_overrides.pop(get_compare_service, None)


def body(a, b, mode='time', **extra):
    return {'a': {'access_url': BASE.format(a)}, 'b': {'access_url': BASE.format(b)},
            'ra': RA, 'dec': DEC, 'size_deg': 0.3, 'mode': mode, **extra}


def png(client, url):
    response = client.get(url)
    assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
    return np.array(Image.open(__import__('io').BytesIO(response.content)))


def test_accepted_time_pair_returns_aligned_previews_difference_and_provenance(setup):
    client, downloader, _, _ = setup
    response = client.post('/api/compare', json=body('D1-JAN', 'D1-JUL'))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['decision'] == 'ACCEPT' and data['validation']['difference_allowed'] is True
    assert {cutout[2] for _, cutout in downloader.calls} == {0.437}  # Covers the rotated grid.
    assert data['overlap_fraction'] > .99 and data['grid']['shape'] == [176, 176] and data['grid']['north_up']
    assert data['stretch']['shared'] is True
    assert data['stretch']['a']['low'] == data['stretch']['b']['low']
    a, b = data['frames']
    assert (a['role'], a['obs_id'], a['band'], b['obs_id']) == ('a', 'TEST-DATA-JAN', 'SPHEREx-D1', 'TEST-DATA-JUL')
    assert a['wavelength_um'] == pytest.approx(.895) and b['wavelength_um'] == pytest.approx(.893)
    assert a['provenance']['source'] == 'irsa_cutout' and len(a['sha256']) == 64
    assert a['fits_url'].startswith(BASE.format('D1-JAN') + '?center=')
    assert data['difference']['n_pixels'] > 0 and data['difference']['display']['zero_gray'] == 128
    for role in ('a', 'b', 'difference'):
        assert png(client, data['previews'][role]).shape == (176, 176, 4)
    assert any('No motion' in note for note in data['notes'])
    assert data['cache_hit'] is False


def test_wavelength_mismatch_warns_and_never_makes_a_difference_image(setup):
    client, _, _, _ = setup
    data = client.post('/api/compare', json=body('D1-JUL25', 'D1-JAN')).json()
    assert data['decision'] == 'WARN'
    assert 'wavelength_mismatch' in {reason['code'] for reason in data['validation']['reasons']}
    assert data['previews']['difference'] is None and data['difference'] is None
    assert data['stretch']['shared'] is False
    missing = client.get(f"/api/compare/{data['compare_id']}/difference.png")
    assert missing.status_code == 404 and missing.json()['code'] == 'difference_not_allowed'
    assert png(client, data['previews']['a']).shape == (176, 176, 4)


def test_two_bands_of_one_exposure_are_shown_side_by_side_only(setup):
    client, _, _, _ = setup
    data = client.post('/api/compare', json=body('D1-JAN', 'D4-JAN', mode='wavelength')).json()
    assert data['decision'] == 'ACCEPT' and data['validation']['difference_allowed'] is False
    assert data['previews']['difference'] is None and data['stretch']['shared'] is False
    assert [frame['band'] for frame in data['frames']] == ['SPHEREx-D1', 'SPHEREx-D4']
    assert any('never subtracted' in note for note in data['notes'])


def test_cached_image_ids_are_accepted_and_results_are_cached(setup):
    client, downloader, images, _ = setup
    first = images.prepare(BASE.format('D1-JAN'), RA, DEC, 0.437)
    second = images.prepare(BASE.format('D1-JUL'), RA, DEC, 0.437)
    request = {'a': {'image_id': first['image_id']}, 'b': {'image_id': second['image_id']},
               'ra': RA, 'dec': DEC, 'size_deg': 0.3, 'mode': 'time'}
    one = client.post('/api/compare', json=request).json()
    two = client.post('/api/compare', json=request).json()
    assert one['decision'] == 'ACCEPT' and one['compare_id'] == two['compare_id']
    assert (one['cache_hit'], two['cache_hit']) == (False, True)
    assert len(downloader.calls) == 2  # Nothing re-downloaded for the comparison.


def test_small_cutouts_are_reported_not_hidden(setup):
    client, _, images, _ = setup
    small = [images.prepare(BASE.format(name), RA, DEC, 0.3)['image_id'] for name in ('D1-JAN', 'D1-JUL')]
    data = client.post('/api/compare', json={'a': {'image_id': small[0]}, 'b': {'image_id': small[1]},
                                             'ra': RA, 'dec': DEC, 'size_deg': 0.3, 'mode': 'time'}).json()
    assert data['overlap_fraction'] < .9 and data['decision'] == 'REJECT'
    assert 'low_overlap' in {reason['code'] for reason in data['validation']['reasons']}
    assert any('smaller than' in note for note in data['notes'])


@pytest.mark.parametrize('change, status', [
    (lambda b: b['a'].update(image_id='a' * 64), 422),  # Both image_id and access_url.
    (lambda b: b.update(mode='motion'), 422),
    (lambda b: b.update(size_deg=0.9), 422),
    (lambda b: b.update(ra=400), 422),
    (lambda b: b.update(zodi_subtract=True), 422),  # Unknown fields are refused.
    (lambda b: b.update(a={'image_id': 'b' * 64}), 404),  # Not in the image cache.
    (lambda b: b.update(a={'access_url': 'http://127.0.0.1/x.fits'}), 400),  # Outside the IRSA allowlist.
])
def test_invalid_requests_are_refused(setup, change, status):
    client, _, _, _ = setup
    request = body('D1-JAN', 'D1-JUL')
    change(request)
    assert client.post('/api/compare', json=request).status_code == status


def test_target_outside_the_images_is_a_clear_error(setup):
    client, _, images, _ = setup
    ids = [images.prepare(BASE.format(name), RA, DEC, 0.437)['image_id'] for name in ('D1-JAN', 'D1-JUL')]
    response = client.post('/api/compare', json={'a': {'image_id': ids[0]}, 'b': {'image_id': ids[1]},
                                                 'ra': RA + 5, 'dec': DEC, 'size_deg': 0.3, 'mode': 'time'})
    assert response.status_code == 422 and response.json()['code'] == 'target_outside'


def test_unknown_comparison_preview_is_404(setup):
    client, _, _, _ = setup
    assert client.get('/api/compare/' + 'c' * 64 + '/a.png').status_code == 404
    assert client.get('/api/compare/' + 'c' * 64 + '/x.png').status_code == 422


# Real preloaded demo frames (frontend/public/demo); no network is allowed.
DEMO_ROOT = Path(__file__).resolve().parents[2] / 'frontend' / 'public' / 'demo'


def demo_image(target_id, obs_id, detector):
    manifest = json.loads((DEMO_ROOT / 'manifest.json').read_text())
    target = next(t for t in manifest['targets'] if t['id'] == target_id)
    row = next(o for o in target['observations'] if o['obs_id'] == obs_id and o['detector'] == detector)
    return target, row['image_id']


@pytest.fixture
def demo_client(tmp_path):
    service = CompareService(images=None, settings=CompareCacheSettings(cache_dir=tmp_path / 'compare', entries=3, ttl=600))
    app.dependency_overrides[get_compare_service] = lambda: service
    try:
        with patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')):
            yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_compare_service, None)


def demo_body(target_id, a, b, mode='time'):
    target, image_a = demo_image(target_id, *a)
    _, image_b = demo_image(target_id, *b)
    return {'a': {'demo_image_id': image_a}, 'b': {'demo_image_id': image_b}, 'ra': target['ra'], 'dec': target['dec'],
            'size_deg': 0.3, 'mode': mode}


def test_a_matched_demo_pair_is_differenced_offline(demo_client):
    # Barnard's Star, D3, August 2025 vs March 2026: wavelength at the target within 0.006 um.
    response = demo_client.post('/api/compare', json=demo_body('barnard', ('2025W34_2B_0030_2', 3), ('2026W12_1A_0598_3', 3)))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['decision'] == 'ACCEPT' and result['previews']['difference']
    assert result['overlap_fraction'] > 0.95
    assert all(frame['demo'] and frame['provenance']['source'] == 'irsa_cutout' for frame in result['frames'])
    assert 'preloaded in the local demo bundle; no network was used' in result['notes'][0]
    assert png(demo_client, result['previews']['difference']).shape[:2] == (176, 176)


def test_demo_comet_frames_hours_apart_stay_side_by_side(demo_client):
    result = demo_client.post('/api/compare', json=demo_body('3i-atlas', ('2025W50_2A_0685_1', 5), ('2025W50_2A_0712_4', 5))).json()
    assert result['decision'] == 'WARN' and result['previews']['difference'] is None
    assert [r['code'] for r in result['validation']['reasons'] if r['severity'] != 'info'] == ['wavelength_mismatch']


@pytest.mark.parametrize('refs, status', [
    ({'a': {'demo_image_id': 'f' * 64}, 'b': {'demo_image_id': 'e' * 64}}, 404),           # Not in the bundle.
    ({'a': {'demo_image_id': 'f' * 64}, 'b': {'access_url': BASE.format('D1-JAN')}}, 422),  # Mixed origins.
    ({'a': {'demo_image_id': 'f' * 64, 'image_id': 'e' * 64}, 'b': {'demo_image_id': 'e' * 64}}, 422),
    ({'a': {'demo_image_id': '../manifest'}, 'b': {'demo_image_id': 'e' * 64}}, 422),
])
def test_demo_references_are_checked(demo_client, refs, status):
    response = demo_client.post('/api/compare', json={**refs, 'ra': 10.0, 'dec': 41.0, 'size_deg': 0.3, 'mode': 'time'})
    assert response.status_code == status


def test_a_corrupted_demo_fits_is_refused(tmp_path):
    root = tmp_path / 'demo'
    shutil.copytree(DEMO_ROOT, root, ignore=shutil.ignore_patterns('*.fits'))
    target, image_id = demo_image('m31', '2026W01_1A_0471_1', 1)
    (root / 'assets' / image_id / 'original.fits').write_bytes(b'not the original')
    service = CompareService(images=None, settings=CompareCacheSettings(cache_dir=tmp_path / 'compare', entries=3, ttl=600), demo_root=root)
    with pytest.raises(ImageError, match='Preloaded science data unavailable'):
        service.compare({'demo_image_id': image_id}, {'demo_image_id': image_id}, target['ra'], target['dec'], 0.3, 'time')
