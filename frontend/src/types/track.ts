import { Coordinate } from './runway';

export type TrackSegmentName =
  | 'departure'
  | 'turn_1'
  | 'crosswind_leg'
  | 'turn_2'
  | 'downwind_leg'
  | 'turn_3'
  | 'base_leg'
  | 'turn_4'
  | 'final_approach';

export type GeometryKind = 'polyline' | 'polygon' | 'arc' | 'marker';
export type ActiveRunwayEnd = 'primary' | 'reciprocal';
export type TrafficPatternSide = 'left' | 'right';
export type RunwayCodeNumber = '1' | '2' | '3' | '4' | 'auto';
export type RunwayOperationType =
  | 'non_instrument'
  | 'non_precision'
  | 'precision_cat_i'
  | 'precision_cat_ii_iii';
export type VisualJoinMethod = 'standard' | 'straight_in' | 'crosswind' | 'downwind' | 'overhead';
export type FlightCampType =
  | 'glider'
  | 'aerobatic'
  | 'powered_hang_glider'
  | 'light_aircraft'
  | 'helicopter'
  | 'gyroplane'
  | 'balloon_airship'
  | 'hang_glider'
  | 'paraglider'
  | 'powered_paraglider'
  | 'aero_model'
  | 'water_sport_aircraft'
  | 'skydiving';

export const TRACK_SEGMENT_NAMES_CN: Record<TrackSegmentName, string> = {
  departure: '起飞航段',
  turn_1: '一转弯',
  crosswind_leg: '二边',
  turn_2: '二转弯',
  downwind_leg: '三边',
  turn_3: '三转弯',
  base_leg: '四边',
  turn_4: '四转弯',
  final_approach: '五边',
};

export interface GeometryOverlay {
  id: string;
  kind: GeometryKind;
  label: string;
  coordinates: Coordinate[];
  styleKey: string;
  altitude?: number | null;
  metadata?: Record<string, unknown> | null;
}

export interface TrackSegment {
  name: TrackSegmentName;
  nameCN: string;
  startPoint: Coordinate;
  endPoint: Coordinate;
  pathPoints?: Coordinate[] | null;
  distance: number;
  heading: number;
  altitude: number;
  verticalAngle: number;
}

export type ProcedureAnnotationStyleKey =
  | 'segment-label'
  | 'point-label'
  | 'performance-label'
  | 'turn-label';

export interface ProcedureAnnotation {
  id: string;
  coordinate: Coordinate;
  label: string;
  lines: string[];
  styleKey: ProcedureAnnotationStyleKey;
  relatedSegment?: TrackSegmentName | null;
}

export interface TrackConfig {
  circuitHeight: number;
  bankAngle: number;
  activeRunwayEnd: ActiveRunwayEnd;
  trafficPatternSide: TrafficPatternSide;
  departureLegLength?: number;
  finalLegLength?: number;
  turnRadius?: number;
  downwindOffset?: number;
  windCorrection: boolean;
  windDirection?: number;
  windSpeed?: number;
  magneticVariation?: number;
  bidirectional?: boolean;
  visualPattern?: VisualPatternConfig;
  obstacleSurfaces?: ObstacleSurfaceConfig;
  flightCampAirspace?: FlightCampAirspaceConfig;
}

export interface VisualPatternConfig {
  performanceClass?: 'A' | 'B' | 'C' | 'D';
  standardCircuitHeight?: number;
  maxIasKmh?: number;
  stableFinalDistance?: number;
  firstTurnMinHeight?: number;
  finalTurnMinHeight?: number;
  joinMethod?: VisualJoinMethod;
}

export interface ObstacleSurfaceConfig {
  codeNumber: RunwayCodeNumber;
  codeLetter?: 'A' | 'B' | 'C' | 'D' | 'E' | 'F';
  runwayOperationType: RunwayOperationType;
  takeoffEnabled: boolean;
  bidirectionalEnvelopeEnabled: boolean;
  showIndividualSurfaces: boolean;
}

