from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile

from app.models.route_schemas import (
    AiAirspaceCommitRequest,
    ImportCombineRequest,
    ImportItemFeaturesUpdateRequest,
    ImportItemUpdateRequest,
    ImportMergeRequest,
    ImportProjectUpdateRequest,
    ImportedDatasetGeoJsonCreate,
    ImportedDatasetResponse,
)
from app.services.import_service import (
    analyze_ai_airspace_import,
    combine_import_projects,
    commit_ai_airspace_import,
    create_ai_airspace_import_job,
    create_obstacle_surface_import_job,
    delete_import_item,
    delete_import_project,
    delete_imported_dataset,
    detect_kml_or_shp_support,
    export_import_geojson,
    get_import_job,
    get_import_item,
    get_import_project,
    get_imported_dataset,
    import_dataset,
    import_geojson_dataset,
    import_obstacle_surface_dataset,
    list_import_items,
    list_import_projects,
    list_imported_datasets,
    merge_import_items,
    query_import_map_features,
    update_import_item_features,
    update_import_item,
    update_import_project,
)

router = APIRouter(prefix="/imports", tags=["imports"])


@router.get("/capabilities")
def read_import_capabilities():
    return detect_kml_or_shp_support()


@router.get("/projects")
def read_import_projects():
    return {"items": list_import_projects()}


@router.post("/projects/combine")
def combine_projects(payload: ImportCombineRequest):
    return combine_import_projects(name=payload.name, project_ids=payload.project_ids, item_ids=payload.item_ids)


@router.get("/projects/{project_id}")
def read_import_project(project_id: int):
    return get_import_project(project_id)


@router.patch("/projects/{project_id}")
def patch_import_project(project_id: int, payload: ImportProjectUpdateRequest):
    return update_import_project(project_id, name=payload.name, is_visible=payload.is_visible)


@router.delete("/projects/{project_id}")
def remove_import_project(project_id: int):
    return delete_import_project(project_id)


@router.get("/items")
def read_import_items(project_id: int | None = Query(default=None)):
    return {"items": list_import_items(project_id=project_id)}


@router.post("/items/merge")
def merge_items(payload: ImportMergeRequest):
    return merge_import_items(name=payload.name, item_ids=payload.item_ids)


@router.get("/items/{item_id}")
def read_import_item(item_id: int):
    return get_import_item(item_id)


@router.patch("/items/{item_id}")
def patch_import_item(item_id: int, payload: ImportItemUpdateRequest):
    return update_import_item(
        item_id,
        name=payload.name,
        is_visible=payload.is_visible,
        is_locked=payload.is_locked,
        airspace_level=payload.airspace_level,
    )


@router.put("/items/{item_id}/features")
def replace_import_item_features(item_id: int, payload: ImportItemFeaturesUpdateRequest):
    return update_import_item_features(item_id, feature_collection=payload.feature_collection)


@router.delete("/items/{item_id}")
def remove_import_item(item_id: int):
    return delete_import_item(item_id)


@router.get("/map-features")
def read_map_features(
    bbox: str | None = Query(default=None),
    zoom: int = Query(default=5, ge=0, le=22),
    item_ids: str | None = Query(default=None),
    project_ids: str | None = Query(default=None),
    max_features: int = Query(default=1200, ge=1, le=10000),
):
    return query_import_map_features(
        bbox_text=bbox,
        zoom=zoom,
        item_ids_text=item_ids,
        project_ids_text=project_ids,
        max_features=max_features,
    )


@router.get("/export.geojson")
def export_geojson(project_ids: str | None = Query(default=None), item_ids: str | None = Query(default=None)):
    return export_import_geojson(project_ids_text=project_ids, item_ids_text=item_ids)


@router.post("/jobs/obstacle-surface/upload")
async def create_obstacle_surface_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    source_crs: str | None = Form(default="EPSG:4326"),
    target_crs: str | None = Form(default="EPSG:4326"),
):
    return create_obstacle_surface_import_job(
        file,
        name=name,
        source_crs=source_crs,
        target_crs=target_crs,
        background_tasks=background_tasks,
    )


@router.get("/jobs/{job_id}")
def read_import_job(job_id: int):
    return get_import_job(job_id)


@router.get("/datasets")
def read_imported_datasets():
    return {"items": list_imported_datasets()}


@router.get("/datasets/{dataset_id}", response_model=ImportedDatasetResponse)
def read_imported_dataset(dataset_id: int):
    return get_imported_dataset(dataset_id)


@router.post("/datasets/upload", response_model=ImportedDatasetResponse)
async def create_imported_dataset(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    source_crs: str | None = Form(default=None),
    target_crs: str | None = Form(default="EPSG:4326"),
):
    return import_dataset(file, name=name, source_crs=source_crs, target_crs=target_crs)


@router.post("/datasets/obstacle-surface/upload", response_model=ImportedDatasetResponse)
async def create_obstacle_surface_dataset(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    source_crs: str | None = Form(default="EPSG:4326"),
    target_crs: str | None = Form(default="EPSG:4326"),
):
    return import_obstacle_surface_dataset(file, name=name, source_crs=source_crs, target_crs=target_crs)


@router.post("/datasets/geojson", response_model=ImportedDatasetResponse)
def create_geojson_dataset(payload: ImportedDatasetGeoJsonCreate):
    return import_geojson_dataset(payload)


@router.post("/ai/analyze")
async def analyze_ai_import(
    files: list[UploadFile] | None = File(default=None),
    name: str | None = Form(default=None),
    provider: str = Form(default="openai"),
    model: str | None = Form(default=None),
    api_key: str = Form(default=""),
    base_url: str | None = Form(default=None),
    text: str | None = Form(default=None),
    instruction: str | None = Form(default=None),
):
    return analyze_ai_airspace_import(
        files=files or [],
        name=name,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        text=text,
        instruction=instruction,
    )


@router.post("/ai/analyze-job")
async def analyze_ai_import_job(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] | None = File(default=None),
    name: str | None = Form(default=None),
    provider: str = Form(default="openai"),
    model: str | None = Form(default=None),
    api_key: str = Form(default=""),
    base_url: str | None = Form(default=None),
    text: str | None = Form(default=None),
    instruction: str | None = Form(default=None),
):
    return create_ai_airspace_import_job(
        files=files or [],
        name=name,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        text=text,
        instruction=instruction,
        background_tasks=background_tasks,
    )


@router.post("/ai/commit")
def commit_ai_import(payload: AiAirspaceCommitRequest):
    return commit_ai_airspace_import(name=payload.name, items=payload.items, metadata=payload.metadata)


@router.delete("/datasets/{dataset_id}")
def remove_imported_dataset(dataset_id: int):
    return delete_imported_dataset(dataset_id)
