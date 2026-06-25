import base64
import io
import json
import math
import mimetypes
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

import geopandas as gpd
import httpx
import pandas as pd
import pyogrio
from fastapi import HTTPException, UploadFile
from fastkml import kml
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point, Polygon, box, mapping, shape
from shapely.ops import unary_union

from app.config import IMPORT_DIR
from app.database_route import db_cursor
from app.models.route_schemas import (
    ImportItemDetailResponse,
    ImportItemSummary,
    ImportJobResponse,
    ImportMapFeaturesResponse,
    ImportProjectResponse,
    ImportProjectSummary,
    ImportedDatasetGeoJsonCreate,
    ImportedDatasetResponse,
    ImportedDatasetSummary,
)

IMPORT_DIR.mkdir(parents=True, exist_ok=True)
JOB_UPLOAD_DIR = IMPORT_DIR / "jobs"
JOB_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_IMPORT_EXTENSIONS = {".kml", ".shp", ".zip"}
SUPPORTED_OBSTACLE_EXTENSIONS = {".xls", ".xlsx", ".csv"}
SUPPORTED_AI_DOCUMENT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".geojson", ".xls", ".xlsx", ".docx", ".pdf"}
SUPPORTED_AI_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AI_TEXT_CHUNK_CHARS = 18000
AI_FILE_TEXT_CHARS = 24000
AI_TOTAL_TEXT_CHARS = 90000
AI_IMAGES_PER_BATCH = 3
AI_MAX_IMAGE_PARTS = 12
AI_MAX_PDF_IMAGE_PAGES = 6
AI_HTTP_TIMEOUT = httpx.Timeout(connect=15.0, read=240.0, write=60.0, pool=15.0)
AI_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
OBSTACLE_POINT_LABELS = ["A1", "A2", "C2", "B2", "B3", "C3", "A3", "A4", "C4", "B4", "B1", "C1"]
OBSTACLE_ARC_SPECS = [("C2", "B2"), ("B3", "C3"), ("C4", "B4"), ("B1", "C1")]
OBSTACLE_RING_SEQUENCE = ["A1", "A2", "C2", "arc0", "B3", "arc1", "A3", "A4", "C4", "arc2", "B1", "arc3", "A1"]

IMPORT_TYPE_LABELS = {
    "vector": "矢量数据导入",
    "obstacle_surface": "障碍物限制面直接导入",
    "manual": "手工导入",
    "ai": "AI 智能体导入",
    "combined": "组合项目",
    "merged": "合并项目",
}

AI_MODEL_PRESETS = {
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    "doubao": {"base_url": "https://ark.cn-beijing.volces.com/api/v3", "model": "doubao-seed-1-6-250615"},
}

AI_VISION_MODEL_HINTS = {
    "openai": ("gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4", "vision", "turbo"),
    "qwen": ("vl", "omni", "vision", "qvq"),
    "zhipu": ("glm-4v", "vision", "vl"),
    "doubao": ("vision", "vl", "multimodal"),
    "moonshot": ("vision", "vl"),
}

AIRSPACE_LABELS = {
    "suitable": "适飞区",
    "limited": "限飞区",
    "prohibited": "禁飞区",
}


def _parse_json(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _utc_now_sql() -> str:
    return "CURRENT_TIMESTAMP"


def _sanitize_value(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _bounds_from_geom(geometry: Any) -> dict[str, float] | None:
    if geometry is None or geometry.is_empty:
        return None
    min_x, min_y, max_x, max_y = [float(item) for item in geometry.bounds]
    return {"west": min_x, "south": min_y, "east": max_x, "north": max_y}


def _bounds_union(bounds_list: list[dict[str, float] | None]) -> dict[str, float] | None:
    valid = [item for item in bounds_list if item]
    if not valid:
        return None
    return {
        "west": min(item["west"] for item in valid),
        "south": min(item["south"] for item in valid),
        "east": max(item["east"] for item in valid),
        "north": max(item["north"] for item in valid),
    }


def _bounds_intersects(bounds: dict[str, float] | None, bbox: dict[str, float] | None) -> bool:
    if not bounds or not bbox:
        return True
    return not (
        bounds["east"] < bbox["west"]
        or bounds["west"] > bbox["east"]
        or bounds["north"] < bbox["south"]
        or bounds["south"] > bbox["north"]
    )


def _geometry_types_from_features(features: list[dict[str, Any]]) -> list[str]:
    types: list[str] = []
    for feature in features:
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        geometry_type = str(geometry.get("type") or "")
        if geometry_type and geometry_type not in types:
            types.append(geometry_type)
    return types


def _row_to_summary(row: dict[str, Any]) -> ImportedDatasetSummary:
    return ImportedDatasetSummary(
        id=int(row["id"]),
        name=str(row["name"]),
        import_type=str(row.get("import_type") or "vector"),
        source_format=str(row["source_format"]),
        file_name=str(row["file_name"]),
        source_crs=str(row["source_crs"]) if row["source_crs"] else None,
        target_crs=str(row["target_crs"]),
        feature_count=int(row["feature_count"]),
        geometry_types=[str(item) for item in _parse_json(row["geometry_types_json"], [])],
        bounds=_parse_json(row["bounds_json"], None),
        created_at=str(row["created_at"]) if row["created_at"] else None,
        updated_at=str(row["updated_at"]) if row["updated_at"] else None,
    )


def _row_to_response(row: dict[str, Any]) -> ImportedDatasetResponse:
    summary = _row_to_summary(row)
    feature_collection = _parse_json(row["geojson_json"], {"type": "FeatureCollection", "features": []})
    import_summary = feature_collection.get("import_summary") if isinstance(feature_collection, dict) else None
    return ImportedDatasetResponse(
        **summary.model_dump(),
        feature_collection=feature_collection,
        import_summary=import_summary if isinstance(import_summary, dict) else None,
    )


def _project_from_row(row: dict[str, Any]) -> ImportProjectSummary:
    return ImportProjectSummary(
        id=int(row["id"]),
        name=str(row["name"]),
        import_type=str(row.get("import_type") or "vector"),
        source_format=str(row.get("source_format") or "geojson"),
        file_name=str(row.get("file_name") or ""),
        source_crs=str(row["source_crs"]) if row.get("source_crs") else None,
        target_crs=str(row.get("target_crs") or "EPSG:4326"),
        feature_count=int(row.get("feature_count") or 0),
        item_count=int(row.get("item_count") or 0),
        geometry_types=[str(item) for item in _parse_json(row.get("geometry_types_json"), [])],
        bounds=_parse_json(row.get("bounds_json"), None),
        metadata=_parse_json(row.get("metadata_json"), {}),
        is_visible=bool(row.get("is_visible", 1)),
        is_locked=bool(row.get("is_locked", 0)),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
    )


def _item_from_row(row: dict[str, Any]) -> ImportItemSummary:
    airspace_level = str(row.get("airspace_level") or "suitable")
    if airspace_level not in {"suitable", "limited", "prohibited"}:
        airspace_level = "suitable"
    return ImportItemSummary(
        id=int(row["id"]),
        project_id=int(row["project_id"]),
        name=str(row["name"]),
        item_type=str(row.get("item_type") or "layer"),
        airspace_level=airspace_level,
        feature_count=int(row.get("feature_count") or 0),
        geometry_types=[str(item) for item in _parse_json(row.get("geometry_types_json"), [])],
        bounds=_parse_json(row.get("bounds_json"), None),
        metadata=_parse_json(row.get("metadata_json"), {}),
        is_visible=bool(row.get("is_visible", 1)),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
    )


def _feature_from_row(row: dict[str, Any]) -> dict[str, Any]:
    properties = _parse_json(row.get("properties_json"), {})
    if not isinstance(properties, dict):
        properties = {}
    properties = {
        **properties,
        "feature_id": int(row["id"]),
        "item_id": int(row["item_id"]),
        "project_id": int(row["project_id"]),
        "display_role": str(row.get("display_role") or "feature"),
    }
    return {
        "type": "Feature",
        "id": int(row["id"]),
        "geometry": _parse_json(row.get("geometry_json"), {}),
        "properties": properties,
    }


def _item_detail_from_row(row: dict[str, Any], features: list[dict[str, Any]]) -> ImportItemDetailResponse:
    return ImportItemDetailResponse(
        **_item_from_row(row).model_dump(),
        feature_collection={"type": "FeatureCollection", "features": features},
    )


def _job_from_row(row: dict[str, Any]) -> ImportJobResponse:
    return ImportJobResponse(
        id=int(row["id"]),
        job_type=str(row["job_type"]),
        status=str(row["status"]),
        phase=str(row["phase"]),
        progress=float(row.get("progress") or 0),
        message=str(row.get("message") or ""),
        error=str(row["error"]) if row.get("error") else None,
        total_count=int(row["total_count"]) if row.get("total_count") is not None else None,
        processed_count=int(row.get("processed_count") or 0),
        result_project_id=int(row["result_project_id"]) if row.get("result_project_id") is not None else None,
        result=_parse_json(row.get("result_json"), {}),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        completed_at=str(row["completed_at"]) if row.get("completed_at") else None,
    )


def _normalize_crs(value: str | None, *, fallback: str | None = None) -> str | None:
    text = (value or "").strip()
    if not text:
        return fallback
    upper = text.upper().replace(" ", "")
    aliases = {
        "WGS84": "EPSG:4326",
        "WGS-84": "EPSG:4326",
        "CGCS2000": "EPSG:4490",
        "EPSG4490": "EPSG:4490",
        "EPSG4326": "EPSG:4326",
        "EPSG3857": "EPSG:3857",
    }
    return aliases.get(upper, text)


def _ensure_allowed_suffix(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_IMPORT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅支持 KML、SHP 或 ZIP（内含 SHP/KML）文件导入")
    return suffix


def _ensure_obstacle_suffix(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_OBSTACLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="障碍物限制面仅支持 XLS、XLSX 或 CSV 文件导入")
    return suffix


def _save_upload(target_dir: Path, upload: UploadFile) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    file_name = Path(upload.filename or "upload.dat").name
    target = target_dir / file_name
    with target.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return target


def _resolve_read_target(upload_path: Path) -> tuple[Path, str]:
    suffix = upload_path.suffix.lower()
    if suffix == ".zip":
        extract_dir = upload_path.parent / "unzipped"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(upload_path, "r") as archive:
            archive.extractall(extract_dir)
        shp_files = sorted(extract_dir.rglob("*.shp"))
        if shp_files:
            return shp_files[0], "shp"
        kml_files = sorted(extract_dir.rglob("*.kml"))
        if kml_files:
            return kml_files[0], "kml"
        raise HTTPException(status_code=400, detail="ZIP 中未找到可读取的 SHP 或 KML 文件")
    if suffix == ".shp":
        return upload_path, "shp"
    if suffix == ".kml":
        return upload_path, "kml"
    raise HTTPException(status_code=400, detail="不支持的导入格式")


def _read_with_pyogrio(path: Path) -> gpd.GeoDataFrame:
    return pyogrio.read_dataframe(path)


def _iter_kml_features(items: list[Any], output: list[dict[str, Any]]) -> None:
    for item in items:
        feature_children = []
        if hasattr(item, "features"):
            features_attr = getattr(item, "features")
            try:
                feature_children = list(features_attr()) if callable(features_attr) else list(features_attr)
            except TypeError:
                feature_children = list(features_attr)
        if feature_children:
            _iter_kml_features(feature_children, output)
        geometry = getattr(item, "geometry", None)
        if geometry is None:
            continue
        props: dict[str, Any] = {}
        name = getattr(item, "name", None)
        description = getattr(item, "description", None)
        if name:
            props["name"] = str(name)
        if description:
            props["description"] = str(description)
        output.append({"geometry": geometry, "properties": props})


def _read_kml_with_fastkml(path: Path) -> gpd.GeoDataFrame:
    document = kml.KML()
    document.from_string(path.read_bytes())
    rows: list[dict[str, Any]] = []
    features_attr = getattr(document, "features", None)
    roots = list(features_attr()) if callable(features_attr) else list(features_attr or [])
    _iter_kml_features(roots, rows)
    if not rows:
        raise HTTPException(status_code=400, detail="KML 中未发现可读取的点线面要素")
    return gpd.GeoDataFrame(
        [row["properties"] for row in rows],
        geometry=[row["geometry"] for row in rows],
        crs="EPSG:4326",
    )


def _read_dataset(path: Path, source_format: str) -> gpd.GeoDataFrame:
    try:
        return _read_with_pyogrio(path)
    except Exception:
        if source_format == "kml":
            return _read_kml_with_fastkml(path)
        raise


def _normalize_gdf(gdf: gpd.GeoDataFrame, *, source_crs: str | None, target_crs: str) -> tuple[gpd.GeoDataFrame, str | None]:
    if gdf.empty:
        raise HTTPException(status_code=400, detail="导入内容中没有可用要素")
    gdf = gdf[gdf.geometry.notnull()].copy()
    if gdf.empty:
        raise HTTPException(status_code=400, detail="导入内容中没有有效几何对象")
    inferred_source_crs = str(gdf.crs) if gdf.crs else None
    normalized_source = _normalize_crs(source_crs, fallback=inferred_source_crs)
    normalized_target = _normalize_crs(target_crs, fallback="EPSG:4326") or "EPSG:4326"
    if gdf.crs is None:
        if not normalized_source:
            raise HTTPException(status_code=400, detail="导入内容未声明坐标系，请在界面中选择源坐标系")
        gdf = gdf.set_crs(normalized_source)
    elif normalized_source and normalized_source != str(gdf.crs):
        gdf = gdf.set_crs(normalized_source, allow_override=True)
    try:
        gdf = gdf.to_crs(normalized_target)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"坐标系转换失败：{exc}") from exc
    return gdf, normalized_source or str(gdf.crs)


def _feature_collection_from_gdf(gdf: gpd.GeoDataFrame) -> tuple[dict[str, Any], list[str], dict[str, float] | None]:
    features: list[dict[str, Any]] = []
    geometry_types: list[str] = []
    for _, row in gdf.iterrows():
        geometry = row.geometry
        if geometry is None:
            continue
        geo_type = str(geometry.geom_type)
        if geo_type not in geometry_types:
            geometry_types.append(geo_type)
        props = {}
        for key, value in row.drop(labels=["geometry"]).items():
            sanitized = _sanitize_value(value)
            if sanitized is not None:
                props[str(key)] = sanitized
        features.append({"type": "Feature", "geometry": mapping(geometry), "properties": props})
    bounds = _bounds_union([_bounds_from_geom(shape(feature["geometry"])) for feature in features])
    return {"type": "FeatureCollection", "features": features}, geometry_types, bounds


def _insert_legacy_dataset(
    *,
    name: str,
    import_type: str,
    source_format: str,
    file_name: str,
    source_crs: str | None,
    target_crs: str,
    feature_collection: dict[str, Any],
    geometry_types: list[str],
    bounds: dict[str, float] | None,
    import_summary: dict[str, Any] | None = None,
) -> ImportedDatasetResponse:
    stored_feature_collection = dict(feature_collection)
    if import_summary:
        stored_feature_collection["import_summary"] = import_summary
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO imported_datasets (
                name, import_type, source_format, file_name, source_crs, target_crs,
                feature_count, geometry_types_json, bounds_json, geojson_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                import_type,
                source_format,
                file_name,
                source_crs,
                target_crs,
                len(stored_feature_collection["features"]),
                _json(geometry_types),
                _json(bounds) if bounds else None,
                _json(stored_feature_collection),
            ),
        )
        dataset_id = int(cursor.lastrowid)
        cursor.execute("SELECT * FROM imported_datasets WHERE id = ?", (dataset_id,))
        row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="导入数据写入成功，但读取结果失败")
    return _row_to_response(dict(row))


