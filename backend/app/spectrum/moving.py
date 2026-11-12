"""Moving targets: a spectrum needs the target's position in each exposure, not one sky position.

Only 3I/ATLAS is supported, because IRSA publishes an official table of the SPHEREx exposures that
contain it together with the predicted comet position for each one. That table is preserved in
this repository (demo/discovery/3i-atlas.vot). No ephemeris is computed here.

The archive path of each listed exposure is kept in demo/discovery/3i-atlas-products.json, written
by `python -m backend.app.spectrum.moving` from the archive's own tables; exposures missing from
that file are looked up live.
"""
import json
import warnings
from functools import lru_cache
from pathlib import Path

from astropy.io.votable import parse_single_table

from . import archive

DISCOVERY = Path(__file__).resolve().parents[3] / 'demo' / 'discovery'
TABLE, PRODUCTS = DISCOVERY / '3i-atlas.vot', DISCOVERY / '3i-atlas-products.json'
SOURCE = 'https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/obscore_3I_Atlas.vot'
TARGETS = {'3i-atlas': '3I/ATLAS (interstellar comet)'}


@lru_cache(maxsize=1)
def comet_rows():
    """Listed exposures: obs_publisher_did -> (ra, dec, t_min, band) at IRSA's predicted positions."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        table = parse_single_table(TABLE).to_table(use_names_over_ids=True)
    rows = {}
    for row in table:
        did = str(row['access_url']).partition('?ID=')[2]
        ra, dec = archive.number(row['comet_ra']), archive.number(row['comet_dec'])
        if archive.DID.match(did) and ra is not None and dec is not None:
            rows[did] = (ra, dec, archive.number(row['t_min']), f"SPHEREx-{str(row['spherex_detector'])}")
    return rows


def comet_exposures(lookup=archive.exposures_by_id):
    rows = comet_rows()
    try:
        products = json.loads(PRODUCTS.read_text())['products']
    except (OSError, ValueError, KeyError):
        products = {}
    found, missing = [], {}
    for did, (ra, dec, start, band) in rows.items():
        item = archive.exposure({'uri': products.get(did, ''), 'obs_publisher_did': did,
                                 'energy_bandpassname': band, 'time_bounds_lower': start}, ra, dec)
        if item:
            found.append(item)
        else:
            missing[did] = (ra, dec)
    if missing:
        found += lookup(missing)
    return sorted(found, key=lambda item: (item['t_min'] is None, item['t_min'], item['uri']))


if __name__ == '__main__':
    listed = archive.exposures_by_id({did: row[:2] for did, row in comet_rows().items()})
    PRODUCTS.write_text(json.dumps({'source': 'IRSA TAP: spherex.plane joined to spherex.artifact, by obs_publisher_did',
                                    'products': {item['obs_publisher_did']: item['uri'] for item in sorted(listed, key=lambda item: item['uri'])}}, indent=1) + '\n')
    print(f'{len(listed)} of {len(comet_rows())} listed exposures have an archive product path')
