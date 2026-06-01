"""Test coordinate transformation module."""
import pytest
import math
from app.core.coordinate import CoordinateTransformer, transformer
from app.models.runway import Coordinate


class TestCoordinateTransformer:
    """Test suite for coordinate transformation engine."""

    def test_is_in_china_valid(self):
        """Test coordinate within China boundary."""
        # Beijing coordinates
        assert transformer.is_in_china(39.9, 116.4) == True
        # Shanghai coordinates
        assert transformer.is_in_china(31.2, 121.5) == True

    def test_is_in_china_outside(self):
        """Test coordinate outside China boundary."""
        # New York coordinates
        assert transformer.is_in_china(40.7, -74.0) == False
        # Tokyo coordinates
        assert transformer.is_in_china(35.7, 139.7) == False
        # Out of range
        assert transformer.is_in_china(0.0, 0.0) == False

    def test_wgs84_to_gcj02_within_china(self):
        """Test WGS84 to GCJ-02 transformation within China."""
        # Beijing WGS84 coordinate
        wgs84_coord = Coordinate(latitude=39.9, longitude=116.4)
        gcj02_coord = transformer.wgs84_to_gcj02(wgs84_coord)

        # GCJ-02 should differ from WGS84 for China coordinates
        assert gcj02_coord.latitude != wgs84_coord.latitude
        assert gcj02_coord.longitude != wgs84_coord.longitude

        # Difference should be small (typically < 0.01 degrees)
        assert abs(gcj02_coord.latitude - wgs84_coord.latitude) < 0.01
        assert abs(gcj02_coord.longitude - wgs84_coord.longitude) < 0.01

    def test_wgs84_to_gcj02_outside_china(self):
        """Test WGS84 to GCJ-02 transformation outside China."""
        # Tokyo WGS84 coordinate (outside China)
        wgs84_coord = Coordinate(latitude=35.7, longitude=139.7)
        gcj02_coord = transformer.wgs84_to_gcj02(wgs84_coord)

        # Should remain unchanged outside China
        assert gcj02_coord.latitude == wgs84_coord.latitude
        assert gcj02_coord.longitude == wgs84_coord.longitude

    def test_gcj02_to_wgs84_roundtrip(self):
        """Test GCJ-02 to WGS84 inverse transformation."""
        # Beijing WGS84 coordinate
        original_wgs84 = Coordinate(latitude=39.9, longitude=116.4)

        # Transform to GCJ-02
        gcj02 = transformer.wgs84_to_gcj02(original_wgs84)

        # Transform back to WGS84
        recovered_wgs84 = transformer.gcj02_to_wgs84(gcj02)

        # Should approximately recover original (within ~1m precision)
        distance = transformer.calculate_distance(original_wgs84, recovered_wgs84)
        assert distance < 5.0  # Within 5 meters

    def test_calculate_distance_same_point(self):
        """Test distance calculation for same point."""
        coord = Coordinate(latitude=39.9, longitude=116.4)
        distance = transformer.calculate_distance(coord, coord)
        assert distance == 0.0

    def test_calculate_distance_known_distance(self):
        """Test distance calculation for known distance."""
        # Beijing to Shanghai (~1000 km)
        beijing = Coordinate(latitude=39.9, longitude=116.4)
        shanghai = Coordinate(latitude=31.2, longitude=121.5)

        distance = transformer.calculate_distance(beijing, shanghai)

        # Should be approximately 1000-1200 km
        assert 1000000 < distance < 1200000

    def test_calculate_bearing_north(self):
        """Test bearing calculation for north direction."""
        # Two points along same longitude (north direction)
        coord1 = Coordinate(latitude=39.0, longitude=116.0)
        coord2 = Coordinate(latitude=40.0, longitude=116.0)

        bearing = transformer.calculate_bearing(coord1, coord2)

        # Should be approximately north (0 or 360 degrees)
        assert bearing == 0.0 or abs(bearing - 360.0) < 1.0

    def test_calculate_bearing_east(self):
        """Test bearing calculation for east direction."""
        # Two points along same latitude (east direction)
        coord1 = Coordinate(latitude=39.0, longitude=116.0)
        coord2 = Coordinate(latitude=39.0, longitude=117.0)

        bearing = transformer.calculate_bearing(coord1, coord2)

        # Should be approximately east (90 degrees)
        assert abs(bearing - 90.0) < 2.0

    def test_destination_point_north(self):
        """Test destination point calculation for north direction."""
        start = Coordinate(latitude=39.0, longitude=116.0)
        bearing = 0.0  # North
        distance = 111000.0  # ~1 degree latitude

        destination = transformer.destination_point(start, bearing, distance)

        # Latitude should increase by approximately 1 degree
        assert abs(destination.latitude - 40.0) < 0.1
        # Longitude should remain approximately the same
        assert abs(destination.longitude - start.longitude) < 0.1

    def test_destination_point_east(self):
        """Test destination point calculation for east direction."""
        start = Coordinate(latitude=39.0, longitude=116.0)
        bearing = 90.0  # East
        distance = 111000.0  # ~1 degree longitude at this latitude

        destination = transformer.destination_point(start, bearing, distance)

        # Longitude should increase
        assert destination.longitude > start.longitude
        # Latitude should remain approximately the same
        assert abs(destination.latitude - start.latitude) < 0.1

    def test_calculate_turn_center_right_turn(self):
        """Test turn center calculation for right turn."""
        current = Coordinate(latitude=39.0, longitude=116.0)
        heading = 0.0  # Heading north
        turn_direction = 1.0  # Right turn
        radius = 500.0  # meters

        center = transformer.calculate_turn_center(current, heading, turn_direction, radius)

        # Center should be to the east (right) of current position
        distance = transformer.calculate_distance(current, center)
        assert abs(distance - radius) < 10.0  # Should be approximately radius

        # Bearing to center should be approximately east (90 degrees)
        bearing = transformer.calculate_bearing(current, center)
        assert abs(bearing - 90.0) < 5.0

    def test_calculate_turn_center_left_turn(self):
        """Test turn center calculation for left turn."""
        current = Coordinate(latitude=39.0, longitude=116.0)
        heading = 0.0  # Heading north
        turn_direction = -1.0  # Left turn
        radius = 500.0  # meters

        center = transformer.calculate_turn_center(current, heading, turn_direction, radius)

        # Center should be to the west (left) of current position
        distance = transformer.calculate_distance(current, center)
        assert abs(distance - radius) < 10.0  # Should be approximately radius

        # Bearing to center should be approximately west (270 degrees)
        bearing = transformer.calculate_bearing(current, center)
        assert abs(bearing - 270.0) < 5.0

    def test_generate_arc_points(self):
        """Test arc point generation."""
        center = Coordinate(latitude=39.0, longitude=116.0)
        radius = 500.0
        start_angle = 0.0
        end_angle = 90.0
        num_points = 16

        points = transformer.generate_arc_points(center, radius, start_angle, end_angle, num_points)

        # Should generate correct number of points
        assert len(points) == num_points

        # All points should be approximately at radius distance from center
        for point in points:
            distance = transformer.calculate_distance(center, point)
            assert abs(distance - radius) < 20.0  # Allow some tolerance

    def test_generate_arc_points_360_wrap(self):
        """Test arc generation with angle wrap-around."""
        center = Coordinate(latitude=39.0, longitude=116.0)
        radius = 500.0
        start_angle = 350.0  # Near wrap-around
        end_angle = 20.0  # After wrap-around
        num_points = 10

        points = transformer.generate_arc_points(center, radius, start_angle, end_angle, num_points)

        # Should still generate correct number of points
        assert len(points) == num_points

    def test_haversine_formula_precision(self):
        """Test Haversine formula precision."""
        # Known distance: 1 degree latitude = approximately 111 km
        coord1 = Coordinate(latitude=0.0, longitude=0.0)
        coord2 = Coordinate(latitude=1.0, longitude=0.0)

        distance = transformer.calculate_distance(coord1, coord2)

        # Should be close to 111.32 km (Earth radius 6378.137 km)
        expected_distance = 111000.0  # meters
        assert abs(distance - expected_distance) < 1000.0  # Within 1 km

    def test_coordinate_precision(self):
        """Test coordinate precision in transformations."""
        # Test that coordinates maintain reasonable precision
        coord = Coordinate(latitude=39.123456, longitude=116.123456)
        transformed = transformer.wgs84_to_gcj02(coord)

        # Should maintain 6 decimal places
        assert len(str(transformed.latitude).split('.')[-1]) <= 6
        assert len(str(transformed.longitude).split('.')[-1]) <= 6


class TestCoordinateEdgeCases:
    """Edge case tests for coordinate transformation."""

    def test_polar_coordinates(self):
        """Test handling of polar coordinates."""
        # Near north pole
        coord = Coordinate(latitude=89.9, longitude=0.0)
        assert transformer.is_in_china(coord.latitude, coord.longitude) == False

    def test_negative_coordinates(self):
        """Test handling of negative coordinates."""
        # South hemisphere
        coord = Coordinate(latitude=-33.9, longitude=151.2)  # Sydney
        assert transformer.is_in_china(coord.latitude, coord.longitude) == False

    def test_zero_coordinates(self):
        """Test handling of zero coordinates."""
        coord = Coordinate(latitude=0.0, longitude=0.0)
        assert transformer.is_in_china(coord.latitude, coord.longitude) == False

    def test_boundary_coordinates(self):
        """Test boundary coordinates."""
        # China boundary edge
        coord = Coordinate(latitude=0.8293, longitude=72.004)
        assert transformer.is_in_china(coord.latitude, coord.longitude) == True

        # Just outside boundary
        coord = Coordinate(latitude=0.8, longitude=72.0)
        assert transformer.is_in_china(coord.latitude, coord.longitude) == False