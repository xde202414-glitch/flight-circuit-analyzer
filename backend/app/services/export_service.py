from datetime import datetime
from pathlib import Path
import zipfile
from xml.etree.ElementTree import Element, SubElement, tostring

import geopandas as gpd

from app.config import EXPORT_DIR
from app.services.route_service import generate_route_geometry, get_points, get_route


def _coord_text(coords: list[list[float]]) -> str:
    return " ".join(f"{lon:.8f},{lat:.8f},0" for lon, lat in coords)


def _line_placemark(parent: Element, name: str, coords: list[list[float]], description: str | None = None) -> None:
    pm = SubElement(parent, "Placemark")
    SubElement(pm, "name").text = name
    if description:
        SubElement(pm, "description").text = description
    line = SubElement(pm, "LineString")
    SubElement(line, "tessellate").text = "1"
    SubElement(line, "altitudeMode").text = "clampToGround"
    SubElement(line, "coordinates").text = _coord_text(coords)


def _point_placemark(parent: Element, name: str, lon: float, lat: float, description: str | None = None) -> None:
    pm = SubElement(parent, "Placemark")
    SubElement(pm, "name").text = name
    if description:
        SubElement(pm, "description").text = description
    point = SubElement(pm, "Point")
    SubElement(point, "altitudeMode").text = "clampToGround"
    SubElement(point, "coordinates").text = f"{lon:.8f},{lat:.8f},0"


def _polygon_placemark(parent: Element, name: str, ring_coords: list[list[float]], description: str | None = None) -> None:
    pm = SubElement(parent, "Placemark")
    SubElement(pm, "name").text = name
    if description:
        SubElement(pm, "description").text = description
    poly = SubElement(pm, "Polygon")
    SubElement(poly, "tessellate").text = "1"
    SubElement(poly, "altitudeMode").text = "clampToGround"
    outer = SubElement(poly, "outerBoundaryIs")
    linear_ring = SubElement(outer, "LinearRing")
    SubElement(linear_ring, "coordinates").text = _coord_text(ring_coords)


def _extract_protection_rings(protection_geo: dict | None) -> list[list[list[float]]]:
    if not isinstance(protection_geo, dict):
        return []
    geo_type = str(protection_geo.get("type") or "")
    coords = protection_geo.get("coordinates")
    if geo_type == "Polygon" and isinstance(coords, (list, tuple)) and coords:
        ring = coords[0]
        return [ring] if isinstance(ring, (list, tuple)) else []
    if geo_type == "MultiPolygon" and isinstance(coords, (list, tuple)):
        rings: list[list[list[float]]] = []
        for polygon in coords:
            if isinstance(polygon, (list, tuple)) and polygon:
                ring = polygon[0]
                if isinstance(ring, (list, tuple)):
                    rings.append(ring)
        return rings
    return []


