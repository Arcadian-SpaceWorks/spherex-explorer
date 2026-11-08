"""No network: frame selection for the larger demo sets (scripts/acquire_demo_targets.py)."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from astropy.table import Table
from astropy.time import Time

from backend.app.demo import Acquisition
from scripts.acquire_demo_targets import (TARGETS, candidates, choose, frame_centre, gaia_astrometry, propagate,
                                          read_table, separation_deg, DISCOVERY)

ROOT = Path(__file__).resolve().parents[2]


# TEST DATA: synthetic frames; wavelengths chosen so exactly one cross-epoch pair matches.
def frame(key, epoch, mjd, wavelength, detector=3, keep=False):
    return dict(key=key, obs_id=key.upper(), epoch=epoch, detector=detector, mjd=mjd, wavelength_um=wavelength, keep=keep)


def test_matched_pairs_across_the_longest_baseline_are_kept_first():
    frames = [frame('a1', 'early', 0.0, 1.700), frame('a2', 'early', 1.0, 1.900), frame('a3', 'early', 2.0, 2.100),
              frame('b1', 'middle', 200.0, 1.950), frame('b2', 'middle', 201.0, 2.300),
              frame('c1', 'late', 365.0, 1.712), frame('c2', 'late', 366.0, 2.200), frame('c3', 'late', 367.0, 2.250)]
    quotas = {('early', 3): 2, ('middle', 3): 1, ('late', 3): 2}
    reasons = choose(frames, quotas, seed_pairs=1)
    assert 'within 0.0120 µm' in reasons['a1'] and 'within 0.0120 µm' in reasons['c1']  # 1-year pair seeded first.
    assert len(reasons) == 5
    per_group = {}
    for key in reasons:
        f = next(x for x in frames if x['key'] == key)
        per_group[f['epoch']] = per_group.get(f['epoch'], 0) + 1
    assert per_group == {'early': 2, 'middle': 1, 'late': 2}
    assert choose(frames, quotas, seed_pairs=1) == reasons  # Deterministic.


def test_no_pair_is_called_a_match_outside_the_compare_tolerance():
    frames = [frame('a', 'early', 0.0, 1.70), frame('b', 'late', 365.0, 1.73), frame('c', 'late', 366.0, 1.90)]
    reasons = choose(frames, {('early', 3): 1, ('late', 3): 1}, seed_pairs=2)
    assert not any('matches' in reason for reason in reasons.values())
    assert sorted(reasons) == ['a', 'b']
    assert 'closest wavelength' in reasons['b'] and '0.0300 µm away' in reasons['b']


def test_curated_frames_are_always_kept_and_fill_their_quota():
    frames = [frame('keep', 'early', 0.0, 0.75, detector=1, keep=True), frame('other', 'early', 0.5, 0.89, detector=1)]
    assert list(choose(frames, {('early', 1): 1}, seed_pairs=1)) == ['keep']


def test_fill_spreads_frames_in_time_within_an_epoch():
    frames = [frame(f'f{i}', 'only', float(i), None) for i in range(10)]
    reasons = choose(frames, {('only', 3): 3}, seed_pairs=0)
    assert sorted(reasons) == ['f0', 'f4', 'f9'] or sorted(reasons) == ['f0', 'f5', 'f9']


def test_barnard_gaia_propagation_moves_ten_arcseconds_a_year_mostly_north():
    gaia = gaia_astrometry()
    assert gaia['ref_epoch'] == 2016.0
    start = Time('2025-08-15', scale='utc').mjd
    ra1, dec1 = propagate(gaia, start)
    ra2, dec2 = propagate(gaia, start + 365.25)
    assert separation_deg(ra1, dec1, ra2, dec2) * 3600 == pytest.approx(10.39, abs=0.02)
    assert (dec2 - dec1) * 3600 == pytest.approx(10.362, abs=0.01)
    assert ra2 < ra1  # Westward component (pmRA is negative).


def test_comet_frame_centre_is_the_mean_of_the_official_predicted_path():
    config = TARGETS['3i-atlas']
    table = read_table(DISCOVERY / '3i-atlas.vot')
    assert frame_centre(config, table) == (167.2031, 5.1481)
    rows = candidates('3i-atlas', config, table)
    assert sorted({r['detector'] for r in rows}) == [2, 5]
    assert sum(r['detector'] == 5 for r in rows) == 12 and sum(r['detector'] == 2 for r in rows) == 6
    # The comet stays inside the 0.3 deg comparison grid around the fixed centre.
    assert max(separation_deg(float(r['row']['comet_ra']), float(r['row']['comet_dec']), 167.2031, 5.1481) for r in rows) < 0.13


def test_each_epoch_uses_one_data_release_and_barnard_spans_two():
    table = read_table(DISCOVERY / 'barnard.vot')
    rows = candidates('barnard', TARGETS['barnard'], table)
    by_epoch = {}
    for r in rows:
        by_epoch.setdefault(r['epoch'], set()).add(str(r['row']['obs_collection']))
    assert by_epoch == {'August 2025': {'spherex_qr2'}, 'March 2026': {'spherex_qr2'}, 'August 2026': {'spherex_qr3'}}


def test_an_epoch_mixing_releases_is_refused():
    table = Table(rows=[('o1', 60900.0, 'spherex_qr2', 'SPHEREx-D3', 'https://example/1', 1e-6, 2e-6),
                        ('o2', 60900.5, 'spherex_qr3', 'SPHEREx-D3', 'https://example/2', 1e-6, 2e-6)],
                  names=['obs_id', 't_min', 'obs_collection', 'energy_bandpassname', 'access_url', 'em_min', 'em_max'])
    config = dict(deepcopy(TARGETS['barnard']), epochs=[('test', '2025-01-01', '2026-12-31')])
    with pytest.raises(ValueError, match='must not mix data releases'):
        candidates('barnard', config, table)


def test_a_predicted_position_needs_both_coordinates():
    base = dict(mission='SPHEREx', data_release='spherex_qr2', calibration='l2b-v20', ra=167.2031, dec=5.1481,
                position_source='https://irsa.ipac.caltech.edu/', position_mode='fixed-sky-region', position_note='test',
                discovery_sha256='0' * 64, archive_em_min_m=3.8e-6, archive_em_max_m=4.4e-6)
    assert Acquisition(**base).predicted_ra is None
    assert Acquisition(**base, predicted_ra=167.28, predicted_dec=5.12).predicted_dec == 5.12
    with pytest.raises(ValueError, match='both RA and Dec'):
        Acquisition(**base, predicted_ra=167.28)


def test_committed_plans_match_their_selection():
    for path in sorted((ROOT / 'demo' / 'plans').glob('*.json')):
        plan = json.loads(path.read_text())
        selected = [f for f in plan['frames'] if f['selected']]
        assert len(selected) == len(plan['inputs']), path.name
        assert not plan['failures'], path.name
        assert all(f['reason'] != 'not selected' for f in selected)


def test_a_frame_clipped_at_a_detector_edge_never_seeds_a_pair():
    # The best wavelength match covers too little of the comparison grid to be differenced.
    frames = [dict(frame('edge', 'early', 0.0, 2.411), coverage=0.40), dict(frame('full', 'early', 1.0, 1.873), coverage=1.0),
              dict(frame('late-edge', 'late', 365.0, 2.411), coverage=1.0), dict(frame('late-full', 'late', 366.0, 1.879), coverage=0.99)]
    reasons = choose(frames, {('early', 3): 1, ('late', 3): 1}, seed_pairs=1)
    assert sorted(reasons) == ['full', 'late-full']
    assert 'within 0.0060 µm' in reasons['full']
