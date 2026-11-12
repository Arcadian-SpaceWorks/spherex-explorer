"""Measure the SPHEREx spectrum of a sky position from the command line (network required).

    .venv/bin/python scripts/spectrum.py 68.0692 18.2328            # RA, Dec in degrees (ICRS)
    .venv/bin/python scripts/spectrum.py 68.0692 18.2328 --csv out.csv --limit 400
    .venv/bin/python scripts/spectrum.py --comet                     # 3I/ATLAS at IRSA's predicted positions

Prints the band measurements and the season-to-season comparison that the web app shows.
"""
import argparse
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.spectrum import analysis  # noqa: E402
from backend.app.spectrum import moving  # noqa: E402
from backend.app.spectrum.service import DEFAULT_EXPOSURES, POINT_KEYS, SpectrumService  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('ra', nargs='?', type=float)
    parser.add_argument('dec', nargs='?', type=float)
    parser.add_argument('--comet', action='store_true', help='3I/ATLAS, tracked with the official per-exposure positions')
    parser.add_argument('--limit', type=int, default=DEFAULT_EXPOSURES)
    parser.add_argument('--csv', type=Path)
    parser.add_argument('--no-cache', action='store_true')
    args = parser.parse_args()
    service = SpectrumService(cache_dir='/nonexistent/never-written' if args.no_cache else SpectrumService().cache_dir)
    if args.comet:
        job_id = service.start_moving('3i-atlas', moving.TARGETS['3i-atlas'], moving.comet_exposures, moving.SOURCE, args.limit)
    elif args.ra is None or args.dec is None:
        parser.error('give RA and Dec, or --comet')
    else:
        job_id = service.start(args.ra, args.dec, args.limit)
    while True:
        job = service.get(job_id)
        print(f"\r{job['state']:8s} {job['done']}/{job['total']}  {job['megabytes_read']} MB  {job['elapsed_s']} s   ", end='', file=sys.stderr)
        if job['state'] in ('done', 'failed'):
            break
        time.sleep(1)
    print(file=sys.stderr)
    print(job['message'])
    if job['state'] == 'failed':
        return 1
    result = job['analysis']
    print('exposures available', job['available'], '| measured', job['total'], '| outcomes', result['counts'])
    if 'median_snr' in result:
        print(f"median S/N {result['median_snr']:.1f} | median flux {result['median_flux_mjy']:.3f} mJy | "
              f"coverage {result['coverage_um'][0]:.2f}-{result['coverage_um'][1]:.2f} um")
    labels = {feature['id']: feature['label'] for feature in analysis.FEATURES}

    def show(features, indent=''):
        for item in features:
            if item['status'] == 'not_measurable':
                continue
            strength = f"{100 * item['strength']:.0f} %" if item.get('strength') is not None else 'n/a'
            tau = f" tau{'>' if item.get('optical_depth_is_lower_limit') else '='}{item['optical_depth']:.2f}" if item['status'] == 'detected' and item.get('optical_depth') else ''
            print(f"{indent}{labels[item['id']]:26s} {item['status']:13s} {item.get('kind') or '':10s} "
                  f"{item['significance']:+7.1f} sigma  strength {strength}{tau}  (n={item['points']['core']})")

    show(result['features'])
    for season, per in zip(result['seasons'], result['features_by_season']):
        print(f"  season {season['index']}: {season['start_utc'][:10]} to {season['end_utc'][:10]}, {season['measured']} measured")
        show([item for item in per['features'] if item['status'] == 'detected'], '    ')
    change = result['variability']
    print('variability:', change['status'], {key: round(value, 3) for key, value in change.items() if isinstance(value, float)})
    for season in change['seasons']:
        print(f"  season {season['index']} {season['start_utc'][:10]}: {season['relative_flux']:.3f} +/- {season['relative_flux_err']:.3f} (n={season['n']})",
              ' '.join(f"D{band['detector']}={band['relative_flux']:.2f}" for band in season['bands']))
    if args.csv:
        with args.csv.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, POINT_KEYS)
            writer.writeheader()
            for point in sorted(job['points'], key=lambda point: (point['wavelength_um'] is None, point['wavelength_um'])):
                writer.writerow({**point, 'flag_names': ' '.join(point.get('flag_names') or [])})
        print('wrote', args.csv)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
