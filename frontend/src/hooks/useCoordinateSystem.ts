/**
 * useCoordinateSystem Hook - Coordinate system management
 * 坐标系管理 Hook - 处理坐标系转换逻辑
 */
import { useState, useCallback } from 'react';
import { Coordinate, CoordinateSystem } from '../types/runway';
import { apiPost } from '../api/client';
import { CoordinateTransformRequest, CoordinateTransformResponse } from '../api/types';

interface UseCoordinateSystemResult {
  /** Current coordinate system */
  coordinateSystem: CoordinateSystem;
  /** Whether conversion is in progress */
  isConverting: boolean;
  /** Conversion error */
  error: string | null;
  /** Set coordinate system */
  setCoordinateSystem: (system: CoordinateSystem) => void;
  /** Convert coordinate to target system */
  convertCoordinate: (
    coordinate: Coordinate,
    fromSystem: CoordinateSystem,
    toSystem: CoordinateSystem
  ) => Promise<Coordinate>;
}

/**
 * useCoordinateSystem Hook
 * Provides coordinate system switching and conversion functionality
 */
export function useCoordinateSystem(): UseCoordinateSystemResult {
  const [coordinateSystem, setCoordinateSystem] = useState<CoordinateSystem>('WGS84');
  const [isConverting, setIsConverting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  /**
   * Convert coordinate between systems
   */
  const convertCoordinate = useCallback(
    async (
      coordinate: Coordinate,
      fromSystem: CoordinateSystem,
      toSystem: CoordinateSystem
    ): Promise<Coordinate> => {
      // No conversion needed if same system
      if (fromSystem === toSystem) {
        return coordinate;
      }
      
      setIsConverting(true);
      setError(null);
      
      try {
        const request: CoordinateTransformRequest = {
          coordinate,
          fromSystem,
          toSystem,
        };
        
        const result = await apiPost<CoordinateTransformResponse>(
          '/coordinate/transform',
          request
        );
        
        return result.coordinate;
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : '转换失败';
        setError(`坐标转换失败: ${errorMessage}`);
        return coordinate; // Return original on error
      } finally {
        setIsConverting(false);
      }
    },
    []
  );
  
  return {
    coordinateSystem,
    isConverting,
    error,
    setCoordinateSystem,
    convertCoordinate,
  };
}

export default useCoordinateSystem;