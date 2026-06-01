import * as THREE from 'three';
import type { Coordinate } from '../types/runway';

export interface ElevationPoint {
  latitude: number;
  longitude: number;
  elevation: number | null;
}

export interface ElevationGridData {
  points: ElevationPoint[];
  gridSize: number;
  spacingMeters: number;
  center: Coordinate;
  validCount: number;
  totalCount: number;
}

const EARTH_RADIUS_M = 6378137.0;

export function projectCoordinate(origin: Coordinate, coord: Coordinate): { east: number; north: number } {
  const refLat = (origin.latitude * Math.PI) / 180;
  const east = ((coord.longitude - origin.longitude) * Math.PI * EARTH_RADIUS_M * Math.cos(refLat)) / 180;
  const north = ((coord.latitude - origin.latitude) * Math.PI * EARTH_RADIUS_M) / 180;
  return { east, north };
}

export async function fetchElevationGrid(
  center: Coordinate,
  radiusMeters: number = 5000,
  spacingMeters: number = 200,
): Promise<ElevationGridData> {
  const resp = await fetch('/api/v1/elevation/grid', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      center: { latitude: center.latitude, longitude: center.longitude },
      radius_meters: radiusMeters,
      spacing_meters: spacingMeters,
    }),
  });
  if (!resp.ok) throw new Error(`Elevation API error: ${resp.status}`);
  const json = await resp.json();
  if (json.code !== 200) throw new Error(json.message || 'Elevation API error');
  return json.data as ElevationGridData;
}

/**
 * Build a Three.js terrain mesh from an elevation grid.
 * Returns a Mesh with PlaneGeometry whose vertices are offset by elevation.
 */
export function buildTerrainMesh(
  data: ElevationGridData,
  _origin: Coordinate,
  runwayElevation: number,
): THREE.Mesh | null {
  const { points, gridSize, spacingMeters } = data;
  if (points.length === 0) return null;

  const width = (gridSize - 1) * spacingMeters;
  const geom = new THREE.PlaneGeometry(width, width, gridSize - 1, gridSize - 1);

  // Apply elevation to vertices
  const positions = geom.attributes.position;
  const colors = new Float32Array(positions.count * 3);

  let minH = Infinity;
  let maxH = -Infinity;
  const heights: (number | null)[] = new Array(positions.count);

  // First pass: compute heights and range
  for (let i = 0; i < positions.count; i++) {
    const x = positions.getX(i);
    const z = positions.getY(i); // PlaneGeometry uses XY plane by default

    const row = Math.round((z / width + 0.5) * (gridSize - 1));
    const col = Math.round((x / width + 0.5) * (gridSize - 1));
    const idx = row * gridSize + col;

    let h: number | null = null;
    if (idx >= 0 && idx < points.length && points[idx]?.elevation != null) {
      h = points[idx]!.elevation! - runwayElevation;
    }
    heights[i] = h;
    if (h != null) {
      minH = Math.min(minH, h);
      maxH = Math.max(maxH, h);
    }
  }

  if (minH === Infinity) return null;

  const hRange = maxH - minH || 1;

  // Second pass: set Y (height) and color
  for (let i = 0; i < positions.count; i++) {
    const h = heights[i];
    if (h != null) {
      positions.setZ(i, h);
    } else {
      // Interpolate from neighbors or set to min
      positions.setZ(i, minH);
    }

    // Color ramp: green (low) -> brown (mid) -> white (high)
    const t = (positions.getZ(i) - minH) / hRange;
    if (t < 0.5) {
      colors[i * 3] = 0.2 + t * 1.2;     // R
      colors[i * 3 + 1] = 0.5 + t * 0.3; // G
      colors[i * 3 + 2] = 0.2;           // B
    } else {
      colors[i * 3] = 0.8 + (t - 0.5) * 0.4;
      colors[i * 3 + 1] = 0.65 - (t - 0.5) * 0.3;
      colors[i * 3 + 2] = 0.2 + (t - 0.5) * 0.6;
    }
  }

  geom.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geom.computeVertexNormals();

  // Rotate 90° around X to convert from XY-plane to XZ-plane (Y up)
  geom.rotateX(-Math.PI / 2);

  const material = new THREE.MeshPhongMaterial({
    vertexColors: true,
    side: THREE.DoubleSide,
    transparent: true,
    opacity: 0.85,
  });

  const mesh = new THREE.Mesh(geom, material);
  mesh.name = 'terrain';
  mesh.receiveShadow = true;

  return mesh;
}

/**
 * Sample terrain height at a given local (east, north) position.
 */
export function sampleTerrainHeight(
  data: ElevationGridData,
  east: number,
  north: number,
  runwayElevation: number,
): number {
  const { points, gridSize, spacingMeters } = data;
  const halfWidth = ((gridSize - 1) * spacingMeters) / 2;

  const col = Math.round((east + halfWidth) / spacingMeters);
  const row = Math.round((-north + halfWidth) / spacingMeters);

  const idx = row * gridSize + col;
  if (idx >= 0 && idx < points.length && points[idx].elevation != null) {
    return points[idx].elevation! - runwayElevation;
  }
  return 0;
}
