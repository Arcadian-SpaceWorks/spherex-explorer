"""Live check (needs internet): search IRSA at a sky point, then request small cutouts of the newest
observations through the same code the web app uses, and print timings.

Usage (from the repository root):
    .venv/bin/python scripts/smoke_cutout.py [RA DEC [SIZE_DEG]]
Defaults: M31 (RA 10.6847, Dec 41.2687), 0.3 degree cutout.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.image_download import ImageError  # noqa: E402
from backend.app.image_service import ImageService  # noqa: E402
from backend.app.irsa import IRSAClient, IRSAUnavailable  # noqa: E402


def main():
    ra = float(sys.argv[1]) if len(sys.argv) > 1 else 10.6847
    dec = float(sys.argv[2]) if len(sys.argv) > 2 else 41.2687
    size = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3
    started = time.time()
    try:
        result = IRSAClient().observations(ra, dec)
    except IRSAUnavailable as exc:
        print('SEARCH FAIL:', exc)
        return 1
    print(f'search: {result["count"]} observations in {time.time() - started:.1f}s')
    rows = [row for row in result['observations'] if row.get('access_url')][:2]
    if not rows:
        print('No observations with an access_url to test.')
        return 1
    service = ImageService()
    failures = 0
    for row in rows:
        started = time.time()
        label = f'{row["obs_id"]} ({row["energy_bandpassname"]})'
        try:
            meta = service.prepare(row['access_url'], ra, dec, size)
        except ImageError as exc:
            failures += 1
            print(f'CUTOUT FAIL {label}: [{exc.status} {exc.code}] {exc}')
            continue
        spectral = meta['center'].get('spectral')
        wave = f'{spectral["wavelength_um"]:.3f} um' if spectral else 'unavailable'
        print(f'CUTOUT OK   {label}: {time.time() - started:.1f}s, {meta["width"]}x{meta["height"]} px, '
              f'{meta["bytes"] / 1024:.0f} KiB, target={meta["target"]["status"] if meta["target"] else None}, '
              f'center wavelength={wave}')
        print(f'            source: {meta["fits_url"]}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
