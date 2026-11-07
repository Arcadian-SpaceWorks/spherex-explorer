"""Deterministic synthetic FITS fixtures test preparation; never shipped as demo data."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from astropy.io import fits
from fastapi.testclient import TestClient
import pytest

from backend.app.demo import Manifest, asset_path, digest, validate_bundle
from backend.app.main import app
from backend.app.image_download import ImageError
from backend.tests.test_images import make_mef
from scripts.prepare_demo import prepare


@pytest.fixture
def inventory(tmp_path):
    source = make_mef(tmp_path / 'synthetic-test-only.fits')
    # Real-shaped identity used solely for a tiny synthetic test fixture.
    obs_id = '2025W01_1A_0001_1'
    with fits.open(source, mode='update') as hdul:
        hdul['IMAGE'].header['OBSID'] = obs_id
        hdul['IMAGE'].header['TIMESYS'] = 'UTC'
    url = f'https://irsa.ipac.caltech.edu/ibe/data/spherex/qr2/level2/{obs_id}D2.fits?center=210.000000,54.000000&size=0.3000deg'
    record = dict(sha256=digest(source), cutout=dict(ra=210., dec=54., size_deg=.3), fits_url=url,
                  access_url=f'https://irsa.ipac.caltech.edu/datalink/links/spherex?ID={obs_id}/D2',
                  observation_id=obs_id, observed_at_utc='2026-06-24T03:19:00.048', detector=2)
    metadata = tmp_path / 'source.json'
    metadata.write_text(json.dumps(record))
    target = dict(id='test-region', name='Synthetic test region; not distributed', ra=210., dec=54.,
                  coordinate_source='https://example.org/test-only', inputs=[dict(fits=source.name, metadata=metadata.name)])
    missing = dict(id='unprepared', name='Unprepared test region', ra=10., dec=41., coordinate_source='https://example.org/test-only', inputs=[])
    config = tmp_path / 'inventory.json'
    config.write_text(json.dumps(dict(schema_version=1, targets=[target, missing])))
    return config, source, metadata


def test_offline_prepare_preserves_original_and_is_reproducible(inventory, tmp_path):
    config, source, _ = inventory
    with patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')):
        first = prepare(config, tmp_path / 'first')
        prepare(config, tmp_path / 'second')
    assert first.targets[0].status == 'ready'
    assert first.targets[1].status == 'missing'
    for path in (tmp_path / 'first').rglob('*'):
        if path.is_file():
            assert path.read_bytes() == (tmp_path / 'second' / path.relative_to(tmp_path / 'first')).read_bytes()
    row = first.targets[0].observations[0]
    assert asset_path(tmp_path / 'first', row.fits_path).read_bytes() == source.read_bytes()
    assert row.observed_at_utc == '2026-06-24T03:19:00.048Z'
    with pytest.raises(ValueError, match='already exists'):
        prepare(config, tmp_path / 'first')


def test_missing_and_corrupted_assets_are_rejected(inventory, tmp_path):
    config, _, _ = inventory
    manifest = prepare(config, tmp_path / 'bundle')
    preview = asset_path(tmp_path / 'bundle', manifest.targets[0].observations[0].preview_path)
    preview.write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='Checksum'):
        validate_bundle(tmp_path / 'bundle')
    preview.unlink()
    with pytest.raises(ValueError, match='Missing demo asset'):
        validate_bundle(tmp_path / 'bundle')


@pytest.mark.parametrize('change', ['checksum', 'timestamp', 'identity', 'coverage', 'timescale'])
def test_rejects_unverified_inputs_without_publishing(inventory, tmp_path, change):
    config, source, metadata = inventory
    record = json.loads(metadata.read_text())
    if change == 'checksum': record['sha256'] = '0' * 64
    if change == 'timestamp': record['observed_at_utc'] = '2020-01-01T00:00:00'
    if change == 'identity': record['fits_url'] = record['fits_url'].replace('D2', 'D3')
    if change == 'timescale':
        with fits.open(source, mode='update') as hdul:
            hdul['IMAGE'].header['TIMESYS'] = 'TT'
        record['sha256'] = digest(source)
    if change == 'coverage':
        data = json.loads(config.read_text()); data['targets'][0]['ra'] = 10
        config.write_text(json.dumps(data))
    metadata.write_text(json.dumps(record))
    with pytest.raises(ValueError): prepare(config, tmp_path / 'bundle')
    assert not (tmp_path / 'bundle').exists()


@pytest.mark.parametrize('change', ['version', 'duplicate', 'utc', 'path', 'synthetic', 'source', 'status'])
def test_manifest_validation(inventory, tmp_path, change):
    config, _, _ = inventory
    data = prepare(config, tmp_path / 'bundle').model_dump()
    if change == 'version': data['schema_version'] = 9
    if change == 'duplicate': data['targets'].append(deepcopy(data['targets'][0]))
    if change == 'utc': data['targets'][0]['observations'][0]['observed_at_utc'] = '2026-02-30T00:00:00Z'
    if change == 'path': data['targets'][0]['observations'][0]['preview_path'] = 'https://evil.test/p.png'
    if change == 'synthetic': data['targets'][0]['observations'][0]['obs_id'] = 'SYNTHETIC-FIXTURE'
    if change == 'source': data['targets'][0]['observations'][0]['source_url'] = 'https://evil.test/a.fits'
    if change == 'status': data['targets'][1]['status'] = 'ready'
    with pytest.raises((ValueError, ImageError)):
        Manifest.model_validate(data)


def test_pixel_readout_uses_local_science_fits_without_live_cache(inventory, tmp_path):
    config, _, _ = inventory
    manifest = prepare(config, tmp_path / 'bundle')
    row = manifest.targets[0].observations[0]
    with patch('backend.app.demo.DEFAULT_ROOT', tmp_path / 'bundle'), \
         patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')):
        with TestClient(app) as client:
            response = client.get(f'/api/demo/images/{row.image_id}/pixel?x=2&y=3')
            assert response.status_code == 200
            assert response.json()['value'] == 26
            assert client.get(f'/api/demo/images/{row.image_id}/pixel?x=999&y=0').status_code == 422
            assert client.get('/api/demo/images/unknown/pixel?x=0&y=0').status_code == 404
            asset_path(tmp_path / 'bundle', row.fits_path).unlink()
            assert client.get(f'/api/demo/images/{row.image_id}/pixel?x=0&y=0').status_code == 503


def test_shipped_real_bundle_validates():
    root = Path(__file__).resolve().parents[2] / 'frontend/public/demo'
    manifest = validate_bundle(root)
    assert len(manifest.targets[0].observations) == 3
    assert manifest.targets[1].status == 'missing'
