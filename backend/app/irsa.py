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
# Accepted wavelength filter range in micrometres; SPHEREx spans about 0.75 to 5.0 µm.
WAVELENGTH_MIN_UM, WAVELENGTH_MAX_UM = 0.7, 5.1
# Accepted limit on how far an image centre may be from the target, in degrees. A SPHEREx
# detector image is about 3.5° wide, so footprint matches have centres up to ~2.5° away.
OFFSET_MIN_DEG, OFFSET_MAX_DEG = 0.05, 3.0


def angular_distance_deg(ra1, dec1, ra2, dec2):
    """Great-circle distance between two ICRS positions, in degrees (haversine, stable for small angles)."""
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1, dec1, ra2, dec2))
    h = math.sin((dec2 - dec1) / 2) ** 2 + math.cos(dec1) * math.cos(dec2) * math.sin((ra2 - ra1) / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h))))


def centre_box_filter(ra, dec, radius):
    """ADQL bounding box on s_ra/s_dec that contains every centre within `radius` degrees.

    IRSA rejects a second CONTAINS(...) geometry test in the same query, so the archive
    query uses this box and the exact circular distance is applied afterwards.
    """
    low, high = dec - radius, dec + radius
    clause = f"AND s_dec BETWEEN {max(-90.0, low):.10f} AND {min(90.0, high):.10f} "
    widest = max(abs(low), abs(high))
    if widest >= 89.9:
        return clause  # the circle reaches a pole: every RA is possible
    half_width = math.degrees(math.asin(min(1.0, math.sin(math.radians(radius)) / math.cos(math.radians(widest)))))
    if half_width >= 180:
        return clause
    ra_low, ra_high = ra - half_width, ra + half_width
    if ra_low < 0:  # wraps through RA 0°
        return clause + f"AND (s_ra >= {ra_low + 360:.10f} OR s_ra <= {ra_high:.10f}) "
    if ra_high >= 360:
        return clause + f"AND (s_ra >= {ra_low:.10f} OR s_ra <= {ra_high - 360:.10f}) "
    return clause + f"AND s_ra BETWEEN {ra_low:.10f} AND {ra_high:.10f} "


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


def build_query(ra, dec, band=None, wavelength_um=None, max_offset_deg=None):
    # Only validated finite floats and whitelisted band names enter ADQL; never interpolate user text.
    if not math.isfinite(ra) or not math.isfinite(dec) or not 0 <= ra < 360 or not -90 <= dec <= 90:
        raise ValueError('Invalid ICRS coordinates')
    band_filter = ''
    if band is not None:
        if band not in BANDS:
            raise ValueError('Invalid SPHEREx band')
        band_filter = f"AND energy_bandpassname = '{band}' "
    if wavelength_um is not None:
        if not math.isfinite(wavelength_um) or not WAVELENGTH_MIN_UM <= wavelength_um <= WAVELENGTH_MAX_UM:
            raise ValueError('Invalid wavelength')
        # em_min/em_max are in metres: keep only images whose spectral range covers the wavelength.
        metres = wavelength_um * 1e-6
        band_filter += f"AND em_min <= {metres:.6e} AND em_max >= {metres:.6e} "
    if max_offset_deg is not None:
        if not math.isfinite(max_offset_deg) or not OFFSET_MIN_DEG <= max_offset_deg <= OFFSET_MAX_DEG:
            raise ValueError('Invalid centre offset')
        band_filter += centre_box_filter(ra, dec, max_offset_deg)
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
    def observations(self, ra, dec, band=None, wavelength_um=None, max_offset_deg=None):
        verify_schema()
        rows, truncated = parse_observations(tap(build_query(ra, dec, band, wavelength_um, max_offset_deg), 'votable'))
        for row in rows:
            row['center_offset_deg'] = (angular_distance_deg(ra, dec, row['s_ra'], row['s_dec'])
                                        if row['s_ra'] is not None and row['s_dec'] is not None else None)
        if max_offset_deg is not None:
            # The archive query used a bounding box; drop its corners so the limit is a true circle.
            rows = [row for row in rows if row['center_offset_deg'] is not None
                    and row['center_offset_deg'] <= max_offset_deg]
        return {'status': 'live', 'source': TAP_URL, 'table': TABLE,
                'ra': ra, 'dec': dec, 'band': band, 'wavelength_um': wavelength_um,
                'max_offset_deg': max_offset_deg,
                'match': 'point-in-footprint' if max_offset_deg is None else 'point-in-footprint, centre within max_offset_deg',
                'limit': LIMIT, 'truncated': truncated, 'count': len(rows), 'observations': rows}
