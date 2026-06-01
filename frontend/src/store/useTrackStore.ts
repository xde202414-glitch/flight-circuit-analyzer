/**
 * Track calculation state management store
 * 航迹计算状态管理
 */
import { create } from 'zustand';
import { TrackConfig, TrackResult, DEFAULT_TRACK_CONFIG } from '../types/track';
import { Aircraft } from '../types/aircraft';

interface TrackState {
  /** Selected aircraft (选中的机型) */
  selectedAircraft: Aircraft | null;
  /** Track configuration (航迹配置) */
  trackConfig: TrackConfig;
  /** Calculated track result (计算结果) */
  trackResult: TrackResult | null;
  /** Whether calculation is in progress (是否正在计算) */
  isCalculating: boolean;
  /** Calculation error message (计算错误消息) */
  error: string | null;
  
  // Actions
  /** Set selected aircraft (设置选中的机型) */
  setSelectedAircraft: (aircraft: Aircraft | null) => void;
  /** Update track configuration (更新航迹配置) */
  setTrackConfig: (config: Partial<TrackConfig>) => void;
  /** Reset track configuration (重置航迹配置) */
  resetTrackConfig: () => void;
  /** Set track result (设置计算结果) */
  setTrackResult: (result: TrackResult | null) => void;
  /** Set calculating state (设置计算状态) */
  setIsCalculating: (isCalculating: boolean) => void;
  /** Set error message (设置错误消息) */
  setError: (error: string | null) => void;
  /** Clear all track data (清除所有航迹数据) */
  clearTrackData: () => void;
}

/**
 * Track state Zustand store
 * 航迹状态存储
 */
export const useTrackStore = create<TrackState>((set) => ({
  selectedAircraft: null,
  trackConfig: DEFAULT_TRACK_CONFIG,
  trackResult: null,
  isCalculating: false,
  error: null,
  
  setSelectedAircraft: (aircraft) => set({ selectedAircraft: aircraft }),
  
  setTrackConfig: (config) =>
    set((state) => ({
      trackConfig: { ...state.trackConfig, ...config },
    })),
  
  resetTrackConfig: () => set({ trackConfig: DEFAULT_TRACK_CONFIG }),
  
  setTrackResult: (result) => set({ trackResult: result }),
  
  setIsCalculating: (isCalculating) => set({ isCalculating }),
  
  setError: (error) => set({ error }),
  
  clearTrackData: () =>
    set({
      trackResult: null,
      error: null,
    }),
}));

/**
 * Selector for getting track segments
 * 获取航段列表选择器
 */
export const selectTrackSegments = (state: TrackState) => state.trackResult?.segments ?? [];

/**
 * Selector for getting total track distance
 * 获取总航迹距离选择器
 */
export const selectTotalDistance = (state: TrackState) => state.trackResult?.totalDistance ?? 0;

/**
 * Selector for getting estimated flight time
 * 获取预计飞行时间选择器
 */
export const selectEstimatedTime = (state: TrackState) => state.trackResult?.estimatedTime ?? 0;

/**
 * Selector for checking if track is valid
 * 检查航迹是否有效选择器
 */
export const selectTrackIsValid = (state: TrackState): boolean =>
  state.trackResult?.validationReport?.isValid ?? false;
