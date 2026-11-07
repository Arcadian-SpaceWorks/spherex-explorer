from io import BytesIO
from unittest.mock import patch

import numpy as np
import pytest
import requests
from astropy.table import Table
from astropy.io.votable import from_table, writeto
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.irsa import (COLUMNS, IRSAUnavailable, angular_distance_deg, build_query,
                              parse_observations, scalar, verify_schema, tap)

client = TestClient(app)


def votable(count=1):
    table = Table()
    for name in COLUMNS:
        if name in ('obs_id', 'energy_bandpassname', 'obs_collection', 'access_url', 'access_format'):
            table[name] = ['test-fixture'] * count
        else:
            table[name] = [60000.] * count
    output = BytesIO()
    document = from_table(table)
    for index, field in enumerate(document.resources[0].tables[0].fields):
        field.ID = f'col_{index}'  # IRSA IDs differ from scientific column names.
    writeto(document, output)
    return output.getvalue().replace(b'<RESOURCE type="results">', b'<RESOURCE type="results"><INFO name="QUERY_STATUS" value="OK"/>')


@pytest.mark.parametrize('query', ['ra=-1&dec=0','ra=360&dec=0','ra=1&dec=91',
                                  'ra=nan&dec=0','ra=0&dec=inf','ra=x&dec=0','ra=0'])
def test_invalid_coordinates(query):
    assert client.get('/api/observations?' + query).status_code == 422


def test_health():
    assert client.get('/api/health').json() == {'status': 'ok'}


def test_live_response():
    with patch('backend.app.irsa.verify_schema'), patch('backend.app.irsa.tap', return_value=votable()):
        response = client.get('/api/observations?ra=0&dec=-90')
    assert response.status_code == 200
    assert response.json()['status'] == 'live'
    assert response.json()['count'] == 1
    assert response.json()['observations'][0]['observed_at_utc'].startswith('2023-02-25')


def test_empty_is_live_not_unavailable():
    with patch('backend.app.irsa.verify_schema'), patch('backend.app.irsa.tap', return_value=votable(0)):
        response = client.get('/api/observations?ra=0&dec=0')
    assert response.json()['status'] == 'live'
    assert response.json()['observations'] == []


def test_upstream_unavailable():
    with patch('backend.app.irsa.verify_schema', side_effect=IRSAUnavailable('IRSA unavailable')):
        response = client.get('/api/observations?ra=0&dec=0')
    assert response.status_code == 503
    assert response.json()['status'] == 'unavailable'
    assert response.json()['observations'] == []


def test_query_uses_footprints_and_limit():
    query = build_query(0, -90)
    assert 'TOP 101' in query
    assert "CONTAINS(POINT('ICRS',0.0000000000,-90.0000000000),s_region)" in query
    with pytest.raises(ValueError):
        build_query(float('nan'), 0)


def test_schema_change_fails_explicitly():
    verify_schema.cache_clear()
    with patch('backend.app.irsa.tap', return_value=b'column_name\nobs_id\n'):
        with pytest.raises(IRSAUnavailable, match='schema'):
            verify_schema()
    verify_schema.cache_clear()


@pytest.mark.parametrize('payload', [b'not xml', b'<VOTABLE><RESOURCE><INFO name="QUERY_STATUS" value="ERROR">bad query</INFO></RESOURCE></VOTABLE>'])
def test_bad_tap_response(payload):
    with pytest.raises(IRSAUnavailable):
        parse_observations(payload)


def test_truncation_and_nulls():
    rows, truncated = parse_observations(votable(101))
    assert len(rows) == 100 and truncated
    assert scalar(np.ma.masked) is None
    assert scalar(np.float64('nan')) is None
    assert scalar(np.float64(2)) == 2


def test_network_timeout():
    with patch('backend.app.irsa.requests.get', side_effect=requests.Timeout):
        with pytest.raises(IRSAUnavailable, match='timed out'):
            tap('SELECT TOP 1 obs_id FROM spherex.obscore', 'votable')


