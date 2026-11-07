"""Pair suggestions (GET /api/pairs), ported from PR #1. Network is mocked; rows are TEST DATA
shaped like the real M31 D1 results (three survey passes about six months apart plus a lone extra)."""
import pytest
from fastapi.testclient import TestClient

from backend.app.analysis.compare import validate
from backend.app.image_download import ImageError
from backend.app.images import get_image_service
from backend.app.irsa import IRSAUnavailable
from backend.app.main import app, get_client
from backend.app.pairs import MAX_CANDIDATES, _frame, build_pair_report, group_visits, separation_deg, shortlist, suggest_pairs
from test_images import ACCESS

client = TestClient(app)
M31 = (10.6847, 41.2687)


def obs(obs_id, t_min, s_ra, s_dec):
    return {'obs_id': obs_id, 't_min': t_min, 's_ra': s_ra, 's_dec': s_dec, 'energy_bandpassname': 'SPHEREx-D1',
            'observed_at_utc': f'utc-{t_min}', 'access_url': f'{ACCESS}&obs={obs_id}'}


OBS = [obs('p1-edge', 60865.6, 10.81, 39.55), obs('p1-mid', 60866.3, 10.49, 41.49), obs('p1-far', 60867.0, 9.82, 41.15),
       obs('p1-extra', 60901.9, 10.48, 41.48),
       obs('p2-mid', 61041.5, 8.81, 41.27), obs('p2-near', 61040.2, 11.85, 41.97),
       obs('p3-near', 61231.0, 10.21, 40.97), obs('p3-mid', 61231.5, 10.66, 41.67)]


def test_separation():
    assert separation_deg(10, 41, 10, 41) == pytest.approx(0)
    assert separation_deg(0, 0, 0, 1) == pytest.approx(1)
    assert separation_deg(0, 89.5, 180, 89.5) == pytest.approx(1)


def test_group_visits_by_time_gap():
    visits = group_visits(OBS)
    assert [o['obs_id'] for o in visits[0]] == ['p1-edge', 'p1-mid', 'p1-far']
    assert len(visits) == 4  # pass 1, the lone extra, pass 2, pass 3
    assert group_visits([]) == []


def test_shortlist_keeps_centres_closest_to_target_per_visit_and_is_bounded():
    picked = shortlist(OBS, *M31, per_visit=1)
    assert [p['obs_id'] for p in picked] == ['p1-mid', 'p1-extra', 'p2-near', 'p3-mid']
    assert [p['visit'] for p in picked] == [0, 1, 2, 3]
    assert len(shortlist(OBS, *M31, per_visit=2)) == 7  # the lone-extra visit only has one
    many = [obs(f'v{n}', 60000 + 30 * n, *M31) for n in range(20)]
    assert len(shortlist(many, *M31, per_visit=1)) == MAX_CANDIDATES


def cand(obs_id, t_min, wl, visit, status='inside', error=None, detector=1):
    return {'obs_id': obs_id, 'image_id': f'id-{obs_id}', 'access_url': f'{ACCESS}&obs={obs_id}', 't_min': t_min,
            'wavelength_um': wl, 'visit': visit, 'detector': detector, 'target_status': status,
            'observed_at_utc': f'utc-{t_min}', 'error': error}


def codes(pair):
    return {reason['code'] for reason in pair['reasons']}


def test_pair_decisions_and_ranking_use_the_shared_rules():
    pairs = suggest_pairs([cand('a', 60866.3, 0.750, 0), cand('b', 61040.2, 0.895, 1),
                           cand('c', 61231.0, 0.893, 2), cand('d', 61231.01, 0.893, 2),  # 14 min after c
                           cand('e', 61231.5, None, 2), cand('out', 61000, 0.9, 1, status='outside'),
                           cand('err', 61010, 0.9, 1, error={'code': 'x'})])
    ids = [(p['a']['obs_id'], p['b']['obs_id']) for p in pairs]
    assert ('c', 'd') not in ids  # too close in time: not listed
    assert not any('out' in pair or 'err' in pair for pair in ids)  # unusable candidates skipped
    first = pairs[0]
    assert first['decision'] == 'ACCEPT' and first['difference_expected'] is True
    assert {first['a']['obs_id'], first['b']['obs_id']} <= {'b', 'c', 'd'}
    assert first['baseline'] == 'between_visits' and first['delta_wavelength_um'] == pytest.approx(0.002)
    assert 'wavelength_match' in codes(first) and 'overlap_not_measured' not in codes(first)
    assert first['a']['access_url'].endswith('obs=' + first['a']['obs_id'])  # Ready for POST /api/compare.
    mismatch = next(p for p in pairs if {p['a']['obs_id'], p['b']['obs_id']} == {'a', 'b'})
    assert mismatch['decision'] == 'WARN' and 'wavelength_mismatch' in codes(mismatch)
    assert mismatch['difference_expected'] is False
    unknown = [p for p in pairs if 'e' in (p['a']['obs_id'], p['b']['obs_id'])]
    assert unknown and all('wavelength_unknown' in codes(p) and p['decision'] == 'WARN' for p in unknown)
    rank = {'ACCEPT': 0, 'WARN': 1, 'REJECT': 2}
    assert [rank[p['decision']] for p in pairs] == sorted(rank[p['decision']] for p in pairs)
    assert all(p['a']['observed_at_utc'] <= p['b']['observed_at_utc'] for p in pairs)  # earlier image is A


