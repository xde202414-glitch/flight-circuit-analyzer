"""Test flight circuit track calculation engine."""
import pytest
import math
from app.core.calculator import TrackCalculator, calculator
from app.models.runway import RunwayParams, Coordinate
from app.models.aircraft import Aircraft
from app.models.track import TrackConfig


class TestTrackCalculator:
    """Test suite for track calculator."""

    def test_calculate_turn_radius_standard(self):
        """Test turn radius calculation with standard parameters."""
        speed_km_h = 150.0  # km/h
        bank_angle_deg = 15.0  # degrees

        radius = calculator.calculate_turn_radius(speed_km_h, bank_angle_deg)

        # Expected radius using formula R = V^2 / (g * tan(bank_angle))
        # V = 150 km/h = 41.67 m/s
        # bank_angle = 15 degrees
        # R = (41.67^2) / (9.81 * tan(15)) = 1736.11 / 2.63 = 661.6 meters
        expected_radius = 661.6

        assert radius > 0.0
        assert abs(radius - expected_radius) < 100.0  # Allow tolerance

    def test_calculate_turn_radius_high_speed(self):
        """Test turn radius calculation with high speed."""
        speed_km_h = 300.0  # km/h
        bank_angle_deg = 20.0  # degrees

        radius = calculator.calculate_turn_radius(speed_km_h, bank_angle_deg)

        # Higher speed should result in larger radius
        assert radius > 500.0

    def test_calculate_turn_radius_large_bank_angle(self):
        """Test turn radius calculation with large bank angle."""
        speed_km_h = 150.0  # km/h
        bank_angle_deg = 30.0  # degrees (maximum for visual flight)

        radius = calculator.calculate_turn_radius(speed_km_h, bank_angle_deg)

        # Larger bank angle should result in smaller radius
        radius_15 = calculator.calculate_turn_radius(speed_km_h, 15.0)
        assert radius < radius_15

    def test_calculate_circuit_complete(self):
        """Test complete circuit calculation."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            engine_type="piston",
        )

        config = TrackConfig(
            circuit_height=300,
            bank_angle=15,
            magnetic_variation=0.0,
        )

        result = calculator.calculate_circuit(runway, aircraft, config)

        # Should generate 9 segments
        assert len(result.segments) == 9

        # Should have total distance
        assert result.total_distance > 0.0

        # Should have estimated time
        assert result.estimated_time > 0.0

        # Should have validation report
        assert result.validation_report is not None

    def test_calculate_circuit_segment_names(self):
        """Test that all segments have correct names."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        expected_names = [
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

        actual_names = [seg.name for seg in result.segments]

        assert actual_names == expected_names

    def test_calculate_circuit_segment_chinese_names(self):
        """Test that all segments have correct Chinese names."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        expected_cn_names = [
            "起飞航段",
            "一转弯",
            "二边",
            "二转弯",
            "三边",
            "三转弯",
            "四边",
            "四转弯",
            "五边",
        ]

        actual_cn_names = [seg.name_cn for seg in result.segments]

        assert actual_cn_names == expected_cn_names

    def test_calculate_circuit_departure_segment(self):
        """Test departure segment properties."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        departure = result.segments[0]

        assert departure.name == "departure"
        assert departure.name_cn == "起飞航段"
        assert departure.heading == 180.0  # Same as runway bearing
        assert departure.altitude > runway.elevation  # Should be climbing
        assert departure.distance > 0.0

    def test_calculate_circuit_turn_segments_have_path_points(self):
        """Test that turn segments have arc path points."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        # Turn segments (turn_1, turn_2, turn_3, turn_4) should have path_points
        turn_segments = [seg for seg in result.segments if seg.name.startswith("turn_")]

        assert len(turn_segments) == 4

        for turn_seg in turn_segments:
            assert turn_seg.path_points is not None
            assert len(turn_seg.path_points) > 0  # Should have arc points

    def test_calculate_circuit_leg_segments_no_path_points(self):
        """Test that leg segments don't have path points."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        # Leg segments should not have path_points (straight line)
        leg_segments = [
            seg for seg in result.segments
            if not seg.name.startswith("turn_") and seg.name != "departure"
        ]

        for leg_seg in leg_segments:
            # These should be straight segments, path_points might be None
            assert leg_seg.path_points is None or len(leg_seg.path_points) == 0

    def test_calculate_circuit_headings_sequence(self):
        """Test that headings follow expected pattern."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,  # South direction
            length=800,
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        # Standard left-hand pattern: heading should turn left by 90 degrees at each turn
        # Starting at 180 (south), should go to: 90 (east), 0 (north), 270 (west), 180 (south)

        headings = [seg.heading for seg in result.segments]

        # Departure: 180 (south)
        assert headings[0] == 180.0

        # After turn_1: should be approximately 90 (east) for crosswind leg
        assert abs(headings[2] - 90.0) < 5.0

        # After turn_2: should be approximately 0 (north) for downwind leg
        assert abs(headings[4] - 0.0) < 5.0 or abs(headings[4] - 360.0) < 5.0

        # After turn_3: should be approximately 270 (west) for base leg
        assert abs(headings[6] - 270.0) < 5.0

    def test_calculate_circuit_altitude_progression(self):
        """Test altitude progression through circuit."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        # Should start at runway elevation and climb to circuit height
        departure_alt = result.segments[0].altitude
        assert departure_alt > runway.elevation

        # Should reach circuit height during downwind leg
        downwind_alt = result.segments[4].altitude
        expected_circuit_alt = runway.elevation + config.circuit_height
        assert abs(downwind_alt - expected_circuit_alt) < 10.0

        # Should start descent during base leg
        base_alt = result.segments[6].altitude
        assert base_alt < downwind_alt

        # Final approach should be low
        final_alt = result.segments[8].altitude
        assert final_alt < base_alt

    def test_calculate_circuit_different_bearings(self):
        """Test circuit calculation with different runway bearings."""
        for bearing in [0.0, 90.0, 180.0, 270.0]:
            runway = RunwayParams(
                coordinate=Coordinate(latitude=39.9, longitude=116.4),
                magnetic_bearing=bearing,
                length=800,
                elevation=50,
            )

            aircraft = Aircraft(
                id="cessna172",
                name="Cessna 172",
                manufacturer="Cessna",
                cruise_speed=222,
                climb_rate=3.5,
                turn_radius=350,
                approach_speed=130,
                max_altitude=4300,
                stall_speed=93,
                category="light",
            )

            config = TrackConfig(circuit_height=300, bank_angle=15)

            result = calculator.calculate_circuit(runway, aircraft, config)

            # Should generate 9 segments for any bearing
            assert len(result.segments) == 9

            # Departure heading should match runway bearing
            assert result.segments[0].heading == bearing

    def test_calculate_circuit_magnetic_variation(self):
        """Test circuit calculation with magnetic variation."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(
            circuit_height=300,
            bank_angle=15,
            magnetic_variation=5.0  # 5 degrees variation
        )

        result = calculator.calculate_circuit(runway, aircraft, config)

        # Should still generate valid circuit
        assert len(result.segments) == 9

        # Heading should be adjusted for magnetic variation
        adjusted_bearing = (180.0 - 5.0 + 360) % 360
        assert result.segments[0].heading == adjusted_bearing

    def test_calculate_circuit_turn_distance(self):
        """Test that turn segments have correct arc distance."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        # Turn distance should be arc length for 90-degree turn
        # Arc length = (pi * radius) / 2 for 90 degrees

        turn_segments = [seg for seg in result.segments if seg.name.startswith("turn_")]

        # Get actual turn radius used
        turn_radius = calculator.calculate_turn_radius(aircraft.approach_speed, config.bank_angle)
        if aircraft.turn_radius > turn_radius:
            turn_radius = aircraft.turn_radius

        expected_arc_distance = math.pi * turn_radius / 2

        for turn_seg in turn_segments:
            # Allow tolerance due to approximation
            assert abs(turn_seg.distance - expected_arc_distance) < 50.0

    def test_calculate_circuit_validation(self):
        """Test that circuit calculation includes validation."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        # Validation report should be present
        assert result.validation_report is not None
        assert hasattr(result.validation_report, 'is_valid')
        assert hasattr(result.validation_report, 'errors')
        assert hasattr(result.validation_report, 'warnings')

    def test_calculate_circuit_returns_key_points_and_surfaces(self):
        """Test that visual procedure geometry includes overlays."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )
        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        assert len(result.segments) == 9
        assert len(result.key_points) >= 5
        assert len(result.surfaces) >= 4
        assert len(result.airspaces) >= 1
        assert len(result.compliance) >= 3
        assert len(result.annotations) > 0
        assert all(len(surface.coordinates) >= 3 for surface in result.surfaces)
        assert any(surface.style_key == "ols-envelope" for surface in result.surfaces)
        assert any(surface.style_key == "ols-approach" for surface in result.surfaces)
        assert any(surface.style_key == "ols-takeoff-climb" for surface in result.surfaces)

    def test_decimal_runway_elevation_is_preserved(self):
        """Test runway elevation supports 0.1m precision in calculated altitudes."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=30.204869, longitude=120.816431),
            magnetic_bearing=96.0,
            length=800,
            elevation=10.5,
        )
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )

        result = calculator.calculate_circuit(
            runway,
            aircraft,
            TrackConfig(circuit_height=290),
        )

        assert runway.elevation == 10.5
        assert result.segments[4].altitude == 300.5
        runway_surface = next(surface for surface in result.surfaces if surface.style_key == "runway-surface")
        assert runway_surface.altitude == 10.5

    def test_bidirectional_envelope_is_generated_for_both_runway_ends(self):
        """Test obstacle envelope covers both runway directions and is stable across active ends."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=30.204869, longitude=120.816431),
            magnetic_bearing=96.0,
            length=800,
            elevation=10.5,
        )
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )

        primary = calculator.calculate_circuit(
            runway,
            aircraft,
            TrackConfig(active_runway_end="primary"),
        )
        reciprocal = calculator.calculate_circuit(
            runway,
            aircraft,
            TrackConfig(active_runway_end="reciprocal"),
        )

        primary_envelope = next(surface for surface in primary.surfaces if surface.style_key == "ols-envelope")
        reciprocal_envelope = next(surface for surface in reciprocal.surfaces if surface.style_key == "ols-envelope")

        assert primary_envelope.id == "mh5001-bidirectional-envelope"
        assert len(primary_envelope.coordinates) >= 4
        assert len(reciprocal_envelope.coordinates) >= 4
        assert primary_envelope.altitude == reciprocal_envelope.altitude

        primary_lats = [point.latitude for point in primary_envelope.coordinates]
        reciprocal_lats = [point.latitude for point in reciprocal_envelope.coordinates]
        primary_lons = [point.longitude for point in primary_envelope.coordinates]
        reciprocal_lons = [point.longitude for point in reciprocal_envelope.coordinates]

        assert abs(min(primary_lats) - min(reciprocal_lats)) < 0.0001
        assert abs(max(primary_lats) - max(reciprocal_lats)) < 0.0001
        assert abs(min(primary_lons) - min(reciprocal_lons)) < 0.0001
        assert abs(max(primary_lons) - max(reciprocal_lons)) < 0.0001

    def test_ols_capsule_surfaces_expand_with_runway_length(self):
        """Test inner horizontal, conical, and envelope surfaces expand with runway length."""
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )

        def calculate(length: int):
            runway = RunwayParams(
                coordinate=Coordinate(latitude=30.204869, longitude=120.816431),
                magnetic_bearing=90.0,
                length=length,
                elevation=10.5,
            )
            return calculator.calculate_circuit(
                runway,
                aircraft,
                TrackConfig(circuit_height=300, bank_angle=15),
            )

        def longitude_span(result, style_key: str) -> float:
            surface = next(surface for surface in result.surfaces if surface.style_key == style_key)
            longitudes = [point.longitude for point in surface.coordinates]
            return max(longitudes) - min(longitudes)

        results = [calculate(length) for length in [600, 1200, 2000]]

        for style_key in ["ols-inner-horizontal", "ols-conical", "ols-envelope"]:
            spans = [longitude_span(result, style_key) for result in results]
            assert spans[0] < spans[1] < spans[2]

        approach_spans = [longitude_span(result, "ols-approach") for result in results]
        assert max(approach_spans) - min(approach_spans) < 0.00001

    def test_geometry_preview_matches_automatic_calculation(self):
        """Test preview values use the same automatic rules as calculation."""
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )

        preview = calculator.resolve_geometry_parameters(
            aircraft,
            TrackConfig(circuit_height=300, bank_angle=15),
        )

        assert preview.departure_leg_length.source == "auto"
        assert preview.departure_leg_length.automatic_value == 2000
        assert preview.final_leg_length.source == "auto"
        assert preview.turn_radius.source == "auto"
        assert preview.downwind_offset.source == "auto"
        assert preview.departure_leg_length.value == 2000
        assert preview.final_leg_length.value == 2600

    def test_geometry_preview_marks_custom_values(self):
        """Test preview reports user-specified geometry values as custom."""
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )

        preview = calculator.resolve_geometry_parameters(
            aircraft,
            TrackConfig(
                departure_leg_length=2700,
                final_leg_length=2700,
                turn_radius=1400,
                downwind_offset=2800,
            ),
        )

        assert preview.departure_leg_length.value == 2700
        assert preview.departure_leg_length.automatic_value == 2000
        assert preview.departure_leg_length.source == "custom"
        assert preview.final_leg_length.source == "custom"
        assert preview.turn_radius.source == "custom"
        assert preview.downwind_offset.source == "custom"

    def test_custom_report_style_geometry_parameters(self):
        """Test user-specified report-style distances and turn radius."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=30.204869, longitude=120.816431),
            magnetic_bearing=96.0,
            length=800,
            elevation=10,
        )
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )

        result = calculator.calculate_circuit(
            runway,
            aircraft,
            TrackConfig(
                circuit_height=300,
                bank_angle=15,
                departure_leg_length=2700,
                final_leg_length=2700,
                turn_radius=1400,
                downwind_offset=2800,
            ),
        )

        assert result.validation_report.is_valid
        assert result.segments[0].distance == 2700
        assert result.segments[-1].distance == 2700
        assert result.segments[1].distance == round(math.pi * 1400 / 2, 1)
        assert result.segments[2].distance == 0
        assert result.segments[6].distance == 0

    def test_segments_include_climb_and_descent_angles(self):
        """Test each segment includes a calculated climb/descent angle."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=30.204869, longitude=120.816431),
            magnetic_bearing=96.0,
            length=800,
            elevation=10.5,
        )
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )

        result = calculator.calculate_circuit(
            runway,
            aircraft,
            TrackConfig(
                circuit_height=290,
                bank_angle=15,
                departure_leg_length=2700,
                final_leg_length=2700,
                turn_radius=1400,
                downwind_offset=2800,
            ),
        )

        assert all(hasattr(segment, "vertical_angle") for segment in result.segments)
        assert result.segments[0].vertical_angle > 0
        assert result.segments[-1].vertical_angle < 0
        assert result.segments[4].vertical_angle == 0

    def test_report_style_annotations_include_lengths_heights_and_performance(self):
        """Test report-style annotations include key procedure parameters."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=30.204869, longitude=120.816431),
            magnetic_bearing=96.0,
            length=800,
            elevation=10.5,
        )
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )

        result = calculator.calculate_circuit(
            runway,
            aircraft,
            TrackConfig(
                circuit_height=290,
                bank_angle=15,
                departure_leg_length=2700,
                final_leg_length=2700,
                turn_radius=1400,
                downwind_offset=2800,
            ),
        )

        annotation_text = "\n".join(
            line
            for annotation in result.annotations
            for line in annotation.lines
        )

        assert "一边 2.7km" in annotation_text
        assert "五边 2.7km" in annotation_text
        assert "R=1.4km" in annotation_text
        assert "QNH300.5m" in annotation_text
        assert "爬升率 3.5m/s" in annotation_text
        assert "爬升角 +" in annotation_text
        assert "下降角 -" in annotation_text
        assert "平飞 0.0°" in annotation_text
        assert all("二边 0m" not in "\n".join(annotation.lines) for annotation in result.annotations)
        assert all("四边 0m" not in "\n".join(annotation.lines) for annotation in result.annotations)
        assert all(-90 <= annotation.coordinate.latitude <= 90 for annotation in result.annotations)
        assert all(-180 <= annotation.coordinate.longitude <= 180 for annotation in result.annotations)

    def test_custom_downwind_offset_must_fit_turn_radius(self):
        """Test invalid custom spacing reports a clear validation error."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=30.204869, longitude=120.816431),
            magnetic_bearing=96.0,
            length=800,
            elevation=10,
        )
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )

        result = calculator.calculate_circuit(
            runway,
            aircraft,
            TrackConfig(turn_radius=1400, downwind_offset=2000),
        )

        assert not result.validation_report.is_valid
        assert any(
            error.code == "DOWNWIND_OFFSET_TOO_SMALL"
            for error in result.validation_report.errors
        )

    def test_left_and_right_patterns_are_on_opposite_sides(self):
        """Test left and right patterns mirror across the runway axis."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=0.0,
            length=800,
            elevation=50,
        )
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )

        left = calculator.calculate_circuit(
            runway,
            aircraft,
            TrackConfig(circuit_height=300, bank_angle=15, traffic_pattern_side="left"),
        )
        right = calculator.calculate_circuit(
            runway,
            aircraft,
            TrackConfig(circuit_height=300, bank_angle=15, traffic_pattern_side="right"),
        )

        threshold_lon = left.key_points[0].coordinates[0].longitude
        left_downwind_lon = left.key_points[2].coordinates[0].longitude
        right_downwind_lon = right.key_points[2].coordinates[0].longitude

        assert left_downwind_lon < threshold_lon
        assert right_downwind_lon > threshold_lon

    def test_primary_and_reciprocal_use_opposite_thresholds(self):
        """Test active runway end changes the origin threshold."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=0.0,
            length=800,
            elevation=50,
        )
        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
            vfr_pattern_class="B",
            vfr_max_ias_kmh=250,
        )

        primary = calculator.calculate_circuit(
            runway,
            aircraft,
            TrackConfig(circuit_height=300, bank_angle=15, active_runway_end="primary"),
        )
        reciprocal = calculator.calculate_circuit(
            runway,
            aircraft,
            TrackConfig(circuit_height=300, bank_angle=15, active_runway_end="reciprocal"),
        )

        primary_threshold = primary.key_points[0].coordinates[0]
        reciprocal_threshold = reciprocal.key_points[0].coordinates[0]

        assert primary_threshold.latitude < runway.coordinate.latitude
        assert reciprocal_threshold.latitude > runway.coordinate.latitude

    def test_regulations_loading(self):
        """Test that regulations are loaded."""
        assert calculator.regulations is not None
        assert "circuit_leg_distances" in calculator.regulations
        assert "turn_constraints" in calculator.regulations


