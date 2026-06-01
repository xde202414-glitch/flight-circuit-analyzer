"""Track-related Pydantic models."""
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Literal, Optional

from app.models.runway import Coordinate, RunwayParams


def to_camel(string: str) -> str:
    """Convert snake_case to camelCase."""
    components = string.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


TrackSegmentName = Literal[
    "departure",
    "turn_1",
    "crosswind_leg",
    "turn_2",
    "downwind_leg",
    "turn_3",
    "base_leg",
    "turn_4",
    "final_approach",
]

GeometryKind = Literal["polyline", "polygon", "arc", "marker"]
TrafficPatternSide = Literal["left", "right"]
ActiveRunwayEnd = Literal["primary", "reciprocal"]
AnnotationStyleKey = Literal["segment-label", "point-label", "performance-label", "turn-label"]
RunwayCodeNumber = Literal["1", "2", "3", "4", "auto"]
RunwayOperationType = Literal[
    "non_instrument",
    "non_precision",
    "precision_cat_i",
    "precision_cat_ii_iii",
]
VisualJoinMethod = Literal["standard", "straight_in", "crosswind", "downwind", "overhead"]
FlightCampType = Literal[
    "glider",
    "aerobatic",
    "powered_hang_glider",
    "light_aircraft",
    "helicopter",
    "gyroplane",
    "balloon_airship",
    "hang_glider",
    "paraglider",
    "powered_paraglider",
    "aero_model",
    "water_sport_aircraft",
    "skydiving",
]
ComplianceStatus = Literal["compliant", "custom_compliant", "non_compliant", "warning", "info"]


class GeometryOverlay(BaseModel):
    """Generic map geometry returned by the procedure calculator."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str = Field(..., description="Stable geometry identifier")
    kind: GeometryKind = Field(..., description="Geometry rendering kind")
    label: str = Field(..., description="Display label")
    coordinates: List[Coordinate] = Field(
        default_factory=list,
        description="Geometry coordinates; markers use a single coordinate",
    )
    style_key: str = Field(default="default", description="Frontend style key")
    altitude: Optional[float] = Field(default=None, description="Altitude in meters")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Regulation and rendering metadata",
    )


class VisualPatternConfig(BaseModel):
    """AP-91/AC-97 visual traffic pattern configuration."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    performance_class: Optional[Literal["A", "B", "C", "D"]] = Field(default=None)
    standard_circuit_height: Optional[float] = Field(default=None, ge=100, le=1200)
    max_ias_kmh: Optional[int] = Field(default=None, ge=80, le=500)
    stable_final_distance: Optional[float] = Field(default=None, ge=500, le=10000)
    first_turn_min_height: Optional[float] = Field(default=None, ge=0, le=1000)
    final_turn_min_height: Optional[float] = Field(default=None, ge=0, le=1000)
    join_method: VisualJoinMethod = Field(default="standard")


class ObstacleSurfaceConfig(BaseModel):
    """MH5001/ICAO Annex 14 obstacle limitation surface configuration."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    code_number: RunwayCodeNumber = Field(default="1")
    code_letter: Optional[Literal["A", "B", "C", "D", "E", "F"]] = Field(default=None)
    runway_operation_type: RunwayOperationType = Field(default="non_instrument")
    takeoff_enabled: bool = Field(default=True)
    bidirectional_envelope_enabled: bool = Field(default=True)
    show_individual_surfaces: bool = Field(default=True)


class FlightCampAirspaceConfig(BaseModel):
    """Flight camp airspace configuration by sport aviation category."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    enabled: bool = Field(default=True)
    camp_type: FlightCampType = Field(default="light_aircraft")
    radius_m: Optional[float] = Field(default=None, ge=100, le=50000)
    true_height_m: Optional[float] = Field(default=None, ge=30, le=6000)
    clearance_radius_m: Optional[float] = Field(default=None, ge=0, le=10000)
    overlay_special_airspace: bool = Field(default=False)


class ComplianceItem(BaseModel):
    """Normative compliance hint returned with the calculated procedure."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    category: Literal["visual_pattern", "obstacle_surface", "flight_camp_airspace"]
    status: ComplianceStatus
    message: str
    source_code: str = Field(default="")
    clause: str = Field(default="")
    severity: Literal["info", "warning", "error"] = Field(default="info")
    details: Optional[Dict[str, Any]] = Field(default=None)


class ProcedureAnnotation(BaseModel):
    """Always-visible procedure chart annotation."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str = Field(..., description="Stable annotation identifier")
    coordinate: Coordinate = Field(..., description="Annotation anchor coordinate")
    label: str = Field(..., description="Short annotation label")
    lines: List[str] = Field(default_factory=list, description="Annotation text lines")
    style_key: AnnotationStyleKey = Field(..., description="Frontend annotation style key")
    related_segment: Optional[TrackSegmentName] = Field(default=None)


