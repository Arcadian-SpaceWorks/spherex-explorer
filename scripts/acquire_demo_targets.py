"""Acquire the larger Demo Mode sets: M31, Barnard's Star and comet 3I/ATLAS (about 18-21 frames each).

Every step is deterministic and resumable:
  1. candidates  Frames are picked from the saved IRSA discovery tables (demo/discovery/*.vot) by the
                 rules in TARGETS below: epoch windows, one data release per epoch, a detector, and an
                 evenly spaced number of candidates. No network.
  2. download    Each candidate is cut out at 0.437 deg (the size /api/compare needs for its north-up
                 0.3 deg grid) through the app's ImageService, checked (identity, UTC, archive time,
                 release, target and predicted position inside the WCS) and staged in
                 demo/acquired/<target>/ (git-ignored). A staged or already published frame is never
                 downloaded again.
  3. select      Per-epoch quotas. Pairs across epochs whose wavelength at the target agrees within
                 0.02 um and that both cover at least 95% of the 0.3 deg comparison grid (the pairs
                 /api/compare can difference) are kept first, longest baseline first; the rest are
                 spread in time, preferring frames that cover the grid. Simultaneous partner detectors (the same exposure
                 through the dichroic) are then added.

Writes demo/source-records/<sha256>.json, demo/plans/<target>.json (every candidate, whether it was
selected and why) and demo/acquired/staging-targets.json (a preparation inventory that reads the
staged FITS). Never edits the published bundle. Afterwards:

  .venv/bin/python scripts/prepare_demo.py --config demo/acquired/staging-targets.json --output NEW_DIR
  (replace frontend/public/demo with NEW_DIR), then
  .venv/bin/python scripts/acquire_demo_targets.py --publish    # demo/targets.json -> published FITS

Usage (needs internet):  .venv/bin/python scripts/acquire_demo_targets.py [m31 barnard 3i-atlas]
"""
import argparse
from dataclasses import replace
from itertools import combinations
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import numpy as np
from astropy.io import fits
from astropy.time import Time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.analysis.compare import CompareSettings, cutout_size_for_grid  # noqa: E402
from backend.app.demo import digest  # noqa: E402
from scripts.discover_demo import CANDIDATES, COMET, read_table  # noqa: E402

GRID_DEG = 0.3  # The comparison grid of /api/compare (frontend COMPARE_SIZE_DEG).
CUTOUT_DEG = round(cutout_size_for_grid(GRID_DEG), 4)
MATCH_UM = CompareSettings().max_wavelength_delta_um
# A frame must cover this much of the grid to seed a matched pair: two such frames overlap by at
# least 90%, the minimum /api/compare needs. Targets near a detector edge (LVF band edges) fail it.
MIN_COVERAGE = 0.95
DISCOVERY = ROOT / 'demo' / 'discovery'
PLANS = ROOT / 'demo' / 'plans'
ACQUIRED = ROOT / 'demo' / 'acquired'
RECORDS = ROOT / 'demo' / 'source-records'
PUBLISHED = ROOT / 'frontend' / 'public' / 'demo'
STAGING_CONFIG = ACQUIRED / 'staging-targets.json'

# Gaia DR3 astrometry of Barnard's Star, saved in demo/discovery/barnard-gaia-dr3.csv.
GAIA_URL = ('https://irsa.ipac.caltech.edu/TAP/sync?LANG=ADQL&FORMAT=csv&QUERY=SELECT+source_id,ra,dec,ref_epoch,'
            'pmra,pmdec,parallax,phot_g_mean_mag+FROM+gaia_dr3_source+WHERE+source_id=4472832130942575872')
GAIA_FILE = DISCOVERY / 'barnard-gaia-dr3.csv'

