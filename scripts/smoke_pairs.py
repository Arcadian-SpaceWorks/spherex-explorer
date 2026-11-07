"""Live check (needs internet): suggest time-comparison pairs for one sky point and band through the
same code as GET /api/pairs, then compare the best suggestion through the same code as
POST /api/compare and check that both agree. Reports each check as PASS / FAIL / NOT RUN.

The first run fetches one IRSA cutout per shortlisted observation (at most 12, roughly 20-60 s
each); repeats reuse cached cutouts while the image cache still holds them.

Usage (from the repository root):
    .venv/bin/python scripts/smoke_pairs.py [RA DEC [BAND [PER_VISIT]]]
Defaults: M31 (RA 10.6847, Dec 41.2687), SPHEREx-D1, 1 observation per visit.
"""
from dataclasses import replace
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.compare_service import CompareService  # noqa: E402
from backend.app.image_download import ImageError, ImageSettings  # noqa: E402
from backend.app.image_service import ImageService  # noqa: E402
from backend.app.irsa import IRSAClient, IRSAUnavailable  # noqa: E402
from backend.app.pairs import MAX_CANDIDATES, build_pair_report  # noqa: E402

checks = []


def check(name, status, detail=''):
    checks.append(status)
    print(f'{status:8} {name}{"  -  " + detail if detail else ""}', flush=True)


def main():
    ra = float(sys.argv[1]) if len(sys.argv) > 1 else 10.6847
    dec = float(sys.argv[2]) if len(sys.argv) > 2 else 41.2687
    band = sys.argv[3] if len(sys.argv) > 3 else 'SPHEREx-D1'
    per_visit = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    # Room for every shortlisted cutout, so the comparison below reuses them instead of re-downloading.
    images = ImageService(replace(ImageSettings.from_env(), cutout_cache_entries=MAX_CANDIDATES + 2))
    started = time.time()
    try:
        report = build_pair_report(IRSAClient(), images, ra, dec, band, per_visit)
    except IRSAUnavailable as exc:
        check('IRSA search', 'FAIL', str(exc))
        check('compare the best suggestion', 'NOT RUN', 'no search results')
        return 1
    print(f'{band}: {report["observations_considered"]} observations'
          f'{" (truncated at 100)" if report["truncated"] else ""}, {len(report["visits"])} visits, '
          f'{len(report["candidates"])} candidates, {time.time() - started:.0f} s')
    for visit in report['visits']:
        print(f'  visit {visit["visit"]}: {visit["first_utc"][:10]} to {visit["last_utc"][:10]}, {visit["observations"]} observations')
    for c in report['candidates']:
        if c.get('error'):
            check(f'candidate {c["obs_id"]}', 'FAIL', c['error']['message'])
        else:
            wl = 'unknown' if c['wavelength_um'] is None else f'{c["wavelength_um"]:.4f} um'
            print(f'  OK   {c["obs_id"]} visit {c["visit"]} {c["observed_at_utc"][:10]} centre '
                  f'{c["center_distance_deg"]:.2f} deg away, target {c["target_status"]}, wavelength {wl}')
    print('best pairs:')
    for p in report['pairs'][:5]:
        dwl = '?' if p['delta_wavelength_um'] is None else f'{p["delta_wavelength_um"]:.4f}'
        print(f'  {p["decision"]:6} {p["a"]["obs_id"]} -> {p["b"]["obs_id"]}: {p["dt_days"]:.1f} days, '
              f'wavelength difference {dwl} um, {p["baseline"]}')
    accepted = [p for p in report['pairs'] if p['decision'] == 'ACCEPT']
    check('at least one ACCEPT suggestion', 'PASS' if accepted else 'FAIL', f'{len(accepted)} of {len(report["pairs"])} pairs')
    if not accepted:
        check('compare the best suggestion', 'NOT RUN', 'no ACCEPT pair')
        return 1
    best = accepted[0]
    try:
        result = CompareService(images).compare({'access_url': best['a']['access_url']}, {'access_url': best['b']['access_url']},
                                                ra, dec, report['rules']['size_deg'], 'time')
    except ImageError as exc:
        check('compare the best suggestion', 'FAIL', f'{exc.code}: {exc}')
        return 1
    reasons = ', '.join(r['code'] for r in result['validation']['reasons'])
    check('compare agrees with the suggestion (ACCEPT)', 'PASS' if result['decision'] == 'ACCEPT' else 'FAIL',
          f'got {result["decision"]}; overlap {result["overlap_fraction"]:.3f}; reasons: {reasons}')
    same = all(abs(f['wavelength_um'] - best[role]['wavelength_um']) < 1e-9 for f, role in zip(result['frames'], 'ab'))
    check('same wavelengths at the target in both', 'PASS' if same else 'FAIL')
    print(f'total {time.time() - started:.0f} s')
    return 1 if 'FAIL' in checks else 0


if __name__ == '__main__':
    raise SystemExit(main())
