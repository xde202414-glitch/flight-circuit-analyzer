import React from 'react';
import { Alert, Box, CircularProgress, Typography } from '@mui/material';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { Coordinate } from '../../types/runway';
import type { BuildingResult, FATORegion, SurfaceStation, VisualSurfaceResult } from '../../types/helipad';
import { fetchElevationGrid, buildTerrainMesh, type ElevationGridData } from '../../utils/elevationGrid';
import { useHelipadStore } from '../../store/useHelipadStore';
import { apiPost } from '../../api/client';
import type { BuildingSearchRequest, BuildingSearchResponse } from '../../types/helipad';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const EARTH_RADIUS_M = 6378137;
const AIRSPACE_RADIUS_M = 5000;

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------
function projectCoord(origin: Coordinate, coord: Coordinate): { east: number; north: number } {
  const refLat = (origin.latitude * Math.PI) / 180;
  const east = ((coord.longitude - origin.longitude) * Math.PI * EARTH_RADIUS_M * Math.cos(refLat)) / 180;
  const north = ((coord.latitude - origin.latitude) * Math.PI * EARTH_RADIUS_M) / 180;
  return { east, north };
}

function toVec3(origin: Coordinate, coord: Coordinate, height = 0): THREE.Vector3 {
  const p = projectCoord(origin, coord);
  return new THREE.Vector3(p.east, height, p.north);
}

// ---------------------------------------------------------------------------
// 3D scene builders
// ---------------------------------------------------------------------------
function createGroundGrid(): THREE.GridHelper {
  return new THREE.GridHelper(AIRSPACE_RADIUS_M * 2, 20, '#94a3b8', '#cbd5e1');
}

function createFATOMarker(origin: Coordinate, center: Coordinate, _elevation: number): THREE.Group {
  const group = new THREE.Group();
  const pos = toVec3(origin, center, 30);

  // Center sphere
  const sphere = new THREE.Mesh(
    new THREE.SphereGeometry(40, 16, 16),
    new THREE.MeshStandardMaterial({ color: '#0066ff' }),
  );
  sphere.position.copy(pos);
  group.add(sphere);

  // Vertical line to ground
  const lineGeo = new THREE.BufferGeometry().setFromPoints([
    pos.clone(),
    toVec3(origin, center, 0),
  ]);
  group.add(new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: '#0066ff' })));

  return group;
}

function createFATOSurface(
  origin: Coordinate,
  fatoRegion: FATORegion,
  _elevation: number,
): THREE.Group {
  const group = new THREE.Group();
  const center = fatoRegion.center;
  const points: THREE.Vector3[] = [];

  if (fatoRegion.shape === 'circle') {
    const n = 48;
    for (let i = 0; i <= n; i++) {
      const bearing = (i * 360) / n;
      const bearingRad = (bearing * Math.PI) / 180;
      const d = fatoRegion.radius;
      const lat = center.latitude + (d / EARTH_RADIUS_M) * (180 / Math.PI) * Math.cos(bearingRad);
      const lon = center.longitude + (d / (EARTH_RADIUS_M * Math.cos((center.latitude * Math.PI) / 180))) * (180 / Math.PI) * Math.sin(bearingRad);
      points.push(toVec3(origin, { latitude: lat, longitude: lon }, 0.5));
    }
  }

  if (points.length >= 3) {
    const geo = new THREE.BufferGeometry().setFromPoints(points);
    const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: '#0066ff' }));
    group.add(line);

    // Filled circle
    const shape = new THREE.Shape(points.map((p) => new THREE.Vector2(p.x, p.z)));
    const mesh = new THREE.Mesh(
      new THREE.ShapeGeometry(shape),
      new THREE.MeshBasicMaterial({ color: '#0066ff', transparent: true, opacity: 0.2, depthWrite: false }),
    );
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.y = 0.5;
    group.add(mesh);
  }

  return group;
}

