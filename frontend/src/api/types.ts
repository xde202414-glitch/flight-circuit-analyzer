/**
 * API type definitions matching backend models
 */
import { RunwayParams, RunwayValidationResult } from '../types/runway';
import { Aircraft } from '../types/aircraft';
import {
  GeometryPreviewRequest, GeometryPreviewResponse,
  ParameterPreviewResponse, TrackConfig, TrackResult, TrackRequest,
} from '../types/track';
import { Coordinate } from '../types/runway';

export type { RunwayValidationResult, TrackResult, TrackConfig, TrackRequest };

export interface CoordinateTransformRequest {
  coordinate: Coordinate;
  fromSystem: 'WGS84' | 'GCJ02';
  toSystem: 'WGS84' | 'GCJ02';
}

export interface CoordinateTransformResponse {
  coordinate: Coordinate;
  originalSystem: 'WGS84' | 'GCJ02';
  targetSystem: 'WGS84' | 'GCJ02';
}

export type RunwayValidateRequest = RunwayParams;
export type RunwayValidateResponse = RunwayValidationResult;
export type AircraftListResponse = { aircrafts: Aircraft[]; total: number };
export type AircraftDetailResponse = Aircraft;
export type TrackCalculateRequest = TrackRequest;
export type TrackCalculateResponse = TrackResult;
export type TrackGeometryPreviewRequest = GeometryPreviewRequest;
export type TrackGeometryPreviewResponse = GeometryPreviewResponse;
export type TrackParameterPreviewResponse = ParameterPreviewResponse;

// ====== Route 10 Types ======

export interface RouteInfo {
  id: number; name: string;
  flight_width: number; protection_width: number;
  bottom_height: number; top_height: number;
  min_turn_radius: number; turn_mode: 'angle' | 'arc';
  altitude_reference_mode: 'asl' | 'agl';
  altitude_change_min: number;
  enable_layering?: boolean; layer_step?: number; layer_scheme?: string;
  is_complete?: boolean; last_generated_at?: string | null;
  point_count?: number; landing_count?: number;
  created_at?: string; updated_at?: string;
}

export interface RouteCreatePayload {
  name: string; flight_width: number; protection_width: number;
  bottom_height: number; top_height: number;
  min_turn_radius?: number; turn_mode?: 'angle' | 'arc';
  altitude_reference_mode?: 'asl' | 'agl';
  altitude_change_min?: number;
  enable_layering?: boolean; layer_step?: number; layer_scheme?: string;
}

export interface RoutePoint {
  id: number; route_id?: number;
  name: string; point_type: 'start' | 'waypoint' | 'end';
  longitude: number; latitude: number; altitude: number;
  order_index: number;
}

export interface RoutePointPayload {
  name: string; point_type: 'start' | 'waypoint' | 'end';
  longitude: number; latitude: number; altitude?: number;
  order_index?: number;
}

export interface LandingSite {
  id: number; route_id?: number;
  name: string; longitude: number; latitude: number; altitude: number;
  altitude_source?: string; altitude_confirmed?: boolean;
}

export interface LandingSitePayload {
  name: string; longitude: number; latitude: number; altitude?: number;
  altitude_source?: string; altitude_confirmed?: boolean;
}

export interface RouteFullState {
  ok?: boolean;
  route: RouteInfo;
  points?: RoutePoint[];
  landing_sites?: LandingSite[];
  centerline?: GeoJSON;
  flight_zone?: GeoJSON;
  protection_zone?: GeoJSON;
  profile?: {
    distance_total: number;
    points: any[];
    layers: any[];
    altitude_reference_mode?: string;
    terrain_points?: any[];
    altitude_profile_points?: any[];
    route_bottom?: number;
    route_top?: number;
    altitude_change_min?: number;
    [key: string]: any;
  };
  sub_routes?: any[];
  turning?: {
    mode?: string;
    warnings?: any[];
    segments?: any[];
  };
  snapshot?: Record<string, any>;
  completeness?: {
    is_complete: boolean;
    missing_items?: string[];
    [key: string]: any;
  };
  errors?: string[];
  [key: string]: any;
}

export interface GeoJSON {
  type: string;
  coordinates?: any[];
  features?: any[];
}

export interface GenerateResult { ok: boolean; errors?: string[]; [key: string]: any; }

export interface AnalysisCatalogItem {
  id: string; category_id: string; name: string;
  control_requirement: string; capability: string;
  parameter_schema: any[]; default_params: Record<string, any>;
}

export interface AnalysisFactorResult {
  factor_id: string; compliance: 'pass' | 'fail' | 'unknown';
  data_status: string; evidence_json?: any;
  auto_value_json?: any; selected_value_json?: any;
  next_action?: string;
}

export interface AnalysisRunResult {
  run_id: string; aircraft_type: string;
  total_factors: number; pass_count: number; fail_count: number; unknown_count: number;
  factors: AnalysisFactorResult[];
}

export interface ImportProject {
  id: number; name: string; import_type: string; source_format: string;
  feature_count: number; item_count: number; is_visible: boolean;
  geometry_types?: string[]; bounds?: any;
  items?: ImportItem[];
}

export interface ImportItem {
  id: number; project_id: number; name: string; item_type: string;
  airspace_level: 'suitable' | 'limited' | 'prohibited';
  feature_count: number; is_visible: boolean; is_locked: boolean;
  feature_collection?: GeoJSON;
}

export interface TakeoffFlightState {
  ok?: boolean;
  route: RouteInfo;
  landing_sites?: LandingSite[];
  landings?: LandingSite[];
  terrain_summary?: any;
  visual?: {
    centerline?: GeoJSON;
    flight_zone?: GeoJSON;
    protection_zone?: GeoJSON;
    sub_routes?: any[];
    profile?: any;
  };
  plans: any[];
}

export interface FlightPlanRequest {
  landing_id: number; target_layer_sequence?: number;
  aircraft_platform: 'vtol' | 'fixed_wing';
  aircraft_preset: 'micro' | 'light' | 'fp98' | 'custom';
  aircraft_params: Record<string, any>;
}
