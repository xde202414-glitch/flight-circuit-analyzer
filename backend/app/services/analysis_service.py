from __future__ import annotations

import json
import math
import re
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from shapely import LineString, Point
from shapely.geometry import shape
from shapely.ops import transform

from app.database_route import db_cursor
from app.services.analysis_catalog import get_catalog_payload, get_factor_map
from app.services.coordinate_service import build_local_transformers
from app.services.geo_service import get_route_geo_data
from app.services.route_service import generate_route_geometry, get_points, get_route, get_route_full_state

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"
COMPLIANCE_VALUES = {"pass", "fail", "unknown"}
INPUT_MODE_VALUES = {"auto", "manual"}
AIRCRAFT_TYPES = {"micro", "light"}
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
_TUNNEL_EXEMPT_LINE_FACTORS = {"infra_electrified_railway", "infra_highway"}
_AREA_FALLBACK_QUERY_FACTORS = {
    "infra_power_plant": "浙江省",
    "infra_substation": "浙江省",
}


def _json_load(raw: str | None, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _normalize_aircraft_type(value: str | None) -> str:
    aircraft_type = str(value or "micro").strip().lower()
    if aircraft_type not in AIRCRAFT_TYPES:
        raise ValueError(f"Unsupported aircraft_type: {aircraft_type}")
    return aircraft_type


def _get_snapshot(route_id: int) -> dict[str, Any]:
    full_state = get_route_full_state(route_id)
    if full_state and isinstance(full_state.get("snapshot"), dict):
        snapshot = full_state["snapshot"]
        if snapshot.get("centerline") and snapshot.get("profile"):
            return snapshot
    generated = generate_route_geometry(route_id, persist_full_state=False)
    if not generated.get("ok"):
        errors = generated.get("errors") or ["Route geometry generation failed"]
        raise ValueError("; ".join(str(item) for item in errors))
    return generated


def _load_factor_inputs(route_id: int) -> dict[str, dict[str, Any]]:
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT factor_id, input_mode, manual_value_json, param_json, updated_at
            FROM route_analysis_factor_inputs
            WHERE route_id=?
            """,
            (route_id,),
        )
        rows = cursor.fetchall()
    payload: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload[row["factor_id"]] = {
            "input_mode": row["input_mode"] or "auto",
            "manual_value": _json_load(row["manual_value_json"], {}),
            "params": _json_load(row["param_json"], {}),
            "updated_at": row["updated_at"],
        }
    return payload


def _load_factor_results(route_id: int) -> dict[str, dict[str, Any]]:
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT factor_id, run_id, aircraft_type, data_status, compliance, source_mode,
                   evidence_json, next_action, auto_value_json, selected_value_json, updated_at
            FROM route_analysis_factor_results
            WHERE route_id=?
            """,
            (route_id,),
        )
        rows = cursor.fetchall()
    payload: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload[row["factor_id"]] = {
            "run_id": row["run_id"],
            "aircraft_type": row["aircraft_type"],
            "data_status": row["data_status"],
            "compliance": row["compliance"],
            "source_mode": row["source_mode"],
            "evidence": _json_load(row["evidence_json"], {}),
            "next_action": row["next_action"],
            "auto_value": _json_load(row["auto_value_json"], {}),
            "selected_value": _json_load(row["selected_value_json"], {}),
            "updated_at": row["updated_at"],
        }
    return payload


def _load_last_run(route_id: int) -> dict[str, Any] | None:
    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT id, aircraft_type, scope_json, total_count, pass_count, fail_count,
                   unknown_count, success_rate, duration_ms, created_at
            FROM route_analysis_runs
            WHERE route_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (route_id,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    return {
        "run_id": row["id"],
        "aircraft_type": row["aircraft_type"],
        "scope": _json_load(row["scope_json"], {}),
        "total_count": row["total_count"],
        "pass_count": row["pass_count"],
        "fail_count": row["fail_count"],
        "unknown_count": row["unknown_count"],
        "success_rate": row["success_rate"],
        "duration_ms": row["duration_ms"],
        "created_at": row["created_at"],
    }


def _merge_factor_state(route_id: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    factor_map = get_factor_map()
    factor_inputs = _load_factor_inputs(route_id)
    factor_results = _load_factor_results(route_id)
    merged: list[dict[str, Any]] = []
    for factor in factor_map.values():
        factor_id = factor["id"]
        merged.append(
            {
                **factor,
                "input": factor_inputs.get(
                    factor_id,
                    {"input_mode": "auto", "manual_value": {}, "params": {}, "updated_at": None},
                ),
                "latest_result": factor_results.get(factor_id),
            }
        )
    catalog = get_catalog_payload()
    return merged, catalog


def get_analysis_catalog() -> dict[str, Any]:
    return get_catalog_payload()


def _iter_lon_lat_coords(node: Any):
    if isinstance(node, (list, tuple)):
        if len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
            yield float(node[0]), float(node[1])
        else:
            for child in node:
                yield from _iter_lon_lat_coords(child)


def _normalize_geojson_feature_collection(raw_geojson: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_geojson, dict):
        raise ValueError("geojson must be an object")
    geo_type = str(raw_geojson.get("type") or "")
    if geo_type == "FeatureCollection":
        features = raw_geojson.get("features")
        if not isinstance(features, list):
            raise ValueError("FeatureCollection.features must be a list")
        normalized_features = []
        for feature in features:
            if not isinstance(feature, dict) or str(feature.get("type") or "") != "Feature":
                raise ValueError("All items in features must be GeoJSON Feature")
            geometry = feature.get("geometry")
            if not geometry:
                continue
            normalized_features.append(
                {
                    "type": "Feature",
                    "properties": feature.get("properties") or {},
                    "geometry": geometry,
                }
            )
        if not normalized_features:
            raise ValueError("No valid feature geometry in geojson")
        return {"type": "FeatureCollection", "features": normalized_features}
    if geo_type == "Feature":
        geometry = raw_geojson.get("geometry")
        if not geometry:
            raise ValueError("Feature.geometry is required")
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": raw_geojson.get("properties") or {},
                    "geometry": geometry,
                }
            ],
        }
    if raw_geojson.get("coordinates") is not None:
        return {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {}, "geometry": raw_geojson},
            ],
        }
    raise ValueError("Unsupported geojson object")


def _validate_geojson_wgs84(feature_collection: dict[str, Any]) -> int:
    features = feature_collection.get("features") or []
    if not features:
        raise ValueError("GeoJSON features is empty")
    count = 0
    for feature in features:
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            raise ValueError("Feature.geometry must be object")
        try:
            geom = shape(geometry)
        except Exception as exc:
            raise ValueError(f"Invalid geometry: {exc}") from exc
        if geom.is_empty:
            continue
        if not geom.is_valid:
            raise ValueError("Invalid geometry topology found")
        for lon, lat in _iter_lon_lat_coords(geometry.get("coordinates")):
            if lon < -180 or lon > 180 or lat < -90 or lat > 90:
                raise ValueError("Coordinates must be WGS84 lon/lat")
        count += 1
    if count <= 0:
        raise ValueError("No non-empty geometry found")
    return count