TARGETS = {
    'm31': dict(
        name='M31 — Andromeda Galaxy core', table='m31', centre=(10.684708333333333, 41.26875),
        coordinate_source=CANDIDATES['m31']['source'], position_source=CANDIDATES['m31']['source'],
        position_note=CANDIDATES['m31']['position'], releases={'spherex_qr2'},
        epochs=[('July 2025', '2025-07-01', '2025-09-01'), ('December 2025', '2025-12-01', '2026-03-01'),
                ('July 2026', '2026-07-01', '2026-09-01')],
        # D1 keeps the curated exposures validated by scripts/smoke_compare.py.
        groups=[dict(detector=1, partner=4, keep=['2025W28_1B_0480_4', '2026W01_1A_0471_1', '2026W28_2A_0117_1']),
                dict(detector=2, partner=5, candidates=4, quota=1),
                dict(detector=3, partner=6, candidates=4, quota=1)],
        seed_pairs=1,
        science_context=(
            'Three SPHEREx survey passes (July 2025, December 2025, July 2026). Each pass has one exposure in '
            'every detector pair: D1/D4 (about 0.75–0.9 and 2.4–3.0 µm at the core), D2/D5 and D3/D6. The two '
            'detectors of a pair see the same moment through a dichroic. Within a detector, exposures were '
            'chosen so the wavelength at the core matches another pass where the archive allows it. Brightness '
            'differences between passes follow the wavelength at the target, not time; no variability is claimed.'),
    ),
    'barnard': dict(
        name='Barnard’s Star — fast-moving nearby red dwarf', table='barnard', centre='gaia-at:2026-03-01',
        coordinate_source=GAIA_URL, position_source=GAIA_URL,
        position_note=('Fixed sky centre (Gaia DR3 position at 2026-03-01). The marker is Gaia DR3 4472832130942575872 '
                       'propagated linearly by its proper motion to each exposure; annual parallax (up to 0.55″) '
                       'and perspective acceleration are ignored (under 0.1 pixel). Not a measured position.'),
        releases={'spherex_qr2', 'spherex_qr3'}, predicted='gaia', max_offset_deg=0.01,
        epochs=[('August 2025', '2025-08-15', '2025-09-01'), ('March 2026', '2026-03-11', '2026-04-15'),
                ('August 2026', '2026-08-16', '2026-09-01')],
        groups=[dict(detector=3, candidates=12, quota=7)],
        seed_pairs=2,
        science_context=(
            'The nearest single star to the Sun (about 6 light-years) and the star with the fastest known motion '
            'across the sky: about 10.4″ per year, mostly northward (Gaia DR3), which is 1.7 SPHEREx pixels. '
            'Detector D3 (about 1.6–2.4 µm) at three epochs: August 2025 and March 2026 (data release QR2) and '
            'August 2026 (QR3). The marker shows the Gaia position propagated to each exposure, not a measured '
            'position. The star is bright enough to saturate its core (OVERFLOW flags), so a position needs a '
            'centroid and is best averaged over several frames: a one-year test averaging three and four frames '
            'measured 9.2″ per year against 10.39″ from Gaia. The epochs mix two data releases, so positions can '
            'be compared but brightness should not be.'),
    ),
    '3i-atlas': dict(
        name='3I/ATLAS — interstellar comet, 14 Dec 2025', table='3i-atlas', centre='comet-path-mean',
        coordinate_source=COMET, position_source=COMET,
        position_note=('Fixed sky centre at the mean of IRSA’s predicted comet path for these exposures, so stars '
                       'stay put and the comet moves. The marker is IRSA’s predicted comet_ra/comet_dec for each '
                       'exposure, not a measured position.'),
        releases={'spherex_qr2'}, predicted='comet', max_offset_deg=0.13,
        epochs=[('14 Dec 2025', '2025-12-14T04:00', '2025-12-14T08:00')],
        groups=[dict(detector=5, candidates=12, quota=12), dict(detector=2, candidates=6, quota=6)],
        seed_pairs=0,
        science_context=(
            'The third known interstellar object. Twelve exposures over 3.3 hours on 14 December 2025 in detector '
            'D5 (about 3.8–4.4 µm, a range that includes the 4.26 µm CO₂ band) and six simultaneous D2 frames '
            '(about 1.1–1.65 µm). Every cutout has the same sky centre, so the stars stay fixed while the comet '
            'crosses about 0.16° (roughly 95 pixels) of the field. The marker shows IRSA’s predicted comet '
            'position for each exposure, not a measured position. IRSA warns of low signal-to-noise at many '
            'wavelengths, and the comet’s brightness changes with the wavelength at its position.'),
    ),
}