export interface FlightCampAirspaceConfig {
  enabled: boolean;
  campType: FlightCampType;
  radiusM?: number;
  trueHeightM?: number;
  clearanceRadiusM?: number;
  overlaySpecialAirspace: boolean;
}

export const DEFAULT_TRACK_CONFIG: TrackConfig = {
  circuitHeight: 300,
  bankAngle: 15,
  activeRunwayEnd: 'primary',
  trafficPatternSide: 'left',
  windCorrection: false,
  magneticVariation: 0,
  bidirectional: false,
  visualPattern: {
    joinMethod: 'standard',
  },
  obstacleSurfaces: {
    codeNumber: 'auto',
    runwayOperationType: 'non_instrument',
    takeoffEnabled: true,
    bidirectionalEnvelopeEnabled: true,
    showIndividualSurfaces: true,
  },
  flightCampAirspace: {
    enabled: true,
    campType: 'light_aircraft',
    overlaySpecialAirspace: false,
  },
};

export const TRACK_CONFIG_CONSTRAINTS = {
  circuitHeight: { min: 100, max: 1000, recommended: 300 },
  bankAngle: { min: 5, max: 30, recommended: 15 },
  departureLegLength: { min: 500, max: 10000 },
  finalLegLength: { min: 500, max: 10000 },
  turnRadius: { min: 100, max: 5000 },
  downwindOffset: { min: 500, max: 10000 },
  windDirection: { min: 0, max: 360 },
  windSpeed: { min: 0, max: 100 },
};

export interface ValidationError {
  code: string;
  message: string;
  segment?: TrackSegmentName;
  severity: 'error' | 'warning';
}

export interface ValidationReport {
  isValid: boolean;
  errors: ValidationError[];
  warnings: ValidationError[];
}

export interface TrackResult {
  segments: TrackSegment[];
  keyPoints: GeometryOverlay[];
  surfaces: GeometryOverlay[];
  airspaces: GeometryOverlay[];
  annotations: ProcedureAnnotation[];
  compliance: ComplianceItem[];
  totalDistance: number;
  estimatedTime: number;
  validationReport: ValidationReport;
}

export interface ComplianceItem {
  id: string;
  category: 'visual_pattern' | 'obstacle_surface' | 'flight_camp_airspace';
  status: 'compliant' | 'custom_compliant' | 'non_compliant' | 'warning' | 'info';
  message: string;
  sourceCode: string;
  clause: string;
  severity: 'info' | 'warning' | 'error';
  details?: Record<string, unknown> | null;
}

export interface TrackRequest {
  runway: import('./runway').RunwayParams;
  aircraft_id: string;
  config: TrackConfig;
}

export interface GeometryParameterPreview {
  value: number;
  automaticValue: number;
  source: 'auto' | 'custom';
}

export interface GeometryPreviewResponse {
  departureLegLength: GeometryParameterPreview;
  finalLegLength: GeometryParameterPreview;
  turnRadius: GeometryParameterPreview;
  downwindOffset: GeometryParameterPreview;
}

export interface ParameterPreviewItem {
  value: number | string | boolean;
  automaticValue: number | string | boolean;
  source: 'auto' | 'custom';
  unit: string;
  sourceCode: string;
  clause: string;
  description: string;
}

export interface ParameterPreviewResponse {
  visualPattern: Record<string, ParameterPreviewItem>;
  obstacleSurfaces: Record<string, ParameterPreviewItem>;
  flightCampAirspace: Record<string, ParameterPreviewItem>;
}

export interface GeometryPreviewRequest {
  aircraft_id: string;
  config: TrackConfig;
}

export const TRACK_COLORS: Record<TrackSegmentName, string> = {
  departure: '#0f766e',
  turn_1: '#f59e0b',
  crosswind_leg: '#2563eb',
  turn_2: '#f59e0b',
  downwind_leg: '#111827',
  turn_3: '#f59e0b',
  base_leg: '#7c3aed',
  turn_4: '#f59e0b',
  final_approach: '#dc2626',
};
