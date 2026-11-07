from dataclasses import replace
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import shutil
from unittest.mock import patch

import numpy as np
import pytest
import requests
from astropy.io import fits
from astropy.io.votable import from_table, writeto
from astropy.table import Table
from astropy.wcs import WCS
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import app
from backend.app.images import get_image_service
from backend.app.image_download import ImageError, ImageSettings, IRSAImageDownloader, check_public_dns, validate_url
from backend.app.fits_image import BAD_FLAGS, render_fits, target_info, read_pixel, stretch_pixels
from backend.app.image_service import ImageService

ACCESS = 'https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=fixture'
FITS_URL = 'https://irsa.ipac.caltech.edu/ibe/data/spherex/qr2/level2/fixture.fits'


def make_mef(path, data=None, flags=None, with_wcs=True):
    data = np.arange(48, dtype=np.float32).reshape(6,8) if data is None else data
    primary = fits.PrimaryHDU()  # Deliberately no image pixels.
    primary.header['OBSID'] = 'LOCAL-SYNTHETIC-FIXTURE'
    science = fits.ImageHDU(data=data, name='IMAGE')
    science.header['BUNIT'] = 'MJy/sr'
    science.header['DETECTOR'] = 2
    science.header['DATE-OBS'] = '2026-06-24T03:19:00.048'
    if with_wcs:
        wcs = WCS(naxis=2)
        wcs.wcs.ctype = ['RA---TAN', 'DEC--TAN']
        wcs.wcs.crpix = [3,4]  # Target intentionally off the image center.
        wcs.wcs.crval = [210,54]
        wcs.wcs.cdelt = [-.01,.01]
        science.header.update(wcs.to_header())
    # Nonstandard HDU ordering proves selection by EXTNAME, not index.
    flag_hdu = fits.ImageHDU(data=np.zeros_like(data, dtype=np.int32) if flags is None else flags, name='FLAGS')
    hdul = fits.HDUList([primary, flag_hdu, fits.ImageHDU(data=np.ones_like(data),name='VARIANCE'), science,
                         fits.ImageHDU(data=np.ones_like(data),name='ZODI'),
                         fits.ImageHDU(data=np.zeros((2,3,3),dtype=np.float32), name='PSF')])
    hdul.writeto(path)
    return path


@pytest.fixture
def mef(tmp_path):
    return make_mef(tmp_path/'fixture.fits')


@pytest.fixture
def settings(tmp_path):
    return ImageSettings(cache_dir=tmp_path/'cache', max_bytes=1024*1024, cache_entries=2, cache_ttl=60)


class FakeResponse:
    def __init__(self, content=b'', status=200, headers=None, error=None, chunks=None):
        self.content, self.status_code, self.headers = content, status, headers or {}
        self.error, self.chunks, self.closed = error, chunks, False
    def __enter__(self): return self
    def __exit__(self, *args): self.closed=True
    def raise_for_status(self):
        if self.status_code >= 400: raise requests.HTTPError('fixture HTTP error')
    def iter_content(self, chunk_size):
        if self.error: raise self.error
        yield from self.chunks if self.chunks is not None else [self.content]


def datalink(url=FITS_URL, length=100):
    table = Table({'semantics':['#calibration','#cutout','#this'],
                   'access_url':[FITS_URL+'?calibration','',url],
                   'content_type':['application/fits','image/fits','image/fits'],
                   'content_length':[100,0,length], 'error_message':['','','']})
    output=BytesIO(); writeto(from_table(table),output)
    return output.getvalue()


@pytest.mark.parametrize('url', [
    'http://irsa.ipac.caltech.edu/ibe/data/spherex/a.fits',
    'https://irsa.ipac.caltech.edu.evil.test/ibe/data/spherex/a.fits',
    'https://evil.test/ibe/data/spherex/a.fits', 'https://127.0.0.1/ibe/data/spherex/a.fits',
    'https://[::1]/ibe/data/spherex/a.fits', 'file:///etc/passwd',
    'https://user:secret@irsa.ipac.caltech.edu/ibe/data/spherex/a.fits',
    'https://irsa.ipac.caltech.edu:444/ibe/data/spherex/a.fits',
    'https://irsa.ipac.caltech.edu/TAP/sync',
    'https://irsa.ipac.caltech.edu/ibe/data/spherex/../../proxy',
    'https://irsa.ipac.caltech.edu/ibe/data/spherex/%2e%2e/proxy',
    'https://irsa.ipac.caltech.edu/ibe/data/spherex/%252e%252e/proxy',
    FITS_URL+'#fragment', FITS_URL+'\n', 'https://irsa.ipac.caltech.edu\\@evil.test/a',
])
def test_unsafe_url(url):
    with pytest.raises(ImageError) as error: validate_url(url)
    assert error.value.code == 'unsafe_url'


