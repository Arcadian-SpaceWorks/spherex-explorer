"""Tests for the band filter, cutout cache split and pair suggestions. Network is mocked."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.image_download import ImageError, ImageSettings
from backend.app.image_service import ImageService
from backend.app.images import get_image_service
from backend.app.irsa import IRSAUnavailable, build_query
from backend.app.main import app, get_client
from backend.app.pairs import (build_pair_report, group_visits, separation_deg, shortlist,
                               suggest_pairs)
from test_api import votable
from test_cutouts import RecordingDownloader
from test_images import ACCESS, mef  # noqa: F401 (fixture)

client = TestClient(app)
M31 = (10.6847, 41.2687)


# ---------- band filter ----------
def test_band_filter_in_query_and_unchanged_without_band():
    assert "AND energy_bandpassname = 'SPHEREx-D1' " in build_query(*M31, 'SPHEREx-D1')
    assert 'energy_bandpassname =' not in build_query(*M31)


@pytest.mark.parametrize('band', ['D1', 'SPHEREx-D7', "SPHEREx-D1' OR 1=1 --", ''])
def test_band_is_whitelisted(band):
    with pytest.raises(ValueError):
        build_query(*M31, band)


@pytest.mark.parametrize('band', ['D1', 'SPHEREx-D7', "SPHEREx-D1' OR 1=1 --"])
def test_api_rejects_bad_band(band):
    assert client.get('/api/observations', params={'ra': 10, 'dec': 41, 'band': band}).status_code == 422
    assert client.get('/api/pairs', params={'ra': 10, 'dec': 41, 'band': band}).status_code == 422


def test_api_band_reaches_the_tap_query():
    with patch('backend.app.irsa.verify_schema'), patch('backend.app.irsa.tap', return_value=votable()) as tap:
        response = client.get('/api/observations', params={'ra': 10, 'dec': 41, 'band': 'SPHEREx-D4'})
    assert response.status_code == 200 and response.json()['band'] == 'SPHEREx-D4'
    assert "energy_bandpassname = 'SPHEREx-D4'" in tap.call_args.args[0]


# ---------- visits and shortlist ----------
def obs(obs_id, t_min, s_ra, s_dec):
    return {'obs_id': obs_id, 't_min': t_min, 's_ra': s_ra, 's_dec': s_dec, 'energy_bandpassname': 'SPHEREx-D1',
            'observed_at_utc': f'utc-{t_min}', 'access_url': f'{ACCESS}&obs={obs_id}'}


# Shaped like the real M31 D1 results: three passes about six months apart plus a lone extra.
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
    assert [[o['obs_id'] for o in v] for v in visits][0] == ['p1-edge', 'p1-mid', 'p1-far']
    assert len(visits) == 4      # pass 1, the lone extra, pass 2, pass 3
    assert group_visits([]) == []


def test_shortlist_keeps_centres_closest_to_target_per_visit():
    picked = shortlist(OBS, *M31, per_visit=1)
    assert [p['obs_id'] for p in picked] == ['p1-mid', 'p1-extra', 'p2-near', 'p3-mid']
    assert [p['visit'] for p in picked] == [0, 1, 2, 3]
    assert len(shortlist(OBS, *M31, per_visit=2)) == 7    # the lone-extra visit only has one


# ---------- pair decisions ----------
def cand(obs_id, t_min, wl, visit, status='inside', error=None):
    return {'obs_id': obs_id, 'image_id': f'id-{obs_id}', 't_min': t_min, 'wavelength_um': wl, 'visit': visit,
            'target_status': status, 'observed_at_utc': f'utc-{t_min}', 'error': error}


def test_pair_decisions_and_ranking():
    pairs = suggest_pairs([cand('a', 60866.3, 0.750, 0), cand('b', 61040.2, 0.895, 1),
                           cand('c', 61231.0, 0.893, 2), cand('d', 61231.01, 0.893, 2),   # 14 min after c
                           cand('e', 61231.5, None, 2), cand('out', 61000, 0.9, 1, status='outside'),
                           cand('err', 61010, 0.9, 1, error={'code': 'x'})])
    ids = [(p['a']['obs_id'], p['b']['obs_id']) for p in pairs]
    assert ('c', 'd') not in ids                                       # too close in time
    assert not any('out' in pair or 'err' in pair for pair in ids)    # unusable candidates skipped
    first = pairs[0]
    assert first['decision'] == 'ACCEPT' and first['difference_allowed'] is True
    assert {first['a']['obs_id'], first['b']['obs_id']} <= {'b', 'c', 'd'}
    assert first['baseline'] == 'between_visits' and first['delta_wavelength_um'] == pytest.approx(0.002)
    mismatch = next(p for p in pairs if {p['a']['obs_id'], p['b']['obs_id']} == {'a', 'b'})
    assert mismatch['decision'] == 'WARN' and mismatch['reasons'][0]['code'] == 'wavelength_mismatch'
    assert mismatch['difference_allowed'] is False
    unknown = [p for p in pairs if 'e' in (p['a']['obs_id'], p['b']['obs_id'])]
    assert unknown and all(p['reasons'][0]['code'] == 'wavelength_unknown' for p in unknown)
    decisions = [p['decision'] for p in pairs]
    assert decisions == sorted(decisions, key=lambda d: d != 'ACCEPT')   # ACCEPT pairs listed first
    assert all(p['a']['observed_at_utc'] <= p['b']['observed_at_utc'] for p in pairs)  # earlier image is A


def test_no_pairs_from_a_single_candidate():
    assert suggest_pairs([cand('a', 1, .9, 0)]) == []


# ---------- report and endpoint ----------
class FakeIRSA:
    def __init__(self, rows=OBS, fail=False):
        self.rows, self.fail, self.calls = rows, fail, []

    def observations(self, ra, dec, band=None):
        self.calls.append(band)
        if self.fail:
            raise IRSAUnavailable('IRSA TAP could not be reached or timed out. Please retry.')
        return {'status': 'live', 'source': 'fixture', 'truncated': False, 'observations': self.rows}


WAVELENGTHS = {'p1-mid': .901, 'p1-extra': .97, 'p2-near': .895, 'p3-mid': .893}


class FakeService:
    def __init__(self):
        self.requests = []

    def prepare(self, access_url, ra, dec, cutout_deg):
        obs_id = access_url.split('obs=')[1]
        self.requests.append((obs_id, cutout_deg))
        if obs_id == 'p1-extra':
            raise ImageError('IRSA could not deliver this image. Please retry.')
        return {'image_id': f'id-{obs_id}', 'preview_url': f'/api/images/id-{obs_id}/preview', 'cache_hit': False,
                'target': {'status': 'inside', 'spectral': {'wavelength_um': WAVELENGTHS[obs_id]}},
                'center': {'spectral': None}}


def test_build_pair_report():
    irsa, service = FakeIRSA(), FakeService()
    report = build_pair_report(irsa, service, *M31, 'SPHEREx-D1', per_visit=1, cutout_deg=0.3)
    assert irsa.calls == ['SPHEREx-D1']
    assert [r[0] for r in service.requests] == ['p1-mid', 'p1-extra', 'p2-near', 'p3-mid']
    assert all(r[1] == 0.3 for r in service.requests)
    failed = next(c for c in report['candidates'] if c['obs_id'] == 'p1-extra')
    assert failed['error']['message'].startswith('IRSA could not deliver')
    assert report['observations_considered'] == len(OBS) and len(report['visits']) == 4
    assert report['candidates'][0]['wavelength_source'] == 'target_pixel'
    best = report['pairs'][0]
    assert best['decision'] == 'ACCEPT' and {best['a']['obs_id'], best['b']['obs_id']} == {'p2-near', 'p3-mid'}
    assert 'not evidence of motion' in report['note']


def test_pairs_endpoint_live_and_unavailable():
    app.dependency_overrides[get_client] = lambda: FakeIRSA()
    app.dependency_overrides[get_image_service] = lambda: FakeService()
    try:
        response = client.get('/api/pairs', params={'ra': M31[0], 'dec': M31[1], 'per_visit': 1})
        assert response.status_code == 200 and response.json()['status'] == 'live'
        assert response.json()['pairs'][0]['decision'] == 'ACCEPT'
        assert client.get('/api/pairs', params={'ra': 10, 'dec': 41, 'per_visit': 9}).status_code == 422
        assert client.get('/api/pairs', params={'ra': 10, 'dec': 41, 'cutout_deg': 5}).status_code == 422
        app.dependency_overrides[get_client] = lambda: FakeIRSA(fail=True)
        down = client.get('/api/pairs', params={'ra': 10, 'dec': 41})
        assert down.status_code == 503 and down.json()['status'] == 'unavailable'
    finally:
        app.dependency_overrides.pop(get_client, None)
        app.dependency_overrides.pop(get_image_service, None)


# ---------- cache: cutouts do not evict full images ----------
def test_cutouts_have_their_own_cache_limit(tmp_path, mef):
    settings = ImageSettings(cache_dir=tmp_path / 'cache', max_bytes=1024 * 1024, cache_entries=1,
                             cache_ttl=60, cutout_cache_entries=2)
    service = ImageService(settings, RecordingDownloader(mef))
    full = service.prepare(ACCESS, 210, 54)
    cuts = [service.prepare(ACCESS, 210, 54, size) for size in (0.1, 0.2, 0.3)]
    kept = {p.name for p in settings.cache_dir.iterdir() if not p.name.startswith('.')}
    assert full['image_id'] in kept                       # the full image survived three cutouts
    assert cuts[0]['image_id'] not in kept                # oldest cutout evicted
    assert {cuts[1]['image_id'], cuts[2]['image_id']} <= kept
    assert len(kept) == 3
