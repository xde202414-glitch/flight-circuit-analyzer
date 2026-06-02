import React from 'react';
import { Alert, Box, Button, CircularProgress, Typography } from '@mui/material';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RunwayParams, Coordinate } from '../../types/runway';
import { GeometryOverlay, TrackResult, TrackSegment, TRACK_COLORS } from '../../types/track';
import { fetchElevationGrid, buildTerrainMesh, sampleTerrainHeight, type ElevationGridData } from '../../utils/elevationGrid';

const AIRSPACE_RADIUS_M = 5000;
const EARTH_RADIUS_M = 6378137;
const DEFAULT_BUILDING_HEIGHT_M = 10;
const MIN_BUILDING_HEIGHT_M = 3;
const MAX_BUILDING_HEIGHT_M = 300;

interface Map3DViewProps {
  runwayParams: RunwayParams;
  trackResult: TrackResult | null;
  enabled: boolean;
}

interface OsmPoint {
  lat: number;
  lon: number;
}

interface OsmElement {
  id: number;
  tags?: Record<string, string | undefined>;
  geometry?: OsmPoint[];
}

interface BuildingFeature {
  id: number;
  tags: Record<string, string | undefined>;
  geometry: Coordinate[];
}

interface RoadFeature {
  id: number;
  geometry: Coordinate[];
}

interface ProjectedPoint {
  east: number;
  north: number;
}

interface Track3DSegment {
  id: string;
  color: string;
  points: THREE.Vector3[];
}

const coordinateKey = (coordinate: Coordinate): string =>
  `${coordinate.latitude.toFixed(5)},${coordinate.longitude.toFixed(5)}`;

const distanceMeters = (from: Coordinate, to: Coordinate): number => {
  const lat1 = (from.latitude * Math.PI) / 180;
  const lat2 = (to.latitude * Math.PI) / 180;
  const dLat = lat2 - lat1;
  const dLon = ((to.longitude - from.longitude) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
};

const projectCoordinate = (origin: Coordinate, coordinate: Coordinate): ProjectedPoint => {
  const refLat = (origin.latitude * Math.PI) / 180;
  const east =
    ((coordinate.longitude - origin.longitude) * Math.PI * EARTH_RADIUS_M * Math.cos(refLat)) /
    180;
  const north = ((coordinate.latitude - origin.latitude) * Math.PI * EARTH_RADIUS_M) / 180;
  return { east, north };
};

const toVector3 = (origin: Coordinate, coordinate: Coordinate, height = 0): THREE.Vector3 => {
  const projected = projectCoordinate(origin, coordinate);
  return new THREE.Vector3(projected.east, height, projected.north);
};

const buildBoundingBox = (center: Coordinate, radiusMeters: number) => {
  const latDelta = radiusMeters / 111320;
  const lngDelta =
    radiusMeters / (111320 * Math.max(Math.cos((center.latitude * Math.PI) / 180), 0.01));
  return {
    south: center.latitude - latDelta,
    west: center.longitude - lngDelta,
    north: center.latitude + latDelta,
    east: center.longitude + lngDelta,
  };
};

const isFeatureInsideRadius = (center: Coordinate, geometry: Coordinate[]): boolean =>
  geometry.some((point) => distanceMeters(center, point) <= AIRSPACE_RADIUS_M);

const parseBuildingHeight = (tags: Record<string, string | undefined>): number => {
  const height = Number.parseFloat(tags.height ?? '');
  const levels = Number.parseFloat(tags['building:levels'] ?? '');
  const resolvedHeight = Number.isFinite(height)
    ? height
    : Number.isFinite(levels)
      ? levels * 2.2
      : DEFAULT_BUILDING_HEIGHT_M;

  return Math.min(Math.max(resolvedHeight, MIN_BUILDING_HEIGHT_M), MAX_BUILDING_HEIGHT_M);
};

const normalizeElementGeometry = (element: OsmElement): Coordinate[] =>
  (element.geometry ?? []).map((point) => ({
    latitude: point.lat,
    longitude: point.lon,
  }));

interface AmapBuilding {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  type: string;
  address: string;
}

async function fetchAmapBuildings(center: Coordinate): Promise<AmapBuilding[]> {
  try {
    const params = new URLSearchParams({
      latitude: String(center.latitude),
      longitude: String(center.longitude),
      radius: String(AIRSPACE_RADIUS_M),
    });
    const resp = await fetch(`/api/v1/buildings/amap?${params}`);
    if (!resp.ok) return [];
    const json = await resp.json();
    if (json.code !== 200) return [];
    return json.data.buildings as AmapBuilding[];
  } catch {
    return [];
  }
}

/** Create a simple box building from a single coordinate (for POI buildings without footprints). */
function createSimpleBuilding(origin: Coordinate, lat: number, lon: number, heightM = 20): THREE.Mesh {
  const proj = projectCoordinate(origin, { latitude: lat, longitude: lon });
  const geom = new THREE.BoxGeometry(30, heightM, 30);
  const mat = new THREE.MeshStandardMaterial({ color: '#94a3b8', roughness: 0.65, metalness: 0.1 });
  const mesh = new THREE.Mesh(geom, mat);
  mesh.position.set(proj.east, heightM / 2, -proj.north);
  return mesh;
}

async function fetchOsmScene(center: Coordinate, signal: AbortSignal) {
  const bbox = buildBoundingBox(center, AIRSPACE_RADIUS_M);
  const query = `
    [out:json][timeout:30];
    (
      way["building"](${bbox.south},${bbox.west},${bbox.north},${bbox.east});
      relation["building"](${bbox.south},${bbox.west},${bbox.north},${bbox.east});
      way["highway"](${bbox.south},${bbox.west},${bbox.north},${bbox.east});
    );
    out body geom;
  `;

  const response = await fetch('https://overpass-api.de/api/interpreter', {
    method: 'POST',
    body: new URLSearchParams({ data: query }).toString(),
    headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
    signal,
  });

  if (!response.ok) {
    throw new Error(`OSM数据请求失败: HTTP ${response.status}`);
  }

  const payload = (await response.json()) as { elements?: OsmElement[] };
  const elements = payload.elements ?? [];

  const buildings: BuildingFeature[] = elements
    .filter((element) => element.tags?.building && element.geometry && element.geometry.length >= 3)
    .map((element) => ({
      id: element.id,
      tags: element.tags ?? {},
      geometry: normalizeElementGeometry(element),
    }))
    .filter((building) => isFeatureInsideRadius(center, building.geometry));

  const roads: RoadFeature[] = elements
    .filter((element) => element.tags?.highway && element.geometry && element.geometry.length >= 2)
    .map((element) => ({
      id: element.id,
      geometry: normalizeElementGeometry(element),
    }))
    .filter((road) => isFeatureInsideRadius(center, road.geometry));

  return { buildings, roads };
}

const createLine = (
  points: THREE.Vector3[],
  color: string,
  opacity = 1
): THREE.Line<THREE.BufferGeometry, THREE.LineBasicMaterial> => {
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: opacity < 1,
    opacity,
  });
  return new THREE.Line(geometry, material);
};

