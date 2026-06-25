from __future__ import annotations

import json
import math
import ssl
import time
import urllib.error
import urllib.request
from bisect import bisect_left
from typing import Any

from shapely import LineString, Point
from shapely.geometry import shape
from shapely.ops import transform

from app.database_route import db_cursor
from app.services.datasource_service import identify_datasource, terrain_provider_priority
from app.services.coordinate_service import build_local_transformers
from app.services.route_service import generate_route_geometry, get_points, get_route

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"
OPEN_TOPO_DATA_URL = "https://api.opentopodata.org/v1/aster30m"
OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"


def _normalize_numeric_text(raw: Any) -> float | None:
    text = str(raw or "").strip().lower()
    if not text:
        return None
    text = text.replace(",", "")
    if text.endswith("m"):
        text = text[:-1].strip()
    if text.endswith("meter"):
        text = text[:-5].strip()
    if text.endswith("meters"):
        text = text[:-6].strip()
    if text.endswith("ft"):
        number = text[:-2].strip()
        try:
            return round(float(number) * 0.3048, 2)
        except ValueError:
            return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _height_from_tags(tags: dict[str, Any]) -> float | None:
    for key in ("height", "building:height"):
        direct = _normalize_numeric_text(tags.get(key, ""))
        if direct is not None:
            return direct
    for key in ("building:levels", "levels"):
        raw = str(tags.get(key, "")).strip()
        if not raw:
            continue
        try:
            levels = float(raw)
        except ValueError:
            continue
        if levels > 0:
            return round(levels * 3.2, 2)
    return None


def _ground_elevation_from_tags(tags: dict[str, Any]) -> float | None:
    for key in ("ele", "elevation", "altitude"):
        value = _normalize_numeric_text(tags.get(key, ""))
        if value is not None:
            return value
    return None


def _summarize_numeric(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "avg": 0.0}
    return {
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": round(sum(values) / len(values), 2),
    }


def _select_sample_step(route_length_m: float) -> float:
    if route_length_m <= 0:
        return 30.0
    return max(25.0, min(80.0, route_length_m / 100.0))


def _build_sample_points(centerline_local: LineString, to_wgs84) -> list[dict[str, Any]]:
    total_length = float(centerline_local.length)
    step = _select_sample_step(total_length)
    if total_length <= 0:
        lon, lat = to_wgs84(*centerline_local.coords[0])
        return [{"index": 1, "distance_m": 0.0, "longitude": lon, "latitude": lat}]
    count = max(2, int(math.floor(total_length / step)) + 1)
    samples: list[dict[str, Any]] = []
    for index in range(count):
        distance = min(total_length, index * step)
        pt = centerline_local.interpolate(distance)
        lon, lat = to_wgs84(pt.x, pt.y)
        samples.append(
            {
                "index": index + 1,
                "distance_m": round(distance, 2),
                "longitude": round(float(lon), 7),
                "latitude": round(float(lat), 7),
            }
        )
    if samples[-1]["distance_m"] < round(total_length, 2):
        pt = centerline_local.interpolate(total_length)
        lon, lat = to_wgs84(pt.x, pt.y)
        samples.append(
            {
                "index": len(samples) + 1,
                "distance_m": round(total_length, 2),
                "longitude": round(float(lon), 7),
                "latitude": round(float(lat), 7),
            }
        )
    return samples


def _build_cross_section_cloud_samples(
    centerline_local: LineString,
    to_wgs84,
    *,
    cross_half_width_m: float,
    per_side_count: int = 10,
) -> list[dict[str, Any]]:
    total_length = float(centerline_local.length)
    if total_length <= 0:
        return []
    along_step = max(60.0, _select_sample_step(total_length) * 1.25)
    cross_half = max(10.0, float(cross_half_width_m))
    per_side = max(1, int(per_side_count))
    cross_count = per_side * 2 + 1
    samples: list[dict[str, Any]] = []
    sample_index = 1
    count = max(2, int(math.floor(total_length / along_step)) + 1)
    for idx in range(count + 1):
        distance = min(total_length, idx * along_step)
        point = centerline_local.interpolate(distance)
        before = centerline_local.interpolate(max(0.0, distance - 2.0))
        after = centerline_local.interpolate(min(total_length, distance + 2.0))
        dx = float(after.x - before.x)
        dy = float(after.y - before.y)
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-6:
            continue
        nx = -dy / seg_len
        ny = dx / seg_len
        for cross_idx in range(cross_count):
            ratio = cross_idx / (cross_count - 1)
            offset = -cross_half + ratio * cross_half * 2
            sx = float(point.x + nx * offset)
            sy = float(point.y + ny * offset)
            lon, lat = to_wgs84(sx, sy)
            samples.append(
                {
                    "index": sample_index,
                    "distance_m": round(float(distance), 2),
                    "cross_offset_m": round(float(offset), 2),
                    "longitude": round(float(lon), 7),
                    "latitude": round(float(lat), 7),
                }
            )
            sample_index += 1
    return samples


