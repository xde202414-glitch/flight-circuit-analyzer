/**
 * Enhanced 3D View — satellite-imaged terrain, realistic lighting, extruded buildings.
 *
 * Satellite tiles via 天地图 WMTS (img_w layer). Elevation via 星图地球数据云.
 */
import React from 'react';
import { Alert, Box, CircularProgress, Typography } from '@mui/material';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { useHelipadStore } from '../../store/useHelipadStore';
import { useMapSettingsStore } from '../../store/useMapSettingsStore';
import { fetchElevationGrid, type ElevationGridData } from '../../utils/elevationGrid';
import { buildSatelliteTexture } from '../../utils/satelliteTile';
import ThreeScaleBar from './ThreeScaleBar';
import { apiPost } from '../../api/client';
import type { Coordinate } from '../../types/runway';
import { type Terrain3DMode } from '../../types/map';
import type { BuildingResult, BuildingSearchRequest, BuildingSearchResponse, FATORegion, SurfaceStation, VisualSurfaceResult } from '../../types/helipad';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const EARTH_RADIUS_M = 6378137;
const AIRSPACE_RADIUS_M = 5000;
const SATELLITE_ZOOM = 15;

// ---------------------------------------------------------------------------
// Mercator helpers
// ---------------------------------------------------------------------------
function lonToTileX(lon: number, z: number): number {
  return ((lon + 180) / 360) * Math.pow(2, z);
}
function latToTileY(lat: number, z: number): number {
  const rad = (lat * Math.PI) / 180;
  return ((1 - Math.asinh(Math.tan(rad)) / Math.PI) / 2) * Math.pow(2, z);
}
// tileXToLon / tileYToLat reserved for future use in tile bounds computation

// ---------------------------------------------------------------------------
// Geo ↔ local projection
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
// Satellite tile fetching & canvas stitching
// ---------------------------------------------------------------------------
interface TileRect {
  minX: number; maxX: number;
  minY: number; maxY: number;
  zoom: number;
}

function computeTileRect(
  bounds: { north: number; south: number; west: number; east: number },
  zoom: number,
): TileRect {
  const minX = Math.floor(lonToTileX(bounds.west, zoom));
  const maxX = Math.floor(lonToTileX(bounds.east, zoom));
  const minY = Math.floor(latToTileY(bounds.north, zoom));
  const maxY = Math.floor(latToTileY(bounds.south, zoom));
  return { minX, maxX, minY, maxY, zoom };
}

/** Compute UV for a geographic point within the tile rect. */
function geoToUV(
  lat: number, lon: number,
  rect: TileRect,
): [number, number] {
  // Tile-space x,y for this lat/lon at the given zoom
  const tx = lonToTileX(lon, rect.zoom);
  const ty = latToTileY(lat, rect.zoom);
  // Fractional position within the tile rect
  const u = (tx - rect.minX) / (rect.maxX - rect.minX + 1);
  const v = (ty - rect.minY) / (rect.maxY - rect.minY + 1);
  return [u, v];
}

// ---------------------------------------------------------------------------
// Scene builders
// ---------------------------------------------------------------------------
function createSkyGradient(scene: THREE.Scene): void {
  // Simple gradient background using scene background color + fog
  scene.background = new THREE.Color('#1a1a2e');
  scene.fog = new THREE.Fog('#1a1a2e', 3000, 14000);
}

function createLighting(scene: THREE.Scene): void {
  // Ambient
  scene.add(new THREE.AmbientLight('#bcd4f0', 0.7));
  // Sun
  const sun = new THREE.DirectionalLight('#fff8e7', 1.8);
  sun.position.set(3000, 5000, 2000);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.camera.left = -6000;
  sun.shadow.camera.right = 6000;
  sun.shadow.camera.top = 6000;
  sun.shadow.camera.bottom = -6000;
  sun.shadow.camera.near = 100;
  sun.shadow.camera.far = 20000;
  scene.add(sun);
  // Fill light
  const fill = new THREE.DirectionalLight('#aaccff', 0.4);
  fill.position.set(-1000, 2000, -1000);
  scene.add(fill);
}

