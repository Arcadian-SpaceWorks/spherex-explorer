"""What the server is fetching right now, for the always-visible download panel.

Only measured facts are reported: bytes received and, when the remote server states it, the total.
There are no estimates. Like the image service's thread locks, this assumes one API process.
"""
from contextlib import contextmanager
import itertools
import threading
import time
from urllib.parse import parse_qs, urlsplit

LINGER_SECONDS = 2.5  # A finished row stays briefly, so a fast job is still seen to complete.


class NullProgress:
    def stage(self, name, source=None):
        pass

    def received(self, done, total):
        pass


NULL_PROGRESS = NullProgress()


class Job:
    def __init__(self, lock, number, kind, label, detail):
        self.lock, self.number, self.kind, self.label, self.detail = lock, number, kind, label, detail
        self.current, self.source, self.done, self.total = 'starting', None, 0, None
        self.state, self.started, self.finished = 'active', time.monotonic(), None

    def stage(self, name, source=None):
        with self.lock:
            self.current = name
            if source is not None:
                self.source = source
            if name == 'downloading':  # A fallback to IRSA starts counting again.
                self.done, self.total = 0, None

    def received(self, done, total):
        with self.lock:
            self.done, self.total = done, total

    def close(self, ok):
        with self.lock:
            self.state, self.finished = 'done' if ok else 'failed', time.monotonic()

    def as_dict(self, now):
        return {'id': self.number, 'kind': self.kind, 'label': self.label, 'detail': self.detail,
                'stage': self.current, 'source': self.source, 'bytes': self.done, 'total': self.total,
                'state': self.state, 'elapsed_seconds': round((self.finished or now) - self.started, 1)}


class ProgressBoard:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = []
        self.numbers = itertools.count(1)

    @contextmanager
    def job(self, kind, label, detail=None):
        with self.lock:
            job = Job(self.lock, next(self.numbers), kind, label, detail)
            self.jobs.append(job)
        try:
            yield job
        except BaseException:
            job.close(False)
            raise
        job.close(True)

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            self.jobs = [job for job in self.jobs if job.finished is None or now - job.finished < LINGER_SECONDS]
            return [job.as_dict(now) for job in self.jobs]


BOARD = ProgressBoard()


def label_for(access_url):
    """Short observation name from a DataLink or product URL, for display only."""
    parts = urlsplit(access_url)
    identifier = parse_qs(parts.query).get('ID', [''])[0]
    if identifier:
        return identifier.rsplit('?', 1)[-1].replace('/', ' · ')
    return parts.path.rsplit('/', 1)[-1].removesuffix('.fits') or 'SPHEREx image'