def _expand_geometry(geometry_obj, *, factor: float):
    if factor <= 1.0:
        return geometry_obj
    center = geometry_obj.centroid
    scaled = transform(
        lambda x, y, z=None: (
            center.x + (x - center.x) * factor,
            center.y + (y - center.y) * factor,
        ),
        geometry_obj,
    )
    return scaled


def _fill_missing_cloud_by_row_interpolation(
    terrain_cloud_points: list[dict[str, Any]],
) -> int:
    if not terrain_cloud_points:
        return 0
    filled = 0
    rows: dict[float, list[dict[str, Any]]] = {}
    for point in terrain_cloud_points:
        key = round(float(point.get("distance_m", 0.0)), 2)
        rows.setdefault(key, []).append(point)

    for _, row in rows.items():
        row.sort(key=lambda item: float(item.get("cross_offset_m", 0.0)))
        known = [item for item in row if item.get("elevation_m") is not None]
        if not known:
            continue
        for idx, item in enumerate(row):
            if item.get("elevation_m") is not None:
                continue
            target = float(item.get("cross_offset_m", 0.0))
            left = None
            right = None
            for left_idx in range(idx - 1, -1, -1):
                if row[left_idx].get("elevation_m") is not None:
                    left = row[left_idx]
                    break
            for right_idx in range(idx + 1, len(row)):
                if row[right_idx].get("elevation_m") is not None:
                    right = row[right_idx]
                    break
            if left and right:
                x1 = float(left.get("cross_offset_m", 0.0))
                x2 = float(right.get("cross_offset_m", 0.0))
                y1 = float(left.get("elevation_m"))
                y2 = float(right.get("elevation_m"))
                ratio = (target - x1) / (x2 - x1 or 1.0)
                value = y1 + (y2 - y1) * ratio
            elif left:
                value = float(left.get("elevation_m"))
            elif right:
                value = float(right.get("elevation_m"))
            else:
                continue
            item["elevation_m"] = round(value, 2)
            item["source_ref"] = "interpolated:row"
            item["source_distance_m"] = 0.0
            filled += 1

    remaining = [item for item in terrain_cloud_points if item.get("elevation_m") is None]
    if not remaining:
        return filled

    by_offset: dict[float, list[dict[str, Any]]] = {}
    for point in terrain_cloud_points:
        key = round(float(point.get("cross_offset_m", 0.0)), 2)
        by_offset.setdefault(key, []).append(point)
    for _, column in by_offset.items():
        column.sort(key=lambda item: float(item.get("distance_m", 0.0)))
        for idx, item in enumerate(column):
            if item.get("elevation_m") is not None:
                continue
            left = None
            right = None
            for left_idx in range(idx - 1, -1, -1):
                if column[left_idx].get("elevation_m") is not None:
                    left = column[left_idx]
                    break
            for right_idx in range(idx + 1, len(column)):
                if column[right_idx].get("elevation_m") is not None:
                    right = column[right_idx]
                    break
            if left and right:
                d1 = float(left.get("distance_m", 0.0))
                d2 = float(right.get("distance_m", 0.0))
                v1 = float(left.get("elevation_m"))
                v2 = float(right.get("elevation_m"))
                ratio = (float(item.get("distance_m", 0.0)) - d1) / (d2 - d1 or 1.0)
                value = v1 + (v2 - v1) * ratio
            elif left:
                value = float(left.get("elevation_m"))
            elif right:
                value = float(right.get("elevation_m"))
            else:
                continue
            item["elevation_m"] = round(value, 2)
            item["source_ref"] = "interpolated:column"
            item["source_distance_m"] = 0.0
            filled += 1
    return filled