function createGroundPlane(): THREE.Mesh {
  const geo = new THREE.PlaneGeometry(AIRSPACE_RADIUS_M * 2.5, AIRSPACE_RADIUS_M * 2.5);
  const mat = new THREE.MeshStandardMaterial({
    color: '#2a2a2a',
    roughness: 0.9,
    metalness: 0,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = -1;
  mesh.receiveShadow = true;
  return mesh;
}

function createTerrainWithTexture(
  elevationData: ElevationGridData,
  origin: Coordinate,
  originElevation: number,
  satelliteTexture: THREE.Texture | null,
  bounds: { north: number; south: number; west: number; east: number },
): THREE.Mesh | null {
  const { points, gridSize, spacingMeters } = elevationData;
  if (points.length === 0) return null;

  const width = (gridSize - 1) * spacingMeters;
  const geom = new THREE.PlaneGeometry(width, width, gridSize - 1, gridSize - 1);

  const positions = geom.attributes.position;
  const uvs = new Float32Array(positions.count * 2);

  const heights: (number | null)[] = new Array(positions.count);
  let hasHeight = false;

  // Compute tile rect for UV mapping
  const rect = computeTileRect(bounds, SATELLITE_ZOOM);

  for (let i = 0; i < positions.count; i++) {
    const x = positions.getX(i);
    const z = positions.getY(i);

    const row = Math.round((z / width + 0.5) * (gridSize - 1));
    const col = Math.round((x / width + 0.5) * (gridSize - 1));
    const idx = row * gridSize + col;

    let h: number | null = null;
    if (idx >= 0 && idx < points.length && points[idx]?.elevation != null) {
      h = points[idx].elevation! - originElevation;
      hasHeight = true;
    }
    heights[i] = h;

    // Compute UV from geographic position
    const lat = origin.latitude + (z / EARTH_RADIUS_M) * (180 / Math.PI);
    const lon = origin.longitude + (x / (EARTH_RADIUS_M * Math.cos((origin.latitude * Math.PI) / 180))) * (180 / Math.PI);
    const [u, v] = geoToUV(lat, lon, rect);
    uvs[i * 2] = u;
    uvs[i * 2 + 1] = 1 - v;
  }

  if (!hasHeight) return null;

  for (let i = 0; i < positions.count; i++) {
    const h = heights[i];
    positions.setZ(i, h ?? 0);
  }

  geom.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  geom.computeVertexNormals();
  geom.rotateX(-Math.PI / 2);

  const mat = satelliteTexture
    ? new THREE.MeshStandardMaterial({
        map: satelliteTexture,
        roughness: 0.65,
        metalness: 0.05,
        color: '#ffffff',
      })
    : new THREE.MeshPhongMaterial({
        vertexColors: false,
        color: '#607848',
        flatShading: false,
        shininess: 5,
      });

  const mesh = new THREE.Mesh(geom, mat);
  mesh.name = 'terrain';
  mesh.receiveShadow = true;
  mesh.castShadow = true;
  return mesh;
}

// FATO + surface builders (simplified, same logic as Helipad3DView)
function createFATOMarker3D(origin: Coordinate, center: Coordinate): THREE.Group {
  const group = new THREE.Group();
  const pos = toVec3(origin, center, 30);
  const sphere = new THREE.Mesh(
    new THREE.SphereGeometry(40, 16, 16),
    new THREE.MeshStandardMaterial({ color: '#0066ff', emissive: '#001166', emissiveIntensity: 0.5 }),
  );
  sphere.position.copy(pos);
  sphere.castShadow = true;
  group.add(sphere);

  const lineGeo = new THREE.BufferGeometry().setFromPoints([pos.clone(), toVec3(origin, center, 0)]);
  group.add(new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: '#0066ff' })));
  return group;
}

