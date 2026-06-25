from fastapi import APIRouter, HTTPException

from app.config import DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM, TIANDITU_KEY
from app.models.route_schemas import DatasourceTestRequest
from app.services.datasource_service import test_datasource_access

router = APIRouter(prefix="/route-config", tags=["route-config"])


@router.get("/map")
def map_config():
    return {
        "default_center": {"lat": DEFAULT_MAP_CENTER[0], "lon": DEFAULT_MAP_CENTER[1]},
        "default_zoom": DEFAULT_MAP_ZOOM,
        "tianditu_key": TIANDITU_KEY,
    }


@router.post("/test-datasource")
async def test_datasource(payload: DatasourceTestRequest):
    try:
        return test_datasource_access(payload.url, timeout=payload.timeout)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
