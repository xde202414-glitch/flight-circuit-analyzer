"""Helipad/FATO analysis API endpoints.

Provides:
- FATO region + approach/takeoff surface calculation
- Polygon-based building search in analysis regions
- Terrain elevation analysis along surfaces
- Single-point elevation query
"""
import asyncio
import math
from typing import List, Optional

import httpx
from fastapi import APIRouter

from app.config import settings
from app.core.coordinate import transformer
from app.core.helipad_calculator import helipad_calculator
from app.core.building_search import search_buildings as _search_buildings
from app.models.helipad import (
    BuildingResult,
    BuildingSearchRequest,
    BuildingSearchResponse,
    ElevationPointRequest,
    HelipadCalculateRequest,
    HelipadCalculateResponse,
    PolygonRegion,
    TerrainAnalysisRequest,
    TerrainAnalysisResponse,
    TerrainExceedance,
)
from app.models.runway import Coordinate
from app.responses import success

router = APIRouter()

# External elevation API endpoints
OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
OPEN_ELEVATION_BATCH_URL = "https://api.open-elevation.com/api/v1/lookup"
OPENTOPODATA_URL = "https://api.opentopodata.org/v1"
ELEVATION_DATASETS = ["srtm30m", "aster30m", "srtm90m"]
ELEVATION_TIMEOUT = 6.0
BATCH_ELEVATION_TIMEOUT = 15.0
MAX_BATCH_SIZE = 80


# ---------------------------------------------------------------------------
# Surface calculation
# ---------------------------------------------------------------------------

@router.post("/helipad/calculate-surface")
async def calculate_helipad_surface(request: HelipadCalculateRequest):
    """Calculate FATO region and approach/takeoff surface polygons.

    Returns FATO geometry, visual surface parameters, and polygon
    coordinates for rendering on the frontend map.
    """
    try:
        result = helipad_calculator.calculate(request)
        return success(data=result.model_dump(by_alias=True))
    except Exception as exc:
        return success(
            data=None,
            message=f"Helipad surface calculation failed: {exc}",
        )


# ---------------------------------------------------------------------------
# Building search
# ---------------------------------------------------------------------------

@router.post("/helipad/buildings")
async def search_helipad_buildings(request: BuildingSearchRequest):
    """Search buildings/POIs inside polygon-defined analysis regions.

    Uses Amap polygon search (if key configured) with Overpass/OSM
    fallback, matching the MAP HELI260522 behaviour.
    """
    try:
        places, source, warnings = await _search_buildings(
            regions=request.polygons,
            mode=request.mode,
            keywords=request.keywords,
            page_size=request.page_size,
        )
        response = BuildingSearchResponse(
            places=places,
            source=source,
            searchedRegions=[r.name for r in request.polygons],
            warnings=warnings,
        )
        return success(data=response.model_dump(by_alias=True))
    except Exception as exc:
        return success(
            data=BuildingSearchResponse(
                places=[],
                source="error",
                searchedRegions=[r.name for r in request.polygons],
                warnings=[str(exc)],
            ).model_dump(by_alias=True),
            message=f"Building search failed: {exc}",
        )


# ---------------------------------------------------------------------------
# Elevation – single point
# ---------------------------------------------------------------------------

async def _query_open_elevation(client: httpx.AsyncClient, lat: float, lon: float) -> Optional[float]:
    """Query Open-Elevation API for a single point."""
    try:
        resp = await client.get(
            OPEN_ELEVATION_URL,
            params={"locations": f"{lat},{lon}"},
            timeout=ELEVATION_TIMEOUT,
        )
        data = resp.json()
        results = data.get("results", [])
        if results and isinstance(results[0].get("elevation"), (int, float)):
            return float(results[0]["elevation"])
    except Exception:
        pass
    return None


async def _query_opentopodata(
    client: httpx.AsyncClient, lat: float, lon: float, dataset: str
) -> Optional[float]:
    """Query OpenTopoData for a single point."""
    try:
        resp = await client.get(
            f"{OPENTOPODATA_URL}/{dataset}",
            params={"locations": f"{lat},{lon}"},
            timeout=ELEVATION_TIMEOUT,
        )
        data = resp.json()
        if data.get("status") == "OK":
            results = data.get("results", [])
            if results and isinstance(results[0].get("elevation"), (int, float)):
                return float(results[0]["elevation"])
    except Exception:
        pass
    return None


