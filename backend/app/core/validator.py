"""Compliance validation module for flight circuit tracks."""
import json
import math
from pathlib import Path
from typing import List

from app.models.runway import RunwayParams, ValidationError, RunwayValidationResult
from app.models.aircraft import Aircraft
from app.models.track import (
    TrackConfig,
    TrackResult,
    TrackSegment,
    ValidationReport,
    TrackValidationError,
    TrackSegmentName,
)


class ComplianceValidator:
    """Compliance validator for flight circuit tracks (航迹合规校验引擎).
    
    Validates track results against:
    - 中国民航《目视飞行程序设计指南》
    - Runway parameters constraints
    - Aircraft performance limits
    """
    
    def __init__(self):
        """Initialize validator."""
        self._load_regulations()
    
    def _load_regulations(self) -> None:
        """Load regulation parameters from JSON file."""
        data_dir = Path(__file__).parent.parent / "data"
        visual_path = data_dir / "visual_procedure_rules.json"
        legacy_path = data_dir / "regulations.json"
        if visual_path.exists():
            with open(visual_path, "r", encoding="utf-8") as f:
                self.regulations = json.load(f)
        elif legacy_path.exists():
            with open(legacy_path, "r", encoding="utf-8") as f:
                self.regulations = json.load(f)
        else:
            self.regulations = {
                "validation_rules": {
                    "runway_length": {"min": 200, "warning_min": 600, "max": 5000},
                    "magnetic_bearing": {"min": 0, "max": 360},
                    "elevation": {"min": -500, "max": 5000},
                },
                "safety_margins": {
                    "runway_clearance": {"min": 50, "recommended": 100},
                    "obstacle_clearance": {"min": 30, "recommended": 50},
                },
                "turn_constraints": {
                    "min_turn_radius": {"light_aircraft": 200, "medium_aircraft": 400},
                },
            }

    def _rule_value(self, rule, default=None):
        if isinstance(rule, dict) and "defaultValue" in rule:
            return rule["defaultValue"]
        return default if rule is None else rule
    
    def validate_runway(self, runway: RunwayParams) -> RunwayValidationResult:
        """Validate runway parameters.
        
        Args:
            runway: Runway parameters to validate
            
        Returns:
            Validation result with errors and warnings
        """
        errors: List[ValidationError] = []
        
        # Validate runway length
        length_rules = self.regulations["validation_rules"]["runway_length"]
        if runway.length < length_rules["min"]:
            errors.append(ValidationError(
                field="length",
                message=f"跑道长度不足：{runway.length}米，最小要求{length_rules['min']}米",
                severity="error",
            ))
        elif runway.length < length_rules["warning_min"]:
            errors.append(ValidationError(
                field="length",
                message=f"跑道长度较短：{runway.length}米，推荐最小{length_rules['warning_min']}米（适合塞斯纳172等机型）",
                severity="warning",
            ))
        
        # Validate magnetic bearing
        bearing_rules = self.regulations["validation_rules"]["magnetic_bearing"]
        if runway.magnetic_bearing < bearing_rules["min"] or runway.magnetic_bearing > bearing_rules["max"]:
            errors.append(ValidationError(
                field="magnetic_bearing",
                message=f"磁方位角无效：{runway.magnetic_bearing}度，应在{bearing_rules['min']}-{bearing_rules['max']}度范围内",
                severity="error",
            ))
        
        # Validate elevation
        elevation_rules = self.regulations["validation_rules"]["elevation"]
        if runway.elevation < elevation_rules["min"]:
            errors.append(ValidationError(
                field="elevation",
                message=f"跑道标高过低：{runway.elevation}米",
                severity="warning",
            ))
        elif runway.elevation > elevation_rules["max"]:
            errors.append(ValidationError(
                field="elevation",
                message=f"跑道标高过高：{runway.elevation}米，超过{elevation_rules['max']}米，需考虑高原机场特殊要求",
                severity="warning",
            ))
        
        # Validate coordinate
        if runway.coordinate.latitude < -90 or runway.coordinate.latitude > 90:
            errors.append(ValidationError(
                field="coordinate.latitude",
                message=f"纬度无效：{runway.coordinate.latitude}度",
                severity="error",
            ))
        if runway.coordinate.longitude < -180 or runway.coordinate.longitude > 180:
            errors.append(ValidationError(
                field="coordinate.longitude",
                message=f"经度无效：{runway.coordinate.longitude}度",
                severity="error",
            ))
        
        is_valid = not any(e.severity == "error" for e in errors)
        
        return RunwayValidationResult(is_valid=is_valid, errors=errors)
    
    def validate(
        self,
        result: TrackResult,
        runway: RunwayParams,
        aircraft: Aircraft,
        config: TrackConfig
    ) -> ValidationReport:
        """Validate complete track result.
        
        Args:
            result: Track result to validate
            runway: Runway parameters
            aircraft: Aircraft parameters
            config: Track configuration
            
        Returns:
            Validation report with errors and warnings
        """
        errors: List[TrackValidationError] = []
        warnings: List[TrackValidationError] = []

        if config.active_runway_end not in {"primary", "reciprocal"}:
            errors.append(TrackValidationError(
                code="ACTIVE_RUNWAY_END_INVALID",
                message="使用跑道入口必须为 primary 或 reciprocal",
                severity="error",
            ))

        if config.traffic_pattern_side not in {"left", "right"}:
            errors.append(TrackValidationError(
                code="TRAFFIC_PATTERN_SIDE_INVALID",
                message="目视起落航线方向必须为 left 或 right",
                severity="error",
            ))

        if aircraft.vfr_pattern_class not in self.regulations.get("vfr_pattern_classes", {}):
            errors.append(TrackValidationError(
                code="AIRCRAFT_VFR_CLASS_MISSING",
                message=f"机型 {aircraft.id} 缺少可用的目视起落航线规范类别",
                severity="error",
            ))

        if aircraft.cruise_speed > aircraft.vfr_max_ias_kmh:
            warnings.append(TrackValidationError(
                code="VFR_IAS_EXCEEDED",
                message=f"机型巡航速度 {aircraft.cruise_speed} km/h 高于程序最大IAS {aircraft.vfr_max_ias_kmh} km/h，计算按程序限制速度估算时间",
                severity="warning",
            ))

        if len(result.key_points) == 0:
            errors.append(TrackValidationError(
                code="KEY_POINTS_MISSING",
                message="目视起落航线关键点未生成",
                severity="error",
            ))

        if len(result.surfaces) == 0:
            errors.append(TrackValidationError(
                code="SURFACES_MISSING",
                message="障碍物限制面未生成",
                severity="error",
            ))
        else:
            for surface in result.surfaces:
                if surface.kind == "polygon" and len(surface.coordinates) < 3:
                    errors.append(TrackValidationError(
                        code="SURFACE_GEOMETRY_INVALID",
                        message=f"{surface.label} 几何坐标不足，无法绘制面",
                        severity="error",
                    ))

        for airspace in getattr(result, "airspaces", []):
            if airspace.kind == "polygon" and len(airspace.coordinates) < 3:
                errors.append(TrackValidationError(
                    code="AIRSPACE_GEOMETRY_INVALID",
                    message=f"{airspace.label} 几何坐标不足，无法绘制飞行营地空域",
                    severity="error",
                ))

        if not getattr(result, "compliance", []):
            warnings.append(TrackValidationError(
                code="COMPLIANCE_HINTS_MISSING",
                message="规范校验提示未生成",
                severity="warning",
            ))

        visual_rules = self.regulations.get("visual_procedure", {})
        minimum_straight_leg = float(self._rule_value(visual_rules.get("minimum_straight_leg_m"), 500))
        first_turn_radius = self._first_turn_radius(result)
        active_turn_radius = float(config.turn_radius or first_turn_radius or 0)

        if config.turn_radius is not None:
            calculated_radius = self._calculate_turn_radius(aircraft.approach_speed, config.bank_angle)
            required_radius = max(float(aircraft.turn_radius), calculated_radius)
            if config.turn_radius < required_radius:
                errors.append(TrackValidationError(
                    code="CUSTOM_TURN_RADIUS_TOO_SMALL",
                    message=(
                        f"配置转弯半径 {config.turn_radius:.0f} 米小于机型/坡度计算要求 "
                        f"{required_radius:.0f} 米"
                    ),
                    severity="error",
                ))

        if config.downwind_offset is not None and active_turn_radius:
            minimum_offset = 2 * active_turn_radius
            if config.downwind_offset < minimum_offset:
                errors.append(TrackValidationError(
                    code="DOWNWIND_OFFSET_TOO_SMALL",
                    message=(
                        f"一边与三边间隔 {config.downwind_offset:.0f} 米小于 2 倍转弯半径 "
                        f"{minimum_offset:.0f} 米，航线会自交或生成反向二/四边"
                    ),
                    severity="error",
                ))

        for field_name, value, label in [
            ("departure_leg_length", config.departure_leg_length, "一边长度"),
            ("final_leg_length", config.final_leg_length, "五边长度"),
        ]:
            if value is not None and value < minimum_straight_leg:
                warnings.append(TrackValidationError(
                    code=f"{field_name.upper()}_SHORT",
                    message=f"{label} {value:.0f} 米低于建议最小直线段 {minimum_straight_leg:.0f} 米",
                    severity="warning",
                ))
        
        # Check turn radius constraints
        min_turn_radius = self.regulations["turn_constraints"]["min_turn_radius"].get(
            aircraft.category, 200
        )
        
        for segment in result.segments:
            if segment.name.startswith("turn_"):
                # Check turn radius (indicated by path_points presence)
                if segment.path_points:
                    # Estimate actual turn radius from arc
                    if len(segment.path_points) >= 3:
                        actual_radius = self._estimate_arc_radius(segment.path_points)
                        if actual_radius < min_turn_radius:
                            errors.append(TrackValidationError(
                                code="TURN_RADIUS_TOO_SMALL",
                                message=f"转弯半径过小：约{actual_radius}米，{aircraft.category}类飞机最小要求{min_turn_radius}米",
                                segment=segment.name,
                                severity="error",
                            ))
        
        # Check altitude constraints
        circuit_height = runway.elevation + config.circuit_height
        
        for segment in result.segments:
            # Check altitude is reasonable
            if segment.altitude < runway.elevation + 15:
                # Below minimum safe altitude
                if segment.name != "final_approach":
                    warnings.append(TrackValidationError(
                        code="LOW_ALTITUDE",
                        message=f"{segment.name_cn}高度过低：{segment.altitude - runway.elevation}米（相对跑道）",
                        segment=segment.name,
                        severity="warning",
                    ))
            
            # Check altitude doesn't exceed aircraft max
            if segment.altitude > aircraft.max_altitude:
                errors.append(TrackValidationError(
                    code="ALTITUDE_EXCEEDS_MAX",
                    message=f"{segment.name_cn}高度超出机型限制：{segment.altitude}米 > {aircraft.max_altitude}米",
                    segment=segment.name,
                    severity="error",
                ))
        
        # Check circuit height configuration
        height_limits = self.regulations["standard_circuit_heights"].get(
            aircraft.category,
            self.regulations["standard_circuit_heights"]["light"]
        )
        
        if config.circuit_height < height_limits["min"]:
            warnings.append(TrackValidationError(
                code="CIRCUIT_HEIGHT_LOW",
                message=f"起落航线高度偏低：{config.circuit_height}米，推荐{height_limits['recommended']}米",
                severity="warning",
            ))
        elif config.circuit_height > height_limits["max"]:
            warnings.append(TrackValidationError(
                code="CIRCUIT_HEIGHT_HIGH",
                message=f"起落航线高度偏高：{config.circuit_height}米，超过{height_limits['max']}米",
                severity="warning",
            ))
        
        # Check bank angle
        bank_limits = self.regulations["bank_angle_limits"]["visual_flight"]
        if config.bank_angle < bank_limits["min"]:
            errors.append(TrackValidationError(
                code="BANK_ANGLE_TOO_SMALL",
                message=f"转弯坡度过小：{config.bank_angle}度，最小{bank_limits['min']}度",
                severity="error",
            ))
        elif config.bank_angle > bank_limits["max"]:
            errors.append(TrackValidationError(
                code="BANK_ANGLE_TOO_LARGE",
                message=f"转弯坡度过大：{config.bank_angle}度，目视飞行最大{bank_limits['max']}度",
                severity="error",
            ))
        
        # Check runway length for aircraft
        if runway.length < 600 and aircraft.category == "light":
            runway_validation = self.validate_runway(runway)
            for err in runway_validation.errors:
                if err.severity == "warning":
                    warnings.append(TrackValidationError(
                        code="RUNWAY_LENGTH_WARNING",
                        message=err.message,
                        severity="warning",
                    ))
                elif err.severity == "error":
                    errors.append(TrackValidationError(
                        code="RUNWAY_LENGTH_ERROR",
                        message=err.message,
                        severity="error",
                    ))
        
        is_valid = len(errors) == 0
        
        return ValidationReport(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
        )

    def _calculate_turn_radius(self, speed_km_h: float, bank_angle_deg: float) -> float:
        """Calculate coordinated turn radius from speed and bank angle."""
        speed_m_s = speed_km_h * 1000 / 3600
        bank_angle_rad = math.radians(bank_angle_deg)
        return (speed_m_s**2) / (9.81 * math.tan(bank_angle_rad))

    def _first_turn_radius(self, result: TrackResult) -> float:
        """Estimate the first generated turn radius in meters."""
        for segment in result.segments:
            if segment.name.startswith("turn_") and segment.path_points:
                return self._estimate_arc_radius(segment.path_points)
        return 0.0
    
    def _estimate_arc_radius(self, points: List) -> float:
        """Estimate arc radius from three points on arc.
        
        Args:
            points: List of coordinate points on arc
            
        Returns:
            Estimated radius in meters
        """
        if len(points) < 3:
            return 0.0
        
        import math
        
        # Use first, middle, and last points
        p1 = points[0]
        p2 = points[len(points) // 2]
        p3 = points[-1]
        
        # Convert to local coordinates (approximate)
        # Using first point as origin
        lat0, lon0 = p1.latitude, p1.longitude
        
        # Approximate conversion: 1 degree ~ 111km
        x1 = 0.0
        y1 = 0.0
        
        x2 = (p2.longitude - lon0) * 111000 * math.cos(math.radians(lat0))
        y2 = (p2.latitude - lat0) * 111000
        
        x3 = (p3.longitude - lon0) * 111000 * math.cos(math.radians(lat0))
        y3 = (p3.latitude - lat0) * 111000
        
        # Calculate circle radius from three points
        # Using formula: R = |AB| * |BC| * |CA| / (4 * Area)
        # where Area = 0.5 * |(x2-x1)*(y3-y1) - (x3-x1)*(y2-y1)|
        
        def dist(p1, p2):
            return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)
        
        a = dist((x1, y1), (x2, y2))
        b = dist((x2, y2), (x3, y3))
        c = dist((x3, y3), (x1, y1))
        
        area = abs(0.5 * ((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)))
        
        if area < 1:  # Nearly collinear
            return max(a, b, c) / 2
        
        radius = (a * b * c) / (4 * area)
        
        return round(abs(radius), 1)


# Global validator instance
validator = ComplianceValidator()