# ---------- positions ----------

def gaia_astrometry():
    header, values = GAIA_FILE.read_text().strip().splitlines()[:2]
    row = dict(zip(header.split(','), values.split(',')))
    return {key: float(row[key]) for key in ('ra', 'dec', 'ref_epoch', 'pmra', 'pmdec', 'parallax')}


def propagate(astrometry, mjd):
    """Linear proper-motion propagation (good to milliarcseconds over a decade; parallax ignored)."""
    years = (Time(mjd, format='mjd', scale='utc').jyear - astrometry['ref_epoch'])
    dec = astrometry['dec'] + astrometry['pmdec'] * years / 3.6e6
    ra = astrometry['ra'] + astrometry['pmra'] * years / 3.6e6 / math.cos(math.radians((dec + astrometry['dec']) / 2))
    return float(ra % 360), float(dec)


def separation_deg(ra1, dec1, ra2, dec2):
    a, b, c, d = map(math.radians, (ra1, dec1, ra2, dec2))
    value = math.sin(b) * math.sin(d) + math.cos(b) * math.cos(d) * math.cos(a - c)
    return math.degrees(math.acos(max(-1.0, min(1.0, value))))


# ---------- step 1: candidates ----------

def band_of(table):
    return 'spherex_detector' if 'spherex_detector' in table.colnames else 'energy_bandpassname'


def epoch_rows(table, start, end, releases):
    lo, hi = Time(start, scale='utc').mjd, Time(end, scale='utc').mjd
    return [row for row in table if lo <= float(row['t_min']) < hi and str(row['obs_collection']) in releases]


def evenly_spaced(rows, count):
    rows = sorted({str(row['access_url']): row for row in rows}.values(), key=lambda row: (float(row['t_min']), str(row['obs_id'])))
    if count >= len(rows):
        return rows
    return [rows[i] for i in sorted(set(np.linspace(0, len(rows) - 1, count).round().astype(int)))]


def candidates(key, config, table):
    """Candidate rows per (epoch, detector), plus the partner rows that may be added later."""
    band = band_of(table)
    out = []
    for label, start, end in config['epochs']:
        rows = epoch_rows(table, start, end, config['releases'])
        releases = {str(row['obs_collection']) for row in rows}
        if len(releases) > 1:
            raise ValueError(f'{key} {label}: one epoch must not mix data releases ({sorted(releases)})')
        for group in config['groups']:
            detector = group['detector']
            mine = [row for row in rows if str(row[band]).endswith(f'D{detector}')]
            if 'keep' in group:
                chosen = [row for row in mine if str(row['obs_id']) in group['keep']]
                if len(chosen) != 1:
                    raise ValueError(f'{key} {label} D{detector}: expected exactly one curated exposure, found {len(chosen)}')
            else:
                chosen = evenly_spaced(mine, group['candidates'])
            out += [dict(row=row, epoch=label, detector=detector, keep='keep' in group) for row in chosen]
    return out


def partner_row(table, row, detector):
    band = band_of(table)
    matches = [other for other in table if str(other['obs_id']) == str(row['obs_id']) and str(other[band]).endswith(f'D{detector}')]
    if len(matches) != 1:
        raise ValueError(f'{row["obs_id"]}: expected one D{detector} partner, found {len(matches)}')
    return matches[0]


