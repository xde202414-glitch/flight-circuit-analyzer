"""Polygon-based building search service.

Ported from MAP HELI260522 cloudfunctions/geoService/index.js and
integrated with existing Amap POI search patterns.

Supports:
- Overpass/OSM building search within polygon regions
- Amap polygon-based POI search (when key is configured)
- Automatic WGS84↔GCJ02 coordinate conversion
"""
import asyncio
import math
import httpx
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.core.coordinate import transformer
from app.models.helipad import BuildingResult, PolygonRegion
from app.models.runway import Coordinate

# Query constants (from MAP HELI260522)
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]
DEFAULT_BUILDING_KEYWORDS = [
    "大厦", "写字楼", "住宅小区", "学校", "医院", "商场",
    "园区", "厂房", "机场", "办公楼",
]
FAST_BUILDING_KEYWORDS = ["大厦", "写字楼", "学校", "医院", "商场"]
DEFAULT_OVERPASS_TIMEOUT = 20.0
FAST_OVERPASS_TIMEOUT = 9.0

AMAP_POLYGON_URL = "https://restapi.amap.com/v3/place/polygon"


def gcj02_to_wgs84(lat: float, lon: float) -> Tuple[float, float]:
    """Convert GCJ-02 → WGS84."""
    try:
        c = transformer.gcj02_to_wgs84(Coordinate(latitude=lat, longitude=lon))
        return c.latitude, c.longitude
    except Exception:
        return lat, lon


def wgs84_to_gcj02(lat: float, lon: float) -> Tuple[float, float]:
    """Convert WGS84 → GCJ-02."""
    try:
        c = transformer.wgs84_to_gcj02(Coordinate(latitude=lat, longitude=lon))
        return c.latitude, c.longitude
    except Exception:
        return lat, lon


def _build_overpass_poly(points: List[Coordinate]) -> str:
    """Build an Overpass poly string from polygon vertices.

    The Overpass API expects WGS84 coordinates formatted as
    "lat1 lon1 lat2 lon2 …".
    """
    return " ".join(
        f"{p.latitude:.7f} {p.longitude:.7f}" for p in points
    )


def _get_osm_name(tags: dict) -> str:
    """Extract best available name from OSM tags."""
    return tags.get("name:zh") or tags.get("name") or tags.get("name:en") or "未命名建筑"


def _parse_osm_building(element: dict, matched_region: str) -> Optional[BuildingResult]:
    """Parse an OSM element into a BuildingResult."""
    tags = element.get("tags", {})

    # Determine coordinate
    lat = lon = None
    if "lat" in element and "lon" in element:
        lat, lon = element["lat"], element["lon"]
    elif element.get("center") and "lat" in element["center"]:
        lat, lon = element["center"]["lat"], element["center"]["lon"]
    else:
        return None

    # Convert from WGS84 (OSM native) to GCJ-02 for display on Chinese maps
    gcj_lat, gcj_lon = wgs84_to_gcj02(lat, lon)

    height_val = tags.get("height") or tags.get("building:height")
    height = float(height_val) if height_val else None
    levels_val = tags.get("building:levels")
    levels = int(float(levels_val)) if levels_val else None

    # Extract boundary if available
    boundary = None
    geom = element.get("geometry")
    if geom and isinstance(geom, list) and len(geom) >= 3:
        boundary = [
            Coordinate(
                latitude=round(wgs84_to_gcj02(float(p["lat"]), float(p["lon"]))[0], 6),
                longitude=round(wgs84_to_gcj02(float(p["lat"]), float(p["lon"]))[1], 6),
            )
            for p in geom
        ]

    category = tags.get("building", "building") if tags.get("building") else "建筑/地点"
    address = " ".join(
        filter(None, [tags.get("addr:street", ""), tags.get("addr:housenumber", "")])
    )

    return BuildingResult(
        id=f"osm-{element['type']}-{element['id']}",
        name=_get_osm_name(tags),
        category=f"OSM building: {category}" if tags.get("building") else category,
        address=address,
        latitude=round(gcj_lat, 6),
        longitude=round(gcj_lon, 6),
        source="overpass",
        height=height,
        levels=levels,
        boundary=boundary,
    )