def _create_project(
    *,
    name: str,
    import_type: str,
    source_format: str,
    file_name: str,
    source_crs: str | None,
    target_crs: str,
    metadata: dict[str, Any] | None = None,
    is_visible: bool = True,
) -> int:
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO import_projects (
                name, import_type, source_format, file_name, source_crs, target_crs,
                metadata_json, is_visible
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, import_type, source_format, file_name, source_crs, target_crs, _json(metadata or {}), 1 if is_visible else 0),
        )
        return int(cursor.lastrowid)


def _create_item(
    *,
    project_id: int,
    name: str,
    item_type: str,
    airspace_level: str | None = None,
    metadata: dict[str, Any] | None = None,
    is_visible: bool = True,
) -> int:
    normalized_level = airspace_level or ("limited" if item_type == "airport_obstacle_surface" else "suitable")
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO import_items (project_id, name, item_type, airspace_level, metadata_json, is_visible)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, name, item_type, normalized_level, _json(metadata or {}), 1 if is_visible else 0),
        )
        return int(cursor.lastrowid)


def _insert_feature(
    *,
    project_id: int,
    item_id: int,
    feature: dict[str, Any],
    display_role: str = "feature",
) -> None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return
    geom = shape(geometry)
    bounds = _bounds_from_geom(geom)
    properties = feature.get("properties")
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO import_features (
                project_id, item_id, geometry_type, geometry_json, properties_json, bounds_json, display_role
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                item_id,
                str(geometry.get("type") or geom.geom_type),
                _json(geometry),
                _json(properties if isinstance(properties, dict) else {}),
                _json(bounds) if bounds else None,
                display_role,
            ),
        )


def _recalculate_item(item_id: int) -> None:
    with db_cursor() as cursor:
        cursor.execute("SELECT geometry_type, bounds_json FROM import_features WHERE item_id = ?", (item_id,))
        rows = [dict(row) for row in cursor.fetchall()]
        geometry_types: list[str] = []
        bounds_list: list[dict[str, float] | None] = []
        for row in rows:
            geometry_type = str(row["geometry_type"])
            if geometry_type not in geometry_types:
                geometry_types.append(geometry_type)
            bounds_list.append(_parse_json(row["bounds_json"], None))
        cursor.execute(
            """
            UPDATE import_items
            SET feature_count = ?, geometry_types_json = ?, bounds_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (len(rows), _json(geometry_types), _json(_bounds_union(bounds_list)) if rows else None, item_id),
        )


def _recalculate_project(project_id: int) -> None:
    with db_cursor() as cursor:
        cursor.execute("SELECT id, geometry_types_json, bounds_json, feature_count FROM import_items WHERE project_id = ?", (project_id,))
        rows = [dict(row) for row in cursor.fetchall()]
        geometry_types: list[str] = []
        bounds_list: list[dict[str, float] | None] = []
        feature_count = 0
        for row in rows:
            feature_count += int(row.get("feature_count") or 0)
            for geometry_type in _parse_json(row.get("geometry_types_json"), []):
                if geometry_type not in geometry_types:
                    geometry_types.append(str(geometry_type))
            bounds_list.append(_parse_json(row.get("bounds_json"), None))
        cursor.execute(
            """
            UPDATE import_projects
            SET feature_count = ?, item_count = ?, geometry_types_json = ?, bounds_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (feature_count, len(rows), _json(geometry_types), _json(_bounds_union(bounds_list)) if rows else None, project_id),
        )