def _ensure_authoritative_layer_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS route_analysis_authoritative_layers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            factor_id TEXT NOT NULL,
            name TEXT NOT NULL,
            version TEXT,
            source TEXT,
            priority INTEGER NOT NULL DEFAULT 100,
            enabled INTEGER NOT NULL DEFAULT 1,
            feature_count INTEGER NOT NULL DEFAULT 0,
            geojson TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_route_analysis_authoritative_layers_factor
        ON route_analysis_authoritative_layers(factor_id, enabled, priority, id DESC)
        """
    )


def list_authoritative_layers(*, factor_id: str | None = None, enabled_only: bool = False) -> list[dict[str, Any]]:
    query = """
        SELECT id, factor_id, name, version, source, priority, enabled, feature_count, geojson, created_at, updated_at
        FROM route_analysis_authoritative_layers
    """
    clauses: list[str] = []
    params: list[Any] = []
    if factor_id:
        clauses.append("factor_id=?")
        params.append(factor_id)
    if enabled_only:
        clauses.append("enabled=1")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY priority ASC, id DESC"
    try:
        with db_cursor() as cursor:
            _ensure_authoritative_layer_table(cursor)
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise
    items: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["enabled"] = bool(data.get("enabled"))
        data["geojson"] = _json_load(data.get("geojson"), {"type": "FeatureCollection", "features": []})
        items.append(data)
    return items


def import_authoritative_layer(payload: dict[str, Any]) -> dict[str, Any]:
    factor_id = str(payload.get("factor_id") or "").strip()
    if not factor_id:
        raise ValueError("factor_id is required")
    factor_map = get_factor_map()
    if factor_id not in factor_map:
        raise ValueError(f"Unknown factor_id: {factor_id}")
    normalized_geojson = _normalize_geojson_feature_collection(payload.get("geojson") or {})
    feature_count = _validate_geojson_wgs84(normalized_geojson)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    version = payload.get("version")
    source = payload.get("source")
    priority = int(payload.get("priority", 100))
    enabled = 1 if bool(payload.get("enabled", True)) else 0
    with db_cursor() as cursor:
        _ensure_authoritative_layer_table(cursor)
        cursor.execute(
            """
            INSERT INTO route_analysis_authoritative_layers (
                factor_id, name, version, source, priority, enabled, feature_count, geojson
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                factor_id,
                name,
                str(version).strip() if version is not None else None,
                str(source).strip() if source is not None else None,
                priority,
                enabled,
                feature_count,
                _json_dump(normalized_geojson),
            ),
        )
        layer_id = int(cursor.lastrowid)
    items = list_authoritative_layers(factor_id=factor_id, enabled_only=False)
    created = next((item for item in items if int(item["id"]) == layer_id), None)
    return {"ok": True, "item": created}


