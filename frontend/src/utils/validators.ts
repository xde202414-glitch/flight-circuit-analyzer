/**
 * Validators Utilities
 * 校验工具函数
 */

import {
  Coordinate,
  RunwayParams,
  RunwayValidationResult,
  RunwayValidationError,
  COORDINATE_CONSTRAINTS,
  MAGNETIC_BEARING_CONSTRAINTS,
  RUNWAY_LENGTH_CONSTRAINTS,
  ELEVATION_CONSTRAINTS,
} from '../types/runway';

import { AIRCRAFT_CONSTRAINTS, Aircraft } from '../types/aircraft';

import {
  TrackConfig,
  TRACK_CONFIG_CONSTRAINTS,
  ValidationReport,
  ValidationError,
} from '../types/track';

/**
 * Validate coordinate
 */
export function validateCoordinate(coord: Coordinate): RunwayValidationError[] {
  const errors: RunwayValidationError[] = [];
  
  // Validate latitude
  if (coord.latitude < COORDINATE_CONSTRAINTS.latitude.min) {
    errors.push({
      field: 'latitude',
      message: `纬度过小: ${coord.latitude}°，最小 ${COORDINATE_CONSTRAINTS.latitude.min}°`,
      severity: 'error',
    });
  } else if (coord.latitude > COORDINATE_CONSTRAINTS.latitude.max) {
    errors.push({
      field: 'latitude',
      message: `纬度过大: ${coord.latitude}°，最大 ${COORDINATE_CONSTRAINTS.latitude.max}°`,
      severity: 'error',
    });
  }
  
  // Validate longitude
  if (coord.longitude < COORDINATE_CONSTRAINTS.longitude.min) {
    errors.push({
      field: 'longitude',
      message: `经度过小: ${coord.longitude}°，最小 ${COORDINATE_CONSTRAINTS.longitude.min}°`,
      severity: 'error',
    });
  } else if (coord.longitude > COORDINATE_CONSTRAINTS.longitude.max) {
    errors.push({
      field: 'longitude',
      message: `经度过大: ${coord.longitude}°，最大 ${COORDINATE_CONSTRAINTS.longitude.max}°`,
      severity: 'error',
    });
  }
  
  return errors;
}

/**
 * Validate runway parameters (frontend validation)
 */
export function validateRunwayParams(params: RunwayParams): RunwayValidationResult {
  const errors: RunwayValidationError[] = [];
  
  // Validate coordinate
  const coordErrors = validateCoordinate(params.coordinate);
  errors.push(...coordErrors);
  
  // Validate magnetic bearing
  if (params.magneticBearing < MAGNETIC_BEARING_CONSTRAINTS.min) {
    errors.push({
      field: 'magneticBearing',
      message: `磁方位角过小: ${params.magneticBearing}°`,
      severity: 'error',
    });
  } else if (params.magneticBearing > MAGNETIC_BEARING_CONSTRAINTS.max) {
    errors.push({
      field: 'magneticBearing',
      message: `磁方位角过大: ${params.magneticBearing}°`,
      severity: 'error',
    });
  }
  
  // Validate runway length
  if (params.length < RUNWAY_LENGTH_CONSTRAINTS.min) {
    errors.push({
      field: 'length',
      message: `跑道长度不足: ${params.length}m，最小 ${RUNWAY_LENGTH_CONSTRAINTS.min}m`,
      severity: 'error',
    });
  } else if (params.length < RUNWAY_LENGTH_CONSTRAINTS.recommended_min) {
    errors.push({
      field: 'length',
      message: `跑道长度较短: ${params.length}m，推荐 ${RUNWAY_LENGTH_CONSTRAINTS.recommended_min}m 以上`,
      severity: 'warning',
    });
  } else if (params.length > RUNWAY_LENGTH_CONSTRAINTS.max) {
    errors.push({
      field: 'length',
      message: `跑道长度过长: ${params.length}m`,
      severity: 'warning',
    });
  }
  
  // Validate elevation
  if (params.elevation < ELEVATION_CONSTRAINTS.min) {
    errors.push({
      field: 'elevation',
      message: `跑道标高过低: ${params.elevation}m`,
      severity: 'warning',
    });
  } else if (params.elevation > ELEVATION_CONSTRAINTS.max) {
    errors.push({
      field: 'elevation',
      message: `跑道标高过高: ${params.elevation}m，需考虑高原机场特殊要求`,
      severity: 'warning',
    });
  }
  
  const isValid = !errors.some((e) => e.severity === 'error');
  
  return {
    isValid,
    errors,
  };
}

/**
 * Validate aircraft parameters
 */
