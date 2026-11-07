"""Bounded metadata-only discovery. Saved responses are reproducible audit inputs.

python scripts/discover_demo.py [--refresh]
No FITS downloads. Each curl is capped at 8 MiB / 60 s, with no retries.
Counts describe archive footprint matches, not validated source detections.
"""
import argparse
import hashlib
import shutil
from collections import Counter
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from astropy.io.votable import parse_single_table
from astropy.time import Time

ROOT = Path(__file__).resolve().parents[1]
TAP = 'https://irsa.ipac.caltech.edu/TAP/sync'
COMET = 'https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/obscore_3I_Atlas.vot'
COLUMNS = 'obs_id,s_ra,s_dec,t_min,t_max,em_min,em_max,energy_bandpassname,obs_collection,access_url,s_region,calib_level,access_estsize'
CANDIDATES = {
 '3i-atlas': dict(name='3I/ATLAS', source=COMET, position='Official per-exposure predicted comet_ra/comet_dec; tracking, not fixed sky'),
 'rw-aur': dict(name='RW Aurigae', ra=76.956067, dec=30.401327, source='https://archive.stsci.edu/prepds/starcat/StarCAT-summary/Table_1.pdf', position='Fixed ICRS region around RW Aur; components unresolved; no astrometric detection claim'),
 'r-dra': dict(name='R Draconis', ra=248.1676075, dec=66.75498417, source='https://aladin.cds.unistra.fr/simbad-thumbnails/thumbnails42.html', position='Fixed catalog ICRS region; source detection and variability unvalidated'),
 'barnard': dict(name="Barnard’s Star", ra=269.446, dec=4.766, source="https://simbad.cds.unistra.fr/simbad/sim-basic?Ident=Barnard%27s+star", position='Mission-era reference position footprint query; near expected proper-motion position; exposure-specific astrometry/detection NOT VERIFIED'),
 'wise0855': dict(name='WISE 0855-0714', ra=133.795125, dec=-7.24513889, source='https://doi.org/10.1088/2041-8205/786/2/L18', position='Catalog-designation position footprint query only; current astrometry and source detectability NOT VERIFIED; not selected'),
}

RATIONALES = {
 '3i-atlas': 'Interstellar-comet observations from the August and December 2025 campaigns. Low signal-to-noise can obscure the comet; no detection or activity change is inferred from these previews.',
 'rw-aur': 'Young variable stellar-system region across separated observing seasons. The components may be unresolved; this sequence is not a calibrated light curve.',
 'r-dra': 'Long-period variable-star region across a year of observing seasons. Different LVF wavelengths and display stretches can mimic variability; no brightness change is established.',
}

def read_table(path):
    root = ET.parse(path).getroot()
    statuses = [n.attrib.get('value') for n in root.iter() if n.tag.endswith('INFO') and n.attrib.get('name') == 'QUERY_STATUS']
    if 'ERROR' in statuses or 'OVERFLOW' in statuses:
        raise ValueError('Unsuccessful or truncated archive table')
    table = parse_single_table(path).to_table(use_names_over_ids=True)
    if len(table) >= 10000:
        raise ValueError('Row cap reached; counts would be incomplete')
    return table


def summary(table):
    times = sorted(set(float(t) for t in table['t_min']))
    band = 'spherex_detector' if 'spherex_detector' in table.colnames else 'energy_bandpassname'
    return dict(records=len(table), observation_ids=len(set(table['obs_id'])), exposure_epochs=len(times),
                visits_gap_over_1_day=1+sum(b-a > 1 for a,b in zip(times,times[1:])) if times else 0,
                earliest_utc=Time(times[0],format='mjd',scale='utc').isot+'Z' if times else None,
                latest_utc=Time(times[-1],format='mjd',scale='utc').isot+'Z' if times else None,
                baseline_days=times[-1]-times[0] if times else 0,
                detectors=dict(Counter(str(x) for x in table[band])),
                releases=dict(Counter(str(x) for x in table['obs_collection'])),
                calib_levels=sorted(set(int(x) for x in table['calib_level'])),
                spectral_range_um=[float(min(table['em_min']))*1e6,float(max(table['em_max']))*1e6] if len(table) else None)


def discover(refresh=False):
    directory=ROOT/'demo/discovery'; directory.mkdir(exist_ok=True)
    results={}
    for key,item in CANDIDATES.items():
        path=directory/f'{key}.vot'
        query=None
        if key != '3i-atlas':
            geometry=f"POINT('ICRS',{item['ra']},{item['dec']})"
            predicate='CONTAINS'
            query=f'SELECT TOP 10000 {COLUMNS} FROM spherex.obscore WHERE 1={predicate}({geometry},s_region) ORDER BY t_min'
        result=dict(**item,query=query,table_url=COMET if key=='3i-atlas' else TAP)
        try:
            if refresh or not path.exists():
                temporary=path.with_suffix('.partial')
                cmd=['curl','--fail','--silent','--show-error','--max-time','60','--max-filesize','8388608','--output',str(temporary)]
                if query:
                    cmd += ['--get',TAP,'--data-urlencode','QUERY='+query,'--data','REQUEST=doQuery&LANG=ADQL&FORMAT=votable&MAXREC=10000']
                else: cmd += [COMET]
                try:
                    subprocess.run(cmd,check=True,timeout=65)
                    read_table(temporary)
                    if path.exists():
                        snapshots=directory/'snapshots';snapshots.mkdir(exist_ok=True)
                        archived=snapshots/(hashlib.sha256(path.read_bytes()).hexdigest()+'.vot')
                        if not archived.exists(): shutil.copyfile(path,archived)
                    temporary.replace(path)
                finally: temporary.unlink(missing_ok=True)
            table=read_table(path)
            result.update(status='metadata_verified',sha256=hashlib.sha256(path.read_bytes()).hexdigest(),**summary(table))
            result['by_release']={str(release):summary(table[table['obs_collection']==release]) for release in sorted(set(table['obs_collection']))}
        except Exception as exc:
            result.update(status='not_verified',error=str(exc))
        results[key]=result
        print(key,result['status'],result.get('records'),flush=True)
    (directory/'audit.json').write_text(json.dumps(dict(audited_at_utc=datetime.now(timezone.utc).isoformat(),epoch_definition='Unique exposure start t_min; visits are separated by >1 day, not inferred variability epochs',targets=results),indent=2)+'\n')
    return results

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--refresh',action='store_true');discover(p.parse_args().refresh)
