"""Live check (needs internet): suggest time-comparison pairs for one sky point and band, using the
same code as GET /api/pairs. The first run fetches one IRSA cutout per shortlisted observation
(about 20 s each); a second run should be fast because cutouts are cached.

Usage (from the repository root):
    .venv/bin/python scripts/smoke_pairs.py [RA DEC [BAND [PER_VISIT]]]
Defaults: M31 (RA 10.6847, Dec 41.2687), SPHEREx-D1, 2 observations per visit.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.image_service import ImageService  # noqa: E402
from backend.app.irsa import IRSAClient, IRSAUnavailable  # noqa: E402
from backend.app.pairs import build_pair_report  # noqa: E402


def main():
    ra = float(sys.argv[1]) if len(sys.argv) > 1 else 10.6847
    dec = float(sys.argv[2]) if len(sys.argv) > 2 else 41.2687
    band = sys.argv[3] if len(sys.argv) > 3 else 'SPHEREx-D1'
    per_visit = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    started = time.time()
    try:
        report = build_pair_report(IRSAClient(), ImageService(), ra, dec, band, per_visit)
    except IRSAUnavailable as exc:
        print('SEARCH FAIL:', exc)
        return 1
    print(f'{band}: {report["observations_considered"]} observations'
          f'{" (truncated at 100)" if report["truncated"] else ""}, {len(report["visits"])} visits, '
          f'{time.time() - started:.0f}s total')
    for visit in report['visits']:
        print(f'  visit {visit["visit"]}: {visit["first_utc"][:10]} to {visit["last_utc"][:10]}, '
              f'{visit["observations"]} observations')
    print('candidates:')
    for c in report['candidates']:
        if c.get('error'):
            print(f'  FAIL {c["obs_id"]}: {c["error"]["message"]}')
        else:
            wl = 'unknown' if c['wavelength_um'] is None else f'{c["wavelength_um"]:.3f} um'
            print(f'  OK   {c["obs_id"]} visit {c["visit"]} {c["observed_at_utc"][:10]} '
                  f'centre {c["center_distance_deg"]:.2f} deg from target, target {c["target_status"]}, '
                  f'wavelength {wl} ({c["wavelength_source"]}){" [cached]" if c.get("cache_hit") else ""}')
    print('best pairs:')
    for p in report['pairs'][:5]:
        dwl = '?' if p['delta_wavelength_um'] is None else f'{p["delta_wavelength_um"]:.3f}'
        print(f'  {p["decision"]:6} {p["a"]["obs_id"]} -> {p["b"]["obs_id"]}: {p["dt_days"]:.1f} days apart, '
              f'wavelength difference {dwl} um, {p["baseline"]}')
        for reason in p['reasons']:
            print(f'         {reason["message"]}')
    if not report['pairs']:
        print('  none (need at least two usable candidates at different times)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
