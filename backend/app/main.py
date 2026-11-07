from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse
from .irsa import IRSAClient, IRSAUnavailable

from .images import router as images_router
from .demo import router as demo_router
from .image_download import ImageError

app = FastAPI(title='Arcadian SkyTracker API', version='0.2.0')
app.include_router(images_router)
app.include_router(demo_router)


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
                 data_client: IRSAClient = Depends(get_client)):
    try:
        return data_client.observations(ra, dec)
    except IRSAUnavailable as exc:
        return JSONResponse(status_code=503, content={
            'status': 'unavailable', 'message': str(exc), 'observations': [],
        })
