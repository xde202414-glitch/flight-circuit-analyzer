/**
 * MapLibre GL JS 3D View — satellite imagery + terrain + 3D buildings
 *
 * Data sources:
 *   Satellite: 天地图 img_w (WMTS)
 *   Terrain:   星图地球数据云 Terrain-RGB (raster-dem)
 *   Labels:    天地图 cia_w (WMTS annotation overlay)
 */
import React from 'react';
import { Alert, Box, CircularProgress, Typography } from '@mui/material';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useHelipadStore } from '../../store/useHelipadStore';
import { useRunwayStore } from '../../store/useRunwayStore';
import type { Coordinate } from '../../types/runway';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const DEFAULT_CENTER: [number, number] = [120.1551, 30.2741];
const DEFAULT_ZOOM = 14;

/** localStorage key for geovis token (星图地球数据云) */
const GEOVIS_TOKEN_STORAGE_KEY = 'geovis_token';

// ---------------------------------------------------------------------------
// Tile URL builders — 天地图优先，星图备选
// ---------------------------------------------------------------------------

function tiandituSatURL(tk: string): string {
  return `https://t0.tianditu.gov.cn/img_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=img&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${tk}`;
}
function tiandituLblURL(tk: string): string {
  return `https://t0.tianditu.gov.cn/cia_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=cia&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${tk}`;
}
function geovisImgURL(token: string): string {
  return `https://tiles1.geovisearth.com/base/v1/img/{z}/{x}/{y}.png?token=${token}`;
}
function geovisLblURL(token: string): string {
  return `https://tiles1.geovisearth.com/base/v1/cia/{z}/{x}/{y}.png?token=${token}`;
}
function geovisTerrainURL(token: string): string {
  return `https://tiles1.geovisearth.com/base/v1/terrain_rgb/{z}/{x}/{y}.png?token=${token}`;
}

// ---------------------------------------------------------------------------
// Style
// ---------------------------------------------------------------------------
function buildStyle(tiandituKey?: string, geovisToken?: string): maplibregl.StyleSpecification {
  const hasTDT = Boolean(tiandituKey);
  const gv = geovisToken || '';
  return {
    version: 8,
    glyphs: 'https://fonts.openmaptiles.org/{fontstack}/{range}.pbf',
    sources: {
      'sat': {
        type: 'raster',
        tiles: hasTDT ? [tiandituSatURL(tiandituKey!)] : [geovisImgURL(gv)],
        tileSize: 256,
        maxzoom: 18,
      },
      'lbl': {
        type: 'raster',
        tiles: hasTDT ? [tiandituLblURL(tiandituKey!)] : [geovisLblURL(gv)],
        tileSize: 256,
        maxzoom: 18,
      },
      'terrain-dem': {
        type: 'raster-dem',
        tiles: [geovisTerrainURL(gv)],
        tileSize: 256,
        maxzoom: 15,
      },
    },
    layers: [
      { id: 'satellite', type: 'raster', source: 'sat' },
      { id: 'labels', type: 'raster', source: 'lbl' },
    ],
    terrain: { source: 'terrain-dem', exaggeration: 1.2 },
  };
}

// ---------------------------------------------------------------------------
// GeoJSON helpers for FATO / surfaces
// ---------------------------------------------------------------------------
function coordsToGeoJSONPolygon(coords: Coordinate[]): number[][][] {
  if (coords.length < 3) return [];
  const ring = coords.map((c) => [c.longitude, c.latitude] as [number, number]);
  ring.push(ring[0]); // close ring
  return [ring];
}

function circleGeoJSON(center: Coordinate, radiusM: number, n = 48): number[][][] {
  const R = 6378137;
  const ring: [number, number][] = [];
  for (let i = 0; i <= n; i++) {
    const bearing = (i * 360) / n;
    const br = (bearing * Math.PI) / 180;
    const d = radiusM / R;
    const lt = Math.asin(
      Math.sin((center.latitude * Math.PI) / 180) * Math.cos(d) +
        Math.cos((center.latitude * Math.PI) / 180) * Math.sin(d) * Math.cos(br),
    );
    const ln =
      (center.longitude * Math.PI) / 180 +
      Math.atan2(
        Math.sin(br) * Math.sin(d) * Math.cos((center.latitude * Math.PI) / 180),
        Math.cos(d) - Math.sin((center.latitude * Math.PI) / 180) * Math.sin(lt),
      );
    ring.push([((ln * 180) / Math.PI + 540) % 360 - 180, (lt * 180) / Math.PI]);
  }
  return [ring];
}