def _fetch_overpass_json(query: str, timeout_s: float = 45.0) -> dict[str, Any]:
    request = urllib.request.Request(
        OVERPASS_API_URL,
        data=query.encode("utf-8"),
        headers={
            "User-Agent": "route-designer/1.0",
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _fetch_json_from_get(url: str, timeout_s: float = 20.0) -> dict[str, Any]:
    candidate_urls = [url]
    if url.startswith("https://"):
        candidate_urls.append("http://" + url[len("https://"):])
    errors: list[str] = []
    for candidate in candidate_urls:
        for verify_ssl in (True, False):
            for attempt in range(1, 4):
                try:
                    request = urllib.request.Request(
                        candidate,
                        headers={"User-Agent": "route-designer/1.0"},
                    )
                    context = None if verify_ssl else ssl._create_unverified_context()
                    with urllib.request.urlopen(request, timeout=timeout_s, context=context) as response:
                        payload = response.read().decode("utf-8")
                    return json.loads(payload)
                except (urllib.error.URLError, TimeoutError, ssl.SSLError, json.JSONDecodeError) as exc:
                    errors.append(f"{candidate} verify={verify_ssl} try={attempt}: {exc}")
                    if attempt < 3:
                        time.sleep(0.25 * attempt)
    raise ValueError("GET JSON 失败，尝试地址: " + " | ".join(candidate_urls) + "；错误: " + "；".join(errors[-6:]))


def _extract_terrain_open_topo(samples: list[dict[str, Any]], dataset_name: str = "aster30m") -> list[float | None]:
    values: list[float | None] = []
    chunk_size = 80
    for index in range(0, len(samples), chunk_size):
        chunk = samples[index:index + chunk_size]
        locations = "|".join(f"{sample['latitude']},{sample['longitude']}" for sample in chunk)
        url = f"https://api.opentopodata.org/v1/{dataset_name}?locations={locations}"
        payload = _fetch_json_from_get(url, timeout_s=25.0)
        results = payload.get("results", [])
        if len(results) != len(chunk):
            raise ValueError("OpenTopoData 返回数据数量异常")
        for item in results:
            elevation = item.get("elevation")
            values.append(round(float(elevation), 2) if elevation is not None else None)
    return values


def _extract_terrain_open_elevation(samples: list[dict[str, Any]]) -> list[float | None]:
    values: list[float | None] = []
    chunk_size = 80
    for index in range(0, len(samples), chunk_size):
        chunk = samples[index:index + chunk_size]
        locations = "|".join(f"{sample['latitude']},{sample['longitude']}" for sample in chunk)
        url = f"{OPEN_ELEVATION_URL}?locations={locations}"
        payload = _fetch_json_from_get(url, timeout_s=25.0)
        results = payload.get("results", [])
        if len(results) != len(chunk):
            raise ValueError("Open-Elevation 返回数据数量异常")
        for item in results:
            elevation = item.get("elevation")
            values.append(round(float(elevation), 2) if elevation is not None else None)
    return values


def _extract_terrain_open_meteo(samples: list[dict[str, Any]]) -> list[float | None]:
    values: list[float | None] = []
    chunk_size = 100
    for index in range(0, len(samples), chunk_size):
        chunk = samples[index:index + chunk_size]
        latitudes = ",".join(str(sample["latitude"]) for sample in chunk)
        longitudes = ",".join(str(sample["longitude"]) for sample in chunk)
        url = f"https://api.open-meteo.com/v1/elevation?latitude={latitudes}&longitude={longitudes}"
        payload = _fetch_json_from_get(url, timeout_s=22.0)
        results = payload.get("elevation", [])
        if len(results) != len(chunk):
            raise ValueError("Open-Meteo elevation 返回数据数量异常")
        for elevation in results:
            values.append(round(float(elevation), 2) if elevation is not None else None)
    return values


def _extract_bounds(geometry_obj) -> tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = geometry_obj.bounds
    return (float(min_lon), float(min_lat), float(max_lon), float(max_lat))


def _element_lon_lat(element: dict[str, Any]) -> tuple[float | None, float | None]:
    if element.get("type") == "node":
        lon = element.get("lon")
        lat = element.get("lat")
    else:
        center = element.get("center", {})
        lon = center.get("lon")
        lat = center.get("lat")
    if lon is None or lat is None:
        return None, None
    return float(lon), float(lat)


def _extract_buildings_in_protection(
    protection_geom,
    centerline_local: LineString,
    to_local,
) -> dict[str, Any]:
    west, south, east, north = _extract_bounds(protection_geom)
    query = (
        "[out:json][timeout:45];"
        "("
        f"node[\"building\"]({south},{west},{north},{east});"
        f"way[\"building\"]({south},{west},{north},{east});"
        f"relation[\"building\"]({south},{west},{north},{east});"
        ");"
        "out center tags;"
    )
    payload = _fetch_overpass_json(query, timeout_s=50.0)
    elements = payload.get("elements", [])

    scanned_count = 0
    items: list[dict[str, Any]] = []
    for element in elements:
        lon, lat = _element_lon_lat(element)
        if lon is None or lat is None:
            continue
        scanned_count += 1
        point_wgs = Point(lon, lat)
        if not (protection_geom.contains(point_wgs) or protection_geom.touches(point_wgs)):
            continue
        local_x, local_y = to_local(lon, lat)
        distance = centerline_local.distance(Point(local_x, local_y))
        tags = element.get("tags", {}) or {}
        item = {
            "id": f"{element.get('type', 'element')}/{element.get('id', '')}",
            "osm_type": str(element.get("type", "")),
            "osm_id": str(element.get("id", "")),
            "name": str(tags.get("name", "")),
            "longitude": round(lon, 7),
            "latitude": round(lat, 7),
            "distance_to_route_m": round(float(distance), 2),
            "height_m": _height_from_tags(tags),
            "ground_elevation_m": _ground_elevation_from_tags(tags),
            "levels": str(tags.get("building:levels") or tags.get("levels") or ""),
            "building_type": str(tags.get("building", "")),
            "raw_tags": tags,
        }
        items.append(item)

    items.sort(key=lambda item: item["distance_to_route_m"])
    heights = [float(item["height_m"]) for item in items if item["height_m"] is not None]
    grounds = [float(item["ground_elevation_m"]) for item in items if item["ground_elevation_m"] is not None]
    return {
        "source": "osm_overpass",
        "summary": {
            "scanned_count": scanned_count,
            "corridor_building_count": len(items),
            "height_record_count": len(heights),
            "ground_elevation_record_count": len(grounds),
            "height_stats": _summarize_numeric(heights),
            "ground_elevation_stats": _summarize_numeric(grounds),
        },
        "items": items,
    }


def _extract_ele_candidates_in_protection(
    protection_geom,
    to_local,
) -> list[dict[str, Any]]:
    west, south, east, north = _extract_bounds(protection_geom)
    query = (
        "[out:json][timeout:45];"
        "("
        f"node[\"ele\"]({south},{west},{north},{east});"
        f"way[\"ele\"]({south},{west},{north},{east});"
        ");"
        "out body geom tags;"
    )
    payload = _fetch_overpass_json(query, timeout_s=55.0)
    elements = payload.get("elements", [])

    candidates: list[dict[str, Any]] = []
    for element in elements:
        tags = element.get("tags", {}) or {}
        ele = _ground_elevation_from_tags(tags)
        if ele is None:
            continue
        # 完全排除带有建筑物高度信息的要素，仅保留纯地面海拔数据
        if any(k in tags for k in ("building", "building:part", "height", "building:height", "building:levels")):
            continue
        if tags.get("man_made") in ("tower", "mast", "chimney", "lighthouse", "water_tower", "communications_tower"):
            continue
        if element.get("type") == "node":
            lon = element.get("lon")
            lat = element.get("lat")
            if lon is None or lat is None:
                continue
            point_wgs = Point(float(lon), float(lat))
            if not (protection_geom.contains(point_wgs) or protection_geom.touches(point_wgs)):
                continue
            local_x, local_y = to_local(float(lon), float(lat))
            candidates.append(
                {
                    "source_ref": f"node/{element.get('id', '')}",
                    "longitude": round(float(lon), 7),
                    "latitude": round(float(lat), 7),
                    "local_x": float(local_x),
                    "local_y": float(local_y),
                    "elevation_m": ele,
                }
            )
            continue

        # way with fixed ele tag; use each vertex as candidate.
        geom_points = element.get("geometry", []) or []
        for vertex in geom_points:
            lon = vertex.get("lon")
            lat = vertex.get("lat")
            if lon is None or lat is None:
                continue
            point_wgs = Point(float(lon), float(lat))
            if not (protection_geom.contains(point_wgs) or protection_geom.touches(point_wgs)):
                continue
            local_x, local_y = to_local(float(lon), float(lat))
            candidates.append(
                {
                    "source_ref": f"way/{element.get('id', '')}",
                    "longitude": round(float(lon), 7),
                    "latitude": round(float(lat), 7),
                    "local_x": float(local_x),
                    "local_y": float(local_y),
                    "elevation_m": ele,
                }
            )
    return candidates


def _match_terrain_samples_from_candidates(
    samples: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    to_local,
    *,
    max_snap_distance_m: float = 120.0,
) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    values: list[float] = []
    for sample in samples:
        sample_x, sample_y = to_local(sample["longitude"], sample["latitude"])
        nearest = None
        nearest_dist = None
        for candidate in candidates:
            dist = math.hypot(float(candidate["local_x"]) - float(sample_x), float(candidate["local_y"]) - float(sample_y))
            if nearest_dist is None or dist < nearest_dist:
                nearest_dist = dist
                nearest = candidate
        elevation = None
        source_ref = ""
        if nearest is not None and nearest_dist is not None and nearest_dist <= max_snap_distance_m:
            elevation = float(nearest["elevation_m"])
            source_ref = str(nearest["source_ref"])
            values.append(elevation)
        points.append(
            {
                **sample,
                "elevation_m": round(elevation, 2) if elevation is not None else None,
                "source_ref": source_ref,
                "source_distance_m": round(float(nearest_dist), 2) if nearest_dist is not None else None,
            }
        )
    return {
        "source": "osm_ele_tags",
        "summary": {
            "sample_count": len(points),
            "elevation_record_count": len(values),
            "snap_distance_threshold_m": round(max_snap_distance_m, 2),
            "height_stats": _summarize_numeric(values),
        },
        "points": points,
    }


def _fill_missing_terrain_values(
    terrain_points: list[dict[str, Any]],
    provider_values: list[float | None],
    provider_name: str,
) -> int:
    if len(terrain_points) != len(provider_values):
        raise ValueError(f"{provider_name} 高程数组长度与采样点数量不一致")
    filled = 0
    for index, value in enumerate(provider_values):
        if value is None:
            continue
        point = terrain_points[index]
        if point.get("elevation_m") is not None:
            continue
        point["elevation_m"] = round(float(value), 2)
        point["source_ref"] = f"{provider_name}:{index + 1}"
        point["source_distance_m"] = 0.0
        filled += 1
    return filled


def _terrain_source_from_point(point: dict[str, Any]) -> str:
    source_ref = str(point.get("source_ref") or "")
    if source_ref.startswith("open_topo_data:") or source_ref.startswith("open_topo_srtm90m:"):
        return "open_topo_data"
    if source_ref.startswith("open_meteo:"):
        return "open_meteo"
    if source_ref.startswith("open_elevation:"):
        return "open_elevation"
    if source_ref.startswith("node/") or source_ref.startswith("way/"):
        return "osm_ele_tags"
    return "unknown"


def _rebuild_terrain_result(terrain_points: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(item["elevation_m"]) for item in terrain_points if item.get("elevation_m") is not None]
    source_set: set[str] = set()
    for point in terrain_points:
        if point.get("elevation_m") is not None:
            source_set.add(_terrain_source_from_point(point))
    if not source_set:
        source_set.add("none")
    source_text = "+".join(sorted(source_set))
    return {
        "source": source_text,
        "summary": {
            "sample_count": len(terrain_points),
            "elevation_record_count": len(values),
            "snap_distance_threshold_m": 120.0,
            "height_stats": _summarize_numeric(values),
        },
        "points": terrain_points,
    }


def _derive_cloud_terrain_from_centerline(
    terrain_cloud_points: list[dict[str, Any]],
    terrain_points: list[dict[str, Any]],
) -> int:
    known_points = [
        item
        for item in terrain_points
        if item.get("elevation_m") is not None and item.get("distance_m") is not None
    ]
    if not terrain_cloud_points or not known_points:
        return 0
    known_points.sort(key=lambda item: float(item.get("distance_m", 0.0)))
    known_distances = [float(item.get("distance_m", 0.0)) for item in known_points]

    filled = 0
    for item in terrain_cloud_points:
        distance = float(item.get("distance_m", 0.0))
        insert_at = bisect_left(known_distances, distance)
        candidates = []
        if insert_at > 0:
            candidates.append(known_points[insert_at - 1])
        if insert_at < len(known_points):
            candidates.append(known_points[insert_at])
        if not candidates:
            continue
        nearest = min(candidates, key=lambda point: abs(float(point.get("distance_m", 0.0)) - distance))
        item["elevation_m"] = round(float(nearest["elevation_m"]), 2)
        item["source_ref"] = f"derived:centerline:{nearest.get('source_ref') or 'terrain'}"
        item["source_distance_m"] = round(abs(float(nearest.get("distance_m", 0.0)) - distance), 2)
        filled += 1
    return filled


def _persist_geo_data(
    route_id: int,
    route_name: str,
    centerline_geojson: dict[str, Any],
    protection_geojson: dict[str, Any],
    buildings: list[dict[str, Any]],
    terrain_points: list[dict[str, Any]],
    terrain_cloud_points: list[dict[str, Any]],
    module_statuses: list[dict[str, Any]],
) -> None:
    terrain_record_count = sum(1 for item in terrain_points if item.get("elevation_m") is not None)
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM route_geo_buildings WHERE route_id=?", (route_id,))
        cursor.execute("DELETE FROM route_geo_terrain WHERE route_id=?", (route_id,))
        cursor.execute("DELETE FROM route_geo_terrain_cloud WHERE route_id=?", (route_id,))

        cursor.executemany(
            """
            INSERT INTO route_geo_buildings (
                route_id, osm_type, osm_id, name, longitude, latitude, distance_to_route_m,
                height_m, ground_elevation_m, levels, building_type, raw_tags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    route_id,
                    item.get("osm_type"),
                    item.get("osm_id"),
                    item.get("name"),
                    item.get("longitude"),
                    item.get("latitude"),
                    item.get("distance_to_route_m"),
                    item.get("height_m"),
                    item.get("ground_elevation_m"),
                    item.get("levels"),
                    item.get("building_type"),
                    json.dumps(item.get("raw_tags", {}), ensure_ascii=False),
                )
                for item in buildings
            ],
        )

        cursor.executemany(
            """
            INSERT INTO route_geo_terrain (
                route_id, sample_index, distance_m, longitude, latitude,
                elevation_m, source_ref, source_distance_m
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    route_id,
                    item.get("index"),
                    item.get("distance_m"),
                    item.get("longitude"),
                    item.get("latitude"),
                    item.get("elevation_m"),
                    item.get("source_ref", ""),
                    item.get("source_distance_m"),
                )
                for item in terrain_points
            ],
        )

        cursor.executemany(
            """
            INSERT INTO route_geo_terrain_cloud (
                route_id, sample_index, distance_m, cross_offset_m, longitude, latitude,
                elevation_m, source_ref, source_distance_m
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    route_id,
                    item.get("index"),
                    item.get("distance_m"),
                    item.get("cross_offset_m", 0.0),
                    item.get("longitude"),
                    item.get("latitude"),
                    item.get("elevation_m"),
                    item.get("source_ref", ""),
                    item.get("source_distance_m"),
                )
                for item in terrain_cloud_points
            ],
        )

        cursor.execute(
            """
            INSERT INTO route_geo_extractions (
                route_id, route_name, source, module_status_json, building_count,
                terrain_sample_count, terrain_record_count, protection_zone_json, centerline_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(route_id) DO UPDATE SET
                route_name=excluded.route_name,
                source=excluded.source,
                module_status_json=excluded.module_status_json,
                building_count=excluded.building_count,
                terrain_sample_count=excluded.terrain_sample_count,
                terrain_record_count=excluded.terrain_record_count,
                protection_zone_json=excluded.protection_zone_json,
                centerline_json=excluded.centerline_json,
                extracted_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                route_id,
                route_name,
                "osm_overpass",
                json.dumps(module_statuses, ensure_ascii=False),
                len(buildings),
                len(terrain_points),
                terrain_record_count,
                json.dumps(protection_geojson, ensure_ascii=False),
                json.dumps(centerline_geojson, ensure_ascii=False),
            ),
        )


def _safe_json_load(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def get_route_geo_data(route_id: int) -> dict[str, Any] | None:
    route = get_route(route_id)
    if not route:
        raise ValueError("Route not found")

    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT route_id, route_name, source, module_status_json, building_count,
                   terrain_sample_count, terrain_record_count, protection_zone_json,
                   centerline_json, extracted_at, updated_at
            FROM route_geo_extractions
            WHERE route_id=?
            """,
            (route_id,),
        )
        extraction_row = cursor.fetchone()
        if not extraction_row:
            return None

        cursor.execute(
            """
            SELECT osm_type, osm_id, name, longitude, latitude, distance_to_route_m,
                   height_m, ground_elevation_m, levels, building_type, raw_tags_json
            FROM route_geo_buildings
            WHERE route_id=?
            ORDER BY distance_to_route_m ASC, id ASC
            """,
            (route_id,),
        )
        building_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT sample_index, distance_m, longitude, latitude, elevation_m, source_ref, source_distance_m
            FROM route_geo_terrain
            WHERE route_id=?
            ORDER BY sample_index ASC
            """,
            (route_id,),
        )
        terrain_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT sample_index, distance_m, cross_offset_m, longitude, latitude, elevation_m, source_ref, source_distance_m
            FROM route_geo_terrain_cloud
            WHERE route_id=?
            ORDER BY sample_index ASC
            """,
            (route_id,),
        )
        terrain_cloud_rows = cursor.fetchall()

    extraction = dict(extraction_row)
    modules = _safe_json_load(extraction.get("module_status_json"), [])
    centerline_geo = _safe_json_load(extraction.get("centerline_json"), None)
    protection_geo = _safe_json_load(extraction.get("protection_zone_json"), None)

    buildings: list[dict[str, Any]] = []
    for row in building_rows:
        item = dict(row)
        item["id"] = f"{item.get('osm_type')}/{item.get('osm_id')}"
        item["raw_tags"] = _safe_json_load(item.get("raw_tags_json"), {})
        item.pop("raw_tags_json", None)
        buildings.append(item)

    terrain_points: list[dict[str, Any]] = []
    for row in terrain_rows:
        item = dict(row)
        item["index"] = item.pop("sample_index")
        terrain_points.append(item)

    terrain_cloud_points: list[dict[str, Any]] = []
    for row in terrain_cloud_rows:
        item = dict(row)
        item["index"] = item.pop("sample_index")
        terrain_cloud_points.append(item)

    height_values = [float(item["height_m"]) for item in buildings if item.get("height_m") is not None]
    ground_values = [float(item["ground_elevation_m"]) for item in buildings if item.get("ground_elevation_m") is not None]
    terrain_values = [float(item["elevation_m"]) for item in terrain_points if item.get("elevation_m") is not None]
    terrain_source_set = {_terrain_source_from_point(item) for item in terrain_points if item.get("elevation_m") is not None}
    terrain_source = "+".join(sorted(terrain_source_set)) if terrain_source_set else "none"

    bounds = None
    if centerline_geo:
        line_shape = shape(centerline_geo)
        west, south, east, north = line_shape.bounds
        bounds = {
            "west": round(float(west), 7),
            "south": round(float(south), 7),
            "east": round(float(east), 7),
            "north": round(float(north), 7),
        }

    return {
        "ok": True,
        "route_id": extraction["route_id"],
        "route_name": extraction["route_name"],
        "centerline": centerline_geo,
        "protection_zone": protection_geo,
        "flight_zone": None,
        "view_bounds": bounds,
        "terrain": {
            "source": terrain_source,
            "summary": {
                "sample_count": len(terrain_points),
                "elevation_record_count": len(terrain_values),
                "cloud_sample_count": len(terrain_cloud_points),
                "snap_distance_threshold_m": 120.0,
                "height_stats": _summarize_numeric(terrain_values),
            },
            "points": terrain_points,
            "cloud_points": terrain_cloud_points,
        },
        "buildings": {
            "source": extraction.get("source", "osm_overpass"),
            "summary": {
                "scanned_count": None,
                "corridor_building_count": len(buildings),
                "height_record_count": len(height_values),
                "ground_elevation_record_count": len(ground_values),
                "height_stats": _summarize_numeric(height_values),
                "ground_elevation_stats": _summarize_numeric(ground_values),
            },
            "items": buildings,
        },
        "modules": modules,
        "storage": {
            "persisted": True,
            "building_rows": len(buildings),
            "terrain_rows": len(terrain_points),
            "terrain_cloud_rows": len(terrain_cloud_points),
            "terrain_record_rows": len(terrain_values),
            "extracted_at": extraction.get("extracted_at"),
            "updated_at": extraction.get("updated_at"),
        },
    }


def _build_geometry_for_geo_extract(route_id: int) -> tuple[dict[str, Any], Any, Any]:
    generated = generate_route_geometry(route_id)
    if not generated.get("ok"):
        errors = generated.get("errors") or ["航路几何生成失败"]
        raise ValueError("; ".join(errors))
    protection_geo = generated.get("protection_zone")
    centerline_geo = generated.get("centerline")
    if not protection_geo or not centerline_geo:
        raise ValueError("缺少保护区或航路中线几何数据")
    protection_geom = shape(protection_geo)
    centerline_geom = shape(centerline_geo)
    if protection_geom.is_empty or centerline_geom.is_empty:
        raise ValueError("保护区或中线几何数据无效")
    return generated, protection_geom, centerline_geom


def _apply_terrain_provider(
    provider_key: str,
    *,
    samples: list[dict[str, Any]],
    terrain_points: list[dict[str, Any]],
    protection_geom,
    to_local,
) -> int:
    if provider_key == "osm_ele_tags":
        candidates = _extract_ele_candidates_in_protection(protection_geom, to_local)
        terrain_match = _match_terrain_samples_from_candidates(samples, candidates, to_local)
        terrain_points[:] = terrain_match["points"]
        return int(terrain_match["summary"]["elevation_record_count"])
    if provider_key == "open_topo_data":
        values = _extract_terrain_open_topo(samples, "aster30m")
        return _fill_missing_terrain_values(terrain_points, values, "open_topo_data")
    if provider_key == "open_topo_srtm90m":
        values = _extract_terrain_open_topo(samples, "srtm90m")
        return _fill_missing_terrain_values(terrain_points, values, "open_topo_srtm90m")
    if provider_key == "open_meteo":
        values = _extract_terrain_open_meteo(samples)
        return _fill_missing_terrain_values(terrain_points, values, "open_meteo")
    if provider_key == "open_elevation":
        values = _extract_terrain_open_elevation(samples)
        return _fill_missing_terrain_values(terrain_points, values, "open_elevation")
    raise ValueError(f"Unsupported terrain provider: {provider_key}")


def extract_route_geo_data(route_id: int, datasource_url: str | None = None) -> dict[str, Any]:
    route = get_route(route_id)
    if not route:
        raise ValueError("Route not found")

    points = get_points(route_id)
    if len(points) < 2:
        raise ValueError("Insufficient route points for geo extraction")

    generated, protection_geom, centerline_geom = _build_geometry_for_geo_extract(route_id)
    ref_lon = float(points[0]["longitude"])
    ref_lat = float(points[0]["latitude"])
    to_local, to_wgs84 = build_local_transformers(ref_lon, ref_lat)
    centerline_local = transform(to_local, centerline_geom)

    samples = _build_sample_points(centerline_local, to_wgs84)
    flight_half = max(0.0, float(route.get("flight_width", 0.0)) / 2.0)
    protection_width = max(0.0, float(route.get("protection_width", 0.0)))
    protection_half = flight_half + protection_width
    terrain_cross_half = protection_half

    terrain_cloud_samples = _build_cross_section_cloud_samples(
        centerline_local,
        to_wgs84,
        cross_half_width_m=terrain_cross_half,
        per_side_count=10,
    )
    module_statuses: list[dict[str, Any]] = []
    preferred_source_info = None
    preferred_extraction_key = None
    if datasource_url:
        preferred_source_info = identify_datasource(datasource_url)
        preferred_extraction_key = preferred_source_info.get("extraction_key")
        module_statuses.append(
            {
                "module": "datasource",
                "success": bool(preferred_extraction_key),
                "message": (
                    f"Selected datasource for priority extraction: {preferred_source_info.get('source_key')}"
                    if preferred_extraction_key
                    else f"Selected datasource is not supported for terrain extraction: {preferred_source_info.get('source_key')}"
                ),
                "source": preferred_source_info.get("source_key") or "custom",
            }
        )

    # 1) Skip buildings extraction to improve speed; keep schema-compatible empty payload.
    building_success = True
    building_message = "Building extraction skipped for faster terrain-only workflow"
    building_result = {
        "source": "skipped",
        "summary": {
            "scanned_count": 0,
            "corridor_building_count": 0,
            "height_record_count": 0,
            "ground_elevation_record_count": 0,
            "height_stats": {"min": 0.0, "max": 0.0, "avg": 0.0},
            "ground_elevation_stats": {"min": 0.0, "max": 0.0, "avg": 0.0},
        },
        "items": [],
    }
    module_statuses.append(
        {
            "module": "buildings",
            "success": building_success,
            "message": building_message,
            "source": "skipped",
        }
    )

    # 2) Centerline terrain elevations with configurable priority.
    terrain_points = [{**sample, "elevation_m": None, "source_ref": "", "source_distance_m": None} for sample in samples]
    terrain_attempts: list[str] = []
    terrain_errors: list[str] = []
    provider_order = terrain_provider_priority(preferred_extraction_key)

    for provider_key in provider_order:
        current_count = sum(1 for item in terrain_points if item.get("elevation_m") is not None)
        if current_count >= len(terrain_points):
            break
        try:
            filled = _apply_terrain_provider(
                provider_key,
                samples=samples,
                terrain_points=terrain_points,
                protection_geom=protection_geom,
                to_local=to_local,
            )
            if provider_key == "osm_ele_tags":
                terrain_attempts.append(f"{provider_key}={filled}")
            else:
                terrain_attempts.append(f"{provider_key}=+{filled}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            terrain_errors.append(f"{provider_key}:{exc}")

    terrain_result = _rebuild_terrain_result(terrain_points)
    terrain_count = int(terrain_result["summary"]["elevation_record_count"])
    terrain_success = terrain_count > 0
    if terrain_success:
        terrain_message = (
            f"Terrain extraction completed: {terrain_count}/{len(terrain_points)} samples "
            f"(source={terrain_result['source']}, priority={','.join(provider_order)})"
        )
    else:
        attempts_text = "; ".join(terrain_attempts) if terrain_attempts else "none"
        errors_text = "; ".join(terrain_errors) if terrain_errors else "none"
        terrain_message = (
            "Terrain extraction failed after provider fallback "
            f"(priority={','.join(provider_order)}, attempts={attempts_text}, errors={errors_text})"
        )
    module_statuses.append(
        {
            "module": "terrain",
            "success": terrain_success,
            "message": terrain_message,
            "source": terrain_result["source"],
        }
    )

    # 3) Terrain cloud for cross-section drawing. Derive from centerline terrain
    # to avoid thousands of slow external elevation requests on long routes.
    terrain_cloud_points = [
        {**sample, "elevation_m": None, "source_ref": "", "source_distance_m": None}
        for sample in terrain_cloud_samples
    ]
    cloud_filled = _derive_cloud_terrain_from_centerline(terrain_cloud_points, terrain_result["points"])
    module_statuses.append(
        {
            "module": "terrain_cloud",
            "success": cloud_filled > 0 or not terrain_cloud_points,
            "message": (
                f"Cross-section terrain derived from centerline samples: {cloud_filled}/{len(terrain_cloud_points)}"
            ),
            "source": "derived_centerline",
        }
    )

    _persist_geo_data(
        route_id=route_id,
        route_name=str(route["name"]),
        centerline_geojson=generated["centerline"],
        protection_geojson=generated["protection_zone"],
        buildings=building_result["items"],
        terrain_points=terrain_result["points"],
        terrain_cloud_points=terrain_cloud_points,
        module_statuses=module_statuses,
    )

    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT extracted_at, updated_at
            FROM route_geo_extractions
            WHERE route_id=?
            """,
            (route_id,),
        )
        storage_row = cursor.fetchone()

    extracted_at = storage_row["extracted_at"] if storage_row else None
    updated_at = storage_row["updated_at"] if storage_row else None

    west, south, east, north = centerline_geom.bounds
    return {
        "ok": True,
        "route_id": route_id,
        "route_name": route["name"],
        "centerline": generated["centerline"],
        "protection_zone": generated["protection_zone"],
        "flight_zone": generated.get("flight_zone"),
        "view_bounds": {
            "west": round(float(west), 7),
            "south": round(float(south), 7),
            "east": round(float(east), 7),
            "north": round(float(north), 7),
        },
        "terrain": {
            **terrain_result,
            "cloud_points": terrain_cloud_points,
            "summary": {
                **terrain_result.get("summary", {}),
                "cloud_sample_count": len(terrain_cloud_points),
                "cross_section_half_width_m": round(float(terrain_cross_half), 2),
                "provider_priority": provider_order,
            },
        },
        "buildings": building_result,
        "modules": module_statuses,
        "storage": {
            "persisted": True,
            "building_rows": len(building_result["items"]),
            "terrain_rows": len(terrain_result["points"]),
            "terrain_cloud_rows": len(terrain_cloud_points),
            "terrain_record_rows": sum(1 for item in terrain_result["points"] if item.get("elevation_m") is not None),
            "extracted_at": extracted_at,
            "updated_at": updated_at,
        },
    }

