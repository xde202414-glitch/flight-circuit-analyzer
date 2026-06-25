from __future__ import annotations

import json
import math
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from shapely import LineString, Point
from shapely.geometry import mapping
from shapely.ops import transform

from app.database_route import db_cursor
from app.models.route_schemas import DEFAULT_LAYER_SCHEME
from app.services.approach_service import build_approach_lines
from app.services.coordinate_service import build_local_transformers

MAX_LAYER_HEIGHT = 300.0
OPEN_TOPO_DATA_URL = "https://api.opentopodata.org/v1/aster30m"
OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
TURN_EPSILON = 1e-6


def _parse_layer_scheme(scheme: str) -> list[tuple[float, float]]:
    layers: list[tuple[float, float]] = []
    for raw in scheme.split(","):
        token = raw.strip()
        if not token:
            continue
        parts = token.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid layer token: {token}")
        low = float(parts[0].strip())
        high = float(parts[1].strip())
        if high <= low:
            raise ValueError(f"Invalid layer range: {token}")
        layers.append((low, high))
    if not layers:
        raise ValueError("Layer scheme is empty")
    return sorted(layers, key=lambda item: item[0])


def _normalize_route_dict(route: dict[str, Any] | None) -> dict[str, Any] | None:
    if route is None:
        return None
    normalized = dict(route)
    normalized["enable_layering"] = bool(normalized.get("enable_layering", 1))
    normalized["is_complete"] = bool(normalized.get("is_complete", 0))
    normalized["layer_step"] = float(normalized.get("layer_step", 50))
    normalized["layer_scheme"] = normalized.get("layer_scheme") or DEFAULT_LAYER_SCHEME
    normalized["altitude_reference_mode"] = normalized.get("altitude_reference_mode") or "asl"
    normalized["altitude_change_min"] = float(normalized.get("altitude_change_min", 10))
    return normalized


def _rows_to_dicts(rows) -> list[dict[str, Any]]:
    items = [dict(row) for row in rows]
    if not items:
        return items
    if "enable_layering" in items[0]:
        return [_normalize_route_dict(item) for item in items]
    return items


def _normalize_point_order(route_id: int) -> None:
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT id, order_index FROM route_points WHERE route_id = ? ORDER BY order_index ASC, id ASC",
            (route_id,),
        )
        rows = cursor.fetchall()
    updates: list[tuple[int, int]] = []
    for index, row in enumerate(rows):
        if row["order_index"] != index:
            updates.append((index, row["id"]))
    if not updates:
        return
    with db_cursor() as cursor:
        cursor.executemany("UPDATE route_points SET order_index = ? WHERE id = ?", updates)


def list_routes() -> list[dict[str, Any]]:
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT r.*,
                   (SELECT COUNT(*) FROM route_points p WHERE p.route_id = r.id) AS point_count,
                   (SELECT COUNT(*) FROM landing_sites l WHERE l.route_id = r.id) AS landing_count
            FROM routes r
            ORDER BY r.updated_at DESC, r.id DESC
            """
        )
        return _rows_to_dicts(cursor.fetchall())


def get_route(route_id: int) -> dict[str, Any] | None:
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM routes WHERE id = ?", (route_id,))
        row = cursor.fetchone()
        return _normalize_route_dict(dict(row)) if row else None


def get_points(route_id: int) -> list[dict[str, Any]]:
    _normalize_point_order(route_id)
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM route_points WHERE route_id = ? ORDER BY order_index ASC, id ASC",
            (route_id,),
        )
        return _rows_to_dicts(cursor.fetchall())


def get_landing_sites(route_id: int) -> list[dict[str, Any]]:
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM landing_sites WHERE route_id = ? ORDER BY id ASC", (route_id,))
        return _rows_to_dicts(cursor.fetchall())


def _has_protection_zone_geometry(geometry: dict[str, Any] | None) -> bool:
    if not geometry:
        return False
    geo_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    return geo_type in {"Polygon", "MultiPolygon"} and bool(coordinates)


def _has_flight_zone_geometry(geometry: dict[str, Any] | None) -> bool:
    if not geometry:
        return False
    geo_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    return geo_type in {"Polygon", "MultiPolygon"} and bool(coordinates)


def _has_altitude_layers(route: dict[str, Any], sub_routes: list[dict[str, Any]]) -> bool:
    if not sub_routes:
        return False
    valid_layers = all(float(layer["top_height"]) > float(layer["bottom_height"]) for layer in sub_routes)
    if not valid_layers:
        return False
    # Single-layer route should also count as having valid layer content.
    if not route.get("enable_layering"):
        return len(sub_routes) >= 1
    return True


def _evaluate_route_completeness(
    route: dict[str, Any] | None,
    points: list[dict[str, Any]],
    sub_routes: list[dict[str, Any]],
    *,
    has_flight_zone_geometry: bool,
    has_protection_zone_geometry: bool,
) -> dict[str, Any]:
    if not route:
        return {
            "has_start_point": False,
            "has_waypoint_point": False,
            "has_end_point": False,
            "has_flight_width": False,
            "has_protection_width": False,
            "has_height_range": False,
            "has_flight_zone": False,
            "has_sub_route_layers": False,
            "has_protection_zone": False,
            "is_complete": False,
            "missing_items": ["航路不存在"],
        }
    start_count = sum(1 for point in points if point["point_type"] == "start")
    waypoint_count = sum(1 for point in points if point["point_type"] == "waypoint")
    end_count = sum(1 for point in points if point["point_type"] == "end")
    has_start_point = start_count == 1
    has_waypoint_point = waypoint_count >= 1
    has_end_point = end_count == 1
    has_flight_width = 30 <= float(route["flight_width"]) <= 50
    has_protection_width = 50 <= float(route["protection_width"]) <= 200
    has_height_range = float(route["top_height"]) > float(route["bottom_height"])
    has_sub_route_scheme = _has_altitude_layers(route, sub_routes)
    has_sub_route_layers = bool(has_sub_route_scheme and has_protection_zone_geometry)

    checks = [
        ("起点", has_start_point),
        ("航路点", has_waypoint_point),
        ("终点", has_end_point),
        ("飞行区宽度", has_flight_width),
        ("保护区宽度", has_protection_width),
        ("航路高度", has_height_range),
        ("飞行区", bool(has_flight_zone_geometry)),
        ("子航路分层", has_sub_route_layers),
        ("保护区", bool(has_protection_zone_geometry)),
    ]
    missing_items = [label for label, ok in checks if not ok]
    is_complete = len(missing_items) == 0
    return {
        "has_start_point": has_start_point,
        "has_waypoint_point": has_waypoint_point,
        "has_end_point": has_end_point,
        "has_flight_width": has_flight_width,
        "has_protection_width": has_protection_width,
        "has_height_range": has_height_range,
        "has_flight_zone": bool(has_flight_zone_geometry),
        "has_sub_route_layers": has_sub_route_layers,
        "has_protection_zone": bool(has_protection_zone_geometry),
        "has_altitude_layers": has_sub_route_layers,
        "is_complete": is_complete,
        "missing_items": missing_items,
    }


def assess_route_completeness(route_id: int) -> dict[str, Any]:
    route = get_route(route_id)
    if not route:
        raise ValueError("Route not found")
    points = get_points(route_id)
    try:
        sub_routes = _build_altitude_sub_routes(route)
    except ValueError:
        sub_routes = []
    full_state = get_route_full_state(route_id)
    snapshot = full_state.get("snapshot") if full_state else None
    has_flight_zone_geometry = _has_flight_zone_geometry(snapshot.get("flight_zone")) if isinstance(snapshot, dict) else False
    has_protection_zone_geometry = _has_protection_zone_geometry(snapshot.get("protection_zone")) if isinstance(snapshot, dict) else False
    return _evaluate_route_completeness(
        route,
        points,
        sub_routes,
        has_flight_zone_geometry=has_flight_zone_geometry,
        has_protection_zone_geometry=has_protection_zone_geometry,
    )


def _persist_route_full_state(route_id: int, payload: dict[str, Any], completeness: dict[str, Any]) -> None:
    snapshot = json.dumps(payload, ensure_ascii=False)
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO route_full_state (
                route_id, snapshot_json, has_protection_zone, has_altitude_layers, is_complete
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(route_id) DO UPDATE SET
                snapshot_json=excluded.snapshot_json,
                has_protection_zone=excluded.has_protection_zone,
                has_altitude_layers=excluded.has_altitude_layers,
                is_complete=excluded.is_complete,
                generated_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                route_id,
                snapshot,
                1 if completeness["has_protection_zone"] else 0,
                1 if completeness["has_altitude_layers"] else 0,
                1 if completeness["is_complete"] else 0,
            ),
        )
        cursor.execute(
            """
            UPDATE routes
            SET is_complete=?, last_generated_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (1 if completeness["is_complete"] else 0, route_id),
        )


