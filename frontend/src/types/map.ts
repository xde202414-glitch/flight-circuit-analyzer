import { Coordinate } from './runway';

export type BaseMapType =
  | 'osm'
  | 'tianditu-vector'
  | 'tianditu-image'
  | 'tianditu-terrain';

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
