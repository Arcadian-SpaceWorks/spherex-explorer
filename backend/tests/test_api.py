from io import BytesIO
from unittest.mock import patch

import numpy as np
import pytest
import requests
from astropy.table import Table
from astropy.io.votable import from_table, writeto
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.irsa import (COLUMNS, IRSAUnavailable, build_query,
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
