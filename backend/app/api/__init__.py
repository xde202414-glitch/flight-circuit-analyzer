"""API routes package initialization."""
from app.api.runway import router as runway_router
from app.api.aircraft import router as aircraft_router
from app.api.track import router as track_router
from app.api.config import router as config_router
from app.api.helipad import router as helipad_router

__all__ = [
    "runway_router",
    "aircraft_router",
    "track_router",
    "config_router",
    "helipad_router",
]
