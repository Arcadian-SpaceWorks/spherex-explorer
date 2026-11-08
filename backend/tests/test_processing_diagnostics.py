"""Numerical diagnostics tests; these are not validation of astrophysical detections."""
import numpy as np
import pytest
from astropy.io import fits
from backend.app.analysis.compare import Frame, common_grid, AlignedFrame
from backend.app.analysis.diagnostics import reproject_variance, feature_registration, local_psf


def frame(grid,var):
    return Frame(np.ones(grid.shape),np.ones(grid.shape,bool),grid.wcs,(0,0),'test',1,
                 '2026-01-01T00:00:00',60000,1.,.02,variance=var)


def test_variance_identity_and_half_pixel_squared_weights():
    grid=common_grid(10,40,.05)
    f=frame(grid,np.full(grid.shape,4.))
    assert np.allclose(reproject_variance(f,grid)[2:-2,2:-2],4,atol=1e-6)
    f.wcs=grid.wcs.deepcopy();f.wcs.wcs.crpix += [.5,.5]
    result=reproject_variance(f,grid)
    assert np.allclose(result[2:-2,2:-2],1.,atol=1e-6) # 4 neighbors * .25**2 * 4
    f.valid[:]=False
    assert not np.isfinite(reproject_variance(f,grid)).any()
    f.valid[:]=True
    f.variance[:]=np.nan
    assert not np.isfinite(reproject_variance(f,grid)).any()
    f.variance=None
    assert reproject_variance(f,grid) is None


def test_registration_known_peak_shift_and_empty_images():
    grid=common_grid(10,40,.1);f=frame(grid,None)
    a=np.zeros(grid.shape);b=a.copy()
    for x,y in [(12,12),(25,15),(40,40),(15,40),(42,15)]:a[y,x]=100;b[y,x+1]=100
    r=feature_registration(AlignedFrame(f,a,f.valid),AlignedFrame(f,b,f.valid))
    assert r['matches']==5
    assert r['median_shift_xy_pixels']==[1,0]
    assert r['rms_separation_pixels']==pytest.approx(1)
    assert feature_registration(AlignedFrame(f,a*0,f.valid),AlignedFrame(f,b*0,f.valid))['matches']==0


def test_local_psf_plane_mapping_and_failure():
    image=fits.ImageHDU(np.zeros((20,20)))
    yy,xx=np.indices((21,21));psf=np.exp(-((xx-10)**2+(yy-10)**2)/8)
    cube=fits.ImageHDU(psf[None],name='PSF');cube.header.update({'OVERSAMP':2,'XCTR_1':50,'YCTR_1':60,'XWID_1':20,'YWID_1':20})
    image.header.update({'CRPIX1A':-39,'CRPIX2A':-49})
    h=fits.HDUList([fits.PrimaryHDU(),image,cube])
    result=local_psf(h,image,10,10)
    assert result['plane']==0 and result['original_detector_pixel']==[50,60]
    assert result['rms_width_native_pixels']==pytest.approx(1,abs=.001)
    cube.data[0,0,0]=-1e-9
    signed=local_psf(h,image,10,10)
    assert signed['status']=='measured' and signed['negative_absolute_mass_fraction']>0
    del image.header['CRPIX1A']
    assert local_psf(h,image,10,10)['status']=='unavailable'


def test_pipeline_blocks_subtraction_with_incompatible_physical_units(tmp_path):
    from test_compare import make_file, RA, DEC, SIZE
    from backend.app.analysis.pipeline import compare_files
    a=make_file(tmp_path,'a.fits',obs_id='A')
    b=make_file(tmp_path,'b.fits',obs_id='B',date='2026-07-01T00:00:00')
    with fits.open(b,mode='update') as hdul:hdul['IMAGE'].header['BUNIT']='adu'
    result=compare_files(a,b,RA,DEC,SIZE,'time',tmp_path)
    assert not result['validation']['difference_allowed']
    assert result['difference'] is None and 'difference' not in result['previews']
    assert result['detection']['status']=='unavailable'
    assert 'incompatible_units' in [r['code'] for r in result['validation']['reasons']]
