from __future__ import annotations

import json
import math
from typing import Any

from fastapi import HTTPException
from shapely.geometry import LineString, Point, shape

from app.database_route import db_cursor
from app.services.coordinate_service import build_local_transformers
from app.services.route_service import (
    _fetch_multi_source_elevations,
    _lookup_cached_terrain_for_distances,
    generate_route_geometry,
    get_landing_sites,
    get_route,
    get_route_full_state,
)


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_load(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _landing_by_id(route_id: int, landing_id: int) -> dict[str, Any]:
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM landing_sites WHERE id=? AND route_id=?", (landing_id, route_id))
        row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="起降场不存在")
    return dict(row)


def _route_snapshot(route_id: int) -> dict[str, Any]:
    full_state = get_route_full_state(route_id)
    snapshot = full_state.get("snapshot") if full_state else None
    if isinstance(snapshot, dict) and snapshot.get("centerline"):
        return snapshot
    generated = generate_route_geometry(route_id)
    if not generated.get("ok"):
        raise HTTPException(status_code=400, detail=generated.get("errors") or ["航路尚未生成"])
    return generated


def _profile_points(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    profile = snapshot.get("profile") if isinstance(snapshot.get("profile"), dict) else {}
    points = profile.get("altitude_profile_points") or profile.get("points") or []
    return [dict(item) for item in points if isinstance(item, dict)]


def _point_distance(item: dict[str, Any]) -> float | None:
    value = item.get("distance_m", item.get("distance"))
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _point_value(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        try:
            value = item.get(key)
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _interpolate_profile_value(points: list[dict[str, Any]], distance_m: float, *keys: str) -> float | None:
    samples = sorted(
        [(dist, item) for item in points if (dist := _point_distance(item)) is not None],
        key=lambda item: item[0],
    )
    if not samples:
        return None
    if distance_m <= samples[0][0]:
        return _point_value(samples[0][1], *keys)
    if distance_m >= samples[-1][0]:
        return _point_value(samples[-1][1], *keys)
    for index in range(1, len(samples)):
        left_dist, left = samples[index - 1]
        right_dist, right = samples[index]
        if left_dist <= distance_m <= right_dist:
            left_value = _point_value(left, *keys)
            right_value = _point_value(right, *keys)
            if left_value is None:
                return right_value
            if right_value is None:
                return left_value
            ratio = (distance_m - left_dist) / (right_dist - left_dist or 1.0)
            return round(left_value + (right_value - left_value) * ratio, 2)
    return None


def _terrain_summary(route_id: int) -> dict[str, Any]:
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT terrain_sample_count, terrain_record_count
            FROM route_geo_extractions
            WHERE route_id=?
            """,
            (route_id,),
        )
        row = cursor.fetchone()
    return dict(row) if row else {"terrain_sample_count": 0, "terrain_record_count": 0}


def _nearest_cloud_elevation(route_id: int, longitude: float, latitude: float, max_distance_m: float = 800.0) -> dict[str, Any] | None:
    route = get_route(route_id)
    if not route:
        return None
    to_local, _ = build_local_transformers(float(longitude), float(latitude))
    target = Point(to_local(longitude, latitude))
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT longitude, latitude, elevation_m, source_ref, source_distance_m
            FROM route_geo_terrain_cloud
            WHERE route_id=? AND elevation_m IS NOT NULL
            """,
            (route_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    best: tuple[float, dict[str, Any]] | None = None
    for row in rows:
        try:
            point = Point(to_local(float(row["longitude"]), float(row["latitude"])))
            distance = target.distance(point)
        except (TypeError, ValueError):
            continue
        if distance <= max_distance_m and (best is None or distance < best[0]):
            best = (distance, row)
    if not best:
        return None
    distance, row = best
    return {
        "altitude_m": round(float(row["elevation_m"]), 2),
        "source": "cached_route_geo_terrain_cloud",
        "confidence": "high" if distance <= 200 else "medium",
        "distance_m": round(distance, 1),
    }


def _fetch_point_elevation(longitude: float, latitude: float) -> dict[str, Any]:
    samples = [{"longitude": longitude, "latitude": latitude, "distance_m": 0}]
    values, source = _fetch_multi_source_elevations(samples)
    value = values[0] if values else None
    if value is None:
        raise HTTPException(status_code=502, detail=f"无法获取起降场高程：{source}")
    return {
        "altitude_m": round(float(value), 2),
        "source": source,
        "confidence": "medium",
        "distance_m": 0,
    }


def suggest_landing_elevation(route_id: int, landing_id: int) -> dict[str, Any]:
    landing = _landing_by_id(route_id, landing_id)
    cached = _nearest_cloud_elevation(route_id, float(landing["longitude"]), float(landing["latitude"]))
    suggestion = cached or _fetch_point_elevation(float(landing["longitude"]), float(landing["latitude"]))
    return {
        "route_id": route_id,
        "landing_id": landing_id,
        "landing_name": landing["name"],
        "suggested_altitude_m": suggestion["altitude_m"],
        "source": suggestion["source"],
        "confidence": suggestion["confidence"],
        "source_distance_m": suggestion.get("distance_m"),
        "message": "已按当前航路地形数据估算" if cached else "已通过在线高程服务估算",
    }


def _selected_target_layer(snapshot: dict[str, Any], sequence: int | None) -> dict[str, Any] | None:
    if sequence is None:
        return None
    for layer in snapshot.get("sub_routes") or []:
        if int(layer.get("sequence", -1)) == int(sequence):
            return {
                "sequence": int(layer["sequence"]),
                "name": layer.get("name") or f"Sub Route {sequence}",
                "bottom_height": float(layer["bottom_height"]),
                "top_height": float(layer["top_height"]),
            }
    raise HTTPException(status_code=400, detail=f"子航路层高 {sequence} 不存在")


def _route_altitude_window(
    route: dict[str, Any],
    profile_points: list[dict[str, Any]],
    route_id: int,
    distance_m: float,
    target_layer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    terrain = _interpolate_profile_value(profile_points, distance_m, "terrain_elevation_m", "elevation_m")
    if terrain is None:
        terrain_values = _lookup_cached_terrain_for_distances(route_id, [distance_m])
        terrain = terrain_values[0] if terrain_values else None

    mode = str(route.get("altitude_reference_mode") or "asl")
    low = float(target_layer["bottom_height"] if target_layer else route["bottom_height"])
    high = float(target_layer["top_height"] if target_layer else route["top_height"])
    if mode == "agl":
        base = float(terrain or 0)
        bottom = base + low
        top = base + high
    else:
        bottom = low
        top = high

    profile_altitude = None if target_layer else _interpolate_profile_value(profile_points, distance_m, "altitude_m")
    target = float(profile_altitude) if profile_altitude is not None else (bottom + top) / 2
    target = min(max(target, bottom), top)
    return {
        "bottom_altitude_m": round(bottom, 2),
        "top_altitude_m": round(top, 2),
        "target_altitude_m": round(target, 2),
        "terrain_elevation_m": round(float(terrain), 2) if terrain is not None else None,
        "altitude_reference_mode": mode,
        "target_layer_sequence": target_layer.get("sequence") if target_layer else None,
        "target_layer_name": target_layer.get("name") if target_layer else None,
    }


def _candidate_distances(line: LineString, landing_point: Point, max_attach_distance_m: float) -> list[tuple[float, float]]:
    projected = float(line.project(landing_point))
    length = float(line.length)
    step = max(80.0, min(250.0, length / 50.0 if length else 100.0))
    raw = {0.0, length, projected}
    for offset in range(0, int(max_attach_distance_m) + int(step), int(step)):
        raw.add(max(0.0, projected - offset))
        raw.add(min(length, projected + offset))
    candidates = [(distance, landing_point.distance(line.interpolate(distance))) for distance in raw]
    return sorted(candidates, key=lambda item: (item[1], abs(item[0] - projected)))


def _leg_status(reasons: list[str], warnings: list[str]) -> str:
    if reasons:
        return "fail"
    if warnings:
        return "warning"
    return "pass"


def _make_path_feature(kind: str, name: str, geometry: dict[str, Any], **props: Any) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"kind": kind, "name": name, **props},
        "geometry": geometry,
    }


def _param_number(params: dict[str, Any], key: str, default: float) -> float:
    try:
        value = float(params.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _param_bool(params: dict[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, default)
    if isinstance(value, str):
        return value.lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _unit(dx: float, dy: float, fallback: tuple[float, float] = (1.0, 0.0)) -> tuple[float, float]:
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return fallback
    return dx / length, dy / length


def _left(v: tuple[float, float]) -> tuple[float, float]:
    return -v[1], v[0]


def _right(v: tuple[float, float]) -> tuple[float, float]:
    return v[1], -v[0]


def _local_to_coord(point: Point, altitude_m: float, to_wgs84) -> list[float]:
    lon, lat = to_wgs84(point.x, point.y)
    return [round(lon, 8), round(lat, 8), round(altitude_m, 2)]


def _line_distance(points: list[Point]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(points[index].distance(points[index + 1]) for index in range(len(points) - 1))


def _points_to_coords(points: list[Point], start_alt: float, end_alt: float, to_wgs84) -> list[list[float]]:
    if not points:
        return []
    if len(points) == 1:
        return [_local_to_coord(points[0], end_alt, to_wgs84)]
    total = max(1.0, _line_distance(points))
    travelled = 0.0
    coords: list[list[float]] = []
    for index, point in enumerate(points):
        if index:
            travelled += points[index - 1].distance(point)
        ratio = min(1.0, max(0.0, travelled / total))
        coords.append(_local_to_coord(point, start_alt + (end_alt - start_alt) * ratio, to_wgs84))
    return coords


def _line_tangent(line: LineString, distance_m: float) -> tuple[float, float]:
    length = max(1.0, float(line.length))
    delta = min(25.0, max(1.0, length * 0.01))
    before = line.interpolate(max(0.0, distance_m - delta))
    after = line.interpolate(min(length, distance_m + delta))
    return _unit(after.x - before.x, after.y - before.y)


def _arc_points(
    center: Point,
    start: Point,
    end: Point,
    *,
    clockwise: bool,
    steps: int = 72,
) -> tuple[list[Point], float]:
    start_angle = math.atan2(start.y - center.y, start.x - center.x)
    end_angle = math.atan2(end.y - center.y, end.x - center.x)
    if clockwise:
        while end_angle > start_angle:
            end_angle -= math.tau
    else:
        while end_angle < start_angle:
            end_angle += math.tau
    sweep = end_angle - start_angle
    count = max(16, min(160, int(abs(sweep) / (math.pi / 90)) + 1, steps))
    points = [
        Point(
            center.x + math.cos(start_angle + sweep * index / count) * start.distance(center),
            center.y + math.sin(start_angle + sweep * index / count) * start.distance(center),
        )
        for index in range(count + 1)
    ]
    return points, abs(sweep) * start.distance(center)


def _circle_tangent_points(external: Point, center: Point, radius_m: float) -> list[Point]:
    dx = external.x - center.x
    dy = external.y - center.y
    distance = math.hypot(dx, dy)
    if distance <= radius_m + 1e-6:
        return []
    base_angle = math.atan2(dy, dx)
    offset = math.acos(max(-1.0, min(1.0, radius_m / distance)))
    return [
        Point(center.x + math.cos(base_angle + sign * offset) * radius_m, center.y + math.sin(base_angle + sign * offset) * radius_m)
        for sign in (-1, 1)
    ]


def _circle_tangent_at(center: Point, point: Point, *, clockwise: bool) -> tuple[float, float]:
    radius_vector = _unit(point.x - center.x, point.y - center.y)
    return _right(radius_vector) if clockwise else _left(radius_vector)


def _fixed_wing_arc_to_attach(
    *,
    landing: Point,
    attach: Point,
    inbound_tangent: tuple[float, float],
    route_tangent: tuple[float, float],
    radius_m: float,
) -> tuple[list[Point], float, list[str]]:
    warnings: list[str] = []
    options: list[tuple[float, list[Point], float]] = []
    for clockwise in (False, True):
        tangent_normal = _left(route_tangent) if clockwise else _right(route_tangent)
        center = Point(attach.x - tangent_normal[0] * radius_m, attach.y - tangent_normal[1] * radius_m)
        tangent_points = _circle_tangent_points(landing, center, radius_m)
        for start in tangent_points:
            straight_tangent = _unit(start.x - landing.x, start.y - landing.y)
            circle_tangent = _circle_tangent_at(center, start, clockwise=clockwise)
            if straight_tangent[0] * circle_tangent[0] + straight_tangent[1] * circle_tangent[1] < 0.15:
                continue
            points, length = _arc_points(center, start, attach, clockwise=clockwise)
            score = landing.distance(start) + length * 0.15
            options.append((score, points, length))
    if not options:
        warnings.append("固定翼接入点距离转弯圆心过近，无法构造严格外切圆弧")
        for clockwise in (False, True):
            tangent_normal = _left(route_tangent) if clockwise else _right(route_tangent)
            center = Point(attach.x - tangent_normal[0] * radius_m, attach.y - tangent_normal[1] * radius_m)
            start_normal = _left(inbound_tangent) if clockwise else _right(inbound_tangent)
            start = Point(center.x + start_normal[0] * radius_m, center.y + start_normal[1] * radius_m)
            points, length = _arc_points(center, start, attach, clockwise=clockwise)
            options.append((landing.distance(start) + length * 0.15, points, length))
    options.sort(key=lambda item: item[0])
    arc_points, arc_length = options[0][1], options[0][2]
    if landing.distance(arc_points[0]) < radius_m:
        warnings.append("固定翼接入直线段过短，圆弧旁切前稳定距离不足")
    return arc_points, arc_length, warnings


def _fixed_wing_arc_from_attach(
    *,
    landing: Point,
    attach: Point,
    route_tangent: tuple[float, float],
    outbound_tangent: tuple[float, float],
    radius_m: float,
) -> tuple[list[Point], float, list[str]]:
    warnings: list[str] = []
    options: list[tuple[float, list[Point], float]] = []
    for clockwise in (False, True):
        start_normal = _right(route_tangent) if not clockwise else _left(route_tangent)
        center = Point(attach.x - start_normal[0] * radius_m, attach.y - start_normal[1] * radius_m)
        tangent_points = _circle_tangent_points(landing, center, radius_m)
        for end in tangent_points:
            straight_tangent = _unit(landing.x - end.x, landing.y - end.y)
            circle_tangent = _circle_tangent_at(center, end, clockwise=clockwise)
            if straight_tangent[0] * circle_tangent[0] + straight_tangent[1] * circle_tangent[1] < 0.15:
                continue
            points, length = _arc_points(center, attach, end, clockwise=clockwise)
            score = landing.distance(end) + length * 0.15
            options.append((score, points, length))
    if not options:
        warnings.append("固定翼退出点距离转弯圆心过近，无法构造严格外切圆弧")
        for clockwise in (False, True):
            start_normal = _right(route_tangent) if not clockwise else _left(route_tangent)
            center = Point(attach.x - start_normal[0] * radius_m, attach.y - start_normal[1] * radius_m)
            end_normal = _right(outbound_tangent) if not clockwise else _left(outbound_tangent)
            end = Point(center.x + end_normal[0] * radius_m, center.y + end_normal[1] * radius_m)
            points, length = _arc_points(center, attach, end, clockwise=clockwise)
            options.append((landing.distance(end) + length * 0.15, points, length))
    options.sort(key=lambda item: item[0])
    arc_points, arc_length = options[0][1], options[0][2]
    if arc_points[-1].distance(landing) < radius_m:
        warnings.append("固定翼退出直线段过短，圆弧旁切后稳定距离不足")
    return arc_points, arc_length, warnings


def _circle_coords(center: Point, radius_m: float, altitude_m: float, to_wgs84, turns: float = 1.0) -> list[list[float]]:
    steps = max(24, min(160, int(48 * max(1.0, min(3.0, turns)))))
    coords = []
    for index in range(steps + 1):
        angle = math.tau * index / steps
        coords.append(_local_to_coord(Point(center.x + math.cos(angle) * radius_m, center.y + math.sin(angle) * radius_m), altitude_m, to_wgs84))
    return coords


def _fixed_wing_rule_metrics(params: dict[str, Any], phase: str) -> dict[str, float]:
    fte_h = _param_number(params, "fte_horizontal_m", 10)
    nse_h = _param_number(params, "nse_horizontal_m", 10)
    fte_v = _param_number(params, "fte_vertical_m", 5)
    nse_v = _param_number(params, "nse_vertical_m", 5)
    xtt = 2 * math.sqrt(fte_h * fte_h + nse_h * nse_h)
    vtt = 2 * math.sqrt(fte_v * fte_v + nse_v * nse_v)
    att = 0.8 * xtt

    g = 9.80665
    wingspan = _param_number(params, "wingspan_m", 18)
    speed = _param_number(params, "max_ground_speed_ms", 55)
    response = _param_number(params, "response_time_s", 3)
    roll = math.radians(max(1.0, min(88.0, _param_number(params, "max_roll_angle_deg", 25))))
    heading = math.radians(max(0.0, min(180.0, _param_number(params, "max_heading_deviation_deg", 30))))
    half_wfg = wingspan / 2 + xtt * 3
    turn_radius_by_roll = speed * speed / max(0.1, g * math.tan(roll))
    if _param_bool(params, "abnormal_area_enabled", True):
        if phase == "cruise":
            wcv = xtt + speed * response + turn_radius_by_roll
        else:
            wcv = xtt + speed * response * math.sin(heading) + turn_radius_by_roll * (1 - math.cos(heading))
    else:
        wcv = 0.0

    body_height = _param_number(params, "body_height_m", 6)
    half_hfg = body_height / 2 + vtt * 2
    if _param_bool(params, "abnormal_height_enabled", True):
        ham = _param_number(params, "altitude_measurement_error_m", 5)
        pitch_error = math.radians(max(0.0, min(45.0, _param_number(params, "pitch_deviation_deg", 5))))
        pitch_adjust = math.radians(max(0.0, min(60.0, _param_number(params, "max_pitch_adjust_deg", 15))))
        hcv = ham + speed * math.sin(pitch_error) * response + (speed * math.sin(pitch_adjust)) ** 2 / (2 * g)
    else:
        hcv = 0.0
    half_hp = half_hfg + hcv
    table_moc = 50.0 if phase == "departure" else 100.0
    recommended_moc = max(table_moc, math.ceil(half_hp + _param_number(params, "additional_moc_m", 0)))

    return {
        "xtt_m": round(xtt, 2),
        "att_m": round(att, 2),
        "vtt_m": round(vtt, 2),
        "protection_half_width_m": round(math.ceil(half_wfg + wcv), 2),
        "vertical_deviation_half_height_m": round(math.ceil(half_hp), 2),
        "recommended_moc_m": round(recommended_moc, 2),
        "computed_turn_radius_m": round(turn_radius_by_roll, 2),
    }


def _evaluate_leg(
    *,
    route_id: int,
    route: dict[str, Any],
    line: LineString,
    to_local,
    to_wgs84,
    profile_points: list[dict[str, Any]],
    landing: dict[str, Any],
    leg_type: str,
    params: dict[str, Any],
    target_layer: dict[str, Any] | None,
    aircraft_platform: str,
) -> dict[str, Any]:
    landing_local = Point(to_local(float(landing["longitude"]), float(landing["latitude"])))
    speed_ms = max(0.1, float(params["cruise_speed_kmh"]) / 3.6)
    candidates = _candidate_distances(line, landing_local, float(params["max_attach_distance_m"]))
    best: dict[str, Any] | None = None

    for distance_m, horizontal_m in candidates:
        route_window = _route_altitude_window(route, profile_points, route_id, distance_m, target_layer)
        target_alt = float(route_window["target_altitude_m"])
        landing_alt = float(landing.get("altitude") or 0)
        horizontal_distance = max(1.0, float(horizontal_m))
        horizontal_time_s = horizontal_distance / speed_ms

        if leg_type == "entry":
            vertical_needed = max(0.0, target_alt - landing_alt)
            vertical_rate = float(params["max_climb_rate_ms"])
            vertical_label = "爬升率不足"
        elif target_alt >= landing_alt:
            vertical_needed = target_alt - landing_alt
            vertical_rate = float(params["max_descent_rate_ms"])
            vertical_label = "下降率不足"
        else:
            vertical_needed = landing_alt - target_alt
            vertical_rate = float(params["max_climb_rate_ms"])
            vertical_label = "退出主航路后爬升率不足"

        min_turn_radius = float(params["min_turn_radius_m"])
        loiter_time_s = 0.0
        loiter_distance_m = 0.0
        loiter_turns = 0.0
        if aircraft_platform == "vtol":
            vertical_method = "vertical_takeoff_landing"
            vertical_capacity = vertical_needed
        elif aircraft_platform == "fixed_wing":
            vertical_method = "circular_loiter"
            if vertical_needed > 0 and min_turn_radius <= 0:
                vertical_capacity = 0.0
            else:
                loiter_time_s = vertical_needed / max(0.1, vertical_rate)
                loiter_distance_m = speed_ms * loiter_time_s
                circumference = max(1.0, 2 * math.pi * max(1.0, min_turn_radius))
                loiter_turns = loiter_distance_m / circumference
                vertical_capacity = vertical_rate * loiter_time_s
        else:
            vertical_method = "straight_segment"
            vertical_capacity = vertical_rate * horizontal_time_s

        leg_distance = horizontal_distance + loiter_distance_m
        time_s = horizontal_time_s + loiter_time_s

        reasons: list[str] = []
        warnings: list[str] = []
        if horizontal_distance > float(params["max_attach_distance_m"]):
            reasons.append("接入距离超过上限")
        if aircraft_platform == "fixed_wing" and vertical_needed > 0 and min_turn_radius <= 0:
            reasons.append("固定翼盘旋半径必须大于0")
        if aircraft_platform not in {"vtol", "fixed_wing"} and vertical_needed > vertical_capacity + 0.1:
            reasons.append(vertical_label)
        if aircraft_platform != "vtol" and horizontal_distance < min_turn_radius * 2:
            warnings.append("接入段过短，可能不满足最小转弯半径")
        if abs(target_alt - landing_alt) < float(params["min_clearance_m"]):
            warnings.append("起降场至主航路高度裕度偏低")
        if target_alt - float(params["vertical_deviation_m"]) < float(route_window["bottom_altitude_m"]):
            warnings.append("垂直偏航下边界接近或低于航路高度下限")
        if target_alt + float(params["vertical_deviation_m"]) > float(route_window["top_altitude_m"]):
            warnings.append("垂直偏航上边界接近或高于航路高度上限")

        score = len(reasons) * 100000 + len(warnings) * 1000 + leg_distance + abs(distance_m - line.project(landing_local)) * 0.15
        attach_local = line.interpolate(distance_m)
        attach_lon, attach_lat = to_wgs84(attach_local.x, attach_local.y)
        landing_lon, landing_lat = float(landing["longitude"]), float(landing["latitude"])
        ratio = min(1.0, max(0.0, float(params["waiting_height_agl_m"]) / max(1.0, abs(target_alt - landing_alt) or 1.0)))
        wait_ratio = min(0.35, max(0.15, ratio))
        wait_x = landing_local.x + (attach_local.x - landing_local.x) * wait_ratio
        wait_y = landing_local.y + (attach_local.y - landing_local.y) * wait_ratio
        wait_lon, wait_lat = to_wgs84(wait_x, wait_y)
        wait_alt = landing_alt + float(params["waiting_height_agl_m"])
        path_coords = [
            [landing_lon, landing_lat, round(landing_alt, 2)],
            [round(wait_lon, 8), round(wait_lat, 8), round(wait_alt, 2)],
            [round(attach_lon, 8), round(attach_lat, 8), round(target_alt, 2)],
        ]
        if leg_type == "exit":
            path_coords = list(reversed(path_coords))
        item = {
            "leg_type": leg_type,
            "status": _leg_status(reasons, warnings),
            "reasons": reasons,
            "warnings": warnings,
            "landing": landing,
            "attach_distance_m": round(distance_m, 2),
            "horizontal_distance_m": round(horizontal_distance, 2),
            "total_distance_m": round(leg_distance, 2),
            "estimated_time_s": round(time_s, 1),
            "horizontal_time_s": round(horizontal_time_s, 1),
            "vertical_needed_m": round(vertical_needed, 2),
            "vertical_capacity_m": round(vertical_capacity, 2),
            "vertical_method": vertical_method,
            "loiter_distance_m": round(loiter_distance_m, 2),
            "loiter_time_s": round(loiter_time_s, 1),
            "loiter_turns": round(loiter_turns, 2),
            "route_altitude": route_window,
            "attach_point": {"longitude": round(attach_lon, 8), "latitude": round(attach_lat, 8), "altitude_m": round(target_alt, 2)},
            "waiting_point": {"longitude": round(wait_lon, 8), "latitude": round(wait_lat, 8), "altitude_m": round(wait_alt, 2)},
            "path_coordinates": path_coords,
            "_score": score,
        }
        if best is None or item["_score"] < best["_score"]:
            best = item
        if not reasons:
            break

    assert best is not None
    best.pop("_score", None)
    return best


def _evaluate_leg_v2(
    *,
    route_id: int,
    route: dict[str, Any],
    line: LineString,
    to_local,
    to_wgs84,
    profile_points: list[dict[str, Any]],
    landing: dict[str, Any],
    leg_type: str,
    params: dict[str, Any],
    target_layer: dict[str, Any] | None,
    aircraft_platform: str,
    manual_attach_point: dict[str, Any] | None = None,
) -> dict[str, Any]:
    landing_local = Point(to_local(float(landing["longitude"]), float(landing["latitude"])))
    speed_ms = max(0.1, _param_number(params, "cruise_speed_kmh", 54) / 3.6)
    max_attach_distance = _param_number(params, "max_attach_distance_m", 2000)
    if manual_attach_point and manual_attach_point.get("longitude") is not None and manual_attach_point.get("latitude") is not None:
        manual_local = Point(to_local(float(manual_attach_point["longitude"]), float(manual_attach_point["latitude"])))
        manual_distance = max(0.0, min(float(line.length), float(line.project(manual_local))))
        candidates = [(manual_distance, landing_local.distance(line.interpolate(manual_distance)))]
    else:
        candidates = _candidate_distances(line, landing_local, max_attach_distance)
    best: dict[str, Any] | None = None

    for distance_m, horizontal_m in candidates:
        route_window = _route_altitude_window(route, profile_points, route_id, distance_m, target_layer)
        target_alt = float(route_window["target_altitude_m"])
        landing_alt = float(landing.get("altitude") or 0)
        attach_local = line.interpolate(distance_m)
        attach_lon, attach_lat = to_wgs84(attach_local.x, attach_local.y)
        landing_lon, landing_lat = float(landing["longitude"]), float(landing["latitude"])
        horizontal_distance = max(1.0, float(horizontal_m))

        if leg_type == "entry":
            vertical_needed = max(0.0, target_alt - landing_alt)
            vertical_rate = _param_number(params, "max_climb_rate_ms", 3)
            fixed_wing_phase = "departure"
            gradient = _param_number(params, "climb_gradient", 0.065)
        elif target_alt >= landing_alt:
            vertical_needed = target_alt - landing_alt
            vertical_rate = _param_number(params, "max_descent_rate_ms", 2.5)
            fixed_wing_phase = "arrival"
            gradient = _param_number(params, "descent_gradient", 0.041)
        else:
            vertical_needed = landing_alt - target_alt
            vertical_rate = _param_number(params, "max_climb_rate_ms", 3)
            fixed_wing_phase = "arrival"
            gradient = _param_number(params, "climb_gradient", 0.065)

        min_turn_radius = _param_number(params, "min_turn_radius_m", 20)
        reasons: list[str] = []
        warnings: list[str] = []
        rule_metrics: dict[str, float] = {}
        feature_specs: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
        loiter_distance_m = 0.0
        loiter_time_s = 0.0
        loiter_turns = 0.0
        height_fusion_required_m = 0.0
        height_fusion_available_m = horizontal_distance
        height_fusion_status = "pass"

        if aircraft_platform == "fixed_wing":
            vertical_method = "fixed_wing_tangent_arc_height_fusion"
            rule_metrics = _fixed_wing_rule_metrics(params, fixed_wing_phase)
            radius = max(1.0, min_turn_radius)
            if min_turn_radius <= 0:
                reasons.append("固定翼最小转弯半径必须大于 0")
            if radius + 0.1 < float(rule_metrics["computed_turn_radius_m"]):
                warnings.append(f"按最大地速和滚转角推算的转弯半径约 {rule_metrics['computed_turn_radius_m']:.1f} m，当前半径偏小")

            route_tangent = _line_tangent(line, distance_m)
            inbound = _unit(attach_local.x - landing_local.x, attach_local.y - landing_local.y, route_tangent)
            outbound = _unit(landing_local.x - attach_local.x, landing_local.y - attach_local.y, (-route_tangent[0], -route_tangent[1]))
            if leg_type == "entry":
                arc_points, arc_length, arc_warnings = _fixed_wing_arc_to_attach(
                    landing=landing_local,
                    attach=attach_local,
                    inbound_tangent=inbound,
                    route_tangent=route_tangent,
                    radius_m=radius,
                )
                straight_points = [landing_local, arc_points[0]]
                arc_start_alt = landing_alt + (target_alt - landing_alt) * 0.72
                straight_distance = _line_distance(straight_points)
                path_points = [*straight_points, *arc_points[1:]]
                path_coords = _points_to_coords(path_points, landing_alt, target_alt, to_wgs84)
                feature_specs.append((
                    "fixed_wing_straight",
                    "固定翼离场直线段",
                    {"type": "LineString", "coordinates": _points_to_coords(straight_points, landing_alt, arc_start_alt, to_wgs84)},
                    {
                        "altitude_start_m": round(landing_alt, 2),
                        "altitude_end_m": round(arc_start_alt, 2),
                        "gradient": round(gradient, 4),
                        "source_rule": "MH/T fixed-wing draft 7.3.2, B.3",
                    },
                ))
                feature_specs.append((
                    "fixed_wing_arc",
                    "固定翼旁切圆弧接入",
                    {"type": "LineString", "coordinates": _points_to_coords(arc_points, arc_start_alt, target_alt, to_wgs84)},
                    {
                        "radius_m": round(radius, 2),
                        "altitude_start_m": round(arc_start_alt, 2),
                        "altitude_end_m": round(target_alt, 2),
                        "source_rule": "MH/T fixed-wing draft B.3",
                    },
                ))
            else:
                arc_points, arc_length, arc_warnings = _fixed_wing_arc_from_attach(
                    landing=landing_local,
                    attach=attach_local,
                    route_tangent=route_tangent,
                    outbound_tangent=outbound,
                    radius_m=radius,
                )
                arc_end_alt = target_alt + (landing_alt - target_alt) * 0.28
                straight_points = [arc_points[-1], landing_local]
                straight_distance = _line_distance(straight_points)
                path_points = [*arc_points, landing_local]
                path_coords = _points_to_coords(path_points, target_alt, landing_alt, to_wgs84)
                feature_specs.append((
                    "fixed_wing_arc",
                    "固定翼旁切圆弧退出",
                    {"type": "LineString", "coordinates": _points_to_coords(arc_points, target_alt, arc_end_alt, to_wgs84)},
                    {
                        "radius_m": round(radius, 2),
                        "altitude_start_m": round(target_alt, 2),
                        "altitude_end_m": round(arc_end_alt, 2),
                        "source_rule": "MH/T fixed-wing draft B.3",
                    },
                ))
                feature_specs.append((
                    "fixed_wing_straight",
                    "固定翼进场直线段",
                    {"type": "LineString", "coordinates": _points_to_coords(straight_points, arc_end_alt, landing_alt, to_wgs84)},
                    {
                        "altitude_start_m": round(arc_end_alt, 2),
                        "altitude_end_m": round(landing_alt, 2),
                        "gradient": round(gradient, 4),
                        "source_rule": "MH/T fixed-wing draft 7.3.5, B.3",
                    },
                ))
            warnings.extend(arc_warnings)
            height_fusion_available_m = max(1.0, straight_distance + arc_length)
            height_fusion_required_m = vertical_needed / max(0.0001, gradient)
            if vertical_needed > 0 and height_fusion_available_m + 0.1 < height_fusion_required_m:
                loiter_distance_m = height_fusion_required_m - height_fusion_available_m
                loiter_time_s = loiter_distance_m / speed_ms
                circumference = max(1.0, 2 * math.pi * radius)
                loiter_turns = loiter_distance_m / circumference
                height_fusion_status = "warning"
                loiter_center = path_points[1] if len(path_points) > 2 else attach_local
                loiter_alt = landing_alt + (target_alt - landing_alt) * 0.55
                feature_specs.append((
                    "fixed_wing_loiter",
                    "固定翼高度融合盘旋段",
                    {"type": "LineString", "coordinates": _circle_coords(loiter_center, radius, loiter_alt, to_wgs84, loiter_turns)},
                    {
                        "radius_m": round(radius, 2),
                        "altitude_start_m": round(loiter_alt, 2),
                        "altitude_end_m": round(loiter_alt, 2),
                        "source_rule": "height_fusion_gradient",
                    },
                ))
                warnings.append(f"高度融合距离不足，需增加约 {loiter_turns:.2f} 圈盘旋")
            leg_distance = height_fusion_available_m + loiter_distance_m
            horizontal_time_s = height_fusion_available_m / speed_ms
            time_s = leg_distance / speed_ms
            vertical_capacity = vertical_needed
        else:
            vertical_method = "vertical_takeoff_landing"
            vertical_capacity = vertical_needed
            ratio = min(1.0, max(0.0, _param_number(params, "waiting_height_agl_m", 30) / max(1.0, abs(target_alt - landing_alt) or 1.0)))
            wait_ratio = min(0.35, max(0.15, ratio))
            wait_point = Point(
                landing_local.x + (attach_local.x - landing_local.x) * wait_ratio,
                landing_local.y + (attach_local.y - landing_local.y) * wait_ratio,
            )
            wait_alt = landing_alt + _param_number(params, "waiting_height_agl_m", 30)
            path_coords = [
                [landing_lon, landing_lat, round(landing_alt, 2)],
                *_points_to_coords([wait_point], wait_alt, wait_alt, to_wgs84),
                [round(attach_lon, 8), round(attach_lat, 8), round(target_alt, 2)],
            ]
            if leg_type == "exit":
                path_coords = list(reversed(path_coords))
            leg_distance = horizontal_distance
            horizontal_time_s = horizontal_distance / speed_ms
            time_s = horizontal_time_s
            feature_specs.append((
                leg_type,
                "进入主航路" if leg_type == "entry" else "退出主航路",
                {"type": "LineString", "coordinates": path_coords},
                {
                    "altitude_start_m": round(landing_alt if leg_type == "entry" else target_alt, 2),
                    "altitude_end_m": round(target_alt if leg_type == "entry" else landing_alt, 2),
                    "source_rule": "vtol_vertical_takeoff_landing",
                },
            ))

        if horizontal_distance > max_attach_distance:
            reasons.append("接入距离超过上限")
        if aircraft_platform != "vtol" and horizontal_distance < max(1.0, min_turn_radius) * 2:
            warnings.append("接入段过短，可能不满足最小转弯半径")
        if aircraft_platform not in {"vtol", "fixed_wing"} and vertical_needed > vertical_capacity + 0.1:
            reasons.append("爬升/下降能力不足")
        if abs(target_alt - landing_alt) < _param_number(params, "min_clearance_m", 15):
            warnings.append("起降场至主航路高度融合余度偏低")
        deviation_half_height = rule_metrics.get("vertical_deviation_half_height_m", _param_number(params, "vertical_deviation_m", 10))
        if target_alt - deviation_half_height < float(route_window["bottom_altitude_m"]):
            warnings.append("垂直偏差下边界接近或低于航路高度下限")
        if target_alt + deviation_half_height > float(route_window["top_altitude_m"]):
            warnings.append("垂直偏差上边界接近或高于航路高度上限")

        status = _leg_status(reasons, warnings)
        score = len(reasons) * 100000 + len(warnings) * 1000 + leg_distance + abs(distance_m - line.project(landing_local)) * 0.15
        if path_coords:
            wait_coord = path_coords[max(0, min(len(path_coords) - 1, len(path_coords) // 3))]
            wait_lon, wait_lat, wait_alt = wait_coord[0], wait_coord[1], wait_coord[2]
        else:
            wait_lon, wait_lat, wait_alt = landing_lon, landing_lat, landing_alt
        features = [_make_path_feature(kind, name, geometry, status=status, leg_type=leg_type, **extra) for kind, name, geometry, extra in feature_specs]
        features.append(
            _make_path_feature(
                "waiting_point",
                "离场等待/融合点" if leg_type == "entry" else "进场等待/融合点",
                {"type": "Point", "coordinates": [wait_lon, wait_lat, wait_alt]},
                status=status,
                leg_type=leg_type,
                altitude_m=wait_alt,
            )
        )
        features.append(
            _make_path_feature(
                "attach_point",
                "主航路接入点" if leg_type == "entry" else "主航路退出点",
                {"type": "Point", "coordinates": [round(attach_lon, 8), round(attach_lat, 8), round(target_alt, 2)]},
                status=status,
                leg_type=leg_type,
                draggable=aircraft_platform == "fixed_wing",
                altitude_m=round(target_alt, 2),
            )
        )

        item = {
            "leg_type": leg_type,
            "status": status,
            "reasons": reasons,
            "warnings": warnings,
            "landing": landing,
            "attach_distance_m": round(distance_m, 2),
            "horizontal_distance_m": round(horizontal_distance, 2),
            "total_distance_m": round(leg_distance, 2),
            "estimated_time_s": round(time_s, 1),
            "horizontal_time_s": round(horizontal_time_s, 1),
            "vertical_needed_m": round(vertical_needed, 2),
            "vertical_capacity_m": round(vertical_capacity, 2),
            "vertical_method": vertical_method,
            "loiter_distance_m": round(loiter_distance_m, 2),
            "loiter_time_s": round(loiter_time_s, 1),
            "loiter_turns": round(loiter_turns, 2),
            "height_fusion_status": height_fusion_status,
            "height_fusion_distance_required_m": round(height_fusion_required_m, 2),
            "height_fusion_distance_available_m": round(height_fusion_available_m, 2),
            "rule_metrics": rule_metrics,
            "route_altitude": route_window,
            "attach_point": {"longitude": round(attach_lon, 8), "latitude": round(attach_lat, 8), "altitude_m": round(target_alt, 2)},
            "waiting_point": {"longitude": round(wait_lon, 8), "latitude": round(wait_lat, 8), "altitude_m": round(wait_alt, 2)},
            "path_coordinates": path_coords,
            "features": features,
            "_score": score,
        }
        if best is None or item["_score"] < best["_score"]:
            best = item
        if not reasons:
            break

    assert best is not None
    best.pop("_score", None)
    return best


def _feature_collection(entry: dict[str, Any], exit_leg: dict[str, Any]) -> dict[str, Any]:
    features = []
    for leg in (entry, exit_leg):
        if leg.get("features"):
            features.extend(leg["features"])
            continue
        label = "进入主航路" if leg["leg_type"] == "entry" else "退出主航路"
        features.append(
            _make_path_feature(
                leg["leg_type"],
                label,
                {"type": "LineString", "coordinates": leg["path_coordinates"]},
                status=leg["status"],
            )
        )
        for point_key, point_label in (("waiting_point", "等待点"), ("attach_point", "进离场点")):
            point = leg[point_key]
            features.append(
                _make_path_feature(
                    point_key,
                    f"{label}{point_label}",
                    {"type": "Point", "coordinates": [point["longitude"], point["latitude"], point["altitude_m"]]},
                    status=leg["status"],
                    altitude_m=point["altitude_m"],
                )
            )
    return {"type": "FeatureCollection", "features": features}


def calculate_takeoff_flight_plan(route_id: int, payload: dict[str, Any], *, persist: bool) -> dict[str, Any]:
    route = get_route(route_id)
    if not route:
        raise HTTPException(status_code=404, detail="航路不存在")

    landing = _landing_by_id(route_id, int(payload["landing_id"]))
    snapshot = _route_snapshot(route_id)
    target_layer = _selected_target_layer(snapshot, payload.get("target_layer_sequence"))
    centerline = shape(snapshot.get("centerline"))
    if not isinstance(centerline, LineString) or centerline.length <= 0:
        raise HTTPException(status_code=400, detail="当前航路缺少可用中心线")

    first = list(centerline.coords)[0]
    to_local, to_wgs84 = build_local_transformers(float(first[0]), float(first[1]))
    centerline_local = LineString([to_local(float(lon), float(lat)) for lon, lat, *_ in centerline.coords])
    profile = _profile_points(snapshot)
    params = dict(payload["aircraft_params"])
    aircraft_platform = str(payload.get("aircraft_platform") or "vtol")

    entry = _evaluate_leg_v2(
        route_id=route_id,
        route=route,
        line=centerline_local,
        to_local=to_local,
        to_wgs84=to_wgs84,
        profile_points=profile,
        landing=landing,
        leg_type="entry",
        params=params,
        target_layer=target_layer,
        aircraft_platform=aircraft_platform,
        manual_attach_point=payload.get("entry_attach_point") if aircraft_platform == "fixed_wing" else None,
    )
    exit_leg = _evaluate_leg_v2(
        route_id=route_id,
        route=route,
        line=centerline_local,
        to_local=to_local,
        to_wgs84=to_wgs84,
        profile_points=profile,
        landing=landing,
        leg_type="exit",
        params=params,
        target_layer=target_layer,
        aircraft_platform=aircraft_platform,
        manual_attach_point=payload.get("exit_attach_point") if aircraft_platform == "fixed_wing" else None,
    )

    total_distance = float(entry["total_distance_m"]) + float(exit_leg["total_distance_m"])
    speed_ms = max(0.1, float(params["cruise_speed_kmh"]) / 3.6)
    total_time_min = total_distance / speed_ms / 60.0
    available_time_min = max(0.0, float(params["max_flight_time_min"]) - float(params["reserve_time_min"]))
    issues = [*entry["reasons"], *exit_leg["reasons"]]
    warnings = [*entry["warnings"], *exit_leg["warnings"]]
    if total_time_min > available_time_min:
        issues.append("续航时间不足")
    status = "fail" if issues else ("warning" if warnings else "pass")
    path_geojson = _feature_collection(entry, exit_leg)
    rule_metrics = entry.get("rule_metrics") or exit_leg.get("rule_metrics") or {}
    height_statuses = {entry.get("height_fusion_status"), exit_leg.get("height_fusion_status")}
    height_fusion_status = "warning" if "warning" in height_statuses else "pass"
    result = {
        "status": status,
        "summary": {
            "total_distance_m": round(total_distance, 2),
            "estimated_time_min": round(total_time_min, 2),
            "available_time_min": round(available_time_min, 2),
            "navigation_protection_half_width_m": round(float(rule_metrics.get("protection_half_width_m", params["horizontal_deviation_m"])), 2),
            "navigation_protection_half_height_m": round(float(rule_metrics.get("vertical_deviation_half_height_m", params["vertical_deviation_m"])), 2),
            "xtt_m": rule_metrics.get("xtt_m"),
            "att_m": rule_metrics.get("att_m"),
            "vtt_m": rule_metrics.get("vtt_m"),
            "protection_half_width_m": rule_metrics.get("protection_half_width_m"),
            "vertical_deviation_half_height_m": rule_metrics.get("vertical_deviation_half_height_m"),
            "recommended_moc_m": rule_metrics.get("recommended_moc_m"),
            "height_fusion_status": height_fusion_status,
            "height_fusion_distance_required_m": round(float(entry.get("height_fusion_distance_required_m", 0)) + float(exit_leg.get("height_fusion_distance_required_m", 0)), 2),
            "height_fusion_distance_available_m": round(float(entry.get("height_fusion_distance_available_m", 0)) + float(exit_leg.get("height_fusion_distance_available_m", 0)), 2),
            "entry_attach_distance_m": entry.get("attach_distance_m"),
            "exit_attach_distance_m": exit_leg.get("attach_distance_m"),
            "target_layer_sequence": target_layer.get("sequence") if target_layer else None,
            "aircraft_platform": aircraft_platform,
            "vertical_mode": "垂直起降不校验爬升/下降率" if aircraft_platform == "vtol" else "固定翼按圆形盘旋爬升/下降",
            "loiter_distance_m": round(float(entry["loiter_distance_m"]) + float(exit_leg["loiter_distance_m"]), 2),
            "loiter_time_s": round(float(entry["loiter_time_s"]) + float(exit_leg["loiter_time_s"]), 1),
            "loiter_turns": round(float(entry["loiter_turns"]) + float(exit_leg["loiter_turns"]), 2),
        },
        "issues": issues,
        "warnings": warnings,
        "departure": entry,
        "arrival": exit_leg,
        "entry": entry,
        "exit": exit_leg,
    }
    target_layer_sequence = target_layer.get("sequence") if target_layer else None
    plan = {
        "id": None,
        "route_id": route_id,
        "landing_id": landing["id"],
        "departure_landing_id": landing["id"],
        "arrival_landing_id": landing["id"],
        "target_layer_sequence": target_layer_sequence,
        "target_layer": target_layer,
        "aircraft_platform": aircraft_platform,
        "aircraft_preset": payload.get("aircraft_preset") or "custom",
        "aircraft_params": params,
        "result": result,
        "path_geojson": path_geojson,
    }
    if persist:
        with db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO takeoff_flight_plans (
                    route_id, departure_landing_id, arrival_landing_id, target_layer_sequence,
                    aircraft_preset, aircraft_params_json, result_json, path_geojson
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    route_id,
                    landing["id"],
                    landing["id"],
                    target_layer_sequence,
                    plan["aircraft_preset"],
                    _json_dump(params),
                    _json_dump(result),
                    _json_dump(path_geojson),
                ),
            )
            plan["id"] = cursor.lastrowid
    return plan


def list_takeoff_flight_plans(route_id: int) -> list[dict[str, Any]]:
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT *
            FROM takeoff_flight_plans
            WHERE route_id=?
            ORDER BY updated_at DESC, id DESC
            """,
            (route_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    items = []
    for row in rows:
        result = _json_load(row.get("result_json"), {})
        target_layer_sequence = row.get("target_layer_sequence")
        if target_layer_sequence is None and isinstance(result, dict):
            target_layer_sequence = result.get("summary", {}).get("target_layer_sequence")
        landing_id = row.get("departure_landing_id")
        items.append(
            {
                **row,
                "landing_id": landing_id,
                "target_layer_sequence": target_layer_sequence,
                "aircraft_platform": result.get("summary", {}).get("aircraft_platform") if isinstance(result, dict) else "vtol",
                "aircraft_params": _json_load(row.get("aircraft_params_json"), {}),
                "result": result,
                "path_geojson": _json_load(row.get("path_geojson"), {}),
            }
        )
    return items


def get_takeoff_flight_state(route_id: int) -> dict[str, Any]:
    route = get_route(route_id)
    if not route:
        raise HTTPException(status_code=404, detail="航路不存在")
    snapshot = _route_snapshot(route_id)
    return {
        "ok": True,
        "route": route,
        "landing_sites": get_landing_sites(route_id),
        "terrain_summary": _terrain_summary(route_id),
        "visual": {
            "centerline": snapshot.get("centerline"),
            "flight_zone": snapshot.get("flight_zone"),
            "protection_zone": snapshot.get("protection_zone"),
            "sub_routes": snapshot.get("sub_routes") or [],
            "profile": snapshot.get("profile"),
        },
        "plans": list_takeoff_flight_plans(route_id),
    }
