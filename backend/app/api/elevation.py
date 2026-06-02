"""Elevation data API — uses 星图地球数据云 Terrain-RGB as primary source,
with Open-Elevation and Amap as fallbacks.
"""
import math
import asyncio
import httpx
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import settings
from app.core.coordinate import CoordinateTransformer
from app.core.elevation_geovis import get_elevation_grid_geovis
from app.responses import success, error

router = APIRouter()
transformer = CoordinateTransformer()

AMAP_REgeo_URL = "https://restapi.amap.com/v3/geocode/regeo"
OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"


class CoordinateInput(BaseModel):
    latitude: float
    longitude: float


class ElevationGridRequest(BaseModel):
    center: CoordinateInput
    radius_meters: int = Field(default=5000, ge=1000, le=10000)
    spacing_meters: int = Field(default=500, ge=50, le=1000)


class ElevationPoint(BaseModel):
    latitude: float
    longitude: float
    elevation: Optional[float] = None


def generate_grid(center_lat: float, center_lon: float,
                  radius_m: int, spacing_m: int) -> tuple[list[tuple[float, float]], int]:
    """Generate a square grid of WGS84 coordinates."""
    R = 6378137.0
    dlat_deg = spacing_m / R * 180 / math.pi
    dlon_deg = spacing_m / (R * math.cos(math.pi * center_lat / 180)) * 180 / math.pi

    steps = int(radius_m / spacing_m)
    grid = []
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            lat = center_lat + i * dlat_deg
            lon = center_lon + j * dlon_deg
            grid.append((round(lat, 6), round(lon, 6)))
    return grid, 2 * steps + 1


@router.post("/elevation/grid")
async def get_elevation_grid(req: ElevationGridRequest):
    """Get elevation grid around a center point.

    Primary: 星图地球数据云 Terrain-RGB tiles (domestic, fast)
    Fallback: Open-Elevation → Amap Regeo
    """
    # Phase 1: Try 星图地球数据云 (best for China)
    if settings.geovis_token:
        try:
            result = await get_elevation_grid_geovis(
                center_lat=req.center.latitude,
                center_lon=req.center.longitude,
                radius_m=req.radius_meters,
                spacing_m=req.spacing_meters,
            )
            if result["valid_count"] > 0:
                return success(data=result)
        except Exception as exc:
            print(f"[elevation] 星图地球数据云 failed: {exc}")

    # Phase 2: Fallback to Open-Elevation + Amap
    raw_grid, grid_size = generate_grid(
        req.center.latitude, req.center.longitude,
        req.radius_meters, req.spacing_meters
    )

    async with httpx.AsyncClient() as client:
        elevations = await fetch_via_open_elevation(client, raw_grid)

        if settings.amap_key:
            null_indices = [i for i, e in enumerate(elevations) if e is None]
            if null_indices:
                semaphore = asyncio.Semaphore(10)
                null_points = [raw_grid[i] for i in null_indices]
                refined = await fetch_via_amap(client, null_points, semaphore)
                for idx, el in zip(null_indices, refined):
                    if el is not None:
                        elevations[idx] = el

    points = [
        ElevationPoint(latitude=lat, longitude=lon, elevation=el)
        for (lat, lon), el in zip(raw_grid, elevations)
    ]
    valid = sum(1 for p in points if p.elevation is not None)

    return success(data={
        "points": [p.model_dump() for p in points],
        "grid_size": grid_size,
        "spacing_meters": req.spacing_meters,
        "center": req.center.model_dump(),
        "valid_count": valid,
        "total_count": len(points),
    })


async def fetch_via_open_elevation(
    client: httpx.AsyncClient, points: list[tuple[float, float]]
) -> list[Optional[float]]:
    """Fast batch elevation query via Open-Elevation API (SRTM data)."""
    locations = [{"latitude": lat, "longitude": lon} for lat, lon in points]
    try:
        resp = await client.post(
            OPEN_ELEVATION_URL,
            json={"locations": locations},
            timeout=30,
        )
        data = resp.json()
        results = data.get("results", [])
        return [r.get("elevation") for r in results]
    except Exception:
        return [None] * len(points)


async def fetch_via_amap(
    client: httpx.AsyncClient, points: list[tuple[float, float]],
    semaphore: asyncio.Semaphore,
) -> list[Optional[float]]:
    """Point-by-point elevation via Amap Regeo API."""
    if not settings.amap_key:
        return [None] * len(points)

    from app.models.runway import Coordinate

    async def fetch_one(lat: float, lon: float) -> Optional[float]:
        async with semaphore:
            try:
                gcj = transformer.wgs84_to_gcj02(Coordinate(latitude=lat, longitude=lon))
                params = {
                    "key": settings.amap_key,
                    "location": f"{gcj.longitude},{gcj.latitude}",
                    "extensions": "all",
                }
                resp = await client.get(AMAP_REgeo_URL, params=params, timeout=5)
                data = resp.json()
                if data.get("status") == "1":
                    street_number = (data.get("regeocode", {})
                                     .get("addressComponent", {})
                                     .get("streetNumber", {}))
                    elevation_str = street_number.get("elevation")
                    if elevation_str:
                        return float(elevation_str)
            except Exception:
                pass
            return None

    tasks = [fetch_one(lat, lon) for lat, lon in points]
    return await asyncio.gather(*tasks)