const createTextSprite = (text: string): THREE.Sprite => {
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  const font = '700 28px Arial, sans-serif';
  const paddingX = 24;
  const height = 56;

  if (!context) {
    return new THREE.Sprite();
  }

  context.font = font;
  const width = Math.ceil(context.measureText(text).width + paddingX * 2);
  canvas.width = width;
  canvas.height = height;
  context.font = font;
  context.fillStyle = 'rgba(255, 255, 255, 0.92)';
  context.strokeStyle = 'rgba(15, 23, 42, 0.18)';
  context.lineWidth = 2;
  context.beginPath();
  context.roundRect(1, 1, width - 2, height - 2, 18);
  context.fill();
  context.stroke();
  context.fillStyle = '#0f172a';
  context.textBaseline = 'middle';
  context.fillText(text, paddingX, height / 2);

  const texture = new THREE.CanvasTexture(canvas);
  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: false,
  });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(width * 1.6, height * 1.6, 1);
  return sprite;
};

const createBuildingMesh = (origin: Coordinate, building: BuildingFeature): THREE.Mesh | null => {
  const points = building.geometry.map((point) => {
    const projected = projectCoordinate(origin, point);
    return new THREE.Vector2(projected.east, -projected.north);
  });

  if (points.length < 3) {
    return null;
  }

  if (!points[0].equals(points[points.length - 1])) {
    points.push(points[0]);
  }

  const shape = new THREE.Shape(points);
  const geometry = new THREE.ExtrudeGeometry(shape, {
    steps: 1,
    depth: parseBuildingHeight(building.tags),
    bevelEnabled: false,
  });
  const material = new THREE.MeshStandardMaterial({
    color: '#9ca3af',
    roughness: 0.72,
    metalness: 0.08,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.rotation.x = -Math.PI / 2;
  return mesh;
};

const createAirspaceGroup = (): THREE.Group => {
  const group = new THREE.Group();
  const circle = new THREE.Mesh(
    new THREE.CircleGeometry(AIRSPACE_RADIUS_M, 128),
    new THREE.MeshBasicMaterial({
      color: '#38bdf8',
      transparent: true,
      opacity: 0.06,
      depthWrite: false,
    })
  );
  circle.rotation.x = -Math.PI / 2;
  group.add(circle);

  const boundaryPoints = Array.from({ length: 129 }, (_, index) => {
    const angle = (index / 128) * Math.PI * 2;
    return new THREE.Vector3(
      Math.cos(angle) * AIRSPACE_RADIUS_M,
      1,
      Math.sin(angle) * AIRSPACE_RADIUS_M
    );
  });
  group.add(createLine(boundaryPoints, '#0284c7', 0.85));
  return group;
};

const createRunwayGroup = (runway: RunwayParams, runwayWidth?: number): THREE.Group => {
  const group = new THREE.Group();
  const rwWidth = runwayWidth && runwayWidth > 0 ? runwayWidth : 18;
  const runwayMesh = new THREE.Mesh(
    new THREE.BoxGeometry(runway.length, 3, rwWidth),
    new THREE.MeshStandardMaterial({ color: '#1e293b' })
  );
  runwayMesh.position.y = 1.5;
  runwayMesh.rotation.y = (runway.magneticBearing * Math.PI) / 180 - Math.PI / 2;
  group.add(runwayMesh);

  const centerMarker = new THREE.Mesh(
    new THREE.SphereGeometry(28, 16, 16),
    new THREE.MeshStandardMaterial({ color: '#2563eb' })
  );
  centerMarker.position.y = 50;
  group.add(centerMarker);

  const label = createTextSprite('跑道中心');
  label.position.set(0, 130, 0);
  group.add(label);
  return group;
};

// ============================================================
// OLS 3D Surface Builders
// ============================================================

const OLS_3D_COLORS: Record<string, string> = {
  'inner-horizontal': '#3b82f6',
  conical: '#d97706',
  approach: '#ef4444',
  'approach-2': '#f87171',
  'takeoff-climb': '#16a34a',
  transitional: '#7c3aed',
  'approach-ih-intersection': '#a855f7',
  'runway-strip': '#94a3b8',
};

function localToWorld3D(x: number, z: number, y: number, bearingDeg: number): THREE.Vector3 {
  const rad = (bearingDeg * Math.PI) / 180;
  return new THREE.Vector3(
    x * Math.sin(rad) + z * Math.cos(rad),
    y,
    x * Math.cos(rad) - z * Math.sin(rad),
  );
}

function capsuleLocalPoints(
  runwayLength: number,
  radius: number,
  count: number,
): Array<[number, number]> {
  const half = Math.max(8, Math.floor(count / 2));
  const pts: Array<[number, number]> = [];
  for (let i = 0; i <= half; i++) {
    const a = Math.PI / 2 + (Math.PI * i) / half;
    pts.push([radius * Math.cos(a), radius * Math.sin(a)]);
  }
  for (let i = 0; i <= half; i++) {
    const a = -Math.PI / 2 + (Math.PI * i) / half;
    pts.push([runwayLength + radius * Math.cos(a), radius * Math.sin(a)]);
  }
  return pts;
}

function createSurfaceMaterial(color: string, opacity: number): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({
    color,
    roughness: 0.65,
    metalness: 0.05,
    transparent: true,
    opacity,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
}

function createEdgeLine(
  points3D: THREE.Vector3[],
  color: string,
  opacity = 0.7,
): THREE.Line {
  const geo = new THREE.BufferGeometry().setFromPoints(points3D);
  return new THREE.Line(
    geo,
    new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity, depthTest: true }),
  );
}

function createExtrudedSlab(
  shapePoints: THREE.Vector3[],
  baseY: number,
  topY: number,
  color: string,
  opacity: number,
): THREE.Group {
  const grp = new THREE.Group();
  if (shapePoints.length < 3 || topY <= baseY) return grp;

  const shape2D = shapePoints.map((p) => new THREE.Vector2(p.x, p.z));
  const shape = new THREE.Shape(shape2D);
  const thickness = topY - baseY;
  const geo = new THREE.ExtrudeGeometry(shape, { steps: 1, depth: thickness, bevelEnabled: false });
  const mat = createSurfaceMaterial(color, opacity);
  const mesh = new THREE.Mesh(geo, mat);
  mesh.userData.isOLS = true;
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = topY;
  grp.add(mesh);

  const closed = [...shapePoints, shapePoints[0]];
  grp.add(createEdgeLine(closed.map((p) => p.clone().setY(topY)), color, 0.5));
  if (baseY > 0.05 && opacity > 0.1) {
    grp.add(createEdgeLine(closed.map((p) => p.clone().setY(baseY)), color, 0.3));
  }
  return grp;
}

function createHorizontalFlatPolygon(
  worldPoints: THREE.Vector3[],
  y: number,
  color: string,
  opacity: number,
): THREE.Group {
  const grp = new THREE.Group();
  if (worldPoints.length < 3) return grp;
  const shape = new THREE.Shape(worldPoints.map((p) => new THREE.Vector2(p.x, p.z)));
  const geo = new THREE.ShapeGeometry(shape);
  const mesh = new THREE.Mesh(geo, createSurfaceMaterial(color, opacity));
  mesh.userData.isOLS = true;
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = y;
  grp.add(mesh);
  const closed = [...worldPoints, worldPoints[0]];
  grp.add(createEdgeLine(closed.map((p) => p.clone().setY(y)), color, 0.55));
  return grp;
}

// ---- Sloped approach / takeoff trapezoid (closed volume) ----
function createSlopedTrapezoid(
  innerLeft: THREE.Vector3,
  innerRight: THREE.Vector3,
  outerRight: THREE.Vector3,
  outerLeft: THREE.Vector3,
  innerY: number,
  outerY: number,
  color: string,
  opacity: number,
): THREE.Group {
  const grp = new THREE.Group();
  const gnd = 0.2;
  const mat = createSurfaceMaterial(color, opacity);

  // Top vertices (sloped surface)
  const t0 = innerLeft.clone(); t0.y = innerY;   // top inner-left
  const t1 = innerRight.clone(); t1.y = innerY;  // top inner-right
  const t2 = outerRight.clone(); t2.y = outerY;  // top outer-right
  const t3 = outerLeft.clone(); t3.y = outerY;   // top outer-left

  // Bottom vertices (all at ground)
  const b0 = innerLeft.clone(); b0.y = gnd;
  const b1 = innerRight.clone(); b1.y = gnd;
  const b2 = outerRight.clone(); b2.y = gnd;
  const b3 = outerLeft.clone(); b3.y = gnd;

  const verts = new Float32Array([
    t0.x, t0.y, t0.z,  // 0
    t1.x, t1.y, t1.z,  // 1
    t2.x, t2.y, t2.z,  // 2
    t3.x, t3.y, t3.z,  // 3
    b0.x, b0.y, b0.z,  // 4
    b1.x, b1.y, b1.z,  // 5
    b2.x, b2.y, b2.z,  // 6
    b3.x, b3.y, b3.z,  // 7
  ]);

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(verts, 3));
  geo.setIndex([
    0, 1, 2, 0, 2, 3,  // top face
    4, 6, 5, 4, 7, 6,  // bottom face
    4, 7, 3, 4, 3, 0,  // left wall
    7, 6, 2, 7, 2, 3,  // outer wall
    6, 5, 1, 6, 1, 2,  // right wall
  ]);
  geo.computeVertexNormals();
  const trapMesh = new THREE.Mesh(geo, mat);
  trapMesh.userData.isOLS = true;
  grp.add(trapMesh);

  // Edge lines
  grp.add(createEdgeLine([t0, t1, t2, t3, t0], color, 0.65));

  return grp;
}