def _create_project_from_features(
    *,
    name: str,
    import_type: str,
    source_format: str,
    file_name: str,
    source_crs: str | None,
    target_crs: str,
    item_name: str,
    item_type: str,
    features: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> int:
    project_id = _create_project(
        name=name,
        import_type=import_type,
        source_format=source_format,
        file_name=file_name,
        source_crs=source_crs,
        target_crs=target_crs,
        metadata=metadata,
    )
    item_id = _create_item(project_id=project_id, name=item_name, item_type=item_type, metadata=metadata)
    for feature in features:
        role = str((feature.get("properties") or {}).get("obstacle_role") or "feature")
        _insert_feature(project_id=project_id, item_id=item_id, feature=feature, display_role=role)
    _recalculate_item(item_id)
    _recalculate_project(project_id)
    return project_id


def _read_project(project_id: int) -> ImportProjectResponse:
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM import_projects WHERE id = ?", (project_id,))
        project_row = cursor.fetchone()
        if not project_row:
            raise HTTPException(status_code=404, detail="Import project not found")
        cursor.execute("SELECT * FROM import_items WHERE project_id = ? ORDER BY id ASC", (project_id,))
        item_rows = [dict(row) for row in cursor.fetchall()]
    project = _project_from_row(dict(project_row))
    return ImportProjectResponse(**project.model_dump(), items=[_item_from_row(row) for row in item_rows])


def _legacy_migrated(dataset_id: int) -> bool:
    pattern = f'%"legacy_dataset_id": {dataset_id}%'
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM import_projects WHERE metadata_json LIKE ? LIMIT 1", (pattern,))
        return cursor.fetchone() is not None


def migrate_legacy_datasets() -> None:
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM imported_datasets ORDER BY id ASC")
        rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        dataset_id = int(row["id"])
        if _legacy_migrated(dataset_id):
            continue
        feature_collection = _parse_json(row["geojson_json"], {"type": "FeatureCollection", "features": []})
        features = feature_collection.get("features") if isinstance(feature_collection, dict) else []
        if not isinstance(features, list):
            features = []
        metadata = {"legacy_dataset_id": dataset_id, "migrated_from": "imported_datasets"}
        _create_project_from_features(
            name=str(row["name"]),
            import_type=str(row.get("import_type") or "vector"),
            source_format=str(row.get("source_format") or "geojson"),
            file_name=str(row.get("file_name") or ""),
            source_crs=str(row["source_crs"]) if row.get("source_crs") else None,
            target_crs=str(row.get("target_crs") or "EPSG:4326"),
            item_name=str(row["name"]),
            item_type=str(row.get("import_type") or "layer"),
            features=features,
            metadata=metadata,
        )


def list_imported_datasets() -> list[ImportedDatasetSummary]:
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM imported_datasets ORDER BY id DESC")
        rows = [dict(item) for item in cursor.fetchall()]
    return [_row_to_summary(row) for row in rows]


def get_imported_dataset(dataset_id: int) -> ImportedDatasetResponse:
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM imported_datasets WHERE id = ?", (dataset_id,))
        row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Imported dataset not found")
    return _row_to_response(dict(row))


def delete_imported_dataset(dataset_id: int) -> dict[str, Any]:
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM imported_datasets WHERE id = ?", (dataset_id,))
        deleted = cursor.rowcount
    if not deleted:
        raise HTTPException(status_code=404, detail="Imported dataset not found")
    return {"ok": True}


def import_dataset(upload: UploadFile, *, name: str | None, source_crs: str | None, target_crs: str | None) -> ImportedDatasetResponse:
    original_name = Path(upload.filename or "upload.dat").name
    _ensure_allowed_suffix(original_name)
    normalized_target = _normalize_crs(target_crs, fallback="EPSG:4326") or "EPSG:4326"
    with tempfile.TemporaryDirectory(prefix="route_import_", dir=str(IMPORT_DIR)) as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        saved_path = _save_upload(temp_dir, upload)
        read_target, source_format = _resolve_read_target(saved_path)
        gdf = _read_dataset(read_target, source_format)
        gdf, normalized_source = _normalize_gdf(gdf, source_crs=source_crs, target_crs=normalized_target)
        feature_collection, geometry_types, bounds = _feature_collection_from_gdf(gdf)

    dataset_name = (name or Path(original_name).stem).strip() or Path(original_name).stem
    response = _insert_legacy_dataset(
        name=dataset_name,
        import_type="vector",
        source_format=source_format,
        file_name=original_name,
        source_crs=normalized_source,
        target_crs=normalized_target,
        feature_collection=feature_collection,
        geometry_types=geometry_types,
        bounds=bounds,
    )
    _create_project_from_features(
        name=dataset_name,
        import_type="vector",
        source_format=source_format,
        file_name=original_name,
        source_crs=normalized_source,
        target_crs=normalized_target,
        item_name=dataset_name,
        item_type="vector",
        features=feature_collection["features"],
        metadata={"legacy_dataset_id": response.id},
    )
    return response


def _gdf_from_feature_collection(feature_collection: dict[str, Any]) -> gpd.GeoDataFrame:
    if feature_collection.get("type") != "FeatureCollection":
        raise HTTPException(status_code=400, detail="仅支持 GeoJSON FeatureCollection")
    features = feature_collection.get("features")
    if not isinstance(features, list) or not features:
        raise HTTPException(status_code=400, detail="GeoJSON 中没有可导入的要素")
    rows: list[dict[str, Any]] = []
    geometries = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        try:
            geometries.append(shape(geometry))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"GeoJSON 几何解析失败：{exc}") from exc
        properties = feature.get("properties")
        rows.append(properties if isinstance(properties, dict) else {})
    if not geometries:
        raise HTTPException(status_code=400, detail="GeoJSON 中没有有效几何对象")
    return gpd.GeoDataFrame(rows, geometry=geometries)


def import_geojson_dataset(payload: ImportedDatasetGeoJsonCreate) -> ImportedDatasetResponse:
    if payload.import_type not in IMPORT_TYPE_LABELS:
        raise HTTPException(status_code=400, detail="不支持的导入类型")
    gdf = _gdf_from_feature_collection(payload.feature_collection)
    normalized_target = _normalize_crs(payload.target_crs, fallback="EPSG:4326") or "EPSG:4326"
    gdf, normalized_source = _normalize_gdf(gdf, source_crs=payload.source_crs, target_crs=normalized_target)
    feature_collection, geometry_types, bounds = _feature_collection_from_gdf(gdf)
    response = _insert_legacy_dataset(
        name=payload.name.strip(),
        import_type=payload.import_type,
        source_format="geojson",
        file_name=f"{payload.import_type}.geojson",
        source_crs=normalized_source,
        target_crs=normalized_target,
        feature_collection=feature_collection,
        geometry_types=geometry_types,
        bounds=bounds,
    )
    _create_project_from_features(
        name=payload.name.strip(),
        import_type=payload.import_type,
        source_format="geojson",
        file_name=f"{payload.import_type}.geojson",
        source_crs=normalized_source,
        target_crs=normalized_target,
        item_name=payload.name.strip(),
        item_type=payload.import_type,
        features=feature_collection["features"],
        metadata={"legacy_dataset_id": response.id},
    )
    return response


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _parse_float(value: Any) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    text = text.replace(",", "").replace("米", "").replace("m", "").replace("M", "").strip()
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _parse_obstacle_dms(value: Any) -> tuple[float, float] | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = (
        text.replace("º", "°")
        .replace("˚", "°")
        .replace("度", "°")
        .replace("′", "'")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("＇", "'")
        .replace("分", "'")
        .replace("，", ",")
    )
    pattern = re.compile(
        r"([NS])\s*([+-]?\d+(?:\.\d+)?)\s*°?\s*([+-]?\d+(?:\.\d+)?)\s*'?\s*"
        r"([EW])\s*([+-]?\d+(?:\.\d+)?)\s*°?\s*([+-]?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    match = pattern.search(normalized)
    if match:
        lat_dir, lat_deg, lat_min, lon_dir, lon_deg, lon_min = match.groups()
        lat = float(lat_deg) + float(lat_min) / 60.0
        lon = float(lon_deg) + float(lon_min) / 60.0
        if lat_dir.upper() == "S":
            lat = -lat
        if lon_dir.upper() == "W":
            lon = -lon
        return lon, lat
    numbers = [float(item) for item in re.findall(r"[-+]?\d+(?:\.\d+)?", normalized)]
    if len(numbers) >= 2:
        first, second = numbers[0], numbers[1]
        if abs(first) <= 90 and abs(second) > 90:
            return second, first
        return first, second
    return None


def _dedupe_column_names(columns: list[Any]) -> list[str]:
    counts: dict[str, int] = {}
    result: list[str] = []
    for column in columns:
        base = _clean_text(column) or "Unnamed"
        index = counts.get(base, 0)
        counts[base] = index + 1
        result.append(base if index == 0 else f"{base}.{index}")
    return result


def _read_xls_with_excel_com(path: Path) -> pd.DataFrame:
    try:
        import pythoncom
        import win32com.client
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="当前 .xls 文件是加密/受保护格式，需要 Excel COM 兜底读取；请重新运行 start.bat 安装 pywin32，或将文件在 Excel/WPS 中另存为 .xlsx 后再导入。",
        ) from exc

    pythoncom.CoInitialize()
    excel = None
    workbook = None
    try:
        for prog_id in ("Excel.Application", "Ket.Application", "KET.Application"):
            try:
                excel = win32com.client.DispatchEx(prog_id)
                break
            except Exception:
                excel = None
        if excel is None:
            raise HTTPException(
                status_code=500,
                detail="当前 .xls 文件是加密/受保护格式，需要本机安装 Microsoft Excel 或 WPS 表格，或将文件另存为 .xlsx/.csv 后再导入。",
            )
        try:
            excel.Visible = False
            excel.DisplayAlerts = False
        except Exception:
            pass
        workbook = excel.Workbooks.Open(str(path.resolve()), ReadOnly=True)
        sheet = workbook.Worksheets(1)
        values = sheet.UsedRange.Value
        if values is None:
            return pd.DataFrame()
        if not isinstance(values, tuple):
            values = ((values,),)
        rows = [list(row) if isinstance(row, tuple) else [row] for row in values]
        if not rows:
            return pd.DataFrame()
        columns = _dedupe_column_names(rows[0])
        return pd.DataFrame(rows[1:], columns=columns, dtype=object)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="当前 .xls 文件是加密/受保护格式，纯 Python 无法读取；请确认本机已安装 Microsoft Excel，或将文件另存为 .xlsx/.csv 后再导入。",
        ) from exc
    finally:
        if workbook is not None:
            workbook.Close(False)
        if excel is not None:
            excel.Quit()
        pythoncom.CoUninitialize()


def _read_obstacle_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            try:
                return pd.read_csv(path, dtype=object)
            except UnicodeDecodeError:
                return pd.read_csv(path, dtype=object, encoding="gb18030")
        if suffix in {".xls", ".xlsx"}:
            try:
                return pd.read_excel(path, dtype=object)
            except Exception as exc:
                if suffix == ".xls" and "encrypted" in str(exc).lower():
                    return _read_xls_with_excel_com(path)
                raise
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"缺少读取表格所需依赖：{exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"表格读取失败：{exc}") from exc
    raise HTTPException(status_code=400, detail="不支持的障碍物限制面表格格式")


def _obstacle_columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    columns = [str(item).strip() for item in df.columns]
    point_columns = [label for label in OBSTACLE_POINT_LABELS if label in columns]
    radius_columns = [column for column in columns if "半径" in column]
    return point_columns, radius_columns


def _transform_point(transformer: Transformer, point: tuple[float, float]) -> tuple[float, float]:
    x, y = transformer.transform(point[0], point[1])
    return float(x), float(y)


def _local_transformers(center_lon: float, center_lat: float) -> tuple[Transformer, Transformer]:
    local_crs = CRS.from_proj4(f"+proj=aeqd +lat_0={center_lat} +lon_0={center_lon} +datum=WGS84 +units=m +no_defs")
    wgs84 = CRS.from_epsg(4326)
    to_local = Transformer.from_crs(wgs84, local_crs, always_xy=True)
    to_wgs84 = Transformer.from_crs(local_crs, wgs84, always_xy=True)
    return to_local, to_wgs84


def _generate_auto_convex_arc_xy(
    p_start: tuple[float, float],
    p_end: tuple[float, float],
    radius: float,
    ref_center: tuple[float, float],
    *,
    num_points: int = 60,
) -> list[tuple[float, float]]:
    x1, y1 = p_start
    x2, y2 = p_end
    d = math.hypot(x2 - x1, y2 - y1)
    if radius <= 0 or d <= 0 or d >= 2 * radius:
        return [p_start, p_end]
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    h = math.sqrt(max(0.0, radius**2 - (d / 2) ** 2))
    dx, dy = (x2 - x1) / d, (y2 - y1) / d
    center_1 = (mx + h * dy, my - h * dx)
    center_2 = (mx - h * dy, my + h * dx)
    dist_1 = math.hypot(center_1[0] - ref_center[0], center_1[1] - ref_center[1])
    dist_2 = math.hypot(center_2[0] - ref_center[0], center_2[1] - ref_center[1])
    cx, cy = center_1 if dist_1 < dist_2 else center_2
    start_angle = math.atan2(y1 - cy, x1 - cx)
    end_angle = math.atan2(y2 - cy, x2 - cx)
    diff = end_angle - start_angle
    while diff > math.pi:
        diff -= 2 * math.pi
    while diff < -math.pi:
        diff += 2 * math.pi
    return [
        (cx + radius * math.cos(start_angle + diff * (index / num_points)), cy + radius * math.sin(start_angle + diff * (index / num_points)))
        for index in range(num_points + 1)
    ]