function createFATORing3D(origin: Coordinate, center: Coordinate, radius: number): THREE.Group {
  const group = new THREE.Group();
  const n = 64;
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i <= n; i++) {
    const bearing = (i * 360) / n;
    const br = (bearing * Math.PI) / 180;
    const d = radius;
    const lat = center.latitude + (d / EARTH_RADIUS_M) * (180 / Math.PI) * Math.cos(br);
    const lon = center.longitude + (d / (EARTH_RADIUS_M * Math.cos((center.latitude * Math.PI) / 180))) * (180 / Math.PI) * Math.sin(br);
    pts.push(toVec3(origin, { latitude: lat, longitude: lon }, 0.8));
  }
  const geo = new THREE.BufferGeometry().setFromPoints(pts);
  group.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color: '#0066ff', linewidth: 1 })));

  // Filled
  const shape = new THREE.Shape(pts.map((p) => new THREE.Vector2(p.x, p.z)));
  const mesh = new THREE.Mesh(
    new THREE.ShapeGeometry(shape),
    new THREE.MeshStandardMaterial({ color: '#0066ff', transparent: true, opacity: 0.15, depthWrite: false }),
  );
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = 0.6;
  mesh.receiveShadow = true;
  group.add(mesh);
  return group;
}

/**
 * Create a sloped 3D approach/takeoff surface from polygon + station heights.
 *
 * Polygon layout from backend:
 *   [left_0, left_1, …, left_{N-1}, right_{N-1}, …, right_1, right_0]
 *
 * Each pair of consecutive stations forms a sloped trapezoid volume.
 * Mirrors the runway Map3DView's createSlopedTrapezoid pattern.
 */
function createSlopedSurface3D(
  origin: Coordinate,
  polygon: Coordinate[],
  stations: SurfaceStation[],
  color: string,
): THREE.Group {
  const group = new THREE.Group();
  if (polygon.length < 4 || stations.length < 2) return group;

  const N = stations.length;
  const GND = 0.3;

  const mat = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.55,
    metalness: 0.1,
    transparent: true,
    opacity: 0.22,
    depthWrite: false,
    side: THREE.DoubleSide,
  });

  for (let i = 0; i < N - 1; i++) {
    const innerY = stations[i].height;
    const outerY = stations[i + 1].height;
    if (outerY <= 0 && innerY <= 0) continue;

    // Four corners
    const left0 = polygon[i];
    const left1 = polygon[i + 1];
    const right0 = polygon[polygon.length - 1 - i];
    const right1 = polygon[polygon.length - 2 - i];

    // Top vertices — sloped surface
    const t0 = toVec3(origin, left0, innerY);
    const t1 = toVec3(origin, right0, innerY);
    const t2 = toVec3(origin, right1, outerY);
    const t3 = toVec3(origin, left1, outerY);

    // Bottom — at ground
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
      0, 1, 2, 0, 2, 3,  // top (sloped)
      4, 6, 5, 4, 7, 6,  // bottom
      4, 7, 3, 4, 3, 0,  // left wall
      7, 6, 2, 7, 2, 3,  // outer wall
      6, 5, 1, 6, 1, 2,  // right wall
    ]);
    geo.computeVertexNormals();

    const mesh = new THREE.Mesh(geo, mat);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.isHelipadSurface = true;
    group.add(mesh);

    // Edge lines
    const lineGeo = new THREE.BufferGeometry().setFromPoints([t0, t1, t2, t3, t0]);
    group.add(new THREE.Line(
      lineGeo,
      new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.55, depthTest: true }),
    ));
  }

  return group;
}

function buildingColorByHeight(h: number): string {
  if (h <= 6) return '#e8e8e8';
  if (h <= 15) return '#dcdcdc';
  if (h <= 30) return '#cfcfcf';
  if (h <= 60) return '#bfbfbf';
  if (h <= 100) return '#adadad';
  return '#9a9a9a';
}

