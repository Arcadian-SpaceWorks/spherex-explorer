"""Compare two SPHEREx images held in (or fetched into) the existing image cache, or preloaded
in the local demo bundle.

Live inputs are resolved through ImageService, so downloads keep its URL allowlist, size limits and
locks. Demo inputs are read from the validated demo bundle (checksum verified) with no network. The comparison itself runs in the isolated FITS worker. Results (metadata and PNGs, no
FITS copies) live in a small separate cache keyed by the input checksums and parameters.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time

from .analysis.compare import cutout_size_for_grid
from .fits_worker import process_fits
from .image_download import ImageError

TOKEN = re.compile(r'^[a-f0-9]{64}$')
PREVIEW_ROLES = ('a', 'b', 'difference')


@dataclass(frozen=True)
class CompareCacheSettings:
    cache_dir: Path = Path(__file__).resolve().parents[2] / '.cache' / 'arcadian-compare-v1'
    entries: int = 6
    ttl: int = 3600

    @classmethod
    def from_env(cls):
        settings = cls(cache_dir=Path(os.getenv('SKYTRACKER_COMPARE_CACHE_DIR', str(cls.cache_dir))),
                       entries=int(os.getenv('SKYTRACKER_COMPARE_CACHE_ENTRIES', cls.entries)),
                       ttl=int(os.getenv('SKYTRACKER_COMPARE_CACHE_TTL', cls.ttl)))
        if settings.entries <= 0 or settings.ttl <= 0:
            raise ValueError('Compare cache limits must be positive integers')
        return settings


def _notes(result, frames, demo=False):
    notes = [('Real NASA/IPAC IRSA SPHEREx cutouts preloaded in the local demo bundle; no network was used. '
              if demo else 'Real NASA/IPAC IRSA SPHEREx data, downloaded through this server\'s image cache. ')
             + 'No motion, variability or discovery is claimed.']
    if result['stretch']['shared']:
        notes.append('A and B share one brightness scale, so their brightness can be compared.')
    else:
        notes.append('A and B each have their own brightness scale; do not compare their brightness by eye.')
    if result['validation']['mode'] == 'wavelength':
        notes.append('Different wavelengths: shown side by side or blinked, never subtracted.')
    smaller = [frame['role'].upper() for frame in frames
               if frame.get('cutout') and frame['cutout']['size_deg'] < result['cutout_deg_used'] - 1e-6]
    if smaller:
        notes.append(f'Image {" and ".join(smaller)} is a cutout smaller than the {result["cutout_deg_used"]:.3f} deg '
                     'needed to fill the north-up grid, so its corners may be empty.')
    return notes


class CompareService:
    def __init__(self, images, settings=None, *, max_active=2, demo_root=None):
        self.images = images
        self.settings = settings or CompareCacheSettings.from_env()
        self.demo_root = demo_root  # None: the app's demo bundle (backend.app.demo.DEFAULT_ROOT).
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(max_active)

    def _resolve_demo(self, image_id):
        from . import demo
        root = Path(self.demo_root or demo.DEFAULT_ROOT)
        try:
            manifest = demo.validate_bundle(root, check_files=False)
            observation = next((o for t in manifest.targets for o in t.observations if o.image_id == image_id), None)
            if observation is None:
                raise ImageError('Unknown preloaded image. Reload Demo Mode.', 404, 'demo_missing')
            path = demo.asset_path(root, observation.fits_path)
            if not path.is_file() or demo.digest(path) != observation.fits_sha256:
                raise ValueError('Preloaded FITS missing or checksum mismatch')
            metadata = json.loads(demo.asset_path(root, observation.metadata_path).read_text())
        except (OSError, ValueError) as exc:
            raise ImageError('Preloaded science data unavailable. Validate or prepare the demo bundle.', 503, 'demo_missing') from exc
        return {'image_id': image_id, 'sha256': observation.fits_sha256, 'cutout': metadata.get('cutout'),
                'access_url': observation.access_url, 'fits_url': observation.source_url, 'demo': True, 'path': path}

    def _resolve(self, ref, ra, dec, size_deg):
        if ref.get('demo_image_id'):
            return self._resolve_demo(ref['demo_image_id'])
        if ref.get('image_id'):
            return self.images.metadata(ref['image_id'])
        return self.images.prepare(ref['access_url'], ra, dec, round(cutout_size_for_grid(size_deg), 4))

    def _prune(self):
        entries = []
        for path in self.settings.cache_dir.iterdir():
            expired = time.time() - path.stat().st_mtime > self.settings.ttl
            if path.name.startswith('.part-') and path.is_dir() and not path.is_symlink():
                if expired:
                    shutil.rmtree(path)
            elif TOKEN.fullmatch(path.name) and path.is_dir() and not path.is_symlink():
                if expired:
                    shutil.rmtree(path)
                else:
                    entries.append(path)
        entries.sort(key=lambda path: path.stat().st_mtime)
        for path in entries[:max(0, len(entries) - self.settings.entries + 1)]:
            shutil.rmtree(path)

    def _cached(self, compare_id):
        path = self.settings.cache_dir / compare_id
        if path.is_symlink() or not (path / 'metadata.json').is_file():
            return None
        path.touch()
        return json.loads((path / 'metadata.json').read_text())

    def compare(self, a, b, ra, dec, size_deg, mode, match_scale=False):
        if not self.slots.acquire(blocking=False):
            raise ImageError('The comparison service is busy. Please retry shortly.', 503, 'compare_busy')
        try:
            inputs = [self._resolve(ref, ra, dec, size_deg) for ref in (a, b)]
            demo = all(meta.get('demo') for meta in inputs)
            key = json.dumps({'v': 'compare-v1', 'a': inputs[0]['sha256'], 'b': inputs[1]['sha256'], 'demo': demo,
                              'ra': round(ra, 6), 'dec': round(dec, 6), 'size': round(size_deg, 4),
                              'mode': mode, 'match_scale': bool(match_scale)}, sort_keys=True)
            compare_id = hashlib.sha256(key.encode()).hexdigest()
            self.settings.cache_dir.mkdir(parents=True, exist_ok=True)
            with self.lock:
                cached = self._cached(compare_id)
            if cached:
                return {**cached, 'cache_hit': True}
            with tempfile.TemporaryDirectory(prefix='.part-', dir=self.settings.cache_dir) as temporary:
                working = Path(temporary)
                for role, meta in zip('ab', inputs):
                    if meta.get('demo'):
                        shutil.copyfile(meta['path'], working / f'{role}.fits')
                    else:
                        self.images.copy_original(meta['image_id'], working / f'{role}.fits')
                result = process_fits('compare', path_a=str((working / 'a.fits').resolve()),
                                      path_b=str((working / 'b.fits').resolve()), ra=ra, dec=dec,
                                      size_deg=size_deg, mode=mode, out_dir=str(working.resolve()),
                                      source_a='irsa_cutout' if inputs[0].get('cutout') else 'irsa_full_file',
                                      source_b='irsa_cutout' if inputs[1].get('cutout') else 'irsa_full_file',
                                      match_scale=bool(match_scale))
                for role in 'ab':
                    (working / f'{role}.fits').unlink()  # Keep only small derived products.
                frames = []
                for frame, meta in zip(result['frames'], inputs):
                    frames.append({**frame, 'image_id': meta['image_id'], 'access_url': meta.get('access_url'),
                                   'fits_url': meta.get('fits_url'), 'cutout': meta.get('cutout'),
                                   'sha256': meta['sha256'], 'demo': bool(meta.get('demo'))})
                previews = {role: (f'/api/compare/{compare_id}/{role}.png' if role in result['previews'] else None)
                            for role in PREVIEW_ROLES}
                metadata = {**result, 'compare_id': compare_id, 'frames': frames, 'previews': previews,
                            'notes': _notes(result, frames, demo)}
                (working / 'metadata.json').write_text(json.dumps(metadata, allow_nan=False))
                with self.lock:
                    if not (self.settings.cache_dir / compare_id).exists():
                        self._prune()
                        working.rename(self.settings.cache_dir / compare_id)
            return {**metadata, 'cache_hit': False}
        finally:
            self.slots.release()

    def open_preview(self, compare_id, role):
        if not TOKEN.fullmatch(compare_id) or role not in PREVIEW_ROLES:
            raise ImageError('Unknown comparison preview.', 404, 'compare_missing')
        with self.lock:
            metadata = self._cached(compare_id)
            if metadata is None:
                raise ImageError('This comparison is no longer cached. Run it again.', 404, 'compare_missing')
            if not metadata['previews'].get(role):
                raise ImageError('No difference image exists for this pair; it was not allowed.', 404, 'difference_not_allowed')
            return (self.settings.cache_dir / compare_id / f'{role}.png').open('rb')
