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
from .image_download import ImageError, ImageSettings, IRSAImageDownloader, validate_url

TOKEN = re.compile(r'^[a-f0-9]{64}$')


class ImageService:
    def __init__(self, settings=None, downloader=None):
        self.settings = settings or ImageSettings.from_env()
        self.downloader = downloader or IRSAImageDownloader(self.settings)
        self.lock = threading.Lock()

    @contextmanager
    def transaction(self):
        # One bounded download/render at a time; no unbounded queue of large jobs.
        if not self.lock.acquire(blocking=False):
            raise ImageError('The image viewer is processing another file. Please retry shortly.', 503, 'viewer_busy')
        cache_lock = None
        try:
            self.settings.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_lock = (self.settings.cache_dir / '.lock').open('a')
            try:
                fcntl.flock(cache_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ImageError('The image cache is busy. Please retry shortly.', 503, 'viewer_busy') from exc
            yield
        except OSError as exc:
            raise ImageError('The local image cache is unavailable or full.', 507, 'cache_unavailable') from exc
        finally:
            if cache_lock is not None:
                cache_lock.close()
            self.lock.release()

    def _prune(self, reserve=0):
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
        for path in entries[:max(0, len(entries) - self.settings.cache_entries + reserve)]:
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

    def prepare(self, access_url, ra=None, dec=None):
        validate_url(access_url)
        image_id = hashlib.sha256(('render-v1:' + access_url).encode()).hexdigest()
        with self.transaction():
            self._prune()
            cached = (self.settings.cache_dir / image_id / 'metadata.json').is_file()
            if not cached:
                self._prune(reserve=1)
                with tempfile.TemporaryDirectory(prefix='.part-', dir=self.settings.cache_dir) as temporary:
                    working = Path(temporary)
                    source = working / 'original.fits'
                    fits_url = self.downloader.download(access_url, source)
                    metadata = process_fits('render', path=str(source.resolve()), preview_path=str((working / 'preview.png').resolve()), max_pixels=self.settings.max_pixels)
                    with source.open('rb') as handle:
                        checksum = hashlib.file_digest(handle, 'sha256').hexdigest()
                    metadata.update(image_id=image_id, access_url=access_url, fits_url=fits_url,
                                    bytes=source.stat().st_size, sha256=checksum,
                                    preview_url=f'/api/images/{image_id}/preview',
                                    original_url=f'/api/images/{image_id}/original')
                    (working / 'metadata.json').write_text(json.dumps(metadata, allow_nan=False))
                    working.rename(self.settings.cache_dir / image_id)
            path, metadata = self._entry(image_id)
            metadata['cache_hit'] = cached
            metadata['target'] = process_fits('target', path=str((path / 'original.fits').resolve()), ra=ra, dec=dec, max_pixels=self.settings.max_pixels) if ra is not None else None
            return metadata

    def open_asset(self, image_id, kind):
        with self.transaction():
            self._prune()
            path, _ = self._entry(image_id)
            # Open under the lock. POSIX open handles survive later cache eviction.
            return (path / ('original.fits' if kind == 'original' else 'preview.png')).open('rb')

    def pixel(self, image_id, x, y):
        with self.transaction():
            self._prune()
            path, _ = self._entry(image_id)
            return process_fits('pixel', path=str((path / 'original.fits').resolve()), x=x, y=y, max_pixels=self.settings.max_pixels)
