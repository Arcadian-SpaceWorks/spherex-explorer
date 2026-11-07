"""Validated, immutable demo bundles. No archive/network access in this module."""
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .fits_worker import process_fits
from .image_download import ImageError, validate_url

DEFAULT_ROOT = Path(os.environ.get('SKYTRACKER_DEMO_DIR', str(Path(__file__).resolve().parents[2] / 'frontend' / 'public' / 'demo')))
ASSET = re.compile(r'^/demo/assets/[a-f0-9]{64}/(?:metadata.json|preview.png|original.fits)$')
SHA = r'^[a-f0-9]{64}$'


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Spectral(Model):
    wavelength_um: float = Field(gt=0)
    bandwidth_um: float = Field(gt=0)
    source: str
    approximate: Literal[True]


class Provenance(Model):
    verification: str = Field(min_length=1)
    renderer: Literal['backend.app.fits_image.render_fits']
    renderer_sha256: str = Field(pattern=SHA)
    versions: dict[str, str]
    registration: Literal['native detector; no spatial registration']
    normalization: str = Field(min_length=1)
    science_values: Literal['original FITS copied byte-for-byte']
    source_sha256: str = Field(pattern=SHA)


class Observation(Model):
    image_id: str = Field(pattern=SHA)
    obs_id: str = Field(min_length=1)
    access_url: str
    source_url: str
    observed_at_utc: str
    detector: int = Field(ge=1, le=6)
    spectral: Spectral | None
    preview_path: str
    metadata_path: str
    fits_path: str
    fits_sha256: str = Field(pattern=SHA)
    preview_sha256: str = Field(pattern=SHA)
    metadata_sha256: str = Field(pattern=SHA)
    provenance: Provenance

    @model_validator(mode='after')
    def scientific_record(self):
        from astropy.time import Time
        from urllib.parse import urlsplit, parse_qs
        validate_url(self.access_url)
        validate_url(self.source_url)
        if not self.observed_at_utc.endswith('Z'):
            raise ValueError('Demo timestamps must explicitly identify UTC with Z')
        Time(self.observed_at_utc[:-1], format='isot', scale='utc')
        if re.search(r'synthetic|fixture|test-only|demo', self.obs_id, re.I):
            raise ValueError('Demo bundles require actual observations, not synthetic observations')
        if not urlsplit(self.source_url).path.startswith('/ibe/data/spherex/'):
            raise ValueError('Expected an IRSA SPHEREx image-server source')
        query = parse_qs(urlsplit(self.source_url).query)
        if not {'center', 'size'} <= query.keys():
            raise ValueError('A documented cutout source URL is required')
        for field, filename in [('preview_path', 'preview.png'), ('metadata_path', 'metadata.json'), ('fits_path', 'original.fits')]:
            if getattr(self, field) != f'/demo/assets/{self.image_id}/{filename}':
                raise ValueError('Asset path must match the observation image ID')
        if self.provenance.source_sha256 != self.fits_sha256:
            raise ValueError('Provenance checksum differs from science FITS')
        return self


class Target(Model):
    id: str = Field(pattern=r'^[a-z0-9-]+$')
    name: str = Field(min_length=1)
    ra: float = Field(ge=0, lt=360)
    dec: float = Field(ge=-90, le=90)
    coordinate_source: str
    status: Literal['ready', 'missing']
    missing_reason: str | None = None
    observations: list[Observation]

    @model_validator(mode='after')
    def availability(self):
        if (self.status == 'ready') != bool(self.observations):
            raise ValueError('Ready targets need observations; missing targets must have none')
        if self.status == 'missing' and not self.missing_reason:
            raise ValueError('Missing targets require an explanation')
        keys = [item.image_id for item in self.observations]
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate observations')
        if not self.coordinate_source.startswith('https://'):
            raise ValueError('Coordinate source reference is required')
        return self


class Manifest(Model):
    schema_version: Literal[1]
    science_note: str = Field(min_length=1)
    targets: list[Target] = Field(min_length=2, max_length=3)

    @model_validator(mode='after')
    def unique(self):
        if len({t.id for t in self.targets}) != len(self.targets):
            raise ValueError('Duplicate target IDs')
        ids = [o.image_id for t in self.targets for o in t.observations]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate image IDs')
        return self


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def asset_path(root, url):
    if not ASSET.fullmatch(url):
        raise ValueError('Unsafe demo asset path')
    path = (Path(root) / url.removeprefix('/demo/')).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Demo asset escapes bundle directory')
    return path


def validate_bundle(root, *, check_files=True):
    root = Path(root)
    manifest = Manifest.model_validate_json((root / 'manifest.json').read_text())
    if check_files:
        for target in manifest.targets:
            for observation in target.observations:
                for kind in ('fits', 'preview', 'metadata'):
                    path = asset_path(root, getattr(observation, f'{kind}_path'))
                    if not path.is_file():
                        raise ValueError(f'Missing demo asset: {path.name} ({target.id})')
                    if digest(path) != getattr(observation, f'{kind}_sha256'):
                        raise ValueError(f'Checksum mismatch: {path.name} ({target.id})')
                metadata = json.loads(asset_path(root, observation.metadata_path).read_text())
                if (metadata.get('observation_id') != observation.obs_id
                        or metadata.get('detector') != observation.detector
                        or str(metadata.get('observed_at_utc')).removesuffix('Z') != observation.observed_at_utc.removesuffix('Z')
                        or metadata.get('preview_url') != observation.preview_path
                        or metadata.get('original_url') != observation.fits_path
                        or metadata.get('fits_url') != observation.source_url
                        or metadata.get('sha256') != observation.fits_sha256):
                    raise ValueError('Image metadata differs from manifest scientific identity')
    return manifest


router = APIRouter(prefix='/api/demo', tags=['Preloaded demo'])
_slots = threading.BoundedSemaphore(2)


@router.get('/images/{image_id}/pixel')
def demo_pixel(image_id: str, x: int = Query(..., ge=0), y: int = Query(..., ge=0)):
    # Local science readout only. Static previews never acquire this semaphore.
    try:
        manifest = validate_bundle(DEFAULT_ROOT, check_files=False)
        observation = next((o for t in manifest.targets for o in t.observations if o.image_id == image_id), None)
        if observation is None:
            raise ImageError('Unknown preloaded science image.', 404, 'demo_missing')
        path = asset_path(DEFAULT_ROOT, observation.fits_path)
        if not path.is_file() or digest(path) != observation.fits_sha256:
            raise ValueError('Preloaded FITS missing or checksum mismatch')
    except (OSError, ValueError) as exc:
        raise ImageError('Preloaded science data unavailable. Validate or prepare the demo bundle.', 503, 'demo_missing') from exc
    if not _slots.acquire(timeout=5):
        raise ImageError('Science pixel readout is busy. Please retry.', 503, 'demo_busy')
    try:
        return process_fits('pixel', path=str(path), x=x, y=y, max_pixels=8_000_000)
    finally:
        _slots.release()
