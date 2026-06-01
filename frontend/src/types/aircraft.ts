/**
 * Aircraft-related type definitions
 * 机型相关类型定义
 */
import type { FlightCampType } from './track';

/**
 * Aircraft performance parameters
 * 机型性能参数
 */
export interface Aircraft {
  /** Aircraft unique identifier (机型唯一标识) */
  id: string;
  /** Aircraft model name (机型名称) */
  name: string;
  /** Manufacturer (制造商) */
  manufacturer: string;
  /** Cruise speed in km/h (巡航速度，单位：km/h) */
  cruiseSpeed: number;
  /** Climb rate in m/s (爬升率，单位：m/s) */
  climbRate: number;
  /** Turn radius in meters (转弯半径，单位：米) */
  turnRadius: number;
  /** Approach speed in km/h (进近速度，单位：km/h) */
  approachSpeed: number;
  /** Maximum altitude in meters (最大高度，单位：米) */
  maxAltitude: number;
  /** Stall speed in km/h (失速速度，单位：km/h) */
  stallSpeed: number;
  /** Aircraft category (机型类别) */
  category: 'light' | 'medium' | 'heavy';
  /** Engine type (发动机类型) */
  vfrPatternClass: 'A' | 'B' | 'C' | 'D';
  vfrMaxIasKmh: number;
  engineType: 'piston' | 'turboprop' | 'jet';
  flightCampCategory: FlightCampType;
  /** Description (描述) */
  description: string;
}

/**
 * Aircraft list response from API
 * 机型列表响应
 */
export interface AircraftListResponse {
  /** Aircraft list (机型列表) */
  aircrafts: Aircraft[];
  /** Total count (总数) */
  total: number;
}

/**
 * Common aircraft presets
 * 常用机型预设
 */
export const COMMON_AIRCRAFT_PRESETS: Partial<Aircraft>[] = [
  {
    id: 'cessna-172',
    name: '塞斯纳172',
    manufacturer: 'Cessna',
    category: 'light',
    engineType: 'piston',
    description: '经典单发活塞教练机，广泛用于飞行培训',
  },
  {
    id: 'diamond-da40',
    name: '钻石DA40',
    manufacturer: 'Diamond Aircraft',
    category: 'light',
    engineType: 'piston',
    description: '复合材料单发教练机，燃油经济性好',
  },
  {
    id: 'cirrus-sr20',
    name: '西锐SR20',
    manufacturer: 'Cirrus Aircraft',
    category: 'light',
    engineType: 'piston',
    description: '配备整机降落伞系统的单发飞机',
  },
  {
    id: 'piper-pa28',
    name: '派珀PA-28',
    manufacturer: 'Piper Aircraft',
    category: 'light',
    engineType: 'piston',
    description: '经典单发教练机，操作简单',
  },
];

/**
 * Aircraft performance constraints
 * 机型性能约束
 */
export const AIRCRAFT_CONSTRAINTS = {
  cruiseSpeed: { min: 40, max: 900 }, // km/h
  climbRate: { min: 1, max: 50 }, // m/s
  turnRadius: { min: 100, max: 5000 }, // m
  approachSpeed: { min: 35, max: 300 }, // km/h
  stallSpeed: { min: 20, max: 200 }, // km/h
};