def frame_centre(config, table):
    centre = config['centre']
    if centre == 'comet-path-mean':
        label, start, end = config['epochs'][0]
        rows = epoch_rows(table, start, end, config['releases'])
        return round(float(np.mean([float(r['comet_ra']) for r in rows])), 4), round(float(np.mean([float(r['comet_dec']) for r in rows])), 4)
    if isinstance(centre, str) and centre.startswith('gaia-at:'):
        ra, dec = propagate(gaia_astrometry(), Time(centre.removeprefix('gaia-at:'), scale='utc').mjd)
        return round(ra, 5), round(dec, 5)
    return centre


def predicted_position(config, row):
    if config.get('predicted') == 'comet':
        return float(row['comet_ra']), float(row['comet_dec'])
    if config.get('predicted') == 'gaia':
        return propagate(gaia_astrometry(), float(row['t_min']))
    return None


def grid_coverage(path, centre):
    """Fraction of the north-up comparison grid around centre with valid data in this frame,
    computed with the same loading and resampling as /api/compare."""
    from backend.app.analysis.compare import align, common_grid, load_frame
    frame = load_frame(str(path), centre[0], centre[1], CUTOUT_DEG)  # As compare_files loads it.
    return round(float(align([frame], common_grid(centre[0], centre[1], GRID_DEG))[0].valid.mean()), 4)


# ---------- step 2: download ----------

def published_index():
    """Frames already in the published bundle, by (access_url, cutout), so they are never fetched again."""
    index = {}
    manifest = PUBLISHED / 'manifest.json'
    if not manifest.exists():
        return index
    for target in json.loads(manifest.read_text())['targets']:
        for row in target['observations']:
            meta = json.loads((PUBLISHED / row['metadata_path'].removeprefix('/demo/')).read_text())
            cutout = meta.get('cutout') or {}
            index[(row['access_url'], cutout.get('ra'), cutout.get('dec'), cutout.get('size_deg'))] = PUBLISHED / row['fits_path'].removeprefix('/demo/')
    return index


def stage(key, config, item, centre, images, published, table_sha):
    """Download (or reuse) one cutout, check it, and return its staged record."""
    row = item['row']
    access_url = str(row['access_url'])
    ra, dec = min(round(centre[0], 6), 359.999999), round(centre[1], 6)
    token = hashlib.sha256(f'{access_url}|{ra:.6f}|{dec:.6f}|{CUTOUT_DEG:.4f}'.encode()).hexdigest()
    folder = ACQUIRED / key / token
    original, record_path = folder / 'original.fits', folder / 'record.json'
    if record_path.exists() and original.exists():
        record = json.loads(record_path.read_text())
        if digest(original) == record['sha256']:
            if 'grid_coverage' not in record['measured']:  # Staged before coverage was measured.
                record['measured']['grid_coverage'] = grid_coverage(original, centre)
                record_path.write_text(json.dumps(record, indent=2) + '\n')
            return record, 'staged'
    folder.mkdir(parents=True, exist_ok=True)
    source = published.get((access_url, ra, dec, CUTOUT_DEG))
    how = 'published'
    if source is None:
        how = 'downloaded'
        for attempt in range(3):  # IRSA sometimes fails a delivery that succeeds moments later.
            try:
                meta = images.prepare(access_url, ra, dec, CUTOUT_DEG)
                break
            except Exception as exc:
                if attempt == 2:
                    raise
                print(f'        retry after: {exc}', flush=True)
                time.sleep(10 * (attempt + 1))
        images.copy_original(meta['image_id'], original)
        if digest(original) != meta['sha256']:
            raise ValueError('checksum of the staged FITS differs from the download record')
        meta = {k: v for k, v in meta.items() if k not in ('cache_hit', 'target')}
    else:
        from backend.app.fits_worker import process_fits
        original.write_bytes(source.read_bytes())
        meta = process_fits('render', path=str(original), preview_path=str(folder / 'check.png'), max_pixels=8_000_000)
        old = json.loads(next(p for p in RECORDS.glob('*.json') if json.loads(p.read_text()).get('sha256') == digest(original)).read_text())
        meta.update({k: old[k] for k in ('image_id', 'access_url', 'fits_url', 'cutout', 'bytes', 'sha256', 'preview_url', 'original_url')})
    record = check_and_describe(key, config, item, meta, original, centre, table_sha)
    record_path.write_text(json.dumps(record, indent=2) + '\n')
    return record, how


