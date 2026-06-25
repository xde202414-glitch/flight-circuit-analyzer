import { Coordinate } from './runway';

export type BaseMapType =
  | 'osm'
  | 'tianditu-vector'
  | 'tianditu-image'
  | 'tianditu-terrain';

/** 3D scene base map mode */
export type Terrain3DMode = 'terrain' | 'buildings';

export type PoiSource = 'tianditu' | 'osm';

export interface MapConfig {
  defaultCenter: Coordinate;
  defaultZoom: number;
  tiandituKey?: string;
  geovisToken?: string;
}

export interface PoiSearchBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

export interface PoiSearchResult {
  id: string;
  name: string;
  address?: string;
  coordinate: Coordinate;
  source: PoiSource;
}

export const BASE_MAP_LABELS: Record<BaseMapType, string> = {
  osm: 'OpenStreetMap',
  'tianditu-vector': '天地图矢量',
  'tianditu-image': '天地图影像',
  'tianditu-terrain': '天地图地形',
};

export const BASE_MAP_TYPES: BaseMapType[] = [
  'osm',
  'tianditu-vector',
  'tianditu-image',
  'tianditu-terrain',
];

export function isBaseMapType(value: string | null): value is BaseMapType {
  return BASE_MAP_TYPES.includes(value as BaseMapType);
}

// ---------------------------------------------------------------------------
// Scale bar
// ---------------------------------------------------------------------------

export type ScaleUnit = 'm' | 'km' | 'ft' | 'NM';

export interface ScaleUnitDef {
  value: ScaleUnit;
  label: string;
  /** meters per unit */
  metersPerUnit: number;
}

export const SCALE_UNITS: ScaleUnitDef[] = [
  { value: 'm', label: '米 (m)', metersPerUnit: 1 },
  { value: 'km', label: '公里 (km)', metersPerUnit: 1000 },
  { value: 'ft', label: '英尺 (ft)', metersPerUnit: 0.3048 },
  { value: 'NM', label: '海里 (NM)', metersPerUnit: 1852 },
];

/** Preset scale ratios for quick selection */
export const SCALE_PRESETS = [500, 1000, 2000, 5000, 10000, 25000, 50000];
