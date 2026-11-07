from functools import lru_cache
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from starlette.background import BackgroundTask

from .image_service import ImageService

router = APIRouter(prefix='/api/images', tags=['FITS images'])
ImageId = Annotated[str, Path(pattern=r'^[a-f0-9]{64}$')]


class ImageRequest(BaseModel):
    access_url: str = Field(min_length=1, max_length=4096)
    ra: float | None = Field(default=None, ge=0, lt=360, allow_inf_nan=False)
    dec: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)

    @model_validator(mode='after')
    def coordinate_pair(self):
        if (self.ra is None) != (self.dec is None):
            raise ValueError('Provide both target RA and Dec, or neither.')
        return self


@lru_cache(maxsize=1)
def get_image_service():
    return ImageService()


@router.post('')
def prepare_image(request: ImageRequest, service=Depends(get_image_service)):
    return service.prepare(request.access_url, request.ra, request.dec)


def asset_response(image_id, kind, service):
    handle = service.open_asset(image_id, kind)
    size = os.fstat(handle.fileno()).st_size
    def chunks():
        try:
            while chunk := handle.read(64 * 1024):
                yield chunk
        finally:
            handle.close()
    headers = {'Content-Length': str(size), 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
    if kind == 'original':
        headers['Content-Disposition'] = f'attachment; filename="spherex-{image_id[:12]}.fits"'
    return StreamingResponse(chunks(), media_type='application/fits' if kind == 'original' else 'image/png',
                             headers=headers, background=BackgroundTask(handle.close))


@router.get('/{image_id}/preview')
def preview(image_id: ImageId, service=Depends(get_image_service)):
    return asset_response(image_id, 'preview', service)


@router.get('/{image_id}/original')
def original(image_id: ImageId, service=Depends(get_image_service)):
    return asset_response(image_id, 'original', service)


@router.get('/{image_id}/pixel')
def pixel(image_id: ImageId, x: int = Query(..., ge=0), y: int = Query(..., ge=0),
          service=Depends(get_image_service)):
    return service.pixel(image_id, x, y)