def _to_wgs84_list(transformer: Transformer, points_xy: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [_transform_point(transformer, point) for point in points_xy]


def _base_obstacle_props(row: pd.Series, excel_row: int) -> dict[str, Any]:
    return {
        "airport_name": _clean_text(row.get("机场名称")),
        "airport_code": _clean_text(row.get("四字地名代码")),
        "airport_elevation_m": _parse_float(row.get("机场标高(m)")),
        "runway_no": _clean_text(row.get("跑道号码")),
        "source_row": excel_row,
    }


def _obstacle_surface_features_by_airport(
    df: pd.DataFrame,
    *,
    source_crs: str,
    job_id: int | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], dict[str, Any]]:
    point_columns, radius_columns = _obstacle_columns(df)
    if len(point_columns) < len(OBSTACLE_POINT_LABELS) or len(radius_columns) < 4:
        raise HTTPException(status_code=400, detail="表格缺少 12 个关键点列或 4 个圆弧半径列")

    source_to_wgs84 = Transformer.from_crs(CRS.from_user_input(source_crs), CRS.from_epsg(4326), always_xy=True)
    grouped_features: dict[str, list[dict[str, Any]]] = {}
    grouped_meta: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    ignored_rows = 0
    total_rows = len(df)

    if job_id:
        _update_job(job_id, status="running", phase="parsing", progress=35, message="正在解析机场限制面表格", total_count=total_rows, processed_count=0)

    for row_index, row in df.iterrows():
        excel_row = int(row_index) + 2
        base_props = _base_obstacle_props(row, excel_row)
        raw_points = {label: _parse_obstacle_dms(row.get(label)) for label in OBSTACLE_POINT_LABELS}
        valid_points = {label: point for label, point in raw_points.items() if point is not None}
        radii = [_parse_float(row.get(radius_columns[index])) for index in range(4)]

        if not valid_points and not base_props["airport_code"] and not base_props["runway_no"]:
            ignored_rows += 1
            continue
        if len(valid_points) < len(OBSTACLE_POINT_LABELS) or any(radius is None for radius in radii):
            skipped.append({
                "row": excel_row,
                "airport_name": base_props["airport_name"],
                "airport_code": base_props["airport_code"],
                "reason": "missing_required_points_or_radii",
            })
            continue

        points_wgs = {label: _transform_point(source_to_wgs84, point) for label, point in valid_points.items()}
        center_lon = sum(point[0] for point in points_wgs.values()) / len(points_wgs)
        center_lat = sum(point[1] for point in points_wgs.values()) / len(points_wgs)
        to_local, to_wgs84 = _local_transformers(center_lon, center_lat)
        points_xy = {label: _transform_point(to_local, point) for label, point in points_wgs.items()}
        ref_center = (
            sum(point[0] for point in points_xy.values()) / len(points_xy),
            sum(point[1] for point in points_xy.values()) / len(points_xy),
        )

        arc_points_xy: list[list[tuple[float, float]]] = []
        for arc_index, (start_label, end_label) in enumerate(OBSTACLE_ARC_SPECS):
            arc_points_xy.append(_generate_auto_convex_arc_xy(points_xy[start_label], points_xy[end_label], float(radii[arc_index] or 0), ref_center))

        ring_xy: list[tuple[float, float]] = []
        for item in OBSTACLE_RING_SEQUENCE:
            if item.startswith("arc"):
                arc_index = int(item.replace("arc", ""))
                ring_xy.extend(arc_points_xy[arc_index][1:])
            else:
                ring_xy.append(points_xy[item])
        if ring_xy[0] != ring_xy[-1]:
            ring_xy.append(ring_xy[0])
        ring_wgs = _to_wgs84_list(to_wgs84, ring_xy)
        polygon = Polygon(ring_wgs)
        if polygon.is_empty:
            skipped.append({**base_props, "row": excel_row, "reason": "empty_polygon"})
            continue

        airport_key = base_props["airport_code"] or base_props["airport_name"] or f"row-{excel_row}"
        grouped_features.setdefault(airport_key, [])
        grouped_meta.setdefault(airport_key, {
            "airport_name": base_props["airport_name"],
            "airport_code": base_props["airport_code"],
            "runways": [],
            "source_rows": [],
            "airport_elevation_m": base_props["airport_elevation_m"],
        })
        grouped_meta[airport_key]["runways"].append(base_props["runway_no"])
        grouped_meta[airport_key]["source_rows"].append(excel_row)
        grouped_features[airport_key].append({
            "type": "Feature",
            "geometry": mapping(polygon),
            "properties": {
                **base_props,
                "name": f"{base_props['airport_name']} {base_props['runway_no']} 障碍物限制面",
                "obstacle_role": "surface",
                "arc_radius_1_m": float(radii[0] or 0),
                "arc_radius_2_m": float(radii[1] or 0),
                "arc_radius_3_m": float(radii[2] or 0),
                "arc_radius_4_m": float(radii[3] or 0),
                "polygon_valid": bool(polygon.is_valid),
            },
        })

        if job_id and (row_index + 1) % 5 == 0:
            progress = 35 + min(45, ((row_index + 1) / max(1, total_rows)) * 45)
            _update_job(job_id, status="running", phase="parsing", progress=progress, total_count=total_rows, processed_count=row_index + 1)

    if not grouped_features:
        raise HTTPException(status_code=400, detail="未生成有效障碍物限制面")

    summary = {
        "success_airports": len(grouped_features),
        "success_rows": sum(len(features) for features in grouped_features.values()),
        "skipped_rows": len(skipped),
        "ignored_rows": ignored_rows,
        "surface_count": sum(len(features) for features in grouped_features.values()),
        "skipped_examples": skipped[:20],
    }
    return grouped_features, grouped_meta, summary


def _create_obstacle_project(
    *,
    name: str,
    source_format: str,
    file_name: str,
    source_crs: str,
    target_crs: str,
    grouped_features: dict[str, list[dict[str, Any]]],
    grouped_meta: dict[str, dict[str, Any]],
    summary: dict[str, Any],
    job_id: int | None = None,
) -> int:
    project_id = _create_project(
        name=name,
        import_type="obstacle_surface",
        source_format=source_format,
        file_name=file_name,
        source_crs=source_crs,
        target_crs=target_crs,
        metadata=summary,
    )
    total_airports = len(grouped_features)
    for index, (airport_key, features) in enumerate(grouped_features.items(), start=1):
        meta = grouped_meta.get(airport_key, {})
        code = str(meta.get("airport_code") or "")
        airport_name = str(meta.get("airport_name") or airport_key)
        item_name = f"{code} {airport_name}".strip()
        item_metadata = {
            **meta,
            "runway_count": len(set([item for item in meta.get("runways", []) if item])),
            "airport_key": airport_key,
        }
        item_id = _create_item(project_id=project_id, name=item_name, item_type="airport_obstacle_surface", metadata=item_metadata)
        for feature in features:
            _insert_feature(project_id=project_id, item_id=item_id, feature=feature, display_role="surface")
        _recalculate_item(item_id)
        if job_id:
            progress = 80 + min(18, (index / max(1, total_airports)) * 18)
            _update_job(job_id, status="running", phase="saving", progress=progress, message="正在写入机场项目", total_count=total_airports, processed_count=index)
    _recalculate_project(project_id)
    return project_id


def import_obstacle_surface_dataset(
    upload: UploadFile,
    *,
    name: str | None,
    source_crs: str | None,
    target_crs: str | None,
) -> ImportedDatasetResponse:
    original_name = Path(upload.filename or "upload.dat").name
    suffix = _ensure_obstacle_suffix(original_name)
    source_format = suffix.lstrip(".")
    normalized_source = _normalize_crs(source_crs, fallback="EPSG:4326") or "EPSG:4326"
    normalized_target = "EPSG:4326"
    with tempfile.TemporaryDirectory(prefix="route_obstacle_import_", dir=str(IMPORT_DIR)) as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        saved_path = _save_upload(temp_dir, upload)
        table = _read_obstacle_table(saved_path)
        grouped_features, grouped_meta, summary = _obstacle_surface_features_by_airport(table, source_crs=normalized_source)

    dataset_name = (name or Path(original_name).stem).strip() or Path(original_name).stem
    all_features = [feature for features in grouped_features.values() for feature in features]
    feature_collection = {"type": "FeatureCollection", "features": all_features}
    geometry_types = _geometry_types_from_features(all_features)
    bounds = _bounds_union([_bounds_from_geom(shape(feature["geometry"])) for feature in all_features])
    response = _insert_legacy_dataset(
        name=dataset_name,
        import_type="obstacle_surface",
        source_format=source_format,
        file_name=original_name,
        source_crs=normalized_source,
        target_crs=normalized_target,
        feature_collection=feature_collection,
        geometry_types=geometry_types,
        bounds=bounds,
        import_summary=summary,
    )
    _create_obstacle_project(
        name=dataset_name,
        source_format=source_format,
        file_name=original_name,
        source_crs=normalized_source,
        target_crs=normalized_target,
        grouped_features=grouped_features,
        grouped_meta=grouped_meta,
        summary={**summary, "legacy_dataset_id": response.id},
    )
    return response


def _create_job(job_type: str, *, message: str = "") -> int:
    with db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO import_jobs (job_type, status, phase, progress, message) VALUES (?, 'queued', 'queued', 0, ?)",
            (job_type, message),
        )
        return int(cursor.lastrowid)


def _update_job(
    job_id: int,
    *,
    status: str | None = None,
    phase: str | None = None,
    progress: float | None = None,
    message: str | None = None,
    error: str | None = None,
    total_count: int | None = None,
    processed_count: int | None = None,
    result_project_id: int | None = None,
    result: dict[str, Any] | None = None,
    completed: bool = False,
) -> None:
    fields: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if phase is not None:
        fields.append("phase = ?")
        values.append(phase)
    if progress is not None:
        fields.append("progress = ?")
        values.append(max(0, min(100, float(progress))))
    if message is not None:
        fields.append("message = ?")
        values.append(message)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if total_count is not None:
        fields.append("total_count = ?")
        values.append(total_count)
    if processed_count is not None:
        fields.append("processed_count = ?")
        values.append(processed_count)
    if result_project_id is not None:
        fields.append("result_project_id = ?")
        values.append(result_project_id)
    if result is not None:
        fields.append("result_json = ?")
        values.append(_json(result))
    if completed:
        fields.append("completed_at = CURRENT_TIMESTAMP")
    values.append(job_id)
    with db_cursor() as cursor:
        cursor.execute(f"UPDATE import_jobs SET {', '.join(fields)} WHERE id = ?", tuple(values))