// ---- Conical surface (fully closed solid volume on top of inner horizontal) ----
// Bottom footprint = inner horizontal boundary at innerY (sits on inner horizontal)
// Top footprint = conical outer boundary at outerY (completely closed flat cap)
// Ring (inner→outer): sloped top | vertical outer wall | bottom face | vertical inner wall
function buildConicalSolid3D(
  outerWorld: THREE.Vector3[],
  innerWorld: THREE.Vector3[],
  innerY: number,
  outerY: number,
  color: string,
  opacity: number,
): THREE.Group {
  const grp = new THREE.Group();
  const n = innerWorld.length;
  const mat = createSurfaceMaterial(color, opacity);

  const oTop = outerWorld;                                    // outer ring at outerY
  const iTop = innerWorld;                                    // inner ring at outerY (flat cap edge)
  const oBot = outerWorld.map((p) => p.clone().setY(innerY)); // outer ring at innerY
  const iBot = innerWorld.map((p) => p.clone().setY(innerY)); // inner ring at innerY

  const allVerts: number[] = [];
  const allIndices: number[] = [];
  let base = 0;

  function addQ(a: THREE.Vector3, b: THREE.Vector3, c: THREE.Vector3, d: THREE.Vector3) {
    [a, b, c, d].forEach((p) => allVerts.push(p.x, p.y, p.z));
    allIndices.push(base, base + 1, base + 2, base, base + 2, base + 3);
    base += 4;
  }

  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    addQ(oTop[i], oTop[j], iTop[j], iTop[i]); // sloped top (innerY→outerY)
    addQ(oBot[j], oBot[i], iBot[i], iBot[j]); // bottom ring face (flat at innerY)
    addQ(oBot[i], oBot[j], oTop[j], oTop[i]); // outer vertical wall
    addQ(iBot[j], iBot[i], iTop[i], iTop[j]); // inner vertical wall (innerY→outerY at inner boundary)
  }

  // Flat top face at outerY covering the full outer capsule
  const topShape = new THREE.Shape(outerWorld.map((p) => new THREE.Vector2(p.x, p.z)));
  const topGeo = new THREE.ShapeGeometry(topShape);
  const topMesh = new THREE.Mesh(topGeo, mat);
  topMesh.userData.isOLS = true;
  topMesh.rotation.x = -Math.PI / 2;
  topMesh.position.y = outerY;
  grp.add(topMesh);

  // Bottom face at innerY for the full outer capsule (closes the entire volume)
  const botShape = new THREE.Shape(outerWorld.map((p) => new THREE.Vector2(p.x, p.z)));
  const botGeo = new THREE.ShapeGeometry(botShape);
  const botMesh = new THREE.Mesh(botGeo, mat);
  botMesh.userData.isOLS = true;
  botMesh.rotation.x = -Math.PI / 2;
  botMesh.position.y = innerY;
  grp.add(botMesh);

  // Combined ring geometry
  const ringGeo = new THREE.BufferGeometry();
  ringGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(allVerts), 3));
  ringGeo.setIndex(allIndices);
  ringGeo.computeVertexNormals();
  const ringMesh = new THREE.Mesh(ringGeo, mat);
  ringMesh.userData.isOLS = true;
  grp.add(ringMesh);

  // Edge lines
  grp.add(createEdgeLine([...oTop, oTop[0]], color, 0.6));
  grp.add(createEdgeLine([...iTop, iTop[0]], color, 0.5));

  return grp;
}

