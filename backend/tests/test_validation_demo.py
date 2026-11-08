"""Offline reproducible engineering tests using bundled real backgrounds."""
import hashlib
import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from astropy import units as u
from backend.app.analysis import validation_demo as lab

@pytest.mark.parametrize('kind', ['brightness','transient','no_change'])
@pytest.mark.parametrize('seed', range(5))
def test_controlled_experiments(kind,seed):
    r=lab.run_experiment(kind,seed)
    assert r['success']
    assert r['context']=='synthetic_injection_validation'
    path=lab.ROOT/r['background']['fits_path'].lstrip('/')
    assert hashlib.sha256(path.read_bytes()).hexdigest()==r['background']['sha256']
    if kind=='no_change':
        assert r['measurements']['false_candidates']==0
    else:
        assert len(r['detection']['candidates'])==1
        assert r['measurements']['localization_error_pixels']<.6
        c=r['detection']['candidates'][0]; inj=r['injection']
        separation=SkyCoord(c['ra']*u.deg,c['dec']*u.deg).separation(SkyCoord(inj['ra']*u.deg,inj['dec']*u.deg)).arcsec
        assert separation<4 # .6 pixel at nominal 6.15 arcsec per pixel
        assert abs(r['measurements']['amplitude_error'])<5*inj['noise_sigma']
        assert c['uncertainty'] is None


def test_threshold_sensitivity_and_bad_settings():
    assert lab.run_experiment('transient',0,threshold=5)['success']
    r=lab.run_experiment('transient',0,threshold=100)
    assert not r['success'] and not r['detection']['candidates']
    with pytest.raises(ValueError):lab.run_experiment('transient',0,threshold=2)
    for kind,seed in [('unknown',0),('transient',-1)]:
        with pytest.raises(ValueError):lab.run_experiment(kind,seed)


def test_metadata_checksum_and_invalid_mask_failures(monkeypatch):
    original=lab.load_frame
    def damaged(*args,**kwargs):
        f=original(*args,**kwargs);f.valid[:]=False;f.data[:]=np.nan
        return f
    monkeypatch.setattr(lab,'load_frame',damaged)
    with pytest.raises(ValueError,match='safe injection'):lab.run_experiment()
    def wrong_units(*args,**kwargs):
        f=original(*args,**kwargs);f.diagnostics['physical_unit']='Jy'
        return f
    monkeypatch.setattr(lab,'load_frame',wrong_units)
    with pytest.raises(ValueError,match='units'):lab.run_experiment()


def test_api_isolation():
    from fastapi.testclient import TestClient
    from backend.app.main import app
    client=TestClient(app)
    assert client.get('/api/validation?experiment=unknown').status_code==422
    assert client.get('/api/validation?seed=99').status_code==422
    r=client.get('/api/validation?experiment=transient').json()
    assert r['context']=='synthetic_injection_validation'
    from backend.app.analysis.detection import detect_changes
    from test_detection import pair
    assert detect_changes(*pair('transient'))['status']=='unavailable'


def test_injection_avoids_masks_and_edges():
    r=lab.run_experiment('transient')
    f=lab.load_frame(lab.ROOT/r['background']['fits_path'].lstrip('/'),10.6847,41.2687,.17)
    x,y=r['injection']['x'],r['injection']['y']
    assert min(x,y,f.data.shape[1]-1-x,f.data.shape[0]-1-y)>=10
    assert f.valid[y-8:y+9,x-8:x+9].all()
    assert np.isfinite(f.data[y-8:y+9,x-8:x+9]).all()
