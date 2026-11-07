from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse
from .irsa import (IRSAClient, IRSAUnavailable, OFFSET_MAX_DEG, OFFSET_MIN_DEG,
                   WAVELENGTH_MAX_UM, WAVELENGTH_MIN_UM)

from .images import get_image_service, router as images_router
from .pairs import build_pair_report
from .image_download import ImageError

app = FastAPI(title='Arcadian SkyTracker API', version='0.2.0')
app.include_router(images_router)


@app.exception_handler(ImageError)
async def image_error_handler(request, exc):
    return JSONResponse(status_code=exc.status, content={
        'status': 'unavailable', 'code': exc.code, 'message': str(exc),
    })

client = IRSAClient()


def get_client():
    return client


@app.get('/api/health')
def health():
    return {'status': 'ok'}


BAND_PATTERN = r'^SPHEREx-D[1-6]$'


@app.get('/api/observations')
def observations(ra: float = Query(..., ge=0, lt=360, allow_inf_nan=False),
                 dec: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
                 band: str | None = Query(None, pattern=BAND_PATTERN),
                 wavelength_um: float | None = Query(None, ge=WAVELENGTH_MIN_UM, le=WAVELENGTH_MAX_UM, allow_inf_nan=False),
                 max_offset_deg: float | None = Query(None, ge=OFFSET_MIN_DEG, le=OFFSET_MAX_DEG, allow_inf_nan=False),
                 data_client: IRSAClient = Depends(get_client)):
    # Filtering in the archive query means only matching observations (and later images) are loaded.
    filters = {key: value for key, value in (('band', band), ('wavelength_um', wavelength_um),
                                             ('max_offset_deg', max_offset_deg)) if value is not None}
    try:
        return data_client.observations(ra, dec, **filters)
    except IRSAUnavailable as exc:
        return JSONResponse(status_code=503, content={
            'status': 'unavailable', 'message': str(exc), 'observations': [],
        })


@app.get('/api/pairs')
def pairs(ra: float = Query(..., ge=0, lt=360, allow_inf_nan=False),
          dec: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
          band: str = Query('SPHEREx-D1', pattern=BAND_PATTERN),
          per_visit: int = Query(2, ge=1, le=4),
          cutout_deg: float = Query(0.3, ge=0.05, le=1.0, allow_inf_nan=False),
          data_client: IRSAClient = Depends(get_client), service=Depends(get_image_service)):
    """Suggest time-comparison pairs for one sky point and band. Slow on first use: one IRSA cutout
    (about 20 s) per shortlisted observation; repeats are served from the cache."""
    try:
        return build_pair_report(data_client, service, ra, dec, band, per_visit, cutout_deg)
    except IRSAUnavailable as exc:
        return JSONResponse(status_code=503, content={
            'status': 'unavailable', 'message': str(exc), 'pairs': [], 'candidates': [],
        })
