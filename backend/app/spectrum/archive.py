"""Archive lookups for spectra: which exposures cover a position, and catalogue photometry.

Uses the IRSA TAP service only. Product paths come from the archive's own CAOM tables
(spherex.plane joined to spherex.artifact), so no path is constructed or guessed here.
"""
import csv
import io
import math
import re

import requests
from astropy.time import Time

from ..irsa import IRSAUnavailable, TAP_URL
from .remote import URI

MAX_ROWS = 60000
DID = re.compile(r'^ivo://irsa\.ipac/spherex_qr\d+\?[A-Za-z0-9_]+/D[1-6]$')
# Zero-magnitude flux densities in Jy and reference wavelengths in micrometres.
# 2MASS: Cohen, Wheaton & Megeath 2003. WISE: Jarrett et al. 2011 (Vega system, W1 and W2).
BANDS = {'J': (1.235, 1594.0), 'H': (1.662, 1024.0), 'Ks': (2.159, 666.7),
         'W1': (3.3526, 309.540), 'W2': (4.6028, 171.787)}


def tap_csv(query, timeout=(10, 110)):
    try:
        response = requests.post(TAP_URL, data={'REQUEST': 'doQuery', 'LANG': 'ADQL', 'FORMAT': 'csv',
                                                'QUERY': query, 'MAXREC': MAX_ROWS}, timeout=timeout)
        response.raise_for_status()
        text = response.content.decode('utf-8')
    except (requests.RequestException, UnicodeError) as exc:
        raise IRSAUnavailable('IRSA TAP could not be reached or timed out. Please retry.') from exc
    if text.lstrip().startswith('<'):  # Errors arrive as a VOTable document even when CSV was requested.
        raise IRSAUnavailable('IRSA rejected the archive query.')
    return list(csv.DictReader(io.StringIO(text)))


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def exposure(row, ra, dec):
    """One archive row as an exposure to measure at (ra, dec); None if the row is unusable."""
    uri, did = row.get('uri', ''), row.get('obs_publisher_did', '')
    if not URI.match(uri) or not DID.match(did):
        return None
    start = number(row.get('time_bounds_lower'))
    return {'uri': uri, 'ra': ra, 'dec': dec, 'obs_publisher_did': did,
            'obs_id': did.partition('?')[2].partition('/')[0], 'band': row.get('energy_bandpassname'),
            'collection': did.split('/')[3].partition('?')[0], 't_min': start}


SELECT = ('SELECT a.uri, p.obs_publisher_did, p.energy_bandpassname, p.time_bounds_lower '
          'FROM spherex.artifact a JOIN spherex.plane p ON a.planeid = p.planeid ')


def exposures_at(ra, dec):
    """Every public Level 2 exposure whose footprint contains the point, oldest first."""
    if not (math.isfinite(ra) and math.isfinite(dec) and 0 <= ra < 360 and -90 <= dec <= 90):
        raise ValueError('Invalid ICRS coordinates')
    rows = tap_csv(f"{SELECT}WHERE 1=CONTAINS(POINT('ICRS',{ra:.8f},{dec:.8f}),p.poly)")
    found = [item for item in (exposure(row, ra, dec) for row in rows) if item]
    return sorted(found, key=lambda item: (item['t_min'] is None, item['t_min'], item['uri']))


def exposures_by_id(positions):
    """Exposures named by archive identifier, each with its own position (a moving target).

    `positions` maps obs_publisher_did -> (ra, dec). Unknown identifiers are simply not returned.
    """
    wanted = [did for did in positions if DID.match(did)]
    found = []
    for start in range(0, len(wanted), 80):
        listed = ','.join(f"'{did}'" for did in wanted[start:start + 80])
        for row in tap_csv(f'{SELECT}WHERE p.obs_publisher_did IN ({listed})'):
            item = exposure(row, *positions.get(row.get('obs_publisher_did'), (None, None)))
            if item and item['ra'] is not None:
                found.append(item)
    return sorted(found, key=lambda item: (item['t_min'] is None, item['t_min'], item['uri']))


def subsample(exposures, limit):
    """At most `limit` exposures, spread evenly in time within each detector.

    Deep fields have tens of thousands of exposures per point; an even spread keeps every part of
    the spectrum and every season represented.
    """
    if len(exposures) <= limit:
        return list(exposures), False
    by_band = {}
    for item in exposures:
        by_band.setdefault(item['band'], []).append(item)
    share = max(1, limit // len(by_band))
    chosen = []
    for items in by_band.values():
        if len(items) <= share:
            chosen += items
        else:
            step = (len(items) - 1) / (share - 1) if share > 1 else 0
            chosen += [items[round(index * step)] for index in range(share)]
    return sorted(chosen, key=lambda item: (item['t_min'] is None, item['t_min'], item['uri'])), True


def mjd_to_utc(mjd):
    return Time(mjd, format='mjd', scale='utc').isot if mjd is not None else None


def catalogue_photometry(ra, dec, radius_arcsec=4.0):
    """2MASS and AllWISE point-source photometry nearest the position, as flux densities in mJy.

    Independent, decades-old measurements: a reference for the SPHEREx spectrum, not part of it.
    """
    circle = f"CIRCLE('ICRS',{ra:.8f},{dec:.8f},{radius_arcsec / 3600:.8f})"
    result = []
    surveys = (('2MASS', 'fp_psc', (('J', 'j_m', 'j_cmsig'), ('H', 'h_m', 'h_cmsig'), ('Ks', 'k_m', 'k_cmsig'))),
               ('AllWISE', 'allwise_p3as_psd', (('W1', 'w1mpro', 'w1sigmpro'), ('W2', 'w2mpro', 'w2sigmpro'))))
    for survey, table, bands in surveys:
        columns = ','.join(name for band in bands for name in band[1:])
        rows = tap_csv(f"SELECT ra,dec,{columns} FROM {table} WHERE CONTAINS(POINT('ICRS',ra,dec),{circle})=1", (10, 40))
        best, best_sep = None, None
        for row in rows:
            row_ra, row_dec = number(row.get('ra')), number(row.get('dec'))
            if row_ra is None or row_dec is None:
                continue
            sep = math.hypot((row_ra - ra) * math.cos(math.radians(dec)), row_dec - dec) * 3600
            if best_sep is None or sep < best_sep:
                best, best_sep = row, sep
        if best is None:
            continue
        for band, mag_column, err_column in bands:
            mag, err = number(best.get(mag_column)), number(best.get(err_column))
            if mag is None or err is None:  # No uncertainty means an upper limit in these catalogues.
                continue
            wavelength, zero = BANDS[band]
            flux = zero * 1000 * 10 ** (-0.4 * mag)
            result.append({'survey': survey, 'band': band, 'wavelength_um': wavelength, 'magnitude': mag,
                           'flux_mjy': flux, 'flux_err_mjy': flux * err * math.log(10) / 2.5,
                           'separation_arcsec': best_sep})
    return result
