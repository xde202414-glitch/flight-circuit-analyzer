/**
 * API type definitions matching backend models
 * API类型定义（与后端模型对应）
 */

import { RunwayParams, RunwayValidationResult } from '../types/runway';
import { Aircraft } from '../types/aircraft';
import {
  GeometryPreviewRequest,
  GeometryPreviewResponse,
  ParameterPreviewResponse,
  TrackConfig,
  TrackResult,
  TrackRequest,
} from '../types/track';
import { Coordinate } from '../types/runway';

// Re-export types for convenience
export type { RunwayValidationResult, TrackResult, TrackConfig, TrackRequest };

/**
 * Coordinate transform request
 * 坐标转换请求
 */
export interface CoordinateTransformRequest {
  /** Source coordinate (源坐标) */
  coordinate: Coordinate;
  /** Source coordinate system (源坐标系) */
  fromSystem: 'WGS84' | 'GCJ02';
  /** Target coordinate system (目标坐标系) */
  toSystem: 'WGS84' | 'GCJ02';
}

/**
 * Coordinate transform response
 * 坐标转换响应
 */
export interface CoordinateTransformResponse {
  /** Transformed coordinate (转换后坐标) */
  coordinate: Coordinate;
  /** Original coordinate system (原坐标系) */
  originalSystem: 'WGS84' | 'GCJ02';
  /** Target coordinate system (目标坐标系) */
  targetSystem: 'WGS84' | 'GCJ02';
}

/**
 * Runway API endpoints types
 * 跑道API端点类型
 */
export type RunwayValidateRequest = RunwayParams;
export type RunwayValidateResponse = RunwayValidationResult;

/**
 * Aircraft API endpoints types
 * 机型API端点类型
 */
export type AircraftListResponse = {
  aircrafts: Aircraft[];
  total: number;
};
export type AircraftDetailResponse = Aircraft;

/**
 * Track API endpoints types
 * 航迹API端点类型
 */
export type TrackCalculateRequest = TrackRequest;
export type TrackCalculateResponse = TrackResult;
export type TrackGeometryPreviewRequest = GeometryPreviewRequest;
export type TrackGeometryPreviewResponse = GeometryPreviewResponse;
export type TrackParameterPreviewResponse = ParameterPreviewResponse;
