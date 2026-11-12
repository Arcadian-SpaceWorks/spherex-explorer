"""Background spectrum jobs: find the exposures, measure them in parallel, analyse as points arrive."""
import hashlib
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

from ..irsa import IRSAUnavailable
from . import analysis, archive
from .photometry import APERTURE_PX, ANNULUS_IN_PX, ANNULUS_OUT_PX, HALF_Y
from .remote import RemoteError, measure_remote

WORKERS = int(os.environ.get('SKYTRACKER_SPECTRUM_WORKERS', '32'))
MAX_EXPOSURES = int(os.environ.get('SKYTRACKER_SPECTRUM_MAX_EXPOSURES', '1500'))
DEFAULT_EXPOSURES = 600
MAX_RUNNING = 2
MAX_JOBS = 24
CACHE_SECONDS = 6 * 3600
CACHE_DIR = Path(os.environ.get('SKYTRACKER_SPECTRUM_CACHE_DIR',
                                str(Path(__file__).resolve().parents[3] / '.cache' / 'arcadian-spectra-v1')))
POINT_KEYS = ('obs_id', 'detector', 'mjd', 'utc', 'collection', 'status', 'wavelength_um', 'bandwidth_um', 'flux_mjy',
              'flux_err_mjy', 'background_mjy_sr', 'flag_names', 'x', 'y', 'ra', 'dec', 'epoch', 'error_source')

METHOD = {
    'photometry': f'Forced circular aperture, radius {APERTURE_PX} px (15.4 arcsec), on the requested position in every exposure; no recentring.',
    'background': f'Sigma-clipped median of pixels {ANNULUS_IN_PX:.0f} to {ANNULUS_OUT_PX:.0f} px from the target within the {2 * HALF_Y + 1} detector rows around it.',
    'uncertainty': 'Pipeline VARIANCE plane summed over the aperture plus the background-estimate term. Calibration and aperture systematics (a few percent) are not included.',
    'wavelength': 'Read for the target\'s pixel from each exposure\'s own WCS-WAVE table. The filter bandwidth is wider than the spacing of the points.',
    'rejected': 'Measurements with a transient, overflow, non-functional, hot, cold, non-linear, persistence, outlier or streak flag inside the aperture are listed but never plotted as flux.',
    'limits': ['No aperture correction: flux in the PSF wings beyond 2.5 px is not added back.',
               'Pixels are 6.15 arcsec: neighbours within about 15 arcsec are blended into the measurement.',
               'Sources brighter than roughly 100 mJy saturate in some channels and are rejected there.',
               'A forced measurement is not a detection claim; check the signal-to-noise.'],
    'source': 'SPHEREx Level 2 spectral images (NASA/IPAC IRSA), read from the AWS Open Data mirror.',
}


def new_session():
    session = requests.Session()
    session.trust_env = False  # Public data: no proxies or .netrc credentials.
    session.mount('https://', HTTPAdapter(pool_connections=4, pool_maxsize=WORKERS + 4))
    return session


def measure_exposure(session, exposure, reader=measure_remote):
    """One exposure -> one point. Failures become a point with a status, never an exception."""
    point = {'obs_id': exposure['obs_id'], 'collection': exposure['collection'], 'mjd': exposure['t_min'],
             'ra': exposure['ra'], 'dec': exposure['dec'],
             'detector': int(exposure['band'][-1]) if (exposure.get('band') or '')[-1:].isdigit() else None}
    try:
        measured = reader(session, exposure['uri'], exposure['ra'], exposure['dec'])
    except RemoteError as exc:
        return {**point, 'status': 'unavailable', 'message': str(exc)}
    except Exception:  # A malformed file must not end the whole spectrum.
        return {**point, 'status': 'unreadable'}
    for key in ('mjd', 'detector'):
        if measured.get(key) is None:
            measured.pop(key, None)
    point.update(measured)
    point['utc'] = archive.mjd_to_utc(point.get('mjd'))
    return point


class Job:
    def __init__(self, key, request):
        self.id, self.key, self.request = uuid.uuid4().hex, key, request
        self.state, self.message = 'queued', ''
        self.total = self.available = 0
        self.truncated = False
        self.points, self.bytes_read = [], 0
        self.created = self.updated = time.time()
        self.finished = None
        self.analysis, self.analysed_at = None, -1
        self.lock = threading.Lock()

    def snapshot(self):
        with self.lock:
            points = list(self.points)
            if self.analysed_at != len(points):
                self.analysis, self.analysed_at = analysis.summarise(points, self.request['kind'] == 'moving'), len(points)
            return {'id': self.id, 'state': self.state, 'message': self.message, 'request': self.request,
                    'total': self.total, 'done': len(points), 'available': self.available, 'truncated': self.truncated,
                    'megabytes_read': round(self.bytes_read / 1e6, 1),
                    'elapsed_s': round((self.finished or time.time()) - self.created, 1),
                    'points': [{key: point.get(key) for key in POINT_KEYS} for point in points],
                    'analysis': self.analysis, 'method': METHOD}


