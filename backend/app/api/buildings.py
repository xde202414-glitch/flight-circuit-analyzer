"""Nearby buildings API — primary: 天地图 (server key), fallback: Amap."""
import math
import json
import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import settings
from app.core.coordinate import CoordinateTransformer
from app.responses import success, error

router = APIRouter()
transformer = CoordinateTransformer()

TIANDITU_SEARCH_URL = "https://api.tianditu.gov.cn/v2/search"
AMAP_POI_URL = "https://restapi.amap.com/v3/place/around"


class BuildingInfo(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    type: str = ""
    address: str = ""


def _bbox_from_center(lat: float, lon: float, radius_m: float) -> str:
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * math.cos(lat * math.pi / 180.0))
    return f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f}"


@router.get("/buildings/amap")
async def get_buildings(
    latitude: float = Query(...),
    longitude: float = Query(...),
    radius: int = Query(default=5000, ge=500, le=10000),
):
    """Get nearby buildings — 天地图优先，高德备用."""
    all_buildings: list[BuildingInfo] = []

    # ---- Phase 1: Try 天地图 (needs server key) ----
    if settings.tianditu_key:
        bbox = _bbox_from_center(latitude, longitude, radius)
        keywords = ["大厦", "写字楼", "住宅", "学校", "医院", "商场", "办公楼", "小区"]
        async with httpx.AsyncClient() as client:
            for kw in keywords:
                for start in range(0, 30, 10):
                    post_str = json.dumps({
                        "keyWord": kw, "queryType": "1",
                        "mapBound": bbox, "level": "13",
                        "start": str(start), "count": "10",
                    })
                    try:
                        resp = await client.get(TIANDITU_SEARCH_URL, params={
                            "postStr": post_str, "type": "query",
                            "tk": settings.tianditu_key,
                        }, timeout=8)
                        data = resp.json()
                        st = data.get("status")
                        # 天地图 status can be str "0" or dict {"infocode": 1000}
                        ok = (st == "0" or (isinstance(st, dict) and st.get("infocode") == 1000))
                        if not ok:
                            break
                        pois = data.get("pois", [])
                        if not pois:
                            break
                        for poi in pois:
                            parts = (poi.get("lonlat") or "").replace(",", " ").split()
                            if len(parts) < 2:
                                continue
                            all_buildings.append(BuildingInfo(
                                id=f"tdt-{len(all_buildings)}",
                                name=str(poi.get("name", "")),
                                latitude=float(parts[1]),
                                longitude=float(parts[0]),
                                type=str(poi.get("type", "")),
                                address=str(poi.get("address", "") or ""),
                            ))
                    except Exception:
                        break
        if all_buildings:
            return success(data={
                "buildings": [b.model_dump() for b in all_buildings],
                "total": len(all_buildings),
                "source": "tianditu",
            })

    # ---- Phase 2: Fallback to Amap ----
    if not settings.amap_key:
        return error(code=400, message="未配置地图 API Key")

    from app.models.runway import Coordinate
    gcj = transformer.wgs84_to_gcj02(Coordinate(latitude=latitude, longitude=longitude))
    building_types = "120300|060100|080000|140000|010000"

    async with httpx.AsyncClient() as client:
        for page in range(1, 6):
            params = {
                "key": settings.amap_key,
                "location": f"{gcj.longitude},{gcj.latitude}",
                "radius": radius,
                "types": building_types,
                "extensions": "all",
                "offset": 25,
                "page": page,
            }
            try:
                resp = await client.get(AMAP_POI_URL, params=params, timeout=10)
                data = resp.json()
                if data.get("status") != "1":
                    break
                pois = data.get("pois", [])
                if not pois:
                    break
                for poi in pois:
                    loc = poi.get("location", "")
                    if "," not in loc:
                        continue
                    lng_str, lat_str = loc.split(",")
                    address_raw = poi.get("address", "")
                    if not isinstance(address_raw, str):
                        address_raw = ""
                    all_buildings.append(BuildingInfo(
                        id=poi.get("id", ""),
                        name=poi.get("name", ""),
                        latitude=float(lat_str),
                        longitude=float(lng_str),
                        type=poi.get("type", ""),
                        address=address_raw,
                    ))
            except Exception:
                break

    return success(data={
        "buildings": [b.model_dump() for b in all_buildings],
        "total": len(all_buildings),
        "source": "amap",
    })
