"""Network check: local cutouts of S3-mirrored products equal IRSA's own cutouts, byte for byte.

Every demo-bundle original.fits is an unmodified IRSA image-server cutout with a recorded SHA-256.
For each one this downloads the full product from the AWS mirror, cuts it with
backend.app.local_cutout.irsa_cutout using the same centre and size, and compares the SHA-256.

    .venv/bin/python scripts/check_mirror_cutouts.py [--limit N]

Downloads about 72 MB per distinct product into a temporary directory (deleted afterwards).
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit, urlunsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.image_download import mirror_url  # noqa: E402
from backend.app.local_cutout import irsa_cutout  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--limit', type=int, default=None, help='check only the first N demo cutouts')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'frontend/public/demo/manifest.json').read_text())
    rows = [(t['id'], o) for t in manifest['targets'] for o in t['observations']][:args.limit]
    same = different = 0
    with tempfile.TemporaryDirectory() as folder, requests.Session() as session:
        session.trust_env = False
        sources = {}
        for target, row in rows:
            parts = urlsplit(row['source_url'])
            query = parse_qs(parts.query)
            ra, dec = map(float, query['center'][0].split(','))
            size = float(query['size'][0].removesuffix('deg'))
            url = mirror_url(urlunsplit(parts._replace(query='')))
            if url not in sources:
                path = Path(folder) / f'{len(sources)}.fits'
                started = time.monotonic()
                with session.get(url, stream=True, timeout=(10, 60)) as response, path.open('wb') as sink:
                    response.raise_for_status()
                    for chunk in response.iter_content(1 << 20):
                        sink.write(chunk)
                sources[url] = path
                fetched = f'{time.monotonic() - started:.1f} s'
            else:
                fetched = 'reused'
            out = Path(folder) / 'cut.fits'
            box = irsa_cutout(sources[url], out, ra, dec, size, 8_000_000)
            ok = hashlib.sha256(out.read_bytes()).hexdigest() == row['fits_sha256']
            same, different = same + ok, different + (not ok)
            release = url.split('/')[3]
            print(f"{'IDENTICAL' if ok else 'DIFFERENT'}  {target:9} {release} {size:.3f} deg "
                  f"box {box['width']}x{box['height']} at ({box['x0']},{box['y0']})  mirror {fetched}", flush=True)
            if len(sources) > 2:  # Keep disk use bounded.
                old = next(iter(sources))
                sources.pop(old).unlink()
    print(f'\n{same} identical, {different} different, of {len(rows)} IRSA cutouts.')
    return 1 if different else 0


if __name__ == '__main__':
    sys.exit(main())