// ---------------------------------------------------------------------------
// Build sloped 3D surface strips from polygon + surface params
// ---------------------------------------------------------------------------

/**
 * Split a surface polygon into narrow quad strips along the flight direction.
 * Each strip has a 'height' property for fill-extrusion, creating a sloped 3D effect.
 *
 * Polygon layout from backend:
 *   [left_0, left_1, ..., left_{n-1}, right_{n-1}, ..., right_1, right_0]
 */
function buildSlopedSurfaceStrips(
  _center: Coordinate,
  polygon: Coordinate[],
  surfaceParams: { stations: Array<{ distance: number; width: number; height: number }> },
  _direction: number,
): GeoJSON.Feature[] {
  const stations = surfaceParams.stations;
  if (stations.length < 2 || polygon.length < 4) return [];

  const n = stations.length;
  const features: GeoJSON.Feature[] = [];

  for (let i = 0; i < n - 1; i++) {
    const left0 = polygon[i];
    const left1 = polygon[i + 1];
    const right0 = polygon[polygon.length - 1 - i];
    const right1 = polygon[polygon.length - 2 - i];

    const h0 = stations[i].height;
    const h1 = stations[i + 1].height;
    const avgH = (h0 + h1) / 2;

    features.push({
      type: 'Feature',
      properties: { height: Math.max(avgH, 0.5) },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [left0.longitude, left0.latitude],
          [left1.longitude, left1.latitude],
          [right1.longitude, right1.latitude],
          [right0.longitude, right0.latitude],
          [left0.longitude, left0.latitude],
        ]],
      },
    });
  }

  return features;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
type ViewMode = 'helipad' | 'runway';

