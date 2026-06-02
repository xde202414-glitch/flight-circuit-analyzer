"""Visual FATO surface calculation engine.

Ported from MAP HELI260522 WeChat Mini Program
(pages/index/index.js) to Python, reusing the existing
CoordinateTransformer from app.core.coordinate.

Supports:
- FATO region geometry (circle / oriented square)
- Visual approach/takeoff surface polygon generation
- Custom slope angles per surface (approach / takeoff)
- Terrain analysis sample-point generation
"""
import math
from typing import List, Optional, Tuple

from app.core.coordinate import transformer as _transformer
from app.models.helipad import (
    FATOConfig,
    FATORegion,
    HelipadCalculateRequest,
    HelipadCalculateResponse,
    SAFETY_AREA_WIDTH_M,
    SurfaceStation,
    VISUAL_SURFACE_RULES,
    VisualSurfaceResult,
    VisualSurfaceRule,
    VisualSurfaceSegment,
)
from app.models.runway import Coordinate

DEFAULT_ARC_POINTS = 24
TERRAIN_ANALYSIS_ALONG_STEPS = 6
TERRAIN_ANALYSIS_ACROSS_FACTORS = [-0.4, -0.2, 0.0, 0.2, 0.4]
TERRAIN_ANALYSIS_MIN_CELL_SIZE = 2.0


def _normalize_direction(value: float) -> float:
    """Normalise a bearing to [0, 360)."""
    return value % 360


def _calculate_offset_point(
    lat: float, lon: float, bearing: float, distance: float
) -> Tuple[float, float]:
    """Calculate a new coordinate given a start point, bearing and distance."""
    coord = _transformer.destination_point(
        Coordinate(latitude=lat, longitude=lon), bearing, distance
    )
    return coord.latitude, coord.longitude


def _build_circle_polygon(
    center_lat: float, center_lon: float, radius: float, count: int = DEFAULT_ARC_POINTS
) -> List[Coordinate]:
    """Build a circle approximation polygon."""
    points: List[Coordinate] = []
    for i in range(count):
        bearing = i * 360.0 / count
        lat, lon = _calculate_offset_point(center_lat, center_lon, bearing, radius)
        points.append(Coordinate(latitude=round(lat, 6), longitude=round(lon, 6)))
    return points


def _create_oriented_square(
    center_lat: float, center_lon: float, side_length: float, direction: float
) -> List[Coordinate]:
    """Create an oriented square centred on (lat, lon), aligned to *direction*."""
    half = side_length / 2.0
    forward = _normalize_direction(direction)
    right = _normalize_direction(direction + 90)
    back = _normalize_direction(direction + 180)
    left = _normalize_direction(direction - 90)

    # centres of the four edges
    fc_lat, fc_lon = _calculate_offset_point(center_lat, center_lon, forward, half)
    rc_lat, rc_lon = _calculate_offset_point(center_lat, center_lon, right, half)
    bc_lat, bc_lon = _calculate_offset_point(center_lat, center_lon, back, half)
    lc_lat, lc_lon = _calculate_offset_point(center_lat, center_lon, left, half)

    # corners
    fl_lat, fl_lon = _calculate_offset_point(fc_lat, fc_lon, left, half)
    fr_lat, fr_lon = _calculate_offset_point(fc_lat, fc_lon, right, half)
    br_lat, br_lon = _calculate_offset_point(bc_lat, bc_lon, right, half)
    bl_lat, bl_lon = _calculate_offset_point(bc_lat, bc_lon, left, half)

    return [
        Coordinate(latitude=round(fl_lat, 6), longitude=round(fl_lon, 6)),
        Coordinate(latitude=round(fr_lat, 6), longitude=round(fr_lon, 6)),
        Coordinate(latitude=round(br_lat, 6), longitude=round(br_lon, 6)),
        Coordinate(latitude=round(bl_lat, 6), longitude=round(bl_lon, 6)),
    ]


