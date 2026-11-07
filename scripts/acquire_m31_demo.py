"""Acquire the curated M31 demo set: three survey passes, each in detector D1 and D4.

These are the observations validated by scripts/smoke_compare.py (time ACCEPT, time WARN and
D1 vs D4 wavelength pairs). Cutouts are 0.437 deg, the size /api/compare needs to fill its
north-up 0.3 deg grid. Downloads go through the app's ImageService (IRSA allowlist, limits),
sequentially, and are reused when already present with a matching checksum.

Writes:
  demo/acquired/m31/<image_id>.fits           staging copy (git-ignored)
  demo/source-records/<sha256>.json           source record, same format as the M101 records
  demo/acquired/m31/inputs.json               inventory entries for demo/targets.json
Never edits the published bundle; run prepare_demo.py afterwards.

Usage (needs internet):  .venv/bin/python scripts/acquire_m31_demo.py
"""
from dataclasses import replace
import json
from pathlib import Path
import os
import sys

from astropy.io import fits
from astropy.time import Time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.analysis.compare import cutout_size_for_grid  # noqa: E402
from backend.app.demo import digest  # noqa: E402
from backend.app.image_download import ImageSettings  # noqa: E402
from backend.app.image_service import ImageService  # noqa: E402
from backend.app.irsa import IRSAClient  # noqa: E402

RA, DEC = 10.684708333333333, 41.26875  # Must match the m31 entry in demo/targets.json.
CUTOUT_DEG = round(cutout_size_for_grid(0.3), 4)
SELECTION = [(obs_id, detector) for obs_id in ('2025W28_1B_0480_4', '2026W01_1A_0471_1', '2026W28_2A_0117_1')
             for detector in (1, 4)]
STAGING = ROOT / 'demo' / 'acquired' / 'm31'


def main():
    STAGING.mkdir(parents=True, exist_ok=True)
    client = IRSAClient()
    rows = {}
    for detector in (1, 4):
        for row in client.observations(RA, DEC, band=f'SPHEREx-D{detector}')['observations']:
            rows[(row['obs_id'], detector)] = row
    images = ImageService(replace(ImageSettings.from_env(), cutout_cache_entries=8))
    inputs, failures = [], []
    for obs_id, detector in SELECTION:
        row = rows.get((obs_id, detector))
        label = f'{obs_id} D{detector}'
        try:
            if row is None:
                raise ValueError('not found in the IRSA search for M31')
            meta = images.prepare(row['access_url'], RA, DEC, CUTOUT_DEG)
            staged = STAGING / f'{meta["sha256"]}.fits'
            if not staged.exists() or digest(staged) != meta['sha256']:
                images.copy_original(meta['image_id'], staged)
            if digest(staged) != meta['sha256']:
                raise ValueError('checksum of the staged FITS differs from the download record')
            with fits.open(staged, memmap=False) as hdul:
                header = hdul['IMAGE'].header
                if header.get('TIMESYS', hdul[0].header.get('TIMESYS')) != 'UTC':
                    raise ValueError('FITS does not declare TIMESYS=UTC')
            if meta['observation_id'] != obs_id or meta['detector'] != detector:
                raise ValueError(f'FITS identity {meta["observation_id"]} D{meta["detector"]} differs from the archive row')
            seconds = abs(Time(meta['observed_at_utc'], format='isot', scale='utc').mjd - row['t_min']) * 86400
            if seconds > 1:
                raise ValueError(f'FITS time differs from the archive time by {seconds:.1f} s')
            if (meta.get('target') or {}).get('status') != 'inside':
                raise ValueError('M31 is outside the cutout or the WCS is unusable')
            record = ROOT / 'demo' / 'source-records' / f'{meta["sha256"]}.json'
            record.write_text(json.dumps({key: value for key, value in meta.items() if key not in ('cache_hit', 'target')}))
            inputs.append({'fits': os.path.relpath(staged, ROOT / 'demo'), 'metadata': os.path.relpath(record, ROOT / 'demo')})
            print(f'OK      {label}  {staged.stat().st_size / 1e6:.1f} MB  {meta["observed_at_utc"]}  '
                  f'{(meta["target"].get("spectral") or {}).get("wavelength_um", float("nan")):.4f} um', flush=True)
        except Exception as exc:  # Report every frame; one failure does not stop the others.
            failures.append({'obs_id': obs_id, 'detector': detector, 'error': str(exc)})
            print(f'FAILED  {label}  {exc}', flush=True)
    (STAGING / 'inputs.json').write_text(json.dumps({'inputs': inputs, 'failures': failures}, indent=2) + '\n')
    print(f'{len(inputs)} acquired, {len(failures)} failed. Inventory: {STAGING / "inputs.json"}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