def invalidate_route_full_state(route_id: int) -> None:
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM route_full_state WHERE route_id = ?", (route_id,))
        cursor.execute(
            """
            UPDATE routes
            SET is_complete=0, last_generated_at=NULL, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (route_id,),
        )


def update_route_full_state_route_name(route_id: int, route_name: str) -> None:
    """Keep generated route snapshots usable when only the display name changes."""
    full_state = get_route_full_state(route_id)
    snapshot = full_state.get("snapshot") if full_state else None
    if not isinstance(snapshot, dict):
        return
    route_snapshot = snapshot.get("route")
    if not isinstance(route_snapshot, dict):
        return
    route_snapshot["name"] = route_name
    with db_cursor() as cursor:
        cursor.execute(
            """
            UPDATE route_full_state
            SET snapshot_json=?, updated_at=CURRENT_TIMESTAMP
            WHERE route_id=?
            """,
            (json.dumps(snapshot, ensure_ascii=False), route_id),
        )


def get_route_full_state(route_id: int) -> dict[str, Any] | None:
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT route_id, snapshot_json, has_protection_zone, has_altitude_layers, is_complete, generated_at, updated_at
            FROM route_full_state
            WHERE route_id=?
            """,
            (route_id,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    raw = dict(row)
    try:
        snapshot = json.loads(raw["snapshot_json"])
    except json.JSONDecodeError:
        snapshot = None
    return {
        "route_id": raw["route_id"],
        "has_protection_zone": bool(raw["has_protection_zone"]),
        "has_altitude_layers": bool(raw["has_altitude_layers"]),
        "is_complete": bool(raw["is_complete"]),
        "generated_at": raw["generated_at"],
        "updated_at": raw["updated_at"],
        "snapshot": snapshot,
    }


def _build_altitude_sub_routes(route: dict[str, Any]) -> list[dict[str, Any]]:
    if not route["enable_layering"]:
        return [
            {
                "sequence": 1,
                "name": "Main Route",
                "bottom_height": float(route["bottom_height"]),
                "top_height": float(route["top_height"]),
            }
        ]

    configured = _parse_layer_scheme(route["layer_scheme"])
    route_low = float(route["bottom_height"])
    route_high = min(float(route["top_height"]), MAX_LAYER_HEIGHT)
    sub_routes: list[dict[str, Any]] = []
    sequence = 1
    for low, high in configured:
        low_clip = max(low, route_low)
        high_clip = min(high, route_high)
        if high_clip <= low_clip:
            continue
        sub_routes.append(
            {
                "sequence": sequence,
                "name": f"Sub Route {sequence}",
                "bottom_height": round(low_clip, 2),
                "top_height": round(high_clip, 2),
            }
        )
        sequence += 1
    return sub_routes


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
    raise ValueError("Elevation GET failed: " + " ; ".join(errors[-6:]))


def _extract_elevations_open_topo(samples: list[dict[str, Any]], dataset_name: str = "aster30m") -> list[float | None]:
    values: list[float | None] = []
    chunk_size = 80
    for index in range(0, len(samples), chunk_size):
        chunk = samples[index:index + chunk_size]
        locations = "|".join(f"{sample['latitude']},{sample['longitude']}" for sample in chunk)
        url = f"https://api.opentopodata.org/v1/{dataset_name}?locations={locations}"
        payload = _fetch_json_from_get(url, timeout_s=25.0)
        results = payload.get("results", [])
        if len(results) != len(chunk):
            raise ValueError("OpenTopoData response size mismatch")
        for item in results:
            elevation = item.get("elevation")
            values.append(round(float(elevation), 2) if elevation is not None else None)
    return values


def _extract_elevations_open_meteo(samples: list[dict[str, Any]]) -> list[float | None]:
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
            raise ValueError("Open-Meteo response size mismatch")
        for elevation in results:
            values.append(round(float(elevation), 2) if elevation is not None else None)
    return values


def _extract_elevations_open_elevation(samples: list[dict[str, Any]]) -> list[float | None]:
    values: list[float | None] = []
    chunk_size = 80
    for index in range(0, len(samples), chunk_size):
        chunk = samples[index:index + chunk_size]
        locations = "|".join(f"{sample['latitude']},{sample['longitude']}" for sample in chunk)
        url = f"{OPEN_ELEVATION_URL}?locations={locations}"
        payload = _fetch_json_from_get(url, timeout_s=25.0)
        results = payload.get("results", [])
        if len(results) != len(chunk):
            raise ValueError("Open-Elevation response size mismatch")
        for item in results:
            elevation = item.get("elevation")
            values.append(round(float(elevation), 2) if elevation is not None else None)
    return values


def _fetch_multi_source_elevations(samples: list[dict[str, Any]]) -> tuple[list[float | None], str]:
    providers = [
        ("open_topo_data", lambda items: _extract_elevations_open_topo(items, "aster30m")),
        ("open_topo_srtm90m", lambda items: _extract_elevations_open_topo(items, "srtm90m")),
        ("open_meteo", _extract_elevations_open_meteo),
        ("open_elevation", _extract_elevations_open_elevation),
    ]
    errors: list[str] = []
    for name, fetcher in providers:
        try:
            values = fetcher(samples)
            valid_count = sum(1 for value in values if value is not None)
            if valid_count > 0:
                return values, name
            errors.append(f"{name}:no_values")
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{name}:{exc}")
    return [None for _ in samples], "none(" + "; ".join(errors[-4:]) + ")"


def _lookup_cached_terrain_for_distances(route_id: int, distances: list[float]) -> list[float | None]:
    if not distances:
        return []
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT distance_m, elevation_m
            FROM route_geo_terrain
            WHERE route_id=? AND elevation_m IS NOT NULL
            ORDER BY distance_m ASC
            """,
            (route_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    if not rows:
        return [None for _ in distances]
    if len(rows) == 1:
        only = float(rows[0]["elevation_m"])
        return [only for _ in distances]

    values: list[float | None] = []
    for distance in distances:
        distance_value = float(distance)
        if distance_value <= float(rows[0]["distance_m"]):
            values.append(float(rows[0]["elevation_m"]))
            continue
        if distance_value >= float(rows[-1]["distance_m"]):
            values.append(float(rows[-1]["elevation_m"]))
            continue
        appended = False
        for idx in range(1, len(rows)):
            prev = rows[idx - 1]
            curr = rows[idx]
            left = float(prev["distance_m"])
            right = float(curr["distance_m"])
            if left <= distance_value <= right:
                ratio = (distance_value - left) / (right - left or 1.0)
                elev = float(prev["elevation_m"]) + (float(curr["elevation_m"]) - float(prev["elevation_m"])) * ratio
                values.append(round(elev, 2))
                appended = True
                break
        if not appended:
            values.append(None)
    return values


def _apply_min_change_smoothing(values: list[float | None], min_change: float) -> list[float | None]:
    if not values:
        return values
    threshold = max(0.0, float(min_change))
    smoothed: list[float | None] = []
    prev: float | None = None
    for value in values:
        if value is None:
            smoothed.append(prev)
            continue
        if prev is None:
            prev = float(value)
            smoothed.append(round(prev, 2))
            continue
        if abs(float(value) - prev) < threshold:
            smoothed.append(round(prev, 2))
            continue
        prev = float(value)
        smoothed.append(round(prev, 2))
    return smoothed


def _select_profile_control_step(total_distance_m: float) -> float:
    if total_distance_m <= 0:
        return 10.0
    # Keep AGL control points dense on short routes while avoiding huge payloads on long routes.
    return max(10.0, min(60.0, float(total_distance_m) / 240.0))


def _build_agl_control_samples(
    route_point_samples: list[dict[str, Any]],
    *,
    centerline_local: LineString,
    to_wgs84,
    route_bottom: float,
    step_m: float,
) -> list[dict[str, Any]]:
    if not route_point_samples:
        return []

    controls: list[dict[str, Any]] = []
    control_index = 1
    first = route_point_samples[0]
    first_required = max(float(route_bottom), float(first.get("height_offset_m", route_bottom)))
    controls.append(
        {
            "control_index": control_index,
            "distance_m": round(float(first["distance_m"]), 2),
            "longitude": round(float(first["longitude"]), 7),
            "latitude": round(float(first["latitude"]), 7),
            "is_route_point": True,
            "route_point_index": int(first["index"]),
            "required_clearance_m": round(first_required, 2),
        }
    )
    control_index += 1

    for point_index in range(1, len(route_point_samples)):
        prev = route_point_samples[point_index - 1]
        curr = route_point_samples[point_index]
        start_distance = float(prev["distance_m"])
        end_distance = float(curr["distance_m"])
        segment_length = max(0.0, end_distance - start_distance)
        prev_required = max(float(route_bottom), float(prev.get("height_offset_m", route_bottom)))
        curr_required = max(float(route_bottom), float(curr.get("height_offset_m", route_bottom)))

        if segment_length > 1e-6 and step_m > 0:
            step_count = int(math.floor(segment_length / step_m))
            for step_index in range(1, step_count + 1):
                current_distance = start_distance + step_index * step_m
                if current_distance >= end_distance - 1e-6:
                    break
                ratio = (current_distance - start_distance) / segment_length
                control_local = centerline_local.interpolate(current_distance)
                longitude, latitude = to_wgs84(*control_local.coords[0])
                controls.append(
                    {
                        "control_index": control_index,
                        "distance_m": round(current_distance, 2),
                        "longitude": round(float(longitude), 7),
                        "latitude": round(float(latitude), 7),
                        "is_route_point": False,
                        "route_point_index": None,
                        "required_clearance_m": round(prev_required + (curr_required - prev_required) * ratio, 2),
                    }
                )
                control_index += 1

        controls.append(
            {
                "control_index": control_index,
                "distance_m": round(end_distance, 2),
                "longitude": round(float(curr["longitude"]), 7),
                "latitude": round(float(curr["latitude"]), 7),
                "is_route_point": True,
                "route_point_index": int(curr["index"]),
                "required_clearance_m": round(curr_required, 2),
            }
        )
        control_index += 1
    return controls


def _fill_missing_elevations(values: list[float | None]) -> list[float | None]:
    if not values:
        return []
    resolved = list(values)
    known_indexes = [index for index, value in enumerate(resolved) if value is not None]
    if not known_indexes:
        return resolved

    first_known = known_indexes[0]
    for index in range(0, first_known):
        resolved[index] = resolved[first_known]

    for pair_index in range(1, len(known_indexes)):
        left_index = known_indexes[pair_index - 1]
        right_index = known_indexes[pair_index]
        left_value = float(resolved[left_index])  # type: ignore[arg-type]
        right_value = float(resolved[right_index])  # type: ignore[arg-type]
        gap = right_index - left_index
        if gap <= 1:
            continue
        for offset in range(1, gap):
            ratio = offset / gap
            resolved[left_index + offset] = round(left_value + (right_value - left_value) * ratio, 2)

    last_known = known_indexes[-1]
    for index in range(last_known + 1, len(resolved)):
        resolved[index] = resolved[last_known]
    return [round(float(item), 2) if item is not None else None for item in resolved]


def _distance_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def _unit_vector(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float] | None:
    length = _distance_between(a, b)
    if length <= TURN_EPSILON:
        return None
    return ((float(b[0]) - float(a[0])) / length, (float(b[1]) - float(a[1])) / length)


def _dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1])


def _cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(a[0]) * float(b[1]) - float(a[1]) * float(b[0])


def _offset_point(point: tuple[float, float], vector: tuple[float, float], scale: float) -> tuple[float, float]:
    return (float(point[0]) + float(vector[0]) * scale, float(point[1]) + float(vector[1]) * scale)


def _left_normal(vector: tuple[float, float]) -> tuple[float, float]:
    return (-float(vector[1]), float(vector[0]))


def _round_wgs84_point(to_wgs84, local_point: tuple[float, float]) -> tuple[float, float]:
    longitude, latitude = to_wgs84(float(local_point[0]), float(local_point[1]))
    return (round(float(longitude), 7), round(float(latitude), 7))


def _arc_warning(
    point: dict[str, Any] | None,
    sequence: int | None,
    code: str,
    message: str,
    radius: float,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "requested_radius_m": round(float(radius), 2),
    }
    if point:
        payload.update(
            {
                "point_id": point.get("id"),
                "point_name": point.get("name"),
                "point_type": point.get("point_type"),
                "point_index": sequence,
                "longitude": round(float(point["longitude"]), 7),
                "latitude": round(float(point["latitude"]), 7),
            }
        )
    return payload


def _build_arc_points(
    center: tuple[float, float],
    radius: float,
    start_angle: float,
    end_angle: float,
    *,
    ccw: bool,
) -> list[tuple[float, float]]:
    sweep = end_angle - start_angle
    if ccw:
        while sweep <= 0:
            sweep += 2 * math.pi
    else:
        while sweep >= 0:
            sweep -= 2 * math.pi
    sweep_abs = abs(sweep)
    if sweep_abs <= TURN_EPSILON:
        return [
            _offset_point(center, (math.cos(start_angle), math.sin(start_angle)), radius),
            _offset_point(center, (math.cos(end_angle), math.sin(end_angle)), radius),
        ]
    segment_count = max(2, min(180, int(math.ceil(max(sweep_abs / (math.pi / 18), (radius * sweep_abs) / 20.0)))))
    points: list[tuple[float, float]] = []
    for index in range(segment_count + 1):
        ratio = index / segment_count
        angle = start_angle + sweep * ratio
        points.append(_offset_point(center, (math.cos(angle), math.sin(angle)), radius))
    return points


def _dedupe_coords(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    deduped: list[tuple[float, float]] = []
    for coord in coords:
        if deduped and _distance_between(deduped[-1], coord) <= TURN_EPSILON:
            continue
        deduped.append((float(coord[0]), float(coord[1])))
    return deduped


def _build_centerline_with_turn_mode(
    local_points: list[tuple[float, float]],
    points: list[dict[str, Any]],
    route: dict[str, Any],
) -> tuple[LineString, dict[str, Any]]:
    raw_line = LineString(local_points)
    turn_mode = str(route.get("turn_mode") or "angle")
    radius = float(route.get("min_turn_radius") or 0.0)

    if turn_mode != "arc":
        return raw_line, {"mode": "angle", "warnings": [], "segments": []}

    warnings: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    if radius <= 0:
        warnings.append(
            _arc_warning(
                None,
                None,
                "non_positive_radius",
                "协调转弯型的最小转弯半径小于等于 0，已按定点转弯型生成。",
                radius,
            )
        )
        for index in range(1, max(1, len(points) - 1)):
            point = points[index]
            segments.append(
                {
                    "point_id": point.get("id"),
                    "point_index": index + 1,
                    "status": "angle",
                    "reason": "non_positive_radius",
                }
            )
        return raw_line, {"mode": "arc", "warnings": warnings, "segments": segments}

    coords: list[tuple[float, float]] = [local_points[0]]
    previous_outgoing_trim = 0.0

    for index in range(1, len(local_points) - 1):
        prev_point = local_points[index - 1]
        vertex = local_points[index]
        next_point = local_points[index + 1]
        point_meta = points[index]
        point_index = index + 1
        prev_length = _distance_between(prev_point, vertex)
        next_length = _distance_between(vertex, next_point)
        incoming = _unit_vector(prev_point, vertex)
        outgoing = _unit_vector(vertex, next_point)
        segment_record: dict[str, Any] = {
            "point_id": point_meta.get("id"),
            "point_index": point_index,
            "requested_radius_m": round(radius, 2),
            "status": "angle",
        }

        if incoming is None or outgoing is None:
            segment_record["reason"] = "zero_length_segment"
            warnings.append(
                _arc_warning(point_meta, point_index, "zero_length_segment", "折点前后存在零长度线段，已退化为折角。", radius)
            )
            coords.append(vertex)
            previous_outgoing_trim = 0.0
            segments.append(segment_record)
            continue

        deflection = math.acos(max(-1.0, min(1.0, _dot(incoming, outgoing))))
        turn_sign = _cross(incoming, outgoing)
        if abs(turn_sign) <= TURN_EPSILON or deflection <= 1e-4:
            segment_record["status"] = "straight"
            segment_record["reason"] = "collinear"
            coords.append(vertex)
            previous_outgoing_trim = 0.0
            segments.append(segment_record)
            continue
        if abs(math.pi - deflection) <= 1e-4:
            segment_record["reason"] = "u_turn"
            warnings.append(
                _arc_warning(point_meta, point_index, "u_turn", "折点接近 180° 掉头，已退化为折角。", radius)
            )
            coords.append(vertex)
            previous_outgoing_trim = 0.0
            segments.append(segment_record)
            continue

        tangent_distance = radius * math.tan(deflection / 2.0)
        segment_record["tangent_distance_m"] = round(float(tangent_distance), 2)
        if tangent_distance <= TURN_EPSILON:
            segment_record["status"] = "straight"
            segment_record["reason"] = "tiny_turn"
            coords.append(vertex)
            previous_outgoing_trim = 0.0
            segments.append(segment_record)
            continue
        if tangent_distance >= prev_length - TURN_EPSILON:
            segment_record["reason"] = "prev_segment_too_short"
            warnings.append(
                _arc_warning(
                    point_meta,
                    point_index,
                    "prev_segment_too_short",
                    "折点前一段长度不足以满足当前最小转弯半径，已退化为折角。",
                    radius,
                )
            )
            coords.append(vertex)
            previous_outgoing_trim = 0.0
            segments.append(segment_record)
            continue
        if tangent_distance >= next_length - TURN_EPSILON:
            segment_record["reason"] = "next_segment_too_short"
            warnings.append(
                _arc_warning(
                    point_meta,
                    point_index,
                    "next_segment_too_short",
                    "折点后一段长度不足以满足当前最小转弯半径，已退化为折角。",
                    radius,
                )
            )
            coords.append(vertex)
            previous_outgoing_trim = 0.0
            segments.append(segment_record)
            continue
        if previous_outgoing_trim + tangent_distance >= prev_length - TURN_EPSILON:
            segment_record["reason"] = "adjacent_arc_overlap"
            warnings.append(
                _arc_warning(
                    point_meta,
                    point_index,
                    "adjacent_arc_overlap",
                    "相邻折点过密，圆弧在共享线段上发生重叠，当前折点已退化为折角。",
                    radius,
                )
            )
            coords.append(vertex)
            previous_outgoing_trim = 0.0
            segments.append(segment_record)
            continue

        tangent_in = _offset_point(vertex, incoming, -tangent_distance)
        tangent_out = _offset_point(vertex, outgoing, tangent_distance)
        normal = _left_normal(incoming)
        if turn_sign < 0:
            normal = (-normal[0], -normal[1])
        center = _offset_point(tangent_in, normal, radius)
        tangent_out_radius = _distance_between(center, tangent_out)
        if abs(tangent_out_radius - radius) > 0.5:
            segment_record["reason"] = "invalid_arc_geometry"
            warnings.append(
                _arc_warning(point_meta, point_index, "invalid_arc_geometry", "折点圆弧几何求解失败，已退化为折角。", radius)
            )
            coords.append(vertex)
            previous_outgoing_trim = 0.0
            segments.append(segment_record)
            continue

        start_angle = math.atan2(tangent_in[1] - center[1], tangent_in[0] - center[0])
        end_angle = math.atan2(tangent_out[1] - center[1], tangent_out[0] - center[0])
        arc_points = _build_arc_points(center, radius, start_angle, end_angle, ccw=turn_sign > 0)
        coords.append(tangent_in)
        coords.extend(arc_points[1:])
        previous_outgoing_trim = tangent_distance
        segment_record.update(
            {
                "status": "arc",
                "reason": None,
                "turn_direction": "left" if turn_sign > 0 else "right",
            }
        )
        segments.append(segment_record)

    coords.append(local_points[-1])
    centerline_local = LineString(_dedupe_coords(coords))
    return centerline_local, {"mode": "arc", "warnings": warnings, "segments": segments}


def _apply_agl_altitude_constraints(
    terrain_values: list[float | None],
    required_clearances: list[float],
    min_change: float,
) -> list[float | None]:
    threshold = max(0.0, float(min_change))
    target_altitudes: list[float | None] = []
    for index, terrain in enumerate(terrain_values):
        if terrain is None:
            target_altitudes.append(None)
            continue
        required = float(required_clearances[index]) if index < len(required_clearances) else 0.0
        target_altitudes.append(round(float(terrain) + required, 2))

    smoothed_targets = _apply_min_change_smoothing(target_altitudes, threshold)
    resolved_altitudes: list[float | None] = []
    prev_altitude: float | None = None

    for index, terrain in enumerate(terrain_values):
        required = float(required_clearances[index]) if index < len(required_clearances) else 0.0
        min_altitude = None if terrain is None else float(terrain) + required
        altitude = smoothed_targets[index]

        if min_altitude is None:
            if altitude is None and prev_altitude is not None:
                altitude = prev_altitude
        else:
            if altitude is None:
                altitude = prev_altitude if prev_altitude is not None else min_altitude
            altitude = max(float(altitude), float(min_altitude))

        if altitude is not None:
            altitude = round(float(altitude), 2)
            prev_altitude = altitude
        resolved_altitudes.append(altitude)
    return resolved_altitudes


def _build_clearance_check(
    control_points: list[dict[str, Any]],
    *,
    route_bottom: float,
) -> dict[str, Any]:
    checked_count = 0
    unknown_count = 0
    min_clearance: float | None = None
    violations: list[dict[str, Any]] = []

    for point in control_points:
        terrain = point.get("terrain_elevation_m")
        altitude = point.get("altitude_m")
        required = max(float(route_bottom), float(point.get("required_clearance_m", route_bottom)))
        if terrain is None or altitude is None:
            unknown_count += 1
            continue
        clearance = float(altitude) - float(terrain)
        point["clearance_m"] = round(clearance, 2)
        checked_count += 1
        if min_clearance is None or clearance < min_clearance:
            min_clearance = clearance
        if clearance + 1e-6 < required:
            if len(violations) < 50:
                violations.append(
                    {
                        "control_index": point.get("control_index"),
                        "distance_m": point.get("distance_m"),
                        "required_clearance_m": round(required, 2),
                        "actual_clearance_m": round(clearance, 2),
                    }
                )

    return {
        "all_passed": len(violations) == 0 and checked_count > 0,
        "required_bottom_clearance_m": round(float(route_bottom), 2),
        "checked_count": checked_count,
        "unknown_count": unknown_count,
        "violation_count": len(violations),
        "min_clearance_m": round(min_clearance, 2) if min_clearance is not None else None,
        "violations": violations,
    }

def _build_profile(
    route_id: int,
    points: list[dict[str, Any]],
    route: dict[str, Any],
    sub_routes: list[dict[str, Any]],
    *,
    local_points: list[tuple[float, float]],
    centerline_local: LineString,
    to_wgs84,
) -> dict[str, Any]:
    if len(points) < 2:
        return {"distance_total": 0.0, "points": [], "layers": sub_routes}
    total_distance = float(centerline_local.length)
    profile_points: list[dict[str, Any]] = []
    route_point_samples: list[dict[str, Any]] = []
    for index, point in enumerate(points):
        if index == 0:
            distance_value = 0.0
            projected_local = local_points[index]
        elif index == len(points) - 1:
            distance_value = total_distance
            projected_local = local_points[index]
        else:
            distance_value = float(centerline_local.project(Point(local_points[index])))
            projected_local_geom = centerline_local.interpolate(distance_value)
            projected_local = (float(projected_local_geom.x), float(projected_local_geom.y))
        longitude, latitude = _round_wgs84_point(to_wgs84, projected_local)
        altitude = float(point.get("altitude", route["bottom_height"]))
        profile_points.append(
            {
                "index": index + 1,
                "name": point["name"],
                "point_type": point["point_type"],
                "distance_m": round(distance_value, 2),
                "altitude_m": round(altitude, 2),
                "longitude": longitude,
                "latitude": latitude,
            }
        )
        route_point_samples.append(
            {
                "index": index + 1,
                "distance_m": round(distance_value, 2),
                "longitude": longitude,
                "latitude": latitude,
                "height_offset_m": round(altitude, 2),
            }
        )

    altitude_mode = str(route.get("altitude_reference_mode") or "asl")
    altitude_source = "point_altitude"
    route_bottom = float(route["bottom_height"])
    min_change = float(route.get("altitude_change_min", 10))
    terrain_points: list[dict[str, Any]] = []
    altitude_profile_points: list[dict[str, Any]] = []
    clearance_check: dict[str, Any] | None = None
    control_step = None
    if altitude_mode == "agl":
        control_step = _select_profile_control_step(total_distance)
        control_points = _build_agl_control_samples(
            route_point_samples,
            centerline_local=centerline_local,
            to_wgs84=to_wgs84,
            route_bottom=route_bottom,
            step_m=control_step,
        )
        control_distances = [float(sample["distance_m"]) for sample in control_points]
        terrain_values = _lookup_cached_terrain_for_distances(route_id, control_distances)
        source_hint = "cached_route_geo_terrain"
        valid_count = sum(1 for value in terrain_values if value is not None)
        if valid_count == 0:
            fetch_samples = [
                {
                    "index": idx + 1,
                    "distance_m": sample["distance_m"],
                    "longitude": sample["longitude"],
                    "latitude": sample["latitude"],
                }
                for idx, sample in enumerate(control_points)
            ]
            terrain_values, source_hint = _fetch_multi_source_elevations(fetch_samples)
        terrain_values = _fill_missing_elevations(terrain_values)
        required_clearances = [float(sample["required_clearance_m"]) for sample in control_points]
        control_altitudes = _apply_agl_altitude_constraints(terrain_values, required_clearances, min_change)
        route_point_lookup: dict[int, dict[str, Any]] = {}

        for idx, control_point in enumerate(control_points):
            terrain_elevation = terrain_values[idx] if idx < len(terrain_values) else None
            required_clearance = required_clearances[idx] if idx < len(required_clearances) else route_bottom
            altitude_value = control_altitudes[idx] if idx < len(control_altitudes) else None
            clearance_value = None
            if terrain_elevation is not None and altitude_value is not None:
                clearance_value = round(float(altitude_value) - float(terrain_elevation), 2)
            terrain_points.append(
                {
                    "index": control_point["control_index"],
                    "distance_m": control_point["distance_m"],
                    "longitude": control_point["longitude"],
                    "latitude": control_point["latitude"],
                    "elevation_m": round(float(terrain_elevation), 2) if terrain_elevation is not None else None,
                    "altitude_m": round(float(altitude_value), 2) if altitude_value is not None else None,
                    "required_clearance_m": round(float(required_clearance), 2),
                    "clearance_m": clearance_value,
                    "is_route_point": bool(control_point["is_route_point"]),
                    "route_point_index": control_point["route_point_index"],
                }
            )
            altitude_profile_points.append(
                {
                    "index": control_point["control_index"],
                    "distance_m": control_point["distance_m"],
                    "longitude": control_point["longitude"],
                    "latitude": control_point["latitude"],
                    "altitude_m": round(float(altitude_value), 2) if altitude_value is not None else None,
                    "terrain_elevation_m": round(float(terrain_elevation), 2) if terrain_elevation is not None else None,
                    "required_clearance_m": round(float(required_clearance), 2),
                    "clearance_m": clearance_value,
                    "is_route_point": bool(control_point["is_route_point"]),
                    "route_point_index": control_point["route_point_index"],
                }
            )
            if control_point["is_route_point"] and control_point["route_point_index"] is not None:
                route_point_lookup[int(control_point["route_point_index"])] = {
                    "altitude_m": round(float(altitude_value), 2) if altitude_value is not None else None,
                    "terrain_elevation_m": round(float(terrain_elevation), 2) if terrain_elevation is not None else None,
                    "height_offset_m": round(float(required_clearance), 2),
                    "required_clearance_m": round(float(required_clearance), 2),
                    "clearance_m": clearance_value,
                }

        for profile_point in profile_points:
            lookup = route_point_lookup.get(int(profile_point["index"]))
            if lookup:
                if lookup["altitude_m"] is not None:
                    profile_point["altitude_m"] = lookup["altitude_m"]
                profile_point["terrain_elevation_m"] = lookup["terrain_elevation_m"]
                profile_point["height_offset_m"] = lookup["height_offset_m"]
                profile_point["required_clearance_m"] = lookup["required_clearance_m"]
                profile_point["clearance_m"] = lookup["clearance_m"]
            else:
                profile_point["terrain_elevation_m"] = None
                profile_point["height_offset_m"] = round(route_bottom, 2)
                profile_point["required_clearance_m"] = round(route_bottom, 2)
                profile_point["clearance_m"] = None

        clearance_check = _build_clearance_check(
            [
                {
                    "control_index": item["index"],
                    "distance_m": item["distance_m"],
                    "terrain_elevation_m": item["elevation_m"],
                    "altitude_m": item["altitude_m"],
                    "required_clearance_m": item["required_clearance_m"],
                }
                for item in terrain_points
            ],
            route_bottom=route_bottom,
        )
        altitude_source = source_hint
        altitude_profile_points.sort(key=lambda item: (float(item["distance_m"]), int(item.get("index", 0))))
    else:
        altitude_profile_points = [
            {
                "index": int(sample["index"]),
                "distance_m": round(float(sample["distance_m"]), 2),
                "longitude": round(float(sample["longitude"]), 7),
                "latitude": round(float(sample["latitude"]), 7),
                "altitude_m": round(float(sample["height_offset_m"]), 2),
                "is_route_point": True,
                "route_point_index": int(sample["index"]),
            }
            for sample in route_point_samples
        ]

    return {
        "distance_total": round(total_distance, 2),
        "points": profile_points,
        "altitude_profile_points": altitude_profile_points,
        "terrain_points": terrain_points,
        "altitude_reference_mode": altitude_mode,
        "altitude_change_min": min_change,
        "altitude_source": altitude_source,
        "control_step_m": round(float(control_step), 2) if control_step is not None else None,
        "clearance_check": clearance_check,
        "layers": [
            {
                "sequence": layer["sequence"],
                "name": layer["name"],
                "bottom_height": layer["bottom_height"],
                "top_height": layer["top_height"],
            }
            for layer in sub_routes
        ],
        "route_bottom": float(route["bottom_height"]),
        "route_top": float(route["top_height"]),
    }


def validate_route_metadata(route: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not route:
        return ["route not found"]
    if not str(route.get("name", "")).strip():
        errors.append("航路名称不能为空")
    flight_width = float(route.get("flight_width", 0))
    protection_width = float(route.get("protection_width", 0))
    bottom_height = float(route.get("bottom_height", 0))
    top_height = float(route.get("top_height", 0))
    altitude_mode = str(route.get("altitude_reference_mode") or "asl")
    altitude_change_min = float(route.get("altitude_change_min", 10))
    if not (30 <= flight_width <= 50):
        errors.append("飞行区宽度应在30-50米之间")
    if not (50 <= protection_width <= 200):
        errors.append("保护区宽度应在50-200米之间")
    if top_height <= bottom_height:
        errors.append("顶部高度必须大于底部高度")
    if altitude_mode not in {"asl", "agl"}:
        errors.append("高度参考模式只支持 asl 或 agl")
    if altitude_change_min < 0 or altitude_change_min > 500:
        errors.append("高度变化最小值应在0-500米之间")
    if route.get("enable_layering"):
        if top_height > MAX_LAYER_HEIGHT:
            errors.append("启用分层时，顶部高度不能超过300米")
        if bottom_height >= MAX_LAYER_HEIGHT:
            errors.append("启用分层时，底部高度必须小于300米")
        try:
            scheme = _parse_layer_scheme(str(route.get("layer_scheme") or DEFAULT_LAYER_SCHEME))
        except ValueError as exc:
            errors.append(f"分层方案错误: {exc}")
            scheme = []
        for low, high in scheme:
            if low < 0 or high > MAX_LAYER_HEIGHT:
                errors.append("分层区间必须在0-300米内")
        for index in range(1, len(scheme)):
            prev = scheme[index - 1]
            current = scheme[index]
            if current[0] < prev[1]:
                errors.append("分层区间不能重叠")
                break
    return errors


def validate_route(route: dict[str, Any], points: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if not route:
        return ["route not found"]
    errors.extend(validate_route_metadata(route))
    if len(points) < 2:
        errors.append("航路至少需要2个航路点")
    if not any(p["point_type"] == "start" for p in points):
        errors.append("必须设置起点")
    if not any(p["point_type"] == "end" for p in points):
        errors.append("必须设置终点")
    if sum(1 for p in points if p["point_type"] == "start") > 1:
        errors.append("起点只能设置一个")
    if sum(1 for p in points if p["point_type"] == "end") > 1:
        errors.append("终点只能设置一个")
    if points and points[0]["point_type"] != "start":
        errors.append("第1个点必须是起点")
    if points and points[-1]["point_type"] != "end":
        errors.append("最后1个点必须是终点")
    return errors


def generate_route_geometry(route_id: int, *, persist_full_state: bool = True) -> dict[str, Any]:
    route = get_route(route_id)
    points = get_points(route_id)
    landing_sites = get_landing_sites(route_id)
    try:
        sub_routes_for_check = _build_altitude_sub_routes(route) if route else []
    except ValueError:
        sub_routes_for_check = []
    precheck_completeness = _evaluate_route_completeness(
        route,
        points,
        sub_routes_for_check,
        has_flight_zone_geometry=False,
        has_protection_zone_geometry=False,
    )
    errors = validate_route(route, points)
    if errors:
        return {"ok": False, "errors": errors, "completeness": precheck_completeness}

    ref_lon, ref_lat = points[0]["longitude"], points[0]["latitude"]
    to_local, to_wgs84 = build_local_transformers(ref_lon, ref_lat)

    local_points = [to_local(p["longitude"], p["latitude"]) for p in points]
    centerline_local, turning = _build_centerline_with_turn_mode(local_points, points, route)
    centerline_wgs84 = transform(to_wgs84, centerline_local)

    flight_half = route["flight_width"] / 2.0
    protection_half = flight_half + route["protection_width"]
    flight_zone_wgs84 = transform(to_wgs84, centerline_local.buffer(flight_half))
    protection_zone_wgs84 = transform(to_wgs84, centerline_local.buffer(protection_half))

    landing_points_local = [Point(to_local(l["longitude"], l["latitude"])) for l in landing_sites]
    approach_lines_local = build_approach_lines(centerline_local, landing_points_local)
    approach_lines_wgs84 = [transform(to_wgs84, line) for line in approach_lines_local]

    centerline_geo = mapping(centerline_wgs84)
    flight_geo = mapping(flight_zone_wgs84)
    protection_geo = mapping(protection_zone_wgs84)
    approach_geos = [mapping(line) for line in approach_lines_wgs84]

    sub_routes = _build_altitude_sub_routes(route)
    profile = _build_profile(
        route_id,
        points,
        route,
        sub_routes,
        local_points=local_points,
        centerline_local=centerline_local,
        to_wgs84=to_wgs84,
    )
    sub_route_geometries = [
        {
            **sub_route,
            "centerline": centerline_geo,
            "flight_zone": flight_geo,
            "protection_zone": protection_geo,
            "approaches": approach_geos,
            "turning": turning,
        }
        for sub_route in sub_routes
    ]

    completeness = _evaluate_route_completeness(
        route,
        points,
        sub_routes,
        has_flight_zone_geometry=_has_flight_zone_geometry(flight_geo),
        has_protection_zone_geometry=_has_protection_zone_geometry(protection_geo),
    )

    payload = {
        "ok": True,
        "route": route,
        "points": points,
        "landing_sites": landing_sites,
        "layering": {
            "enabled": bool(route["enable_layering"]),
            "layer_scheme": route["layer_scheme"],
            "max_layer_height": MAX_LAYER_HEIGHT,
        },
        "sub_routes": sub_route_geometries,
        "profile": profile,
        "centerline": centerline_geo,
        "flight_zone": flight_geo,
        "protection_zone": protection_geo,
        "approaches": approach_geos,
        "turning": turning,
        "completeness": completeness,
        "storage": {"persisted": False},
    }
    if persist_full_state:
        _persist_route_full_state(route_id, payload, completeness)
        stored = get_route_full_state(route_id)
        payload["storage"] = {
            "persisted": True,
            "generated_at": stored["generated_at"] if stored else None,
            "updated_at": stored["updated_at"] if stored else None,
        }
    return payload


def _insert_route(
    *,
    name: str,
    route: dict[str, Any],
    bottom_height: float,
    top_height: float,
    enable_layering: bool,
) -> int:
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO routes (
                name, flight_width, protection_width, bottom_height, top_height,
                min_turn_radius, turn_mode, altitude_reference_mode, altitude_change_min,
                enable_layering, layer_step, layer_scheme
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                route["flight_width"],
                route["protection_width"],
                bottom_height,
                top_height,
                route["min_turn_radius"],
                route["turn_mode"],
                route.get("altitude_reference_mode", "asl"),
                route.get("altitude_change_min", 10),
                1 if enable_layering else 0,
                route.get("layer_step", 50),
                route.get("layer_scheme", DEFAULT_LAYER_SCHEME),
            ),
        )
        return int(cursor.lastrowid)


def _copy_points_and_landings(source_route_id: int, target_route_id: int) -> None:
    points = get_points(source_route_id)
    landings = get_landing_sites(source_route_id)
    with db_cursor() as cursor:
        for point in points:
            cursor.execute(
                """
                INSERT INTO route_points (route_id, name, point_type, longitude, latitude, altitude, order_index)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_route_id,
                    point["name"],
                    point["point_type"],
                    point["longitude"],
                    point["latitude"],
                    point["altitude"],
                    point["order_index"],
                ),
            )
        for landing in landings:
            cursor.execute(
                """
                INSERT INTO landing_sites (route_id, name, longitude, latitude, altitude)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    target_route_id,
                    landing["name"],
                    landing["longitude"],
                    landing["latitude"],
                    landing["altitude"],
                ),
            )


def duplicate_route(route_id: int, name: str | None = None) -> dict[str, Any]:
    route = get_route(route_id)
    if not route:
        raise ValueError("Route not found")
    new_name = name or f"{route['name']}_copy"
    new_route_id = _insert_route(
        name=new_name,
        route=route,
        bottom_height=float(route["bottom_height"]),
        top_height=float(route["top_height"]),
        enable_layering=bool(route["enable_layering"]),
    )
    _copy_points_and_landings(route_id, new_route_id)
    return get_route(new_route_id)


def extract_sub_route_as_new_route(route_id: int, sequence: int, name: str | None = None) -> dict[str, Any]:
    generated = generate_route_geometry(route_id)
    if not generated["ok"]:
        raise ValueError("; ".join(generated["errors"]))
    selected = next((s for s in generated["sub_routes"] if int(s["sequence"]) == int(sequence)), None)
    if not selected:
        raise ValueError("Sub route not found")

    base_route = generated["route"]
    new_name = name or f"{base_route['name']}_layer_{sequence}"
    new_route_id = _insert_route(
        name=new_name,
        route=base_route,
        bottom_height=float(selected["bottom_height"]),
        top_height=float(selected["top_height"]),
        enable_layering=False,
    )
    _copy_points_and_landings(route_id, new_route_id)
    return get_route(new_route_id)
