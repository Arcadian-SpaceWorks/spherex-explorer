"""Read-only real-data audit. No downloads or writes to scientific assets."""
from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.demo import validate_bundle,DEFAULT_ROOT,asset_path
from backend.app.analysis.moving_target import verified_prediction,local_excess,predicted_motion
from backend.app.analysis.compare import load_frame

if __name__=='__main__':
    manifest=validate_bundle(DEFAULT_ROOT)
    target=next(t for t in manifest.targets if t.id=='3i-atlas')
    records=[]
    for row in target.observations:
        path=asset_path(DEFAULT_ROOT,row.fits_path);prediction=verified_prediction(row)
        frame=load_frame(path,prediction['ra'],prediction['dec'],.06,source='verified_local_irsa_cutout')
        records.append({'prediction':prediction,'fits_sha256':row.fits_sha256,'fits_source':row.source_url,
                        'frame':frame.summary(),'measurement':local_excess(path,prediction)})
    print(json.dumps({'context':'real_observation_comparison','frames':records,
        'predicted_first_to_last':predicted_motion(records[0]['prediction'],records[-1]['prediction']),
        'measured_comet_motion':None,'calibrated_brightness_change':None,
        'conclusion':'Predicted trajectory and real image playback; local excesses remain unconfirmed. No independently validated comet motion, physical brightening or coma activity change is established.'},indent=2,allow_nan=False))
