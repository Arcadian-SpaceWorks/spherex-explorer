from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse
from .irsa import IRSAClient, IRSAUnavailable, WAVELENGTH_MIN_UM, WAVELENGTH_MAX_UM

from .images import get_image_service, router as images_router
from .pairs import build_pair_report
from .demo import router as demo_router
from .compare_api import router as compare_router
from .image_download import ImageError

app = FastAPI(title='Arcadian SkyTracker API', version='0.2.0')
app.include_router(images_router)
app.include_router(demo_router)
app.include_router(compare_router)


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


@app.get('/api/observations')
def observations(ra: float = Query(..., ge=0, lt=360, allow_inf_nan=False),
                 dec: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
                 band: str | None = Query(None, pattern=r'^SPHEREx-D[1-6]$'),
                 wavelength_um: float | None = Query(None, ge=WAVELENGTH_MIN_UM, le=WAVELENGTH_MAX_UM, allow_inf_nan=False),
                 data_client: IRSAClient = Depends(get_client)):
    filters = {key: value for key, value in (('band', band), ('wavelength_um', wavelength_um)) if value is not None}
    try:
        return data_client.observations(ra, dec, **filters)
    except IRSAUnavailable as exc:
        return JSONResponse(status_code=503, content={
            'status': 'unavailable', 'message': str(exc), 'observations': [],
        })


@app.get('/api/pairs')
def pairs(ra: float = Query(..., ge=0, lt=360, allow_inf_nan=False),
          dec: float = Query(..., ge=-90, le=90, allow_inf_nan=False),
          band: str = Query('SPHEREx-D1', pattern=r'^SPHEREx-D[1-6]$'),
          per_visit: int = Query(2, ge=1, le=4),
          size_deg: float = Query(0.3, ge=0.02, le=0.68, allow_inf_nan=False),
          data_client: IRSAClient = Depends(get_client), service=Depends(get_image_service)):
    """Suggest time-comparison pairs for one sky point and band, judged by the same rules as
    POST /api/compare. Slow on first use: one IRSA cutout (about 20-60 s) per shortlisted
    observation, at most 12; repeats are served from the image cache while it holds them."""
    try:
        return build_pair_report(data_client, service, ra, dec, band, per_visit, size_deg)
    except IRSAUnavailable as exc:
        return JSONResponse(status_code=503, content={
            'status': 'unavailable', 'message': str(exc), 'pairs': [], 'candidates': [],
        })
