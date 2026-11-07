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
BANDS = tuple(f'SPHEREx-D{n}' for n in range(1, 7))
WAVELENGTH_MIN_UM, WAVELENGTH_MAX_UM = 0.7, 5.1


def wavelength_coverage(row, wavelength_um):
    """ObsCore bounds are in metres; unknown/inconsistent bounds are not exclusions.

    This is whole-product spectral coverage, never a target-pixel wavelength test.
    """
    low, high = row.get('em_min'), row.get('em_max')
    if (low is None or high is None or not math.isfinite(low) or not math.isfinite(high)
            or low <= 0 or high < low):
        return 'unknown'
    return 'range_includes' if low <= wavelength_um / 1_000_000 <= high else 'range_excludes'


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


def build_query(ra, dec, band=None, wavelength_um=None):
    # Only validated finite floats enter ADQL; never interpolate user text.
    if not math.isfinite(ra) or not math.isfinite(dec) or not 0 <= ra < 360 or not -90 <= dec <= 90:
        raise ValueError('Invalid ICRS coordinates')
    filters = ''
    if band is not None:
        if band not in BANDS:
            raise ValueError('Invalid SPHEREx detector')
        filters += f"AND energy_bandpassname = '{band}' "
    if wavelength_um is not None:
        if not math.isfinite(wavelength_um) or not WAVELENGTH_MIN_UM <= wavelength_um <= WAVELENGTH_MAX_UM:
            raise ValueError('Invalid wavelength')
        metres = wavelength_um / 1_000_000
        # Filter before TOP/LIMIT; retain missing or inconsistent coverage as unverified.
        filters += (f'AND (em_min IS NULL OR em_max IS NULL OR em_min <= 0 OR em_max < em_min '
                    f'OR (em_min <= {metres:.17e} AND em_max >= {metres:.17e})) ')
    return (f"SELECT TOP {LIMIT + 1} {', '.join(COLUMNS)} FROM {TABLE} "
            f"WHERE 1=CONTAINS(POINT('ICRS',{ra:.10f},{dec:.10f}),s_region) "
            f'{filters}'
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
    def observations(self, ra, dec, band=None, wavelength_um=None):
        query = build_query(ra, dec, band, wavelength_um)
        verify_schema()
        rows, truncated = parse_observations(tap(query, 'votable'))
        if wavelength_um is not None:
            for row in rows:
                row['wavelength_coverage'] = wavelength_coverage(row, wavelength_um)
            rows = [row for row in rows if row['wavelength_coverage'] != 'range_excludes']
        return {'status': 'live', 'source': TAP_URL, 'table': TABLE,
                'ra': ra, 'dec': dec, 'band': band, 'wavelength_um': wavelength_um,
                'unknown_wavelength_count': sum(row.get('wavelength_coverage') == 'unknown' for row in rows),
                'match': 'point-in-footprint',
                'limit': LIMIT, 'truncated': truncated, 'count': len(rows), 'observations': rows}