function createBuildingMesh3D(
  origin: Coordinate,
  b: BuildingResult,
  elevationData: ElevationGridData | null,
  originElevation: number,
  mode: Terrain3DMode = 'terrain',
): THREE.Group | null {
  const group = new THREE.Group();
  const coord: Coordinate = { latitude: b.latitude, longitude: b.longitude };
  const proj = projectCoord(origin, coord);

  let groundH = 0;
  if (mode === 'terrain' && elevationData) {
    const { points, gridSize, spacingMeters } = elevationData;
    const halfW = ((gridSize - 1) * spacingMeters) / 2;
    const col = Math.round((proj.east + halfW) / spacingMeters);
    const row = Math.round((-proj.north + halfW) / spacingMeters);
    const idx = row * gridSize + col;
    if (idx >= 0 && idx < points.length && points[idx]?.elevation != null) {
      groundH = points[idx].elevation! - originElevation;
    }
  }

  const h = b.height ?? (b.levels ? b.levels * 3 : 15);
  const w = b.boundary ? 20 : 18;
  const d = b.boundary ? 20 : 18;

  const geom = new THREE.BoxGeometry(w, h, d);
  const color = mode === 'buildings' ? buildingColorByHeight(h) : '#94a3b8';
  const mat = mode === 'buildings'
    ? new THREE.MeshStandardMaterial({ color, roughness: 0.35, metalness: 0.02 })
    : new THREE.MeshStandardMaterial({ color: '#94a3b8', roughness: 0.55, metalness: 0.3 });
  const mesh = new THREE.Mesh(geom, mat);
  mesh.position.set(proj.east, groundH + h / 2, -proj.north);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  return group;
}

// ---------------------------------------------------------------------------
// Scene
// ---------------------------------------------------------------------------
interface SceneProps {
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
  tiandituKey: string;
  terrain3DMode: Terrain3DMode;
  onCameraReady?: (cam: THREE.PerspectiveCamera, el: HTMLElement) => void;
}

