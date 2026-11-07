"""Adapted contributor band/wavelength tests; no archive or FITS downloads."""
from io import BytesIO
import re
from unittest.mock import patch

from astropy.io.votable import from_table, writeto
from astropy.table import Table, MaskedColumn
from fastapi.testclient import TestClient
import pytest

from backend.app.irsa import BANDS, IRSAClient, build_query, wavelength_coverage
from backend.app.main import app


def spectral_rows():
    table = Table(dict(obs_id=['SYNTHETIC-WITHIN','SYNTHETIC-OUTSIDE','SYNTHETIC-UNKNOWN','SYNTHETIC-INVALID','SYNTHETIC-BOUNDARY'],
                       energy_bandpassname=['SPHEREx-D4']*5, obs_collection=['test-only']*5,
                       access_url=['https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=test-fixture']*5,
                       access_format=['application/x-votable+xml']*5, s_ra=[10.]*5,s_dec=[20.]*5,
                       t_min=[60000.,60001.,60002.,60003.,60004.],t_max=[60000.1]*5,t_exptime=[100.]*5,
                       em_max=[3e-6,1.1e-6,0.,2e-6,2.5e-6]))
    table['em_min'] = MaskedColumn([2e-6,1e-6,0.,3e-6,2.5e-6], mask=[False,False,True,False,False])
    output=BytesIO();writeto(from_table(table),output)
    return output.getvalue().replace(b'<RESOURCE type="results">',b'<RESOURCE type="results"><INFO name="QUERY_STATUS" value="OK"/>')


def test_query_filters_archive_before_limit_in_metres_and_keeps_unknowns():
    base = build_query(10,20)
    assert 'em_min <=' not in base and 'energy_bandpassname =' not in base
    query = build_query(10,20,band='SPHEREx-D4',wavelength_um=2.5)
    assert "AND energy_bandpassname = 'SPHEREx-D4'" in query
    assert float(re.findall(r'em_min <= ([0-9.e+-]+)',query)[-1]) == 2.5e-6
    assert float(re.search(r'em_max >= ([0-9.e+-]+)',query)[1]) == 2.5e-6
    assert 'em_min IS NULL OR em_max IS NULL' in query
    assert 'em_min <= 0 OR em_max < em_min' in query
    assert 'TOP 101' in query and 's_region' in query
    assert 's_dec BETWEEN' not in query  # no hidden image-center restriction


@pytest.mark.parametrize('band', ['D1','SPHEREx-D7',"SPHEREx-D1' OR 1=1 --",''])
def test_invalid_band_cannot_enter_adql(band):
    with pytest.raises(ValueError):build_query(10,20,band=band)


@pytest.mark.parametrize('wavelength', [0.1,9,float('nan'),float('inf')])
def test_invalid_wavelength_cannot_enter_adql(wavelength):
    with pytest.raises(ValueError):build_query(10,20,wavelength_um=wavelength)


@pytest.mark.parametrize('suffix', ['band=D1','band=SPHEREx-D7','wavelength_um=nan','wavelength_um=inf','wavelength_um=9','wavelength_um=x'])
def test_api_rejects_invalid_filter_without_network(suffix):
    with patch('backend.app.irsa.tap',side_effect=AssertionError('must not query')):
        assert TestClient(app).get('/api/observations?ra=10&dec=20&'+suffix).status_code==422


def test_real_client_path_preserves_unknowns_and_scientific_identity():
    with patch('backend.app.irsa.verify_schema'),patch('backend.app.irsa.tap',return_value=spectral_rows()) as remote:
        response=TestClient(app).get('/api/observations?ra=10&dec=20&band=SPHEREx-D4&wavelength_um=2.5')
    assert response.status_code==200
    body=response.json()
    assert body['band']=='SPHEREx-D4' and body['wavelength_um']==2.5
    assert body['unknown_wavelength_count']==2
    assert [row['obs_id'] for row in body['observations']]==['SYNTHETIC-WITHIN','SYNTHETIC-UNKNOWN','SYNTHETIC-INVALID','SYNTHETIC-BOUNDARY']
    assert body['observations'][0]['observed_at_utc'].startswith('2023-02-25')
    assert all(row['energy_bandpassname']=='SPHEREx-D4' for row in body['observations'])
    assert 'em_min IS NULL' in remote.call_args.args[0]


@pytest.mark.parametrize('band',BANDS)
def test_each_detector_label_is_whitelisted(band):
    assert f"energy_bandpassname = '{band}'" in build_query(10,20,band=band)


def test_invalid_filter_validated_before_schema_query():
    with patch('backend.app.irsa.tap',side_effect=AssertionError('must not query')):
        with pytest.raises(ValueError):IRSAClient().observations(10,20,wavelength_um=9)


@pytest.mark.parametrize('low,high',[(None,None),(None,2e-6),(2e-6,None),(3e-6,2e-6),(-1,2e-6),(float('nan'),2e-6)])
def test_unknown_bounds_never_exclude(low,high):
    assert wavelength_coverage(dict(em_min=low,em_max=high),2.5)=='unknown'


def test_query_does_not_round_away_input_wavelength_precision():
    wavelength=2.500000000000123
    query=build_query(10,20,wavelength_um=wavelength)
    assert float(re.search(r'em_max >= ([0-9.e+-]+)',query)[1]) == wavelength / 1_000_000