/**
 * Create a sloped 3D approach/takeoff surface from polygon + station heights.
 *
 * The polygon from the backend has the layout:
 *   [left_0, left_1, …, left_{N-1}, right_{N-1}, …, right_1, right_0]
 * where N = stations.length.
 *
 * Each pair of consecutive stations forms a sloped trapezoid:
 *   - inner edge (station i)   at height = stations[i].height
 *   - outer edge (station i+1) at height = stations[i+1].height
 *
 * This mirrors the runway Map3DView's createSlopedTrapezoid pattern.
 */
function createSlopedSurfacePolygon(
  origin: Coordinate,
  polygon: Coordinate[],
  stations: SurfaceStation[],
  color: string,
): THREE.Group {
  const group = new THREE.Group();
  if (polygon.length < 4 || stations.length < 2) return group;

  const N = stations.length;
  const GND = 0.2; // slight offset above ground to avoid z-fighting

  // Material matching runway OLS style
  const mat = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.6,
    metalness: 0.05,
    transparent: true,
    opacity: 0.25,
    depthWrite: false,
    side: THREE.DoubleSide,
  });

  // Create a sloped trapezoid for each segment between consecutive stations
  for (let i = 0; i < N - 1; i++) {
    const innerY = stations[i].height;
    const outerY = stations[i + 1].height;

    // Four corners in WGS84
    const left0 = polygon[i];                      // left, station i (inner)
    const left1 = polygon[i + 1];                  // left, station i+1 (outer)
    const right0 = polygon[polygon.length - 1 - i]; // right, station i (inner)
    const right1 = polygon[polygon.length - 2 - i]; // right, station i+1 (outer)

    // Top vertices — sloped surface
    const t0 = toVec3(origin, left0, innerY);   // top inner-left
    const t1 = toVec3(origin, right0, innerY);  // top inner-right
    const t2 = toVec3(origin, right1, outerY);  // top outer-right
    const t3 = toVec3(origin, left1, outerY);   // top outer-left

    // Bottom vertices — all at ground level
    const b0 = toVec3(origin, left0, GND);
    const b1 = toVec3(origin, right0, GND);
    const b2 = toVec3(origin, right1, GND);
    const b3 = toVec3(origin, left1, GND);

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
      0, 1, 2, 0, 2, 3,  // top face (sloped)
      4, 6, 5, 4, 7, 6,  // bottom face (ground)
      4, 7, 3, 4, 3, 0,  // left wall
      7, 6, 2, 7, 2, 3,  // outer wall
      6, 5, 1, 6, 1, 2,  // right wall
    ]);
    geo.computeVertexNormals();

    const mesh = new THREE.Mesh(geo, mat);
    mesh.userData.isHelipadSurface = true;
    group.add(mesh);

    // Edge lines — top sloped face outline
    const lineGeo = new THREE.BufferGeometry().setFromPoints([t0, t1, t2, t3, t0]);
    group.add(new THREE.Line(
      lineGeo,
      new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.6, depthTest: true }),
    ));
  }

  return group;
}

function createBuildingBox(
  origin: Coordinate,
  b: BuildingResult,
  elevationData: ElevationGridData | null,
  originElevation: number,
): THREE.Mesh | null {
  const coord: Coordinate = { latitude: b.latitude, longitude: b.longitude };
  const proj = projectCoord(origin, coord);

  // Determine ground elevation
  let groundH = 0;
  if (elevationData) {
    const { points, gridSize, spacingMeters } = elevationData;
    const halfWidth = ((gridSize - 1) * spacingMeters) / 2;
    const col = Math.round((proj.east + halfWidth) / spacingMeters);
    const row = Math.round((-proj.north + halfWidth) / spacingMeters);
    const idx = row * gridSize + col;
    if (idx >= 0 && idx < points.length && points[idx]?.elevation != null) {
      groundH = points[idx].elevation! - originElevation;
    }
  }

  const buildingH = b.height ?? b.levels ? (b.levels ?? 5) * 3 : 20;
  const geom = new THREE.BoxGeometry(30, buildingH, 30);
  const mat = new THREE.MeshStandardMaterial({ color: '#f97316', roughness: 0.6, metalness: 0.1 });
  const mesh = new THREE.Mesh(geom, mat);
  mesh.position.set(proj.east, groundH + buildingH / 2, -proj.north);
  return mesh;
}