// ---- Transitional surface (closed wedge volumes, left + right of runway) ----
// Cross-section: inner edge at strip edge (ground) → slopes up to outer edge (ih_height)
// side: 0 = both sides, 1 = right only, -1 = left only
function createTransitional3D(
  startX: number,
  endX: number,
  innerHalfWidth: number,
  outerHalfWidth: number,
  innerY: number,
  outerY: number,
  xOff: number,
  bearingDeg: number,
  color: string,
  opacity: number,
  side: number = 0,
): THREE.Group {
  const grp = new THREE.Group();
  const mat = createSurfaceMaterial(color, opacity);
  const gnd = 0.2;
  const w = (x: number, z: number, y: number) => localToWorld3D(x + xOff, z, y, bearingDeg);

  const sides = side === 0 ? [-1, 1] : [side];

  sides.forEach((s) => {
    const iz = s * innerHalfWidth;
    const oz = s * outerHalfWidth;

    const tIL = w(startX, iz, innerY);
    const tIR = w(endX, iz, innerY);
    const tOR = w(endX, oz, outerY);
    const tOL = w(startX, oz, outerY);

    const bIL = w(startX, iz, gnd);
    const bIR = w(endX, iz, gnd);
    const bOR = w(endX, oz, gnd);
    const bOL = w(startX, oz, gnd);

    const all = [tIL, tIR, tOR, tOL, bIL, bIR, bOR, bOL];
    const verts = new Float32Array(all.flatMap((v) => [v.x, v.y, v.z]));

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(verts, 3));
    geo.setIndex([
      0, 1, 2, 0, 2, 3,  // top (sloped)
      4, 6, 5, 4, 7, 6,  // bottom (flat ground)
      7, 6, 2, 7, 2, 3,  // outer wall (vertical)
      4, 7, 3, 4, 3, 0,  // front wall
      5, 6, 2, 5, 2, 1,  // back wall
      4, 0, 1, 4, 1, 5,  // inner wall (near strip edge)
    ]);
    geo.computeVertexNormals();
    const transMesh = new THREE.Mesh(geo, mat);
    transMesh.userData.isOLS = true;
    grp.add(transMesh);

    grp.add(createEdgeLine([tIL, tIR, tOR, tOL, tIL], color, 0.55));
  });

  return grp;
}

