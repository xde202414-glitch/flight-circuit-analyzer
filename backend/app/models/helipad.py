"""Helipad / FATO analysis Pydantic models.

Ports the visual surface parameter calculations from the
MAP HELI260522 WeChat Mini Program.
"""
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Literal, Optional

from app.models.runway import Coordinate


def to_camel(string: str) -> str:
    """Convert snake_case to camelCase."""
    components = string.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


# ---------------------------------------------------------------------------
# Visual FATO obstacle limitation surface table (目视条件下 FATO 障碍物限制面)
# Ported from MAP HELI260522 pages/index/index.js VISUAL_SURFACE_TABLE
# ---------------------------------------------------------------------------

class VisualSurfaceSegment(BaseModel):
    """A single segment of a visual approach/takeoff surface."""
    length: float = Field(..., description="Segment length in meters")
    slope: float = Field(..., description="Segment slope as ratio (e.g. 0.045 = 4.5%)")


class VisualSurfaceRule(BaseModel):
    """Visual surface parameters for a slope type (A/B/C)."""
    label: Literal["A", "B", "C"]
    total_length: float = Field(..., alias="totalLength", description="Total surface length in meters")
    segments: List[VisualSurfaceSegment] = Field(..., description="Ordered segments from inner edge outward")

    model_config = ConfigDict(populate_by_name=True)


# Built-in visual surface rules matching MAP HELI260522
VISUAL_SURFACE_RULES: dict[str, VisualSurfaceRule] = {
    "A": VisualSurfaceRule(
        label="A",
        totalLength=3386,
        segments=[VisualSurfaceSegment(length=3386, slope=0.045)],
    ),
    "B": VisualSurfaceRule(
        label="B",
        totalLength=1075,
        segments=[
            VisualSurfaceSegment(length=245, slope=0.08),
            VisualSurfaceSegment(length=830, slope=0.16),
        ],
    ),
    "C": VisualSurfaceRule(
        label="C",
        totalLength=1220,
        segments=[VisualSurfaceSegment(length=1220, slope=0.125)],
    ),
}

SAFETY_AREA_WIDTH_M = 3.0  # metres – safety margin around FATO


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class FATOConfig(BaseModel):
    """FATO (Final Approach and Take-Off area) configuration."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    shape: Literal["circle", "square"] = Field(
        default="circle",
        description="FATO shape — 圆形 or 正方形",
    )
    diameter: float = Field(
        ...,
        gt=0,
        description="FATO diameter (or side length for square) in metres",
    )
    rotor_diameter: float = Field(
        ...,
        gt=0,
        alias="rotorDiameter",
        description="Rotor diameter RD in metres – used for outer width (7RD / 10RD)",
    )
    elevation: float = Field(
        ...,
        description="FATO elevation / altitude in metres",
    )
    flight_direction: float = Field(
        ...,
        ge=0,
        le=360,
        alias="flightDirection",
        description="Approach surface horizontal direction in degrees (0-360)",
    )
    takeoff_direction: Optional[float] = Field(
        default=None,
        alias="takeoffDirection",
        ge=0,
        le=360,
        description="Takeoff surface horizontal direction. Defaults to flightDirection + 180 if not set.",
    )
    slope_type: Literal["A", "B", "C"] = Field(
        default="A",
        alias="slopeType",
        description="Visual surface slope type (A/B/C). Overridden by approachSlope or takeoffSlope if set.",
    )
    approach_slope: Optional[float] = Field(
        default=None,
        alias="approachSlope",
        ge=1.0,
        le=30.0,
        description="Custom approach surface slope angle in degrees (1-30). Overrides slopeType.",
    )
    takeoff_slope: Optional[float] = Field(
        default=None,
        alias="takeoffSlope",
        ge=1.0,
        le=30.0,
        description="Custom takeoff surface slope angle in degrees (1-30). Overrides slopeType.",
    )
    operation_mode: Literal["day", "night"] = Field(
        default="day",
        alias="operationMode",
        description="Operation mode – day (散开率 10%) or night (散开率 15%)",
    )


class HelipadCalculateRequest(BaseModel):
    """Request body for helipad surface calculation."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    center: Coordinate = Field(
        ...,
        description="FATO centre coordinate (WGS84)",
    )
    config: FATOConfig = Field(
        ...,
        description="FATO configuration parameters",
    )


class FATORegion(BaseModel):
    """Calculated FATO region geometry."""
    center: Coordinate
    shape: Literal["circle", "square"]
    direction: float = Field(..., description="Flight direction for square orientation")
    diameter: float
    radius: float
    safety_size: float = Field(..., alias="safetySize", description="Diameter + 2×safety width")
    safety_radius: float = Field(..., alias="safetyRadius", description="safetySize / 2")
    safety_width: float = Field(default=3.0, alias="safetyWidth")

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SurfaceStation(BaseModel):
    """A station point along an approach/takeoff surface."""
    distance: float = Field(..., description="Distance from inner edge in metres")
    width: float = Field(..., description="Width at this distance in metres")
    height: float = Field(..., description="Relative control height above FATO elevation")