def test_wavelength_filter_enters_query_in_metres():
    query = build_query(10, 20, wavelength_um=2.5)
    assert 'AND em_min <= 2.500000e-06 AND em_max >= 2.500000e-06' in query
    assert 'em_min <=' not in build_query(10, 20)
    combined = build_query(10, 20, band='SPHEREx-D4', wavelength_um=3)
    assert "energy_bandpassname = 'SPHEREx-D4'" in combined and 'em_max >= 3.000000e-06' in combined
    for bad in (0.1, 9, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            build_query(10, 20, wavelength_um=bad)


def test_wavelength_filter_is_passed_to_archive_and_echoed():
    with patch('backend.app.irsa.verify_schema'), patch('backend.app.irsa.tap', return_value=votable()) as tap_call:
        response = client.get('/api/observations?ra=10&dec=20&wavelength_um=1.25')
    assert response.status_code == 200
    assert response.json()['wavelength_um'] == 1.25
    assert 'em_min <= 1.250000e-06' in tap_call.call_args.args[0]


@pytest.mark.parametrize('value', ['0.2', '6', 'nan', 'inf', 'x'])
def test_invalid_wavelength_rejected(value):
    assert client.get(f'/api/observations?ra=10&dec=20&wavelength_um={value}').status_code == 422


def test_band_filter_is_passed_to_archive():
    with patch('backend.app.irsa.verify_schema'), patch('backend.app.irsa.tap', return_value=votable()) as tap_call:
        response = client.get('/api/observations?ra=10&dec=20&band=SPHEREx-D3')
    assert response.json()['band'] == 'SPHEREx-D3'
    assert "energy_bandpassname = 'SPHEREx-D3'" in tap_call.call_args.args[0]


def centres_votable(centres):
    """VOTable whose rows have the given (s_ra, s_dec) image centres."""
    table = Table()
    for name in COLUMNS:
        if name in ('obs_id', 'energy_bandpassname', 'obs_collection', 'access_url', 'access_format'):
            table[name] = [f'test-fixture-{i}' for i in range(len(centres))]
        elif name == 's_ra':
            table[name] = [ra for ra, _ in centres]
        elif name == 's_dec':
            table[name] = [dec for _, dec in centres]
        else:
            table[name] = [60000.] * len(centres)
    output = BytesIO()
    writeto(from_table(table), output)
    return output.getvalue().replace(b'<RESOURCE type="results">', b'<RESOURCE type="results"><INFO name="QUERY_STATUS" value="OK"/>')


def test_angular_distance():
    assert angular_distance_deg(10, 20, 10, 20) == 0
    assert angular_distance_deg(0, 0, 0, 1) == pytest.approx(1)
    assert angular_distance_deg(359.5, 0, 0.5, 0) == pytest.approx(1)  # across RA 0°
    assert angular_distance_deg(0, 60, 2, 60) == pytest.approx(1, rel=1e-3)  # RA shrinks with cos(dec)
    assert angular_distance_deg(0, 89.5, 180, 89.5) == pytest.approx(1)  # across the pole


def test_offset_box_in_query():
    query = build_query(210, 54, max_offset_deg=0.5)
    assert 's_dec BETWEEN 53.5000000000 AND 54.5000000000' in query
    assert 's_ra BETWEEN 209.1' in query and 'AND 210.8' in query  # widened by 1/cos(dec)
    assert 's_dec BETWEEN' not in build_query(210, 54)
    for bad in (0.01, 5, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            build_query(210, 54, max_offset_deg=bad)


def test_offset_box_wraps_ra_and_handles_poles():
    assert '(s_ra >= 359.' in build_query(0.2, 0, max_offset_deg=1) and 'OR s_ra <= 1.2' in build_query(0.2, 0, max_offset_deg=1)
    assert '(s_ra >= 358.79' in build_query(359.8, 0, max_offset_deg=1) and 'OR s_ra <= 0.8' in build_query(359.8, 0, max_offset_deg=1)
    polar = build_query(10, 89.5, max_offset_deg=1)
    assert 's_dec BETWEEN 88.5000000000 AND 90.0000000000' in polar and 's_ra' not in polar.split('WHERE')[1].split('ORDER')[0]


def test_offset_filter_keeps_only_centres_inside_circle():
    # Inside (0.3°), box corner but outside the circle (~0.57°), and just outside on the edge.
    centres = [(210.0, 54.3), (210.0 + 0.4 / 0.588, 54.4), (210.0, 54.0 - 0.51)]
    with patch('backend.app.irsa.verify_schema'), patch('backend.app.irsa.tap', return_value=centres_votable(centres)) as tap_call:
        response = client.get('/api/observations?ra=210&dec=54&max_offset_deg=0.5')
    body = response.json()
    assert response.status_code == 200
    assert body['max_offset_deg'] == 0.5 and body['count'] == 1
    assert body['observations'][0]['center_offset_deg'] == pytest.approx(0.3)
    assert 's_dec BETWEEN' in tap_call.call_args.args[0]


def test_offset_reported_without_filter():
    with patch('backend.app.irsa.verify_schema'), patch('backend.app.irsa.tap', return_value=centres_votable([(210.0, 55.0)])):
        body = client.get('/api/observations?ra=210&dec=54').json()
    assert body['max_offset_deg'] is None and body['count'] == 1
    assert body['observations'][0]['center_offset_deg'] == pytest.approx(1)


@pytest.mark.parametrize('value', ['0', '0.01', '3.5', 'nan', 'x'])
def test_invalid_offset_rejected(value):
    assert client.get(f'/api/observations?ra=10&dec=20&max_offset_deg={value}').status_code == 422
