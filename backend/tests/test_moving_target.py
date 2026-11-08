"""Real local comet data, plus deterministic geometry fixtures. No network."""
import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from backend.app.analysis.moving_target import verified_prediction,predicted_motion,local_excess,local_excess_pair
from backend.app.demo import validate_bundle,DEFAULT_ROOT,asset_path
from backend.app.compare_service import CompareService,CompareCacheSettings
from backend.app.image_service import ImageService


def test_spherical_ra_wrap_and_declination():
    a={'ra':359.999,'dec':60,'observed_at_utc':'2025-01-01T00:00:00Z'}
    b={'ra':.001,'dec':60,'observed_at_utc':'2025-01-01T01:00:00Z'}
    r=predicted_motion(a,b)
    assert r['separation_arcsec']==pytest.approx(3.6,abs=.00001)
    assert r['rate_arcsec_per_hour']==pytest.approx(3.6,abs=.00001)
    assert r['measured_motion'] is None


def test_real_comet_frames_predictions_views_and_cache(tmp_path):
    m=validate_bundle(DEFAULT_ROOT);target=next(t for t in m.targets if t.id=='3i-atlas')
    assert len(target.observations)==18
    assert len({o.observed_at_utc for o in target.observations})==13
    assert len({o.obs_id for o in target.observations})==12
    for o in target.observations:
        p=verified_prediction(o)
        assert p['obs_id']==o.obs_id
    rows=[o for o in target.observations if o.detector==5]
    a,b=rows[0],rows[-1]
    service=CompareService(ImageService(),CompareCacheSettings(cache_dir=tmp_path/'cache'))
    refs=[{'demo_image_id':o.image_id} for o in (a,b)]
    for view in ('fixed_sky','comet_centered'):
        r=service.compare(*refs,target.ra,target.dec,.3,'time',tracking_view=view)
        assert r['context']=='real_observation_comparison'
        assert r['detection']['status']=='unavailable' and not r['detection']['candidates']
        motion=r['moving_target']['trajectory']
        assert motion['separation_arcsec']==pytest.approx(581.799803,abs=.001)
        assert motion['elapsed_hours']==pytest.approx(3.327301389,abs=1e-6)
        assert motion['measured_motion'] is None
        peaks=r['moving_target']['local_peak_motion']
        assert peaks['status']=='unverified_peak_motion'
        assert peaks['source_identity_verified'] is False
        assert peaks['positional_uncertainty_arcsec'] is None
        assert 550 < peaks['peak_separation_arcsec'] < 610
        assert service.compare(*refs,target.ra,target.dec,.3,'time',tracking_view=view)['cache_hit']
        for frame in r['moving_target']['frames']:
            assert frame['image_measurement']['source_identity_verified'] is False
            assert frame['image_measurement']['measured_comet_position'] is None
            assert frame['local_peak_marker']['kind']=='unverified_image_peak'
            assert 0<frame['local_peak_marker']['x']<176 and 0<frame['local_peak_marker']['y']<176
            assert 0<frame['marker']['x']<176 and 0<frame['marker']['y']<176
            if view=='comet_centered':assert frame['marker']['x']==pytest.approx(87.5,abs=1e-6)
        if view=='comet_centered':assert r['difference'] is None


def test_altered_ephemeris_is_rejected():
    target=next(t for t in validate_bundle(DEFAULT_ROOT).targets if t.id=='3i-atlas')
    o=target.observations[0].model_copy(deep=True)
    o.acquisition.predicted_ra+=.01
    with pytest.raises(ValueError,match='differs'):verified_prediction(o)


def test_low_signal_is_not_a_comet_detection(monkeypatch):
    from backend.app.analysis import moving_target
    from backend.app.analysis.compare import Frame,common_grid
    grid=common_grid(10,40,.06)
    rng=np.random.default_rng(2)
    data=rng.normal(0,1,grid.shape)
    frame=Frame(data,np.ones(grid.shape,bool),grid.wcs,((grid.shape[1]-1)/2,(grid.shape[0]-1)/2),'fixture',1,'2025-01-01T00:00:00',60000,1.,.01,diagnostics={'physical_unit':'MJy/sr'})
    monkeypatch.setattr(moving_target,'load_frame',lambda *args,**kwargs:frame)
    r=local_excess('unused',{'ra':10,'dec':40})
    assert r['status']=='insufficient_signal' and r['measured_comet_position'] is None
    frame.valid[:]=False;frame.data[:]=np.nan
    assert local_excess('unused',{'ra':10,'dec':40})['status']=='insufficient_signal'


def test_local_peak_motion_never_confirms_comet_identity():
    def report(ra, time, status='unconfirmed_local_excess'):
        return {'prediction':{'ra':ra,'dec':60,'observed_at_utc':time},
                'image_measurement':{'status':status,'candidate_ra':ra,'candidate_dec':60}}
    a=report(359.999,'2025-01-01T00:00:00Z')
    b=report(.001,'2025-01-01T01:00:00Z')
    r=local_excess_pair(a,b)
    assert r['peak_separation_arcsec']==pytest.approx(3.6,abs=.00001)
    assert r['source_identity_verified'] is False and r['positional_uncertainty_arcsec'] is None
    assert local_excess_pair(a,report(.001,'2025-01-01T00:00:00Z'))['status']=='unavailable'
    assert local_excess_pair(a,report(.001,'2025-01-01T01:00:00Z','insufficient_signal'))['status']=='unavailable'