// ---- Approach-section transitional surface ----
// Follows the approach surface side edge outward from the approach/inner-horizontal
// intersection point, extending horizontally to the transitional outer boundary.
// The inner edge is sloped (following the approach surface side edge), creating a
// wedge that tapers to zero width at the approach/inner-horizontal intersection.
function createApproachTransitional3D(
  xIntersect: number,
  xInner: number,
  zIntersect: number,
  zApproachOuter: number,
  approachInnerHW: number,
  ihHeight: number,
  xOff: number,
  bearingDeg: number,
  color: string,
  opacity: number,
  side: number = 0,
): THREE.Group {
  const grp = new THREE.Group();
  const mat = createSurfaceMaterial(color, opacity);
  const gnd = 0.2;
  const w = (x: number, z: number, y: number) => localToWorld3D(x + xOff, z, y, bearingDeg);

  const sides = side === 0 ? [-1, 1] : [side];

  sides.forEach((s) => {
    const zi = s * zIntersect;
    const zao = s * zApproachOuter;
    const aihw = s * approachInnerHW;

    // At x=xIntersect: inner=outer=zIntersect, y_inner=ih_height (wedge has zero width)
    const tI_start = w(xIntersect, zi, ihHeight);
    const tO_start = w(xIntersect, zi, ihHeight);  // same point
    const bI_start = w(xIntersect, zi, gnd);
    const bO_start = w(xIntersect, zi, gnd);        // same point

    // At x=xInner: inner at approach edge (y=0), outer at full height
    const tI_end = w(xInner, aihw, 0);
    const tO_end = w(xInner, zao, ihHeight);
    const bI_end = w(xInner, aihw, gnd);
    const bO_end = w(xInner, zao, gnd);

    const verts = new Float32Array([
      tI_start.x, tI_start.y, tI_start.z,  // 0
      tO_start.x, tO_start.y, tO_start.z,  // 1
      tO_end.x, tO_end.y, tO_end.z,        // 2
      tI_end.x, tI_end.y, tI_end.z,        // 3
      bI_start.x, bI_start.y, bI_start.z,  // 4
      bO_start.x, bO_start.y, bO_start.z,  // 5
      bO_end.x, bO_end.y, bO_end.z,        // 6
      bI_end.x, bI_end.y, bI_end.z,        // 7
    ]);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(verts, 3));
    // 0,1 are same (zero-width at approach end), 1→2→3→0 is the top face
    // 4→5 are same, faces involving them are degenerate at the approach end
    geo.setIndex([
      0, 3, 2, 0, 2, 1,  // top (sloped inner→outer)
      4, 6, 7,            // bottom (ground)
      5, 2, 1, 5, 6, 2,  // outer wall (vertical)
      4, 7, 3, 4, 3, 0,  // inner wall
      6, 7, 3, 6, 3, 2,  // front wall (at x=xInner)
    ]);
    geo.computeVertexNormals();
    const mesh = new THREE.Mesh(geo, mat);
    mesh.userData.isOLS = true;
    grp.add(mesh);

    grp.add(createEdgeLine([tI_start, tI_end, tO_end, tO_start, tI_start], color, 0.55));
  });

  return grp;
}