/** Read geovis token from localStorage (set by user in 2D settings or browser console). */
function getStoredGeovisToken(): string {
  try {
    return localStorage.getItem(GEOVIS_TOKEN_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

interface MapLibre3DViewProps {
  mode: ViewMode;
  enabled: boolean;
  tiandituKey?: string;
}

const MapLibre3DView: React.FC<MapLibre3DViewProps> = ({ mode, enabled, tiandituKey }) => {
  const geovisToken = getStoredGeovisToken();
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const mapRef = React.useRef<maplibregl.Map | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  // State from stores
  const helipad = useHelipadStore();
  const runway = useRunwayStore();

  const center: [number, number] =
    mode === 'helipad' && helipad.helipadCenter
      ? [helipad.helipadCenter.longitude, helipad.helipadCenter.latitude]
      : runway.runwayParams?.coordinate
        ? [runway.runwayParams.coordinate.longitude, runway.runwayParams.coordinate.latitude]
        : DEFAULT_CENTER;

  // ------------------------------------------------------------------
  // Init / destroy map
  // ------------------------------------------------------------------
  React.useEffect(() => {
    if (!enabled || !containerRef.current) return;

    setLoading(true);
    setError(null);

    const style = buildStyle(tiandituKey, geovisToken);
    const map = new maplibregl.Map({
      container: containerRef.current,
      style,
      center,
      zoom: DEFAULT_ZOOM,
      pitch: 55,
      bearing: 0,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');

    map.on('load', () => setLoading(false));
    map.on('error', (e) => console.warn('MapLibre error:', e));

    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, [enabled]);

  // Update center when mode/location changes
  React.useEffect(() => {
    if (mapRef.current) {
      mapRef.current.flyTo({ center, zoom: DEFAULT_ZOOM, pitch: 55, duration: 1500 });
    }
  }, [center[0], center[1]]);

  // ------------------------------------------------------------------
  // Helipad 3D layers
  // ------------------------------------------------------------------
  React.useEffect(() => {
    const map = mapRef.current;
    if (!map || mode !== 'helipad') return;

    const addLayers = () => {
      // Remove previous
      const ids = [
        'fato-3d', 'fato-line',
        'approach-3d', 'approach-line',
        'takeoff-3d', 'takeoff-line',
        'center-marker',
      ];
      ids.forEach((id) => {
        if (map.getLayer(id)) map.removeLayer(id);
        if (map.getSource(id)) map.removeSource(id);
      });

      if (!helipad.fatoRegion || !helipad.helipadCenter) return;

      const c = helipad.helipadCenter!;
      const appSp = helipad.approachSurfaceParams ?? helipad.surfaceParams;
      const tofSp = helipad.takeoffSurfaceParams ?? helipad.surfaceParams;

      // ---- FATO (flat) ----
      const fatoGeo = helipad.fatoRegion.shape === 'circle'
        ? { type: 'Polygon' as const, coordinates: circleGeoJSON(c, helipad.fatoRegion.radius, 48) }
        : { type: 'Polygon' as const, coordinates: coordsToGeoJSONPolygon(helipad.fatoPolygon || []) };

      map.addSource('fato', { type: 'geojson', data: fatoGeo });
      map.addLayer({
        id: 'fato-3d', type: 'fill-extrusion', source: 'fato',
        paint: {
          'fill-extrusion-color': '#0066ff',
          'fill-extrusion-opacity': 0.4,
          'fill-extrusion-height': 3,
          'fill-extrusion-base': 0,
        },
      });
      map.addLayer({
        id: 'fato-line', type: 'line', source: 'fato',
        paint: { 'line-color': '#0066ff', 'line-width': 2 },
      });

      // ---- Approach surface (3D sloped) ----
      if (helipad.approachPolygon && helipad.approachPolygon.length >= 3 && appSp) {
        const strips = buildSlopedSurfaceStrips(
          c, helipad.approachPolygon, appSp, helipad.fatoConfig.flightDirection,
        );
        map.addSource('approach', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: strips },
        });
        map.addLayer({
          id: 'approach-3d', type: 'fill-extrusion', source: 'approach',
          paint: {
            'fill-extrusion-color': '#1677ff',
            'fill-extrusion-opacity': 0.45,
            'fill-extrusion-height': ['get', 'height'],
            'fill-extrusion-base': 0,
          },
        });
        map.addLayer({
          id: 'approach-line', type: 'line', source: 'approach',
          paint: { 'line-color': '#1677ff', 'line-width': 1.5 },
        });
      }

      // ---- Takeoff surface (3D sloped, opposite direction) ----
      if (helipad.takeoffPolygon && helipad.takeoffPolygon.length >= 3 && tofSp) {
        const strips = buildSlopedSurfaceStrips(
          c, helipad.takeoffPolygon, tofSp,
          (helipad.fatoConfig.flightDirection + 180) % 360,
        );
        map.addSource('takeoff', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: strips },
        });
        map.addLayer({
          id: 'takeoff-3d', type: 'fill-extrusion', source: 'takeoff',
          paint: {
            'fill-extrusion-color': '#13a8a8',
            'fill-extrusion-opacity': 0.45,
            'fill-extrusion-height': ['get', 'height'],
            'fill-extrusion-base': 0,
          },
        });
        map.addLayer({
          id: 'takeoff-line', type: 'line', source: 'takeoff',
          paint: { 'line-color': '#13a8a8', 'line-width': 1.5 },
        });
      }

      // ---- Center marker ----
      map.addSource('center-point', {
        type: 'geojson',
        data: { type: 'Point', coordinates: [c.longitude, c.latitude] },
      });
      map.addLayer({
        id: 'center-marker', type: 'circle', source: 'center-point',
        paint: {
          'circle-radius': 8, 'circle-color': '#0066ff',
          'circle-stroke-width': 2, 'circle-stroke-color': '#fff',
        },
      });
    };

    if (map.loaded()) {
      addLayers();
    } else {
      map.once('load', addLayers);
    }
  }, [mode, helipad.fatoRegion, helipad.approachPolygon, helipad.takeoffPolygon,
      helipad.helipadCenter, helipad.surfaceParams, helipad.fatoPolygon]);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <Box sx={{ position: 'relative', height: '100%', width: '100%' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
      {loading && (
        <Box sx={{ position: 'absolute', left: 12, top: 12, zIndex: 10 }}>
          <Alert severity="info" icon={<CircularProgress size={18} />}>
            正在加载三维地图...
          </Alert>
        </Box>
      )}
      {error && (
        <Box sx={{ position: 'absolute', left: 12, top: 12, zIndex: 10 }}>
          <Alert severity="error">{error}</Alert>
        </Box>
      )}
      <Box sx={{
        position: 'absolute', left: 12, bottom: 24, zIndex: 10,
        px: 1.5, py: 0.5, borderRadius: 1,
        bgcolor: 'rgba(0,0,0,0.7)', color: '#fff',
      }}>
        <Typography variant="caption">
          {tiandituKey ? '天地图' : '星图'}卫星 · 地形 · 右键旋转 · 滚轮缩放 · Ctrl+拖拽倾斜
        </Typography>
      </Box>
    </Box>
  );
};

export default MapLibre3DView;