def check_and_describe(key, config, item, meta, original, centre, table_sha):
    from backend.app.fits_worker import process_fits
    row = item['row']
    with fits.open(original, memmap=False) as hdul:
        hdul.verify('exception')
        header = hdul['IMAGE'].header
        if header.get('TIMESYS', hdul[0].header.get('TIMESYS')) != 'UTC':
            raise ValueError('FITS does not declare TIMESYS=UTC')
    if meta['observation_id'] != str(row['obs_id']) or meta['detector'] != item['detector']:
        raise ValueError(f'FITS identity {meta["observation_id"]} D{meta["detector"]} differs from the archive row')
    seconds = abs(Time(meta['observed_at_utc'], format='isot', scale='utc').mjd - float(row['t_min'])) * 86400
    if seconds > 0.1:  # Same tolerance as scripts/validate_demo_science.py.
        raise ValueError(f'FITS time differs from the archive time by {seconds:.2f} s')
    parts = urlsplit(meta['fits_url']).path.split('/')
    release, calibration = 'spherex_' + parts[4], parts[-3]
    if release != str(row['obs_collection']):
        raise ValueError(f'image server release {release} differs from the archive row {row["obs_collection"]}')
    at_centre = process_fits('target', path=str(original), ra=meta['cutout']['ra'], dec=meta['cutout']['dec'], max_pixels=8_000_000)
    if at_centre['status'] != 'inside':
        raise ValueError('the cutout centre is outside the image or the WCS is unusable')
    predicted = predicted_position(config, row)
    marker = at_centre
    if predicted:
        offset = separation_deg(*predicted, *centre)
        if offset > config['max_offset_deg']:
            raise ValueError(f'predicted position is {offset:.3f} deg from the frame centre')
        marker = process_fits('target', path=str(original), ra=predicted[0], dec=predicted[1], max_pixels=8_000_000)
        if marker['status'] != 'inside':
            raise ValueError('the predicted position is outside the image')
    record = dict(meta)
    record.update(
        target_position={'ra': predicted[0], 'dec': predicted[1]} if predicted else {'ra': centre[0], 'dec': centre[1]},
        mission='SPHEREx', data_release=release, calibration=calibration,
        position_source=config['position_source'], position_mode='fixed-sky-region', position_note=config['position_note'],
        predicted_ra=predicted[0] if predicted else None, predicted_dec=predicted[1] if predicted else None,
        archive_t_min=float(row['t_min']), archive_em_min_m=float(row['em_min']), archive_em_max_m=float(row['em_max']),
        discovery_sha256=table_sha,
        measured=dict(wavelength_um_at_centre=(at_centre.get('spectral') or {}).get('wavelength_um'),
                      wavelength_um_at_marker=(marker.get('spectral') or {}).get('wavelength_um'),
                      marker_pixel=[marker['x'], marker['y']], grid_coverage=grid_coverage(original, centre)),
    )
    return record


# ---------- step 3: select ----------