function createOLSSurfacesGroup(
  surfaces: GeometryOverlay[],
  _origin: Coordinate,
  runwayParams: RunwayParams,
): THREE.Group {
  const group = new THREE.Group();
  const elev = runwayParams.elevation;
  const rwLen = runwayParams.length;

  // Backend uses threshold as local origin (x=0).
  // 3D scene uses runway center as origin → offset all backend X by -rwLen/2.
  const xOff = -rwLen / 2;

  for (const surface of surfaces) {
    if (!surface.metadata) continue;
    if (surface.kind !== 'polygon' && surface.kind !== 'polyline') continue;
    const st = surface.metadata.surfaceType as string;
    if (!st) continue;

    const bearing = (surface.metadata.departureBearing as number) ?? runwayParams.magneticBearing;
    const w = (x: number, z: number, y: number) => localToWorld3D(x + xOff, z, y, bearing);

    const altRel = (surface.altitude ?? elev) - elev;
    const color = OLS_3D_COLORS[st] ?? '#6b7280';

    switch (st) {
      case 'runway-area':
        break;

      case 'runway-strip': {
        const halfW = (surface.metadata.halfWidthM as number) ?? 75;
        const endS = (surface.metadata.endSafetyM as number) ?? 60;
        const stripPts = [
          w(-endS, -halfW, 0.3),
          w(rwLen + endS, -halfW, 0.3),
          w(rwLen + endS, halfW, 0.3),
          w(-endS, halfW, 0.3),
        ];
        group.add(createHorizontalFlatPolygon(stripPts, 0.3, color, 0.12));
        break;
      }

      case 'inner-horizontal': {
        const radius = (surface.metadata.radiusM as number) ?? 2000;
        const slabThick = 3;
        const ihBase = altRel;               // bottom at 45m — transitional outer edge meets here
        const ihTop = altRel + slabThick;    // top at 48m — clearly above transitional
        const ihCapsule = capsuleLocalPoints(rwLen, radius, 96);
        const ihWorld = ihCapsule.map(([x, z]) => w(x, z, ihTop));
        group.add(createExtrudedSlab(ihWorld, ihBase, ihTop, color, 0.12));
        break;
      }

      case 'conical': {
        const ihRadius = (surface.metadata.innerRadiusM as number) ?? 2000;
        const coRadius = (surface.metadata.outerRadiusM as number) ?? 3500;
        const coHeight = (surface.metadata.heightM as number) ?? 35;
        // altRel = total height above runway = ih_height + conical_height
        // conical sits ON TOP of inner horizontal: innerY = ih_height, outerY = ih_height + coHeight
        const outerY = altRel;
        const innerY = outerY - coHeight;
        const innerCap = capsuleLocalPoints(rwLen, ihRadius, 96);
        const outerCap = capsuleLocalPoints(rwLen, coRadius, 96);
        const innerWorld3D = innerCap.map(([x, z]) => w(x, z, innerY));
        const outerWorld3D = outerCap.map(([x, z]) => w(x, z, outerY));
        group.add(buildConicalSolid3D(outerWorld3D, innerWorld3D, innerY, outerY, color, 0.1));
        break;
      }

      case 'approach':
      case 'approach-2': {
        const segLen = (surface.metadata.lengthM as number) ?? 1600;
        const slope = ((surface.metadata.slopePercent as number) ?? 2.5) / 100;
        const innerHW = ((surface.metadata.innerEdgeWidthM as number) ?? 60) / 2;
        const distThr = (surface.metadata.distanceFromThresholdM as number) ?? 0;
        const diverge = (surface.metadata.divergenceEachSide as number) ?? 0.15;

        const outerAlt = altRel;
        const innerAlt = Math.max(0, altRel - segLen * slope);

        const outerHW = innerHW + segLen * diverge;
        const innerX = -distThr;
        const outerX = innerX - segLen;

        const vIL = w(innerX, -innerHW, innerAlt);
        const vIR = w(innerX, innerHW, innerAlt);
        const vOR = w(outerX, outerHW, outerAlt);
        const vOL = w(outerX, -outerHW, outerAlt);

        group.add(createSlopedTrapezoid(vIL, vIR, vOR, vOL, innerAlt, outerAlt, color, 0.14));
        break;
      }

      case 'takeoff-climb': {
        const toLen = (surface.metadata.lengthM as number) ?? 1600;
        const toSlope = ((surface.metadata.slopePercent as number) ?? 2.5) / 100;
        const toInnerHW = ((surface.metadata.innerEdgeWidthM as number) ?? 60) / 2;
        const toDistEnd = (surface.metadata.distanceFromRunwayEndM as number) ?? 0;
        const toDiv = (surface.metadata.divergenceEachSide as number) ?? 0.1;
        const toFinalHW = ((surface.metadata.finalWidthM as number) ?? 380) / 2;

        const outerAlt = toLen * toSlope;
        const outerHW = Math.min(toInnerHW + toLen * toDiv, toFinalHW);
        const innerX = rwLen + toDistEnd;
        const outerX = innerX + toLen;

        const vIL = w(innerX, -toInnerHW, 0);
        const vOL = w(outerX, -outerHW, outerAlt);
        const vOR = w(outerX, outerHW, outerAlt);
        const vIR = w(innerX, toInnerHW, 0);

        group.add(createSlopedTrapezoid(vIL, vIR, vOR, vOL, 0, outerAlt, color, 0.14));
        break;
      }

      case 'transitional': {
        const stripStartX = (surface.metadata.startX as number) ?? -60;
        const stripEndX = (surface.metadata.endX as number) ?? rwLen + 60;
        const stripInnerHW = (surface.metadata.stripHalfWidthM as number)
          ?? (surface.metadata.innerHalfWidthM as number)
          ?? 30;
        const stripOuterHW = (surface.metadata.stripOuterHW as number)
          ?? (surface.metadata.outerHalfWidthM as number)
          ?? 255;
        const sideDir = surface.metadata.side === 'left' ? -1
          : surface.metadata.side === 'right' ? 1
          : 0;
        group.add(
          createTransitional3D(stripStartX, stripEndX, stripInnerHW, stripOuterHW, 0, altRel, xOff, bearing, color, 0.11, sideDir),
        );

        // Approach section: transitional surface extending from approach surface side edges
        const apIntersectX = surface.metadata.approachIntersectX as number | undefined;
        const apIntersectZ = surface.metadata.approachIntersectZ as number | undefined;
        const apOuterZ = surface.metadata.approachOuterZ as number | undefined;
        const apInnerHW = (surface.metadata.approachInnerHW as number) ?? 30;
        if (apIntersectX != null && apIntersectZ != null && apOuterZ != null) {
          group.add(
            createApproachTransitional3D(
              apIntersectX, stripStartX, apIntersectZ, apOuterZ,
              apInnerHW, altRel, xOff, bearing, color, 0.11, sideDir,
            ),
          );
        }
        break;
      }

      case 'approach-ih-intersection': {
        // 3D line showing where the approach surface intersects the inner horizontal plane
        const ix = (surface.metadata.xIntersect as number) ?? 0;
        const iz = (surface.metadata.zIntersect as number) ?? 120;
        const startP = w(ix, iz, altRel);
        const endP = w(ix, -iz, altRel);
        group.add(createEdgeLine([startP, endP], color, 0.8));
        break;
      }

      default:
        break;
    }
  }

  return group;
}

const buildTrack3DSegments = (
  origin: Coordinate,
  runway: RunwayParams,
  trackResult: TrackResult | null
): Track3DSegment[] => {
  if (!trackResult) {
    return [];
  }

  let previousAltitude = runway.elevation;

  return trackResult.segments
    .map((segment: TrackSegment) => {
      const coordinates =
        segment.pathPoints && segment.pathPoints.length > 0
          ? segment.pathPoints
          : [segment.startPoint, segment.endPoint];
      const startAltitude = previousAltitude;
      const endAltitude = segment.altitude;
      previousAltitude = endAltitude;

      const points = coordinates.map((point, index) => {
        const progress = coordinates.length > 1 ? index / (coordinates.length - 1) : 1;
        const altitude = startAltitude + (endAltitude - startAltitude) * progress;
        return toVector3(origin, point, Math.max(altitude - runway.elevation, 3));
      });

      return {
        id: segment.name,
        color: TRACK_COLORS[segment.name] ?? '#dc2626',
        points,
      };
    })
    .filter((segment) => segment.points.length >= 2);
};

const createTrackGroup = (
  origin: Coordinate,
  runway: RunwayParams,
  trackResult: TrackResult | null
): THREE.Group => {
  const group = new THREE.Group();
  const segments = buildTrack3DSegments(origin, runway, trackResult);

  segments.forEach((segment) => {
    group.add(createLine(segment.points, segment.color));
  });

  trackResult?.keyPoints.forEach((point) => {
    const marker = createKeyPointMarker(origin, runway, point);
    if (marker) {
      group.add(marker);
    }
  });

  return group;
};

