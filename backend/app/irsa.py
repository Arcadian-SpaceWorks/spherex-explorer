"""Bounded, read-only IRSA TAP/ObsCore client. No synthetic fallback data."""
from functools import lru_cache
from io import BytesIO
import csv
import math
import xml.etree.ElementTree as ET

import numpy as np
import requests
from astropy.io.votable import parse_single_table
from astropy.time import Time

TAP_URL = 'https://irsa.ipac.caltech.edu/TAP/sync'
TABLE = 'spherex.obscore'
COLUMNS = ('obs_id', 's_ra', 's_dec', 't_min', 't_max', 't_exptime',
           'em_min', 'em_max', 'energy_bandpassname', 'obs_collection',
           'access_url', 'access_format')
LIMIT = 100
BANDS = tuple(f'SPHEREx-D{n}' for n in range(1, 7))  # the only values allowed into ADQL


class IRSAUnavailable(Exception):
    pass


def tap(query, format):
    try:
        response = requests.get(TAP_URL, params={
            'REQUEST': 'doQuery', 'LANG': 'ADQL', 'FORMAT': format,
            'QUERY': query, 'MAXREC': LIMIT + 1,
        }, timeout=(10, 50))
        response.raise_for_status()
        return response.content
    except requests.RequestException as exc:
        raise IRSAUnavailable('IRSA TAP could not be reached or timed out. Please retry.') from exc


@lru_cache(maxsize=1)
def verify_schema():
    payload = tap("SELECT column_name FROM TAP_SCHEMA.columns WHERE table_name = 'spherex.obscore'", 'csv')
    try:
        columns = {row['column_name'] for row in csv.DictReader(payload.decode('utf-8').splitlines())}
    except (KeyError, UnicodeError) as exc:
        raise IRSAUnavailable('IRSA returned an unreadable schema response.') from exc
    if not set(COLUMNS + ('s_region',)).issubset(columns):
        raise IRSAUnavailable('The published SPHEREx schema is unavailable or has changed.')
    return True


def build_query(ra, dec, band=None):
    # Only validated finite floats and whitelisted band names enter ADQL; never interpolate user text.
    if not math.isfinite(ra) or not math.isfinite(dec) or not 0 <= ra < 360 or not -90 <= dec <= 90:
        raise ValueError('Invalid ICRS coordinates')
    band_filter = ''
    if band is not None:
        if band not in BANDS:
            raise ValueError('Invalid SPHEREx band')
        band_filter = f"AND energy_bandpassname = '{band}' "
    return (f"SELECT TOP {LIMIT + 1} {', '.join(COLUMNS)} FROM {TABLE} "
            f"WHERE 1=CONTAINS(POINT('ICRS',{ra:.10f},{dec:.10f}),s_region) "
            f"{band_filter}"
            'ORDER BY t_min DESC, obs_id ASC, energy_bandpassname ASC')


def scalar(value):
    if np.ma.is_masked(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return value.decode('utf-8')
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def parse_observations(payload):
    try:
        root = ET.fromstring(payload)
        statuses = [node for node in root.iter() if node.tag.split('}')[-1] == 'INFO'
                    and node.attrib.get('name') == 'QUERY_STATUS']
        if not statuses or any(node.attrib.get('value') == 'ERROR' for node in statuses):
            raise ValueError('TAP query did not report success')
        table = parse_single_table(BytesIO(payload)).to_table(use_names_over_ids=True)
        if not set(COLUMNS).issubset(table.colnames):
            raise ValueError('Missing metadata columns')
        rows = []
        for row in table[:LIMIT]:
            record = {column: scalar(row[column]) for column in COLUMNS}
            record['observed_at_utc'] = (Time(record['t_min'], format='mjd', scale='utc').isot
                                         if record['t_min'] is not None else None)
            rows.append(record)
        truncated = len(table) > LIMIT or any(node.attrib.get('value') == 'OVERFLOW' for node in statuses)
        return rows, truncated
    except Exception as exc:
        raise IRSAUnavailable('IRSA returned an invalid or unsuccessful TAP response.') from exc


class IRSAClient:
    def observations(self, ra, dec, band=None):
        verify_schema()
        rows, truncated = parse_observations(tap(build_query(ra, dec, band), 'votable'))
        return {'status': 'live', 'source': TAP_URL, 'table': TABLE,
                'ra': ra, 'dec': dec, 'band': band, 'match': 'point-in-footprint',
                'limit': LIMIT, 'truncated': truncated, 'count': len(rows), 'observations': rows}