def export_kml(route_id: int) -> tuple[bytes, str, bool]:
    route = get_route(route_id)
    if not route:
        raise ValueError(f"Route not found: {route_id}")

    points = get_points(route_id)
    if len(points) < 2:
        raise ValueError("Not enough route points, at least start and end are required")

    ordered_points = sorted(points, key=lambda point: (int(point["order_index"]), int(point["id"])))
    line_coords: list[list[float]] = [[float(point["longitude"]), float(point["latitude"])] for point in ordered_points]

    kml = Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    document = SubElement(kml, "Document")
    SubElement(document, "name").text = f"{route['name']} - WGS84"
    SubElement(document, "description").text = (
        "Coordinate Reference System: WGS-84 (EPSG:4326). "
        "Contains route start/waypoints/end points, route centerline and protection zone when available."
    )

    points_folder = SubElement(document, "Folder")
    SubElement(points_folder, "name").text = "Route Points (WGS-84)"
    for point in ordered_points:
        point_type = str(point["point_type"])
        order_index = int(point["order_index"])
        point_name = str(point["name"] or f"P{order_index + 1}")
        if point_type == "start":
            label = f"Start: {point_name}"
        elif point_type == "end":
            label = f"End: {point_name}"
        else:
            label = f"Waypoint {order_index}: {point_name}"
        _point_placemark(
            points_folder,
            label,
            float(point["longitude"]),
            float(point["latitude"]),
            description=f"type={point_type}, order_index={order_index}, CRS=WGS-84",
        )

    line_folder = SubElement(document, "Folder")
    SubElement(line_folder, "name").text = "Route Line (WGS-84)"
    _line_placemark(
        line_folder,
        "Route Centerline",
        line_coords,
        description="Route polyline built from start -> waypoints (ascending order) -> end, CRS=WGS-84",
    )

    has_protection_zone = False
    generated = generate_route_geometry(route_id, persist_full_state=False)
    if generated.get("ok"):
        protection_geo = generated.get("protection_zone")
        protection_rings = _extract_protection_rings(protection_geo if isinstance(protection_geo, dict) else None)
        if protection_rings:
            has_protection_zone = True
            protection_folder = SubElement(document, "Folder")
            SubElement(protection_folder, "name").text = "Protection Zone (WGS-84)"
            if len(protection_rings) == 1:
                _polygon_placemark(
                    protection_folder,
                    "Protection Zone",
                    protection_rings[0],
                    description="Protection zone polygon, CRS=WGS-84",
                )
            else:
                for index, ring in enumerate(protection_rings, start=1):
                    _polygon_placemark(
                        protection_folder,
                        f"Protection Zone {index}",
                        ring,
                        description="Protection zone polygon, CRS=WGS-84",
                    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"route_{route_id}_{timestamp}.kml"
    content = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(kml, encoding="utf-8")
    return content, filename, has_protection_zone


def export_shp(route_id: int) -> Path:
    route = get_route(route_id)
    if not route:
        raise ValueError(f"Route not found: {route_id}")
    points = get_points(route_id)
    if len(points) < 2:
        raise ValueError("Not enough route points, at least start and end are required")

    ordered_points = sorted(points, key=lambda point: (int(point["order_index"]), int(point["id"])))
    line_coords = [(float(point["longitude"]), float(point["latitude"])) for point in ordered_points]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = EXPORT_DIR / f"route_{route_id}_{timestamp}_shp"
    work_dir.mkdir(parents=True, exist_ok=True)

    points_gdf = gpd.GeoDataFrame(
        {
            "route_id": [int(route_id) for _ in ordered_points],
            "route_name": [str(route["name"])[:80] for _ in ordered_points],
            "pt_name": [str(point.get("name") or "")[:80] for point in ordered_points],
            "pt_type": [str(point.get("point_type") or "waypoint")[:16] for point in ordered_points],
            "order_idx": [int(point.get("order_index") or 0) for point in ordered_points],
            "alt_m": [float(point.get("altitude") or 0.0) for point in ordered_points],
        },
        geometry=gpd.points_from_xy(
            [float(point["longitude"]) for point in ordered_points],
            [float(point["latitude"]) for point in ordered_points],
        ),
        crs="EPSG:4326",
    )
    points_path = work_dir / "route_points.shp"
    points_gdf.to_file(points_path, driver="ESRI Shapefile", engine="pyogrio", encoding="UTF-8")

    from shapely.geometry import LineString

    line_gdf = gpd.GeoDataFrame(
        {
            "route_id": [int(route_id)],
            "route_name": [str(route["name"])[:80]],
            "pt_count": [len(ordered_points)],
            "crs": ["WGS84"],
        },
        geometry=[LineString(line_coords)],
        crs="EPSG:4326",
    )
    line_path = work_dir / "route_line.shp"
    line_gdf.to_file(line_path, driver="ESRI Shapefile", engine="pyogrio", encoding="UTF-8")

    zip_path = EXPORT_DIR / f"route_{route_id}_{timestamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in work_dir.iterdir():
            if file.is_file():
                zf.write(file, arcname=file.name)

    return zip_path
