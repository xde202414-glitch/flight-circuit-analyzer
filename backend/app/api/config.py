"""Map and frontend configuration API endpoints."""
from fastapi import APIRouter

from app.config import settings
from app.responses import success

router = APIRouter()


@router.get("/config/map")
async def get_map_config():
    """Return non-sensitive map defaults used by the frontend."""
    return success(
        data={
            "defaultCenter": {
                "latitude": settings.default_map_latitude,
                "longitude": settings.default_map_longitude,
            },
            "defaultZoom": settings.default_map_zoom,
            "tiandituKey": settings.tianditu_key,
        }
    )