// ---------------------------------------------------------------------------
// Three.js Scene Component
// ---------------------------------------------------------------------------
interface Helipad3DSceneProps {
  center: Coordinate;
  elevation: number;
  fatoRegion: FATORegion | null;
  approachPolygon: Coordinate[] | null;
  takeoffPolygon: Coordinate[] | null;
  surfaceParams: VisualSurfaceResult | null;
  approachSurfaceParams: VisualSurfaceResult | null;
  takeoffSurfaceParams: VisualSurfaceResult | null;
  buildings: BuildingResult[];
  elevationData: ElevationGridData | null;
}

const Helipad3DScene: React.FC<Helipad3DSceneProps> = ({
  center,
  elevation,
  fatoRegion,
  approachPolygon,
  takeoffPolygon,
  surfaceParams,
  approachSurfaceParams,
  takeoffSurfaceParams,
  buildings,
  elevationData,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#dbeafe');
    const camera = new THREE.PerspectiveCamera(
      48,
      Math.max(container.clientWidth, 1) / Math.max(container.clientHeight, 1),
      1,
      15000,
    );
    camera.position.set(0, 5000, 6000);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(Math.max(container.clientWidth, 1), Math.max(container.clientHeight, 1));
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    controls.minDistance = 300;
    controls.maxDistance = 10000;
    controls.enableDamping = true;

    // Lighting
    scene.add(new THREE.AmbientLight('#ffffff', 0.9));
    const light = new THREE.DirectionalLight('#ffffff', 1.1);
    light.position.set(2000, 4500, 1500);
    scene.add(light);

    // Ground grid
    scene.add(createGroundGrid());

    // Terrain mesh
    const terrainMesh = elevationData
      ? buildTerrainMesh(elevationData, center, elevation)
      : null;
    if (terrainMesh) scene.add(terrainMesh);

    // FATO marker
    scene.add(createFATOMarker(center, center, elevation));

    // FATO region
    if (fatoRegion) {
      scene.add(createFATOSurface(center, fatoRegion, elevation));
    }

    // Approach / takeoff surfaces in 3D — sloped trapezoid segments (per-surface params)
    const appParams = approachSurfaceParams ?? surfaceParams;
    const tofParams = takeoffSurfaceParams ?? surfaceParams;
    if (approachPolygon && approachPolygon.length >= 4 && appParams?.stations?.length) {
      scene.add(createSlopedSurfacePolygon(center, approachPolygon, appParams.stations, '#1677ff'));
    }
    if (takeoffPolygon && takeoffPolygon.length >= 4 && tofParams?.stations?.length) {
      scene.add(createSlopedSurfacePolygon(center, takeoffPolygon, tofParams.stations, '#13a8a8'));
    }

    // Buildings
    buildings.forEach((b) => {
      const box = createBuildingBox(center, b, elevationData, elevation);
      if (box) scene.add(box);
    });

    // Resize handling
    const resizeObserver = new ResizeObserver(() => {
      const w = Math.max(container.clientWidth, 1);
      const h = Math.max(container.clientHeight, 1);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
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
      resizeObserver.disconnect();
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      scene.traverse((obj) => {
        const d = obj as THREE.Mesh;
        d.geometry?.dispose();
        if (Array.isArray(d.material)) d.material.forEach((m) => m.dispose());
        else d.material?.dispose();
      });
    };
  }, [center, elevation, fatoRegion, approachPolygon, takeoffPolygon, surfaceParams, buildings, elevationData]);

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />;
};

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
const Helipad3DView: React.FC<{ enabled: boolean }> = ({ enabled }) => {
  const {
    helipadCenter,
    fatoConfig,
    fatoRegion,
    approachPolygon,
    takeoffPolygon,
    surfaceParams,
    approachSurfaceParams,
    takeoffSurfaceParams,
  } = useHelipadStore();

  const [elevationData, setElevationData] = React.useState<ElevationGridData | null>(null);
  const [buildings, setBuildings] = React.useState<BuildingResult[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [msg, setMsg] = React.useState('');

  React.useEffect(() => {
    if (!enabled || !helipadCenter) return;
    setLoading(true);
    setMsg('正在加载地形和建筑数据...');

    Promise.all([
      fetchElevationGrid(helipadCenter).then(setElevationData).catch(() => {}),
      fetchHelipadBuildings(helipadCenter, fatoRegion, approachPolygon, takeoffPolygon)
        .then(setBuildings)
        .catch(() => {}),
    ]).finally(() => {
      setLoading(false);
      setMsg(
        `高程 ${elevationData?.validCount ?? '?'}/${elevationData?.totalCount ?? '?'}  ·  建筑 ${buildings.length}`
      );
    });
  }, [enabled, helipadCenter]);

  if (!helipadCenter) {
    return (
      <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', bgcolor: '#dbeafe' }}>
        <Alert severity="info">请先在二维地图上点击选择起降场中心点</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ position: 'relative', height: '100%', width: '100%', bgcolor: '#dbeafe' }}>
      {enabled && (
        <Helipad3DScene
          center={helipadCenter}
          elevation={fatoConfig.elevation}
          fatoRegion={fatoRegion}
          approachPolygon={approachPolygon}
          takeoffPolygon={takeoffPolygon}
          surfaceParams={surfaceParams}
          approachSurfaceParams={approachSurfaceParams}
          takeoffSurfaceParams={takeoffSurfaceParams}
          buildings={buildings}
          elevationData={elevationData}
        />
      )}
      {(loading) && (
        <Box sx={{ position: 'absolute', left: 12, top: 12, zIndex: 2 }}>
          <Alert severity="info" icon={<CircularProgress size={18} />}>{msg}</Alert>
        </Box>
      )}
      <Box sx={{
        position: 'absolute', left: 12, bottom: 12, zIndex: 2,
        px: 1.5, py: 0.75, borderRadius: 1,
        bgcolor: 'rgba(15,23,42,0.72)', color: '#fff',
      }}>
        <Typography variant="caption">
          建筑 {buildings.length} · 地形 {elevationData?.validCount ?? 0}/{elevationData?.totalCount ?? 0}
        </Typography>
      </Box>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Helper: fetch buildings using same polygon logic as store
// ---------------------------------------------------------------------------
async function fetchHelipadBuildings(
  center: Coordinate,
  fatoRegion: FATORegion | null,
  approachPolygon: Coordinate[] | null,
  takeoffPolygon: Coordinate[] | null,
): Promise<BuildingResult[]> {
  const polygons = [];
  if (fatoRegion) {
    const circlePts = generateCircleApprox(center, fatoRegion.radius, 24);
    polygons.push({ name: 'FATO', points: circlePts });
  }
  if (approachPolygon && approachPolygon.length >= 3) {
    polygons.push({ name: '进近面', points: approachPolygon });
  }
  if (takeoffPolygon && takeoffPolygon.length >= 3) {
    polygons.push({ name: '起飞爬升面', points: takeoffPolygon });
  }
  if (polygons.length === 0) return [];

  try {
    const req: BuildingSearchRequest = { polygons, mode: 'fast', pageSize: 10 };
    const result = await apiPost<BuildingSearchResponse>('/helipad/buildings', req);
    return result.places ?? [];
  } catch {
    return [];
  }
}

function generateCircleApprox(center: Coordinate, radius: number, count: number): Coordinate[] {
  const R = 6378137;
  const pts: Coordinate[] = [];
  for (let i = 0; i < count; i++) {
    const bearing = (i * 360) / count;
    const brng = (bearing * Math.PI) / 180;
    const d = radius / R;
    const lat1 = (center.latitude * Math.PI) / 180;
    const lon1 = (center.longitude * Math.PI) / 180;
    const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brng));
    const lon2 = lon1 + Math.atan2(Math.sin(brng) * Math.sin(d) * Math.cos(lat1), Math.cos(d) - Math.sin(lat1) * Math.sin(lat2));
    pts.push({
      latitude: (lat2 * 180) / Math.PI,
      longitude: ((lon2 * 180) / Math.PI + 540) % 360 - 180,
    });
  }
  return pts;
}

export default Helipad3DView;