class SpectrumService:
    def __init__(self, find=archive.exposures_at, reader=measure_remote,
                 cache_dir=CACHE_DIR, workers=WORKERS):
        self.find, self.reader = find, reader
        self.cache_dir, self.workers = Path(cache_dir), workers
        self.jobs, self.lock = {}, threading.Lock()
        self.slots = threading.Semaphore(MAX_RUNNING)

    # -- public -------------------------------------------------------------------------------
    def start(self, ra, dec, limit=DEFAULT_EXPOSURES):
        request = {'kind': 'position', 'ra': round(ra, 6), 'dec': round(dec, 6), 'limit': limit}
        return self._start(request, lambda: self.find(request['ra'], request['dec']))

    def start_moving(self, target_id, name, finder, source, limit=DEFAULT_EXPOSURES):
        """`finder()` returns exposures that each carry the target's predicted position."""
        request = {'kind': 'moving', 'target': target_id, 'name': name, 'position_source': source, 'limit': limit}
        return self._start(request, finder)

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        return job.snapshot() if job else None

    # -- internals ----------------------------------------------------------------------------
    def _start(self, request, finder):
        key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        with self.lock:
            self._prune()
            for job in self.jobs.values():  # The same request shares one job while it is fresh.
                if job.key == key and job.state != 'failed':
                    return job.id
            cached = self._load(key, request)
            if cached is None and sum(job.state in ('queued', 'running') for job in self.jobs.values()) >= MAX_RUNNING + 4:
                raise RuntimeError('busy')
            job = cached or Job(key, request)
            self.jobs[job.id] = job
        if cached is None:
            threading.Thread(target=self._run, args=(job, finder), daemon=True).start()
        return job.id

    def _prune(self):
        now = time.time()
        finished = sorted((job for job in self.jobs.values() if job.finished), key=lambda job: job.finished)
        for job in finished:
            if now - job.finished > CACHE_SECONDS or len(self.jobs) > MAX_JOBS:
                del self.jobs[job.id]

    def _path(self, key):
        return self.cache_dir / f'{key}.json'

    def _load(self, key, request):
        path = self._path(key)
        try:
            if time.time() - path.stat().st_mtime > CACHE_SECONDS:
                return None
            saved = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        job = Job(key, request)
        job.points, job.total, job.available = saved['points'], saved['total'], saved['available']
        job.truncated, job.bytes_read = saved['truncated'], saved['bytes_read']
        job.state, job.message = 'done', 'Served from the local spectrum cache.'
        job.created = time.time() - saved['elapsed_s']
        job.finished = time.time()
        return job

    def _save(self, job):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = self._path(job.key).with_suffix('.tmp')
            temporary.write_text(json.dumps({'points': job.points, 'total': job.total, 'available': job.available,
                                             'truncated': job.truncated, 'bytes_read': job.bytes_read,
                                             'elapsed_s': job.finished - job.created}))
            temporary.replace(self._path(job.key))
        except OSError:
            pass  # The cache is an optimisation only.

    def _run(self, job, finder):
        with self.slots:
            job.state, job.message = 'running', 'Asking the IRSA archive which exposures cover this position…'
            try:
                found = finder()
            except IRSAUnavailable as exc:
                job.state, job.message, job.finished = 'failed', str(exc), time.time()
                return
            except Exception:
                job.state, job.message, job.finished = 'failed', 'The exposure search failed.', time.time()
                return
            chosen, truncated = archive.subsample(found, min(job.request['limit'], MAX_EXPOSURES))
            job.available, job.total, job.truncated = len(found), len(chosen), truncated
            if not chosen:
                job.state, job.message, job.finished = 'done', 'SPHEREx has no public exposure of this position yet.', time.time()
                return
            job.message = 'Measuring the target in each exposure…'
            session = new_session()
            try:
                with ThreadPoolExecutor(self.workers) as pool:
                    futures = [pool.submit(measure_exposure, session, exposure, self.reader) for exposure in chosen]
                    for future in as_completed(futures):
                        point = future.result()
                        with job.lock:
                            job.bytes_read += point.pop('bytes_read', 0) or 0
                            job.points.append(point)
            finally:
                session.close()
            job.finished = time.time()
            measured = sum(point['status'] == 'ok' for point in job.points)
            job.state, job.message = 'done', f'{measured} of {job.total} exposures gave a usable measurement.'
            self._save(job)