const EnhancedScene: React.FC<SceneProps> = ({
  center, elevation, fatoRegion, approachPolygon, takeoffPolygon,
  surfaceParams, approachSurfaceParams, takeoffSurfaceParams,
  buildings, elevationData, tiandituKey, terrain3DMode, onCameraReady,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const scene = new THREE.Scene();
    createSkyGradient(scene);

    const camera = new THREE.PerspectiveCamera(
      50,
      Math.max(container.clientWidth, 1) / Math.max(container.clientHeight, 1),
      10, 20000,
    );
    camera.position.set(3500, 4500, 5000);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(Math.max(container.clientWidth, 1), Math.max(container.clientHeight, 1));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 200, 0);
    controls.minDistance = 400;
    controls.maxDistance = 10000;
    controls.maxPolarAngle = Math.PI * 0.48;
    controls.enableDamping = true;
    controls.dampingFactor = 0.1;

    onCameraReady?.(camera, container);

    createLighting(scene);

    const isBuildingsMode = terrain3DMode === 'buildings';
    const bounds = computeAreaBounds(center, AIRSPACE_RADIUS_M);

    if (isBuildingsMode) {
      // Flat satellite ground plane for buildings mode
      const groundGeo = new THREE.PlaneGeometry(AIRSPACE_RADIUS_M * 3, AIRSPACE_RADIUS_M * 3);
      const groundMat = new THREE.MeshStandardMaterial({ color: '#3a3a3a', roughness: 0.95 });
      const groundPlane = new THREE.Mesh(groundGeo, groundMat);
      groundPlane.rotation.x = -Math.PI / 2;
      groundPlane.position.y = -2;
      groundPlane.receiveShadow = true;
      groundPlane.name = 'satellite-ground';
      scene.add(groundPlane);

      if (tiandituKey) {
        buildSatelliteTexture(bounds, tiandituKey).then((tex) => {
          if (tex) {
            groundMat.map = tex;
            groundMat.color.set('#ffffff');
            groundMat.needsUpdate = true;
          }
        });
      }
    } else {
      scene.add(createGroundPlane());

      // Load satellite texture asynchronously onto terrain
      if (tiandituKey) {
        buildSatelliteTexture(bounds, tiandituKey).then((tex) => {
          if (tex) {
            scene.traverse((obj) => {
              if (obj.name === 'terrain' && obj instanceof THREE.Mesh) {
                (obj.material as THREE.MeshStandardMaterial).map = tex;
                (obj.material as THREE.MeshStandardMaterial).color.set('#ffffff');
                (obj.material as THREE.MeshStandardMaterial).needsUpdate = true;
              }
            });
          }
        });
      }

      // Terrain mesh (only in terrain mode)
      const terrainMesh = elevationData
        ? createTerrainWithTexture(elevationData, center, elevation, null, bounds)
        : null;
      if (terrainMesh) scene.add(terrainMesh);
    }

    // FATO
    scene.add(createFATOMarker3D(center, center));
    if (fatoRegion) {
      scene.add(createFATORing3D(center, center, fatoRegion.radius));
    }

    // Approach / takeoff surfaces — sloped trapezoid segments (per-surface params)
    const appParams = approachSurfaceParams ?? surfaceParams;
    const tofParams = takeoffSurfaceParams ?? surfaceParams;
    if (approachPolygon && approachPolygon.length >= 4 && appParams?.stations?.length) {
      scene.add(createSlopedSurface3D(center, approachPolygon, appParams.stations, '#1677ff'));
    }
    if (takeoffPolygon && takeoffPolygon.length >= 4 && tofParams?.stations?.length) {
      scene.add(createSlopedSurface3D(center, takeoffPolygon, tofParams.stations, '#13a8a8'));
    }

    // Buildings
    buildings.forEach((b) => {
      const mesh = createBuildingMesh3D(center, b, elevationData, elevation, terrain3DMode);
      if (mesh) scene.add(mesh);
    });

    // Resize
    const ro = new ResizeObserver(() => {
      const w = Math.max(container.clientWidth, 1);
      const h = Math.max(container.clientHeight, 1);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });
    ro.observe(container);

    let frameId = 0;
    const render = () => {
      controls.update();
      renderer.render(scene, camera);
      frameId = window.requestAnimationFrame(render);
    };
    render();

    return () => {
      window.cancelAnimationFrame(frameId);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      scene.traverse((obj) => {
        const d = obj as THREE.Mesh;
        d.geometry?.dispose();
        const mats = Array.isArray(d.material) ? d.material : [d.material];
        mats.forEach((m) => { m?.dispose(); });
      });
    };
  }, [center, elevation, fatoRegion, approachPolygon, takeoffPolygon, surfaceParams, buildings, elevationData, tiandituKey, terrain3DMode]);

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />;
};