def create_obstacle_surface_import_job(upload: UploadFile, *, name: str | None, source_crs: str | None, target_crs: str | None, background_tasks: Any) -> ImportJobResponse:
    original_name = Path(upload.filename or "upload.dat").name
    suffix = _ensure_obstacle_suffix(original_name)
    job_id = _create_job("obstacle_surface", message="文件已上传，等待解析")
    job_dir = JOB_UPLOAD_DIR / str(job_id)
    saved_path = _save_upload(job_dir, upload)
    background_tasks.add_task(
        run_obstacle_surface_import_job,
        job_id,
        str(saved_path),
        (name or Path(original_name).stem).strip() or Path(original_name).stem,
        suffix.lstrip("."),
        original_name,
        _normalize_crs(source_crs, fallback="EPSG:4326") or "EPSG:4326",
        "EPSG:4326",
    )
    return get_import_job(job_id)


def run_obstacle_surface_import_job(
    job_id: int,
    path_raw: str,
    name: str,
    source_format: str,
    file_name: str,
    source_crs: str,
    target_crs: str,
) -> None:
    path = Path(path_raw)
    try:
        _update_job(job_id, status="running", phase="reading", progress=5, message="正在读取表格")
        table = _read_obstacle_table(path)
        _update_job(job_id, status="running", phase="parsing", progress=30, message="表格读取完成，开始解析", total_count=len(table), processed_count=0)
        grouped_features, grouped_meta, summary = _obstacle_surface_features_by_airport(table, source_crs=source_crs, job_id=job_id)
        _update_job(job_id, status="running", phase="saving", progress=80, message="解析完成，正在入库", total_count=len(grouped_features), processed_count=0)
        project_id = _create_obstacle_project(
            name=name,
            source_format=source_format,
            file_name=file_name,
            source_crs=source_crs,
            target_crs=target_crs,
            grouped_features=grouped_features,
            grouped_meta=grouped_meta,
            summary=summary,
            job_id=job_id,
        )
        _update_job(
            job_id,
            status="completed",
            phase="completed",
            progress=100,
            message="导入完成",
            result_project_id=project_id,
            result={**summary, "project_id": project_id},
            completed=True,
        )
    except HTTPException as exc:
        _update_job(job_id, status="failed", phase="failed", progress=100, message="导入失败", error=str(exc.detail), completed=True)
    except Exception as exc:
        _update_job(job_id, status="failed", phase="failed", progress=100, message="导入失败", error=str(exc), completed=True)
    finally:
        try:
            shutil.rmtree(path.parent, ignore_errors=True)
        except Exception:
            pass


def get_import_job(job_id: int) -> ImportJobResponse:
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Import job not found")
    return _job_from_row(dict(row))


def list_import_projects() -> list[ImportProjectSummary]:
    migrate_legacy_datasets()
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM import_projects ORDER BY id DESC")
        rows = [dict(row) for row in cursor.fetchall()]
    return [_project_from_row(row) for row in rows]


def get_import_project(project_id: int) -> ImportProjectResponse:
    migrate_legacy_datasets()
    return _read_project(project_id)


def update_import_project(project_id: int, *, name: str | None = None, is_visible: bool | None = None) -> ImportProjectResponse:
    fields: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = []
    if name is not None:
        fields.append("name = ?")
        values.append(name.strip())
    if is_visible is not None:
        fields.append("is_visible = ?")
        values.append(1 if is_visible else 0)
    values.append(project_id)
    with db_cursor() as cursor:
        cursor.execute(f"UPDATE import_projects SET {', '.join(fields)} WHERE id = ?", tuple(values))
        if not cursor.rowcount:
            raise HTTPException(status_code=404, detail="Import project not found")
    return _read_project(project_id)


def delete_import_project(project_id: int) -> dict[str, Any]:
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM import_projects WHERE id = ?", (project_id,))
        deleted = cursor.rowcount
    if not deleted:
        raise HTTPException(status_code=404, detail="Import project not found")
    return {"ok": True}


def list_import_items(project_id: int | None = None) -> list[ImportItemSummary]:
    migrate_legacy_datasets()
    with db_cursor() as cursor:
        if project_id is None:
            cursor.execute("SELECT * FROM import_items ORDER BY project_id DESC, id ASC")
            rows = [dict(row) for row in cursor.fetchall()]
        else:
            cursor.execute("SELECT * FROM import_items WHERE project_id = ? ORDER BY id ASC", (project_id,))
            rows = [dict(row) for row in cursor.fetchall()]
    return [_item_from_row(row) for row in rows]


def get_import_item(item_id: int) -> ImportItemDetailResponse:
    migrate_legacy_datasets()
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM import_items WHERE id = ?", (item_id,))
        item_row = cursor.fetchone()
        if not item_row:
            raise HTTPException(status_code=404, detail="Import item not found")
        cursor.execute("SELECT * FROM import_features WHERE item_id = ? ORDER BY id ASC", (item_id,))
        features = [_feature_from_row(dict(row)) for row in cursor.fetchall()]
    return _item_detail_from_row(dict(item_row), features)


def update_import_item(
    item_id: int,
    *,
    name: str | None = None,
    is_visible: bool | None = None,
    is_locked: bool | None = None,
    airspace_level: str | None = None,
) -> ImportItemSummary:
    fields: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = []
    if name is not None:
        fields.append("name = ?")
        values.append(name.strip())
    if is_visible is not None:
        fields.append("is_visible = ?")
        values.append(1 if is_visible else 0)
    if is_locked is not None:
        fields.append("is_locked = ?")
        values.append(1 if is_locked else 0)
    if airspace_level is not None:
        if airspace_level not in {"suitable", "limited", "prohibited"}:
            raise HTTPException(status_code=400, detail="Invalid airspace level")
        fields.append("airspace_level = ?")
        values.append(airspace_level)
    values.append(item_id)
    with db_cursor() as cursor:
        cursor.execute(f"UPDATE import_items SET {', '.join(fields)} WHERE id = ?", tuple(values))
        if not cursor.rowcount:
            raise HTTPException(status_code=404, detail="Import item not found")
        cursor.execute("SELECT * FROM import_items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
    return _item_from_row(dict(row))


def _validated_feature_rows(
    *,
    project_id: int,
    item_id: int,
    feature_collection: dict[str, Any],
) -> list[tuple[int, int, str, str, str, str | None, str]]:
    if feature_collection.get("type") != "FeatureCollection":
        raise HTTPException(status_code=400, detail="请提交 GeoJSON FeatureCollection")
    raw_features = feature_collection.get("features")
    if not isinstance(raw_features, list) or not raw_features:
        raise HTTPException(status_code=400, detail="FeatureCollection 至少需要一个要素")

    rows: list[tuple[int, int, str, str, str, str | None, str]] = []
    for index, raw_feature in enumerate(raw_features, start=1):
        if not isinstance(raw_feature, dict) or raw_feature.get("type") != "Feature":
            raise HTTPException(status_code=400, detail=f"第 {index} 个要素不是有效 Feature")
        geometry = raw_feature.get("geometry")
        if not isinstance(geometry, dict):
            raise HTTPException(status_code=400, detail=f"第 {index} 个要素缺少有效几何")
        try:
            geom = shape(geometry)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"第 {index} 个要素几何无效：{exc}") from exc
        if geom.is_empty:
            raise HTTPException(status_code=400, detail=f"第 {index} 个要素几何为空")
        properties = raw_feature.get("properties")
        clean_properties = dict(properties) if isinstance(properties, dict) else {}
        clean_properties.pop("feature_id", None)
        clean_properties.pop("item_id", None)
        clean_properties.pop("project_id", None)
        display_role = str(clean_properties.pop("display_role", None) or raw_feature.get("display_role") or "feature")
        normalized_geometry = mapping(geom)
        bounds = _bounds_from_geom(geom)
        rows.append(
            (
                project_id,
                item_id,
                str(normalized_geometry.get("type") or geom.geom_type),
                _json(normalized_geometry),
                _json(clean_properties),
                _json(bounds) if bounds else None,
                display_role,
            )
        )
    return rows