def update_authoritative_layer(layer_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    with db_cursor() as cursor:
        _ensure_authoritative_layer_table(cursor)
        cursor.execute(
            """
            SELECT id, factor_id, name, version, source, priority, enabled, feature_count, geojson
            FROM route_analysis_authoritative_layers
            WHERE id=?
            """,
            (layer_id,),
        )
        current = cursor.fetchone()
    if not current:
        raise ValueError("Authoritative layer not found")
    current_item = dict(current)

    next_name = patch.get("name", current_item.get("name"))
    next_version = patch.get("version", current_item.get("version"))
    next_source = patch.get("source", current_item.get("source"))
    next_priority = patch.get("priority", current_item.get("priority"))
    next_enabled = patch.get("enabled", bool(current_item.get("enabled")))
    next_geojson = current_item.get("geojson")
    next_feature_count = current_item.get("feature_count")

    if "geojson" in patch:
        normalized_geojson = _normalize_geojson_feature_collection(patch.get("geojson") or {})
        next_feature_count = _validate_geojson_wgs84(normalized_geojson)
        next_geojson = _json_dump(normalized_geojson)

    with db_cursor() as cursor:
        _ensure_authoritative_layer_table(cursor)
        cursor.execute(
            """
            UPDATE route_analysis_authoritative_layers
            SET name=?, version=?, source=?, priority=?, enabled=?, feature_count=?, geojson=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                str(next_name).strip(),
                str(next_version).strip() if next_version is not None else None,
                str(next_source).strip() if next_source is not None else None,
                int(next_priority),
                1 if bool(next_enabled) else 0,
                int(next_feature_count),
                next_geojson,
                layer_id,
            ),
        )
    items = list_authoritative_layers(enabled_only=False)
    updated = next((item for item in items if int(item["id"]) == int(layer_id)), None)
    return {"ok": True, "item": updated}


def delete_authoritative_layer(layer_id: int) -> dict[str, Any]:
    with db_cursor() as cursor:
        _ensure_authoritative_layer_table(cursor)
        cursor.execute("DELETE FROM route_analysis_authoritative_layers WHERE id=?", (layer_id,))
        if cursor.rowcount <= 0:
            raise ValueError("Authoritative layer not found")
    return {"ok": True, "id": layer_id}


def _load_authoritative_layers_for_factor(factor_id: str) -> list[dict[str, Any]]:
    return list_authoritative_layers(factor_id=factor_id, enabled_only=True)


def _build_visual_payload(snapshot: dict[str, Any], geo_data: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "route": snapshot.get("route"),
        "centerline": snapshot.get("centerline"),
        "flight_zone": snapshot.get("flight_zone"),
        "protection_zone": snapshot.get("protection_zone"),
        "profile": snapshot.get("profile"),
        "sub_routes": snapshot.get("sub_routes", []),
        "geo": geo_data
        if geo_data
        else {
            "terrain": {"points": [], "cloud_points": [], "summary": {}},
            "buildings": {"items": [], "summary": {}},
            "modules": [],
            "storage": {"persisted": False},
        },
    }


def get_route_analysis_view(route_id: int) -> dict[str, Any]:
    route = get_route(route_id)
    if not route:
        raise ValueError("Route not found")
    snapshot = _get_snapshot(route_id)
    try:
        geo_data = get_route_geo_data(route_id)
    except ValueError:
        geo_data = None
    factors, catalog = _merge_factor_state(route_id)
    return {
        "ok": True,
        "route_id": route_id,
        "route_name": route.get("name"),
        "categories": catalog["categories"],
        "factors": factors,
        "last_run": _load_last_run(route_id),
        "visual": _build_visual_payload(snapshot, geo_data),
    }


def update_factor_input(
    route_id: int,
    factor_id: str,
    *,
    input_mode: str,
    manual_value: dict[str, Any] | None,
) -> dict[str, Any]:
    route = get_route(route_id)
    if not route:
        raise ValueError("Route not found")
    factor_map = get_factor_map()
    if factor_id not in factor_map:
        raise ValueError(f"Unknown factor_id: {factor_id}")
    mode = str(input_mode or "auto").strip().lower()
    if mode not in INPUT_MODE_VALUES:
        raise ValueError(f"Unsupported input_mode: {mode}")
    manual_payload = manual_value or {}
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO route_analysis_factor_inputs (route_id, factor_id, input_mode, manual_value_json, param_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(route_id, factor_id) DO UPDATE SET
                input_mode=excluded.input_mode,
                manual_value_json=excluded.manual_value_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (route_id, factor_id, mode, _json_dump(manual_payload), _json_dump({})),
        )
        cursor.execute(
            """
            UPDATE route_analysis_factor_inputs
            SET param_json = COALESCE(param_json, ?)
            WHERE route_id=? AND factor_id=?
            """,
            (_json_dump({}), route_id, factor_id),
        )
    return {"ok": True, "route_id": route_id, "factor_id": factor_id, "input_mode": mode, "manual_value": manual_payload}


def update_factor_params(route_id: int, factor_id: str, params: dict[str, Any]) -> dict[str, Any]:
    route = get_route(route_id)
    if not route:
        raise ValueError("Route not found")
    factor_map = get_factor_map()
    if factor_id not in factor_map:
        raise ValueError(f"Unknown factor_id: {factor_id}")
    payload = params or {}
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO route_analysis_factor_inputs (route_id, factor_id, input_mode, manual_value_json, param_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(route_id, factor_id) DO UPDATE SET
                param_json=excluded.param_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (route_id, factor_id, "auto", _json_dump({}), _json_dump(payload)),
        )
        cursor.execute(
            """
            UPDATE route_analysis_factor_inputs
            SET manual_value_json = COALESCE(manual_value_json, ?)
            WHERE route_id=? AND factor_id=?
            """,
            (_json_dump({}), route_id, factor_id),
        )
    return {"ok": True, "route_id": route_id, "factor_id": factor_id, "params": payload}


def _read_manual_override(manual_value: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = manual_value or {}
    compliance = str(payload.get("compliance") or "").strip().lower()
    if compliance not in {"pass", "fail"}:
        return None
    return {
        "compliance": compliance,
        "notes": str(payload.get("notes") or "").strip(),
    }


def _resolve_threshold(params: dict[str, Any], aircraft_type: str, fallback: float | None = None) -> float | None:
    key = "micro_threshold_m" if aircraft_type == "micro" else "light_threshold_m"
    value = params.get(key)
    if value is None or value == "":
        if fallback is None:
            return None
        try:
            return float(fallback)
        except (TypeError, ValueError):
            return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return max(0.0, parsed)


def _build_geo_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    centerline_geo = snapshot.get("centerline")
    protection_geo = snapshot.get("protection_zone")
    points = snapshot.get("points") or get_points(int(snapshot.get("route", {}).get("id", 0)))
    if not centerline_geo or not protection_geo or not points:
        return {}
    try:
        ref_lon = float(points[0]["longitude"])
        ref_lat = float(points[0]["latitude"])
        to_local, _to_wgs84 = build_local_transformers(ref_lon, ref_lat)
        centerline_local = transform(to_local, shape(centerline_geo))
        protection_local = transform(to_local, shape(protection_geo))
        return {
            "to_local": to_local,
            "centerline_local": centerline_local,
            "protection_local": protection_local,
            "protection_bounds_wgs84": shape(protection_geo).bounds,
        }
    except Exception:
        return {}


def _distance_to_basis_m(lon: float, lat: float, geo_context: dict[str, Any], basis: str) -> float | None:
    to_local = geo_context.get("to_local")
    if not to_local:
        return None
    x, y = to_local(lon, lat)
    point_local = Point(float(x), float(y))
    if basis == "centerline":
        line = geo_context.get("centerline_local")
        if line is None:
            return None
        return float(line.distance(point_local))
    polygon = geo_context.get("protection_local")
    if polygon is None:
        return None
    if polygon.contains(point_local) or polygon.touches(point_local):
        return 0.0
    return float(polygon.distance(point_local))


def _is_tunnel_like(tags: dict[str, Any] | None) -> bool:
    payload = tags or {}
    tunnel_value = str(payload.get("tunnel") or "").strip().lower()
    if tunnel_value and tunnel_value not in {"no", "false", "0"}:
        return True
    location_value = str(payload.get("location") or "").strip().lower()
    if location_value in {"underground", "subway"}:
        return True
    return False


def _fetch_overpass_points(
    filters: list[str],
    bounds: tuple[float, float, float, float],
    *,
    timeout_s: float,
    max_candidates: int,
) -> list[dict[str, Any]]:
    west, south, east, north = bounds
    query_parts: list[str] = []
    for raw_filter in filters:
        filter_text = str(raw_filter or "").strip()
        if not filter_text:
            continue
        query_parts.append(f"{filter_text}({south},{west},{north},{east});")
    if not query_parts:
        return []
    query = (
        f"[out:json][timeout:{int(max(5, min(120, timeout_s)))}];"
        "("
        + "".join(query_parts)
        + ");"
        f"out center tags {int(max(20, min(2000, max_candidates)))};"
    )
    request = urllib.request.Request(
        OVERPASS_API_URL,
        data=query.encode("utf-8"),
        headers={"User-Agent": "route-designer-analysis/1.0", "Content-Type": "text/plain; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    elements = data.get("elements", []) or []
    points: list[dict[str, Any]] = []
    for element in elements:
        lon = None
        lat = None
        if element.get("type") == "node":
            lon = element.get("lon")
            lat = element.get("lat")
        else:
            center = element.get("center", {}) or {}
            lon = center.get("lon")
            lat = center.get("lat")
        if lon is None or lat is None:
            continue
        points.append(
            {
                "id": f"{element.get('type', 'element')}/{element.get('id', '')}",
                "lon": float(lon),
                "lat": float(lat),
                "tags": element.get("tags", {}) or {},
            }
        )
    return points


def _fetch_overpass_points_by_area_name(
    filters: list[str],
    area_name: str,
    *,
    timeout_s: float,
    max_candidates: int,
) -> list[dict[str, Any]]:
    query_parts: list[str] = []
    for raw_filter in filters:
        filter_text = str(raw_filter or "").strip()
        if not filter_text:
            continue
        query_parts.append(f"{filter_text}(area.searchArea);")
    if not query_parts:
        return []
    query = (
        f"[out:json][timeout:{int(max(5, min(180, timeout_s)))}];"
        f'area["name"="{area_name}"]->.searchArea;'
        "("
        + "".join(query_parts)
        + ");"
        f"out center tags {int(max(20, min(3000, max_candidates)))};"
    )
    req = urllib.request.Request(
        OVERPASS_API_URL,
        data=query.encode("utf-8"),
        headers={"User-Agent": "route-designer-analysis/1.0", "Content-Type": "text/plain; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    elements = data.get("elements", []) or []
    points: list[dict[str, Any]] = []
    for element in elements:
        lon = None
        lat = None
        if element.get("type") == "node":
            lon = element.get("lon")
            lat = element.get("lat")
        else:
            center = element.get("center", {}) or {}
            lon = center.get("lon")
            lat = center.get("lat")
        if lon is None or lat is None:
            continue
        points.append(
            {
                "id": f"{element.get('type', 'element')}/{element.get('id', '')}",
                "lon": float(lon),
                "lat": float(lat),
                "tags": element.get("tags", {}) or {},
            }
        )
    return points


def _fetch_overpass_lines(
    filters: list[str],
    bounds: tuple[float, float, float, float],
    *,
    timeout_s: float,
    max_candidates: int,
) -> list[dict[str, Any]]:
    west, south, east, north = bounds
    query_parts: list[str] = []
    for raw_filter in filters:
        filter_text = str(raw_filter or "").strip()
        if not filter_text:
            continue
        # For linear extraction, ignore node filters and force way/relation queries.
        if filter_text.startswith("node["):
            continue
        query_parts.append(f"{filter_text}({south},{west},{north},{east});")
    if not query_parts:
        return []
    query = (
        f"[out:json][timeout:{int(max(5, min(120, timeout_s)))}];"
        "("
        + "".join(query_parts)
        + ");"
        "out geom tags;"
    )
    request = urllib.request.Request(
        OVERPASS_API_URL,
        data=query.encode("utf-8"),
        headers={"User-Agent": "route-designer-analysis/1.0", "Content-Type": "text/plain; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    elements = data.get("elements", []) or []
    lines: list[dict[str, Any]] = []
    for element in elements:
        if element.get("type") not in {"way", "relation"}:
            continue
        geometry = element.get("geometry", []) or []
        coords: list[tuple[float, float]] = []
        for point in geometry:
            lon = point.get("lon")
            lat = point.get("lat")
            if lon is None or lat is None:
                continue
            coords.append((float(lon), float(lat)))
        if len(coords) < 2:
            continue
        line_id = f"{element.get('type', 'element')}/{element.get('id', '')}"
        lines.append(
            {
                "id": line_id,
                "coordinates": coords,
                "tags": element.get("tags", {}) or {},
            }
        )
        if len(lines) >= int(max(10, min(500, max_candidates))):
            break
    return lines


def _expand_bounds(bounds: tuple[float, float, float, float], expand_m: float) -> tuple[float, float, float, float]:
    west, south, east, north = bounds
    center_lat = (south + north) / 2.0
    lat_expand = max(0.0, float(expand_m)) / 110540.0
    lon_divisor = max(20000.0, 111320.0 * math.cos(math.radians(center_lat)))
    lon_expand = max(0.0, float(expand_m)) / lon_divisor
    return (west - lon_expand, south - lat_expand, east + lon_expand, north + lat_expand)


def _line_distance_to_basis_m(
    coordinates: list[tuple[float, float]],
    geo_context: dict[str, Any],
    basis: str,
) -> float | None:
    to_local = geo_context.get("to_local")
    if not to_local:
        return None
    local_coords: list[tuple[float, float]] = []
    for lon, lat in coordinates:
        x, y = to_local(float(lon), float(lat))
        local_coords.append((float(x), float(y)))
    if len(local_coords) < 2:
        return None
    try:
        line_local = LineString(local_coords)
    except Exception:
        return None
    if basis == "centerline":
        centerline = geo_context.get("centerline_local")
        if centerline is None:
            return None
        return float(centerline.distance(line_local))
    protection = geo_context.get("protection_local")
    if protection is None:
        return None
    if protection.intersects(line_local):
        return 0.0
    return float(protection.distance(line_local))


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _extract_meter_value(text: Any) -> float | None:
    if text is None:
        return None
    raw = str(text).strip().lower()
    if not raw:
        return None
    cleaned = raw.replace("meters", "m").replace("meter", "m")
    cleaned = cleaned.replace("米", "m")
    numeric = []
    dot_seen = False
    sign_allowed = True
    for ch in cleaned:
        if ch in "+-" and sign_allowed:
            numeric.append(ch)
            sign_allowed = False
            continue
        sign_allowed = False
        if ch.isdigit():
            numeric.append(ch)
            continue
        if ch == "." and not dot_seen:
            numeric.append(ch)
            dot_seen = True
            continue
        if numeric:
            break
    if not numeric:
        return None
    return _to_float("".join(numeric))


def _estimate_powerline_height_m(tags: dict[str, Any] | None) -> float | None:
    payload = tags or {}
    candidates = [
        _extract_meter_value(payload.get("height")),
        _extract_meter_value(payload.get("tower:height")),
        _extract_meter_value(payload.get("line:height")),
        _extract_meter_value(payload.get("cable:height")),
        _extract_meter_value(payload.get("maxheight")),
    ]
    for value in candidates:
        if value is None:
            continue
        if 5.0 <= value <= 120.0:
            return float(value)
    return None


def _extract_terrain_samples(geo_data: dict[str, Any] | None) -> list[dict[str, float]]:
    terrain = ((geo_data or {}).get("terrain") or {}).get("points") or []
    samples: list[dict[str, float]] = []
    for item in terrain:
        lon = _to_float(item.get("longitude"))
        lat = _to_float(item.get("latitude"))
        elevation = _to_float(item.get("elevation_m"))
        route_distance = _to_float(item.get("distance_m"))
        if lon is None or lat is None:
            continue
        samples.append(
            {
                "lon": lon,
                "lat": lat,
                "elevation_m": elevation if elevation is not None else float("nan"),
                "distance_m": route_distance if route_distance is not None else float("nan"),
            }
        )
    return samples


def _distance_meter_wgs84(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    mid_lat = math.radians((lat1 + lat2) * 0.5)
    dx = (lon1 - lon2) * 111320.0 * max(0.2, math.cos(mid_lat))
    dy = (lat1 - lat2) * 110540.0
    return math.hypot(dx, dy)


def _estimate_line_surface_info(
    coordinates: list[tuple[float, float]],
    terrain_samples: list[dict[str, float]],
) -> dict[str, float | None]:
    if not coordinates or not terrain_samples:
        return {"route_distance_m": None, "elevation_avg_m": None, "elevation_min_m": None, "elevation_max_m": None}

    step = max(1, len(coordinates) // 8)
    sample_points = [coordinates[idx] for idx in range(0, len(coordinates), step)]
    if sample_points[-1] != coordinates[-1]:
        sample_points.append(coordinates[-1])

    elevations: list[float] = []
    nearest_route_distance: float | None = None
    nearest_dist_meter: float | None = None

    for lon, lat in sample_points:
        best: dict[str, float] | None = None
        best_dist = float("inf")
        for terrain in terrain_samples:
            d = _distance_meter_wgs84(lon, lat, terrain["lon"], terrain["lat"])
            if d < best_dist:
                best_dist = d
                best = terrain
        if best is None:
            continue
        elevation = best.get("elevation_m")
        if elevation is not None and math.isfinite(elevation):
            elevations.append(float(elevation))
        route_distance = best.get("distance_m")
        if route_distance is not None and math.isfinite(route_distance):
            if nearest_dist_meter is None or best_dist < nearest_dist_meter:
                nearest_dist_meter = best_dist
                nearest_route_distance = float(route_distance)

    if not elevations:
        return {
            "route_distance_m": round(nearest_route_distance, 2) if nearest_route_distance is not None else None,
            "elevation_avg_m": None,
            "elevation_min_m": None,
            "elevation_max_m": None,
        }

    return {
        "route_distance_m": round(nearest_route_distance, 2) if nearest_route_distance is not None else None,
        "elevation_avg_m": round(sum(elevations) / len(elevations), 2),
        "elevation_min_m": round(min(elevations), 2),
        "elevation_max_m": round(max(elevations), 2),
    }


def _geometry_distance_to_basis_m(geometry: dict[str, Any], geo_context: dict[str, Any], basis: str) -> float | None:
    to_local = geo_context.get("to_local")
    if not to_local:
        return None
    try:
        geom_local = transform(to_local, shape(geometry))
    except Exception:
        return None
    if geom_local.is_empty:
        return None
    if basis == "centerline":
        centerline = geo_context.get("centerline_local")
        if centerline is None:
            return None
        return float(centerline.distance(geom_local))
    protection = geo_context.get("protection_local")
    if protection is None:
        return None
    if protection.intersects(geom_local) or protection.touches(geom_local):
        return 0.0
    return float(protection.distance(geom_local))


def _build_standard_evidence(
    *,
    features: list[dict[str, Any]],
    metrics: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "features": features,
        "metrics": metrics,
        "sample_hits": [{"id": item.get("id"), "distance_m": item.get("distance_m")} for item in features[:8]],
    }
    if extra:
        payload.update(extra)
    return payload


def _evaluate_authoritative_layers(
    *,
    factor: dict[str, Any],
    params: dict[str, Any],
    aircraft_type: str,
    geo_context: dict[str, Any],
) -> dict[str, Any] | None:
    layers = _load_authoritative_layers_for_factor(str(factor.get("id") or ""))
    if not layers:
        return None
    if not geo_context:
        return {
            "data_status": "auto_failed",
            "compliance": "unknown",
            "source_mode": "authoritative_import",
            "evidence": _build_standard_evidence(
                features=[],
                metrics={
                    "nearest_distance_m": None,
                    "hit_count": 0,
                    "threshold_m": None,
                    "basis": str(params.get("distance_basis") or "protection_zone"),
                    "confidence": CONFIDENCE_LOW,
                    "source": "authoritative",
                },
                extra={"reason": "missing_route_geometry"},
            ),
            "auto_value": {},
            "next_action": "Route geometry unavailable, unable to complete authoritative-layer evaluation.",
        }
    defaults = factor.get("default_thresholds") or {}
    fallback = defaults.get("micro") if aircraft_type == "micro" else defaults.get("light")
    threshold = _resolve_threshold(params, aircraft_type, fallback=fallback)
    basis = str(params.get("distance_basis") or defaults.get("basis") or "protection_zone")
    if basis not in {"centerline", "protection_zone"}:
        basis = "protection_zone"
    query_range_m = float(params.get("query_range_m") or max(300.0, float(threshold or 1000)))

    features: list[dict[str, Any]] = []
    nearest_distance: float | None = None
    for layer in layers:
        source_name = str(layer.get("name") or "authoritative")
        layer_geojson = layer.get("geojson") or {}
        layer_features = layer_geojson.get("features") if isinstance(layer_geojson, dict) else []
        if not isinstance(layer_features, list):
            continue
        for idx, feature in enumerate(layer_features):
            geometry = (feature or {}).get("geometry")
            if not geometry:
                continue
            distance_m = _geometry_distance_to_basis_m(geometry, geo_context, basis)
            if distance_m is None:
                continue
            if distance_m > query_range_m:
                continue
            if nearest_distance is None or distance_m < nearest_distance:
                nearest_distance = distance_m
            props = (feature or {}).get("properties") or {}
            fid = (
                str(props.get("id") or "")
                or str((feature or {}).get("id") or "")
                or f"layer-{layer.get('id')}-feature-{idx + 1}"
            )
            name = str(props.get("name") or props.get("title") or fid)
            features.append(
                {
                    "id": fid,
                    "name": name,
                    "distance_m": round(float(distance_m), 2),
                    "geometry": geometry,
                    "source": "authoritative",
                    "layer_id": layer.get("id"),
                    "layer_name": source_name,
                }
            )

    features.sort(key=lambda item: float(item.get("distance_m") or 0.0))
    hit_count = len(features)
    if nearest_distance is None:
        compliance = "pass" if threshold is not None else "unknown"
    elif threshold is None:
        compliance = "fail" if nearest_distance <= 0 else "unknown"
    else:
        compliance = "fail" if nearest_distance <= threshold else "pass"
    confidence = CONFIDENCE_HIGH if hit_count else CONFIDENCE_MEDIUM
    metrics = {
        "nearest_distance_m": round(float(nearest_distance), 2) if nearest_distance is not None else None,
        "hit_count": hit_count,
        "threshold_m": round(float(threshold), 2) if threshold is not None else None,
        "basis": basis,
        "confidence": confidence,
        "source": "authoritative",
        "query_range_m": round(float(query_range_m), 2),
    }
    return {
        "data_status": "auto_ok",
        "compliance": compliance,
        "source_mode": "authoritative_import",
        "evidence": _build_standard_evidence(features=features, metrics=metrics),
        "auto_value": {
            "nearest_distance_m": metrics["nearest_distance_m"],
            "hit_count": hit_count,
        },
        "next_action": (
            "Potential conflict detected in authoritative layer; please review and adjust route."
            if compliance == "fail"
            else "Authoritative-layer evaluation passed."
        ),
    }


def _evaluate_auto_query(
    *,
    factor: dict[str, Any],
    params: dict[str, Any],
    aircraft_type: str,
    geo_context: dict[str, Any],
    geo_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    defaults = factor.get("default_thresholds") or {}
    fallback_threshold = defaults.get("micro") if aircraft_type == "micro" else defaults.get("light")
    threshold = _resolve_threshold(params, aircraft_type, fallback=fallback_threshold)
    basis = str(params.get("distance_basis") or defaults.get("basis") or "protection_zone")
    if basis not in {"centerline", "protection_zone"}:
        basis = "protection_zone"
    if not geo_context:
        return {
            "data_status": "auto_failed",
            "compliance": "unknown",
            "source_mode": "auto_query",
            "evidence": _build_standard_evidence(
                features=[],
                metrics={
                    "nearest_distance_m": None,
                    "hit_count": 0,
                    "threshold_m": threshold,
                    "basis": basis,
                    "confidence": CONFIDENCE_LOW,
                    "source": "auto_query",
                },
                extra={"reason": "missing_route_geometry"},
            ),
            "auto_value": {},
            "next_action": "Route geometry is missing; unable to run auto-query evaluation.",
        }
    bounds = geo_context.get("protection_bounds_wgs84")
    if not bounds:
        return {
            "data_status": "auto_failed",
            "compliance": "unknown",
            "source_mode": "auto_query",
            "evidence": _build_standard_evidence(
                features=[],
                metrics={
                    "nearest_distance_m": None,
                    "hit_count": 0,
                    "threshold_m": threshold,
                    "basis": basis,
                    "confidence": CONFIDENCE_LOW,
                    "source": "auto_query",
                },
                extra={"reason": "missing_bounds"},
            ),
            "auto_value": {},
            "next_action": "Route protection-zone bounds are unavailable.",
        }

    timeout_s = float(params.get("query_timeout_s") or 25)
    query_range_m = float(params.get("query_range_m") or params.get("bbox_expand_m") or 3000)
    max_candidates = int(params.get("max_feature_count") or params.get("max_candidates") or 500)
    query_bounds = _expand_bounds(bounds, query_range_m)
    filters = factor.get("query_filters") or []
    geometry_expectation = str(factor.get("geometry_expectation") or "point")
    factor_id = str(factor.get("id") or "")
    terrain_samples = _extract_terrain_samples(geo_data) if geometry_expectation == "line" else []

    query_scope = "bbox_expand"
    try:
        if geometry_expectation == "line":
            candidates = _fetch_overpass_lines(filters, query_bounds, timeout_s=timeout_s, max_candidates=max_candidates)
        else:
            candidates = _fetch_overpass_points(filters, query_bounds, timeout_s=timeout_s, max_candidates=max_candidates)
            if not candidates and factor_id in _AREA_FALLBACK_QUERY_FACTORS:
                area_name = _AREA_FALLBACK_QUERY_FACTORS[factor_id]
                candidates = _fetch_overpass_points_by_area_name(
                    filters,
                    area_name,
                    timeout_s=max(timeout_s, 40.0),
                    max_candidates=max_candidates,
                )
                if candidates:
                    query_scope = f"area_fallback:{area_name}"
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, json.JSONDecodeError, ValueError) as exc:
        return {
            "data_status": "auto_failed",
            "compliance": "unknown",
            "source_mode": "auto_query",
            "evidence": _build_standard_evidence(
                features=[],
                metrics={
                    "nearest_distance_m": None,
                    "hit_count": 0,
                    "threshold_m": threshold,
                    "basis": basis,
                    "confidence": CONFIDENCE_LOW,
                    "source": "auto_query",
                    "query_range_m": round(float(query_range_m), 2),
                },
                extra={"reason": "query_failed", "error": str(exc)},
            ),
            "auto_value": {},
            "next_action": "Auto-query failed. Check network connectivity or adjust parameters and retry.",
        }

    raw_candidate_count = len(candidates)
    tunnel_excluded_count = 0
    if geometry_expectation == "line" and factor_id in _TUNNEL_EXEMPT_LINE_FACTORS:
        filtered_candidates: list[dict[str, Any]] = []
        for item in candidates:
            if _is_tunnel_like(item.get("tags")):
                tunnel_excluded_count += 1
                continue
            filtered_candidates.append(item)
        candidates = filtered_candidates
    effective_candidate_count = len(candidates)

    features: list[dict[str, Any]] = []
    nearest_distance: float | None = None
    nearest_id: str | None = None
    for item in candidates:
        if factor_id == "infra_aviation_electronics_hub":
            tags = item.get("tags") or {}
            tag_text = " ".join(f"{key}={value}" for key, value in tags.items()).lower()
            # Factor 12 is defined as waterway power-generation facilities.
            if any(token in tag_text for token in ("aeroway", "airport", "terminal", "navigationaid", "beacon")):
                continue
            if not any(token in tag_text for token in ("power=plant", "hydro", "hydroelectric", "waterway", "dam", "weir", "lock_gate", "generator:source")):
                continue
        if geometry_expectation == "line":
            distance_m = _line_distance_to_basis_m(item["coordinates"], geo_context, basis)
            geometry = {
                "type": "LineString",
                "coordinates": [[round(float(lon), 7), round(float(lat), 7)] for lon, lat in item["coordinates"]],
            }
            name = str((item.get("tags") or {}).get("name") or item.get("id") or "")
            line_surface = _estimate_line_surface_info(item["coordinates"], terrain_samples)
            if factor_id == "infra_high_voltage_powerline":
                tags = item.get("tags") or {}
                ground_avg = _to_float(line_surface.get("elevation_avg_m"))
                cable_height_m = _estimate_powerline_height_m(tags)
                if cable_height_m is None:
                    # Conservatively assume minimum typical overhead clearance when tags omit height.
                    cable_height_m = 18.0
                if ground_avg is not None:
                    line_surface["ground_elevation_avg_m"] = round(float(ground_avg), 2)
                    line_surface["elevation_avg_m"] = round(float(ground_avg) + float(cable_height_m), 2)
                line_surface["line_height_m"] = round(float(cable_height_m), 2)
        else:
            distance_m = _distance_to_basis_m(item["lon"], item["lat"], geo_context, basis)
            geometry = {"type": "Point", "coordinates": [round(float(item["lon"]), 7), round(float(item["lat"]), 7)]}
            name = str((item.get("tags") or {}).get("name") or item.get("id") or "")
            line_surface = {}
        if distance_m is None or distance_m > query_range_m:
            continue
        if nearest_distance is None or distance_m < nearest_distance:
            nearest_distance = distance_m
            nearest_id = str(item.get("id") or "")
        features.append(
            {
                "id": str(item.get("id") or ""),
                "name": name,
                "distance_m": round(float(distance_m), 2),
                "geometry": geometry,
                "source": "auto_query",
                **line_surface,
            }
        )

    features.sort(key=lambda feature: float(feature.get("distance_m") or 0.0))
    if nearest_distance is None:
        return {
            "data_status": "auto_ok",
            "compliance": "pass",
            "source_mode": "auto_query",
            "evidence": _build_standard_evidence(
                features=[],
                metrics={
                    "nearest_distance_m": None,
                    "hit_count": 0,
                    "threshold_m": threshold,
                    "basis": basis,
                    "confidence": CONFIDENCE_MEDIUM,
                    "source": "auto_query",
                    "query_range_m": round(float(query_range_m), 2),
                    "candidate_count": effective_candidate_count,
                    "raw_candidate_count": raw_candidate_count,
                    "tunnel_excluded_count": tunnel_excluded_count,
                    "query_scope": query_scope,
                },
            ),
            "auto_value": {"candidate_count": effective_candidate_count, "nearest_distance_m": None, "hit_count": 0},
            "next_action": (
                f"No matched objects found in query range (excluded tunnel-like segments: {tunnel_excluded_count})."
                if tunnel_excluded_count > 0
                else "No matched objects found in query range."
            ),
        }

    compliance = "fail" if (threshold is not None and nearest_distance <= threshold) else "pass"
    return {
        "data_status": "auto_ok",
        "compliance": compliance,
        "source_mode": "auto_query",
        "evidence": _build_standard_evidence(
            features=features,
            metrics={
                "nearest_distance_m": round(float(nearest_distance), 2),
                "hit_count": len(features),
                "threshold_m": threshold,
                "basis": basis,
                "confidence": CONFIDENCE_MEDIUM,
                    "source": "auto_query",
                    "query_range_m": round(float(query_range_m), 2),
                    "candidate_count": effective_candidate_count,
                    "raw_candidate_count": raw_candidate_count,
                    "tunnel_excluded_count": tunnel_excluded_count,
                    "query_scope": query_scope,
                },
                extra={"nearest_id": nearest_id},
            ),
        "auto_value": {
            "candidate_count": effective_candidate_count,
            "nearest_distance_m": round(float(nearest_distance), 2),
            "nearest_id": nearest_id,
            "hit_count": len(features),
        },
        "next_action": (
            f"Potential conflict detected; review and adjust route (excluded tunnel-like segments: {tunnel_excluded_count})."
            if (compliance == "fail" and tunnel_excluded_count > 0)
            else (
                "Potential conflict detected; review and adjust route."
                if compliance == "fail"
                else (
                    f"Auto-evaluation passed; keep review record (excluded tunnel-like segments: {tunnel_excluded_count})."
                    if tunnel_excluded_count > 0
                    else "Auto-evaluation passed; keep review record."
                )
            )
        ),
    }


def _evaluate_electrified_railway_query(
    *,
    factor: dict[str, Any],
    params: dict[str, Any],
    aircraft_type: str,
    geo_context: dict[str, Any],
) -> dict[str, Any]:
    threshold = _resolve_threshold(params, aircraft_type)
    if threshold is None:
        return {
            "data_status": "auto_failed",
            "compliance": "unknown",
            "source_mode": "auto_query",
            "evidence": {"reason": "missing_threshold"},
            "auto_value": {},
            "next_action": "Please configure threshold parameters and rerun.",
        }
    bounds = geo_context.get("protection_bounds_wgs84")
    if not bounds:
        return {
            "data_status": "auto_failed",
            "compliance": "unknown",
            "source_mode": "auto_query",
            "evidence": {"reason": "missing_bounds"},
            "auto_value": {},
            "next_action": "Unable to determine route bounds. Generate route geometry and retry.",
        }
    basis = str(params.get("distance_basis") or "protection_zone")
    if basis not in {"centerline", "protection_zone"}:
        basis = "protection_zone"
    timeout_s = float(params.get("query_timeout_s") or 25)
    query_range_m = float(params.get("query_range_m") or 500)
    max_features = int(params.get("max_line_features") or 80)
    query_bounds = _expand_bounds(bounds, max(50.0, query_range_m))
    filters = factor.get("query_filters") or []
    try:
        lines = _fetch_overpass_lines(
            filters,
            query_bounds,
            timeout_s=timeout_s,
            max_candidates=max_features,
        )
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, json.JSONDecodeError, ValueError) as exc:
        return {
            "data_status": "auto_failed",
            "compliance": "unknown",
            "source_mode": "auto_query",
            "evidence": {"reason": "query_failed", "error": str(exc)},
            "auto_value": {},
            "next_action": "Review required. Please validate and rerun.",
        }

    line_hits: list[dict[str, Any]] = []
    nearest = None
    nearest_id = None
    for item in lines:
        distance_m = _line_distance_to_basis_m(item["coordinates"], geo_context, basis)
        if distance_m is None:
            continue
        if distance_m > query_range_m:
            continue
        if nearest is None or distance_m < nearest:
            nearest = distance_m
            nearest_id = item["id"]
        line_hits.append(
            {
                "id": item["id"],
                "name": str((item.get("tags") or {}).get("name") or item["id"]),
                "distance_m": round(float(distance_m), 2),
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[round(lon, 7), round(lat, 7)] for lon, lat in item["coordinates"]],
                },
            }
        )

    line_hits.sort(key=lambda item: float(item.get("distance_m", 0.0)))
    if nearest is None:
        return {
            "data_status": "auto_ok",
            "compliance": "pass",
            "source_mode": "auto_query",
            "evidence": {
                "candidate_count": len(lines),
                "line_hit_count": 0,
                "nearest_distance_m": None,
                "threshold_m": threshold,
                "query_range_m": query_range_m,
                "distance_basis": basis,
                "line_hits": [],
            },
            "auto_value": {"candidate_count": len(lines), "nearest_distance_m": None, "line_hit_count": 0},
            "next_action": "Review required. Please validate and rerun.",
        }

    compliance = "fail" if nearest <= threshold else "pass"
    return {
        "data_status": "auto_ok",
        "compliance": compliance,
        "source_mode": "auto_query",
        "evidence": {
            "candidate_count": len(lines),
            "line_hit_count": len(line_hits),
            "nearest_distance_m": round(float(nearest), 2),
            "nearest_id": nearest_id,
            "threshold_m": threshold,
            "query_range_m": query_range_m,
            "distance_basis": basis,
            "line_hits": line_hits,
            "sample_hits": [{"id": item["id"], "distance_m": item["distance_m"]} for item in line_hits[:8]],
        },
        "auto_value": {
            "candidate_count": len(lines),
            "line_hit_count": len(line_hits),
            "nearest_distance_m": round(float(nearest), 2),
            "nearest_id": nearest_id,
        },
        "next_action": "Review required. Please validate and rerun.",
    }


def _evaluate_auto_db(
    *,
    factor: dict[str, Any],
    params: dict[str, Any],
    aircraft_type: str,
    geo_data: dict[str, Any] | None,
) -> dict[str, Any]:
    defaults = factor.get("default_thresholds") or {}
    fallback_threshold = defaults.get("micro") if aircraft_type == "micro" else defaults.get("light")
    threshold = _resolve_threshold(params, aircraft_type, fallback=fallback_threshold)
    basis = str(params.get("distance_basis") or defaults.get("basis") or "protection_zone")
    query_range_m = float(params.get("query_range_m") or max(300.0, float(threshold or 1000)))
    if not geo_data:
        return {
            "data_status": "auto_failed",
            "compliance": "unknown",
            "source_mode": "auto_db",
            "evidence": _build_standard_evidence(
                features=[],
                metrics={
                    "nearest_distance_m": None,
                    "hit_count": 0,
                    "threshold_m": threshold,
                    "basis": basis,
                    "confidence": CONFIDENCE_LOW,
                    "source": "auto_db",
                    "query_range_m": round(float(query_range_m), 2),
                },
                extra={"reason": "missing_geo_data"},
            ),
            "auto_value": {},
            "next_action": "Review required. Please validate and rerun.",
        }
    buildings = ((geo_data.get("buildings") or {}).get("items") or [])
    keywords = [str(item).lower() for item in (factor.get("db_keywords") or []) if str(item).strip()]
    features: list[dict[str, Any]] = []
    nearest_distance: float | None = None
    def _keyword_matches(word: str, name: str, btype: str, raw_tags: dict, full_text: str) -> bool:
        w = word.lower().strip()
        if not w:
            return False
        if "=" in w:
            k, v = w.split("=", 1)
            k = k.strip()
            v = v.strip()
            for rk, rv in raw_tags.items():
                if str(rk).lower().strip() == k and str(rv).lower().strip() == v:
                    return True
            if btype.lower().strip() == v:
                return True
            return w in full_text
        if any('\u4e00' <= ch <= '\u9fff' for ch in w):
            return w in full_text
        pattern = re.compile(r'(?<![a-z0-9_])' + re.escape(w) + r'(?![a-z0-9_])')
        return bool(pattern.search(full_text))

    for building in buildings:
        name = str(building.get("name") or "")
        btype = str(building.get("building_type") or "")
        raw_tags = building.get("raw_tags") or {}
        raw_text = " ".join(f"{key}:{value}" for key, value in raw_tags.items())
        full_text = f"{name} {btype} {raw_text}".lower()
        if keywords and not any(_keyword_matches(word, name, btype, raw_tags, full_text) for word in keywords):
            continue
        lon = building.get("longitude")
        lat = building.get("latitude")
        distance_m = building.get("distance_to_route_m")
        try:
            lon_f = float(lon)
            lat_f = float(lat)
            distance_f = float(distance_m)
        except (TypeError, ValueError):
            continue
        if distance_f > query_range_m:
            continue
        if nearest_distance is None or distance_f < nearest_distance:
            nearest_distance = distance_f
        features.append(
            {
                "id": str(building.get("id") or ""),
                "name": name or str(building.get("id") or ""),
                "distance_m": round(distance_f, 2),
                "geometry": {"type": "Point", "coordinates": [round(lon_f, 7), round(lat_f, 7)]},
                "source": "geo_db",
            }
        )
    features.sort(key=lambda item: float(item.get("distance_m") or 0.0))
    if nearest_distance is None:
        return {
            "data_status": "auto_ok",
            "compliance": "pass",
            "source_mode": "auto_db",
            "evidence": _build_standard_evidence(
                features=[],
                metrics={
                    "nearest_distance_m": None,
                    "hit_count": 0,
                    "threshold_m": threshold,
                    "basis": basis,
                    "confidence": CONFIDENCE_MEDIUM,
                    "source": "auto_db",
                    "query_range_m": round(float(query_range_m), 2),
                },
            ),
            "auto_value": {"hit_count": 0, "nearest_distance_m": None},
            "next_action": "Review required. Please validate and rerun.",
        }
    compliance = "fail" if (threshold is not None and nearest_distance <= threshold) else "pass"
    return {
        "data_status": "auto_ok",
        "compliance": compliance,
        "source_mode": "auto_db",
        "evidence": _build_standard_evidence(
            features=features,
            metrics={
                "nearest_distance_m": round(float(nearest_distance), 2),
                "hit_count": len(features),
                "threshold_m": threshold,
                "basis": basis,
                "confidence": CONFIDENCE_MEDIUM,
                "source": "auto_db",
                "query_range_m": round(float(query_range_m), 2),
            },
        ),
        "auto_value": {"hit_count": len(features), "nearest_distance_m": round(float(nearest_distance), 2)},
        "next_action": "Review required. Please validate and rerun.",
    }


def _merge_params(factor: dict[str, Any], saved_params: dict[str, Any] | None, override_params: dict[str, Any] | None) -> dict[str, Any]:
    params = dict(factor.get("default_params") or {})
    if saved_params:
        params.update(saved_params)
    if override_params:
        params.update(override_params)
    return params


def _normalize_evidence_payload(
    evidence: dict[str, Any] | None,
    *,
    source_mode: str,
    threshold: float | None,
    basis: str,
) -> dict[str, Any]:
    payload = evidence if isinstance(evidence, dict) else {}
    features = payload.get("features")
    if not isinstance(features, list):
        features = []
    if not features:
        line_hits = payload.get("line_hits")
        if isinstance(line_hits, list):
            for item in line_hits:
                geometry = (item or {}).get("geometry")
                if not geometry:
                    continue
                features.append(
                    {
                        "id": str((item or {}).get("id") or ""),
                        "name": str((item or {}).get("name") or (item or {}).get("id") or ""),
                        "distance_m": (item or {}).get("distance_m"),
                        "geometry": geometry,
                        "source": source_mode,
                    }
                )
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    nearest_distance = metrics.get("nearest_distance_m")
    if nearest_distance is None:
        nearest_distance = payload.get("nearest_distance_m")
    if nearest_distance is None and features:
        try:
            nearest_distance = min(float(item.get("distance_m")) for item in features if item.get("distance_m") is not None)
        except ValueError:
            nearest_distance = None
    hit_count = metrics.get("hit_count")
    if not isinstance(hit_count, int):
        hit_count = len(features)
    normalized_metrics = {
        "nearest_distance_m": nearest_distance,
        "hit_count": hit_count,
        "threshold_m": metrics.get("threshold_m", threshold),
        "basis": metrics.get("basis", basis),
        "confidence": metrics.get("confidence", CONFIDENCE_MEDIUM if hit_count else CONFIDENCE_LOW),
        "source": metrics.get("source", source_mode),
    }
    for metric_key in ("query_range_m", "candidate_count", "raw_candidate_count", "tunnel_excluded_count"):
        if metric_key in metrics:
            normalized_metrics[metric_key] = metrics.get(metric_key)
        elif metric_key in payload:
            normalized_metrics[metric_key] = payload.get(metric_key)
    extra = dict(payload)
    extra.pop("features", None)
    extra.pop("metrics", None)
    return _build_standard_evidence(features=features, metrics=normalized_metrics, extra=extra)


def _build_unknown_result(
    *,
    source_mode: str,
    threshold: float | None,
    basis: str,
    reason: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "data_status": "auto_failed",
        "compliance": "unknown",
        "source_mode": source_mode,
        "evidence": _build_standard_evidence(
            features=[],
            metrics={
                "nearest_distance_m": None,
                "hit_count": 0,
                "threshold_m": threshold,
                "basis": basis,
                "confidence": CONFIDENCE_LOW,
                "source": source_mode,
            },
            extra={"reason": reason},
        ),
        "auto_value": {},
        "next_action": next_action,
    }


def _evaluate_by_capability(
    *,
    capability: str,
    factor: dict[str, Any],
    params: dict[str, Any],
    aircraft_type: str,
    geo_data: dict[str, Any] | None,
    geo_context: dict[str, Any],
) -> dict[str, Any] | None:
    if capability == "auto_query":
        return _evaluate_auto_query(
            factor=factor,
            params=params,
            aircraft_type=aircraft_type,
            geo_context=geo_context,
            geo_data=geo_data,
        )
    if capability == "auto_db":
        return _evaluate_auto_db(
            factor=factor,
            params=params,
            aircraft_type=aircraft_type,
            geo_data=geo_data,
        )
    return None


def _evaluate_factor(
    *,
    factor: dict[str, Any],
    factor_input: dict[str, Any],
    effective_params: dict[str, Any],
    aircraft_type: str,
    geo_data: dict[str, Any] | None,
    geo_context: dict[str, Any],
) -> dict[str, Any]:
    input_mode = str((factor_input or {}).get("input_mode") or "auto").strip().lower()
    if input_mode not in INPUT_MODE_VALUES:
        input_mode = "auto"

    defaults = factor.get("default_thresholds") or {}
    fallback_threshold = defaults.get("micro") if aircraft_type == "micro" else defaults.get("light")
    threshold = _resolve_threshold(effective_params, aircraft_type, fallback=fallback_threshold)
    basis = str(effective_params.get("distance_basis") or defaults.get("basis") or "protection_zone")
    if basis not in {"centerline", "protection_zone"}:
        basis = "protection_zone"

    manual_override = _read_manual_override((factor_input or {}).get("manual_value"))
    if input_mode == "manual" and manual_override:
        evidence = _normalize_evidence_payload(
            {"notes": manual_override.get("notes", "")},
            source_mode="manual",
            threshold=threshold,
            basis=basis,
        )
        return {
            "factor_id": factor["id"],
            "data_status": "manual_ok",
            "compliance": manual_override["compliance"],
            "source_mode": "manual",
            "evidence": evidence,
            "next_action": "Manual override applied. Keep auditable data source records.",
            "auto_value": {},
            "selected_value": manual_override,
            "effective_params": effective_params,
            "input_mode": input_mode,
            "manual_override": True,
        }
    if input_mode == "manual" and not manual_override:
        return {
            "factor_id": factor["id"],
            "data_status": "manual_required",
            "compliance": "unknown",
            "source_mode": "manual",
            "evidence": _normalize_evidence_payload(
                {"reason": "manual_value_missing"},
                source_mode="manual",
                threshold=threshold,
                basis=basis,
            ),
            "next_action": "Please choose pass or fail in manual mode, then run analysis again.",
            "auto_value": {},
            "selected_value": {},
            "effective_params": effective_params,
            "input_mode": input_mode,
            "manual_override": False,
        }

    capability = str(factor.get("capability") or "")
    data_source_mode = str(factor.get("data_source_mode") or "")

    authoritative_result = _evaluate_authoritative_layers(
        factor=factor,
        params=effective_params,
        aircraft_type=aircraft_type,
        geo_context=geo_context,
    )
    auto_result = _evaluate_by_capability(
        capability=capability,
        factor=factor,
        params=effective_params,
        aircraft_type=aircraft_type,
        geo_data=geo_data,
        geo_context=geo_context,
    )

    if data_source_mode == "authoritative_import_required":
        result = authoritative_result or _build_unknown_result(
            source_mode="authoritative_import",
            threshold=threshold,
            basis=basis,
            reason="authoritative_data_missing",
            next_action=factor.get("next_action_template") or "Import authoritative data and rerun this factor.",
        )
    elif data_source_mode in {"import_primary_auto_secondary", "import_primary_optional_auto"}:
        if authoritative_result:
            result = authoritative_result
        elif auto_result:
            result = auto_result
        else:
            result = _build_unknown_result(
                source_mode="authoritative_import",
                threshold=threshold,
                basis=basis,
                reason="authoritative_data_missing",
                next_action=factor.get("next_action_template") or "Import authoritative data and rerun this factor.",
            )
    elif data_source_mode in {"auto_query_with_authoritative", "auto_db_with_authoritative"}:
        if authoritative_result:
            result = authoritative_result
        elif auto_result:
            result = auto_result
        else:
            result = _build_unknown_result(
                source_mode=data_source_mode,
                threshold=threshold,
                basis=basis,
                reason="auto_engine_unavailable",
                next_action=factor.get("next_action_template") or "Check data source connectivity and rerun this factor.",
            )
    elif data_source_mode == "auto_query_import_fallback":
        if auto_result and str(auto_result.get("data_status")) == "auto_ok":
            result = auto_result
        elif authoritative_result:
            result = authoritative_result
        elif auto_result:
            result = auto_result
        else:
            result = _build_unknown_result(
                source_mode="auto_query",
                threshold=threshold,
                basis=basis,
                reason="auto_and_authoritative_missing",
                next_action=factor.get("next_action_template") or "Auto query failed. Import authoritative data and rerun.",
            )
    else:
        if auto_result:
            result = auto_result
        elif authoritative_result:
            result = authoritative_result
        elif capability == "manual_required":
            result = {
                "data_status": "manual_required",
                "compliance": "unknown",
                "source_mode": "manual_required",
                "evidence": {"reason": "manual_required"},
                "next_action": factor.get("next_action_template"),
                "auto_value": {},
            }
        else:
            result = _build_unknown_result(
                source_mode="unknown",
                threshold=threshold,
                basis=basis,
                reason="unsupported_capability",
                next_action="Factor capability is not configured. Check factor catalog metadata.",
            )

    normalized_evidence = _normalize_evidence_payload(
        result.get("evidence"),
        source_mode=str(result.get("source_mode") or "unknown"),
        threshold=threshold,
        basis=basis,
    )

    selected_value = dict(result.get("auto_value") or {})
    selected_value["compliance"] = result.get("compliance")
    return {
        "factor_id": factor["id"],
        "data_status": result["data_status"],
        "compliance": result["compliance"],
        "source_mode": result["source_mode"],
        "evidence": normalized_evidence,
        "next_action": result.get("next_action"),
        "auto_value": result.get("auto_value") or {},
        "selected_value": selected_value,
        "effective_params": effective_params,
        "input_mode": input_mode,
        "manual_override": False,
    }

def _insert_run(route_id: int, aircraft_type: str, factor_ids: list[str]) -> int:
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO route_analysis_runs (route_id, aircraft_type, scope_json, total_count, pass_count, fail_count, unknown_count, success_rate, duration_ms)
            VALUES (?, ?, ?, 0, 0, 0, 0, 0, 0)
            """,
            (route_id, aircraft_type, _json_dump({"factor_ids": factor_ids})),
        )
        return int(cursor.lastrowid)


def _update_run_summary(run_id: int, *, total: int, pass_count: int, fail_count: int, unknown_count: int, duration_ms: int) -> None:
    success_rate = round((pass_count / total) if total else 0.0, 4)
    with db_cursor() as cursor:
        cursor.execute(
            """
            UPDATE route_analysis_runs
            SET total_count=?, pass_count=?, fail_count=?, unknown_count=?, success_rate=?, duration_ms=?
            WHERE id=?
            """,
            (total, pass_count, fail_count, unknown_count, success_rate, duration_ms, run_id),
        )


def _persist_factor_result(route_id: int, run_id: int, aircraft_type: str, result: dict[str, Any]) -> None:
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO route_analysis_factor_results (
                route_id, run_id, factor_id, aircraft_type, data_status, compliance, source_mode,
                evidence_json, next_action, auto_value_json, selected_value_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(route_id, factor_id) DO UPDATE SET
                run_id=excluded.run_id,
                aircraft_type=excluded.aircraft_type,
                data_status=excluded.data_status,
                compliance=excluded.compliance,
                source_mode=excluded.source_mode,
                evidence_json=excluded.evidence_json,
                next_action=excluded.next_action,
                auto_value_json=excluded.auto_value_json,
                selected_value_json=excluded.selected_value_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                route_id,
                run_id,
                result["factor_id"],
                aircraft_type,
                result["data_status"],
                result["compliance"],
                result["source_mode"],
                _json_dump(result.get("evidence") or {}),
                result.get("next_action"),
                _json_dump(result.get("auto_value") or {}),
                _json_dump(result.get("selected_value") or {}),
            ),
        )


