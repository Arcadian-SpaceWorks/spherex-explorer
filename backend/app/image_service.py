"""Small on-disk cache of immutable FITS originals and derived previews."""
from contextlib import contextmanager
import hashlib
import fcntl
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time

from .fits_worker import process_fits
from .image_download import ImageError, ImageSettings, MirrorDownloader, validate_cutout, validate_url
from .progress import BOARD, label_for

TOKEN = re.compile(r'^[a-f0-9]{64}$')


class ImageService:
    """Downloads and decoding run outside the cache lock, so one slow image never blocks the others.

    The lock now covers only short cache steps (lookup, pruning, publishing an entry, reading assets).
    Preparations of the same image share one download; at most `max_preparing` run at once.
    """

    def __init__(self, settings=None, downloader=None, *, max_waiters=4, wait_seconds=720, max_preparing=3, board=None):
        self.settings = settings or ImageSettings.from_env()
        self.downloader = downloader or MirrorDownloader(self.settings)  # Goes straight to IRSA when the mirror is off.
        self.board = board or BOARD
        self.lock = threading.Lock()
        # Bound waiting API threads for cache steps as well as concurrent preparations.
        self.slots = threading.BoundedSemaphore(max_waiters + 1)
        self.wait_seconds = wait_seconds
        self.queue = threading.BoundedSemaphore(max_preparing + max_waiters)
        self.preparing = threading.BoundedSemaphore(max_preparing)
        self.key_guard = threading.Lock()
        self.key_locks = {}

    @contextmanager
    def _admitted(self):
        if not self.queue.acquire(blocking=False):
            raise ImageError('The image viewer queue is full. Please retry shortly.', 503, 'viewer_busy')
        try:
            yield time.monotonic() + self.wait_seconds
        finally:
            self.queue.release()

    @staticmethod
    def _wait(lock, deadline, message):
        if not lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise ImageError(message, 503, 'viewer_busy')

    @contextmanager
    def _single_flight(self, image_id, deadline):
        """Callers preparing the same image wait for the first one and then reuse its cache entry."""
        with self.key_guard:
            entry = self.key_locks.setdefault(image_id, [threading.Lock(), 0])
            entry[1] += 1
        try:
            self._wait(entry[0], deadline, 'Timed out waiting for the same image to finish. Please retry.')
            try:
                yield
            finally:
                entry[0].release()
        finally:
            with self.key_guard:
                entry[1] -= 1
                if not entry[1]:
                    self.key_locks.pop(image_id, None)

    @contextmanager
    def transaction(self):
        if not self.slots.acquire(blocking=False):
            raise ImageError('The image viewer queue is full. Please retry shortly.', 503, 'viewer_busy')
        deadline = time.monotonic() + self.wait_seconds
        acquired = False
        cache_lock = None
        try:
            acquired = self.lock.acquire(timeout=max(0, deadline - time.monotonic()))
            if not acquired:
                raise ImageError('Timed out waiting for the image viewer. Please retry.', 503, 'viewer_busy')
            self.settings.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_lock = (self.settings.cache_dir / '.lock').open('a')
            while True:
                try:
                    fcntl.flock(cache_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ImageError('Timed out waiting for the image cache. Please retry.', 503, 'viewer_busy')
                    time.sleep(min(0.05, remaining))
            yield
        except OSError as exc:
            raise ImageError('The local image cache is unavailable or full.', 507, 'cache_unavailable') from exc
        finally:
            if cache_lock is not None:
                cache_lock.close()
            if acquired:
                self.lock.release()
            self.slots.release()

    @staticmethod
    def _is_cutout(path):
        try:
            return bool(json.loads((path / 'metadata.json').read_text()).get('cutout'))
        except (OSError, ValueError):
            return False

    def _prune(self, reserve=0, cutout=False):
        entries = []
        for path in self.settings.cache_dir.iterdir():
            if path.name.startswith('.part-') and path.is_dir() and not path.is_symlink():
                if time.time() - path.stat().st_mtime > self.settings.cache_ttl:
                    shutil.rmtree(path)
                continue
            if not TOKEN.fullmatch(path.name) or not path.is_dir() or path.is_symlink():
                continue
            if time.time() - path.stat().st_mtime > self.settings.cache_ttl:
                shutil.rmtree(path)
            else:
                entries.append(path)
        entries.sort(key=lambda path: path.stat().st_mtime)
        groups = {False: [], True: []}
        for path in entries:
            groups[self._is_cutout(path)].append(path)
        for kind, group in groups.items():
            limit = self.settings.cutout_cache_entries if kind else self.settings.cache_entries
            extra = reserve if kind == cutout else 0
            for path in group[:max(0, len(group) - limit + extra)]:
                shutil.rmtree(path)

    def _entry(self, image_id):
        if not TOKEN.fullmatch(image_id):
            raise ImageError('Invalid image identifier.', 404, 'cache_miss')
        path = self.settings.cache_dir / image_id
        if not (path / 'metadata.json').is_file() or path.is_symlink():
            raise ImageError('This image is no longer cached. Choose View Image again.', 404, 'cache_miss')
        metadata = json.loads((path / 'metadata.json').read_text())
        if (path / 'original.fits').stat().st_size > self.settings.max_bytes or metadata['width'] * metadata['height'] > self.settings.max_pixels:
            raise ImageError('The cached image exceeds the current configured limits.', 413, 'file_too_large')
        path.touch()
        return path, metadata

    def prepare(self, access_url, ra=None, dec=None, cutout_deg=None):
        validate_url(access_url)
        cutout = None
        if cutout_deg is not None:
            if ra is None or dec is None:
                raise ImageError('A cutout needs a target RA and Dec.', 400, 'invalid_cutout')
            validate_cutout(ra, dec, cutout_deg)
            cutout = (min(round(ra, 6), 359.999999), round(dec, 6), round(cutout_deg, 4))
            cache_key = f'render-v1-cutout:{access_url}|{cutout[0]:.6f}|{cutout[1]:.6f}|{cutout[2]:.4f}'
        else:
            cache_key = 'render-v1:' + access_url
        image_id = hashlib.sha256(cache_key.encode()).hexdigest()
        with self._admitted() as deadline, self._single_flight(image_id, deadline):
            with self.transaction():
                self._prune()
                if (self.settings.cache_dir / image_id / 'metadata.json').is_file():
                    return self._finish(image_id, ra, dec, cached=True)
            detail = f'{cutout[2]:g}° cutout' if cutout else 'full detector image'
            with self.board.job('image', label_for(access_url), detail) as job:
                job.stage('queued')
                self._wait(self.preparing, deadline, 'Timed out waiting for the image viewer. Please retry.')
                try:
                    self._build(image_id, access_url, ra, dec, cutout, job)
                finally:
                    self.preparing.release()
            with self.transaction():
                return self._finish(image_id, ra, dec, cached=False)

    def _build(self, image_id, access_url, ra, dec, cutout, job):
        """Download and decode into a private directory, then publish it under the cache lock."""
        try:
            self.settings.cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.part-', dir=self.settings.cache_dir) as temporary:
                working = Path(temporary)
                source = working / 'original.fits'
                if hasattr(self.downloader, 'fetch'):
                    fits_url, delivery = self.downloader.fetch(access_url, source, cutout, progress=job)
                else:
                    job.stage('downloading')
                    fits_url = (self.downloader.download(access_url, source, cutout=cutout) if cutout
                                else self.downloader.download(access_url, source))
                    delivery = {'source': 'irsa'}
                job.stage('decoding')
                arguments = dict(path=str(source.resolve()), preview_path=str((working / 'preview.png').resolve()),
                                 max_pixels=self.settings.max_pixels)
                if ra is not None:
                    metadata = process_fits('render_target', **arguments, ra=ra, dec=dec)
                    target = metadata.pop('target')
                else:
                    metadata, target = process_fits('render', **arguments), None
                with source.open('rb') as handle:
                    checksum = hashlib.file_digest(handle, 'sha256').hexdigest()
                metadata.update(image_id=image_id, access_url=access_url, fits_url=fits_url, delivery=delivery,
                                cutout=({'ra': cutout[0], 'dec': cutout[1], 'size_deg': cutout[2]} if cutout else None),
                                bytes=source.stat().st_size, sha256=checksum,
                                preview_url=f'/api/images/{image_id}/preview',
                                original_url=f'/api/images/{image_id}/original',
                                stored_target={'ra': ra, 'dec': dec, 'target': target})
                (working / 'metadata.json').write_text(json.dumps(metadata, allow_nan=False))
                with self.transaction():
                    self._prune(reserve=1, cutout=cutout is not None)
                    destination = self.settings.cache_dir / image_id
                    if not (destination / 'metadata.json').is_file():  # Another process may have published it.
                        if destination.exists():
                            shutil.rmtree(destination)
                        working.rename(destination)
        except OSError as exc:
            raise ImageError('The local image cache is unavailable or full.', 507, 'cache_unavailable') from exc

    def _finish(self, image_id, ra, dec, *, cached):
        """Entry metadata for the API; call under the cache lock."""
        path, metadata = self._entry(image_id)
        stored = metadata.pop('stored_target', None) or {}
        metadata['cache_hit'] = cached
        if ra is None:
            metadata['target'] = None
        elif stored.get('ra') == ra and stored.get('dec') == dec:
            metadata['target'] = stored.get('target')
        else:
            metadata['target'] = process_fits('target', path=str((path / 'original.fits').resolve()), ra=ra, dec=dec,
                                              max_pixels=self.settings.max_pixels)
        return metadata

    def open_asset(self, image_id, kind):
        with self.transaction():
            self._prune()
            path, _ = self._entry(image_id)
            # Open under the lock. POSIX open handles survive later cache eviction.
            return (path / ('original.fits' if kind == 'original' else 'preview.png')).open('rb')

    def metadata(self, image_id):
        """Metadata of a cached image (404 if it is not, or no longer, cached)."""
        with self.transaction():
            self._prune()
            _, metadata = self._entry(image_id)
            return metadata

    def copy_original(self, image_id, destination):
        """Copy a cached original FITS under the cache lock, so eviction cannot remove it mid-read."""
        with self.transaction():
            self._prune()
            path, metadata = self._entry(image_id)
            shutil.copyfile(path / 'original.fits', destination)
            return metadata

    def pixel(self, image_id, x, y):
        with self.transaction():
            self._prune()
            path, _ = self._entry(image_id)
            return process_fits('pixel', path=str((path / 'original.fits').resolve()), x=x, y=y, max_pixels=self.settings.max_pixels)
