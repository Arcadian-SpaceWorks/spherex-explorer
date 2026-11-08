"""Offline integrity audit of every published FITS, PNG and provenance reference."""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astropy.io import fits
from PIL import Image
from backend.app.demo import validate_bundle,asset_path,digest
from backend.app.fits_worker import process_fits


@lru_cache(maxsize=None)
def discovery_table(sha):
    """The saved discovery response with this SHA-256 (current tables first, then snapshots)."""
    directory=Path(__file__).resolve().parents[1]/'demo/discovery'
    for candidate in [*sorted(directory.glob('*.vot')),*sorted((directory/'snapshots').glob('*.vot'))]:
        if digest(candidate)==sha: return candidate
    raise ValueError('Missing discovery snapshot or digest mismatch')


def validate(root):
    root=Path(root)
    manifest=validate_bundle(root)
    report=[]
    for target in manifest.targets:
        for row in target.observations:
            path=asset_path(root,row.fits_path)
            meta=json.loads(asset_path(root,row.metadata_path).read_text())
            with fits.open(path,memmap=False) as hdul:
                hdul.verify('exception')
                for hdu in hdul:
                    if 'CHECKSUM' in hdu.header and hdu.verify_checksum()!=1: raise ValueError('Invalid FITS CHECKSUM')
                    if 'DATASUM' in hdu.header and hdu.verify_datasum()!=1: raise ValueError('Invalid FITS DATASUM')
                h=hdul['IMAGE'].header
                if h.get('TIMESYS',hdul[0].header.get('TIMESYS'))!='UTC': raise ValueError('Unverified UTC')
                if h['DATE-OBS'].removesuffix('Z')!=row.observed_at_utc.removesuffix('Z'): raise ValueError('Timestamp mismatch')
                if hdul['IMAGE'].data.shape != (meta['height'],meta['width']): raise ValueError('Shape mismatch')
                if not {'IMAGE','FLAGS','VARIANCE','WCS-WAVE'} <= {hdu.name for hdu in hdul}: raise ValueError('Missing scientific extensions')
            with Image.open(asset_path(root,row.preview_path)) as png:
                if png.format!='PNG' or png.size!=(meta['preview_width'],meta['preview_height']) or max(png.size)>1024: raise ValueError('Invalid preview')
                png.verify()
            if row.acquisition:
                from scripts.discover_demo import read_table
                from astropy.time import Time
                a=row.acquisition
                table=read_table(discovery_table(a.discovery_sha256))
                matches=[r for r in table if str(r['access_url'])==row.access_url and str(r['obs_id'])==row.obs_id]
                if len(matches)!=1: raise ValueError('Observation not uniquely present in original discovery response')
                record=matches[0]
                if str(record['obs_collection'])!=a.data_release: raise ValueError('Release differs from discovery')
                if abs(Time(row.observed_at_utc.removesuffix('Z'),format='isot',scale='utc').mjd-float(record['t_min']))*86400>0.1: raise ValueError('Discovery/FITS time mismatch')
                if 'comet_ra' in table.colnames:
                    # A tracking cutout is centred on the official prediction; a fixed-sky cutout records it.
                    expected=(a.ra,a.dec) if a.position_mode=='moving-target-centered' else (a.predicted_ra,a.predicted_dec)
                    if expected[0] is None or abs(float(record['comet_ra'])-expected[0])>1e-8 or abs(float(record['comet_dec'])-expected[1])>1e-8: raise ValueError('Comet position differs from official ephemeris table')
                if a.predicted_ra is not None:
                    predicted=process_fits('target',path=str(path),ra=a.predicted_ra,dec=a.predicted_dec,max_pixels=8_000_000)
                    if predicted['status']!='inside': raise ValueError('Predicted source position outside WCS')
            position=row.acquisition or target
            placed=process_fits('target',path=str(path),ra=position.ra,dec=position.dec,max_pixels=8_000_000)
            if placed['status']!='inside': raise ValueError('Frame reference outside WCS')
            report.append(dict(target=target.id,observation=row.obs_id,bytes=path.stat().st_size,sha256=digest(path),wcs=placed['status']))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('bundle',type=Path);args=p.parse_args()
    result=validate(args.bundle);print(json.dumps(result,indent=2));print(f'{len(result)} science FITS / PNG pairs verified offline')
