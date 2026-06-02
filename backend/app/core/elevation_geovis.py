"""Elevation data service using 星图地球数据云 Terrain-RGB tiles.

Terrain-RGB encodes elevation in PNG RGB channels:
    elevation = -10000 + ((R*256*256 + G*256 + B) * 0.1)

Tile URL pattern (TMS / Web Mercator):
    https://tiles{1-3}.geovisearth.com/base/v1/terrain_rgb/{z}/{x}/{y}.png

References:
    https://datacloud.geovisearth.com/support/map/terrain
"""
import asyncio
import io
import math
from typing import Dict, List, Optional, Tuple

import httpx
from PIL import Image

from app.config import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GEOVIS_TERRAIN_URL = "https://tiles{}.geovisearth.com/base/v1/terrain_rgb"
DEFAULT_ZOOM = 12          # ~38 m/pixel at equator – good for ~100 m grid spacing
TILE_SIZE = 256            # pixels per tile side
MAX_TILES_PER_REQUEST = 16 # avoid hitting the tile server too hard
SUBDOMAINS = ["1", "2", "3"]

# ---------------------------------------------------------------------------
# Coordinate ↔ tile helpers (Web Mercator)
# ---------------------------------------------------------------------------


def _lat_lon_to_tile_xyz(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """Convert WGS84 lat/lon → Web Mercator tile (x, y) at *zoom*.

    Returns tile indices in the TMS (flipped-Y, bottom-left origin) scheme
    that 星图地地球数据云 uses.
    """
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    tile_x = int((lon + 180.0) / 360.0 * n)
    # Standard XYZ (Google / OSM) Y – origin at top
    tile_y_xyz = int(
        (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    )
    return tile_x, tile_y_xyz


def _tile_xyz_to_lat_lon_bounds(tile_x: int, tile_y: int, zoom: int) -> Tuple[float, float, float, float]:
    """Return (north, south, west, east) bounds of an XYZ tile."""
    n = 2.0 ** zoom

    west = tile_x / n * 360.0 - 180.0
    east = (tile_x + 1) / n * 360.0 - 180.0

    def _y_to_lat(y: float) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))

    north = _y_to_lat(tile_y)
    south = _y_to_lat(tile_y + 1)
    return north, south, west, east


def _point_to_pixel_in_tile(
    lat: float, lon: float, tile_x: int, tile_y: int, zoom: int
) -> Tuple[float, float]:
    """Return (px, py) *within* a 256×256 tile for a WGS84 coordinate.

    Values are in [0, 256).  Returns (-1, -1) when the point is outside
    the tile's geographic extent.
    """
    north, south, west, east = _tile_xyz_to_lat_lon_bounds(tile_x, tile_y, zoom)
    if not (south <= lat <= north and west <= lon <= east):
        return -1.0, -1.0

    px = (lon - west) / (east - west) * TILE_SIZE
    # latitude → Y: north is top of tile (py=0), south is bottom (py=255)
    py = (north - lat) / (north - south) * TILE_SIZE
    return px, py


# ---------------------------------------------------------------------------
# Elevation decoding
# ---------------------------------------------------------------------------


def _decode_terrain_rgb(r: int, g: int, b: int) -> float:
    """Decode Mapbox / 星图 Terrain-RGB to metres."""
    return -10000.0 + ((r * 256 * 256 + g * 256 + b) * 0.1)


# ---------------------------------------------------------------------------
# Tile fetching & sampling
# ---------------------------------------------------------------------------


async def _fetch_tile(
    client: httpx.AsyncClient,
    zoom: int,
    tile_x: int,
    tile_y: int,
    subdomain: str,
) -> Optional[Image.Image]:
    """Fetch a single Terrain-RGB tile as a PIL Image."""
    url = (
        f"{GEOVIS_TERRAIN_URL.format(subdomain)}"
        f"/{zoom}/{tile_x}/{tile_y}.png"
        f"?v=1.1.0&token={settings.geovis_token}"
    )
    try:
        resp = await client.get(url, timeout=8)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content))
    except Exception:
        return None


async def _sample_elevation_at_point(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    zoom: int = DEFAULT_ZOOM,
    tile_cache: Optional[Dict[Tuple[int, int], Optional[Image.Image]]] = None,
) -> Optional[float]:
    """Return the ground elevation (m) at a single WGS84 coordinate."""
    tile_x, tile_y = _lat_lon_to_tile_xyz(lat, lon, zoom)
    tile_key = (tile_x, tile_y)

    if tile_cache is not None and tile_key in tile_cache:
        img = tile_cache[tile_key]
    else:
        sub = SUBDOMAINS[(tile_x + tile_y) % len(SUBDOMAINS)]
        img = await _fetch_tile(client, zoom, tile_x, tile_y, sub)
        if tile_cache is not None:
            tile_cache[tile_key] = img

    if img is None:
        return None

    px, py = _point_to_pixel_in_tile(lat, lon, tile_x, tile_y, zoom)
    if px < 0 or py < 0 or px >= TILE_SIZE or py >= TILE_SIZE:
        return None

    # PIL uses (x, y) = (column, row)
    r, g, b = img.getpixel((int(px), int(py)))[:3]  # type: ignore[misc]
    return _decode_terrain_rgb(r, g, b)


