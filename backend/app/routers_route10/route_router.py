from fastapi import APIRouter, HTTPException

from app.database_route import db_cursor
from app.models.route_schemas import (
    LandingSiteCreate,
    LandingSiteUpdate,
    RouteCloneRequest,
    RouteCreate,
    RouteGeoExtractRequest,
    RoutePointCreate,
    RoutePointUpdate,
    RouteResponse,
    SubRouteExtractRequest,
    TakeoffFlightPlanRequest,
    RouteUpdate,
)
from app.services.geo_service import extract_route_geo_data, get_route_geo_data
from app.services.route_service import (
    assess_route_completeness,
    duplicate_route,
    extract_sub_route_as_new_route,
    generate_route_geometry,
    get_route_full_state,
    get_landing_sites,
    get_points,
    get_route,
    invalidate_route_full_state,
    list_routes,
    update_route_full_state_route_name,
    validate_route_metadata,
)
from app.services.takeoff_flight_service import (
    calculate_takeoff_flight_plan,
    get_takeoff_flight_state,
    list_takeoff_flight_plans,
    suggest_landing_elevation,
)

router = APIRouter(prefix="", tags=["routes"])


@router.post("/routes", response_model=RouteResponse)
def create_route(payload: RouteCreate):
    metadata_errors = validate_route_metadata(payload.model_dump())
    if metadata_errors:
        raise HTTPException(status_code=400, detail=metadata_errors)
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
                payload.name,
                payload.flight_width,
                payload.protection_width,
                payload.bottom_height,
                payload.top_height,
                payload.min_turn_radius,
                payload.turn_mode,
                payload.altitude_reference_mode,
                payload.altitude_change_min,
                1 if payload.enable_layering else 0,
                payload.layer_step,
                payload.layer_scheme,
            ),
        )
        route_id = cursor.lastrowid
    route = get_route(route_id)
    return RouteResponse(**route)


@router.get("/routes")
def get_route_list():
    return {"items": list_routes()}


