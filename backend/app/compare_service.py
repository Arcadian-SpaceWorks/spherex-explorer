"""Compare two SPHEREx images held in (or fetched into) the existing image cache.

Inputs are resolved through ImageService, so downloads keep its URL allowlist, size limits and
locks. The comparison itself runs in the isolated FITS worker. Results (metadata and PNGs, no
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


def _notes(result, frames):
    notes = ['Real NASA/IPAC IRSA SPHEREx data from verified local assets or the image cache. '
             'No motion, variability or discovery is claimed.']
    if result['stretch']['shared']:
        notes.append('A and B share one brightness scale, for visual comparison; this does not establish photometric equivalence.')
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
    def __init__(self, images, settings=None, *, max_active=2):
        self.images = images
        self.settings = settings or CompareCacheSettings.from_env()
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(max_active)

    def _resolve(self, ref, ra, dec, size_deg):
        if ref.get('demo_image_id'):
            from .demo import DEFAULT_ROOT, validate_bundle, asset_path, digest
            try:
                manifest = validate_bundle(DEFAULT_ROOT, check_files=False)
                observation = next((o for t in manifest.targets for o in t.observations if o.image_id == ref['demo_image_id']), None)
                if observation is None:
                    raise ValueError('Unknown preloaded observation')
                path = asset_path(DEFAULT_ROOT, observation.fits_path)
                if digest(path) != observation.fits_sha256:
                    raise ValueError('Preloaded FITS checksum mismatch')
                from urllib.parse import parse_qs, urlsplit
                size = float(parse_qs(urlsplit(observation.source_url).query)['size'][0].removesuffix('deg'))
                return {'image_id': observation.image_id, 'sha256': observation.fits_sha256,
                        'access_url': observation.access_url, 'fits_url': observation.source_url,
                        'cutout': {'size_deg': size}, '_demo_path': path}
            except (ValueError, OSError, KeyError) as exc:
                raise ImageError('Preloaded observation unavailable or failed verification.', 422, 'demo_invalid') from exc
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
            key = json.dumps({'v': 'compare-v5-final-real-analysis', 'a': inputs[0]['sha256'], 'b': inputs[1]['sha256'],
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
                    if meta.get('_demo_path'):
                        shutil.copyfile(meta['_demo_path'], working / f'{role}.fits')
                    else:
                        self.images.copy_original(meta['image_id'], working / f'{role}.fits')
                result = process_fits('compare', path_a=str((working / 'a.fits').resolve()),
                                      path_b=str((working / 'b.fits').resolve()), ra=ra, dec=dec,
                                      size_deg=size_deg, mode=mode, out_dir=str(working.resolve()),
                                      source_a='verified_local_irsa_cutout' if inputs[0].get('_demo_path') else ('irsa_cutout' if inputs[0].get('cutout') else 'irsa_full_file'),
                                      source_b='verified_local_irsa_cutout' if inputs[1].get('_demo_path') else ('irsa_cutout' if inputs[1].get('cutout') else 'irsa_full_file'),
                                      match_scale=bool(match_scale))
                for role in 'ab':
                    (working / f'{role}.fits').unlink()  # Keep only small derived products.
                frames = []
                for frame, meta in zip(result['frames'], inputs):
                    frames.append({**frame, 'image_id': meta['image_id'], 'access_url': meta.get('access_url'),
                                   'fits_url': meta.get('fits_url'), 'cutout': meta.get('cutout'),
                                   'sha256': meta['sha256']})
                previews = {role: (f'/api/compare/{compare_id}/{role}.png' if role in result['previews'] else None)
                            for role in PREVIEW_ROLES}
                metadata = {**result, 'compare_id': compare_id, 'frames': frames, 'previews': previews,
                            'notes': _notes(result, frames)}
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
