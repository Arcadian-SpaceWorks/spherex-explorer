"""POST /api/compare and its preview PNGs. Existing endpoints are unchanged."""
from functools import lru_cache
import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.background import BackgroundTask

from .compare_service import CompareService
from .images import get_image_service

router = APIRouter(prefix='/api/compare', tags=['Image comparison'])
CompareId = Annotated[str, Path(pattern=r'^[a-f0-9]{64}$')]


class ImageRef(BaseModel):
    """Exactly one of: an image already in the image cache, or an IRSA SPHEREx product URL."""
    model_config = ConfigDict(extra='forbid')
    demo_image_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    image_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    access_url: str | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode='after')
    def exactly_one(self):
        if sum(v is not None for v in (self.image_id, self.access_url, self.demo_image_id)) != 1:
            raise ValueError('Give exactly one of image_id, demo_image_id or access_url.')
        return self


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    a: ImageRef
    b: ImageRef
    ra: float = Field(ge=0, lt=360, allow_inf_nan=False)
    dec: float = Field(ge=-90, le=90, allow_inf_nan=False)
    # The cutout requested is size_deg * 1.457 (to cover a rotated grid), at most IRSA's 1 deg.
    size_deg: float = Field(default=0.3, ge=0.02, le=0.68, allow_inf_nan=False)
    mode: Literal['time', 'wavelength']
    match_scale: bool = False


@lru_cache(maxsize=1)
def _service(images):
    return CompareService(images)


def get_compare_service(images=Depends(get_image_service)):
    return _service(images)


@router.post('')
def compare(request: CompareRequest, service=Depends(get_compare_service)):
    return service.compare(request.a.model_dump(), request.b.model_dump(), request.ra, request.dec,
                           request.size_deg, request.mode, request.match_scale)


@router.get('/{compare_id}/{role}.png')
def preview(compare_id: CompareId, role: Literal['a', 'b', 'difference'], service=Depends(get_compare_service)):
    handle = service.open_preview(compare_id, role)
    size = os.fstat(handle.fileno()).st_size

    def chunks():
        try:
            while chunk := handle.read(64 * 1024):
                yield chunk
        finally:
            handle.close()
    return StreamingResponse(chunks(), media_type='image/png', background=BackgroundTask(handle.close),
                             headers={'Content-Length': str(size), 'Cache-Control': 'no-store',
                                      'X-Content-Type-Options': 'nosniff'})