class VisualSurfaceResult(BaseModel):
    """Visual surface calculation result."""
    slope_type: Literal["A", "B", "C"] = Field(..., alias="slopeType")
    slope_label: str = Field(..., alias="slopeLabel")
    operation_mode: Literal["day", "night"] = Field(..., alias="operationMode")
    divergence: float = Field(..., description="Divergence ratio (0.10 day / 0.15 night)")
    inner_width: float = Field(..., alias="innerWidth", description="Inner edge width (diameter + 2×safety)")
    outer_width: float = Field(..., alias="outerWidth", description="Outer edge width = max(innerWidth, 7or10×RD)")
    outer_width_multiplier: int = Field(..., alias="outerWidthMultiplier", description="7 (day) or 10 (night)")
    rotor_diameter: float = Field(..., alias="rotorDiameter")
    max_height: float = Field(default=152, alias="maxHeight")
    total_length: float = Field(..., alias="totalLength")
    segments: List[VisualSurfaceSegment] = Field(...)
    stations: List[SurfaceStation] = Field(default_factory=list)
    transition_surface: dict = Field(
        default_factory=lambda: {"slope": 0.5, "height": 45},
        alias="transitionSurface",
    )

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class HelipadCalculateResponse(BaseModel):
    """Response for helipad surface calculation."""
    fato_region: FATORegion = Field(..., alias="fatoRegion")
    surface_params: Optional[VisualSurfaceResult] = Field(
        default=None, alias="surfaceParams",
        description="Shared surface params (legacy). Use approachSurfaceParams / takeoffSurfaceParams.",
    )
    approach_surface_params: Optional[VisualSurfaceResult] = Field(
        default=None, alias="approachSurfaceParams",
        description="Approach surface parameters (may differ from takeoff when custom angles used)",
    )
    takeoff_surface_params: Optional[VisualSurfaceResult] = Field(
        default=None, alias="takeoffSurfaceParams",
        description="Takeoff surface parameters (may differ from approach when custom angles used)",
    )
    approach_polygon: List[Coordinate] = Field(..., alias="approachPolygon")
    takeoff_polygon: List[Coordinate] = Field(..., alias="takeoffPolygon")
    fato_polygon: List[Coordinate] = Field(default_factory=list, alias="fatoPolygon")
    fato_circles: List[dict] = Field(default_factory=list, alias="fatoCircles")

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------------------
# Building search
# ---------------------------------------------------------------------------

class PolygonRegion(BaseModel):
    """A named polygon region for building search."""
    name: str = Field(..., description="Region name (e.g. FATO, 进近面)")
    points: List[Coordinate] = Field(..., description="Ordered polygon vertices")


class BuildingSearchRequest(BaseModel):
    """Request for building search within analysis regions."""
    polygons: List[PolygonRegion] = Field(..., description="Search regions")
    mode: Literal["fast", "full"] = Field(default="fast")
    keywords: Optional[List[str]] = Field(default=None)
    page_size: int = Field(default=10, alias="pageSize", ge=5, le=50)

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class BuildingResult(BaseModel):
    """A single building / POI search result."""
    id: str = Field(..., description="Unique building identifier")
    name: str = Field(..., description="Building / POI name")
    category: str = Field(default="", description="Building category")
    address: str = Field(default="")
    latitude: float
    longitude: float
    source: str = Field(default="", description="Data source: overpass / tencent-map")
    height: Optional[float] = Field(default=None, description="Building height in metres")
    levels: Optional[int] = Field(default=None, description="Number of storeys")
    boundary: Optional[List[Coordinate]] = Field(default=None, description="Building footprint polygon")

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class BuildingSearchResponse(BaseModel):
    """Response for building search."""
    places: List[BuildingResult] = Field(default_factory=list)
    source: str = Field(default="")
    searched_regions: List[str] = Field(default_factory=list, alias="searchedRegions")
    warnings: List[str] = Field(default_factory=list)

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------------------
# Elevation / terrain analysis
# ---------------------------------------------------------------------------

class ElevationPointRequest(BaseModel):
    """Single-point elevation query."""
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class ElevationSamplePoint(BaseModel):
    """A sample point for terrain analysis."""
    latitude: float
    longitude: float
    surface_name: str = Field(default="", alias="surfaceName")
    distance: float = Field(default=0, description="Distance from inner edge")
    control_elevation: float = Field(..., alias="controlElevation", description="Allowed max elevation")


class TerrainAnalysisRequest(BaseModel):
    """Request for terrain elevation analysis along surfaces."""
    fato_center: Coordinate = Field(..., alias="fatoCenter")
    fato_elevation: float = Field(..., alias="fatoElevation")
    surface_params: VisualSurfaceResult = Field(..., alias="surfaceParams")
    fato_region: FATORegion = Field(..., alias="fatoRegion")
    flight_direction: float = Field(..., alias="flightDirection")

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TerrainExceedance(BaseModel):
    """A terrain point that exceeds control elevation."""
    latitude: float
    longitude: float
    surface_name: str = Field(..., alias="surfaceName")
    ground_elevation: float = Field(..., alias="groundElevation")
    control_elevation: float = Field(..., alias="controlElevation")
    exceedance: float = Field(..., description="ground - control (positive = exceeded)")
    cell_points: List[Coordinate] = Field(default_factory=list, alias="cellPoints")

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TerrainAnalysisResponse(BaseModel):
    """Response for terrain elevation analysis."""
    sample_count: int = Field(..., alias="sampleCount")
    exceeded: List[TerrainExceedance] = Field(default_factory=list)
    failed_count: int = Field(default=0, alias="failedCount")
    message: str = Field(default="")

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
