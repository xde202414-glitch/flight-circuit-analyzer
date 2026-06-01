"""Visual flight procedure calculation engine."""
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.coordinate import transformer
from app.core.validator import ComplianceValidator
from app.models.aircraft import Aircraft
from app.models.runway import Coordinate, RunwayParams
from app.models.track import (
    GeometryOverlay,
    GeometryParameterPreview,
    GeometryPreviewResponse,
    ComplianceItem,
    FlightCampAirspaceConfig,
    ObstacleSurfaceConfig,
    ParameterPreviewItem,
    ParameterPreviewResponse,
    ProcedureAnnotation,
    TrackConfig,
    TrackResult,
    TrackSegment,
    TrackSegmentName,
    TrackValidationError,
    ValidationReport,
)

LocalPoint = Tuple[float, float]


class TrackCalculator:
    """AC-97-FS-005R1-oriented visual traffic pattern calculator."""

    SEGMENT_NAMES: Dict[TrackSegmentName, str] = {
        "departure": "起飞航段",
        "turn_1": "一转弯",
        "crosswind_leg": "二边",
        "turn_2": "二转弯",
        "downwind_leg": "三边",
        "turn_3": "三转弯",
        "base_leg": "四边",
        "turn_4": "四转弯",
        "final_approach": "五边",
    }
    LEG_LABELS: Dict[TrackSegmentName, str] = {
        "departure": "一边",
        "crosswind_leg": "二边",
        "downwind_leg": "三边",
        "base_leg": "四边",
        "final_approach": "五边",
    }

    def __init__(self):
        self.transformer = transformer
        self.validator = ComplianceValidator()
        self._load_regulations()

    def _load_regulations(self) -> None:
        data_dir = Path(__file__).parent.parent / "data"
        legacy = self._load_json_file(data_dir / "regulations.json", {})
        visual_rules = self._load_json_file(data_dir / "visual_procedure_rules.json", legacy)
        obstacle_rules = self._load_json_file(data_dir / "obstacle_limitation_surfaces.json", {})
        flight_camp_rules = self._load_json_file(data_dir / "flight_camp_airspace_rules.json", {})

        self.regulations = {**legacy, **visual_rules}
        self.obstacle_rules = obstacle_rules
        self.flight_camp_rules = flight_camp_rules

    def _load_json_file(self, path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return fallback

    def _rule_value(self, rule: Any, default: Any = None) -> Any:
        if isinstance(rule, dict) and "defaultValue" in rule:
            return rule["defaultValue"]
        return default if rule is None else rule

    def calculate_turn_radius(self, speed_km_h: float, bank_angle_deg: float) -> float:
        """Calculate coordinated turn radius from speed and bank angle."""
        speed_m_s = speed_km_h * 1000 / 3600
        bank_angle_rad = math.radians(bank_angle_deg)
        radius = (speed_m_s**2) / (9.81 * math.tan(bank_angle_rad))
        return round(radius, 1)

    def _effective_visual_config(self, aircraft: Aircraft, config: TrackConfig) -> TrackConfig:
        """Apply nested visual pattern overrides while preserving old flat fields."""
        visual = config.visual_pattern
        if not visual:
            return config

        updates: Dict[str, Any] = {}
        if visual.standard_circuit_height is not None:
            updates["circuit_height"] = int(round(visual.standard_circuit_height))
        return config.model_copy(update=updates) if updates else config

    def calculate_circuit(
        self,
        runway: RunwayParams,
        aircraft: Aircraft,
        config: TrackConfig,
    ) -> TrackResult:
        """Calculate a visual traffic pattern and related map overlays."""
        errors = self._validate_required_mapping(aircraft)
        if errors:
            return TrackResult(
                segments=[],
                key_points=[],
                surfaces=[],
                airspaces=[],
                annotations=[],
                compliance=[],
                total_distance=0,
                estimated_time=0,
                validation_report=ValidationReport(
                    is_valid=False,
                    errors=errors,
                    warnings=[],
                ),
            )

        config = self._effective_visual_config(aircraft, config)

        departure_heading = self._departure_heading(runway, config)
        threshold = self._active_threshold(runway, departure_heading)
        side = -1 if config.traffic_pattern_side == "left" else 1

        visual_rules = self.regulations["visual_procedure"]
        geometry = self.resolve_geometry_parameters(aircraft, config)
        turn_radius = geometry.turn_radius.value
        downwind_offset = geometry.downwind_offset.value
        departure_distance = geometry.departure_leg_length.value
        final_distance = geometry.final_leg_length.value
        arc_points_count = int(self._rule_value(visual_rules.get("arc_points"), 24))

        local_segments = self._build_local_pattern(
            side=side,
            turn_radius=turn_radius,
            departure_distance=departure_distance,
            final_distance=final_distance,
            downwind_offset=downwind_offset,
            arc_points_count=arc_points_count,
        )

        segments = self._to_track_segments(
            local_segments=local_segments,
            origin=threshold,
            departure_heading=departure_heading,
            runway=runway,
            aircraft=aircraft,
            config=config,
        )
        key_points = self._build_key_points(
            segments=segments,
            threshold=threshold,
            runway=runway,
            config=config,
        )
        surfaces = self._build_obstacle_surfaces(
            origin=threshold,
            departure_heading=departure_heading,
            runway=runway,
            config=config,
        )

        if config.bidirectional:
            reciprocal_end = "reciprocal" if config.active_runway_end == "primary" else "primary"
            reciprocal_config = config.model_copy(update={"active_runway_end": reciprocal_end})
            reciprocal_heading = self._departure_heading(runway, reciprocal_config)
            reciprocal_threshold = self._active_threshold(runway, reciprocal_heading)
            reciprocal_surfaces = self._build_obstacle_surfaces(
                origin=reciprocal_threshold,
                departure_heading=reciprocal_heading,
                runway=runway,
                config=reciprocal_config,
            )
            surfaces = self._merge_bidirectional_surfaces(surfaces, reciprocal_surfaces)

        airspaces = self._build_flight_camp_airspaces(runway, aircraft, config)
        compliance = self._build_compliance(
            runway=runway,
            aircraft=aircraft,
            config=config,
            geometry=geometry,
            surfaces=surfaces,
            airspaces=airspaces,
        )
        annotations = self._build_annotations(
            segments=segments,
            key_points=key_points,
            runway=runway,
            aircraft=aircraft,
            config=config,
            geometry=geometry,
        )

        total_distance = sum(segment.distance for segment in segments)
        avg_speed = (min(aircraft.cruise_speed, aircraft.vfr_max_ias_kmh) + aircraft.approach_speed) / 2
        estimated_time = total_distance / (avg_speed * 1000 / 3600)

        draft = TrackResult(
            segments=segments,
            key_points=key_points,
            surfaces=surfaces,
            airspaces=airspaces,
            annotations=annotations,
            compliance=compliance,
            total_distance=round(total_distance, 1),
            estimated_time=round(estimated_time, 1),
            validation_report=ValidationReport(is_valid=True, errors=[], warnings=[]),
        )
        validation_report = self.validator.validate(draft, runway, aircraft, config)

        return TrackResult(
            segments=segments,
            key_points=key_points,
            surfaces=surfaces,
            airspaces=airspaces,
            annotations=annotations,
            compliance=compliance,
            total_distance=round(total_distance, 1),
            estimated_time=round(estimated_time, 1),
            validation_report=validation_report,
        )

    def resolve_geometry_parameters(
        self,
        aircraft: Aircraft,
        config: TrackConfig,
    ) -> GeometryPreviewResponse:
        """Resolve automatic/custom visual traffic pattern geometry parameters."""
        class_rules = self.regulations["vfr_pattern_classes"][aircraft.vfr_pattern_class]
        visual_rules = self.regulations["visual_procedure"]

        calculated_turn_radius = max(
            float(aircraft.turn_radius),
            self.calculate_turn_radius(aircraft.approach_speed, config.bank_angle),
        )
        turn_radius = self._geometry_preview_value(config.turn_radius, calculated_turn_radius)

        minimum_straight_leg = float(self._rule_value(visual_rules.get("minimum_straight_leg_m"), 500))
        automatic_downwind_offset = max(
            float(self._rule_value(class_rules.get("downwind_offset_m"), 2500)),
            2 * turn_radius.value + minimum_straight_leg,
        )
        automatic_departure_distance = max(
            float(self._rule_value(class_rules.get("departure_distance_m"), 2000)),
            turn_radius.value + minimum_straight_leg,
        )
        automatic_final_distance = max(
            float(self._rule_value(class_rules.get("final_distance_m"), 2600)),
            turn_radius.value + minimum_straight_leg,
        )

        return GeometryPreviewResponse(
            departure_leg_length=self._geometry_preview_value(
                config.departure_leg_length,
                automatic_departure_distance,
            ),
            final_leg_length=self._geometry_preview_value(
                config.final_leg_length,
                automatic_final_distance,
            ),
            turn_radius=turn_radius,
            downwind_offset=self._geometry_preview_value(
                config.downwind_offset,
                automatic_downwind_offset,
            ),
        )

    def resolve_parameter_preview(
        self,
        aircraft: Aircraft,
        config: TrackConfig,
    ) -> ParameterPreviewResponse:
        """Resolve all optional parameters and expose regulation help text."""
        config = self._effective_visual_config(aircraft, config)
        geometry = self.resolve_geometry_parameters(aircraft, config)
        class_rules = self.regulations["vfr_pattern_classes"][aircraft.vfr_pattern_class]
        visual_rules = self.regulations["visual_procedure"]
        visual_config = config.visual_pattern

        standard_height_rule = class_rules.get("standard_circuit_height_m", {})
        max_ias_rule = class_rules.get("max_ias_kmh", {})
        first_turn_rule = visual_rules.get("first_turn_min_height_m", {})
        final_turn_rule = visual_rules.get("final_turn_min_height_m", {})
        stable_final_rule = visual_rules.get("stable_final_distance_m", {})

        obstacle_config = self._obstacle_config(config)
        surface_set, code_rules, effective_code = self._surface_rule_set(obstacle_config)
        approach_segments = code_rules["approach"]["segments"]
        approach_first = approach_segments[0]
        takeoff_rule = code_rules["takeoffClimb"]
        inner_horizontal_rule = code_rules["innerHorizontal"]
        conical_rule = code_rules["conical"]
        transitional_rule = code_rules.get("transitional", {})

        airspace_config = self._flight_camp_config(aircraft, config)
        camp_rules = self._flight_camp_category_rules(airspace_config.camp_type)
        radius_value, height_value, clearance_value = self._resolve_airspace_values(airspace_config, camp_rules)

        return ParameterPreviewResponse(
            visual_pattern={
                "departureLegLength": self._parameter_item_from_geometry(
                    geometry.departure_leg_length,
                    "m",
                    class_rules["departure_distance_m"],
                ),
                "finalLegLength": self._parameter_item_from_geometry(
                    geometry.final_leg_length,
                    "m",
                    class_rules["final_distance_m"],
                ),
                "turnRadius": self._parameter_item_from_geometry(
                    geometry.turn_radius,
                    "m",
                    {
                        "sourceCode": "AC-97-FS-005R1",
                        "clause": "转弯半径",
                        "description": "按机型最小半径和速度/坡度协调转弯半径取大值。",
                    },
                ),
                "downwindOffset": self._parameter_item_from_geometry(
                    geometry.downwind_offset,
                    "m",
                    class_rules["downwind_offset_m"],
                ),
                "standardCircuitHeight": self._parameter_item(
                    value=config.circuit_height,
                    automatic_value=self._rule_value(standard_height_rule, 300),
                    source="custom" if visual_config and visual_config.standard_circuit_height is not None else "auto",
                    rule=standard_height_rule,
                ),
                "maxIasKmh": self._parameter_item(
                    value=visual_config.max_ias_kmh if visual_config and visual_config.max_ias_kmh is not None else aircraft.vfr_max_ias_kmh,
                    automatic_value=self._rule_value(max_ias_rule, aircraft.vfr_max_ias_kmh),
                    source="custom" if visual_config and visual_config.max_ias_kmh is not None else "auto",
                    rule=max_ias_rule,
                ),
                "stableFinalDistance": self._parameter_item(
                    value=visual_config.stable_final_distance if visual_config and visual_config.stable_final_distance is not None else self._rule_value(stable_final_rule, 1500),
                    automatic_value=self._rule_value(stable_final_rule, 1500),
                    source="custom" if visual_config and visual_config.stable_final_distance is not None else "auto",
                    rule=stable_final_rule,
                ),
                "firstTurnMinHeight": self._parameter_item(
                    value=visual_config.first_turn_min_height if visual_config and visual_config.first_turn_min_height is not None else self._rule_value(first_turn_rule, 150),
                    automatic_value=self._rule_value(first_turn_rule, 150),
                    source="custom" if visual_config and visual_config.first_turn_min_height is not None else "auto",
                    rule=first_turn_rule,
                ),
                "finalTurnMinHeight": self._parameter_item(
                    value=visual_config.final_turn_min_height if visual_config and visual_config.final_turn_min_height is not None else self._rule_value(final_turn_rule, 150),
                    automatic_value=self._rule_value(final_turn_rule, 150),
                    source="custom" if visual_config and visual_config.final_turn_min_height is not None else "auto",
                    rule=final_turn_rule,
                ),
            },
            obstacle_surfaces={
                "codeNumber": self._parameter_item(
                    value=effective_code,
                    automatic_value=self.resolve_code_number(800),
                    source="custom" if config.obstacle_surfaces is not None else "auto",
                    unit="",
                    rule={"sourceCode": "MH 5001-2021", "clause": "5.2 表5.2.4", "description": f"飞行区指标I 根据跑道长度自动确定（当前: {effective_code}）"},
                ),
                "runwayOperationType": self._parameter_item(
                    value=obstacle_config.runway_operation_type,
                    automatic_value="non_instrument",
                    source="custom" if config.obstacle_surfaces is not None else "auto",
                    unit="",
                    rule=surface_set,
                ),
                "approachLength": self._parameter_item(
                    value=approach_first["lengthM"],
                    automatic_value=approach_first["lengthM"],
                    source="auto",
                    unit="m",
                    rule=surface_set,
                    description=f"进近面第一段长度，内边宽 {approach_first['innerEdgeWidthM']}m，散开率每侧 {approach_first['divergenceEachSide'] * 100:.1f}%，坡度 {approach_first['slopePercent']}%。",
                ),
                "takeoffClimbLength": self._parameter_item(
                    value=takeoff_rule["lengthM"],
                    automatic_value=takeoff_rule["lengthM"],
                    source="auto",
                    unit="m",
                    rule=surface_set,
                    description=f"起飞爬升面长度，最终宽度 {takeoff_rule['finalWidthM']}m，坡度 {takeoff_rule['slopePercent']}%。",
                ),
                "innerHorizontalRadius": self._parameter_item(
                    value=inner_horizontal_rule["radiusM"],
                    automatic_value=inner_horizontal_rule["radiusM"],
                    source="auto",
                    unit="m",
                    rule=surface_set,
                    description=f"内水平面半径，高出跑道标高 {inner_horizontal_rule['heightM']}m。",
                ),
                "conicalOuterRadius": self._parameter_item(
                    value=inner_horizontal_rule["radiusM"] + conical_rule["heightM"] / (conical_rule["slopePercent"] / 100),
                    automatic_value=inner_horizontal_rule["radiusM"] + conical_rule["heightM"] / (conical_rule["slopePercent"] / 100),
                    source="auto",
                    unit="m",
                    rule=surface_set,
                    description=f"锥形面外缘半径，坡度 {conical_rule['slopePercent']}%，高度 {conical_rule['heightM']}m。",
                ),
            },
            flight_camp_airspace={
                "campType": self._parameter_item(
                    value=airspace_config.camp_type,
                    automatic_value=getattr(aircraft, "flight_camp_category", "light_aircraft"),
                    source="custom" if config.flight_camp_airspace is not None else "auto",
                    unit="",
                    rule={"sourceCode": self.flight_camp_rules.get("sourceCode", ""), "clause": camp_rules["radiusM"].get("clause", ""), "description": camp_rules["radiusM"].get("description", "")},
                ),
                "radius": self._parameter_item(
                    value=radius_value,
                    automatic_value=self._rule_value(camp_rules["radiusM"], radius_value),
                    source="custom" if airspace_config.radius_m is not None else "auto",
                    rule=camp_rules["radiusM"],
                ),
                "trueHeight": self._parameter_item(
                    value=height_value,
                    automatic_value=self._rule_value(camp_rules["trueHeightM"], height_value),
                    source="custom" if airspace_config.true_height_m is not None else "auto",
                    rule=camp_rules["trueHeightM"],
                ),
                "clearanceRadius": self._parameter_item(
                    value=clearance_value,
                    automatic_value=self._rule_value(camp_rules["clearanceRadiusM"], clearance_value),
                    source="custom" if airspace_config.clearance_radius_m is not None else "auto",
                    rule=camp_rules["clearanceRadiusM"],
                ),
            },
        )

    def _parameter_item_from_geometry(
        self,
        preview: GeometryParameterPreview,
        unit: str,
        rule: Dict[str, Any],
    ) -> ParameterPreviewItem:
        return self._parameter_item(
            value=preview.value,
            automatic_value=preview.automatic_value,
            source=preview.source,
            unit=unit,
            rule=rule,
        )

    def _parameter_item(
        self,
        value: float | str | bool,
        automatic_value: float | str | bool,
        source: str,
        rule: Dict[str, Any],
        unit: Optional[str] = None,
        description: Optional[str] = None,
    ) -> ParameterPreviewItem:
        return ParameterPreviewItem(
            value=value,
            automatic_value=automatic_value,
            source=source,  # type: ignore[arg-type]
            unit=unit if unit is not None else str(rule.get("unit", "")),
            source_code=str(rule.get("sourceCode", "")),
            clause=str(rule.get("clause", "")),
            description=description if description is not None else str(rule.get("description", "")),
        )

    def _geometry_preview_value(
        self,
        configured_value: float | None,
        automatic_value: float,
    ) -> GeometryParameterPreview:
        source = "custom" if configured_value is not None else "auto"
        return GeometryParameterPreview(
            value=round(float(configured_value if configured_value is not None else automatic_value), 1),
            automatic_value=round(float(automatic_value), 1),
            source=source,
        )

    @staticmethod
    def resolve_code_number(runway_length_m: float) -> str:
        """根据跑道长度自动确定飞行区指标I (MH 5001-2021 / ICAO Annex 14).

        代码1: L ≤ 800m  (飞行营地通常为 400-800m 跑道)
        代码2: 800m < L < 1200m
        代码3: 1200m ≤ L < 1800m
        代码4: L ≥ 1800m
        """
        if runway_length_m <= 800:
            return "1"
        elif runway_length_m < 1200:
            return "2"
        elif runway_length_m < 1800:
            return "3"
        else:
            return "4"

    def _obstacle_config(self, config: TrackConfig) -> ObstacleSurfaceConfig:
        return config.obstacle_surfaces or ObstacleSurfaceConfig()

    def _surface_rule_set(
        self, surface_config: ObstacleSurfaceConfig, runway_length_m: float = 800
    ) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
        """获取障碍物限制面规则集，支持根据跑道长度自动确定代码编号。"""
        surface_sets = self.obstacle_rules.get("surfaceSets", {})
        selected = surface_sets.get(surface_config.runway_operation_type, {})
        if isinstance(selected, dict) and "codeNumbers" not in selected:
            selected = surface_sets.get("non_instrument", {})

        # 自动根据跑道长度确定代码编号（若用户选择auto或未指定）
        effective_code = surface_config.code_number
        if effective_code == "auto" or effective_code not in ("1", "2", "3", "4"):
            effective_code = self.resolve_code_number(runway_length_m)

        code_rules = selected.get("codeNumbers", {}).get(effective_code)
        if code_rules is None:
            code_rules = selected.get("codeNumbers", {}).get("1")
        if code_rules is None:
            raise ValueError("MH5001 obstacle surface rules are not configured")
        return selected, code_rules, effective_code

    def _flight_camp_config(self, aircraft: Aircraft, config: TrackConfig) -> FlightCampAirspaceConfig:
        if config.flight_camp_airspace:
            return config.flight_camp_airspace
        camp_type = getattr(aircraft, "flight_camp_category", "light_aircraft")
        return FlightCampAirspaceConfig(camp_type=camp_type)

    def _flight_camp_category_rules(self, camp_type: str) -> Dict[str, Any]:
        categories = self.flight_camp_rules.get("categories", {})
        if camp_type not in categories:
            raise ValueError(f"Unknown flight camp airspace category: {camp_type}")
        return categories[camp_type]

    def _resolve_airspace_values(
        self,
        config: FlightCampAirspaceConfig,
        rules: Dict[str, Any],
    ) -> Tuple[float, float, float]:
        radius = float(config.radius_m if config.radius_m is not None else self._rule_value(rules["radiusM"], 2000))
        true_height = float(
            config.true_height_m if config.true_height_m is not None else self._rule_value(rules["trueHeightM"], 100)
        )
        clearance_radius = float(
            config.clearance_radius_m
            if config.clearance_radius_m is not None
            else self._rule_value(rules["clearanceRadiusM"], 0)
        )
        return radius, true_height, clearance_radius

    def _validate_required_mapping(self, aircraft: Aircraft) -> List[TrackValidationError]:
        errors: List[TrackValidationError] = []
        if aircraft.vfr_pattern_class not in self.regulations["vfr_pattern_classes"]:
            errors.append(
                TrackValidationError(
                    code="AIRCRAFT_VFR_CLASS_MISSING",
                    message=f"机型缺少可用的目视起落航线规范类别：{aircraft.id}",
                    severity="error",
                )
            )
        if not aircraft.vfr_max_ias_kmh:
            errors.append(
                TrackValidationError(
                    code="AIRCRAFT_VFR_IAS_MISSING",
                    message=f"机型缺少目视程序最大IAS：{aircraft.id}",
                    severity="error",
                )
            )
        return errors

    def _departure_heading(self, runway: RunwayParams, config: TrackConfig) -> float:
        heading = runway.magnetic_bearing
        if config.active_runway_end == "reciprocal":
            heading = (heading + 180) % 360
        if config.magnetic_variation != 0:
            heading = (heading - config.magnetic_variation + 360) % 360
        return round(heading, 1)

    def _active_threshold(self, runway: RunwayParams, departure_heading: float) -> Coordinate:
        return self.transformer.destination_point(
            runway.coordinate,
            (departure_heading + 180) % 360,
            runway.length / 2,
        )

    def _local_to_coordinate(
        self,
        origin: Coordinate,
        departure_heading: float,
        point: LocalPoint,
    ) -> Coordinate:
        x, y = point
        coordinate = origin
        if abs(x) > 0.001:
            bearing = departure_heading if x >= 0 else (departure_heading + 180) % 360
            coordinate = self.transformer.destination_point(coordinate, bearing, abs(x))
        if abs(y) > 0.001:
            bearing = (departure_heading + 90) % 360 if y >= 0 else (departure_heading - 90) % 360
            coordinate = self.transformer.destination_point(coordinate, bearing, abs(y))
        return coordinate

    def _bearing_from_local_heading(self, departure_heading: float, theta: float) -> float:
        return round((departure_heading + math.degrees(theta) + 360) % 360, 1)

    def _build_local_pattern(
        self,
        side: int,
        turn_radius: float,
        departure_distance: float,
        final_distance: float,
        downwind_offset: float,
        arc_points_count: int,
    ) -> List[dict]:
        segments: List[dict] = []

        p0: LocalPoint = (0.0, 0.0)
        p1: LocalPoint = (departure_distance, 0.0)
        theta = 0.0
        segments.append(self._straight("departure", p0, p1, theta))

        arc, p2, theta = self._turn_arc(p1, theta, side, turn_radius, arc_points_count)
        segments.append(self._turn("turn_1", p1, p2, theta, turn_radius, arc))

        p3: LocalPoint = (departure_distance + turn_radius, side * (downwind_offset - turn_radius))
        segments.append(self._straight("crosswind_leg", p2, p3, theta))

        arc, p4, theta = self._turn_arc(p3, theta, side, turn_radius, arc_points_count)
        segments.append(self._turn("turn_2", p3, p4, theta, turn_radius, arc))

        p5: LocalPoint = (-final_distance, side * downwind_offset)
        segments.append(self._straight("downwind_leg", p4, p5, theta))

        arc, p6, theta = self._turn_arc(p5, theta, side, turn_radius, arc_points_count)
        segments.append(self._turn("turn_3", p5, p6, theta, turn_radius, arc))

        p7: LocalPoint = (-final_distance - turn_radius, side * turn_radius)
        segments.append(self._straight("base_leg", p6, p7, theta))

        arc, p8, theta = self._turn_arc(p7, theta, side, turn_radius, arc_points_count)
        segments.append(self._turn("turn_4", p7, p8, theta, turn_radius, arc))

        p9: LocalPoint = (0.0, 0.0)
        segments.append(self._straight("final_approach", p8, p9, theta))
        return segments

    def _straight(self, name: TrackSegmentName, start: LocalPoint, end: LocalPoint, theta: float) -> dict:
        distance = math.dist(start, end)
        return {
            "name": name,
            "start": start,
            "end": end,
            "path": None,
            "distance": distance,
            "theta": theta,
        }

    def _turn(
        self,
        name: TrackSegmentName,
        start: LocalPoint,
        end: LocalPoint,
        theta: float,
        radius: float,
        path: List[LocalPoint],
    ) -> dict:
        return {
            "name": name,
            "start": start,
            "end": end,
            "path": path,
            "distance": math.pi * radius / 2,
            "theta": theta,
        }

    def _turn_arc(
        self,
        start: LocalPoint,
        theta: float,
        side: int,
        radius: float,
        count: int,
    ) -> Tuple[List[LocalPoint], LocalPoint, float]:
        right_normal = (-math.sin(theta), math.cos(theta))
        center = (
            start[0] + side * right_normal[0] * radius,
            start[1] + side * right_normal[1] * radius,
        )
        initial = (start[0] - center[0], start[1] - center[1])

        path: List[LocalPoint] = []
        for index in range(count):
            progress = index / (count - 1)
            angle = side * (math.pi / 2) * progress
            path.append(
                (
                    center[0] + initial[0] * math.cos(angle) - initial[1] * math.sin(angle),
                    center[1] + initial[0] * math.sin(angle) + initial[1] * math.cos(angle),
                )
            )

        return path, path[-1], theta + side * (math.pi / 2)

    def _to_track_segments(
        self,
        local_segments: List[dict],
        origin: Coordinate,
        departure_heading: float,
        runway: RunwayParams,
        aircraft: Aircraft,
        config: TrackConfig,
    ) -> List[TrackSegment]:
        segments: List[TrackSegment] = []
        previous_altitude = runway.elevation

        for local_segment in local_segments:
            name: TrackSegmentName = local_segment["name"]
            path_points = None
            if local_segment["path"]:
                path_points = [
                    self._local_to_coordinate(origin, departure_heading, point)
                    for point in local_segment["path"]
                ]

            altitude = self._segment_altitude(name, runway, aircraft, config, local_segment["distance"])
            vertical_angle = self._segment_vertical_angle(
                start_altitude=previous_altitude,
                end_altitude=altitude,
                distance=local_segment["distance"],
            )
            segments.append(
                TrackSegment(
                    name=name,
                    name_cn=self.SEGMENT_NAMES[name],
                    start_point=self._local_to_coordinate(origin, departure_heading, local_segment["start"]),
                    end_point=self._local_to_coordinate(origin, departure_heading, local_segment["end"]),
                    path_points=path_points,
                    distance=round(local_segment["distance"], 1),
                    heading=self._bearing_from_local_heading(departure_heading, local_segment["theta"]),
                    altitude=altitude,
                    vertical_angle=vertical_angle,
                )
            )
            previous_altitude = altitude

        return segments

    def _segment_altitude(
        self,
        name: TrackSegmentName,
        runway: RunwayParams,
        aircraft: Aircraft,
        config: TrackConfig,
        distance: float,
    ) -> float:
        circuit_altitude = runway.elevation + config.circuit_height
        if name == "departure":
            climb_gain = distance * aircraft.climb_rate / (aircraft.cruise_speed * 1000 / 3600)
            return round(min(circuit_altitude, runway.elevation + climb_gain), 1)
        if name in {"turn_1", "crosswind_leg"}:
            return round(min(circuit_altitude, runway.elevation + config.circuit_height * 0.65), 1)
        if name in {"turn_2", "downwind_leg", "turn_3"}:
            return round(circuit_altitude, 1)
        if name in {"base_leg", "turn_4"}:
            return round(max(runway.elevation + 30, runway.elevation + config.circuit_height * 0.5), 1)
        return round(runway.elevation + 15, 1)

    def _segment_vertical_angle(
        self,
        start_altitude: float,
        end_altitude: float,
        distance: float,
    ) -> float:
        if distance <= 0:
            return 0.0
        return round(math.degrees(math.atan((end_altitude - start_altitude) / distance)), 1)

    def _build_key_points(
        self,
        segments: List[TrackSegment],
        threshold: Coordinate,
        runway: RunwayParams,
        config: TrackConfig,
    ) -> List[GeometryOverlay]:
        return [
            GeometryOverlay(
                id="active-threshold",
                kind="marker",
                label=f"{'主向' if config.active_runway_end == 'primary' else '反向'}入口",
                coordinates=[threshold],
                style_key="threshold",
                altitude=runway.elevation,
            ),
            GeometryOverlay(
                id="departure-turn",
                kind="marker",
                label="一转弯点",
                coordinates=[segments[0].end_point],
                style_key="key-point",
                altitude=segments[0].altitude,
            ),
            GeometryOverlay(
                id="downwind-entry",
                kind="marker",
                label="三边加入点",
                coordinates=[segments[3].end_point],
                style_key="key-point",
                altitude=segments[3].altitude,
            ),
            GeometryOverlay(
                id="base-turn",
                kind="marker",
                label="四边转弯点",
                coordinates=[segments[5].end_point],
                style_key="key-point",
                altitude=segments[5].altitude,
            ),
            GeometryOverlay(
                id="final-intercept",
                kind="marker",
                label="五边切入点",
                coordinates=[segments[7].end_point],
                style_key="key-point",
                altitude=segments[7].altitude,
            ),
        ]

    def _build_annotations(
        self,
        segments: List[TrackSegment],
        key_points: List[GeometryOverlay],
        runway: RunwayParams,
        aircraft: Aircraft,
        config: TrackConfig,
        geometry: GeometryPreviewResponse,
    ) -> List[ProcedureAnnotation]:
        annotations: List[ProcedureAnnotation] = []

        for segment in segments:
            if segment.name in self.LEG_LABELS and segment.distance > 1:
                leg_label = self.LEG_LABELS[segment.name]
                annotations.append(
                    ProcedureAnnotation(
                        id=f"segment-{segment.name}",
                        coordinate=self._segment_midpoint(segment),
                        label=leg_label,
                        lines=[
                            f"{leg_label} {self._format_distance(segment.distance)}",
                            f"航向 {segment.heading:.0f}°",
                            self._format_vertical_angle(segment.vertical_angle),
                        ],
                        style_key="segment-label",
                        related_segment=segment.name,
                    )
                )

            if segment.name.startswith("turn_") and segment.distance > 1:
                turn_radius = segment.distance / (math.pi / 2)
                annotations.append(
                    ProcedureAnnotation(
                        id=f"turn-{segment.name}",
                        coordinate=self._segment_midpoint(segment),
                        label=segment.name_cn,
                        lines=[
                            f"R={self._format_distance(turn_radius)}",
                            f"MAX{aircraft.vfr_max_ias_kmh}km/h",
                            self._format_vertical_angle(segment.vertical_angle),
                        ],
                        style_key="turn-label",
                        related_segment=segment.name,
                    )
                )

        for point in key_points:
            if not point.coordinates:
                continue
            altitude_text = f"QNH{point.altitude:.1f}m" if point.altitude is not None else ""
            annotations.append(
                ProcedureAnnotation(
                    id=f"point-{point.id}",
                    coordinate=point.coordinates[0],
                    label=point.label,
                    lines=[line for line in [point.label, altitude_text] if line],
                    style_key="point-label",
                )
            )

        if key_points and key_points[0].coordinates:
            annotations.append(
                ProcedureAnnotation(
                    id="performance-summary",
                    coordinate=key_points[0].coordinates[0],
                    label="程序参数",
                    lines=[
                        f"爬升率 {aircraft.climb_rate:.1f}m/s",
                        f"MAX IAS {aircraft.vfr_max_ias_kmh}km/h",
                        f"坡度 {config.bank_angle}°",
                        f"间隔 {self._format_distance(geometry.downwind_offset.value)}",
                    ],
                    style_key="performance-label",
                )
            )

        return annotations

    def _segment_midpoint(self, segment: TrackSegment) -> Coordinate:
        if segment.path_points:
            return segment.path_points[len(segment.path_points) // 2]

        return Coordinate(
            latitude=(segment.start_point.latitude + segment.end_point.latitude) / 2,
            longitude=(segment.start_point.longitude + segment.end_point.longitude) / 2,
        )

    def _format_distance(self, distance_m: float) -> str:
        if distance_m >= 1000:
            return f"{distance_m / 1000:.1f}km"
        return f"{distance_m:.0f}m"

    def _format_vertical_angle(self, angle: float) -> str:
        if angle > 0:
            return f"爬升角 +{angle:.1f}°"
        if angle < 0:
            return f"下降角 {angle:.1f}°"
        return "平飞 0.0°"

    def _build_flight_camp_airspaces(
        self,
        runway: RunwayParams,
        aircraft: Aircraft,
        config: TrackConfig,
    ) -> List[GeometryOverlay]:
        airspace_config = self._flight_camp_config(aircraft, config)
        if not airspace_config.enabled:
            return []

        rules = self._flight_camp_category_rules(airspace_config.camp_type)
        radius, true_height, clearance_radius = self._resolve_airspace_values(airspace_config, rules)
        label = rules.get("label", airspace_config.camp_type)

        def coords(points: List[LocalPoint]) -> List[Coordinate]:
            return [self._local_to_coordinate(runway.coordinate, 0, point) for point in points]

        overlays = [
            GeometryOverlay(
                id=f"flight-camp-{airspace_config.camp_type}",
                kind="polygon",
                label=f"飞行营地空域：{label} 半径{radius / 1000:.1f}km 真高{true_height:.0f}m",
                coordinates=coords(self._circle_points((0, 0), radius, 96)),
                style_key=self.flight_camp_rules.get("defaultStyleKey", "flight-camp-airspace"),
                altitude=runway.elevation + true_height,
                metadata={
                    "sourceCode": self.flight_camp_rules.get("sourceCode", ""),
                    "clause": rules["radiusM"].get("clause", ""),
                    "campType": airspace_config.camp_type,
                    "radiusM": radius,
                    "trueHeightM": true_height,
                    "description": rules["radiusM"].get("description", ""),
                },
            )
        ]

        if clearance_radius > 0:
            overlays.append(
                GeometryOverlay(
                    id=f"flight-camp-clearance-{airspace_config.camp_type}",
                    kind="polygon",
                    label=f"{label}净空检查范围 {clearance_radius:.0f}m",
                    coordinates=coords(self._circle_points((0, 0), clearance_radius, 72)),
                    style_key="flight-camp-clearance",
                    altitude=runway.elevation,
                    metadata={
                        "sourceCode": self.flight_camp_rules.get("sourceCode", ""),
                        "clause": rules["clearanceRadiusM"].get("clause", ""),
                        "campType": airspace_config.camp_type,
                        "clearanceRadiusM": clearance_radius,
                        "description": rules["clearanceRadiusM"].get("description", ""),
                    },
                )
            )

        if airspace_config.overlay_special_airspace:
            overlays.append(
                GeometryOverlay(
                    id=f"flight-camp-special-{airspace_config.camp_type}",
                    kind="polygon",
                    label=f"{label}特殊飞行空域预留范围",
                    coordinates=coords(self._circle_points((0, 0), radius * 1.2, 96)),
                    style_key="flight-camp-special-airspace",
                    altitude=runway.elevation + true_height,
                    metadata={
                        "sourceCode": self.flight_camp_rules.get("sourceCode", ""),
                        "clause": "声明 / 各项目特殊飞行空域",
                        "campType": airspace_config.camp_type,
                        "radiusM": radius * 1.2,
                        "description": "竞赛及特殊飞行空域可按需求另行申请划设；该层仅作预留示意。",
                    },
                )
            )

        return overlays

    def _build_compliance(
        self,
        runway: RunwayParams,
        aircraft: Aircraft,
        config: TrackConfig,
        geometry: GeometryPreviewResponse,
        surfaces: List[GeometryOverlay],
        airspaces: List[GeometryOverlay],
    ) -> List[ComplianceItem]:
        items: List[ComplianceItem] = []
        visual_rules = self.regulations.get("visual_procedure", {})
        class_rules = self.regulations.get("vfr_pattern_classes", {}).get(aircraft.vfr_pattern_class, {})

        items.append(
            ComplianceItem(
                id="visual-pattern-side",
                category="visual_pattern",
                status="compliant" if config.traffic_pattern_side == "left" else "warning",
                severity="info" if config.traffic_pattern_side == "left" else "warning",
                message=(
                    "按 AP-91 标准左起落航线生成。"
                    if config.traffic_pattern_side == "left"
                    else "已按右起落航线生成；AP-91 要求右起落航线应由航空情报资料公布或另有规定。"
                ),
                source_code="AP-91-FS-2019-02",
                clause="5.1 / 8.1",
            )
        )

        max_ias = self._rule_value(class_rules.get("max_ias_kmh"), aircraft.vfr_max_ias_kmh)
        items.append(
            ComplianceItem(
                id="visual-max-ias",
                category="visual_pattern",
                status="compliant" if aircraft.vfr_max_ias_kmh <= max_ias else "warning",
                severity="info" if aircraft.vfr_max_ias_kmh <= max_ias else "warning",
                message=f"机型程序最大 IAS {aircraft.vfr_max_ias_kmh} km/h，类别 {aircraft.vfr_pattern_class} 规则值 {max_ias} km/h。",
                source_code=str(class_rules.get("max_ias_kmh", {}).get("sourceCode", "AC-97-FS-005R1")),
                clause=str(class_rules.get("max_ias_kmh", {}).get("clause", "航空器速度分类")),
            )
        )

        first_turn_min = float(self._rule_value(visual_rules.get("first_turn_min_height_m"), 150))
        final_turn_min = float(self._rule_value(visual_rules.get("final_turn_min_height_m"), 150))
        items.append(
            ComplianceItem(
                id="visual-key-heights",
                category="visual_pattern",
                status="custom_compliant",
                message=f"关键高度提示：一转弯建议不低于 {first_turn_min:.0f}m，四转弯/五边切入建议不低于 {final_turn_min:.0f}m。",
                source_code="AC-97-FS-005R1",
                clause="目视起落航线关键高度控制",
                details={
                    "firstTurnMinHeightM": first_turn_min,
                    "finalTurnMinHeightM": final_turn_min,
                    "circuitHeightM": config.circuit_height,
                },
            )
        )

        custom_geometry = [
            geometry.departure_leg_length,
            geometry.final_leg_length,
            geometry.turn_radius,
            geometry.downwind_offset,
        ]
        items.append(
            ComplianceItem(
                id="visual-geometry-source",
                category="visual_pattern",
                status="custom_compliant" if any(item.source == "custom" for item in custom_geometry) else "compliant",
                message=(
                    "存在人工航线几何参数；已按最小直线段、转弯半径和一边三边间隔进行校验。"
                    if any(item.source == "custom" for item in custom_geometry)
                    else "航线几何参数按机型规范类别、速度和坡度自动推算。"
                ),
                source_code="AC-97-FS-005R1",
                clause="目视起落航线几何参数",
                details={
                    "departureLegLengthM": geometry.departure_leg_length.value,
                    "finalLegLengthM": geometry.final_leg_length.value,
                    "turnRadiusM": geometry.turn_radius.value,
                    "downwindOffsetM": geometry.downwind_offset.value,
                },
            )
        )

        obstacle_config = self._obstacle_config(config)
        surface_set, _, effective_code = self._surface_rule_set(obstacle_config, runway.length)
        precise_fallback = obstacle_config.runway_operation_type != "non_instrument"
        items.append(
            ComplianceItem(
                id="ols-generated",
                category="obstacle_surface",
                status="compliant",
                severity="info",
                message=(
                    f"已生成 {len(surfaces)} 个 MH5001 障碍物限制面图层（飞行区指标I: {effective_code}，{surface_set.get('label', obstacle_config.runway_operation_type)}）。"
                ),
                source_code=surface_set.get("sourceCode", "MH 5001-2021"),
                clause=surface_set.get("clause", "5.2"),
                details={
                    "surfaceCount": len(surfaces),
                    "runwayOperationType": obstacle_config.runway_operation_type,
                    "codeNumber": effective_code,
                },
            )
        )

        airspace_config = self._flight_camp_config(aircraft, config)
        if airspace_config.enabled:
            rules = self._flight_camp_category_rules(airspace_config.camp_type)
            radius, true_height, clearance_radius = self._resolve_airspace_values(airspace_config, rules)
            auto_radius = float(self._rule_value(rules["radiusM"], radius))
            auto_height = float(self._rule_value(rules["trueHeightM"], true_height))
            status = "compliant"
            severity = "info"
            if radius < auto_radius or true_height < auto_height:
                status = "non_compliant"
                severity = "error"
            elif airspace_config.radius_m is not None or airspace_config.true_height_m is not None:
                status = "custom_compliant"
            items.append(
                ComplianceItem(
                    id="flight-camp-airspace",
                    category="flight_camp_airspace",
                    status=status,
                    severity=severity,
                    message=f"飞行营地空域 {rules.get('label', airspace_config.camp_type)}：半径 {radius / 1000:.1f}km，真高 {true_height:.0f}m，净空检查半径 {clearance_radius:.0f}m。",
                    source_code=self.flight_camp_rules.get("sourceCode", ""),
                    clause=rules["radiusM"].get("clause", ""),
                    details={
                        "airspaceCount": len(airspaces),
                        "campType": airspace_config.camp_type,
                        "radiusM": radius,
                        "trueHeightM": true_height,
                        "clearanceRadiusM": clearance_radius,
                    },
                )
            )

        return items

    def _build_obstacle_surfaces(
        self,
        origin: Coordinate,
        departure_heading: float,
        runway: RunwayParams,
        config: TrackConfig,
    ) -> List[GeometryOverlay]:
        """构建非仪表跑道障碍物限制面 (MH 5001-2021 第五章 表5.2.4)

        绘制顺序（从外到内，保证正确的遮挡关系）:
        1. 锥形面外缘 (最外层近似椭圆)
        2. 内水平面 (45m高水平面, 两端为圆弧两侧为直线)
        3. 进近面 (跑道入口前梯形斜面)
        4. 起飞爬升面 (跑道端外梯形斜面)
        5. 过渡面 (沿升降带和进近面边缘, 延伸到内水平面)
        6. 跑道升降带 (最内层)
        """
        surface_config = self._obstacle_config(config)
        runway_len = runway.length
        surface_set, rules, effective_code = self._surface_rule_set(surface_config, runway_len)

        styles = self.obstacle_rules.get("styles", {})
        strip_rules = self.obstacle_rules.get("runwayStrip", {})
        # strip half-width 根据飞行区指标取不同值: 指标1=30m, 指标2=40m, 指标3-4=75m
        strip_hw_rules = strip_rules.get("halfWidthM", {})
        strip_hw_defaults = strip_hw_rules.get("codeNumberDefaults", {"1": 30, "2": 40, "3": 75, "4": 75})
        strip_half_width = float(strip_hw_defaults.get(effective_code, 75))
        # endSafety 根据飞行区指标取不同值: 指标1=30m, 指标2-4=60m
        end_safety_rules = strip_rules.get("endSafetyM", {})
        end_safety_defaults = end_safety_rules.get("codeNumberDefaults", {"1": 30, "2": 60, "3": 60, "4": 60})
        end_safety = float(end_safety_defaults.get(effective_code, 60))

        # 跑道宽度 — 根据飞行区指标自动确定或使用用户输入值
        rw_width_rules = self.obstacle_rules.get("runwayWidth", {})
        rw_width_defaults = rw_width_rules.get("codeNumberDefaults", {"1": 18, "2": 23, "3": 30, "4": 45})
        auto_rw_width = float(rw_width_defaults.get(effective_code, 18))
        runway_width = runway.runway_width if runway.runway_width and runway.runway_width > 0 else auto_rw_width
        rw_half_width = runway_width / 2.0

        # 提取各面参数
        approach_segments = rules["approach"]["segments"]
        approach_first = approach_segments[0]
        takeoff = rules["takeoffClimb"]
        transitional = rules["transitional"]
        ih = rules["innerHorizontal"]
        conical = rules["conical"]

        # 关键尺寸
        ih_radius = float(ih["radiusM"])
        ih_height = float(ih["heightM"])
        conical_height = float(conical["heightM"])
        conical_slope = float(conical["slopePercent"]) / 100.0
        conical_outer_radius = ih_radius + conical_height / conical_slope
        trans_slope = float(transitional["slopePercent"]) / 100.0
        trans_run = ih_height / trans_slope  # 过渡面水平延伸距离

        # 进近面和起飞爬升面内边位置
        approach_inner_x = -float(approach_first["distanceFromThresholdM"])
        approach_inner_hw = float(approach_first["innerEdgeWidthM"]) / 2
        takeoff_inner_x = runway_len + float(takeoff["distanceFromRunwayEndM"])
        takeoff_inner_hw = float(takeoff["innerEdgeWidthM"]) / 2

        def coords(points: List[LocalPoint]) -> List[Coordinate]:
            return [self._local_to_coordinate(origin, departure_heading, point) for point in points]

        def overlay_metadata(surface_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "sourceCode": surface_set.get("sourceCode", self.obstacle_rules.get("sourceCode", "")),
                "clause": surface_set.get("clause", ""),
                "runwayOperationType": surface_config.runway_operation_type,
                "codeNumber": effective_code,
                "surfaceType": surface_type,
                "departureBearing": departure_heading,
                **params,
            }

        surfaces: List[GeometryOverlay] = []

        # ===== 1. 锥形面 (最外层环形) =====
        # 5.1.3: 从内水平面周边以1:20坡度向上向外倾斜
        # 锥形面是一个环形面, 外边界=conical外缘, 内边界(孔洞)=内水平面边界
        ih_capsule = self._capsule_points(runway_len, ih_radius, 96)
        conical_capsule = self._capsule_points(runway_len, conical_outer_radius, 96)
        inner_hole = [{"lat": c.latitude, "lng": c.longitude} for c in coords(ih_capsule)]
        surfaces.append(
            GeometryOverlay(
                id="mh5001-conical",
                kind="polygon",
                label=f"MH5001 锥形面 (内径{ih_radius}m, 外径{conical_outer_radius:.0f}m, 高{conical_height}m, 坡度1:20)",
                coordinates=coords(conical_capsule),
                style_key=styles.get("conical", "ols-conical"),
                altitude=runway.elevation + ih_height + conical_height,
                metadata=overlay_metadata("conical", {
                    **conical,
                    "innerRadiusM": ih_radius,
                    "outerRadiusM": conical_outer_radius,
                    "runwayLengthM": runway_len,
                    "holeRings": [inner_hole],
                    "description": f"锥形面——从内水平面周边起以1:20坡度向外向上倾斜{conical_height}m至外缘。",
                }),
            )
        )
        # 锥形面内边界线 (使环形更直观)
        surfaces.append(
            GeometryOverlay(
                id="mh5001-conical-inner-edge",
                kind="polyline",
                label=f"锥形面内边界 (内水平面外缘, 半径{ih_radius}m)",
                coordinates=coords(ih_capsule),
                style_key="ols-conical-inner-edge",
                altitude=runway.elevation + ih_height,
                metadata=overlay_metadata("conical-inner-edge", {
                    "radiusM": ih_radius,
                    "description": "锥形面内边界——即内水平面外缘。",
                }),
            )
        )

        # ===== 2. 内水平面 =====
        # 5.1.2: 高出跑道两端入口中点平均标高45m
        surfaces.append(
            GeometryOverlay(
                id="mh5001-inner-horizontal",
                kind="polygon",
                label=f"MH5001 内水平面 (半径{ih_radius}m, 高{ih_height}m)",
                coordinates=coords(ih_capsule),
                style_key=styles.get("innerHorizontal", "ols-inner-horizontal"),
                altitude=runway.elevation + ih_height,
                metadata=overlay_metadata("inner-horizontal", {
                    **ih,
                    "runwayLengthM": runway_len,
                    "description": "以跑道两端入口中点为圆心画弧，两侧以平行于跑道中线的直线相切形成的近似椭圆水平面。",
                }),
            )
        )

        # ===== 3. 进近面 =====
        # 5.1.4: 跑道入口前倾斜平面
        for seg_idx, seg in enumerate(approach_segments):
            seg_points = self._approach_segment_points(approach_segments, seg_idx)
            seg_length = float(seg["lengthM"])
            seg_slope = float(seg["slopePercent"])
            suffix = f"-section{seg_idx + 1}" if len(approach_segments) > 1 else ""
            suffix_label = f" 第{seg_idx + 1}段" if len(approach_segments) > 1 else ""
            alt = runway.elevation
            for i in range(seg_idx + 1):
                alt += float(approach_segments[i]["lengthM"]) * float(approach_segments[i]["slopePercent"]) / 100.0
            surfaces.append(
                GeometryOverlay(
                    id=f"mh5001-approach-surface{suffix}",
                    kind="polygon",
                    label=f"MH5001 进近面{suffix_label} (长{seg_length:.0f}m, 坡度{seg_slope}%)",
                    coordinates=coords(seg_points),
                    style_key=styles.get(
                        "approach" if seg_idx == 0 else f"approach-{seg_idx + 1}",
                        "ols-approach"
                    ),
                    altitude=alt,
                    metadata=overlay_metadata(f"approach{suffix}", {**seg, "segmentIndex": seg_idx}),
                )
            )

        # ===== 4. 起飞爬升面 =====
        # 5.1.9 / 表5.2.7: 跑道端外倾斜面
        if surface_config.takeoff_enabled:
            to_points = self._takeoff_climb_points(runway_len, takeoff)
            to_length = float(takeoff["lengthM"])
            to_slope = float(takeoff["slopePercent"])
            to_alt = runway.elevation + to_length * to_slope / 100.0
            surfaces.append(
                GeometryOverlay(
                    id="mh5001-takeoff-climb-surface",
                    kind="polygon",
                    label=f"MH5001 起飞爬升面 (长{to_length:.0f}m, 坡度{to_slope}%)",
                    coordinates=coords(to_points),
                    style_key=styles.get("takeoffClimb", "ols-takeoff-climb"),
                    altitude=to_alt,
                    metadata=overlay_metadata("takeoff-climb", {
                        **takeoff,
                        "description": f"起飞爬升面——内边{takeoff['innerEdgeWidthM']}m宽位于跑道端外{takeoff['distanceFromRunwayEndM']}m，散开至最终宽度{takeoff['finalWidthM']}m。",
                    }),
                )
            )

        # ===== 5. 过渡面 =====
        # 5.1.6: 沿升降带边缘和进近面边缘, 坡度向上向外延伸到内水平面
        # 左右两侧分开绘制, 内边界始于升降带端部(非跑道端部).
        # 进近面与内水平面的垂直交线连接左右过渡面, 三者共同形成封闭区域.
        approach_slope = float(approach_first["slopePercent"]) / 100.0
        approach_div = float(approach_first["divergenceEachSide"])
        approach_len = float(approach_first["lengthM"])

        # 进近面侧边与内水平面(y=ih_height)的交点距进近内边距离
        d_intersect = ih_height / approach_slope if approach_slope > 0 else 0
        d_intersect = min(d_intersect, approach_len)
        x_intersect = approach_inner_x - d_intersect
        z_intersect = approach_inner_hw + d_intersect * approach_div

        # 过渡面外边界半宽
        z_approach_outer = approach_inner_hw + trans_run  # 进近段外侧半宽 (x=approach_inner_x处)
        strip_outer_hw = strip_half_width + trans_run     # 升降带段外侧半宽

        # 右侧过渡面: 从进近面与内水平面交点 → 沿进近面右边缘/升降带右边缘 → 到起飞爬升面 → 返回
        trans_right = [
            (x_intersect, z_intersect),           # 1. 进近面右边缘∩内水平面
            (approach_inner_x, approach_inner_hw), # 2. 进近面右边缘起点(内边处)
            (approach_inner_x, strip_half_width),  # 3. 升降带右边缘起点
            (takeoff_inner_x, strip_half_width),   # 4. 升降带右边缘终点(起飞爬升面处)
            (takeoff_inner_x, strip_outer_hw),     # 5. 外侧边界终点
            (approach_inner_x, strip_outer_hw),    # 6. 升降带段外侧边起点
            (approach_inner_x, z_approach_outer),  # 7. 进近段外侧边起点(内边处)
            (x_intersect, z_intersect),           # 回到点1
        ]

        # 左侧过渡面: 镜像
        trans_left = [
            (x_intersect, -z_intersect),
            (approach_inner_x, -approach_inner_hw),
            (approach_inner_x, -strip_half_width),
            (takeoff_inner_x, -strip_half_width),
            (takeoff_inner_x, -strip_outer_hw),
            (approach_inner_x, -strip_outer_hw),
            (approach_inner_x, -z_approach_outer),
            (x_intersect, -z_intersect),
        ]

        # 进近面与内水平面垂直交线 (连接左右过渡面的进近端)
        ih_intersection_line = [
            (x_intersect, z_intersect),
            (x_intersect, -z_intersect),
        ]

        surface_label = (
            f"MH5001 进近面∩内水平面交线 "
            f"(x={x_intersect:.0f}m, z=±{z_intersect:.0f}m, 高{ih_height:.0f}m)"
        )
        surfaces.append(
            GeometryOverlay(
                id="mh5001-approach-ih-intersection",
                kind="polyline",
                label=surface_label,
                coordinates=coords(ih_intersection_line),
                style_key="ols-approach-ih-intersection",
                altitude=runway.elevation + ih_height,
                metadata=overlay_metadata("approach-ih-intersection", {
                    "xIntersect": x_intersect,
                    "zIntersect": z_intersect,
                    "ihHeightM": ih_height,
                    "description": (
                        f"进近面与内水平面的垂直交线——进近面侧边在y={ih_height:.0f}m处与内水平面相交, "
                        f"交点位置x={x_intersect:.0f}m, z=±{z_intersect:.0f}m。"
                    ),
                }),
            )
        )

        common_metadata = {
            **transitional,
            "transitionRunM": trans_run,
            "stripHalfWidthM": strip_half_width,
            "stripOuterHW": strip_outer_hw,
            "startX": approach_inner_x,
            "endX": takeoff_inner_x,
            "approachIntersectX": x_intersect,
            "approachIntersectZ": z_intersect,
            "approachOuterZ": z_approach_outer,
            "approachInnerX": approach_inner_x,
            "approachLengthM": approach_len,
            "approachSlopePercent": float(approach_first["slopePercent"]),
            "approachDivergence": approach_div,
            "approachInnerHW": approach_inner_hw,
            "description": (
                f"过渡面——沿升降带边缘({strip_half_width:.0f}m)和进近面边缘"
                f"以{int(trans_slope*100)}%坡度向上向外延伸{trans_run:.0f}m至内水平面({ih_height:.0f}m高)。"
            ),
        }

        surfaces.append(
            GeometryOverlay(
                id="mh5001-transitional-right",
                kind="polygon",
                label=f"MH5001 右侧过渡面 (坡度{int(trans_slope*100)}%, 水平延伸{trans_run:.0f}m)",
                coordinates=coords(trans_right),
                style_key=styles.get("transitional", "ols-transitional"),
                altitude=runway.elevation + ih_height,
                metadata=overlay_metadata("transitional", {"side": "right", **common_metadata}),
            )
        )
        surfaces.append(
            GeometryOverlay(
                id="mh5001-transitional-left",
                kind="polygon",
                label=f"MH5001 左侧过渡面 (坡度{int(trans_slope*100)}%, 水平延伸{trans_run:.0f}m)",
                coordinates=coords(trans_left),
                style_key=styles.get("transitional", "ols-transitional"),
                altitude=runway.elevation + ih_height,
                metadata=overlay_metadata("transitional", {"side": "left", **common_metadata}),
            )
        )

        # ===== 6. 跑道升降带 (最内层) =====
        runway_strip_points = [
            (-end_safety, -strip_half_width),
            (runway_len + end_safety, -strip_half_width),
            (runway_len + end_safety, strip_half_width),
            (-end_safety, strip_half_width),
        ]
        surfaces.append(
            GeometryOverlay(
                id="runway-protection-surface",
                kind="polygon",
                label=f"跑道升降带 (半宽{strip_half_width:.0f}m, 端外{end_safety:.0f}m)",
                coordinates=coords(runway_strip_points),
                style_key=styles.get("runwayStrip", "runway-surface"),
                altitude=runway.elevation,
                metadata=overlay_metadata("runway-strip", {
                    "halfWidthM": strip_half_width,
                    "endSafetyM": end_safety,
                    "description": f"升降带——跑道两侧各{strip_half_width:.0f}m、两端外各{end_safety:.0f}m。",
                }),
            )
        )

        # ===== 7. 跑道 =====
        runway_rect = [
            (0, -rw_half_width),
            (runway_len, -rw_half_width),
            (runway_len, rw_half_width),
            (0, rw_half_width),
        ]
        surfaces.append(
            GeometryOverlay(
                id="runway-area",
                kind="polygon",
                label=f"跑道 {runway_len}m × {runway_width:.0f}m (飞行区指标{effective_code})",
                coordinates=coords(runway_rect),
                style_key="runway-area",
                altitude=runway.elevation,
                metadata=overlay_metadata("runway-area", {
                    "lengthM": runway_len,
                    "widthM": runway_width,
                    "codeNumber": effective_code,
                    "description": f"跑道，{runway_len}m×{runway_width:.0f}m。",
                }),
            )
        )

        # ===== 8. 跑道中线 (参考线) =====
        runway_centerline_points = [(0, 0), (runway_len, 0)]
        surfaces.append(
            GeometryOverlay(
                id="runway-centerline",
                kind="polyline",
                label=f"跑道中线 {runway_len}m / 磁方位 {runway.magnetic_bearing}°",
                coordinates=coords(runway_centerline_points),
                style_key="runway-centerline",
                altitude=runway.elevation,
                metadata=overlay_metadata("runway-centerline", {
                    "runwayLengthM": runway_len,
                    "magneticBearing": runway.magnetic_bearing,
                }),
            )
        )

        # ===== 9. 入口中点标记 (内水平面圆心) =====
        for label_text, x_pos in [("primary", 0), ("reciprocal", runway_len)]:
            threshold_marker = coords([(x_pos, 0)])
            surfaces.append(
                GeometryOverlay(
                    id=f"threshold-midpoint-{label_text}",
                    kind="marker",
                    label=f"跑道{'入口' if label_text == 'primary' else '末端'}中点 (内水平面圆心)",
                    coordinates=threshold_marker,
                    style_key="threshold",
                    altitude=runway.elevation,
                    metadata=overlay_metadata("threshold-midpoint", {
                        "end": label_text,
                        "description": "内水平面以此点为圆心绘制半圆弧。",
                    }),
                )
            )

        return surfaces

    SYMMETRIC_SURFACE_IDS = {
        "runway-area",
        "runway-protection-surface",
        "mh5001-inner-horizontal",
        "mh5001-conical",
        "mh5001-conical-inner-edge",
        "runway-centerline",
        "threshold-midpoint-primary",
        "threshold-midpoint-reciprocal",
    }

    def _merge_bidirectional_surfaces(
        self,
        primary: List[GeometryOverlay],
        reciprocal: List[GeometryOverlay],
    ) -> List[GeometryOverlay]:
        merged: List[GeometryOverlay] = []
        reciprocal_ids_seen: set = set()

        for surface in primary:
            merged.append(surface)

        for surface in reciprocal:
            if surface.id in self.SYMMETRIC_SURFACE_IDS:
                continue
            reciprocal_surface = surface.model_copy(update={
                "id": f"{surface.id}-reciprocal",
                "label": f"{surface.label} (反向)",
            })
            merged.append(reciprocal_surface)

        return merged

    # --- 进近面分段点的辅助方法 ---
    def _approach_segment_points(
        self, segments: List[Dict[str, Any]], seg_idx: int
    ) -> List[LocalPoint]:
        """计算第 seg_idx 段进近面的四个角点（在世界坐标系中的梯形）。"""
        first = segments[0]
        start_x = -float(first["distanceFromThresholdM"])
        start_hw = float(first["innerEdgeWidthM"]) / 2

        # 累积计算起点位置
        for i in range(seg_idx):
            s = segments[i]
            sl = float(s["lengthM"])
            sd = float(s["divergenceEachSide"])
            start_x -= sl
            start_hw += sl * sd

        seg = segments[seg_idx]
        seg_len = float(seg["lengthM"])
        seg_div = float(seg["divergenceEachSide"])
        end_x = start_x - seg_len
        end_hw = start_hw + seg_len * seg_div
        return [
            (start_x, -start_hw),
            (start_x, start_hw),
            (end_x, end_hw),
            (end_x, -end_hw),
        ]

    # --- 起飞爬升面 ---
    def _takeoff_climb_points(
        self, runway_len: float, takeoff: Dict[str, Any]
    ) -> List[LocalPoint]:
        """起飞爬升面梯形 (表5.2.7)"""
        inner_hw = float(takeoff["innerEdgeWidthM"]) / 2
        dist = float(takeoff["distanceFromRunwayEndM"])
        length = float(takeoff["lengthM"])
        div = float(takeoff["divergenceEachSide"])
        final_hw = float(takeoff["finalWidthM"]) / 2
        start_x = runway_len + dist
        end_x = start_x + length
        outer_hw = min(inner_hw + length * div, final_hw)
        return [
            (start_x, -inner_hw),
            (end_x, -outer_hw),
            (end_x, outer_hw),
            (start_x, inner_hw),
        ]

    # --- 多段进近面 ---
    def _approach_surface_points_multi(self, segments: List[Dict[str, Any]]) -> List[List[LocalPoint]]:
        """为多段进近面计算各段的LocalPoint。返回列表中每个元素对应一段。"""
        result: List[List[LocalPoint]] = []
        # 第一段从内边开始
        first = segments[0]
        inner_half_width = float(first["innerEdgeWidthM"]) / 2
        dist_from_threshold = float(first["distanceFromThresholdM"])
        inner_x = -dist_from_threshold
        current_outer_hw = inner_half_width
        current_outer_x = inner_x

        for seg in segments:
            seg_len = float(seg["lengthM"])
            divergence = float(seg["divergenceEachSide"])
            seg_inner_x = current_outer_x
            seg_outer_x = seg_inner_x - seg_len
            seg_inner_hw = current_outer_hw
            seg_outer_hw = seg_inner_hw + seg_len * divergence
            result.append([
                (seg_inner_x, -seg_inner_hw),
                (seg_inner_x, seg_inner_hw),
                (seg_outer_x, seg_outer_hw),
                (seg_outer_x, -seg_outer_hw),
            ])
            current_outer_x = seg_outer_x
            current_outer_hw = seg_outer_hw

        return result

    def _approach_surface_points(self, approach: Dict[str, Any]) -> List[LocalPoint]:
        """单段进近面（向后兼容）。"""
        inner_half_width = float(approach["innerEdgeWidthM"]) / 2
        distance = float(approach["distanceFromThresholdM"])
        length = float(approach["lengthM"])
        divergence = float(approach["divergenceEachSide"])
        inner_x = -distance
        outer_x = inner_x - length
        outer_half_width = inner_half_width + length * divergence
        return [
            (inner_x, -inner_half_width),
            (inner_x, inner_half_width),
            (outer_x, outer_half_width),
            (outer_x, -outer_half_width),
        ]

    # --- 内进近面（精密进近） ---
    def _inner_approach_surface_points(self, ia: Dict[str, Any]) -> List[LocalPoint]:
        """5.1.5 内进近面：紧靠跑道入口前的长方形，不散开。"""
        half_width = float(ia["innerEdgeWidthM"]) / 2
        distance = float(ia["distanceFromThresholdM"])
        length = float(ia["lengthM"])
        inner_x = -distance
        outer_x = inner_x - length
        return [
            (inner_x, -half_width),
            (inner_x, half_width),
            (outer_x, half_width),
            (outer_x, -half_width),
        ]

    # --- 复飞面（精密进近） ---
    def _balked_landing_surface_points(self, runway_len: float, bl: Dict[str, Any]) -> List[LocalPoint]:
        """5.1.8 复飞面：跑道入口后方，两侧散开直到内水平面。"""
        half_width = float(bl["innerEdgeWidthM"]) / 2
        distance = float(bl["distanceFromThresholdM"])
        divergence = float(bl["divergenceEachSide"])
        inner_x = distance  # 入口后方
        inner_horizontal_height = 45.0
        bl_slope = float(bl["slopePercent"]) / 100.0
        length = inner_horizontal_height / bl_slope if bl_slope > 0 else 10000
        outer_x = inner_x + length
        outer_hw = half_width + length * divergence
        return [
            (inner_x, -half_width),
            (inner_x, half_width),
            (outer_x, outer_hw),
            (outer_x, -outer_hw),
        ]

    # --- 起飞爬升面（支持最终宽度限制） ---
    def _takeoff_climb_surface_points_v2(
        self,
        runway_length: float,
        takeoff: Dict[str, Any],
        forward: bool,
    ) -> List[LocalPoint]:
        inner_half_width = float(takeoff["innerEdgeWidthM"]) / 2
        distance = float(takeoff["distanceFromRunwayEndM"])
        length = float(takeoff["lengthM"])
        divergence = float(takeoff["divergenceEachSide"])
        final_half_width = float(takeoff["finalWidthM"]) / 2
        start_x = runway_length + distance if forward else -distance
        end_x = start_x + length if forward else start_x - length
        outer_half_width = min(inner_half_width + length * divergence, final_half_width)
        return [
            (start_x, -inner_half_width),
            (end_x, -outer_half_width),
            (end_x, outer_half_width),
            (start_x, inner_half_width),
        ]

    def _takeoff_climb_surface_points(
        self,
        runway_length: float,
        takeoff: Dict[str, Any],
        forward: bool,
    ) -> List[LocalPoint]:
        """向后兼容。"""
        return self._takeoff_climb_surface_points_v2(runway_length, takeoff, forward)

    # --- 双向范围点（多段进近面版本） ---
    def _bidirectional_ols_scope_points_v2(
        self,
        runway_length: float,
        approach_segments: List[Dict[str, Any]],
        takeoff: Dict[str, Any],
    ) -> List[LocalPoint]:
        all_sections = self._approach_surface_points_multi(approach_segments)
        primary_approach_pts = [pt for sec in all_sections for pt in sec]
        primary_takeoff = self._takeoff_climb_surface_points_v2(runway_length, takeoff, forward=True)

        reciprocal_approach_pts: List[LocalPoint] = [
            (runway_length - x, y) for sec in all_sections for x, y in sec
        ]
        reciprocal_takeoff = self._takeoff_climb_surface_points_v2(0, takeoff, forward=False)

        return primary_approach_pts + primary_takeoff + reciprocal_approach_pts + reciprocal_takeoff

    def _bidirectional_ols_scope_points(
        self,
        runway_length: float,
        approach: Dict[str, Any],
        takeoff: Dict[str, Any],
    ) -> List[LocalPoint]:
        """向后兼容（单段进近面）。"""
        primary_approach = self._approach_surface_points(approach)
        primary_takeoff = self._takeoff_climb_surface_points(runway_length, takeoff, forward=True)
        reciprocal_approach = [
            (runway_length - x, y) for x, y in primary_approach
        ]
        reciprocal_takeoff = self._takeoff_climb_surface_points(0, takeoff, forward=False)
        return primary_approach + primary_takeoff + reciprocal_approach + reciprocal_takeoff

    # --- 几何工具 ---
    def _circle_points(self, center: LocalPoint, radius: float, count: int) -> List[LocalPoint]:
        return [
            (
                center[0] + radius * math.cos(2 * math.pi * i / count),
                center[1] + radius * math.sin(2 * math.pi * i / count),
            )
            for i in range(count)
        ]

    def _capsule_points(self, runway_length: float, radius: float, count: int) -> List[LocalPoint]:
        """Generate a runway-axis capsule around both runway ends."""
        half_count = max(8, count // 2)
        points: List[LocalPoint] = []

        for index in range(half_count + 1):
            angle = math.pi / 2 + math.pi * index / half_count
            points.append((radius * math.cos(angle), radius * math.sin(angle)))

        for index in range(half_count + 1):
            angle = -math.pi / 2 + math.pi * index / half_count
            points.append((runway_length + radius * math.cos(angle), radius * math.sin(angle)))

        return points

    def _convex_hull(self, points: List[LocalPoint]) -> List[LocalPoint]:
        unique = sorted(set((round(x, 6), round(y, 6)) for x, y in points))
        if len(unique) <= 1:
            return unique

        def cross(o: LocalPoint, a: LocalPoint, b: LocalPoint) -> float:
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        lower: List[LocalPoint] = []
        for point in unique:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
                lower.pop()
            lower.append(point)

        upper: List[LocalPoint] = []
        for point in reversed(unique):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
                upper.pop()
            upper.append(point)

        return lower[:-1] + upper[:-1]


calculator = TrackCalculator()
