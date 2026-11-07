"""Real API/service concurrency with a gated synthetic FITS download."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import shutil
import threading

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.images import get_image_service
from backend.app.image_service import ImageService
from backend.app.image_download import ImageError
from backend.tests.test_images import ACCESS, FITS_URL, make_mef, settings


class GatedDownloader:
    def __init__(self, source):
        self.source = source
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.fail = False

    def download(self, url, destination, cutout=None):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(10), 'test did not release download'
        if self.fail:
            self.fail = False
            raise ImageError('Synthetic download failure', 502, 'download_failed')
        shutil.copyfile(self.source, destination)
        return FITS_URL


@pytest.mark.parametrize('cutout_deg', [None, 0.3])
@pytest.mark.parametrize('same_observation', [True, False])
def test_concurrent_slider_and_viewer_wait_and_reuse_cache(settings, tmp_path, same_observation, cutout_deg):
    downloader = GatedDownloader(make_mef(tmp_path / 'synthetic.fits'))
    service = ImageService(settings, downloader)
    app.dependency_overrides[get_image_service] = lambda: service
    try:
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.post, '/api/images', json={'access_url': ACCESS, 'ra': 210, 'dec': 54, 'cutout_deg': cutout_deg},
                                headers={'X-SkyTracker-Client': 'time-slider'})
            assert downloader.entered.wait(5)
            second = pool.submit(client.post, '/api/images', json={
                'access_url': ACCESS if same_observation else ACCESS + '-other', 'ra': 210, 'dec': 54, 'cutout_deg': cutout_deg})
            try:
                # Before the fix this returns 503 immediately instead of waiting.
                with pytest.raises(TimeoutError):
                    second.result(timeout=0.2)
            finally:
                downloader.release.set()
            a, b = first.result(timeout=10), second.result(timeout=10)
            assert (a.status_code, b.status_code) == (200, 200)
            assert b.json()['cache_hit'] is same_observation
            assert downloader.calls == (1 if same_observation else 2)
            assert client.get(a.json()['preview_url']).status_code == 200
            assert client.get(b.json()['preview_url']).status_code == 200
            assert client.get(f"/api/images/{b.json()['image_id']}/pixel?x=2&y=3").status_code == 200
    finally:
        downloader.release.set()
        app.dependency_overrides.pop(get_image_service, None)


def test_failed_preparation_releases_waiter_and_recovers(settings, tmp_path):
    downloader = GatedDownloader(make_mef(tmp_path / 'synthetic.fits'))
    downloader.fail = True
    service = ImageService(settings, downloader)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.prepare, ACCESS)
        assert downloader.entered.wait(5)
        second = pool.submit(service.prepare, ACCESS)
        try:
            with pytest.raises(TimeoutError):
                second.result(timeout=0.2)
        finally:
            downloader.release.set()
        with pytest.raises(ImageError, match='Synthetic download failure'):
            first.result(timeout=10)
        assert second.result(timeout=10)['cache_hit'] is False
        assert service.prepare(ACCESS)['cache_hit'] is True
        assert downloader.calls == 2


def test_queue_bound_timeout_and_lock_cleanup(settings):
    service = ImageService(settings, max_waiters=1, wait_seconds=0.02)
    service.lock.acquire()
    try:
        with pytest.raises(ImageError, match='Timed out'):
            with service.transaction():
                pytest.fail('held lock was bypassed')
    finally:
        service.lock.release()
    assert service.slots.acquire(blocking=False)
    assert service.slots.acquire(blocking=False)
    try:
        with pytest.raises(ImageError, match='queue is full'):
            with service.transaction():
                pytest.fail('queue bound was bypassed')
    finally:
        service.slots.release()
        service.slots.release()
    with service.transaction():
        pass


def test_preview_waits_for_another_service_instance(settings, tmp_path):
    downloader = GatedDownloader(make_mef(tmp_path / 'synthetic.fits'))
    downloader.release.set()
    first = ImageService(settings, downloader)
    metadata = first.prepare(ACCESS)
    second = ImageService(settings, downloader)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with first.transaction():
            preview = pool.submit(second.open_asset, metadata['image_id'], 'preview')
            with pytest.raises(TimeoutError):
                preview.result(timeout=0.2)
        with preview.result(timeout=5) as handle:
            assert handle.read(8) == b'\x89PNG\r\n\x1a\n'
    assert downloader.calls == 1