const createKeyPointMarker = (
  origin: Coordinate,
  runway: RunwayParams,
  point: GeometryOverlay
): THREE.Group | null => {
  const coordinate = point.coordinates[0];
  if (!coordinate) {
    return null;
  }

  const group = new THREE.Group();
  const height = Math.max((point.altitude ?? runway.elevation) - runway.elevation, 5);
  group.position.copy(toVector3(origin, coordinate, height));

  const sphere = new THREE.Mesh(
    new THREE.SphereGeometry(28, 16, 16),
    new THREE.MeshStandardMaterial({ color: '#f97316' })
  );
  group.add(sphere);

  const label = createTextSprite(point.label);
  label.position.set(0, 80, 0);
  group.add(label);
  return group;
};

const disposeObject = (object: THREE.Object3D) => {
  object.traverse((child) => {
    const disposable = child as THREE.Object3D & {
      geometry?: THREE.BufferGeometry;
      material?: THREE.Material | THREE.Material[];
    };
    disposable.geometry?.dispose();
    const materials = Array.isArray(disposable.material)
      ? disposable.material
      : disposable.material
        ? [disposable.material]
        : [];
    materials.forEach((material) => {
      const textureMaterial = material as THREE.Material & { map?: THREE.Texture };
      textureMaterial.map?.dispose();
      material.dispose();
    });
  });
};

const ThreeScene: React.FC<{
  runwayParams: RunwayParams;
  trackResult: TrackResult | null;
  buildings: BuildingFeature[];
  roads: RoadFeature[];
  elevationData: ElevationGridData | null;
  amapBuildings: AmapBuilding[];
}> = ({ runwayParams, trackResult, buildings, roads, elevationData, amapBuildings }) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return undefined;
    }

    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#dbeafe');
    const camera = new THREE.PerspectiveCamera(
      48,
      Math.max(container.clientWidth, 1) / Math.max(container.clientHeight, 1),
      1,
      18000
    );
    camera.position.set(0, 5600, 6900);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(Math.max(container.clientWidth, 1), Math.max(container.clientHeight, 1));
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    controls.minDistance = 500;
    controls.maxDistance = 13000;
    controls.enableDamping = true;

    // --- Mouse hover highlighting for OLS surfaces ---
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    let hovered: THREE.Mesh | null = null;

    const handleMouseMove = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(scene.children, true);

      let newHovered: THREE.Mesh | null = null;
      for (const intersect of intersects) {
        if (intersect.object instanceof THREE.Mesh && intersect.object.userData.isOLS) {
          newHovered = intersect.object as THREE.Mesh;
          break;
        }
      }

      if (hovered !== newHovered) {
        if (hovered && hovered.material instanceof THREE.MeshStandardMaterial) {
          hovered.material.emissive.setHex(0x000000);
        }
        if (newHovered && newHovered.material instanceof THREE.MeshStandardMaterial) {
          newHovered.material.emissive.set(newHovered.material.color).multiplyScalar(0.5);
        }
        hovered = newHovered;
      }
    };

    renderer.domElement.addEventListener('mousemove', handleMouseMove);

    // Resolve runway width from OLS surfaces metadata
    let rwWidth: number | undefined;
    if (trackResult) {
      const rwSurface = trackResult.surfaces.find(
        (s) => s.metadata?.surfaceType === 'runway-area',
      );
      if (rwSurface?.metadata?.widthM) {
        rwWidth = rwSurface.metadata.widthM as number;
      }
    }

    scene.add(new THREE.AmbientLight('#ffffff', 0.95));
    const light = new THREE.DirectionalLight('#ffffff', 1.15);
    light.position.set(2600, 5200, 1800);
    scene.add(light);
    scene.add(new THREE.GridHelper(AIRSPACE_RADIUS_M * 2, 20, '#94a3b8', '#cbd5e1'));

    // --- Terrain mesh ---
    const terrainMesh = elevationData
      ? buildTerrainMesh(elevationData, runwayParams.coordinate, runwayParams.elevation)
      : null;
    if (terrainMesh) {
      scene.add(terrainMesh);
    }

    scene.add(createAirspaceGroup());
    scene.add(createRunwayGroup(runwayParams, rwWidth));

    if (trackResult) {
      scene.add(createOLSSurfacesGroup(trackResult.surfaces, runwayParams.coordinate, runwayParams));
    }

    buildings.forEach((building) => {
      const mesh = createBuildingMesh(runwayParams.coordinate, building);
      if (mesh) {
        const centroid = building.geometry[0];
        if (centroid && elevationData) {
          const proj = projectCoordinate(runwayParams.coordinate, centroid);
          const terrainH = sampleTerrainHeight(elevationData, proj.east, proj.north, runwayParams.elevation);
          mesh.position.y = terrainH;
        }
        scene.add(mesh);
      }
    });

    // Amap POI buildings (simple boxes, no footprint data)
    amapBuildings.forEach((b) => {
      const mesh = createSimpleBuilding(runwayParams.coordinate, b.latitude, b.longitude);
      if (elevationData) {
        const proj = projectCoordinate(runwayParams.coordinate, { latitude: b.latitude, longitude: b.longitude });
        const terrainH = sampleTerrainHeight(elevationData, proj.east, proj.north, runwayParams.elevation);
        mesh.position.y = terrainH + 10; // half height offset
      }
      scene.add(mesh);
    });

    roads.forEach((road) => {
      const points = road.geometry.map((point) => {
        const terrainH = elevationData
          ? sampleTerrainHeight(elevationData,
              projectCoordinate(runwayParams.coordinate, point).east,
              projectCoordinate(runwayParams.coordinate, point).north,
              runwayParams.elevation)
          : 0;
        return toVector3(runwayParams.coordinate, point, Math.max(0.35, terrainH + 0.35));
      });
      if (points.length >= 2) {
        scene.add(createLine(points, '#64748b', 0.85));
      }
    });

    scene.add(createTrackGroup(runwayParams.coordinate, runwayParams, trackResult));

    const resizeObserver = new ResizeObserver(() => {
      const width = Math.max(container.clientWidth, 1);
      const height = Math.max(container.clientHeight, 1);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    });
    resizeObserver.observe(container);

    let frameId = 0;
    const render = () => {
      controls.update();
      renderer.render(scene, camera);
      frameId = window.requestAnimationFrame(render);
    };
    render();

    return () => {
      window.cancelAnimationFrame(frameId);
      renderer.domElement.removeEventListener('mousemove', handleMouseMove);
      resizeObserver.disconnect();
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      disposeObject(scene);
    };
  }, [buildings, roads, runwayParams, trackResult, elevationData, amapBuildings]);

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />;
};

