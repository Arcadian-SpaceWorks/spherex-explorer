"""HTTP API for spectra. Live spectra are background jobs that the client polls, so the plot can
fill in while exposures are measured; preloaded-bundle spectra are computed locally, offline."""
import csv
import io
import threading
from functools import lru_cache
from typing import Literal

from astropy.io import fits
from astropy.time import Time
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import demo
from ..irsa import IRSAUnavailable
from . import analysis, archive, moving
from .photometry import measure_hdul
from .service import DEFAULT_EXPOSURES, MAX_EXPOSURES, METHOD, POINT_KEYS, SpectrumService

router = APIRouter(prefix='/api/spectrum', tags=['Spectra'])
_service = SpectrumService()
_demo_lock = threading.Lock()


def get_spectrum_service():
    return _service


class SpectrumRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    ra: float | None = Field(default=None, ge=0, lt=360)
    dec: float | None = Field(default=None, ge=-90, le=90)
    target: Literal['3i-atlas'] | None = None
    limit: int = Field(default=DEFAULT_EXPOSURES, ge=20, le=MAX_EXPOSURES)

    @model_validator(mode='after')
    def one_target(self):
        if (self.target is None) == (self.ra is None or self.dec is None) or (self.ra is None) != (self.dec is None):
            raise ValueError('Give either ra and dec, or a named moving target')
        return self


def unavailable(status, code, message):
    return JSONResponse(status_code=status, content={'status': 'unavailable', 'code': code, 'message': message})


@router.get('/features')
def features():
    """The bands that are measured, with their wavelength windows, and the photometry method."""
    return {'features': analysis.feature_catalogue(), 'method': METHOD,
            'thresholds': {'sigma': analysis.MIN_SIGMA, 'strength': analysis.MIN_STRENGTH,
                           'variability': analysis.VARIABILITY_FLOOR, 'season_gap_days': analysis.EPOCH_GAP_DAYS},
            'moving_targets': [{'id': key, 'name': name, 'position_source': moving.SOURCE} for key, name in moving.TARGETS.items()]}


@router.post('', status_code=202)
def start(request: SpectrumRequest, service: SpectrumService = Depends(get_spectrum_service)):
    try:
        if request.target:
            job_id = service.start_moving(request.target, moving.TARGETS[request.target], moving.comet_exposures,
                                          moving.SOURCE, request.limit)
        else:
            job_id = service.start(request.ra, request.dec, request.limit)
    except RuntimeError:
        return unavailable(503, 'busy', 'Several spectra are already being measured. Please retry in a minute.')
    return {'id': job_id}


@router.get('/reference')
def reference(ra: float = Query(..., ge=0, lt=360, allow_inf_nan=False),
              dec: float = Query(..., ge=-90, le=90, allow_inf_nan=False)):
    """2MASS and AllWISE catalogue photometry at the position: an independent check of the spectrum."""
    try:
        return {'status': 'live', 'ra': ra, 'dec': dec, 'match_radius_arcsec': 4.0, 'photometry': _reference(round(ra, 5), round(dec, 5)),
                'note': 'Catalogue epochs are 1997-2001 (2MASS) and 2010 (WISE); variable or moving sources will differ.'}
    except IRSAUnavailable as exc:
        return unavailable(503, 'catalogue_unavailable', str(exc))


@lru_cache(maxsize=128)
def _reference(ra, dec):
    return archive.catalogue_photometry(ra, dec)


@router.get('/demo/{target_id}')
def demo_spectrum(target_id: str):
    """Spectrum of a preloaded target from the local demo bundle. No network access."""
    try:
        with _demo_lock:
            return _demo(target_id)
    except (OSError, ValueError, KeyError) as exc:
        return unavailable(404 if isinstance(exc, KeyError) else 503, 'demo_missing',
                           'This preloaded target has no local science data to measure.')


@lru_cache(maxsize=8)
def _demo(target_id):
    manifest = demo.validate_bundle(demo.DEFAULT_ROOT, check_files=False)
    target = next((item for item in manifest.targets if item.id == target_id), None)
    if target is None or not target.observations:
        raise KeyError(target_id)
    points, tracked = [], False
    for observation in target.observations:
        path = demo.asset_path(demo.DEFAULT_ROOT, observation.fits_path)
        if demo.digest(path) != observation.fits_sha256:
            raise ValueError('Preloaded FITS checksum mismatch')
        acquisition = observation.acquisition
        ra, dec = target.ra, target.dec
        if acquisition and acquisition.predicted_ra is not None:
            ra, dec, tracked = acquisition.predicted_ra, acquisition.predicted_dec, True
        elif acquisition and acquisition.position_mode == 'moving-target-centered':
            ra, dec, tracked = acquisition.ra, acquisition.dec, True
        utc = observation.observed_at_utc.removesuffix('Z')
        point = {'obs_id': observation.obs_id, 'detector': observation.detector, 'utc': utc, 'ra': ra, 'dec': dec,
                 'mjd': float(Time(utc, format='isot', scale='utc').mjd),
                 'collection': acquisition.data_release if acquisition else None}
        try:
            with fits.open(path, memmap=False) as hdul:
                point.update(measure_hdul(hdul, ra, dec))
        except Exception:
            point['status'] = 'unreadable'
        points.append(point)
    return {'id': f'demo-{target_id}', 'state': 'done', 'total': len(points), 'done': len(points), 'available': len(points),
            'truncated': False, 'megabytes_read': 0, 'elapsed_s': 0,
            'message': f'{sum(point["status"] == "ok" for point in points)} of {len(points)} preloaded exposures gave a usable measurement.',
            'request': {'kind': 'demo', 'target': target_id, 'name': target.name, 'ra': target.ra, 'dec': target.dec, 'tracked': tracked},
            'analysis': analysis.summarise(points, tracked), 'points': [{key: point.get(key) for key in POINT_KEYS} for point in points],
            'method': {**METHOD, 'source': 'Preloaded SPHEREx Level 2 cutouts in the local demo bundle (checksums verified).'}}


@router.get('/{job_id}')
def status(job_id: str, service: SpectrumService = Depends(get_spectrum_service)):
    job = service.get(job_id)
    if job is None:
        return unavailable(404, 'unknown_spectrum', 'This spectrum is no longer held by the server. Measure it again.')
    return job


@router.get('/{job_id}/csv')
def download(job_id: str, service: SpectrumService = Depends(get_spectrum_service)):
    job = service.get(job_id)
    if job is None:
        return unavailable(404, 'unknown_spectrum', 'This spectrum is no longer held by the server. Measure it again.')
    return Response(to_csv(job), media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="spherex-spectrum-{job_id[:8]}.csv"'})


def to_csv(job):
    """Every exposure, including the rejected ones with the reason, plus the method as comments."""
    output = io.StringIO()
    output.write('# SPHEREx forced-photometry spectrum. Flux densities in mJy, wavelengths in micrometres.\n')
    output.write(f'# Request: {job["request"]}\n')
    for key in ('source', 'photometry', 'background', 'uncertainty', 'wavelength', 'rejected'):
        output.write(f'# {key}: {job["method"][key]}\n')
    for line in job['method']['limits']:
        output.write(f'# limit: {line}\n')
    writer = csv.DictWriter(output, POINT_KEYS)
    writer.writeheader()
    for point in sorted(job['points'], key=lambda item: (item.get('wavelength_um') is None, item.get('wavelength_um') or 0)):
        writer.writerow({**point, 'flag_names': ' '.join(point.get('flag_names') or [])})
    return output.getvalue()