export function validateAircraft(aircraft: Aircraft): RunwayValidationError[] {
  const errors: RunwayValidationError[] = [];
  
  // Validate cruise speed
  if (aircraft.cruiseSpeed < AIRCRAFT_CONSTRAINTS.cruiseSpeed.min) {
    errors.push({
      field: 'cruiseSpeed',
      message: `巡航速度过小: ${aircraft.cruiseSpeed} km/h`,
      severity: 'error',
    });
  } else if (aircraft.cruiseSpeed > AIRCRAFT_CONSTRAINTS.cruiseSpeed.max) {
    errors.push({
      field: 'cruiseSpeed',
      message: `巡航速度过大: ${aircraft.cruiseSpeed} km/h`,
      severity: 'warning',
    });
  }
  
  // Validate climb rate
  if (aircraft.climbRate < AIRCRAFT_CONSTRAINTS.climbRate.min) {
    errors.push({
      field: 'climbRate',
      message: `爬升率过小: ${aircraft.climbRate} m/s`,
      severity: 'error',
    });
  }
  
  // Validate turn radius
  if (aircraft.turnRadius < AIRCRAFT_CONSTRAINTS.turnRadius.min) {
    errors.push({
      field: 'turnRadius',
      message: `转弯半径过小: ${aircraft.turnRadius} m`,
      severity: 'error',
    });
  }
  
  return errors;
}

/**
 * Validate track configuration
 */
export function validateTrackConfig(config: TrackConfig): ValidationReport {
  const errors: ValidationError[] = [];
  const warnings: ValidationError[] = [];
  
  // Validate circuit height
  if (config.circuitHeight < TRACK_CONFIG_CONSTRAINTS.circuitHeight.min) {
    errors.push({
      code: 'CIRCUIT_HEIGHT_MIN',
      message: `起落航线高度过低: ${config.circuitHeight}m`,
      severity: 'error',
    });
  } else if (config.circuitHeight < TRACK_CONFIG_CONSTRAINTS.circuitHeight.recommended) {
    warnings.push({
      code: 'CIRCUIT_HEIGHT_LOW',
      message: `起落航线高度偏低: ${config.circuitHeight}m，推荐 ${TRACK_CONFIG_CONSTRAINTS.circuitHeight.recommended}m`,
      severity: 'warning',
    });
  } else if (config.circuitHeight > TRACK_CONFIG_CONSTRAINTS.circuitHeight.max) {
    warnings.push({
      code: 'CIRCUIT_HEIGHT_HIGH',
      message: `起落航线高度过高: ${config.circuitHeight}m`,
      severity: 'warning',
    });
  }
  
  // Validate bank angle
  if (config.bankAngle < TRACK_CONFIG_CONSTRAINTS.bankAngle.min) {
    errors.push({
      code: 'BANK_ANGLE_MIN',
      message: `转弯坡度过小: ${config.bankAngle}°`,
      severity: 'error',
    });
  } else if (config.bankAngle > TRACK_CONFIG_CONSTRAINTS.bankAngle.max) {
    errors.push({
      code: 'BANK_ANGLE_MAX',
      message: `转弯坡度过大: ${config.bankAngle}°`,
      severity: 'error',
    });
  }

  const geometryFields = [
    ['departureLegLength', config.departureLegLength, '一边长度'],
    ['finalLegLength', config.finalLegLength, '五边长度'],
    ['turnRadius', config.turnRadius, '转弯半径'],
    ['downwindOffset', config.downwindOffset, '一边三边间隔'],
  ] as const;

  geometryFields.forEach(([key, value, label]) => {
    if (value === undefined) {
      return;
    }
    const limits = TRACK_CONFIG_CONSTRAINTS[key];
    if (value < limits.min || value > limits.max) {
      errors.push({
        code: `${key.toUpperCase()}_OUT_OF_RANGE`,
        message: `${label}应在 ${limits.min}-${limits.max}m 范围内`,
        severity: 'error',
      });
    }
  });

  if (
    config.turnRadius !== undefined &&
    config.downwindOffset !== undefined &&
    config.downwindOffset < config.turnRadius * 2
  ) {
    errors.push({
      code: 'DOWNWIND_OFFSET_TOO_SMALL',
      message: `一边三边间隔应不小于 2 倍转弯半径（当前需至少 ${Math.round(config.turnRadius * 2)}m）`,
      severity: 'error',
    });
  }
  
  // Validate wind parameters if wind correction enabled
  if (config.windCorrection) {
    if (config.windDirection === undefined) {
      errors.push({
        code: 'WIND_DIRECTION_MISSING',
        message: '启用风修正但未提供风向',
        severity: 'error',
      });
    } else if (
      config.windDirection < TRACK_CONFIG_CONSTRAINTS.windDirection.min ||
      config.windDirection > TRACK_CONFIG_CONSTRAINTS.windDirection.max
    ) {
      errors.push({
        code: 'WIND_DIRECTION_INVALID',
        message: `风向无效: ${config.windDirection}°`,
        severity: 'error',
      });
    }
    
    if (config.windSpeed === undefined) {
      errors.push({
        code: 'WIND_SPEED_MISSING',
        message: '启用风修正但未提供风速',
        severity: 'error',
      });
    } else if (
      config.windSpeed < TRACK_CONFIG_CONSTRAINTS.windSpeed.min ||
      config.windSpeed > TRACK_CONFIG_CONSTRAINTS.windSpeed.max
    ) {
      warnings.push({
        code: 'WIND_SPEED_INVALID',
        message: `风速异常: ${config.windSpeed} km/h`,
        severity: 'warning',
      });
    }
  }
  
  const isValid = errors.length === 0;
  
  return {
    isValid,
    errors,
    warnings,
  };
}

export default {
  validateCoordinate,
  validateRunwayParams,
  validateAircraft,
  validateTrackConfig,
};
