/**
 * Runway-related type definitions
 * 跑道参数相关类型定义
 */

/**
 * Coordinate representation
 * 坐标点表示
 */
export interface Coordinate {
  /** Latitude in degrees (纬度) */
  latitude: number;
  /** Longitude in degrees (经度) */
  longitude: number;
}

/**
 * Coordinate system type
 * 坐标系类型
 */
export type CoordinateSystem = 'WGS84' | 'GCJ02';

/**
 * Runway parameters for flight circuit calculation
 * 跑道参数定义
 */
export interface RunwayParams {
  /** Runway center point coordinate (跑道中心点坐标) */
  coordinate: Coordinate;
  /** Magnetic bearing in degrees (磁方位角，0-360度) */
  magneticBearing: number;
  /** Runway length in meters (跑道长度，单位：米) */
  length: number;
  /** Runway width in meters (跑道宽度，0或不填=自动根据飞行区指标) */
  runwayWidth?: number;
  /** Runway elevation in meters, 0.1m precision (跑道标高，单位：米，精确到0.1米) */
  elevation: number;
  /** Coordinate system used for input (输入坐标系类型) */
  coordinateSystem: CoordinateSystem;
}

/**
 * Validation error for runway parameters
 * 跑道参数校验错误
 */
export interface RunwayValidationError {
  /** Field name that has error (错误字段名) */
  field: string;
  /** Error message (错误消息) */
  message: string;
  /** Error severity (错误级别) */
  severity: 'error' | 'warning';
}

/**
 * Runway validation result
 * 跑道参数校验结果
 */
export interface RunwayValidationResult {
  /** Whether parameters are valid (是否有效) */
  isValid: boolean;
  /** Validation errors (校验错误列表) */
  errors: RunwayValidationError[];
}

/**
 * Default runway parameters
 * 默认跑道参数
 */
export const DEFAULT_RUNWAY_PARAMS: RunwayParams = {
  coordinate: { latitude: 30.2741, longitude: 120.1551 },
  magneticBearing: 180,
  length: 800,
  elevation: 20,
  coordinateSystem: 'WGS84',
};

/**
 * Coordinate validation constraints
 * 坐标校验约束
 */
export const COORDINATE_CONSTRAINTS = {
  latitude: { min: -90, max: 90 },
  longitude: { min: -180, max: 180 },
};

/**
 * Magnetic bearing constraints
 * 磁方位角约束
 */
export const MAGNETIC_BEARING_CONSTRAINTS = {
  min: 0,
  max: 360,
};

/**
 * Runway length constraints (meters)
 * 跑道长度约束（米）
 */
export const RUNWAY_LENGTH_CONSTRAINTS = {
  min: 200, // 最小200米（轻型飞机）
  max: 5000, // 最大5000米
  recommended_min: 600, // 推荐最小600米（塞斯纳172）
};

/**
 * Elevation constraints (meters)
 * 标高约束（米）
 */
export const ELEVATION_CONSTRAINTS = {
  min: -500, // 最低-500米（死海等特殊地区）
  max: 5000, // 最高5000米（高原机场）
};
