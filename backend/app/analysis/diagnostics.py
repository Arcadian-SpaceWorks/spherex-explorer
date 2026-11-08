"""Bounded diagnostics, not certification of astrophysical change."""
import numpy as np
from scipy.ndimage import maximum_filter, binary_erosion
from scipy.spatial import cKDTree


def local_psf(hdul, image, x, y):
    """IRSA cutout-to-detector mapping; moments are diagnostic, not a PSF match."""
    if 'PSF' not in hdul:
        return {'status':'unavailable', 'reason':'No PSF extension'}
    if hdul['PSF'].data is None or hdul['PSF'].data.ndim!=3:
        return {'status':'unavailable','reason':'Unsupported PSF cube shape'}
    header=hdul['PSF'].header
    if 'CRPIX1A' not in image.header or 'CRPIX2A' not in image.header:
        return {'status':'unavailable', 'reason':'Original-detector mapping unavailable'}
    ox,oy=1+x-image.header['CRPIX1A'],1+y-image.header['CRPIX2A']
    for i,plane in enumerate(hdul['PSF'].data,1):
        if not all(k+str(i) in header for k in ('XCTR_','YCTR_','XWID_','YWID_')):continue
        if abs(ox-header[f'XCTR_{i}'])>header[f'XWID_{i}']/2 or abs(oy-header[f'YCTR_{i}'])>header[f'YWID_{i}']/2:continue
        oversamp=header.get('OVERSAMP')
        if not oversamp or oversamp<=0 or plane.ndim!=2 or not np.isfinite(plane).all() or plane.sum()<=0:
            return {'status':'unavailable','reason':'PSF model cannot support positive intensity moments'}
        weights=plane/plane.sum();yy,xx=np.indices(plane.shape)
        cx,cy=(xx*weights).sum(),(yy*weights).sum()
        moment=float(((((xx-cx)**2+(yy-cy)**2)*weights).sum()/2))
        if moment<=0:return {'status':'unavailable','plane':i-1,'reason':'Signed empirical PSF has nonpositive second moment'}
        rms=float(np.sqrt(moment)/oversamp)
        negative_fraction=float(-plane[plane<0].sum()/np.abs(plane).sum())
        return {'status':'measured','plane':i-1,'original_detector_pixel':[float(ox),float(oy)],
                'rms_width_native_pixels':rms,'oversampling':float(oversamp),'negative_absolute_mass_fraction':negative_fraction,
                'limitation':'Signed empirical model moments may depend on negative wings; not field-wide PSF matching or measured source sharpness'}
    return {'status':'unavailable','reason':'Target outside documented PSF zones'}


def reproject_variance(frame,grid):
    """Diagonal variance for bilinear interpolation: sum(w_i**2 * var_i).

    Assumes independent input pixels. Output correlations exist and are NOT discarded
    by claiming this is a calibrated detection variance; no candidate significance uses it.
    """
    if frame.variance is None:return None
    yy,xx=np.indices(grid.shape)
    x,y=frame.wcs.world_to_pixel(grid.wcs.pixel_to_world(xx,yy))
    safe=np.isfinite(x)&np.isfinite(y)
    ix=np.floor(np.where(safe,x,0)).astype(int);iy=np.floor(np.where(safe,y,0)).astype(int)
    fx=x-ix;fy=y-iy
    out=np.zeros(grid.shape);valid=safe.copy()
    h,w=frame.variance.shape
    for dx,dy,weight in ((0,0,(1-fx)*(1-fy)),(1,0,fx*(1-fy)),(0,1,(1-fx)*fy),(1,1,fx*fy)):
        needed=weight>1e-8
        inside=(ix+dx>=0)&(ix+dx<w)&(iy+dy>=0)&(iy+dy<h)
        values=frame.variance[np.clip(iy+dy,0,h-1),np.clip(ix+dx,0,w-1)]
        native_valid=frame.valid[np.clip(iy+dy,0,h-1),np.clip(ix+dx,0,w-1)]
        valid &= ~needed | (inside & native_valid & np.isfinite(values) & (values>0))
        out+=np.where(needed & inside & np.isfinite(values),weight**2*np.nan_to_num(values),0)
    return np.where(valid & (out>0),out,np.nan)


def feature_registration(a,b):
    """Mutual nearest bright image peaks on aligned grids. Not source identification."""
    mask=binary_erosion(a.valid & b.valid,iterations=4)
    def peaks(data):
        values=data[mask]
        if values.size<100:return np.empty((0,2))
        median=np.median(values);noise=1.4826*np.median(np.abs(values-median))
        good=mask & (data>median+5*max(noise,1e-12))
        good &= np.where(mask,data,-np.inf)==maximum_filter(np.where(mask,data,-np.inf),size=7)
        y,x=np.nonzero(good)
        order=np.argsort(data[y,x])[-100:]
        return np.column_stack([x[order],y[order]])
    pa,pb=peaks(a.data),peaks(b.data)
    if not len(pa) or not len(pb):return {'status':'insufficient_features','matches':0}
    distance,idx=cKDTree(pb).query(pa);_,reverse=cKDTree(pa).query(pb)
    keep=(distance<=2)&(reverse[idx]==np.arange(len(pa)))
    delta=pb[idx[keep]]-pa[keep]
    if not len(delta):return {'status':'insufficient_features','matches':0}
    return {'status':'diagnostic_only','matches':len(delta),
            'median_shift_xy_pixels':np.median(delta,axis=0).tolist(),
            'rms_separation_pixels':float(np.sqrt(np.mean(np.sum(delta**2,axis=1)))),
            'limitation':'Integer-pixel image peaks; matching can be biased by morphology, PSF or wavelength. Stationarity and source identity are unverified.'}