@router.post("/helipad/elevation/point")
async def get_point_elevation(request: ElevationPointRequest):
    """Get ground elevation at a single WGS84 coordinate.

    Tries Open-Elevation first, then OpenTopoData as fallback.
    """
    lat, lon = request.latitude, request.longitude

    async with httpx.AsyncClient() as client:
        elevation = await _query_open_elevation(client, lat, lon)
        source = "open-elevation"

        if elevation is None:
            for dataset in ELEVATION_DATASETS:
                elevation = await _query_opentopodata(client, lat, lon, dataset)
                if elevation is not None:
                    source = f"opentopodata/{dataset}"
                    break

    if elevation is not None:
        return success(data={
            "latitude": lat,
            "longitude": lon,
            "elevation": round(elevation, 2),
            "unit": "m",
            "source": source,
        })
    return success(
        data={"latitude": lat, "longitude": lon, "elevation": None},
        message="External elevation sources unavailable",
    )


# ---------------------------------------------------------------------------
# Elevation – batch query
# ---------------------------------------------------------------------------

async def _query_open_elevation_batch(
    client: httpx.AsyncClient, points: List[dict]
) -> List[Optional[float]]:
    """Batch query Open-Elevation."""
    if not points:
        return []
    try:
        locations = [{"latitude": p["lat"], "longitude": p["lon"]} for p in points]
        resp = await client.post(
            OPEN_ELEVATION_BATCH_URL,
            json={"locations": locations},
            timeout=BATCH_ELEVATION_TIMEOUT,
        )
        data = resp.json()
        results = data.get("results", [])
        return [r.get("elevation") for r in results]
    except Exception:
        return [None] * len(points)


# ---------------------------------------------------------------------------
# Terrain analysis
# ---------------------------------------------------------------------------

@router.post("/helipad/elevation/analyze")
async def analyze_terrain_elevations(request: TerrainAnalysisRequest):
    """Analyse terrain elevation against control heights along surfaces.

    Generates sample points on approach and takeoff surfaces, queries
    ground elevation for each, and returns points where ground exceeds
    the calculated control height.
    """
    # Build sample points
    samples = helipad_calculator.build_terrain_analysis_samples(
        fato_region=request.fato_region,
        surface_params=request.surface_params,
        flight_direction=request.flight_direction,
        fato_elevation=request.fato_elevation,
    )

    if not samples:
        return success(data=TerrainAnalysisResponse(
            sampleCount=0, exceeded=[], failedCount=0, message="No sample points generated"
        ).model_dump(by_alias=True))

    # Batch query elevations
    async with httpx.AsyncClient() as client:
        batch = [{"lat": s["latitude"], "lon": s["longitude"]} for s in samples[:MAX_BATCH_SIZE]]
        elevations = await _query_open_elevation_batch(client, batch)

    # Compare against control elevations
    exceeded: List[TerrainExceedance] = []
    failed = 0
    for idx, sample in enumerate(samples):
        if idx >= len(elevations) or elevations[idx] is None:
            failed += 1
            continue

        ground = elevations[idx]
        if ground > sample["controlElevation"]:
            exceeded.append(TerrainExceedance(
                latitude=sample["latitude"],
                longitude=sample["longitude"],
                surfaceName=sample["surfaceName"],
                groundElevation=round(ground, 2),
                controlElevation=sample["controlElevation"],
                exceedance=round(ground - sample["controlElevation"], 2),
                cellPoints=sample["cellPoints"],
            ))

    message = (
        f"发现 {len(exceeded)} 个地面高于控制高程的取样点" if exceeded
        else "未发现地面高于控制高程的取样点"
    )
    if failed:
        message += f"，{failed} 个点未获取高程"

    return success(data=TerrainAnalysisResponse(
        sampleCount=len(samples),
        exceeded=exceeded,
        failedCount=failed,
        message=message,
    ).model_dump(by_alias=True))
