"""Live check (needs internet): search IRSA at a sky point, then request one small cutout of the newest
observation through the same code the web app uses, and print timings.

Usage (from the repository root):
    .venv/bin/python scripts/smoke_cutout.py [RA DEC [SIZE_DEG]]
Defaults: M31 (RA 10.6847, Dec 41.2687), 0.02 degree cutout.
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.image_download import ImageError, ImageSettings, validate_cutout  # noqa: E402
from backend.app.image_service import ImageService  # noqa: E402
from backend.app.irsa import IRSAClient, IRSAUnavailable  # noqa: E402


def main():
    ra = float(sys.argv[1]) if len(sys.argv) > 1 else 10.6847
    dec = float(sys.argv[2]) if len(sys.argv) > 2 else 41.2687
    size = float(sys.argv[3]) if len(sys.argv) > 3 else 0.02
    validate_cutout(ra, dec, size)
    started = time.time()
    try:
        result = IRSAClient().observations(ra, dec)
    except IRSAUnavailable as exc:
        print('SEARCH FAIL:', exc)
        return 1
    print(f'search: {result["count"]} observations in {time.time() - started:.1f}s')
    rows = [row for row in result['observations'] if row.get('access_url')][:1]
    if not rows:
        print('No observations with an access_url to test.')
        return 1
    row = rows[0]
    with tempfile.TemporaryDirectory(prefix='spherex-smoke-') as directory:
        service = ImageService(ImageSettings(cache_dir=Path(directory), max_bytes=16*1024*1024, download_seconds=90))
        started = time.monotonic()
        label = f'{row["obs_id"]} ({row["energy_bandpassname"]})'
        try:
            meta = service.prepare(row['access_url'], ra, dec, size)
        except ImageError as exc:
            print(f'CUTOUT FAIL {label}: [{exc.status} {exc.code}] {exc}')
            if exc.__cause__:
                print(f'            cause: {exc.__cause__}')
            return 1
        spectral = meta['center'].get('spectral')
        wave = f'{spectral["wavelength_um"]:.3f} um' if spectral else 'unavailable'
        print(f'CUTOUT OK   {label}: {time.monotonic() - started:.1f}s, {meta["width"]}x{meta["height"]} px, '
              f'{meta["bytes"] / 1024:.0f} KiB, target={meta["target"]["status"] if meta["target"] else None}, '
              f'center wavelength={wave}')
        print(f'            source: {meta["fits_url"]}')
        started = time.monotonic()
        repeated = service.prepare(row['access_url'], ra, dec, size)
        assert repeated['cache_hit'] and repeated['image_id'] == meta['image_id']
        with service.open_asset(meta['image_id'], 'preview') as preview:
            assert preview.read(8) == b'\x89PNG\r\n\x1a\n'
        print(f'CACHE OK: {time.monotonic() - started:.2f}s, same image_id; PNG preview available; '
              f'WCS={meta["spatial_wcs"]}, spectral={meta["spectral_wcs"]}, HDUs={len(meta["hdus"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
