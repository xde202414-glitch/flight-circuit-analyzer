/**
 * Helipad / FATO analysis TypeScript types.
 *
 * Mirror the backend models in backend/app/models/helipad.py
 * (camelCase response fields via alias_generator=to_camel).
 */
import type { Coordinate } from './runway';

// ---------------------------------------------------------------------------
// FATO Config
// ---------------------------------------------------------------------------

export type FATOSlopeType = 'A' | 'B' | 'C';
export type FATOShape = 'circle' | 'square';
export type OperationMode = 'day' | 'night';

export interface FATOConfig {
  shape: FATOShape;
  diameter: number;
  rotorDiameter: number;
  elevation: number;
  flightDirection: number;        // 进近面水平方向 (0-360°)
  takeoffDirection?: number | null; // 起飞面水平方向，不设则自动 = flightDirection + 180°
  slopeType: FATOSlopeType;
  operationMode: OperationMode;
}

// ---------------------------------------------------------------------------
// Surface calculation
// ---------------------------------------------------------------------------

export interface VisualSurfaceSegment {
  length: number;   // metres
  slope: number;    // ratio (e.g. 0.045 = 4.5%)
}

export interface SurfaceStation {
  distance: number;  // from inner edge
  width: number;     // at this distance
  height: number;    // relative control height
}

export interface VisualSurfaceResult {
  slopeType: FATOSlopeType;
  slopeLabel: string;
  operationMode: OperationMode;
  divergence: number;         // 0.10 day / 0.15 night
  innerWidth: number;
  outerWidth: number;
  outerWidthMultiplier: number; // 7 or 10
  rotorDiameter: number;
  maxHeight: number;
  totalLength: number;
  segments: VisualSurfaceSegment[];
  stations: SurfaceStation[];
  transitionSurface: {
    slope: number;
    height: number;
  };
}

export interface FATORegion {
  center: Coordinate;
  shape: FATOShape;
  direction: number;
  diameter: number;
  radius: number;
  safetySize: number;
  safetyRadius: number;
  safetyWidth: number;
}

export interface HelipadCalculateRequest {
  center: Coordinate;
  config: FATOConfig;
}

export interface HelipadCalculateResponse {
  fatoRegion: FATORegion;
  surfaceParams?: VisualSurfaceResult | null;         // legacy (uses approach params)
  approachSurfaceParams?: VisualSurfaceResult | null; // approach-specific
  takeoffSurfaceParams?: VisualSurfaceResult | null;  // takeoff-specific
  approachPolygon: Coordinate[];
  takeoffPolygon: Coordinate[];
  fatoPolygon: Coordinate[];
  fatoCircles: Array<{
    latitude: number;
    longitude: number;
    radius: number;
  }>;
}

// ---------------------------------------------------------------------------
// Building search
// ---------------------------------------------------------------------------

export interface PolygonRegion {
  name: string;
  points: Coordinate[];
}

export interface BuildingResult {
  id: string;
  name: string;
  category: string;
  address: string;
  latitude: number;
  longitude: number;
  source: string;
  height?: number | null;
  levels?: number | null;
  boundary?: Coordinate[] | null;
}

export interface BuildingSearchRequest {
  polygons: PolygonRegion[];
  mode: 'fast' | 'full';
  keywords?: string[];
  pageSize?: number;
}

export interface BuildingSearchResponse {
  places: BuildingResult[];
  source: string;
  searchedRegions: string[];
  warnings: string[];
}

// ---------------------------------------------------------------------------
// Elevation / terrain analysis
// ---------------------------------------------------------------------------

export interface TerrainExceedance {
  latitude: number;
  longitude: number;
  surfaceName: string;
  groundElevation: number;
  controlElevation: number;
  exceedance: number;
  cellPoints: Coordinate[];
}

export interface TerrainAnalysisRequest {
  fatoCenter: Coordinate;
  fatoElevation: number;
  surfaceParams: VisualSurfaceResult;
  fatoRegion: FATORegion;
  flightDirection: number;
}

export interface TerrainAnalysisResponse {
  sampleCount: number;
  exceeded: TerrainExceedance[];
  failedCount: number;
  message: string;
}
