"""Offline, independent real SPHEREx pair assessment; never changes source FITS."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.analysis.pipeline import compare_files

ROOT=Path(__file__).resolve().parents[1]/'frontend/public'

def run():
    manifest=json.loads((ROOT/'demo/manifest.json').read_text())
    for target in manifest['targets']:
        rows=target['observations']
        for i,a in enumerate(rows):
            for b in rows[i+1:]:
                if a['detector']!=b['detector']:continue
                paths=[ROOT/r['fits_path'].lstrip('/') for r in (a,b)]
                for path,row in zip(paths,(a,b)):
                    assert hashlib.sha256(path.read_bytes()).hexdigest()==row['fits_sha256']
                with tempfile.TemporaryDirectory() as out:
                    result=compare_files(*paths,target['ra'],target['dec'],.1,'time',out,
                                         source_a='verified_local_irsa_cutout',source_b='verified_local_irsa_cutout')
                print(json.dumps({k:result[k] for k in ('context','frames','validation','overlap_fraction','difference','detection')},allow_nan=False))
if __name__=='__main__':run()


def run_cache():
    """Optional bounded examination of up to 3 cached real M101 D2 cutouts."""
    import itertools
    root=ROOT.parents[1]/'.cache/arcadian-fits-v1'
    rows=[]
    for metadata in sorted(root.glob('*/metadata.json')):
        if len(rows)>=3:break
        row=json.loads(metadata.read_text()); path=metadata.parent/'original.fits'
        if not path.is_file() or row.get('detector')!=2:continue
        from urllib.parse import urlsplit,parse_qs
        query=parse_qs(urlsplit(row.get('fits_url','')).query)
        center=[float(v) for v in query.get('center',['nan,nan'])[0].split(',')]
        if len(center)!=2 or abs(center[0]-210.80227)>.00001 or abs(center[1]-54.34895)>.00001:continue
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row.get('sha256'):raise ValueError('Cached original checksum mismatch')
        rows.append((row,path))
    for (a,pa),(b,pb) in itertools.combinations(rows,2):
        with tempfile.TemporaryDirectory() as out:
            result=compare_files(pa,pb,210.80227,54.34895,.1,'time',out,source_a='verified_existing_cache',source_b='verified_existing_cache')
        print(json.dumps({k:result[k] for k in ('context','frames','validation','overlap_fraction','difference','detection')},allow_nan=False))

if __name__=='__main__' and '--include-cache' in sys.argv:run_cache()