class TestCalculatorEdgeCases:
    """Edge case tests for calculator."""

    def test_minimum_runway_length(self):
        """Test circuit with minimum runway length."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=600,  # Minimum recommended for light aircraft
            elevation=50,
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        # Should still generate valid circuit
        assert len(result.segments) == 9

    def test_high_elevation(self):
        """Test circuit with high elevation runway."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=3000,  # High altitude airport
        )

        aircraft = Aircraft(
            id="cessna172",
            name="Cessna 172",
            manufacturer="Cessna",
            cruise_speed=222,
            climb_rate=3.5,
            turn_radius=350,
            approach_speed=130,
            max_altitude=4300,
            stall_speed=93,
            category="light",
        )

        config = TrackConfig(circuit_height=300, bank_angle=15)

        result = calculator.calculate_circuit(runway, aircraft, config)

        # Should generate circuit considering high elevation
        assert len(result.segments) == 9
        # Circuit altitude should be relative to runway elevation
        expected_circuit_alt = runway.elevation + config.circuit_height
        assert abs(result.segments[4].altitude - expected_circuit_alt) < 10.0

    def test_different_aircraft_types(self):
        """Test circuit with different aircraft categories."""
        runway = RunwayParams(
            coordinate=Coordinate(latitude=39.9, longitude=116.4),
            magnetic_bearing=180.0,
            length=800,
            elevation=50,
        )

        # Test with medium aircraft
        aircraft = Aircraft(
            id="test_medium",
            name="Test Medium",
            manufacturer="Test",
            cruise_speed=300,
            climb_rate=5.0,
            turn_radius=500,
            approach_speed=180,
            max_altitude=8000,
            stall_speed=120,
            category="medium",
        )

        config = TrackConfig(circuit_height=400, bank_angle=20)

        result = calculator.calculate_circuit(runway, aircraft, config)

        # Should generate circuit for medium aircraft
        assert len(result.segments) == 9
        # Larger aircraft should have larger turn radius
        # Turn distances should be larger
        turn_segments = [seg for seg in result.segments if seg.name.startswith("turn_")]
        assert all(seg.distance > 500.0 for seg in turn_segments)
