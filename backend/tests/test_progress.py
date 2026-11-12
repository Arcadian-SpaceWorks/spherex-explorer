"""No network: the download panel reports measured bytes and honest states. TEST DATA throughout."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import shutil
import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app import progress
from backend.app.image_download import ImageError, IRSAImageDownloader, MirrorDownloader
from backend.app.image_service import ImageService
from backend.app.main import app
from backend.app.progress import ProgressBoard, label_for
from backend.tests.test_images import ACCESS, FITS_URL, FakeResponse, make_mef, settings  # noqa: F401 (fixture)
from backend.tests.test_mirror import FakeIRSA, cutter


def test_labels_are_short_observation_names():
    assert label_for('https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=ivo://irsa.ipac/spherex_qr2?2026W21_2A_0213_2/D5') == '2026W21_2A_0213_2 · D5'
    assert label_for(FITS_URL) == 'fixture'


def test_a_job_reports_stages_bytes_and_success():
    board = ProgressBoard()
    with board.job('image', 'A', '0.3° cutout') as job:
        job.stage('downloading', source='AWS mirror')
        job.received(10, 40)
        row = board.snapshot()[0]
        assert (row['stage'], row['source'], row['bytes'], row['total'], row['state']) == ('downloading', 'AWS mirror', 10, 40, 'active')
    assert board.snapshot()[0]['state'] == 'done'


def test_a_failed_job_says_so_and_the_error_still_propagates():
    board = ProgressBoard()
    with pytest.raises(ImageError):
        with board.job('image', 'A'):
            raise ImageError('Synthetic failure')
    assert board.snapshot()[0]['state'] == 'failed'


def test_finished_jobs_leave_after_a_short_while(monkeypatch):
    board = ProgressBoard()
    with board.job('search', 'S'):
        pass
    assert len(board.snapshot()) == 1
    monkeypatch.setattr(progress, 'LINGER_SECONDS', 0)
    assert board.snapshot() == []


def test_a_fallback_restarts_the_byte_count():
    board = ProgressBoard()
    with board.job('image', 'A') as job:
        job.stage('downloading', source='AWS mirror')
        job.received(50, 100)
        job.stage('downloading', source='IRSA')
        row = board.snapshot()[0]
    assert (row['source'], row['bytes'], row['total']) == ('IRSA', 0, None)


def test_stream_reports_received_bytes_and_a_stated_total(settings, tmp_path):
    seen = []
    with patch('backend.app.image_download.check_public_dns'):
        session = type('S', (), {'get': lambda self, *a, **k: FakeResponse(b'SIMPLE  =' * 10, headers={'Content-Length': '90'}, chunks=[b'SIMPLE  =' * 5, b'SIMPLE  =' * 5])})()
        IRSAImageDownloader(settings)._stream(session, FITS_URL, BytesIO(), 1000, time.monotonic() + 30,
                                              progress=lambda done, total: seen.append((done, total)))
    assert seen == [(45, 90), (90, 90)]


def test_a_response_without_a_length_reports_no_total(settings):
    seen = []
    with patch('backend.app.image_download.check_public_dns'):
        session = type('S', (), {'get': lambda self, *a, **k: FakeResponse(b'x' * 20)})()
        IRSAImageDownloader(settings)._stream(session, FITS_URL, BytesIO(), 1000, time.monotonic() + 30,
                                              progress=lambda done, total: seen.append((done, total)))
    assert seen == [(20, None)]  # No percentage can be claimed for such a download.


class Recorder:
    def __init__(self):
        self.stages, self.bytes = [], []

    def stage(self, name, source=None):
        self.stages.append((name, source))

    def received(self, done, total):
        self.bytes.append((done, total))


def test_mirror_path_reports_each_stage_and_skips_download_when_reused(settings, tmp_path):
    product = make_mef(tmp_path / 'synthetic.fits')
    downloader = MirrorDownloader(settings, irsa=FakeIRSA(product), cutter=cutter([]))
    first = Recorder()
    downloader.fetch(ACCESS, tmp_path / 'a.fits', (210.0, 54.0, 0.3), progress=first)
    assert first.stages == [('locating', 'IRSA'), ('downloading', 'AWS mirror'), ('cutting', None)]
    second = Recorder()
    downloader.fetch(ACCESS, tmp_path / 'b.fits', (210.0, 54.0, 0.437), progress=second)
    assert second.stages == [('locating', 'IRSA'), ('cutting', None)]


def test_fallback_to_irsa_is_shown(settings, tmp_path):
    product = make_mef(tmp_path / 'synthetic.fits')
    record = Recorder()
    MirrorDownloader(settings, irsa=FakeIRSA(product, fail_stream=True), cutter=cutter([])).fetch(ACCESS, tmp_path / 'a.fits', (210.0, 54.0, 0.3), progress=record)
    assert record.stages[-1] == ('downloading', 'IRSA')


def test_api_shows_a_running_preparation_and_then_nothing_stale(settings, tmp_path, monkeypatch):
    source = make_mef(tmp_path / 'synthetic.fits')
    entered, release = threading.Event(), threading.Event()

    class Held:
        def download(self, url, destination, cutout=None):
            entered.set()
            assert release.wait(10)
            shutil.copyfile(source, destination)
            return FITS_URL

    service = ImageService(settings, Held())
    client = TestClient(app)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(service.prepare, ACCESS, 210, 54, 0.3)
        assert entered.wait(5)
        try:
            rows = [row for row in client.get('/api/images/progress').json()['jobs'] if row['label'] == 'fixture']
            assert len(rows) == 1 and rows[0]['stage'] == 'downloading' and rows[0]['detail'] == '0.3° cutout' and rows[0]['state'] == 'active'
            assert 'ra' not in rows[0] and 'access_url' not in rows[0]  # Observation names only.
        finally:
            release.set()
        running.result(timeout=10)
    jobs = [row for row in client.get('/api/images/progress').json()['jobs'] if row['label'] == 'fixture']
    assert jobs and all(row['state'] == 'done' for row in jobs)
    entered.clear()
    again = service.prepare(ACCESS, 210, 54, 0.3)  # A cache hit downloads nothing, so it adds no row.
    assert again['cache_hit'] is True and not entered.is_set()
    assert len([row for row in client.get('/api/images/progress').json()['jobs'] if row['label'] == 'fixture']) == len(jobs)