class HelipadCalculator:
    """Calculator for helipad/FATO visual surfaces."""

    def __init__(self):
        self.transformer = _transformer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(self, request: HelipadCalculateRequest) -> HelipadCalculateResponse:
        """Calculate FATO region and approach/takeoff surface polygons."""
        config = request.config
        center = request.center

        fato_region = self._calculate_fato_region(center, config)

        # Compute surface params — separate for approach and takeoff when custom angles set
        approach_params = self._calculate_visual_surface_params(
            config, angle_override=config.approach_slope
        )
        takeoff_params = self._calculate_visual_surface_params(
            config, angle_override=config.takeoff_slope
        )

        # Takeoff direction: use explicit value, or default to approach + 180°
        takeoff_dir = (
            config.takeoff_direction
            if config.takeoff_direction is not None
            else (config.flight_direction + 180) % 360
        )

        approach_polygon = self._calculate_surface_polygon(
            fato_region, approach_params, config.flight_direction
        )
        takeoff_polygon = self._calculate_surface_polygon(
            fato_region, takeoff_params, takeoff_dir
        )

        # Build FATO display polygons / circles
        fato_polygon: List[Coordinate] = []
        fato_circles: List[dict] = []
        if config.shape == "circle":
            fato_circles = [
                {
                    "latitude": center.latitude,
                    "longitude": center.longitude,
                    "radius": fato_region.radius,
                },
                {
                    "latitude": center.latitude,
                    "longitude": center.longitude,
                    "radius": fato_region.safety_radius,
                },
            ]
        else:
            fato_polygon = _create_oriented_square(
                center.latitude, center.longitude,
                config.diameter, config.flight_direction,
            )

        # Legacy surfaceParams for backward compatibility (uses approach)
        legacy_params = approach_params

        return HelipadCalculateResponse(
            fatoRegion=fato_region,
            surfaceParams=legacy_params,
            approachSurfaceParams=approach_params,
            takeoffSurfaceParams=takeoff_params,
            approachPolygon=approach_polygon,
            takeoffPolygon=takeoff_polygon,
            fatoPolygon=fato_polygon,
            fatoCircles=fato_circles,
        )

    # ------------------------------------------------------------------
    # FATO region
    # ------------------------------------------------------------------

    def _calculate_fato_region(self, center: Coordinate, config: FATOConfig) -> FATORegion:
        safety_size = config.diameter + 2 * SAFETY_AREA_WIDTH_M
        return FATORegion(
            center=center,
            shape=config.shape,
            direction=config.flight_direction,
            diameter=config.diameter,
            radius=config.diameter / 2.0,
            safetySize=safety_size,
            safetyRadius=safety_size / 2.0,
            safetyWidth=SAFETY_AREA_WIDTH_M,
        )

    # ------------------------------------------------------------------
    # Visual surface parameters
    # ------------------------------------------------------------------

    def _make_surface_rule_from_angle(self, angle_deg: float) -> VisualSurfaceRule:
        """Create a single-segment surface rule from a slope angle in degrees.

        Converts the angle to a slope ratio (tan), then builds a single segment
        extending to ~152 m above FATO (standard visual surface ceiling).
        """
        slope = math.tan(math.radians(angle_deg))
        length = 152.0 / slope  # reach ~152m at the given angle
        total = round(length, 1)
        return VisualSurfaceRule(
            label=f"{angle_deg:.1f}°",
            totalLength=total,
            segments=[VisualSurfaceSegment(length=total, slope=round(slope, 6))],
        )

    def _calculate_visual_surface_params(
        self, config: FATOConfig, angle_override: Optional[float] = None
    ) -> VisualSurfaceResult:
        """Resolve visual surface parameters.

        If *angle_override* is provided (in degrees), creates a custom single-segment
        rule at that angle. Otherwise falls back to the configured slope_type (A/B/C).
        """
        if angle_override is not None:
            rule = self._make_surface_rule_from_angle(angle_override)
            slope_label = f"自定义 {angle_override:.1f}°"
        else:
            rule = VISUAL_SURFACE_RULES[config.slope_type]
            slope_label = config.slope_type

        divergence = 0.10 if config.operation_mode == "day" else 0.15
        outer_multiplier = 7 if config.operation_mode == "day" else 10

        inner_width = config.diameter + 2 * SAFETY_AREA_WIDTH_M
        target_outer = outer_multiplier * config.rotor_diameter
        outer_width = max(inner_width, target_outer)

        # Build stations
        stations = self._calculate_surface_stations(rule, inner_width, outer_width, divergence)

        # Compute max height
        max_height = 0.0
        for seg in rule.segments:
            max_height += seg.length * seg.slope

        return VisualSurfaceResult(
            slopeType=config.slope_type,
            slopeLabel=slope_label,
            operationMode=config.operation_mode,
            divergence=divergence,
            innerWidth=inner_width,
            outerWidth=outer_width,
            outerWidthMultiplier=outer_multiplier,
            rotorDiameter=config.rotor_diameter,
            maxHeight=round(max_height, 2),
            totalLength=rule.total_length,
            segments=rule.segments,
            stations=stations,
        )

    # ------------------------------------------------------------------
    # Surface stations
    # ------------------------------------------------------------------

    def _calculate_surface_stations(
        self,
        rule,
        inner_width: float,
        outer_width: float,
        divergence: float,
    ) -> List[SurfaceStation]:
        """Build station list (distance → width → height) along the surface."""
        stations: List[SurfaceStation] = [SurfaceStation(distance=0, width=inner_width, height=0)]
        distance = 0.0
        height = 0.0
        cap_inserted = False
        cap_distance = (
            (outer_width - inner_width) / (2 * divergence) if divergence > 0 else float("inf")
        )

        for seg in rule.segments:
            seg_start = distance
            seg_end = distance + seg.length

            # Insert the cap station where the diverged width hits outer_width
            if not cap_inserted and seg_start < cap_distance < seg_end:
                cap_seg_dist = cap_distance - seg_start
                stations.append(
                    SurfaceStation(
                        distance=cap_distance,
                        width=outer_width,
                        height=height + cap_seg_dist * seg.slope,
                    )
                )
                cap_inserted = True

            distance = seg_end
            height += seg.length * seg.slope
            width_at_end = self._get_surface_width(distance, inner_width, outer_width, divergence)
            stations.append(
                SurfaceStation(distance=distance, width=width_at_end, height=height)
            )

        return stations

    def _get_surface_width(self, distance: float, inner_width: float, outer_width: float, divergence: float) -> float:
        diverged = inner_width + 2 * distance * divergence
        return min(outer_width, diverged)

    # ------------------------------------------------------------------
    # Surface polygon
    # ------------------------------------------------------------------

    def _calculate_surface_polygon(
        self,
        fato_region: FATORegion,
        surface_params: VisualSurfaceResult,
        direction: float,
    ) -> List[Coordinate]:
        """Generate the polygon (left-edge + reversed right-edge) for a surface."""
        direction = _normalize_direction(direction)

        # The inner edge starts at the FATO safety boundary in the given direction
        start_lat, start_lon = _calculate_offset_point(
            fato_region.center.latitude,
            fato_region.center.longitude,
            direction,
            fato_region.safety_radius,
        )

        left_points: List[Coordinate] = []
        right_points: List[Coordinate] = []

        for station in surface_params.stations:
            left = self._surface_edge_point(
                start_lat, start_lon, direction,
                station.distance, station.width, side=-1,
            )
            right = self._surface_edge_point(
                start_lat, start_lon, direction,
                station.distance, station.width, side=1,
            )
            left_points.append(left)
            right_points.append(right)

        # Polygon = left edge → reversed right edge
        return left_points + list(reversed(right_points))

    def _surface_edge_point(
        self,
        start_lat: float,
        start_lon: float,
        direction: float,
        distance: float,
        width: float,
        side: int,
    ) -> Coordinate:
        """Calculate a single edge point.
        side=-1 → left edge, side=+1 → right edge.
        """
        # Move *distance* metres in the surface direction
        clat, clon = _calculate_offset_point(start_lat, start_lon, direction, distance)
        # Move *width/2* metres perpendicular
        perp = _normalize_direction(direction + side * 90)
        elat, elon = _calculate_offset_point(clat, clon, perp, width / 2.0)
        return Coordinate(latitude=round(elat, 6), longitude=round(elon, 6))

    # ------------------------------------------------------------------
    # Terrain sample-point generation
    # ------------------------------------------------------------------

    def build_terrain_analysis_samples(
        self,
        fato_region: FATORegion,
        surface_params: VisualSurfaceResult,
        flight_direction: float,
        fato_elevation: float,
    ) -> List[dict]:
        """Generate sample points for terrain-vs-control-height analysis.

        Returns a list of dicts with keys: latitude, longitude,
        surfaceName, distance, width, direction, controlElevation, cellPoints.
        """
        directions = [
            {"name": "进近面", "direction": flight_direction},
            {"name": "起飞爬升面", "direction": flight_direction + 180},
        ]
        samples: List[dict] = []
        total_length = surface_params.total_length
        along_step = total_length / (TERRAIN_ANALYSIS_ALONG_STEPS + 1)
        cell_along_half = along_step * 0.45

        for item in directions:
            direction = _normalize_direction(item["direction"])
            start_lat, start_lon = _calculate_offset_point(
                fato_region.center.latitude,
                fato_region.center.longitude,
                direction,
                fato_region.safety_radius,
            )

            for step in range(1, TERRAIN_ANALYSIS_ALONG_STEPS + 1):
                distance = along_step * step
                width = self._get_surface_width(
                    distance,
                    surface_params.inner_width,
                    surface_params.outer_width,
                    surface_params.divergence,
                )
                clat, clon = _calculate_offset_point(start_lat, start_lon, direction, distance)
                relative_height = self._get_surface_height_at_distance(surface_params, distance)
                control_elevation = fato_elevation + relative_height
                cell_across_half = max(width * 0.1, TERRAIN_ANALYSIS_MIN_CELL_SIZE / 2)

                for factor in TERRAIN_ANALYSIS_ACROSS_FACTORS:
                    plat, plon = _calculate_offset_point(
                        clat, clon, direction + 90, width * factor
                    )
                    cell = self._build_sample_cell(
                        plat, plon, direction, cell_along_half, cell_across_half
                    )
                    samples.append({
                        "latitude": plat,
                        "longitude": plon,
                        "surfaceName": item["name"],
                        "distance": distance,
                        "width": width,
                        "direction": direction,
                        "controlElevation": round(control_elevation, 2),
                        "cellPoints": cell,
                    })

        return samples

    def _get_surface_height_at_distance(
        self, surface_params: VisualSurfaceResult, distance: float
    ) -> float:
        """Calculate the relative control height at a given distance."""
        remaining = distance
        height = 0.0
        for seg in surface_params.segments:
            seg_dist = min(remaining, seg.length)
            height += seg_dist * seg.slope
            remaining -= seg_dist
            if remaining <= 0:
                break
        return height

    def _build_sample_cell(
        self, center_lat: float, center_lon: float,
        direction: float, along_half: float, across_half: float,
    ) -> List[Coordinate]:
        """Build a small rectangle (cell) around a sample point."""
        offsets = [
            (-along_half, -across_half),
            (along_half, -across_half),
            (along_half, across_half),
            (-along_half, across_half),
        ]
        points: List[Coordinate] = []
        for al, ac in offsets:
            clat, clon = _calculate_offset_point(center_lat, center_lon, direction, al)
            plat, plon = _calculate_offset_point(clat, clon, direction + 90, ac)
            points.append(Coordinate(latitude=round(plat, 6), longitude=round(plon, 6)))
        return points


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

helipad_calculator = HelipadCalculator()
