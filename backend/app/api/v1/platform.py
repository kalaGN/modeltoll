"""Public branding only; no administrator operations."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.api.responses import success
from app.services import branding as branding_service

router = APIRouter(tags=["platform"])


@router.get("/v1/platform/branding")
def branding():
    return success(branding=branding_service.branding())


@router.get("/v1/platform/logo")
def logo():
    image = branding_service.logo()
    if image is None:
        raise HTTPException(status_code=404, detail="未设置 Logo")
    return Response(image, media_type="image/png",
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})
