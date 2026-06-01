/**
 * Coordinate Converter Utilities
 * 坐标转换工具函数（前端实现，用于离线转换）
 */

import { Coordinate, CoordinateSystem } from '../types/runway';

/**
 * GCJ-02 transformation parameters
 */
const A = 6378245.0; // Semi-major axis
const EE = 6.693421622965943e-3; // Eccentricity squared

/**
 * China boundary bounds (approximate)
 */
const CHINA_BOUNDS = {
  minLat: 0.8293,
  maxLat: 55.8271,
  minLon: 72.004,
  maxLon: 137.8347,
};

/**
 * Check if coordinate is within China boundary
 */
export function isInChina(lat: number, lon: number): boolean {
  return (
    lat >= CHINA_BOUNDS.minLat &&
    lat <= CHINA_BOUNDS.maxLat &&
    lon >= CHINA_BOUNDS.minLon &&
    lon <= CHINA_BOUNDS.maxLon
  );
}

/**
 * Transform latitude component for GCJ-02
 */
function transformLat(x: number, y: number): number {
  let ret =
    -100.0 +
    2.0 * x +
    3.0 * y +
    0.2 * y * y +
    0.1 * x * y +
    0.2 * Math.sqrt(Math.abs(x));
  
  ret +=
    (20.0 * Math.sin(6.0 * x * Math.PI) +
      20.0 * Math.sin(2.0 * x * Math.PI)) *
    2.0 /
    3.0;
  ret +=
    (20.0 * Math.sin(y * Math.PI) +
      40.0 * Math.sin(y / 3.0 * Math.PI)) *
    2.0 /
    3.0;
  ret +=
    (160.0 * Math.sin(y / 12.0 * Math.PI) +
      320.0 * Math.sin(y * Math.PI / 30.0)) *
    2.0 /
    3.0;
  
  return ret;
}

/**
 * Transform longitude component for GCJ-02
 */
function transformLon(x: number, y: number): number {
  let ret =
    300.0 +
    x +
    2.0 * y +
    0.1 * x * x +
    0.1 * x * y +
    0.1 * Math.sqrt(Math.abs(x));
  
  ret +=
    (20.0 * Math.sin(6.0 * x * Math.PI) +
      20.0 * Math.sin(2.0 * x * Math.PI)) *
    2.0 /
    3.0;
  ret +=
    (20.0 * Math.sin(x * Math.PI) +
      40.0 * Math.sin(x / 3.0 * Math.PI)) *
    2.0 /
    3.0;
  ret +=
    (150.0 * Math.sin(x / 12.0 * Math.PI) +
      300.0 * Math.sin(x / 30.0 * Math.PI)) *
    2.0 /
    3.0;
  
  return ret;
}

/**
 * Apply GCJ-02 transformation
 */
function transform(lat: number, lon: number): { lat: number; lon: number } {
  if (!isInChina(lat, lon)) {
    return { lat, lon };
  }
  
  const dLat = transformLat(lon - 105.0, lat - 35.0);
  const dLon = transformLon(lon - 105.0, lat - 35.0);
  
  const radLat = (lat / 180.0) * Math.PI;
  const magic = Math.sin(radLat);
  const sqrtMagic = Math.sqrt(1 - EE * magic * magic);
  
  const transformedLat =
    lat +
    (dLat * 180.0) / ((A * (1 - EE)) / (magic * sqrtMagic) * Math.PI);
  const transformedLon =
    lon +
    (dLon * 180.0) / (A / sqrtMagic * Math.cos(radLat) * Math.PI);
  
  return {
    lat: transformedLat,
    lon: transformedLon,
  };
}

/**
 * WGS84 to GCJ-02 transformation
 */
export function wgs84ToGcj02(coord: Coordinate): Coordinate {
  const transformed = transform(coord.latitude, coord.longitude);
  return {
    latitude: Math.round(transformed.lat * 1e6) / 1e6,
    longitude: Math.round(transformed.lon * 1e6) / 1e6,
  };
}

/**
 * GCJ-02 to WGS84 transformation (approximate inverse)
 */
export function gcj02ToWgs84(coord: Coordinate): Coordinate {
  if (!isInChina(coord.latitude, coord.longitude)) {
    return coord;
  }
  
  // Iterative approximation
  let initLat = coord.latitude;
  let initLon = coord.longitude;
  
  const threshold = 0.000001; // ~0.1m precision
  
  for (let i = 0; i < 10; i++) {
    const tmp = transform(initLat, initLon);
    
    const errorLat = tmp.lat - coord.latitude;
    const errorLon = tmp.lon - coord.longitude;
    
    initLat -= errorLat;
    initLon -= errorLon;
    
    if (Math.abs(errorLat) < threshold && Math.abs(errorLon) < threshold) {
      break;
    }
  }
  
  return {
    latitude: Math.round(initLat * 1e6) / 1e6,
    longitude: Math.round(initLon * 1e6) / 1e6,
  };
}

/**
 * Convert coordinate based on system type
 */
export function convertCoordinate(
  coord: Coordinate,
  fromSystem: CoordinateSystem,
  toSystem: CoordinateSystem
): Coordinate {
  if (fromSystem === toSystem) {
    return coord;
  }
  
  if (fromSystem === 'WGS84' && toSystem === 'GCJ02') {
    return wgs84ToGcj02(coord);
  }
  
  if (fromSystem === 'GCJ02' && toSystem === 'WGS84') {
    return gcj02ToWgs84(coord);
  }
  
  return coord;
}

/**
 * Calculate distance between two coordinates (Haversine formula)
 */
export function calculateDistance(coord1: Coordinate, coord2: Coordinate): number {
  const R = 6378137; // Earth radius in meters
  
  const lat1 = (coord1.latitude * Math.PI) / 180;
  const lat2 = (coord2.latitude * Math.PI) / 180;
  const dLat = ((coord2.latitude - coord1.latitude) * Math.PI) / 180;
  const dLon = ((coord2.longitude - coord1.longitude) * Math.PI) / 180;
  
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1) *
      Math.cos(lat2) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  
  return R * c;
}

/**
 * Calculate bearing from coord1 to coord2
 */
export function calculateBearing(coord1: Coordinate, coord2: Coordinate): number {
  const lat1 = (coord1.latitude * Math.PI) / 180;
  const lat2 = (coord2.latitude * Math.PI) / 180;
  const dLon = ((coord2.longitude - coord1.longitude) * Math.PI) / 180;
  
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x =
    Math.cos(lat1) * Math.sin(lat2) -
    Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  
  let bearing = Math.atan2(y, x);
  bearing = ((bearing * 180) / Math.PI + 360) % 360;
  
  return Math.round(bearing * 10) / 10;
}

export default {
  isInChina,
  wgs84ToGcj02,
  gcj02ToWgs84,
  convertCoordinate,
  calculateDistance,
  calculateBearing,
};
