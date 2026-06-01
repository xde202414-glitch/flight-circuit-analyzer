/**
 * useTrackCalculation Hook - Track calculation logic
 * 航迹计算 Hook - 处理航迹计算逻辑
 */
import { useState, useCallback } from 'react';
import { TrackResult, TrackConfig } from '../types/track';
import { RunwayParams } from '../types/runway';
import { Aircraft } from '../types/aircraft';
import { apiPost } from '../api/client';
import { TrackCalculateRequest } from '../api/types';

interface UseTrackCalculationResult {
  /** Calculated track result */
  result: TrackResult | null;
  /** Whether calculation is in progress */
  isCalculating: boolean;
  /** Error message if calculation failed */
  error: string | null;
  /** Trigger calculation */
  calculate: (runway: RunwayParams, aircraft: Aircraft, config: TrackConfig) => Promise<void>;
  /** Clear result */
  clearResult: () => void;
}

/**
 * useTrackCalculation Hook
 * Provides track calculation functionality with loading state and error handling
 */
export function useTrackCalculation(): UseTrackCalculationResult {
  const [result, setResult] = useState<TrackResult | null>(null);
  const [isCalculating, setIsCalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  /**
   * Calculate track
   */
  const calculate = useCallback(
    async (runway: RunwayParams, aircraft: Aircraft, config: TrackConfig) => {
      setIsCalculating(true);
      setError(null);
      
      try {
        const request: TrackCalculateRequest = {
          runway,
          aircraft_id: aircraft.id,
          config,
        };
        
        const trackResult = await apiPost<TrackResult>('/track/calculate', request);
        setResult(trackResult);
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : '未知错误';
        setError(`航迹计算失败: ${errorMessage}`);
        setResult(null);
      } finally {
        setIsCalculating(false);
      }
    },
    []
  );
  
  /**
   * Clear result
   */
  const clearResult = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);
  
  return {
    result,
    isCalculating,
    error,
    calculate,
    clearResult,
  };
}

export default useTrackCalculation;