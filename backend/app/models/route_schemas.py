from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

DEFAULT_LAYER_SCHEME = "60-90,90-120,120-180,180-240,240-300"


class RouteBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    flight_width: float = Field(ge=1)
    protection_width: float = Field(ge=0)
    bottom_height: float = Field(ge=0)
    top_height: float = Field(ge=0)
    min_turn_radius: float = Field(default=0, ge=0)
    turn_mode: Literal["angle", "arc"] = "angle"
    altitude_reference_mode: Literal["asl", "agl"] = "asl"
    altitude_change_min: float = Field(default=10, ge=0, le=500)
    enable_layering: bool = True
    layer_step: float = Field(default=50, ge=10, le=300)
    layer_scheme: str = Field(default=DEFAULT_LAYER_SCHEME, min_length=1, max_length=200)

    @field_validator("top_height")
    @classmethod
    def validate_height(cls, value: float, info):
        bottom = info.data.get("bottom_height")
        if bottom is not None and value <= bottom:
            raise ValueError("top_height must be greater than bottom_height")
        return value


class RouteCreate(RouteBase):
    pass


class RouteUpdate(RouteBase):
    pass


class RouteResponse(RouteBase):
    id: int
    is_complete: bool = False
    last_generated_at: str | None = None


class RoutePointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    point_type: Literal["start", "waypoint", "end"] = "waypoint"
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    altitude: float = Field(default=0)
    order_index: int | None = None


class RoutePointUpdate(RoutePointCreate):
    pass


class LandingSiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    altitude: float = Field(default=0)
    altitude_source: str = Field(default="manual", max_length=80)
    altitude_confirmed: bool = False


class LandingSiteUpdate(LandingSiteCreate):
    pass


class AircraftPerformanceParams(BaseModel):
    cruise_speed_kmh: float = Field(default=54, gt=0, le=240)
    max_climb_rate_ms: float = Field(default=3, gt=0, le=30)
    max_descent_rate_ms: float = Field(default=2.5, gt=0, le=30)
    min_turn_radius_m: float = Field(default=20, ge=0, le=1000)
    max_flight_time_min: float = Field(default=35, gt=0, le=600)
    reserve_time_min: float = Field(default=5, ge=0, le=300)
    horizontal_deviation_m: float = Field(default=15, ge=0, le=500)
    vertical_deviation_m: float = Field(default=10, ge=0, le=300)
    waiting_height_agl_m: float = Field(default=30, ge=0, le=300)
    max_attach_distance_m: float = Field(default=2000, gt=0, le=50000)
    min_clearance_m: float = Field(default=15, ge=0, le=300)
    wingspan_m: float = Field(default=18, ge=0, le=200)
    max_ground_speed_ms: float = Field(default=55, gt=0, le=200)
    response_time_s: float = Field(default=3, ge=0, le=120)
    max_roll_angle_deg: float = Field(default=25, gt=0, lt=89)
    max_heading_deviation_deg: float = Field(default=30, ge=0, le=180)
    climb_gradient: float = Field(default=0.065, gt=0, le=1)
    descent_gradient: float = Field(default=0.041, gt=0, le=1)
    fte_horizontal_m: float = Field(default=10, ge=0, le=500)
    nse_horizontal_m: float = Field(default=10, ge=0, le=500)
    fte_vertical_m: float = Field(default=5, ge=0, le=300)
    nse_vertical_m: float = Field(default=5, ge=0, le=300)
    body_height_m: float = Field(default=6, ge=0, le=100)
    altitude_measurement_error_m: float = Field(default=5, ge=0, le=300)
    pitch_deviation_deg: float = Field(default=5, ge=0, le=45)
    max_pitch_adjust_deg: float = Field(default=15, ge=0, le=60)
    additional_moc_m: float = Field(default=0, ge=0, le=500)
    abnormal_area_enabled: bool = True
    abnormal_height_enabled: bool = True


class TakeoffFlightPlanRequest(BaseModel):
    landing_id: int
    target_layer_sequence: int | None = None
    aircraft_platform: Literal["vtol", "fixed_wing"] = "vtol"
    aircraft_preset: Literal["micro", "light", "fp98", "custom"] = "micro"
    aircraft_params: AircraftPerformanceParams
    entry_attach_point: dict[str, float] | None = None
    exit_attach_point: dict[str, float] | None = None


class KMLExportRequest(BaseModel):
    route_id: int


class RouteCloneRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)


class SubRouteExtractRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)


class DatasourceTestRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    timeout: int = Field(default=10, ge=1, le=60)


class RouteGeoExtractRequest(BaseModel):
    datasource_url: str | None = Field(default=None, max_length=500)


class AnalysisRunRequest(BaseModel):
    aircraft_type: Literal["micro", "light"] = "micro"
    factor_ids: list[str] | None = None
    param_overrides: dict[str, dict[str, Any]] | None = None


class AnalysisFactorInputUpdateRequest(BaseModel):
    input_mode: Literal["auto", "manual"] = "auto"
    manual_value: dict[str, Any] = Field(default_factory=dict)


class AnalysisFactorParamsUpdateRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class AnalysisFactorRunRequest(BaseModel):
    aircraft_type: Literal["micro", "light"] = "micro"
    param_override: dict[str, Any] = Field(default_factory=dict)


class AnalysisAuthoritativeLayerImportRequest(BaseModel):
    factor_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    version: str | None = Field(default=None, max_length=80)
    source: str | None = Field(default=None, max_length=200)
    priority: int = Field(default=100, ge=0, le=10000)
    enabled: bool = True
    geojson: dict[str, Any]


class AnalysisAuthoritativeLayerUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    version: str | None = Field(default=None, max_length=80)
    source: str | None = Field(default=None, max_length=200)
    priority: int | None = Field(default=None, ge=0, le=10000)
    enabled: bool | None = None


class ImportedDatasetSummary(BaseModel):
    id: int
    name: str
    import_type: Literal["vector", "obstacle_surface", "manual", "ai"]
    source_format: Literal["kml", "shp", "geojson", "xls", "xlsx", "csv"]
    file_name: str
    source_crs: str | None = None
    target_crs: str
    feature_count: int
    geometry_types: list[str] = Field(default_factory=list)
    bounds: dict[str, float] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ImportedDatasetResponse(ImportedDatasetSummary):
    feature_collection: dict[str, Any]
    import_summary: dict[str, Any] | None = None


class ImportedDatasetGeoJsonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    import_type: Literal["vector", "obstacle_surface", "manual", "ai"] = "manual"
    source_crs: str | None = Field(default=None, max_length=80)
    target_crs: str = Field(default="EPSG:4326", min_length=1, max_length=80)
    feature_collection: dict[str, Any]


class ImportProjectSummary(BaseModel):
    id: int
    name: str
    import_type: Literal["vector", "obstacle_surface", "manual", "ai", "combined", "merged"]
    source_format: Literal["kml", "shp", "geojson", "xls", "xlsx", "csv", "combined", "mixed"]
    file_name: str
    source_crs: str | None = None
    target_crs: str
    feature_count: int
    item_count: int
    geometry_types: list[str] = Field(default_factory=list)
    bounds: dict[str, float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_visible: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class ImportItemSummary(BaseModel):
    id: int
    project_id: int
    name: str
    item_type: str
    airspace_level: Literal["suitable", "limited", "prohibited"] = "suitable"
    feature_count: int
    geometry_types: list[str] = Field(default_factory=list)
    bounds: dict[str, float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_visible: bool = True
    is_locked: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class ImportItemDetailResponse(ImportItemSummary):
    feature_collection: dict[str, Any]


class ImportProjectResponse(ImportProjectSummary):
    items: list[ImportItemSummary] = Field(default_factory=list)


class ImportProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    is_visible: bool | None = None


class ImportItemUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    is_visible: bool | None = None
    is_locked: bool | None = None
    airspace_level: Literal["suitable", "limited", "prohibited"] | None = None


class ImportItemFeaturesUpdateRequest(BaseModel):
    feature_collection: dict[str, Any]


class AiAirspaceCommitRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    items: list[dict[str, Any]] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportJobResponse(BaseModel):
    id: int
    job_type: str
    status: Literal["queued", "running", "completed", "failed"]
    phase: Literal["queued", "reading", "parsing", "saving", "completed", "failed"]
    progress: float
    message: str = ""
    error: str | None = None
    total_count: int | None = None
    processed_count: int = 0
    result_project_id: int | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class ImportCombineRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    project_ids: list[int] = Field(default_factory=list)
    item_ids: list[int] = Field(default_factory=list)


class ImportMergeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    item_ids: list[int] = Field(min_length=1)


class ImportMapFeaturesResponse(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[dict[str, Any]] = Field(default_factory=list)
    returned_count: int = 0
    total_count: int = 0
    truncated: bool = False
    bounds: dict[str, float] | None = None