function computeAreaBounds(center: Coordinate, radiusM: number) {
  const dLat = radiusM / 111320;
  const dLon = radiusM / (111320 * Math.max(Math.cos((center.latitude * Math.PI) / 180), 0.1));
  return {
    north: center.latitude + dLat,
    south: center.latitude - dLat,
    west: center.longitude - dLon,
    east: center.longitude + dLon,
  };
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
const Enhanced3DView: React.FC<{ enabled: boolean }> = ({ enabled }) => {
  const {
    helipadCenter, fatoConfig, fatoRegion,
    approachPolygon, takeoffPolygon,
    surfaceParams, approachSurfaceParams, takeoffSurfaceParams,
  } = useHelipadStore();
  const tiandituKey = useMapSettingsStore((s) => s.tiandituKey);
  const terrain3DMode = useMapSettingsStore((s) => s.terrain3DMode);

  const scaleUnit = useMapSettingsStore((s) => s.scaleUnit);
  const [cameraInfo, setCameraInfo] = React.useState<{ cam: THREE.PerspectiveCamera; el: HTMLElement } | null>(null);

  const [elevationData, setElevationData] = React.useState<ElevationGridData | null>(null);
  const [buildings, setBuildings] = React.useState<BuildingResult[]>([]);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!enabled || !helipadCenter) return;
    setLoading(true);
    Promise.all([
      fetchElevationGrid(helipadCenter).then(setElevationData).catch(() => {}),
      fetchBuildings(helipadCenter, fatoRegion, approachPolygon, takeoffPolygon)
        .then(setBuildings).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, [enabled, helipadCenter]);

  if (!helipadCenter) {
    return (
      <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', bgcolor: '#1a1a2e' }}>
        <Alert severity="info">请先在二维地图上点击选择起降场中心点</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ position: 'relative', height: '100%', width: '100%', bgcolor: '#1a1a2e' }}>
      {enabled && (
        <EnhancedScene
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
          tiandituKey={tiandituKey}
          terrain3DMode={terrain3DMode}
          onCameraReady={(cam, el) => setCameraInfo({ cam, el })}
        />
      )}
      {loading && (
        <Box sx={{ position: 'absolute', left: 12, top: 12, zIndex: 2 }}>
          <Alert severity="info" icon={<CircularProgress size={18} />}>
            正在加载地形与卫星影像...
          </Alert>
        </Box>
      )}
      {cameraInfo && (
        <ThreeScaleBar camera={cameraInfo.cam} container={cameraInfo.el} unit={scaleUnit} />
      )}
      <Box sx={{
        position: 'absolute', right: 12, bottom: 12, zIndex: 2,
        px: 1.5, py: 0.75, borderRadius: 1,
        bgcolor: 'rgba(15,23,42,0.8)', color: '#fff',
      }}>
        <Typography variant="caption">
          {terrain3DMode === 'buildings' ? '建筑群' : '地形'}
          {' · '}高程 {elevationData?.validCount ?? 0}/{elevationData?.totalCount ?? 0}
          {' · '}建筑 {buildings.length}
          {' · '}卫星影像: {tiandituKey ? '天地图' : '关闭'}
          {' · '}拖拽旋转 · 滚轮缩放
        </Typography>
      </Box>
    </Box>
  );
};

async function fetchBuildings(
  center: Coordinate,
  fatoRegion: FATORegion | null,
  approachPolygon: Coordinate[] | null,
  takeoffPolygon: Coordinate[] | null,
): Promise<BuildingResult[]> {
  const polygons = [];
  if (fatoRegion) {
    polygons.push({ name: 'FATO', points: circleApprox(center, fatoRegion.radius, 24) });
  }
  if (approachPolygon?.length) polygons.push({ name: '进近面', points: approachPolygon });
  if (takeoffPolygon?.length) polygons.push({ name: '起飞爬升面', points: takeoffPolygon });
  if (!polygons.length) return [];
  try {
    const req: BuildingSearchRequest = { polygons, mode: 'fast', pageSize: 10 };
    const r = await apiPost<BuildingSearchResponse>('/helipad/buildings', req);
    return r.places ?? [];
  } catch { return []; }
}

function circleApprox(c: Coordinate, r: number, n: number): Coordinate[] {
  const R = 6378137; const pts: Coordinate[] = [];
  for (let i = 0; i < n; i++) {
    const b = (i * 360) / n; const br = (b * Math.PI) / 180; const d = r / R;
    const lt = Math.asin(Math.sin(c.latitude * Math.PI / 180) * Math.cos(d) + Math.cos(c.latitude * Math.PI / 180) * Math.sin(d) * Math.cos(br));
    const ln = c.longitude * Math.PI / 180 + Math.atan2(Math.sin(br) * Math.sin(d) * Math.cos(c.latitude * Math.PI / 180), Math.cos(d) - Math.sin(c.latitude * Math.PI / 180) * Math.sin(lt));
    pts.push({ latitude: (lt * 180) / Math.PI, longitude: ((ln * 180) / Math.PI + 540) % 360 - 180 });
  }
  return pts;
}

export default Enhanced3DView;
