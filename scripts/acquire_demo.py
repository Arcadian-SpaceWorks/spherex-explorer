"""Acquire selected, bounded QR2 cutouts from saved discovery metadata.

Sequential only; 16 MiB and 90 seconds per complete DataLink/cutout operation;
maximum 6 frames per target. Reuses verified local source records and FITS.
Writes an inventory for prepare_demo.py, never edits the published bundle.
"""
import argparse
import os
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
import numpy as np
from astropy.time import Time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.demo import digest
from backend.app.image_download import ImageSettings, IRSAImageDownloader
from backend.app.fits_worker import process_fits
from scripts.discover_demo import ROOT, CANDIDATES, RATIONALES, read_table


def selected_rows(table, detector, count=6):
    band='spherex_detector' if 'spherex_detector' in table.colnames else 'energy_bandpassname'
    table=table[(table['obs_collection']=='spherex_qr2') & np.array([str(x).endswith(f'D{detector}') for x in table[band]])]
    table.sort('t_min')
    if not len(table): return []
    # Evenly spaced temporal ranks, retaining endpoints; unique archive identities.
    unique={str(row['access_url']):row for row in table}
    rows=sorted(unique.values(),key=lambda r: float(r['t_min']))
    return [rows[i] for i in sorted(set(np.linspace(0,len(rows)-1,min(count,len(rows)),dtype=int))) ]


def frame_position(key,row):
    if key=='3i-atlas': return float(row['comet_ra']),float(row['comet_dec'])
    return CANDIDATES[key]['ra'],CANDIDATES[key]['dec']


def acquire_one(access_url, output, ra, dec):
    settings=ImageSettings(max_bytes=16*1024*1024,download_seconds=80)
    return IRSAImageDownloader(settings).download(access_url,output,cutout=(ra,dec,0.12))


def acquire(keys, count=6):
    inventory=json.loads((ROOT/'demo/targets.json').read_text())
    inventory['targets']=[t for t in inventory['targets'] if t['id'] in ('m101','m31')]
    failures=[]
    for key in keys:
        item=CANDIDATES[key]; table=read_table(ROOT/f'demo/discovery/{key}.vot')
        detector=5 if key=='3i-atlas' else 2
        rows=selected_rows(table,detector,count)
        if not rows: continue
        ra,dec=frame_position(key,rows[0])
        target=dict(id=key,name=item['name'],ra=ra,dec=dec,coordinate_source=item['source'],science_context=RATIONALES[key]+' '+item['position'],inputs=[])
        for row in rows:
            ra,dec=frame_position(key,row)
            access=str(row['access_url'])
            token=hashlib.sha256(f'{access}:{ra:.6f}:{dec:.6f}:0.12'.encode()).hexdigest()
            folder=ROOT/'demo/acquired'/token; folder.mkdir(parents=True,exist_ok=True)
            fits=folder/'original.fits'; record_path=folder/'source.json'
            preserved=ROOT/'demo/source-records'/f'{token}.json'
            if not record_path.exists() and preserved.exists():
                saved=json.loads(preserved.read_text())
                image_id=hashlib.sha256(f'{key}:{saved["sha256"]}'.encode()).hexdigest()
                fits=ROOT/'frontend/public/demo/assets'/image_id/'original.fits'
                record_path=preserved
            try:
                if record_path.exists():
                    record=json.loads(record_path.read_text())
                    if digest(fits)!=record['sha256']: raise ValueError('Previously downloaded cutout checksum changed')
                else:
                    # Child process provides a hard wall-clock cap, including slow reads/DNS.
                    result=subprocess.run([sys.executable,__file__,'--one',access,str(fits),str(ra),str(dec)],capture_output=True,text=True,timeout=90,check=True)
                    url=result.stdout.strip().splitlines()[-1]
                    from astropy.io import fits as afits
                    with afits.open(fits,memmap=False,checksum=True) as hdul:
                        hdul.verify('exception')
                        header=hdul['IMAGE'].header
                        if header.get('TIMESYS',hdul[0].header.get('TIMESYS'))!='UTC': raise ValueError('Unverified FITS time scale')
                        calibration=urlsplit(url).path.split('/')[-3]
                    meta=process_fits('render',path=str(fits),preview_path=str(folder/'check.png'),max_pixels=8_000_000)
                    observed=Time(meta['observed_at_utc'],format='isot',scale='utc')
                    if abs(observed.mjd-float(row['t_min']))*86400>0.1: raise ValueError('Archive/FITS timestamp mismatch')
                    if meta['observation_id']!=str(row['obs_id']) or meta['detector']!=detector: raise ValueError('Archive/FITS identity mismatch')
                    position=process_fits('target',path=str(fits),ra=ra,dec=dec,max_pixels=8_000_000)
                    if position['status']!='inside': raise ValueError('Predicted source outside valid WCS footprint')
                    record=dict(observation_id=meta['observation_id'],observed_at_utc=meta['observed_at_utc'],detector=detector,
                                access_url=access,fits_url=url,sha256=digest(fits),cutout=dict(ra=ra,dec=dec,size_deg=0.12),
                                target_position=dict(ra=ra,dec=dec),mission='SPHEREx',data_release='spherex_qr2',calibration=calibration,
                                position_source=item['source'],position_mode='moving-target-centered' if key=='3i-atlas' else 'fixed-sky-region',
                                position_note=item['position'],archive_t_min=float(row['t_min']),archive_em_min_m=float(row['em_min']),archive_em_max_m=float(row['em_max']),
                                discovery_sha256=digest(ROOT/f'demo/discovery/{key}.vot'))
                    record_path.write_text(json.dumps(record,indent=2)+'\n')
                target['inputs'].append(dict(fits=os.path.relpath(fits,ROOT/'demo'),metadata=os.path.relpath(record_path,ROOT/'demo')))
                print(key,row['obs_id'],fits.stat().st_size,'bytes verified',flush=True)
            except Exception as exc:
                failures.append(dict(target=key,obs_id=str(row['obs_id']),error=str(exc),detail=str(getattr(exc,'stderr',None) or '')[-2000:]))
                print(key,row['obs_id'],'FAILED',str(exc),flush=True)
                if not record_path.exists(): fits.unlink(missing_ok=True)
        inventory['targets'].append(target)
    for key, reason in [('barnard', 'Metadata coverage found; not selected for this bundle. Epoch-specific proper motion, parallax and source-detection review remain required before a motion demonstration.'),
                        ('wise0855', 'Footprint matches found at the catalog designation position only. Current source astrometry and SPHEREx detectability are unverified; no cutouts prepared.')]:
        if key not in keys:
            item=CANDIDATES[key]
            inventory['targets'].append(dict(id=key,name=item['name'],ra=item['ra'],dec=item['dec'],coordinate_source=item['source'],inputs=[],missing_reason=reason,science_context=item['position']))
    (ROOT/'demo/showcase-targets.json').write_text(json.dumps(inventory,indent=2)+'\n')
    (ROOT/'demo/discovery/acquisition-failures.json').write_text(json.dumps(failures,indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets',nargs='+',choices=['3i-atlas','rw-aur','r-dra'],default=['3i-atlas','rw-aur','r-dra'])
    parser.add_argument('--frames',type=int,choices=range(1,7),default=6)
    parser.add_argument('--one',nargs=4,metavar=('URL','OUTPUT','RA','DEC'))
    args=parser.parse_args()
    if args.one: print(acquire_one(args.one[0],args.one[1],float(args.one[2]),float(args.one[3])))
    else: acquire(args.targets,args.frames)