def choose(frames, quotas, seed_pairs, match_um=MATCH_UM, min_coverage=MIN_COVERAGE):
    """Pick frames per (epoch, detector) quota. frames: dicts with key, epoch, detector, mjd,
    wavelength_um, coverage (of the comparison grid) and keep. Returns {key: reason}. Deterministic."""
    chosen = {}
    by_key = {f['key']: f for f in frames}
    order = {e: i for i, e in enumerate(dict.fromkeys(f['epoch'] for f in sorted(frames, key=lambda f: f['mjd'])))}

    def room(f):
        taken = sum(1 for k in chosen if by_key[k]['epoch'] == f['epoch'] and by_key[k]['detector'] == f['detector'])
        return taken < quotas[(f['epoch'], f['detector'])]

    def covers(f):
        return f.get('coverage', 1.0) >= min_coverage

    def delta(a, b):
        if a['wavelength_um'] is None or b['wavelength_um'] is None or not (covers(a) and covers(b)):
            return None  # Not a usable difference pair.
        return abs(a['wavelength_um'] - b['wavelength_um'])

    def label(f):
        return f'{f["obs_id"]} D{f["detector"]} ({f["epoch"]})'

    for f in frames:
        if f['keep']:
            chosen[f['key']] = 'curated exposure (validated by scripts/smoke_compare.py)'
    epochs = sorted(order, key=order.get)
    middle = {e: np.median([f['mjd'] for f in frames if f['epoch'] == e]) for e in epochs}
    for detector in sorted({f['detector'] for f in frames}):
        for e1, e2 in sorted(combinations(epochs, 2), key=lambda pair: -(middle[pair[1]] - middle[pair[0]])):
            for _ in range(seed_pairs):
                options = []
                for a in frames:
                    for b in frames:
                        if (a['epoch'], b['epoch'], a['detector'], b['detector']) != (e1, e2, detector, detector):
                            continue
                        if a['key'] in chosen or b['key'] in chosen or not room(a) or not room(b):
                            continue
                        d = delta(a, b)
                        if d is not None and d <= match_um:
                            options.append((d, -abs(b['mjd'] - a['mjd']), a['key'], b['key']))
                if not options:
                    break
                d, _, ka, kb = min(options)
                chosen[ka] = f'wavelength at the target matches {label(by_key[kb])} within {d:.4f} µm'
                chosen[kb] = f'wavelength at the target matches {label(by_key[ka])} within {d:.4f} µm'
    for (epoch, detector) in sorted(quotas, key=lambda g: (order[g[0]], g[1])):
        pool = [f for f in frames if (f['epoch'], f['detector']) == (epoch, detector)]
        while True:
            options = [f for f in pool if f['key'] not in chosen and room(f)]
            if not options:
                break
            others = [by_key[k] for k in chosen if by_key[k]['detector'] == detector and by_key[k]['epoch'] != epoch]
            same = [by_key[k] for k in chosen if (by_key[k]['epoch'], by_key[k]['detector']) == (epoch, detector)]

            def score(f):
                deltas = [d for d in (delta(f, g) for g in others) if d is not None]
                matches = sum(d <= match_um for d in deltas)
                gap = min((abs(f['mjd'] - g['mjd']) for g in same), default=math.inf)
                return (covers(f), matches, gap, -min(deltas, default=math.inf), -f['mjd'], f['key'])
            best = max(options, key=score)
            matches, gap, closest = score(best)[1:4]
            if len(pool) <= quotas[(epoch, detector)]:
                reason = 'every candidate of this epoch and detector is kept'
            elif not covers(best):
                reason = f'no candidate left that covers {min_coverage:.0%} of the comparison grid'
            elif matches:
                reason = f'wavelength at the target matches {matches} frame(s) of another epoch'
            elif same:
                reason = 'spread in time within the epoch'
            elif others and math.isfinite(-closest):
                reason = f'closest wavelength at the target to another epoch ({-closest:.4f} µm away)'
            else:
                reason = 'first in time'
            chosen[best['key']] = reason
    return chosen


# ---------- orchestration ----------