@router.get("/routes/{route_id}", response_model=RouteResponse)
def get_route_by_id(route_id: int):
    route = get_route(route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return RouteResponse(**route)


@router.get("/routes/{route_id}/completeness")
def get_route_completeness(route_id: int):
    try:
        return assess_route_completeness(route_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/routes/{route_id}/full")
def get_full_route_by_id(route_id: int):
    route = get_route(route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    full_state = get_route_full_state(route_id)
    if not full_state:
        raise HTTPException(status_code=404, detail="Full route state not found, please generate route first")
    return full_state


@router.put("/routes/{route_id}", response_model=RouteResponse)
def update_route(route_id: int, payload: RouteUpdate):
    current_route = get_route(route_id)
    if not current_route:
        raise HTTPException(status_code=404, detail="Route not found")
    metadata_errors = validate_route_metadata(payload.model_dump())
    if metadata_errors:
        raise HTTPException(status_code=400, detail=metadata_errors)
    geometry_fields = [
        "flight_width",
        "protection_width",
        "bottom_height",
        "top_height",
        "min_turn_radius",
        "turn_mode",
        "altitude_reference_mode",
        "altitude_change_min",
        "enable_layering",
        "layer_step",
        "layer_scheme",
    ]
    geometry_changed = any(current_route.get(field) != getattr(payload, field) for field in geometry_fields)
    with db_cursor() as cursor:
        cursor.execute(
            """
            UPDATE routes
            SET name=?, flight_width=?, protection_width=?, bottom_height=?, top_height=?,
                min_turn_radius=?, turn_mode=?, altitude_reference_mode=?, altitude_change_min=?,
                enable_layering=?, layer_step=?, layer_scheme=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                payload.name,
                payload.flight_width,
                payload.protection_width,
                payload.bottom_height,
                payload.top_height,
                payload.min_turn_radius,
                payload.turn_mode,
                payload.altitude_reference_mode,
                payload.altitude_change_min,
                1 if payload.enable_layering else 0,
                payload.layer_step,
                payload.layer_scheme,
                route_id,
            ),
        )
    if geometry_changed:
        invalidate_route_full_state(route_id)
    else:
        update_route_full_state_route_name(route_id, payload.name)
    return RouteResponse(**get_route(route_id))


@router.delete("/routes/{route_id}")
def delete_route(route_id: int):
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM routes WHERE id=?", (route_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Route not found")
    return {"ok": True}


@router.post("/routes/{route_id}/duplicate", response_model=RouteResponse)
def clone_route(route_id: int, payload: RouteCloneRequest):
    try:
        cloned = duplicate_route(route_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RouteResponse(**cloned)


@router.post("/routes/{route_id}/points")
def create_point(route_id: int, payload: RoutePointCreate):
    if not get_route(route_id):
        raise HTTPException(status_code=404, detail="Route not found")
    order_index = payload.order_index
    if order_index is None:
        with db_cursor() as cursor:
            cursor.execute("SELECT COALESCE(MAX(order_index), -1) + 1 FROM route_points WHERE route_id=?", (route_id,))
            order_index = int(cursor.fetchone()[0])
    else:
        with db_cursor() as cursor:
            cursor.execute(
                "UPDATE route_points SET order_index = order_index + 1 WHERE route_id = ? AND order_index >= ?",
                (route_id, order_index)
            )
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO route_points (route_id, name, point_type, longitude, latitude, altitude, order_index)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                route_id,
                payload.name,
                payload.point_type,
                payload.longitude,
                payload.latitude,
                payload.altitude,
                order_index,
            ),
        )
        point_id = cursor.lastrowid
    invalidate_route_full_state(route_id)
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM route_points WHERE id=?", (point_id,))
        return dict(cursor.fetchone())


@router.put("/routes/{route_id}/points/{point_id}")
def update_point(route_id: int, point_id: int, payload: RoutePointUpdate):
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM route_points WHERE id=? AND route_id=?", (point_id, route_id))
        current = cursor.fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="Point not found")
    resolved_order_index = payload.order_index if payload.order_index is not None else current["order_index"]
    with db_cursor() as cursor:
        cursor.execute(
            """
            UPDATE route_points
            SET name=?, point_type=?, longitude=?, latitude=?, altitude=?, order_index=?
            WHERE id=? AND route_id=?
            """,
            (
                payload.name,
                payload.point_type,
                payload.longitude,
                payload.latitude,
                payload.altitude,
                resolved_order_index,
                point_id,
                route_id,
            ),
        )
    invalidate_route_full_state(route_id)
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM route_points WHERE id=?", (point_id,))
        return dict(cursor.fetchone())


@router.delete("/routes/{route_id}/points/{point_id}")
def delete_point(route_id: int, point_id: int):
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM route_points WHERE id=? AND route_id=?", (point_id, route_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Point not found")
    invalidate_route_full_state(route_id)
    return {"ok": True}


@router.get("/routes/{route_id}/points")
def list_points(route_id: int):
    return {"items": get_points(route_id)}


@router.post("/routes/{route_id}/landing-sites")
def create_landing_site(route_id: int, payload: LandingSiteCreate):
    if not get_route(route_id):
        raise HTTPException(status_code=404, detail="Route not found")
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO landing_sites (
                route_id, name, longitude, latitude, altitude,
                altitude_source, altitude_confirmed, altitude_confirmed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
            """,
            (
                route_id,
                payload.name,
                payload.longitude,
                payload.latitude,
                payload.altitude,
                payload.altitude_source,
                1 if payload.altitude_confirmed else 0,
                1 if payload.altitude_confirmed else 0,
            ),
        )
        landing_id = cursor.lastrowid
    invalidate_route_full_state(route_id)
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM landing_sites WHERE id=?", (landing_id,))
        return dict(cursor.fetchone())


@router.get("/routes/{route_id}/landing-sites")
def list_landing_sites(route_id: int):
    return {"items": get_landing_sites(route_id)}


@router.put("/routes/{route_id}/landing-sites/{landing_id}")
def update_landing_site(route_id: int, landing_id: int, payload: LandingSiteUpdate):
    if not get_route(route_id):
        raise HTTPException(status_code=404, detail="Route not found")
    with db_cursor() as cursor:
        cursor.execute(
            """
            UPDATE landing_sites
            SET name=?, longitude=?, latitude=?, altitude=?,
                altitude_source=?, altitude_confirmed=?,
                altitude_confirmed_at=CASE WHEN ? THEN COALESCE(altitude_confirmed_at, CURRENT_TIMESTAMP) ELSE NULL END
            WHERE id=? AND route_id=?
            """,
            (
                payload.name,
                payload.longitude,
                payload.latitude,
                payload.altitude,
                payload.altitude_source,
                1 if payload.altitude_confirmed else 0,
                1 if payload.altitude_confirmed else 0,
                landing_id,
                route_id,
            ),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Landing site not found")
    invalidate_route_full_state(route_id)
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM landing_sites WHERE id=? AND route_id=?", (landing_id, route_id))
        return dict(cursor.fetchone())


@router.delete("/routes/{route_id}/landing-sites/{landing_id}")
def delete_landing_site(route_id: int, landing_id: int):
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM landing_sites WHERE id=? AND route_id=?", (landing_id, route_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Landing site not found")
    invalidate_route_full_state(route_id)
    return {"ok": True}


@router.get("/routes/{route_id}/takeoff-flight")
def read_takeoff_flight_state(route_id: int):
    return get_takeoff_flight_state(route_id)


@router.post("/routes/{route_id}/landing-sites/{landing_id}/elevation/suggest")
def suggest_takeoff_landing_elevation(route_id: int, landing_id: int):
    return suggest_landing_elevation(route_id, landing_id)


@router.post("/routes/{route_id}/takeoff-flight/preview")
def preview_takeoff_flight_plan(route_id: int, payload: TakeoffFlightPlanRequest):
    return calculate_takeoff_flight_plan(route_id, payload.model_dump(), persist=False)


@router.post("/routes/{route_id}/takeoff-flight/plans")
def create_takeoff_flight_plan(route_id: int, payload: TakeoffFlightPlanRequest):
    return calculate_takeoff_flight_plan(route_id, payload.model_dump(), persist=True)


@router.get("/routes/{route_id}/takeoff-flight/plans")
def read_takeoff_flight_plans(route_id: int):
    return {"items": list_takeoff_flight_plans(route_id)}


@router.post("/routes/{route_id}/generate")
def generate_route(route_id: int):
    result = generate_route_geometry(route_id)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["errors"])
    return result


@router.post("/routes/{route_id}/geo/extract")
def extract_route_geo(route_id: int, payload: RouteGeoExtractRequest | None = None):
    try:
        datasource_url = payload.datasource_url if payload else None
        return extract_route_geo_data(route_id, datasource_url=datasource_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/routes/{route_id}/geo")
def get_route_geo(route_id: int):
    try:
        result = get_route_geo_data(route_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Geo extraction data not found for route")
    return result


@router.post("/routes/{route_id}/sub-routes/{sequence}/extract", response_model=RouteResponse)
def extract_sub_route(route_id: int, sequence: int, payload: SubRouteExtractRequest):
    try:
        extracted = extract_sub_route_as_new_route(route_id, sequence, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RouteResponse(**extracted)