async def search_overpass_region(
    client: httpx.AsyncClient,
    region: PolygonRegion,
    timeout: float = DEFAULT_OVERPASS_TIMEOUT,
    include_geometry: bool = True,
    endpoint: str = OVERPASS_URLS[0],
) -> List[BuildingResult]:
    """Search for buildings inside a polygon region via Overpass API."""
    if len(region.points) < 3:
        return []

    poly = _build_overpass_poly(region.points)
    timeout_sec = max(5, int(timeout) - 1)
    out_clause = "out tags center geom 80;" if include_geometry else "out tags center 80;"

    query = (
        f"[out:json][timeout:{timeout_sec}];("
        f'way["building"](poly:"{poly}");'
        f'relation["building"](poly:"{poly}");'
        f'node["building"](poly:"{poly}");'
        f");{out_clause}"
    )

    resp = await client.post(
        endpoint,
        content=f"data={httpx.QueryParams(query.encode())}",
        timeout=timeout,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    data = resp.json()

    results: List[BuildingResult] = []
    for element in data.get("elements", []):
        parsed = _parse_osm_building(element, region.name)
        if parsed:
            results.append(parsed)

    return results


async def search_overpass_buildings(
    regions: List[PolygonRegion],
    timeout: float = DEFAULT_OVERPASS_TIMEOUT,
    include_geometry: bool = True,
) -> Tuple[List[BuildingResult], List[str]]:
    """Search Overpass for buildings across multiple regions."""
    seen: Dict[str, BuildingResult] = {}
    errors: List[str] = []

    async with httpx.AsyncClient() as client:
        for endpoint in OVERPASS_URLS:
            endpoint_errors: List[str] = []
            for region in regions:
                try:
                    places = await search_overpass_region(
                        client, region, timeout, include_geometry, endpoint,
                    )
                    for place in places:
                        if place.id not in seen:
                            seen[place.id] = place
                except Exception as exc:
                    endpoint_errors.append(f"{region.name}: {exc}")

            if seen or not endpoint_errors:
                errors.extend(endpoint_errors)
                break
            errors.extend(f"{endpoint}: {e}" for e in endpoint_errors)

    return list(seen.values()), errors


async def search_amap_polygon(
    regions: List[PolygonRegion],
    keywords: List[str],
    page_size: int = 10,
) -> Tuple[List[BuildingResult], List[str]]:
    """Search Amap polygon-based POI search.

    Requires an Amap Web服务 API Key. Returns GCJ-02 coordinates
    that are already compatible with Chinese map display.
    """
    if not settings.amap_key:
        return [], ["Amap key not configured"]

    seen: Dict[str, BuildingResult] = {}
    errors: List[str] = []

    async with httpx.AsyncClient() as client:
        for region in regions:
            if len(region.points) < 3:
                continue

            polygon_str = ";".join(
                f"{p.longitude:.6f},{p.latitude:.6f}" for p in region.points
            )

            for keyword in keywords:
                try:
                    resp = await client.get(
                        AMAP_POLYGON_URL,
                        params={
                            "key": settings.amap_key,
                            "polygon": polygon_str,
                            "keywords": keyword,
                            "offset": page_size,
                            "page": 1,
                            "extensions": "all",
                        },
                        timeout=10,
                    )
                    data = resp.json()
                    if data.get("status") != "1":
                        errors.append(f"Amap {region.name}/{keyword}: {data.get('info', '')}")
                        continue

                    for poi in data.get("pois", []):
                        pid = poi.get("id", "")
                        if pid in seen:
                            continue
                        loc = poi.get("location", "")
                        if "," not in loc:
                            continue
                        lng_s, lat_s = loc.split(",")
                        seen[pid] = BuildingResult(
                            id=f"amap-{pid}",
                            name=poi.get("name", "未命名"),
                            category=poi.get("type", ""),
                            address=poi.get("address", ""),
                            latitude=float(lat_s),
                            longitude=float(lng_s),
                            source="amap",
                        )
                except Exception as exc:
                    errors.append(f"Amap {region.name}/{keyword}: {exc}")

    return list(seen.values()), errors


async def search_buildings(
    regions: List[PolygonRegion],
    mode: str = "fast",
    keywords: Optional[List[str]] = None,
    page_size: int = 10,
) -> Tuple[List[BuildingResult], str, List[str]]:
    """Main building search with fallback chain.

    Priority: Amap (if key) → Overpass → returns empty with warnings.
    """
    is_fast = mode != "full"
    keywords = keywords or (FAST_BUILDING_KEYWORDS if is_fast else DEFAULT_BUILDING_KEYWORDS)
    overpass_timeout = FAST_OVERPASS_TIMEOUT if is_fast else DEFAULT_OVERPASS_TIMEOUT
    warnings: List[str] = []
    searched_regions = [r.name for r in regions]

    # Try Amap first
    amap_places, amap_errors = await search_amap_polygon(regions, keywords, page_size)
    if amap_places:
        if amap_errors:
            warnings.extend(amap_errors[:3])
        return amap_places, "amap", warnings

    if amap_errors:
        warnings.extend(amap_errors[:3])

    # Fallback to Overpass
    # Filter to polygon regions only (not FATO which might be a very small area) in fast mode
    overpass_regions = (
        [r for r in regions if r.name != "FATO"] if is_fast else regions
    )
    if not overpass_regions:
        overpass_regions = regions

    places, ov_errors = await search_overpass_buildings(
        overpass_regions, overpass_timeout, include_geometry=not is_fast,
    )
    if ov_errors:
        warnings.extend(ov_errors[:3])

    source = "overpass" if places else "none"
    return places, source, warnings