const Map3DView: React.FC<Map3DViewProps> = ({ runwayParams, trackResult, enabled }) => {
  const [buildings, setBuildings] = React.useState<BuildingFeature[]>([]);
  const [roads, setRoads] = React.useState<RoadFeature[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [loadedKey, setLoadedKey] = React.useState<string | null>(null);
  const [reloadToken, setReloadToken] = React.useState(0);

  // Elevation + Amap buildings
  const [elevationData, setElevationData] = React.useState<ElevationGridData | null>(null);
  const [amapBuildings, setAmapBuildings] = React.useState<AmapBuilding[]>([]);
  const [elevationLoading, setElevationLoading] = React.useState(false);
  const [elevationError, setElevationError] = React.useState<string | null>(null);

  const currentKey = coordinateKey(runwayParams.coordinate);

  React.useEffect(() => {
    if (!enabled || loadedKey === currentKey) {
      return undefined;
    }

    const controller = new AbortController();
    const osmTimeoutId = window.setTimeout(() => controller.abort(), 15000);

    setLoading(true);
    setElevationLoading(true);
    setElevationError(null);

    // Fetch OSM, elevation, and Amap buildings in parallel
    Promise.allSettled([
      fetchOsmScene(runwayParams.coordinate, controller.signal)
        .then((scene) => {
          setBuildings(scene.buildings);
          setRoads(scene.roads);
        })
        .catch(() => {
          // OSM timeout is expected in China — not a fatal error
          console.log('[Map3D] OSM fetch failed, will rely on Amap buildings');
        }),
      fetchElevationGrid(runwayParams.coordinate)
        .then((data) => {
          setElevationData(data);
        }),
      fetchAmapBuildings(runwayParams.coordinate)
        .then((data) => {
          setAmapBuildings(data);
        }),
    ]).then(([_osmResult, elResult]) => {
      if (elResult.status === 'rejected') {
        setElevationError(elResult.reason instanceof Error ? elResult.reason.message : '高程数据获取失败');
      }
      setLoadedKey(currentKey);
    }).finally(() => {
      window.clearTimeout(osmTimeoutId);
      setLoading(false);
      setElevationLoading(false);
    });

    return () => {
      window.clearTimeout(osmTimeoutId);
      controller.abort();
    };
  }, [currentKey, enabled, loadedKey, reloadToken, runwayParams.coordinate]);

  const handleRetry = () => {
    setLoadedKey(null);
    setReloadToken((value) => value + 1);
  };

  return (
    <Box sx={{ position: 'relative', height: '100%', width: '100%', bgcolor: '#dbeafe' }}>
      {enabled && (
        <ThreeScene
          runwayParams={runwayParams}
          trackResult={trackResult}
          buildings={buildings}
          roads={roads}
          elevationData={elevationData}
          amapBuildings={amapBuildings}
        />
      )}

      <Box sx={{ position: 'absolute', left: 12, top: 12, zIndex: 2, maxWidth: 360 }}>
        {(loading || elevationLoading) && (
          <Alert severity="info" icon={<CircularProgress size={18} />}>
            {elevationLoading ? '正在获取地形高程数据...' : '正在获取周边建筑数据...'}
          </Alert>
        )}
        {!loading && !elevationLoading && elevationError && (
          <Alert severity="warning" action={<Button color="inherit" size="small" onClick={handleRetry}>重试</Button>}>
            {elevationError}
          </Alert>
        )}
        {!loading && !elevationLoading && buildings.length === 0 && amapBuildings.length === 0 && loadedKey === currentKey && (
          <Alert severity="info">5km范围内未获取到建筑数据</Alert>
        )}
        {!loading && !elevationLoading && buildings.length === 0 && amapBuildings.length > 0 && loadedKey === currentKey && (
          <Alert severity="success">已获取 {amapBuildings.length} 个周边建筑（高德POI）</Alert>
        )}
        {!trackResult && (
          <Alert severity="info" sx={{ mt: 1 }}>
            请先计算目视航线以显示三维航线
          </Alert>
        )}
      </Box>

      <Box
        sx={{
          position: 'absolute',
          left: 12,
          bottom: 12,
          zIndex: 2,
          px: 1.5,
          py: 0.75,
          borderRadius: 1,
          bgcolor: 'rgba(15, 23, 42, 0.72)',
          color: '#fff',
        }}
      >
        <Typography variant="caption">
          建筑 OSM {buildings.length} / 高德 {amapBuildings.length} / 道路 {roads.length}
          {elevationData && ` / 地形 ${elevationData.validCount}/${elevationData.totalCount}`}
          {' / 半径 5km'}
        </Typography>
      </Box>
    </Box>
  );
};

export default Map3DView;
