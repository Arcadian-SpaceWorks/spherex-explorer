"""Tests for the optional IRSA cutout mode. All network access is mocked; fixtures are synthetic."""
import shutil
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.image_download import ImageError, IRSAImageDownloader, add_cutout_query
from backend.app.image_service import ImageService
from backend.app.images import get_image_service
from backend.app.main import app
from test_images import ACCESS, FITS_URL, FakeResponse, datalink, make_mef, mef, settings  # noqa: F401 (fixtures)

CUT = (10.6847, 41.2687, 0.3)
CUT_URL = FITS_URL + '?center=10.684700,41.268700&size=0.3000deg'


def test_add_cutout_query_builds_the_irsa_cutout_url():
    assert add_cutout_query(FITS_URL, *CUT) == CUT_URL


@pytest.mark.parametrize('url', [
    FITS_URL + '?already=1',                                    # product URL already has a query
    'https://irsa.ipac.caltech.edu/data/SPHEREx/a.fits',        # not the image server
    'https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=x',  # DataLink metadata, not a product
])
def test_cutout_only_for_plain_image_server_products(url):
    with pytest.raises(ImageError) as error:
        add_cutout_query(url, *CUT)
    assert error.value.code in ('cutout_unsupported', 'unsafe_url')


@pytest.mark.parametrize('values', [
    (float('nan'), 41, .3), (10, float('inf'), .3), (360, 41, .3), (10, 91, .3),
    (10, 41, 0), (10, 41, 1.5), (10, 41, -.1),
])
def test_cutout_parameters_are_validated(values):
    with pytest.raises(ImageError) as error:
        add_cutout_query(FITS_URL, *values)
    assert error.value.code == 'invalid_cutout'


def test_download_with_cutout_requests_the_cutout_url(settings, mef, tmp_path):
    destination = tmp_path / 'cutout.fits'
    r1, r2 = FakeResponse(datalink(length=mef.stat().st_size)), FakeResponse(mef.read_bytes())
    with patch('backend.app.image_download.check_public_dns'), \
            patch('backend.app.image_download.requests.Session') as factory:
        session = factory.return_value.__enter__.return_value
        session.get.side_effect = [r1, r2]
        result = IRSAImageDownloader(settings).download(ACCESS, destination, cutout=CUT)
        calls = session.get.call_args_list
    assert calls[0].args[0] == ACCESS             # DataLink metadata first, unchanged
    assert calls[1].args[0] == CUT_URL            # then the cutout, not the full product URL
    assert result == CUT_URL
    assert destination.read_bytes() == mef.read_bytes()


class RecordingDownloader:
    def __init__(self, path):
        self.path, self.calls = path, []

    def download(self, url, destination, cutout=None):
        self.calls.append(cutout)
        shutil.copyfile(self.path, destination)
        return FITS_URL if cutout is None else add_cutout_query(FITS_URL, *cutout)


def test_service_cache_keys_include_cutout_parameters(settings, mef):
    downloader = RecordingDownloader(mef)
    service = ImageService(settings, downloader)
    full = service.prepare(ACCESS, 210, 54)
    cut = service.prepare(ACCESS, 210, 54, 0.3)
    assert full['image_id'] != cut['image_id']
    assert full['cutout'] is None
    assert cut['cutout'] == {'ra': 210.0, 'dec': 54.0, 'size_deg': 0.3}
    assert cut['fits_url'].endswith('?center=210.000000,54.000000&size=0.3000deg')
    assert service.prepare(ACCESS, 210, 54, 0.3)['cache_hit'] is True      # same cutout: cached
    assert service.prepare(ACCESS, 210, 54, 0.5)['image_id'] != cut['image_id']  # new size: new entry
    assert downloader.calls == [None, (210.0, 54.0, 0.3), (210.0, 54.0, 0.5)]


def test_service_cutout_needs_a_target(settings, mef):
    service = ImageService(settings, RecordingDownloader(mef))
    with pytest.raises(ImageError) as error:
        service.prepare(ACCESS, None, None, 0.3)
    assert error.value.code == 'invalid_cutout'


def test_api_cutout_request_and_validation(settings, mef):
    service = ImageService(settings, RecordingDownloader(mef))
    app.dependency_overrides[get_image_service] = lambda: service
    try:
        client = TestClient(app)
        ok = client.post('/api/images', json={'access_url': ACCESS, 'ra': 210, 'dec': 54, 'cutout_deg': 0.3})
        assert ok.status_code == 200 and ok.json()['cutout']['size_deg'] == 0.3
        assert ok.json()['target']['status'] == 'inside'
        assert client.post('/api/images', json={'access_url': ACCESS, 'cutout_deg': 0.3}).status_code == 422
        for bad in (0.001, 5, -1):
            assert client.post('/api/images', json={'access_url': ACCESS, 'ra': 210, 'dec': 54,
                                                    'cutout_deg': bad}).status_code == 422
        # Existing full-image behaviour is unchanged when no cutout is requested.
        full = client.post('/api/images', json={'access_url': ACCESS, 'ra': 210, 'dec': 54})
        assert full.status_code == 200 and full.json()['cutout'] is None
    finally:
        app.dependency_overrides.pop(get_image_service, None)
