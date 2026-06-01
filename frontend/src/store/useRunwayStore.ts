/**
 * Runway parameters state management store
 * 跑道参数状态管理
 */
import { create } from 'zustand';
import { RunwayParams, RunwayValidationResult, DEFAULT_RUNWAY_PARAMS } from '../types/runway';

interface RunwayState {
  /** Current runway parameters (当前跑道参数) */
  runwayParams: RunwayParams;
  /** Validation result (校验结果) */
  validationResult: RunwayValidationResult | null;
  /** Whether validation is in progress (是否正在校验) */
  isValidating: boolean;
  
  // Actions
  /** Update runway parameters (更新跑道参数) */
  setRunwayParams: (params: Partial<RunwayParams>) => void;
  /** Reset to default parameters (重置为默认参数) */
  resetRunwayParams: () => void;
  /** Set validation result (设置校验结果) */
  setValidationResult: (result: RunwayValidationResult | null) => void;
  /** Set validating state (设置校验状态) */
  setIsValidating: (isValidating: boolean) => void;
}

/**
 * Runway parameters Zustand store
 * 跑道参数状态存储
 */
export const useRunwayStore = create<RunwayState>((set) => ({
  runwayParams: DEFAULT_RUNWAY_PARAMS,
  validationResult: null,
  isValidating: false,
  
  setRunwayParams: (params) =>
    set((state) => ({
      runwayParams: { ...state.runwayParams, ...params },
      validationResult: null, // Clear validation when params change
    })),
  
  resetRunwayParams: () =>
    set({
      runwayParams: DEFAULT_RUNWAY_PARAMS,
      validationResult: null,
    }),
  
  setValidationResult: (result) => set({ validationResult: result }),
  
  setIsValidating: (isValidating) => set({ isValidating }),
}));

/**
 * Selector for getting runway center coordinate
 * 获取跑道中心点坐标选择器
 */
export const selectRunwayCenter = (state: RunwayState): [number, number] => [
  state.runwayParams.coordinate.latitude,
  state.runwayParams.coordinate.longitude,
];

/**
 * Selector for checking if runway is valid
 * 检查跑道参数是否有效选择器
 */
export const selectRunwayIsValid = (state: RunwayState): boolean =>
  state.validationResult?.isValid ?? false;