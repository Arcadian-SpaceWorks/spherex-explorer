"""Live check (needs internet): compare real SPHEREx images of M31 through the same code as
POST /api/compare, and report every check as PASS / FAIL / NOT RUN.

Cases (from the M31 notebook run):
  1. time, D1: 2026W01_1A_0471_1 vs 2026W28_2A_0117_1   expected ACCEPT (about 0.002 um apart)
  2. time, D1: 2025W28_1B_0480_4 vs 2026W01_1A_0471_1   expected WARN (wavelength mismatch)
  3. wavelength: D1 vs D4 of 2026W01_1A_0471_1          expected side by side only, no difference

The notebook's measured values are compared as observations with a tolerance, not as fixed
truths: they came from one run with a different cutout method.

Usage (from the repository root):
    .venv/bin/python scripts/smoke_compare.py [OUTPUT_DIR]
Preview PNGs and the full JSON results are written to OUTPUT_DIR (default: .cache/smoke-compare).
"""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.compare_service import CompareService  # noqa: E402
from backend.app.image_download import ImageError, ImageSettings  # noqa: E402
from backend.app.image_service import ImageService  # noqa: E402
from backend.app.irsa import IRSAClient, IRSAUnavailable  # noqa: E402

RA, DEC, SIZE = 10.6847, 41.2687, 0.3
# Notebook observations (one real run): D1/D4 wavelength at M31 and the raw 20x20 core median.
NOTEBOOK = {
    ('2025W28_1B_0480_4', 1): {'wavelength_um': 0.750, 'core': 40.150},
    ('2026W01_1A_0471_1', 1): {'wavelength_um': 0.895, 'core': 50.982},
    ('2026W28_2A_0117_1', 1): {'wavelength_um': 0.893, 'core': 51.511},
    ('2026W01_1A_0471_1', 4): {'wavelength_um': 2.98},
}
WAVELENGTH_TOLERANCE_UM, CORE_TOLERANCE = 0.01, 0.05
CASES = [
    ('1 time D1, same wavelength', 'time', ('2026W01_1A_0471_1', 1), ('2026W28_2A_0117_1', 1), 'ACCEPT'),
    ('2 time D1, wavelength mismatch', 'time', ('2025W28_1B_0480_4', 1), ('2026W01_1A_0471_1', 1), 'WARN'),
    ('3 wavelength D1 vs D4', 'wavelength', ('2026W01_1A_0471_1', 1), ('2026W01_1A_0471_1', 4), 'ACCEPT'),
]

checks = []


def check(name, status, detail=''):
    checks.append((name, status, detail))
    print(f'{status:8} {name}{"  -  " + detail if detail else ""}', flush=True)


def find_observations(client):
    rows = {}
    for detector in sorted({key[1] for key in NOTEBOOK}):
        result = client.observations(RA, DEC, band=f'SPHEREx-D{detector}')
        for row in result['observations']:
            rows.setdefault((row['obs_id'], detector), []).append(row)
    return rows


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / '.cache' / 'smoke-compare'
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        rows = find_observations(IRSAClient())
    except IRSAUnavailable as exc:
        check('IRSA search for M31 observations', 'FAIL', str(exc))
        for case in CASES:
            check(f'case {case[0]}', 'NOT RUN', 'no search results')
        return summary()
    for key in NOTEBOOK:
        found = rows.get(key, [])
        check(f'IRSA lists {key[0]} D{key[1]}', 'PASS' if found else 'FAIL',
              f'{len(found)} product(s)' + (f', {found[0]["access_url"]}' if found else ''))

    # Room for all four cutouts at once, so case 3 does not re-download an evicted image.
    images = ImageService(replace(ImageSettings.from_env(), cutout_cache_entries=8))
    service = CompareService(images)
    results = {}
    for name, mode, key_a, key_b, expected in CASES:
        if not rows.get(key_a) or not rows.get(key_b):
            check(f'case {name}', 'NOT RUN', 'observation not found in IRSA search')
            continue
        refs = [{'access_url': rows[key][0]['access_url']} for key in (key_a, key_b)]
        began = time.time()
        try:
            result = service.compare(*refs, RA, DEC, SIZE, mode)
        except ImageError as exc:
            check(f'case {name}', 'FAIL', f'{exc.code}: {exc}')
            continue
        results[name] = result
        reasons = ', '.join(f'{r["code"]}({r["severity"]})' for r in result['validation']['reasons'])
        check(f'case {name}: decision {expected}', 'PASS' if result['decision'] == expected else 'FAIL',
              f'got {result["decision"]} in {time.time() - began:.0f} s; overlap {result["overlap_fraction"]:.3f}; '
              f'delta wavelength {result["validation"]["wavelength_delta_um"]}; reasons: {reasons}')
        allowed = mode == 'time' and expected == 'ACCEPT'
        has_difference = result['previews']['difference'] is not None
        check(f'case {name}: difference image {"present" if allowed else "absent"}',
              'PASS' if has_difference == allowed else 'FAIL',
              f'shared stretch {result["stretch"]["shared"]}')
        folder = out / name.split()[0]
        folder.mkdir(exist_ok=True)
        for role, url in result['previews'].items():
            if url:
                compare_id = url.split('/')[3]
                shutil.copyfile(service.settings.cache_dir / compare_id / f'{role}.png', folder / f'{role}.png')
        (folder / 'result.json').write_text(json.dumps(result, indent=2))
        for frame in result['frames']:
            reference = NOTEBOOK.get((frame['obs_id'], frame['detector']))
            label = f'{frame["obs_id"]} {frame["band"]}'
            wavelength, core = frame['wavelength_um'], frame['diagnostics']['core_median']
            if reference and wavelength is not None:
                delta = abs(wavelength - reference['wavelength_um'])
                check(f'observation {label}: wavelength near notebook {reference["wavelength_um"]} um',
                      'PASS' if delta <= WAVELENGTH_TOLERANCE_UM else 'FAIL', f'measured {wavelength:.4f} um')
            elif reference:
                check(f'observation {label}: wavelength', 'FAIL', 'wavelength unavailable')
            if reference and 'core' in reference:
                if core is None:
                    check(f'observation {label}: core level', 'FAIL', 'core unavailable')
                else:
                    ratio = core / reference['core'] - 1
                    check(f'observation {label}: core near notebook {reference["core"]} MJy/sr',
                          'PASS' if abs(ratio) <= CORE_TOLERANCE else 'FAIL',
                          f'measured {core:.3f} MJy/sr ({ratio:+.1%}); zodi {frame["diagnostics"]["zodi_median"]}')
    print(f'\nPreviews and JSON: {out}   total time {time.time() - started:.0f} s')
    return summary()


def summary():
    counts = {status: sum(1 for _, s, _ in checks if s == status) for status in ('PASS', 'FAIL', 'NOT RUN')}
    print('SUMMARY ' + '  '.join(f'{status} {count}' for status, count in counts.items()))
    return 1 if counts['FAIL'] else 0


if __name__ == '__main__':
    sys.exit(main())