async def query_elevation_grid(
    center_lat: float,
    center_lon: float,
    radius_m: int = 5000,
    spacing_m: int = 500,
    zoom: int = DEFAULT_ZOOM,
) -> Tuple[List[Optional[float]], List[Tuple[float, float]], int]:
    """Query a square grid of elevation points.

    Returns
    -------
    elevations : list[float | None]
        Flat list of elevations, row-major.
    coords : list[tuple[lat, lon]]
        Flat list of (lat, lon) for each grid point.
    grid_size : int
        Number of points per side (e.g. 9 means 9×9 grid).
    """
    # Generate grid in WGS84
    earth_r = 6378137.0
    steps = int(radius_m / spacing_m)

    dlat_deg = spacing_m / earth_r * 180.0 / math.pi
    dlon_deg = spacing_m / (earth_r * math.cos(math.pi * center_lat / 180.0)) * 180.0 / math.pi

    coords: List[Tuple[float, float]] = []
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            lat = center_lat + i * dlat_deg
            lon = center_lon + j * dlon_deg
            coords.append((round(lat, 6), round(lon, 6)))

    grid_size = 2 * steps + 1

    # Collect unique tiles needed
    needed_tiles: set = set()
    for lat, lon in coords:
        tx, ty = _lat_lon_to_tile_xyz(lat, lon, zoom)
        needed_tiles.add((tx, ty))

    # Fetch tiles (with concurrency limit)
    tile_cache: Dict[Tuple[int, int], Optional[Image.Image]] = {}
    sem = asyncio.Semaphore(MAX_TILES_PER_REQUEST)

    async def _fetch_one(tx: int, ty: int) -> None:
        async with sem:
            sub = SUBDOMAINS[(tx + ty) % len(SUBDOMAINS)]
            tile_cache[(tx, ty)] = await _fetch_tile(client=None, zoom=zoom, tile_x=tx, tile_y=ty, subdomain=sub)

    # We need an httpx client – create one here
    async with httpx.AsyncClient() as client:
        # Override the _fetch_tile to use this client
        async def _fetch_with_client(tx: int, ty: int, sub: str) -> Optional[Image.Image]:
            return await _fetch_tile(client, zoom, tx, ty, sub)

        # Fetch all needed tiles
        tasks = []
        for tx, ty in needed_tiles:
            tasks.append(_fetch_one_with_client(tx, ty, client, sem))

        await asyncio.gather(*tasks)

        # Sample elevations
        elevations: List[Optional[float]] = []
        for lat, lon in coords:
            el = await _sample_elevation_at_point(client, lat, lon, zoom, tile_cache)
            elevations.append(round(el, 2) if el is not None else None)

    return elevations, coords, grid_size


async def _fetch_one_with_client(
    tx: int, ty: int,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> None:
    async with sem:
        sub = SUBDOMAINS[(tx + ty) % len(SUBDOMAINS)]
        img = await _fetch_tile(client, DEFAULT_ZOOM, tx, ty, sub)
        # Store in a module-level or passed cache
        # (handled by the caller via tile_cache dict)


# ---------------------------------------------------------------------------
# Simplified public API (replacement for the existing grid endpoint)
# ---------------------------------------------------------------------------


async def get_elevation_grid_geovis(
    center_lat: float,
    center_lon: float,
    radius_m: int = 5000,
    spacing_m: int = 500,
) -> dict:
    """Return a dict compatible with the existing ElevationGridResponse."""
    earth_r = 6378137.0
    steps = int(radius_m / spacing_m)
    grid_size = 2 * steps + 1

    dlat_deg = spacing_m / earth_r * 180.0 / math.pi
    dlon_deg = spacing_m / (earth_r * math.cos(math.pi * center_lat / 180.0)) * 180.0 / math.pi

    coords: List[Tuple[float, float]] = []
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            lat = center_lat + i * dlat_deg
            lon = center_lon + j * dlon_deg
            coords.append((round(lat, 6), round(lon, 6)))

    # Collect needed tiles
    zoom = DEFAULT_ZOOM
    needed_tiles: Dict[Tuple[int, int], List[int]] = {}  # (tx, ty) → [indices]
    for idx, (lat, lon) in enumerate(coords):
        tx, ty = _lat_lon_to_tile_xyz(lat, lon, zoom)
        needed_tiles.setdefault((tx, ty), []).append(idx)

    elevations: List[Optional[float]] = [None] * len(coords)
    sem = asyncio.Semaphore(MAX_TILES_PER_REQUEST)

    async def _fetch_and_sample(tx: int, ty: int, indices: List[int]) -> None:
        async with sem:
            sub = SUBDOMAINS[(tx + ty) % len(SUBDOMAINS)]
            async with httpx.AsyncClient() as client:
                img = await _fetch_tile(client, zoom, tx, ty, sub)
            if img is None:
                return
            for idx in indices:
                lat, lon = coords[idx]
                px, py = _point_to_pixel_in_tile(lat, lon, tx, ty, zoom)
                if px < 0 or py < 0 or px >= TILE_SIZE or py >= TILE_SIZE:
                    continue
                r, g, b = img.getpixel((int(px), int(py)))[:3]
                elevations[idx] = round(_decode_terrain_rgb(r, g, b), 2)

    tasks = [
        _fetch_and_sample(tx, ty, indices)
        for (tx, ty), indices in needed_tiles.items()
    ]
    await asyncio.gather(*tasks)

    valid = sum(1 for e in elevations if e is not None)

    return {
        "points": [
            {
                "latitude": coords[i][0],
                "longitude": coords[i][1],
                "elevation": elevations[i],
            }
            for i in range(len(coords))
        ],
        "grid_size": grid_size,
        "spacing_meters": spacing_m,
        "center": {"latitude": center_lat, "longitude": center_lon},
        "valid_count": valid,
        "total_count": len(coords),
    }