def update_import_item_features(item_id: int, *, feature_collection: dict[str, Any]) -> ImportItemDetailResponse:
    migrate_legacy_datasets()
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM import_items WHERE id = ?", (item_id,))
        item_row = cursor.fetchone()
        if not item_row:
            raise HTTPException(status_code=404, detail="Import item not found")
        project_id = int(item_row["project_id"])
    feature_rows = _validated_feature_rows(project_id=project_id, item_id=item_id, feature_collection=feature_collection)
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM import_features WHERE item_id = ?", (item_id,))
        cursor.executemany(
            """
            INSERT INTO import_features (
                project_id, item_id, geometry_type, geometry_json, properties_json, bounds_json, display_role
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            feature_rows,
        )
    _recalculate_item(item_id)
    _recalculate_project(project_id)
    return get_import_item(item_id)


def delete_import_item(item_id: int) -> dict[str, Any]:
    with db_cursor() as cursor:
        cursor.execute("SELECT project_id, is_locked FROM import_items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Import item not found")
        if bool(row["is_locked"]):
            raise HTTPException(status_code=409, detail="数据项已锁定，不能删除")
        project_id = int(row["project_id"])
        cursor.execute("DELETE FROM import_items WHERE id = ?", (item_id,))
    _recalculate_project(project_id)
    return {"ok": True}


def _item_ids_for_projects(project_ids: list[int]) -> list[int]:
    if not project_ids:
        return []
    placeholders = ",".join("?" for _ in project_ids)
    with db_cursor() as cursor:
        cursor.execute(f"SELECT id FROM import_items WHERE project_id IN ({placeholders})", tuple(project_ids))
        direct_ids = [int(row["id"]) for row in cursor.fetchall()]
        cursor.execute(
            f"SELECT source_item_id FROM import_project_members WHERE project_id IN ({placeholders}) AND source_item_id IS NOT NULL",
            tuple(project_ids),
        )
        member_ids = [int(row["source_item_id"]) for row in cursor.fetchall()]
    return sorted(set(direct_ids + member_ids))


def combine_import_projects(*, name: str, project_ids: list[int], item_ids: list[int]) -> ImportProjectResponse:
    resolved_item_ids = sorted(set(item_ids + _item_ids_for_projects(project_ids)))
    if not resolved_item_ids:
        raise HTTPException(status_code=400, detail="请选择需要组合的项目或项")
    with db_cursor() as cursor:
        placeholders = ",".join("?" for _ in resolved_item_ids)
        cursor.execute(f"SELECT feature_count, geometry_types_json, bounds_json FROM import_items WHERE id IN ({placeholders})", tuple(resolved_item_ids))
        rows = [dict(row) for row in cursor.fetchall()]
    geometry_types: list[str] = []
    bounds_list: list[dict[str, float] | None] = []
    feature_count = 0
    for row in rows:
        feature_count += int(row.get("feature_count") or 0)
        bounds_list.append(_parse_json(row.get("bounds_json"), None))
        for geometry_type in _parse_json(row.get("geometry_types_json"), []):
            if geometry_type not in geometry_types:
                geometry_types.append(str(geometry_type))
    project_id = _create_project(
        name=name,
        import_type="combined",
        source_format="combined",
        file_name="combined",
        source_crs=None,
        target_crs="EPSG:4326",
        metadata={"source_project_ids": project_ids, "source_item_ids": resolved_item_ids},
    )
    with db_cursor() as cursor:
        for source_project_id in project_ids:
            cursor.execute(
                "INSERT INTO import_project_members (project_id, source_project_id, source_item_id) VALUES (?, ?, NULL)",
                (project_id, source_project_id),
            )
        for source_item_id in resolved_item_ids:
            cursor.execute(
                "INSERT INTO import_project_members (project_id, source_project_id, source_item_id) VALUES (?, NULL, ?)",
                (project_id, source_item_id),
            )
        cursor.execute(
            """
            UPDATE import_projects
            SET feature_count = ?, item_count = ?, geometry_types_json = ?, bounds_json = ?
            WHERE id = ?
            """,
            (feature_count, len(resolved_item_ids), _json(geometry_types), _json(_bounds_union(bounds_list)), project_id),
        )
    return _read_project(project_id)


def merge_import_items(*, name: str, item_ids: list[int]) -> ImportProjectResponse:
    if not item_ids:
        raise HTTPException(status_code=400, detail="请选择需要合并的项")
    placeholders = ",".join("?" for _ in item_ids)
    with db_cursor() as cursor:
        cursor.execute(f"SELECT * FROM import_features WHERE item_id IN ({placeholders})", tuple(item_ids))
        rows = [dict(row) for row in cursor.fetchall()]
    if not rows:
        raise HTTPException(status_code=400, detail="选中项没有可合并要素")
    geometries = [shape(_parse_json(row["geometry_json"], {})) for row in rows]
    polygon_geoms = [geom for geom in geometries if geom.geom_type in {"Polygon", "MultiPolygon"}]
    features: list[dict[str, Any]] = []
    if polygon_geoms and len(polygon_geoms) == len(geometries):
        merged = unary_union(polygon_geoms)
        features.append({"type": "Feature", "geometry": mapping(merged), "properties": {"name": name, "merged_from_item_ids": item_ids}})
    else:
        for row in rows:
            features.append({
                "type": "Feature",
                "geometry": _parse_json(row["geometry_json"], {}),
                "properties": {**_parse_json(row["properties_json"], {}), "merged_from_item_ids": item_ids},
            })
    project_id = _create_project_from_features(
        name=name,
        import_type="merged",
        source_format="mixed",
        file_name="merged.geojson",
        source_crs=None,
        target_crs="EPSG:4326",
        item_name=name,
        item_type="merged",
        features=features,
        metadata={"source_item_ids": item_ids},
    )
    return _read_project(project_id)


def _simplify_tolerance(zoom: int) -> float:
    if zoom <= 4:
        return 0.05
    if zoom <= 6:
        return 0.02
    if zoom <= 8:
        return 0.006
    if zoom <= 10:
        return 0.0015
    return 0.0


def query_import_map_features(
    *,
    bbox_text: str | None,
    zoom: int,
    item_ids_text: str | None,
    project_ids_text: str | None,
    max_features: int,
) -> ImportMapFeaturesResponse:
    migrate_legacy_datasets()
    bbox_dict = None
    bbox_geom = None
    if bbox_text:
        parts = [float(part) for part in bbox_text.split(",")]
        if len(parts) != 4:
            raise HTTPException(status_code=400, detail="bbox 格式应为 west,south,east,north")
        bbox_dict = {"west": parts[0], "south": parts[1], "east": parts[2], "north": parts[3]}
        bbox_geom = box(parts[0], parts[1], parts[2], parts[3])
    item_ids = [int(item) for item in item_ids_text.split(",") if item.strip()] if item_ids_text else []
    project_ids = [int(item) for item in project_ids_text.split(",") if item.strip()] if project_ids_text else []
    if project_ids:
        item_ids = sorted(set(item_ids + _item_ids_for_projects(project_ids)))

    params: list[Any] = []
    where = ["p.is_visible = 1", "i.is_visible = 1"]
    if item_ids:
        where.append(f"f.item_id IN ({','.join('?' for _ in item_ids)})")
        params.extend(item_ids)
    if bbox_dict:
        where.append("f.bounds_json IS NOT NULL")
    sql = f"""
        SELECT f.*, i.name AS item_name, i.airspace_level AS airspace_level,
               i.bounds_json AS item_bounds_json, i.metadata_json AS item_metadata_json,
               p.import_type AS project_import_type
        FROM import_features f
        JOIN import_items i ON i.id = f.item_id
        JOIN import_projects p ON p.id = f.project_id
        WHERE {' AND '.join(where)}
        ORDER BY f.id ASC
    """
    with db_cursor() as cursor:
        cursor.execute(sql, tuple(params))
        rows = [dict(row) for row in cursor.fetchall()]

    tolerance = _simplify_tolerance(zoom)
    features: list[dict[str, Any]] = []
    label_candidates: dict[int, dict[str, Any]] = {}
    matched_count = 0
    bounds_list: list[dict[str, float] | None] = []
    for row in rows:
        feature_bounds = _parse_json(row["bounds_json"], None)
        if not _bounds_intersects(feature_bounds, bbox_dict):
            continue
        geometry = shape(_parse_json(row["geometry_json"], {}))
        if bbox_geom is not None and not geometry.intersects(bbox_geom):
            continue
        matched_count += 1
        if len(features) >= max_features:
            continue
        render_geom = geometry.simplify(tolerance, preserve_topology=True) if tolerance and geometry.geom_type != "Point" else geometry
        properties = _parse_json(row["properties_json"], {})
        properties.update({
            "item_id": int(row["item_id"]),
            "project_id": int(row["project_id"]),
            "item_name": str(row.get("item_name") or ""),
            "airspace_level": str(row.get("airspace_level") or "suitable"),
            "display_role": str(row.get("display_role") or "feature"),
        })
        features.append({"type": "Feature", "geometry": mapping(render_geom), "properties": properties})
        bounds_list.append(_bounds_from_geom(render_geom))
        if row["project_import_type"] == "obstacle_surface" and int(row["item_id"]) not in label_candidates:
            item_metadata = _parse_json(row.get("item_metadata_json"), {})
            point = geometry.representative_point()
            label_candidates[int(row["item_id"])] = {
                "type": "Feature",
                "geometry": mapping(point),
                "properties": {
                    "name": str(row.get("item_name") or properties.get("airport_name") or "机场"),
                    "airport_name": item_metadata.get("airport_name") or properties.get("airport_name"),
                    "airport_code": item_metadata.get("airport_code") or properties.get("airport_code"),
                    "display_role": "airport_label",
                    "airspace_level": str(row.get("airspace_level") or "suitable"),
                    "item_id": int(row["item_id"]),
                    "project_id": int(row["project_id"]),
                },
            }
    if zoom >= 5 and len(label_candidates) <= 160:
        remaining = max(0, max_features - len(features))
        labels = list(label_candidates.values())[:remaining]
        features.extend(labels)
    return ImportMapFeaturesResponse(
        features=features,
        returned_count=len(features),
        total_count=matched_count,
        truncated=matched_count > max_features,
        bounds=_bounds_union(bounds_list),
    )


def export_import_geojson(project_ids_text: str | None, item_ids_text: str | None) -> dict[str, Any]:
    item_ids = [int(item) for item in item_ids_text.split(",") if item.strip()] if item_ids_text else []
    project_ids = [int(item) for item in project_ids_text.split(",") if item.strip()] if project_ids_text else []
    if project_ids:
        item_ids = sorted(set(item_ids + _item_ids_for_projects(project_ids)))
    if not item_ids:
        raise HTTPException(status_code=400, detail="请选择要导出的项目或项")
    placeholders = ",".join("?" for _ in item_ids)
    with db_cursor() as cursor:
        cursor.execute(f"SELECT * FROM import_features WHERE item_id IN ({placeholders}) ORDER BY id ASC", tuple(item_ids))
        rows = [dict(row) for row in cursor.fetchall()]
    features = [
        {
            "type": "Feature",
            "geometry": _parse_json(row["geometry_json"], {}),
            "properties": _parse_json(row["properties_json"], {}),
        }
        for row in rows
    ]
    return {"type": "FeatureCollection", "features": features}


def _normalize_airspace_level(value: Any) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "suitable": "suitable",
        "flyable": "suitable",
        "green": "suitable",
        "适飞区": "suitable",
        "适飞": "suitable",
        "limited": "limited",
        "restricted": "limited",
        "yellow": "limited",
        "限飞区": "limited",
        "限飞": "limited",
        "prohibited": "prohibited",
        "forbidden": "prohibited",
        "no-fly": "prohibited",
        "red": "prohibited",
        "禁飞区": "prohibited",
        "禁飞": "prohibited",
    }
    return mapping.get(text, "limited")


def _decode_text_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _table_to_text(frame: pd.DataFrame, *, max_rows: int = 120) -> str:
    view = frame.head(max_rows).copy()
    return view.to_csv(index=False)


def _docx_to_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    lines: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        parts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        text = "".join(parts).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _pdf_pages_to_text(data: bytes) -> list[str]:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return [(page.extract_text() or "").strip() for page in pdf.pages]
    except Exception:
        pass
    try:
        from pypdf import PdfReader
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception as exc:
            raise HTTPException(status_code=400, detail="PDF 解析需要安装 pypdf 或 PyPDF2") from exc
    reader = PdfReader(io.BytesIO(data))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def _pdf_to_text(data: bytes) -> str:
    return "\n\n".join(page for page in _pdf_pages_to_text(data) if page)


def _image_data_url(data: bytes, *, file_name: str, max_side: int = 1600, quality: int = 82) -> dict[str, Any]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((max_side, max_side))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            data = output.getvalue()
            mime = "image/jpeg"
    except Exception:
        mime = mimetypes.guess_type(file_name)[0] or "image/png"
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}",
            "detail": "high",
        },
    }


def _pdf_pages_to_images(data: bytes, *, file_name: str, page_texts: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    sparse_pages = [index for index, text in enumerate(page_texts) if len(text.strip()) < 120]
    if not sparse_pages and not any(page_texts):
        sparse_pages = list(range(AI_MAX_PDF_IMAGE_PAGES))
    sparse_pages = sparse_pages[:AI_MAX_PDF_IMAGE_PAGES]
    if not sparse_pages:
        return [], []
    try:
        import fitz  # PyMuPDF
    except Exception:
        return [], [f"{file_name} 可能是扫描版 PDF，但当前环境未安装 PyMuPDF，无法转为图片识别。"]

    images: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        document = fitz.open(stream=data, filetype="pdf")
        for page_index in sparse_pages:
            if page_index >= len(document):
                continue
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
            image_bytes = pixmap.tobytes("png")
            images.append(_image_data_url(image_bytes, file_name=f"{file_name}-page-{page_index + 1}.png"))
        document.close()
    except Exception as exc:
        warnings.append(f"{file_name} 扫描页转图片失败：{exc}")
    return images, warnings


def _extract_ai_file_data(file_name: str, content_type: str | None, data: bytes) -> tuple[str | None, list[dict[str, Any]], list[str]]:
    file_name = Path(file_name or "upload.dat").name
    suffix = Path(file_name).suffix.lower()
    if suffix in SUPPORTED_AI_IMAGE_EXTENSIONS or str(content_type or "").startswith("image/"):
        return None, [_image_data_url(data, file_name=file_name)], []
    if suffix not in SUPPORTED_AI_DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"AI 分析暂不支持文件类型：{suffix or file_name}")
    warnings: list[str] = []
    image_parts: list[dict[str, Any]] = []
    if suffix in {".txt", ".md", ".json", ".geojson"}:
        text = _decode_text_bytes(data)
    elif suffix == ".csv":
        try:
            frame = pd.read_csv(io.BytesIO(data), dtype=object)
        except UnicodeDecodeError:
            frame = pd.read_csv(io.BytesIO(data), dtype=object, encoding="gb18030")
        text = _table_to_text(frame)
    elif suffix in {".xls", ".xlsx"}:
        text = _table_to_text(pd.read_excel(io.BytesIO(data), dtype=object))
    elif suffix == ".docx":
        text = _docx_to_text(data)
    elif suffix == ".pdf":
        page_texts = _pdf_pages_to_text(data)
        text = "\n\n".join(f"第 {index + 1} 页：\n{page_text}" for index, page_text in enumerate(page_texts) if page_text)
        pdf_images, pdf_warnings = _pdf_pages_to_images(data, file_name=file_name, page_texts=page_texts)
        image_parts.extend(pdf_images)
        warnings.extend(pdf_warnings)
        if pdf_images:
            warnings.append(f"{file_name} 有 {len(pdf_images)} 页文本较少，已转为图片交给视觉模型识别。")
    else:
        text = ""
    return f"文件：{file_name}\n{text[:AI_FILE_TEXT_CHARS]}", image_parts, warnings


def _extract_ai_file_content(upload: UploadFile) -> tuple[str | None, list[dict[str, Any]], list[str]]:
    file_name = Path(upload.filename or "upload.dat").name
    data = upload.file.read()
    upload.file.seek(0)
    return _extract_ai_file_data(file_name, upload.content_type, data)


def _ai_base_url(provider: str, base_url: str | None) -> str:
    if provider == "custom":
        if not base_url or not base_url.strip():
            raise HTTPException(status_code=400, detail="自定义模型需要填写 Base URL")
        return base_url.strip().rstrip("/")
    preset = AI_MODEL_PRESETS.get(provider)
    if not preset:
        raise HTTPException(status_code=400, detail="不支持的大模型服务商")
    return str(preset["base_url"]).rstrip("/")


def _ai_default_model(provider: str, model: str | None) -> str:
    if model and model.strip():
        return model.strip()
    preset = AI_MODEL_PRESETS.get(provider)
    if not preset:
        raise HTTPException(status_code=400, detail="请填写模型名称")
    return str(preset["model"])


def _ai_model_supports_vision(provider: str, model_name: str) -> bool:
    if provider == "custom":
        return True
    normalized = model_name.lower()
    return any(hint in normalized for hint in AI_VISION_MODEL_HINTS.get(provider, ()))


def _chunk_ai_text(text: str, *, max_chars: int = AI_TEXT_CHUNK_CHARS) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    chunks: list[str] = []
    paragraphs = re.split(r"\n{2,}", normalized)
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(paragraph[index : index + max_chars] for index in range(0, len(paragraph), max_chars))
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _batched(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _ai_system_prompt() -> str:
    return (
        "你是低空空域数据分析智能体。请从用户提供的文档、文字和图片中识别空域范围，"
        "将每一项分类为 suitable(适飞区)、limited(限飞区)、prohibited(禁飞区)。"
        "只输出 JSON，格式为：{\"items\":[{\"name\":\"名称\",\"airspace_level\":\"suitable|limited|prohibited\","
        "\"geometry\":{\"type\":\"Polygon|MultiPolygon|LineString|Point\",\"coordinates\":[]},"
        "\"description\":\"依据说明\",\"evidence\":\"来源摘录\",\"confidence\":0.8}]}。"
        "所有坐标必须使用 WGS84，经纬度顺序为 [longitude, latitude]。没有明确坐标的内容不要编造几何。"
        "如果图片或 PDF 页面中出现坐标表、红黄绿空域图、边界文字说明，请尽量结合文字和视觉信息提取几何。"
    )


def _ai_user_content(text: str, image_parts: list[dict[str, Any]]) -> str | list[dict[str, Any]]:
    if not image_parts:
        return text
    return [{"type": "text", "text": text}, *image_parts]


def _call_ai_chat_completion(
    *,
    endpoint: str,
    api_key: str,
    model_name: str,
    user_text: str,
    image_parts: list[dict[str, Any]],
) -> str:
    request_payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _ai_system_prompt()},
            {"role": "user", "content": _ai_user_content(user_text, image_parts)},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=AI_HTTP_TIMEOUT) as client:
                response = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=request_payload,
                )
                response.raise_for_status()
                result = response.json()
            message = result.get("choices", [{}])[0].get("message", {})
            content_text = message.get("content")
            if not isinstance(content_text, str):
                raise HTTPException(status_code=502, detail="大模型响应中没有文本结果")
            return content_text
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status_code = exc.response.status_code
            detail_text = exc.response.text[:1000]
            if status_code == 400 and "response_format" in detail_text.lower() and "response_format" in request_payload:
                request_payload.pop("response_format", None)
                time.sleep(0.5)
                continue
            if status_code not in AI_RETRY_STATUS_CODES or attempt >= 2:
                raise HTTPException(status_code=502, detail=f"大模型调用失败：{detail_text}") from exc
        except httpx.TimeoutException as exc:
            last_error = exc
            if attempt >= 2:
                raise HTTPException(status_code=504, detail="大模型响应超时，请减少输入内容、分批上传文件，或更换响应更快的模型。") from exc
        except httpx.TransportError as exc:
            last_error = exc
            if attempt >= 2:
                raise HTTPException(status_code=502, detail=f"大模型网络连接失败：{exc}") from exc
        time.sleep(1.5 * (attempt + 1))
    raise HTTPException(status_code=502, detail=f"大模型调用失败：{last_error}")


def _extract_json_payload(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            raise HTTPException(status_code=502, detail="大模型未返回可解析的 JSON")
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="大模型 JSON 结果格式无效")
    return payload


def _features_from_ai_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list):
        source_items = payload["features"]
    else:
        source_items = payload.get("items")
    if not isinstance(source_items, list) or not source_items:
        raise HTTPException(status_code=502, detail="大模型未识别出可导入的空域范围")
    features: list[dict[str, Any]] = []
    for index, item in enumerate(source_items, start=1):
        if not isinstance(item, dict):
            continue
        geometry = item.get("geometry") if item.get("type") != "Feature" else item.get("geometry")
        if not isinstance(geometry, dict):
            continue
        try:
            geom = shape(geometry)
        except Exception:
            continue
        if geom.is_empty:
            continue
        properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        name = str(item.get("name") or properties.get("name") or f"AI 空域范围 {index}")
        airspace_level = _normalize_airspace_level(item.get("airspace_level") or item.get("category") or properties.get("airspace_level"))
        feature_properties = {
            **properties,
            "name": name,
            "airspace_level": airspace_level,
            "airspace_label": AIRSPACE_LABELS[airspace_level],
            "description": item.get("description") or properties.get("description"),
            "confidence": item.get("confidence") or properties.get("confidence"),
            "evidence": item.get("evidence") or properties.get("evidence"),
            "source": "ai_agent",
        }
        features.append({"type": "Feature", "geometry": mapping(geom), "properties": feature_properties})
    if not features:
        raise HTTPException(status_code=502, detail="大模型结果中没有有效几何")
    return features


def _ai_preview_response(
    *,
    name: str,
    provider: str,
    model_name: str,
    file_names: list[str],
    features: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    preview_features: list[dict[str, Any]] = []
    preview_items: list[dict[str, Any]] = []
    for index, feature in enumerate(features, start=1):
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else None
        if not geometry:
            continue
        level = _normalize_airspace_level(properties.get("airspace_level"))
        item_name = str(properties.get("name") or f"AI 空域范围 {index}")
        preview_properties = {
            **properties,
            "name": item_name,
            "airspace_level": level,
            "airspace_label": AIRSPACE_LABELS[level],
            "display_role": "ai_preview",
            "preview": True,
            "source": "ai_agent_preview",
        }
        preview_features.append({"type": "Feature", "geometry": geometry, "properties": preview_properties})
        preview_items.append(
            {
                "name": item_name,
                "airspace_level": level,
                "geometry": geometry,
                "properties": preview_properties,
                "description": preview_properties.get("description"),
                "evidence": preview_properties.get("evidence"),
                "confidence": preview_properties.get("confidence"),
            }
        )
    if not preview_items:
        raise HTTPException(status_code=502, detail="大模型结果中没有有效几何")
    metadata = {
        "provider": provider,
        "model": model_name,
        "file_names": file_names,
        "source": "ai_agent_preview",
        "item_count": len(preview_items),
        "warnings": warnings or [],
    }
    return {
        "ok": True,
        "name": name,
        "provider": provider,
        "model": model_name,
        "item_count": len(preview_items),
        "items": preview_items,
        "feature_collection": {"type": "FeatureCollection", "features": preview_features},
        "metadata": metadata,
        "warnings": warnings or [],
    }


def _analyze_ai_airspace_records(
    *,
    file_records: list[dict[str, Any]],
    name: str | None,
    provider: str,
    model: str | None,
    api_key: str,
    base_url: str | None,
    text: str | None,
    instruction: str | None,
    progress: Callable[[str, float, str, int | None, int | None], None] | None = None,
) -> dict[str, Any]:
    api_key = api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="请填写 API Key")
    provider = (provider or "openai").strip().lower()
    model_name = _ai_default_model(provider, model)
    endpoint = f"{_ai_base_url(provider, base_url)}/chat/completions"
    document_chunks: list[str] = []
    image_parts: list[dict[str, Any]] = []
    warnings: list[str] = []
    file_names: list[str] = []
    if progress:
        progress("reading", 10, "正在读取上传内容", len(file_records), 0)
    for index, record in enumerate(file_records, start=1):
        file_name = str(record.get("file_name") or "upload.dat")
        file_names.append(Path(file_name).name)
        document_text, image_part, file_warnings = _extract_ai_file_data(
            file_name,
            str(record.get("content_type") or "") or None,
            record.get("data") if isinstance(record.get("data"), bytes) else b"",
        )
        if document_text:
            document_chunks.append(document_text)
        image_parts.extend(image_part)
        warnings.extend(file_warnings)
        if progress:
            progress("reading", 10 + min(15, index / max(1, len(file_records)) * 15), "正在预处理上传内容", len(file_records), index)
    input_text = (text or "").strip()
    if not input_text and not document_chunks and not image_parts:
        raise HTTPException(status_code=400, detail="请上传文件、图片，或输入待分析文字")
    if image_parts and not _ai_model_supports_vision(provider, model_name):
        raise HTTPException(status_code=400, detail=f"当前模型 {model_name} 可能不支持图片或扫描 PDF 识别，请切换视觉模型后重试。")
    if len(image_parts) > AI_MAX_IMAGE_PARTS:
        warnings.append(f"图片/PDF 页面较多，本次仅分析前 {AI_MAX_IMAGE_PARTS} 张视觉内容。")
        image_parts = image_parts[:AI_MAX_IMAGE_PARTS]

    combined_text = "\n\n".join(
        item
        for item in [
            f"任务补充要求：{instruction.strip()}" if instruction and instruction.strip() else "",
            f"用户输入文字：\n{input_text}" if input_text else "",
            "\n\n".join(document_chunks),
        ]
        if item
    )[:AI_TOTAL_TEXT_CHARS]
    text_chunks = _chunk_ai_text(combined_text)
    image_batches = _batched(image_parts, AI_IMAGES_PER_BATCH)
    requests: list[tuple[str, list[dict[str, Any]]]] = []
    requests.extend((chunk, []) for chunk in text_chunks)
    requests.extend(("请识别这些图片或 PDF 页面中的空域范围、边界坐标、限制说明和空域分类，只输出 JSON。", batch) for batch in image_batches)
    if not requests:
        requests.append(("请根据上传内容识别空域范围和空域分类，只输出 JSON。", []))

    features: list[dict[str, Any]] = []
    failed_batches: list[str] = []
    if progress:
        progress("parsing", 30, "正在调用大模型识别空域", len(requests), 0)
    for index, (request_text, request_images) in enumerate(requests, start=1):
        try:
            content_text = _call_ai_chat_completion(
                endpoint=endpoint,
                api_key=api_key,
                model_name=model_name,
                user_text=request_text,
                image_parts=request_images,
            )
            batch_features = _features_from_ai_payload(_extract_json_payload(content_text))
            features.extend(batch_features)
        except HTTPException as exc:
            failed_batches.append(str(exc.detail))
        if progress:
            batch_progress = 30 + min(55, index / max(1, len(requests)) * 55)
            progress("parsing", batch_progress, f"正在分析第 {index} / {len(requests)} 批内容", len(requests), index)
    if failed_batches:
        warnings.extend(f"第 {index + 1} 批识别失败：{message}" for index, message in enumerate(failed_batches[:5]))
    if not features:
        detail = "；".join(failed_batches[:3]) or "大模型未识别出可导入的空域范围"
        raise HTTPException(status_code=502, detail=detail)
    dataset_name = (name or "AI 智能体空域分析").strip() or "AI 智能体空域分析"
    if progress:
        progress("saving", 92, "正在生成地图预览", len(requests), len(requests))
    return _ai_preview_response(
        name=dataset_name,
        provider=provider,
        model_name=model_name,
        file_names=file_names,
        features=features,
        warnings=warnings,
    )


def analyze_ai_airspace_import(
    *,
    files: list[UploadFile],
    name: str | None,
    provider: str,
    model: str | None,
    api_key: str,
    base_url: str | None,
    text: str | None,
    instruction: str | None,
) -> dict[str, Any]:
    file_records: list[dict[str, Any]] = []
    for upload in files:
        file_records.append(
            {
                "file_name": Path(upload.filename or "upload.dat").name,
                "content_type": upload.content_type,
                "data": upload.file.read(),
            }
        )
        upload.file.seek(0)
    return _analyze_ai_airspace_records(
        file_records=file_records,
        name=name,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        text=text,
        instruction=instruction,
    )


def create_ai_airspace_import_job(
    files: list[UploadFile],
    *,
    name: str | None,
    provider: str,
    model: str | None,
    api_key: str,
    base_url: str | None,
    text: str | None,
    instruction: str | None,
    background_tasks: Any,
) -> ImportJobResponse:
    if not api_key.strip():
        raise HTTPException(status_code=400, detail="请填写 API Key")
    if not (text or "").strip() and not files:
        raise HTTPException(status_code=400, detail="请上传文件、图片，或输入待分析文字")
    provider_normalized = (provider or "openai").strip().lower()
    model_name = _ai_default_model(provider_normalized, model)
    has_direct_image = any(
        Path(upload.filename or "").suffix.lower() in SUPPORTED_AI_IMAGE_EXTENSIONS
        or str(upload.content_type or "").startswith("image/")
        for upload in files
    )
    if has_direct_image and not _ai_model_supports_vision(provider_normalized, model_name):
        raise HTTPException(status_code=400, detail=f"当前模型 {model_name} 可能不支持图片识别，请切换视觉模型后重试。")
    job_id = _create_job("ai_airspace", message="AI 识别任务已创建，等待处理")
    job_dir = JOB_UPLOAD_DIR / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    file_records: list[dict[str, Any]] = []
    for index, upload in enumerate(files, start=1):
        original_name = Path(upload.filename or "upload.dat").name
        target = job_dir / f"{index:03d}_{original_name}"
        with target.open("wb") as handle:
            shutil.copyfileobj(upload.file, handle)
        file_records.append({"path": str(target), "file_name": original_name, "content_type": upload.content_type})
    background_tasks.add_task(
        run_ai_airspace_import_job,
        job_id,
        file_records,
        name,
        provider,
        model,
        api_key,
        base_url,
        text,
        instruction,
    )
    return get_import_job(job_id)


def run_ai_airspace_import_job(
    job_id: int,
    file_records: list[dict[str, Any]],
    name: str | None,
    provider: str,
    model: str | None,
    api_key: str,
    base_url: str | None,
    text: str | None,
    instruction: str | None,
) -> None:
    job_dir = JOB_UPLOAD_DIR / str(job_id)

    def report(phase: str, progress: float, message: str, total: int | None, processed: int | None) -> None:
        _update_job(
            job_id,
            status="running",
            phase=phase,
            progress=progress,
            message=message,
            total_count=total,
            processed_count=processed,
        )

    try:
        _update_job(job_id, status="running", phase="reading", progress=5, message="正在读取 AI 分析输入")
        records_with_data: list[dict[str, Any]] = []
        for record in file_records:
            path = Path(str(record.get("path") or ""))
            records_with_data.append(
                {
                    "file_name": record.get("file_name") or path.name,
                    "content_type": record.get("content_type"),
                    "data": path.read_bytes(),
                }
            )
        preview = _analyze_ai_airspace_records(
            file_records=records_with_data,
            name=name,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            text=text,
            instruction=instruction,
            progress=report,
        )
        _update_job(
            job_id,
            status="completed",
            phase="completed",
            progress=100,
            message=f"AI 识别完成，生成 {len(preview.get('items') or [])} 个预览项",
            result={"preview": preview, "warnings": preview.get("warnings", [])},
            completed=True,
        )
    except HTTPException as exc:
        _update_job(job_id, status="failed", phase="failed", progress=100, message="AI 识别失败", error=str(exc.detail), completed=True)
    except Exception as exc:
        _update_job(job_id, status="failed", phase="failed", progress=100, message="AI 识别失败", error=str(exc), completed=True)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


def commit_ai_airspace_import(
    *,
    name: str,
    items: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> ImportProjectResponse:
    prepared_items: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        geometry = item.get("geometry")
        if not isinstance(geometry, dict):
            continue
        try:
            geom = shape(geometry)
        except Exception:
            continue
        if geom.is_empty:
            continue
        properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        level = _normalize_airspace_level(item.get("airspace_level") or properties.get("airspace_level"))
        item_name = str(item.get("name") or properties.get("name") or f"AI 空域范围 {index}")
        feature_properties = {
            **properties,
            "name": item_name,
            "airspace_level": level,
            "airspace_label": AIRSPACE_LABELS[level],
            "display_role": "feature",
            "preview": False,
            "source": "ai_agent_confirmed",
        }
        feature = {"type": "Feature", "geometry": mapping(geom), "properties": feature_properties}
        item_metadata = {
            "airspace_level": level,
            "airspace_label": AIRSPACE_LABELS[level],
            "description": item.get("description") or feature_properties.get("description"),
            "evidence": item.get("evidence") or feature_properties.get("evidence"),
            "confidence": item.get("confidence") or feature_properties.get("confidence"),
            "source": "ai_agent_confirmed",
        }
        prepared_items.append((item_name, level, feature, item_metadata))
    if not prepared_items:
        raise HTTPException(status_code=400, detail="没有可确认入库的 AI 识别结果")

    project_metadata = {
        **(metadata or {}),
        "source": "ai_agent_confirmed",
        "item_count": len(prepared_items),
    }
    project_id = _create_project(
        name=name.strip() or "AI 智能体空域分析",
        import_type="ai",
        source_format="geojson",
        file_name="ai-analysis-confirmed.geojson",
        source_crs="EPSG:4326",
        target_crs="EPSG:4326",
        metadata=project_metadata,
    )
    for item_name, level, feature, item_metadata in prepared_items:
        item_id = _create_item(
            project_id=project_id,
            name=item_name,
            item_type="ai_airspace",
            airspace_level=level,
            metadata=item_metadata,
        )
        _insert_feature(project_id=project_id, item_id=item_id, feature=feature, display_role="feature")
        _recalculate_item(item_id)
    _recalculate_project(project_id)
    return _read_project(project_id)


def detect_kml_or_shp_support() -> dict[str, Any]:
    return {
        "formats": ["kml", "shp", "geojson", "xls", "xlsx", "csv"],
        "import_types": [{"id": key, "label": value} for key, value in IMPORT_TYPE_LABELS.items()],
        "upload_suffixes": [".kml", ".shp", ".zip", ".xls", ".xlsx", ".csv"],
        "target_crs_default": "EPSG:4326",
        "notes": [
            "矢量数据支持 KML、SHP 或包含完整 SHP 文件组的 ZIP 包。",
            "障碍物限制面直接导入按机场聚合管理，地图默认只显示限制面区域和机场标注。",
            "大数据地图按视口和缩放级别按需加载，避免一次性渲染全量要素。",
        ],
    }
