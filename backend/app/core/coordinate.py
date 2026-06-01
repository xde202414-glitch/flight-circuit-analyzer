"""Coordinate system transformation module."""
import math
import numpy as np
from typing import Tuple
from app.models.runway import Coordinate


class CoordinateTransformer:
    """Coordinate system transformation engine (坐标系转换引擎).
    
    Supports bidirectional transformation between WGS84 and GCJ-02 coordinate systems.
    GCJ-02 is the coordinate system used by Chinese mapping services (Gaode, Baidu).
    """
    
    # GCJ-02 transformation parameters
    A = 6378245.0  # Semi-major axis
    EE = 0.00669342162296594323  # Eccentricity squared
    
    # China boundary bounds (approximate)
    CHINA_MIN_LAT = 0.8293
    CHINA_MAX_LAT = 55.8271
    CHINA_MIN_LON = 72.004
    CHINA_MAX_LON = 137.8347
    
    def __init__(self):
        """Initialize coordinate transformer."""
        pass
    
    def is_in_china(self, lat: float, lon: float) -> bool:
        """Check if coordinate is within China boundary.
        
        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            
        Returns:
            True if within China boundary, False otherwise
        """
        return (
            self.CHINA_MIN_LAT <= lat <= self.CHINA_MAX_LAT
            and self.CHINA_MIN_LON <= lon <= self.CHINA_MAX_LON
        )
    
    def transform_lat(self, x: float, y: float) -> float:
        """Transform latitude component for GCJ-02.
        
        Args:
            x: X coordinate
            y: Y coordinate
            
        Returns:
            Transformed latitude offset
        """
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y
        ret += 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
        return ret
    
    def transform_lon(self, x: float, y: float) -> float:
        """Transform longitude component for GCJ-02.
        
        Args:
            x: X coordinate
            y: Y coordinate
            
        Returns:
            Transformed longitude offset
        """
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y
        ret += 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
        return ret
    
    def _transform_single(self, lat: float, lon: float) -> Tuple[float, float]:
        """Apply GCJ-02 transformation to single coordinate.
        
        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            
        Returns:
            Tuple of (transformed_lat, transformed_lon)
        """
        if not self.is_in_china(lat, lon):
            return lat, lon
        
        d_lat = self.transform_lat(lon - 105.0, lat - 35.0)
        d_lon = self.transform_lon(lon - 105.0, lat - 35.0)
        
        rad_lat = lat / 180.0 * math.pi
        magic = math.sin(rad_lat)
        magic = 1 - self.EE * magic * magic
        sqrt_magic = math.sqrt(magic)
        
        d_lat = (d_lat * 180.0) / ((self.A * (1 - self.EE)) / (magic * sqrt_magic) * math.pi)
        d_lon = (d_lon * 180.0) / (self.A / sqrt_magic * math.cos(rad_lat) * math.pi)
        
        transformed_lat = lat + d_lat
        transformed_lon = lon + d_lon
        
        return transformed_lat, transformed_lon
    
    def wgs84_to_gcj02(self, coord: Coordinate) -> Coordinate:
        """Transform WGS84 coordinate to GCJ-02.
        
        Args:
            coord: WGS84 coordinate
            
        Returns:
            GCJ-02 coordinate
        """
        lat, lon = self._transform_single(coord.latitude, coord.longitude)
        return Coordinate(latitude=round(lat, 6), longitude=round(lon, 6))
    
    def gcj02_to_wgs84(self, coord: Coordinate) -> Coordinate:
        """Transform GCJ-02 coordinate to WGS84 (approximate inverse).
        
        Args:
            coord: GCJ-02 coordinate
            
        Returns:
            Approximate WGS84 coordinate
        """
        if not self.is_in_china(coord.latitude, coord.longitude):
            return coord
        
        # Iterative approximation (usually 2-3 iterations sufficient)
        # Start with rough inverse
        init_lat, init_lon = coord.latitude, coord.longitude
        
        # Use iterative approach
        threshold = 0.000001  # ~0.1m precision
        
        for _ in range(10):  # Max iterations
            # Forward transform from current estimate
            tmp_lat, tmp_lon = self._transform_single(init_lat, init_lon)
            
            # Calculate error
            error_lat = tmp_lat - coord.latitude
            error_lon = tmp_lon - coord.longitude
            
            # Adjust estimate
            init_lat -= error_lat
            init_lon -= error_lon
            
            # Check convergence
            if abs(error_lat) < threshold and abs(error_lon) < threshold:
                break
        
        return Coordinate(latitude=round(init_lat, 6), longitude=round(init_lon, 6))
    
    def calculate_distance(
        self, 
        coord1: Coordinate, 
        coord2: Coordinate,
        method: str = "haversine"
    ) -> float:
        """Calculate distance between two coordinates using Haversine formula.
        
        Args:
            coord1: First coordinate
            coord2: Second coordinate
            method: Distance calculation method
            
        Returns:
            Distance in meters
        """
        # Convert degrees to radians
        lat1 = math.radians(coord1.latitude)
        lon1 = math.radians(coord1.longitude)
        lat2 = math.radians(coord2.latitude)
        lon2 = math.radians(coord2.longitude)
        
        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        
        # Earth radius in meters (WGS84)
        r = 6378137.0
        
        return round(c * r, 1)
    
    def calculate_bearing(self, coord1: Coordinate, coord2: Coordinate) -> float:
        """Calculate bearing from coord1 to coord2.
        
        Args:
            coord1: Start coordinate
            coord2: End coordinate
            
        Returns:
            Bearing in degrees (0-360)
        """
        # Convert degrees to radians
        lat1 = math.radians(coord1.latitude)
        lon1 = math.radians(coord1.longitude)
        lat2 = math.radians(coord2.latitude)
        lon2 = math.radians(coord2.longitude)
        
        # Calculate bearing
        dlon = lon2 - lon1
        
        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        
        bearing = math.atan2(y, x)
        
        # Convert to degrees and normalize to 0-360
        bearing_deg = math.degrees(bearing)
        bearing_deg = (bearing_deg + 360) % 360
        
        return round(bearing_deg, 1)
    
    def destination_point(
        self,
        start: Coordinate,
        bearing: float,
        distance: float
    ) -> Coordinate:
        """Calculate destination point given start, bearing, and distance.
        
        Args:
            start: Start coordinate
            bearing: Bearing in degrees
            distance: Distance in meters
            
        Returns:
            Destination coordinate
        """
        # Convert to radians
        lat1 = math.radians(start.latitude)
        lon1 = math.radians(start.longitude)
        brng = math.radians(bearing)
        
        # Earth radius in meters (WGS84)
        r = 6378137.0
        
        # Angular distance
        d = distance / r
        
        # Calculate destination
        lat2 = math.asin(
            math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brng)
        )
        
        lon2 = lon1 + math.atan2(
            math.sin(brng) * math.sin(d) * math.cos(lat1),
            math.cos(d) - math.sin(lat1) * math.sin(lat2)
        )
        
        # Convert back to degrees
        dest_lat = math.degrees(lat2)
        dest_lon = math.degrees(lon2)
        
        # Normalize longitude to -180 to 180
        dest_lon = (dest_lon + 540) % 360 - 180
        
        return Coordinate(latitude=round(dest_lat, 6), longitude=round(dest_lon, 6))
    
    def calculate_turn_center(
        self,
        current: Coordinate,
        heading: float,
        turn_direction: float,
        radius: float
    ) -> Coordinate:
        """Calculate turn arc center point.
        
        Args:
            current: Current position
            heading: Current heading in degrees
            turn_direction: Turn direction (positive for right, negative for left)
            radius: Turn radius in meters
            
        Returns:
            Turn center coordinate
        """
        # Adjust heading to get perpendicular direction to center
        # For right turn: center is at heading + 90
        # For left turn: center is at heading - 90
        perpendicular_bearing = heading + (90 if turn_direction > 0 else -90)
        perpendicular_bearing = (perpendicular_bearing + 360) % 360
        
        return self.destination_point(current, perpendicular_bearing, radius)
    
    def generate_arc_points(
        self,
        center: Coordinate,
        radius: float,
        start_angle: float,
        end_angle: float,
        num_points: int = 16
    ) -> list[Coordinate]:
        """Generate points along an arc.
        
        Args:
            center: Arc center coordinate
            radius: Arc radius in meters
            start_angle: Start angle in degrees (from center)
            end_angle: End angle in degrees
            num_points: Number of points to generate
            
        Returns:
            List of coordinates along the arc
        """
        points = []
        
        # Normalize angles
        start_angle = (start_angle + 360) % 360
        end_angle = (end_angle + 360) % 360
        
        # Calculate angular increment
        # Handle wrap-around
        if end_angle < start_angle:
            end_angle += 360
        
        angle_step = (end_angle - start_angle) / (num_points - 1)
        
        # Earth radius
        earth_r = 6378137.0
        
        # Convert center to radians
        center_lat_rad = math.radians(center.latitude)
        center_lon_rad = math.radians(center.longitude)
        
        # Angular radius
        angular_radius = radius / earth_r
        
        for i in range(num_points):
            angle = start_angle + angle_step * i
            angle_rad = math.radians(angle)
            
            # Calculate point on arc using spherical geometry
            lat = math.asin(
                math.sin(center_lat_rad) * math.cos(angular_radius)
                + math.cos(center_lat_rad) * math.sin(angular_radius) * math.cos(angle_rad)
            )
            
            lon = center_lon_rad + math.atan2(
                math.sin(angle_rad) * math.sin(angular_radius) * math.cos(center_lat_rad),
                math.cos(angular_radius) - math.sin(center_lat_rad) * math.sin(lat)
            )
            
            # Convert to degrees
            point_lat = math.degrees(lat)
            point_lon = math.degrees(lon)
            
            # Normalize longitude
            point_lon = (point_lon + 540) % 360 - 180
            
            points.append(Coordinate(latitude=round(point_lat, 6), longitude=round(point_lon, 6)))
        
        return points


# Global transformer instance
transformer = CoordinateTransformer()