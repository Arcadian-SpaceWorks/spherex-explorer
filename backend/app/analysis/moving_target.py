"""Verified ephemeris provenance and conservative local image diagnostics; no discovery claims."""
from functools import lru_cache
from pathlib import Path
import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astropy.io.votable import parse_single_table
from .compare import load_frame

@lru_cache(maxsize=4)
def _ephemeris(path, checksum):
    return parse_single_table(path).to_table(use_names_over_ids=True)


def verified_prediction(observation):
    from ..demo import digest
    acquisition=observation.acquisition
    path=Path(__file__).resolve().parents[3]/'demo/discovery/3i-atlas.vot'
    if acquisition is None or digest(path)!=acquisition.discovery_sha256:
        raise ValueError('Comet discovery-table checksum mismatch')
    table=_ephemeris(str(path),acquisition.discovery_sha256)
    matches=[r for r in table if str(r['obs_id'])==observation.obs_id and str(r['spherex_detector']).removeprefix('D')==str(observation.detector)]
    if len(matches)!=1:raise ValueError('Comet exposure is not uniquely identified in official table')
    row=matches[0]
    ra=acquisition.predicted_ra if acquisition.predicted_ra is not None else acquisition.ra
    dec=acquisition.predicted_dec if acquisition.predicted_dec is not None else acquisition.dec
    if not np.isfinite([ra,dec]).all() or abs(ra-float(row['comet_ra']))>1e-8 or abs(dec-float(row['comet_dec']))>1e-8:
        raise ValueError('Comet prediction differs from official table')
    if abs((Time(observation.observed_at_utc.removesuffix('Z'))-Time(float(row['t_min']),format='mjd')).sec)>.01:
        raise ValueError('Comet exposure time differs from official table')
    return {'ra':ra,'dec':dec,'source':acquisition.position_source,'discovery_sha256':acquisition.discovery_sha256,
            'obs_id':observation.obs_id,'observed_at_utc':observation.observed_at_utc,'detector':observation.detector}


def predicted_motion(a,b):
    elapsed=float((Time(b['observed_at_utc'].removesuffix('Z'))-Time(a['observed_at_utc'].removesuffix('Z'))).sec/3600)
    separation=float(SkyCoord(a['ra']*u.deg,a['dec']*u.deg).separation(SkyCoord(b['ra']*u.deg,b['dec']*u.deg)).arcsec)
    return {'kind':'predicted_only','separation_arcsec':separation,'elapsed_hours':elapsed,
            'rate_arcsec_per_hour':separation/abs(elapsed) if elapsed else None,'measured_motion':None}


def local_excess(path,prediction):
    """Measure a local excess near a prediction. No verified source identity or motion."""
    frame=load_frame(path,prediction['ra'],prediction['dec'],.06)
    if u.Unit(frame.diagnostics['physical_unit']) != u.MJy/u.sr:
        raise ValueError('Unsupported units for comet image measurements')
    yy,xx=np.indices(frame.data.shape);x,y=frame.target_pixel
    radius=np.hypot(xx-x,yy-y);annulus=frame.valid & (radius>=8)&(radius<=12)
    search=frame.valid & (radius<=4)
    result={'status':'insufficient_signal','source_identity_verified':False,'measured_comet_position':None,
            'limitations':['A local excess can be a background source, noise or coma structure. No comet identity is established.',
                           'Empirical image contrast is not calibrated detection significance. No aperture/PSF correction or physical variability is inferred.']}
    if annulus.sum()<100 or search.sum()<40:return result
    bg=float(np.median(frame.data[annulus]));noise=float(1.4826*np.median(np.abs(frame.data[annulus]-bg)))
    if noise<=0:return result
    peak=np.argmax(np.where(search,frame.data,-np.inf));py,px=np.unravel_index(peak,frame.data.shape)
    amplitude=float(frame.data[py,px]-bg);aperture=frame.valid & (np.hypot(xx-px,yy-py)<=3)
    weights=np.where(aperture,np.maximum(frame.data-bg,0),0);weights=np.nan_to_num(weights)
    result.update(background=bg,empirical_noise=noise,peak_contrast=amplitude/noise,units=frame.diagnostics['physical_unit'])
    if amplitude/noise<5 or aperture.sum()<25 or weights.sum()<=0:return result
    cx=float((xx*weights).sum()/weights.sum());cy=float((yy*weights).sum()/weights.sum())
    sky=frame.wcs.pixel_to_world(cx,cy)
    result.update(status='ambiguous_local_excess' if np.hypot(cx-x,cy-y)>2 else 'unconfirmed_local_excess',candidate_ra=float(sky.ra.deg),candidate_dec=float(sky.dec.deg),
                  offset_from_prediction_pixels=float(np.hypot(cx-x,cy-y)),peak_surface_brightness_excess=amplitude,
                  positional_uncertainty_arcsec=None)
    return result


def frame_report(path,prediction,grid):
    x,y=grid.wcs.world_to_pixel(SkyCoord(prediction['ra']*u.deg,prediction['dec']*u.deg))
    # wavelength at the moving position, not the fixed cutout centre
    f=load_frame(path,prediction['ra'],prediction['dec'],.06)
    if f.obs_id!=prediction['obs_id'] or f.observed_at_utc is None or abs((Time(f.observed_at_utc)-Time(prediction['observed_at_utc'].removesuffix('Z'))).sec)>.01:
        raise ValueError('FITS exposure identity/time differs from ephemeris record')
    return {'prediction':prediction,'marker':{'x':float(x),'y':float(y),'kind':'predicted'},
            'target_wavelength_um':f.wavelength_um,'target_bandwidth_um':f.bandwidth_um,
            'image_measurement':local_excess(path,prediction)}