class TrackSegment(BaseModel):
    """Track segment representation."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: TrackSegmentName = Field(..., description="Segment name")
    name_cn: str = Field(..., description="Chinese segment name")
    start_point: Coordinate = Field(..., description="Start coordinate")
    end_point: Coordinate = Field(..., description="End coordinate")
    path_points: Optional[List[Coordinate]] = Field(
        default=None,
        description="Arc path points for turn segments",
    )
    distance: float = Field(..., description="Segment distance in meters", ge=0)
    heading: float = Field(..., description="Segment heading in degrees", ge=0, le=360)
    altitude: float = Field(..., description="End altitude in meters", ge=0)
    vertical_angle: float = Field(
        default=0.0,
        description="Segment climb/descent angle in degrees; positive means climb",
        ge=-90,
        le=90,
    )


class TrackConfig(BaseModel):
    """Track configuration for visual traffic pattern calculation."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    circuit_height: int = Field(default=300, ge=100, le=1000)
    bank_angle: int = Field(default=15, ge=5, le=30)
    active_runway_end: ActiveRunwayEnd = Field(default="primary")
    traffic_pattern_side: TrafficPatternSide = Field(default="left")
    departure_leg_length: Optional[float] = Field(default=None, ge=500, le=10000)
    final_leg_length: Optional[float] = Field(default=None, ge=500, le=10000)
    turn_radius: Optional[float] = Field(default=None, ge=100, le=5000)
    downwind_offset: Optional[float] = Field(default=None, ge=500, le=10000)
    wind_correction: bool = Field(default=False)
    wind_direction: Optional[int] = Field(default=None, ge=0, le=360)
    wind_speed: Optional[int] = Field(default=None, ge=0, le=100)
    magnetic_variation: float = Field(default=0.0)
    bidirectional: bool = Field(default=False, description="Compute OLS surfaces for both runway directions")
    visual_pattern: Optional[VisualPatternConfig] = Field(default=None)
    obstacle_surfaces: Optional[ObstacleSurfaceConfig] = Field(default=None)
    flight_camp_airspace: Optional[FlightCampAirspaceConfig] = Field(default=None)


GeometryParameterSource = Literal["auto", "custom"]


class GeometryParameterPreview(BaseModel):
    """Resolved geometry parameter and whether it came from automatic rules or user input."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    value: float = Field(..., description="Resolved value in meters")
    automatic_value: float = Field(..., description="Automatic rule-based value in meters")
    source: GeometryParameterSource = Field(..., description="auto or custom")


class GeometryPreviewResponse(BaseModel):
    """Resolved visual traffic pattern geometry parameters."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    departure_leg_length: GeometryParameterPreview
    final_leg_length: GeometryParameterPreview
    turn_radius: GeometryParameterPreview
    downwind_offset: GeometryParameterPreview


class ParameterPreviewItem(BaseModel):
    """Resolved optional parameter with regulation help text."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    value: float | str | bool = Field(..., description="Resolved value")
    automatic_value: float | str | bool = Field(..., description="Automatic/default value")
    source: GeometryParameterSource = Field(..., description="auto or custom")
    unit: str = Field(default="")
    source_code: str = Field(default="")
    clause: str = Field(default="")
    description: str = Field(default="")


class ParameterPreviewResponse(BaseModel):
    """Resolved visual pattern, OLS, and flight camp airspace parameters."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    visual_pattern: Dict[str, ParameterPreviewItem]
    obstacle_surfaces: Dict[str, ParameterPreviewItem]
    flight_camp_airspace: Dict[str, ParameterPreviewItem]


class TrackValidationError(BaseModel):
    """Validation error for track calculation."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    segment: Optional[TrackSegmentName] = Field(default=None)
    severity: Literal["error", "warning"] = Field(default="error")


class ValidationReport(BaseModel):
    """Validation report."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    is_valid: bool = Field(..., description="Whether the track is valid")
    errors: List[TrackValidationError] = Field(default_factory=list)
    warnings: List[TrackValidationError] = Field(default_factory=list)


class TrackResult(BaseModel):
    """Track calculation result."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    segments: List[TrackSegment] = Field(default_factory=list)
    key_points: List[GeometryOverlay] = Field(default_factory=list)
    surfaces: List[GeometryOverlay] = Field(default_factory=list)
    airspaces: List[GeometryOverlay] = Field(default_factory=list)
    annotations: List[ProcedureAnnotation] = Field(default_factory=list)
    compliance: List[ComplianceItem] = Field(default_factory=list)
    total_distance: float = Field(default=0, ge=0)
    estimated_time: float = Field(default=0, ge=0)
    validation_report: ValidationReport = Field(...)


class TrackRequest(BaseModel):
    """Track calculation request."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    runway: RunwayParams = Field(..., description="Runway parameters")
    aircraft_id: str = Field(..., description="Aircraft ID")
    config: TrackConfig = Field(..., description="Track configuration")


class GeometryPreviewRequest(BaseModel):
    """Geometry preview request for automatic/custom visual pattern parameters."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    aircraft_id: str = Field(..., description="Aircraft ID")
    config: TrackConfig = Field(..., description="Track configuration")


class CoordinateTransformRequest(BaseModel):
    """Coordinate transform request."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    coordinate: Coordinate = Field(..., description="Source coordinate")
    from_system: Literal["WGS84", "GCJ02"] = Field(..., description="Source system")
    to_system: Literal["WGS84", "GCJ02"] = Field(..., description="Target system")


class CoordinateTransformResponse(BaseModel):
    """Coordinate transform response."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    coordinate: Coordinate = Field(..., description="Transformed coordinate")
    original_system: Literal["WGS84", "GCJ02"] = Field(..., description="Source system")
    target_system: Literal["WGS84", "GCJ02"] = Field(..., description="Target system")