def run(key, images, published):
    config = TARGETS[key]
    table_path = DISCOVERY / f'{config["table"]}.vot'
    table, table_sha = read_table(table_path), digest(table_path)
    centre = frame_centre(config, table)
    print(f'== {key}: centre RA {centre[0]}, Dec {centre[1]}; cutout {CUTOUT_DEG} deg', flush=True)
    items = candidates(key, config, table)
    staged, failures = [], []

    def fetch(item):
        row = item['row']
        name = f'{row["obs_id"]} D{item["detector"]} ({item["epoch"]})'
        try:
            record, how = stage(key, config, item, centre, images, published, table_sha)
            wl = record['measured']['wavelength_um_at_centre']
            shown = 'unknown' if wl is None else f'{wl:.4f} µm'
            print(f'  OK      {name}  {how}  {record["data_release"]}  λ at centre {shown}', flush=True)
            return record
        except Exception as exc:  # Report every frame; one failure does not stop the others.
            failures.append({'obs_id': str(row['obs_id']), 'detector': item['detector'], 'epoch': item['epoch'], 'error': str(exc)})
            print(f'  FAILED  {name}  {exc}', flush=True)
            return None

    for item in items:
        record = fetch(item)
        if record:
            staged.append(dict(item, record=record))
    frames = [dict(key=s['record']['sha256'], obs_id=s['record']['observation_id'], epoch=s['epoch'], detector=s['detector'],
                   mjd=s['record']['archive_t_min'], wavelength_um=s['record']['measured']['wavelength_um_at_centre'],
                   coverage=s['record']['measured']['grid_coverage'], keep=s['keep'])
              for s in staged]
    quotas = {}
    for group in config['groups']:
        for label, _, _ in config['epochs']:
            quotas[(label, group['detector'])] = len(group['keep']) // len(config['epochs']) if 'keep' in group else group['quota']
    reasons = choose(frames, quotas, config['seed_pairs'])
    selected = [s for s in staged if s['record']['sha256'] in reasons]
    partners = []
    for s in selected:
        detector = next(g.get('partner') for g in config['groups'] if g['detector'] == s['detector'])
        if detector:
            item = dict(row=partner_row(table, s['row'], detector), epoch=s['epoch'], detector=detector, keep=False)
            record = fetch(item)
            if record:
                partners.append(dict(item, record=record))
                reasons[record['sha256']] = (f'simultaneous D{detector} exposure of {s["record"]["observation_id"]} '
                                             f'D{s["detector"]} (same moment through the dichroic)')
    chosen = selected + partners
    chosen.sort(key=lambda s: (s['record']['archive_t_min'], s['detector']))
    inputs = []
    for s in chosen:
        record = {k: v for k, v in s['record'].items() if k != 'measured'}
        path = RECORDS / f'{record["sha256"]}.json'
        path.write_text(json.dumps(record) + '\n')
        inputs.append(dict(fits=os.path.relpath(ACQUIRED / key / Path(staged_folder(s)) / 'original.fits', ROOT / 'demo'),
                           metadata=os.path.relpath(path, ROOT / 'demo')))
    plan = dict(
        target=dict(id=key, name=config['name'], ra=centre[0], dec=centre[1], coordinate_source=config['coordinate_source'],
                    science_context=config['science_context']),
        cutout_deg=CUTOUT_DEG, grid_deg=GRID_DEG, min_grid_coverage=MIN_COVERAGE, wavelength_match_um=MATCH_UM, discovery_table=os.path.relpath(table_path, ROOT), discovery_sha256=table_sha,
        rules=dict(epochs=config['epochs'], releases=sorted(config['releases']), groups=config['groups'], seed_pairs=config['seed_pairs']),
        frames=[dict(obs_id=s['record']['observation_id'], detector=s['detector'], epoch=s['epoch'],
                     observed_at_utc=s['record']['observed_at_utc'], data_release=s['record']['data_release'],
                     calibration=s['record']['calibration'], sha256=s['record']['sha256'],
                     wavelength_um_at_centre=s['record']['measured']['wavelength_um_at_centre'],
                     wavelength_um_at_marker=s['record']['measured']['wavelength_um_at_marker'],
                     grid_coverage=s['record']['measured']['grid_coverage'],
                     predicted=(None if s['record']['predicted_ra'] is None else [s['record']['predicted_ra'], s['record']['predicted_dec']]),
                     selected=s['record']['sha256'] in reasons, reason=reasons.get(s['record']['sha256'], 'not selected'))
                for s in sorted(staged + partners, key=lambda s: (s['record']['archive_t_min'], s['detector']))],
        failures=failures,
        inputs=inputs,
    )
    PLANS.mkdir(parents=True, exist_ok=True)
    (PLANS / f'{key}.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False) + '\n')
    print(f'   {len(chosen)} selected from {len(staged)} candidates (+{len(partners)} partners), {len(failures)} failed. '
          f'Plan: {PLANS / f"{key}.json"}', flush=True)
    return plan


def staged_folder(s):
    record = s['record']
    cutout = record['cutout']
    return hashlib.sha256(f'{record["access_url"]}|{cutout["ra"]:.6f}|{cutout["dec"]:.6f}|{CUTOUT_DEG:.4f}'.encode()).hexdigest()


ORDER = ['m101', 'm31', 'barnard', '3i-atlas']


def inventory(rebase):
    """Targets in display order: planned ones from demo/plans, others as in demo/targets.json.
    rebase(path relative to demo/) gives the path written into the inventory."""
    current = json.loads((ROOT / 'demo' / 'targets.json').read_text())
    by_id = {t['id']: t for t in current['targets']}
    for path in sorted(PLANS.glob('*.json')):
        plan = json.loads(path.read_text())
        by_id[plan['target']['id']] = dict(plan['target'], inputs=plan['inputs'], planned=True)
    targets = sorted(by_id.values(), key=lambda t: ORDER.index(t['id']) if t['id'] in ORDER else len(ORDER))
    for target in targets:
        target['inputs'] = [{kind: rebase(item[kind], target, kind) for kind in ('fits', 'metadata')} for item in target['inputs']]
        target.pop('planned', None)
    return dict(schema_version=1, targets=targets)


def write_staging_config():
    """Preparation inventory that reads the staged FITS (lives in demo/acquired/, so paths are rebased)."""
    data = inventory(lambda path, target, kind: os.path.relpath(ROOT / 'demo' / path, ACQUIRED))
    STAGING_CONFIG.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    print(f'Preparation inventory (reads staged FITS): {STAGING_CONFIG}')


def publish_config():
    """Point demo/targets.json at the published FITS of every planned target (after the bundle is replaced)."""
    planned = {path.stem for path in PLANS.glob('*.json')}

    def rebase(path, target, kind):
        if kind == 'metadata' or target['id'] not in planned:
            return path
        sha = digest(ROOT / 'demo' / path)
        published = PUBLISHED / 'assets' / hashlib.sha256(f'{target["id"]}:{sha}'.encode()).hexdigest() / 'original.fits'
        if not published.is_file() or digest(published) != sha:
            raise ValueError(f'{target["id"]}: {path} is not in the published bundle; prepare and publish it first')
        return os.path.relpath(published, ROOT / 'demo')
    data = inventory(rebase)
    (ROOT / 'demo' / 'targets.json').write_text(json.dumps(data, indent=2) + '\n')
    print('demo/targets.json now reads the published FITS.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('targets', nargs='*', choices=sorted(TARGETS), help='default: all')
    parser.add_argument('--publish', action='store_true', help='rewrite demo/targets.json to read the published FITS')
    args = parser.parse_args()
    if args.publish:
        publish_config()
        return 0
    from backend.app.image_download import ImageSettings
    from backend.app.image_service import ImageService
    # A cache of its own, so a running app's image cache is never pruned by this script.
    images = ImageService(replace(ImageSettings.from_env(), cache_dir=ROOT / '.cache' / 'acquire-demo-targets', cutout_cache_entries=4))
    published = published_index()
    failed = 0
    for key in args.targets or sorted(TARGETS):
        plan = run(key, images, published)
        failed += len(plan['failures'])
    write_staging_config()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