def run_route_analysis(
    route_id: int,
    *,
    aircraft_type: str = "micro",
    factor_ids: list[str] | None = None,
    param_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    route = get_route(route_id)
    if not route:
        raise ValueError("Route not found")
    normalized_aircraft = _normalize_aircraft_type(aircraft_type)
    factor_map = get_factor_map()
    target_ids = [factor_id for factor_id in (factor_ids or list(factor_map.keys())) if factor_id]
    if not target_ids:
        raise ValueError("factor_ids is empty")
    unknown_ids = [factor_id for factor_id in target_ids if factor_id not in factor_map]
    if unknown_ids:
        raise ValueError(f"Unknown factor_ids: {', '.join(unknown_ids)}")
    snapshot = _get_snapshot(route_id)
    try:
        geo_data = get_route_geo_data(route_id)
    except ValueError:
        geo_data = None
    geo_context = _build_geo_context(snapshot)
    factor_inputs = _load_factor_inputs(route_id)
    overrides = param_overrides or {}
    run_id = _insert_run(route_id, normalized_aircraft, target_ids)
    start_ts = time.perf_counter()
    results: list[dict[str, Any]] = []
    for factor_id in target_ids:
        factor = factor_map[factor_id]
        factor_input = factor_inputs.get(factor_id, {"input_mode": "auto", "manual_value": {}, "params": {}})
        effective_params = _merge_params(
            factor,
            saved_params=factor_input.get("params") or {},
            override_params=overrides.get(factor_id) or {},
        )
        result = _evaluate_factor(
            factor=factor,
            factor_input=factor_input,
            effective_params=effective_params,
            aircraft_type=normalized_aircraft,
            geo_data=geo_data,
            geo_context=geo_context,
        )
        _persist_factor_result(route_id, run_id, normalized_aircraft, result)
        result_payload = {
            "factor_id": factor_id,
            "factor_name": factor["name"],
            "category_id": factor["category_id"],
            "data_status": result["data_status"],
            "compliance": result["compliance"],
            "source_mode": result["source_mode"],
            "evidence": result["evidence"],
            "next_action": result["next_action"],
            "effective_params": result["effective_params"],
            "manual_override": result["manual_override"],
        }
        results.append(result_payload)
    duration_ms = int((time.perf_counter() - start_ts) * 1000)
    total = len(results)
    pass_count = sum(1 for item in results if item["compliance"] == "pass")
    fail_count = sum(1 for item in results if item["compliance"] == "fail")
    unknown_count = total - pass_count - fail_count
    _update_run_summary(
        run_id,
        total=total,
        pass_count=pass_count,
        fail_count=fail_count,
        unknown_count=unknown_count,
        duration_ms=duration_ms,
    )
    return {
        "ok": True,
        "run_id": run_id,
        "route_id": route_id,
        "route_name": route.get("name"),
        "aircraft_type": normalized_aircraft,
        "summary": {
            "total_count": total,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "unknown_count": unknown_count,
            "success_rate": round((pass_count / total) if total else 0.0, 4),
            "duration_ms": duration_ms,
        },
        "results": results,
    }