def test_private_dns_blocked():
    with patch('backend.app.image_download.socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]):
        with pytest.raises(ImageError): check_public_dns(FITS_URL)


def download_mock(settings, destination, responses, url=ACCESS):
    with patch('backend.app.image_download.check_public_dns'), patch('backend.app.image_download.requests.Session') as factory:
        session=factory.return_value.__enter__.return_value
        session.get.side_effect=responses
        result=IRSAImageDownloader(settings).download(url,destination)
        calls=session.get.call_args_list
        assert session.trust_env is False
        assert all(call.kwargs['allow_redirects'] is False and call.kwargs['stream'] is True for call in calls)
        return result,calls


def test_datalink_original_and_streaming(settings, mef, tmp_path):
    destination=tmp_path/'download.fits'
    r1=FakeResponse(datalink(length=mef.stat().st_size)); r2=FakeResponse(mef.read_bytes())
    result,calls=download_mock(settings,destination,[r1,r2])
    assert result == FITS_URL and calls[1].args[0] == FITS_URL
    assert destination.read_bytes() == mef.read_bytes()
    assert r1.closed and r2.closed


def test_redirect_to_localhost_never_connected(settings,tmp_path):
    with patch('backend.app.image_download.check_public_dns'), patch('backend.app.image_download.requests.Session') as factory:
        session=factory.return_value.__enter__.return_value
        session.get.return_value=FakeResponse(status=302,headers={'Location':'https://127.0.0.1/private'})
        with pytest.raises(ImageError, match='Only HTTPS'):
            IRSAImageDownloader(settings).download(FITS_URL,tmp_path/'bad.fits')
        assert session.get.call_count == 1
        assert not (tmp_path/'bad.fits').exists()


def test_untrusted_datalink_destination(settings):
    with pytest.raises(ImageError,match='Only HTTPS'):
        IRSAImageDownloader(settings).resolve_datalink(datalink('https://evil.test/image.fits'))


@pytest.mark.parametrize('response', [
    FakeResponse(headers={'Content-Length':'2000000'}),
    FakeResponse(chunks=[b'x'*700000,b'x'*700000]),
])
def test_oversize_announced_or_streamed(settings,tmp_path,response):
    destination=tmp_path/'large.fits'
    with pytest.raises(ImageError) as error: download_mock(settings,destination,[response],FITS_URL)
    assert error.value.status == 413 and not destination.exists()


@pytest.mark.parametrize('response', [FakeResponse(error=requests.Timeout()), FakeResponse(status=503),
                                     FakeResponse(b'html error'), FakeResponse(b'x',headers={'Content-Length':'100'}),
                                     FakeResponse(b'x',headers={'Content-Encoding':'gzip'})])
def test_failed_downloads_remove_partial(settings,tmp_path,response):
    destination=tmp_path/'partial.fits'
    with pytest.raises(ImageError): download_mock(settings,destination,[response],FITS_URL)
    assert not destination.exists()


def test_datalink_limit(settings):
    with pytest.raises(ImageError) as error: IRSAImageDownloader(settings).resolve_datalink(datalink(length=2_000_000))
    assert error.value.status == 413


def test_render_science_hdu_original_unchanged_and_orientation(mef,tmp_path):
    before=hashlib.sha256(mef.read_bytes()).hexdigest()
    preview=tmp_path/'preview.png'
    metadata=render_fits(mef,preview,1000)
    assert metadata['science_hdu'] == 3
    assert len(metadata['hdus']) == 6 and metadata['hdus'][-1]['shape'] == [2,3,3]
    assert metadata['spatial_wcs'] == 'available' and metadata['spectral_wcs'] == 'unavailable'
    assert 'CRPIX1' in metadata['science_header']
    rgba=np.array(Image.open(preview))
    assert rgba[0,0,0] > rgba[-1,0,0]  # FITS top row displayed above bottom row.
    assert before == hashlib.sha256(mef.read_bytes()).hexdigest()
    target=target_info(mef,210,54,1000)
    assert target['status']=='inside'
    assert target['x']==pytest.approx(2,abs=1e-6) and target['y']==pytest.approx(3,abs=1e-6)
    assert target_info(mef,100,-40,1000)['status'] != 'inside'
    pixel=read_pixel(mef,2,3,1000)
    assert pixel['ra']==pytest.approx(210) and pixel['dec']==pytest.approx(54)
    assert pixel['value']==26 and pixel['spectral'] is None


def test_invalid_and_flagged_pixels(tmp_path):
    data=np.arange(48,dtype=np.float32).reshape(6,8);data[0,0]=np.nan;data[0,1]=np.inf
    flags=np.zeros((6,8),dtype=np.int32);flags[0,2]=64;flags[0,3]=128;flags[0,4]=512
    flags[0,5]=1  # Other flags retained and disclosed, rather than silently dropped.
    path=make_mef(tmp_path/'masked.fits',data,flags)
    metadata=render_fits(path,tmp_path/'masked.png',1000)
    pixels=np.array(Image.open(tmp_path/'masked.png'))
    assert metadata['scaling']['masked_pixels']==5
    assert (pixels[-1,:5,3]==0).all() and pixels[-1,5,3]==255
    assert read_pixel(path,2,0,1000)['masked']


def test_constant_and_no_valid_pixels():
    rgba,info=stretch_pixels(np.ones((4,4)),np.zeros((4,4),dtype=bool))
    assert info['constant'] and (rgba[:,:,0]==128).all()
    with pytest.raises(ImageError) as error:
        stretch_pixels(np.ones((4,4)),np.ones((4,4),dtype=bool))
    assert error.value.code=='no_valid_pixels'


def test_missing_science_no_primary_fallback(tmp_path):
    path=tmp_path/'primary.fits'; fits.PrimaryHDU(np.ones((8,8))).writeto(path)
    with pytest.raises(ImageError, match='science extension'):
        render_fits(path,tmp_path/'bad.png',1000)


def test_pixel_limit_and_missing_wcs(mef,tmp_path):
    with pytest.raises(ImageError) as error: render_fits(mef,tmp_path/'bad.png',10)
    assert error.value.status==413
    path=make_mef(tmp_path/'no-wcs.fits',with_wcs=False)
    metadata=render_fits(path,tmp_path/'no-wcs.png',1000)
    assert metadata['spatial_wcs']=='unavailable'
    assert target_info(path,210,54,1000)['status']=='wcs_unavailable'


class FixtureDownloader:
    def __init__(self,path): self.path,self.calls=path,0
    def download(self,url,destination):
        self.calls+=1; shutil.copyfile(self.path,destination); return FITS_URL


def test_cache_hits_eviction_ttl_and_open_download(settings,mef):
    downloader=FixtureDownloader(mef);service=ImageService(settings,downloader)
    first=service.prepare(ACCESS,210,54)
    assert not first['cache_hit'] and first['target']['status']=='inside'
    assert service.prepare(ACCESS)['cache_hit'] and downloader.calls==1
    handle=service.open_asset(first['image_id'],'original')
    service.prepare(ACCESS+'2');service.prepare(ACCESS+'3')
    assert handle.read()==mef.read_bytes();handle.close()  # Still safe after eviction.
    with pytest.raises(ImageError) as error: service.open_asset(first['image_id'],'original')
    assert error.value.status==404
    newest=service.prepare(ACCESS+'3')
    os.utime(settings.cache_dir/newest['image_id'],(0,0))
    assert not service.prepare(ACCESS+'3')['cache_hit']
    assert len([p for p in settings.cache_dir.iterdir() if not p.name.startswith('.')])<=2


def test_api_image_preview_pixel_original_and_errors(settings,mef):
    downloader=FixtureDownloader(mef);service=ImageService(settings,downloader)
    app.dependency_overrides[get_image_service]=lambda:service
    try:
        client=TestClient(app)
        response=client.post('/api/images',json={'access_url':ACCESS,'ra':210,'dec':54})
        assert response.status_code==200
        metadata=response.json();image_id=metadata['image_id']
        png=client.get(metadata['preview_url']);assert png.headers['content-type']=='image/png' and png.content.startswith(b'\x89PNG')
        original=client.get(metadata['original_url']);assert original.content==mef.read_bytes()
        assert original.headers['content-disposition'].startswith('attachment;')
        assert client.get(f'/api/images/{image_id}/pixel?x=2&y=3').json()['value']==26
        assert client.get(f'/api/images/{image_id}/pixel?x=100&y=3').status_code==422
        assert client.get('/api/images/'+'a'*64+'/original').status_code==404
        assert client.post('/api/images',json={'access_url':'http://127.0.0.1/private'}).status_code==400
        assert client.post('/api/images',json={'access_url':ACCESS,'ra':1}).status_code==422
        service.lock.acquire()
        try: assert client.post('/api/images',json={'access_url':ACCESS}).status_code==503
        finally: service.lock.release()
    finally:
        app.dependency_overrides.pop(get_image_service,None)


def add_spectral_table(path):
    # Tiny synthetic FITS -TAB model: wavelength depends on both detector axes.
    values=np.array([[[1.,.1],[2.,.2]],[[3.,.3],[4.,.4]]])
    columns=[fits.Column(name='X',format='2D',array=[[1.,8.]]),
             fits.Column(name='Y',format='2D',array=[[1.,6.]]),
             fits.Column(name='VALUES',format='8D',dim='(2,2,2)',array=[values])]
    with fits.open(path,mode='update') as hdul:
        header=hdul['IMAGE'].header
        header['WCSAXESW']=2
        header['WCSNAMEW']='Synthetic per-pixel wavelength and bandwidth'
        for axis,ctype,column in [(1,'WAVE-TAB','X'),(2,'BAND-TAB','Y')]:
            for key,value in {f'CTYPE{axis}W':ctype,f'CUNIT{axis}W':'um',f'CRPIX{axis}W':1.,
                              f'CRVAL{axis}W':1.,f'CDELT{axis}W':1.,f'PS{axis}_0W':'WCS-WAVE',
                              f'PS{axis}_1W':'VALUES',f'PS{axis}_2W':column,f'PV{axis}_1W':1,
                              f'PV{axis}_3W':axis}.items():
                header[key]=value
        hdul.append(fits.BinTableHDU.from_columns(columns,name='WCS-WAVE'))


def test_per_pixel_spectral_wcs_and_table_preserved(mef,tmp_path):
    add_spectral_table(mef)
    metadata=render_fits(mef,tmp_path/'spectral.png',1000)
    assert metadata['spectral_wcs']=='available'
    assert metadata['center']['spectral']['wavelength_um']==pytest.approx(2.5)
    a=read_pixel(mef,0,0,1000);b=read_pixel(mef,7,5,1000)
    assert a['spectral']['wavelength_um']==pytest.approx(1)
    assert b['spectral']['wavelength_um']==pytest.approx(4)
    assert b['spectral']['bandwidth_um']==pytest.approx(.4)
    assert b['spectral']['approximate'] is True
    assert 'VALUES' in metadata['wavelength_header']
    assert metadata['hdus'][-1]['columns']==['X','Y','VALUES']


def test_broken_spectral_wcs_is_unavailable_not_a_guessed_wavelength(mef,tmp_path):
    add_spectral_table(mef)
    with fits.open(mef,mode='update') as hdul: hdul['IMAGE'].header['PS1_0W']='MISSING-TABLE'
    metadata=render_fits(mef,tmp_path/'broken-spectral.png',1000)
    assert metadata['spectral_wcs']=='unavailable'
    assert metadata['center']['spectral'] is None


def test_preview_downsampling_keeps_full_science_metadata(tmp_path):
    path=make_mef(tmp_path/'wide.fits',data=np.arange(6*1200,dtype=np.float32).reshape(6,1200))
    metadata=render_fits(path,tmp_path/'wide.png',10000)
    assert metadata['width']==1200 and metadata['preview_width']==1024
    assert Image.open(tmp_path/'wide.png').size==(1024,5)


def test_native_decoder_failure_is_a_friendly_api_error():
    from backend.app.fits_worker import process_fits
    import subprocess
    with patch('backend.app.fits_worker.subprocess.run', return_value=subprocess.CompletedProcess([], -6, '', 'native error')):
        with pytest.raises(ImageError) as error: process_fits('render',path='unused')
    assert error.value.status==422


def test_download_deadline_and_redirect_limit(settings,tmp_path):
    from unittest.mock import MagicMock
    downloader=IRSAImageDownloader(settings)
    with patch('backend.app.image_download.check_public_dns'), patch('backend.app.image_download.time.monotonic',return_value=100):
        with pytest.raises(ImageError) as error:
            downloader._stream(MagicMock(),FITS_URL,BytesIO(),1000,99)
    assert error.value.status==504
    redirects=[FakeResponse(status=302,headers={'Location':FITS_URL}) for _ in range(5)]
    with pytest.raises(ImageError,match='Too many'):
        download_mock(settings,tmp_path/'redirect.fits',redirects,FITS_URL)


def test_cache_file_lock_across_service_instances(settings):
    first=ImageService(settings);second=ImageService(settings)
    with first.transaction():
        with pytest.raises(ImageError) as error:
            with second.transaction(): pass
    assert error.value.code=='viewer_busy'
    with second.transaction(): pass
