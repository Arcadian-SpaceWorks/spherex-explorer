"""Actual local independent-epoch FITS: verifies rejection, never asserts discoveries."""
import json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.compare_api import get_compare_service
from backend.app.compare_service import CompareService, CompareCacheSettings
from backend.app.image_service import ImageService
from backend.app.image_download import ImageSettings


def test_independent_real_pair_gate_and_cache(tmp_path):
    manifest=json.loads(Path('frontend/public/demo/manifest.json').read_text())
    rows=next(t for t in manifest['targets'] if t['id']=='m31')['observations']
    a=next(o for o in rows if o['obs_id']=='2026W01_1A_0471_1' and o['detector']==1)
    b=next(o for o in rows if o['obs_id']=='2026W28_2A_0117_1' and o['detector']==1)
    service=CompareService(ImageService(ImageSettings(cache_dir=tmp_path/'images')),
                           CompareCacheSettings(cache_dir=tmp_path/'comparison'))
    app.dependency_overrides[get_compare_service]=lambda:service
    try:
        client=TestClient(app)
        body={'a':{'demo_image_id':a['image_id']},'b':{'demo_image_id':b['image_id']},'ra':10.6847,'dec':41.2687,'size_deg':.1,'mode':'time'}
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Network prohibited')):
            response=client.post('/api/compare',json=body)
            assert response.status_code==200,response.text
            r=response.json()
            assert r['context']=='real_observation_comparison'
            assert r['detection']['status']=='unavailable' and not r['detection']['candidates']
            assert r['difference'] is not None and r['overlap_fraction']>.9
            assert r['detection']['time_separation_hours']>4000
            assert all(f['diagnostics']['variance']['median']>0 for f in r['frames'])
            assert all(f['diagnostics']['psf_shape']==[121,101,101] for f in r['frames'])
            assert client.post('/api/compare',json=body).json()['cache_hit']
            assert client.get(r['previews']['difference']).status_code==200
            for field in ('context','evidence'):
                assert client.post('/api/compare',json={**body,field:True}).status_code==422
    finally:app.dependency_overrides.pop(get_compare_service,None)