def test_suggestions_agree_with_the_compare_rules():
    a, b = cand('a', 61040.2, 0.8946, 1), cand('b', 61231.0, 0.8935, 2)
    (pair,) = suggest_pairs([a, b])
    with_overlap = validate(_frame(a), _frame(b), 'time', overlap=.98)
    assert pair['decision'] == with_overlap.decision == 'ACCEPT'
    assert validate(_frame(a), _frame(b), 'time', overlap=.5).decision == 'REJECT'  # Overlap is decided on compare.


def test_mixed_detectors_are_rejected():
    (pair,) = suggest_pairs([cand('a', 61040.2, 0.8946, 1), cand('b', 61231.0, 2.9751, 2, detector=4)])
    assert pair['decision'] == 'REJECT' and 'band_mismatch' in codes(pair)


def test_no_pairs_from_a_single_candidate():
    assert suggest_pairs([cand('a', 1, .9, 0)]) == []


class FakeIRSA:
    def __init__(self, rows=OBS, fail=False):
        self.rows, self.fail, self.calls = rows, fail, []

    def observations(self, ra, dec, band=None, wavelength_um=None):
        self.calls.append(band)
        if self.fail:
            raise IRSAUnavailable('IRSA TAP could not be reached or timed out. Please retry.')
        return {'status': 'live', 'source': 'fixture', 'truncated': False, 'observations': self.rows}


WAVELENGTHS = {'p1-mid': .901, 'p1-extra': .97, 'p2-near': .895, 'p3-mid': .893}


class FakeService:
    def __init__(self, no_target_wavelength=()):
        self.requests, self.no_target_wavelength = [], set(no_target_wavelength)

    def prepare(self, access_url, ra, dec, cutout_deg):
        obs_id = access_url.split('obs=')[1]
        self.requests.append((obs_id, cutout_deg))
        if obs_id == 'p1-extra':
            raise ImageError('IRSA could not deliver this image. Please retry.')
        spectral = None if obs_id in self.no_target_wavelength else {'wavelength_um': WAVELENGTHS[obs_id], 'bandwidth_um': .01}
        return {'image_id': f'id-{obs_id}', 'preview_url': f'/api/images/id-{obs_id}/preview', 'cache_hit': False,
                'detector': 1, 'target': {'status': 'inside', 'spectral': spectral},
                'center': {'spectral': {'wavelength_um': .9, 'bandwidth_um': .01}}}


def test_build_pair_report_uses_compare_sized_cutouts():
    irsa, service = FakeIRSA(), FakeService()
    report = build_pair_report(irsa, service, *M31, 'SPHEREx-D1', per_visit=1)
    assert irsa.calls == ['SPHEREx-D1']
    assert [r[0] for r in service.requests] == ['p1-mid', 'p1-extra', 'p2-near', 'p3-mid']
    assert {r[1] for r in service.requests} == {0.437}  # What /api/compare needs for a 0.3 deg grid.
    failed = next(c for c in report['candidates'] if c['obs_id'] == 'p1-extra')
    assert failed['error']['message'].startswith('IRSA could not deliver')
    assert report['observations_considered'] == len(OBS) and len(report['visits']) == 4
    best = report['pairs'][0]
    assert best['decision'] == 'ACCEPT' and {best['a']['obs_id'], best['b']['obs_id']} == {'p2-near', 'p3-mid'}
    assert best['a']['image_id'] == 'id-p2-near'
    assert 'not evidence of motion' in report['note'] and report['rules']['cutout_deg'] == 0.437


def test_unreadable_target_wavelength_stays_unknown_not_the_image_centre():
    report = build_pair_report(FakeIRSA(), FakeService(no_target_wavelength={'p3-mid'}), *M31, per_visit=1)
    p3 = next(c for c in report['candidates'] if c['obs_id'] == 'p3-mid')
    assert p3['wavelength_um'] is None  # The centre value (0.9) is never substituted.
    assert all(p['decision'] == 'WARN' for p in report['pairs'] if 'p3-mid' in (p['a']['obs_id'], p['b']['obs_id']))


def test_pairs_endpoint_live_validation_and_unavailable():
    app.dependency_overrides[get_client] = lambda: FakeIRSA()
    app.dependency_overrides[get_image_service] = lambda: FakeService()
    try:
        response = client.get('/api/pairs', params={'ra': M31[0], 'dec': M31[1], 'per_visit': 1})
        assert response.status_code == 200 and response.json()['status'] == 'live'
        assert response.json()['pairs'][0]['decision'] == 'ACCEPT'
        for bad in [{'per_visit': 9}, {'size_deg': 5}, {'band': 'SPHEREx-D7'}, {'band': "SPHEREx-D1' OR 1=1 --"}]:
            assert client.get('/api/pairs', params={'ra': 10, 'dec': 41, **bad}).status_code == 422
        app.dependency_overrides[get_client] = lambda: FakeIRSA(fail=True)
        down = client.get('/api/pairs', params={'ra': 10, 'dec': 41})
        assert down.status_code == 503 and down.json()['status'] == 'unavailable'
    finally:
        app.dependency_overrides.pop(get_client, None)
        app.dependency_overrides.pop(get_image_service, None)
