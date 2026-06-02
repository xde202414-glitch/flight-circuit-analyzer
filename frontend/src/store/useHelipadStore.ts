/**
 * Helipad/FATO analysis state management (Zustand).
 */
import { create } from 'zustand';
import type { Coordinate } from '../types/runway';
import type {
  BuildingResult,
  FATOConfig,
  FATORegion,
  HelipadCalculateResponse,
  TerrainExceedance,
  VisualSurfaceResult,
} from '../types/helipad';
import { apiPost } from '../api/client';
import type {
  BuildingSearchRequest,
  BuildingSearchResponse,
  HelipadCalculateRequest,
  TerrainAnalysisRequest,
  TerrainAnalysisResponse,
} from '../types/helipad';

/** Analysis mode */
export type AnalysisMode = 'runway' | 'helipad';

interface HelipadState {
  // Mode
  analysisMode: AnalysisMode;

  // FATO centre (set by map click)
  helipadCenter: Coordinate | null;

  // Configuration
  fatoConfig: FATOConfig;

  // Calculation results
  fatoRegion: FATORegion | null;
  surfaceParams: VisualSurfaceResult | null;
  approachSurfaceParams: VisualSurfaceResult | null;
  takeoffSurfaceParams: VisualSurfaceResult | null;
  approachPolygon: Coordinate[] | null;
  takeoffPolygon: Coordinate[] | null;
  fatoPolygon: Coordinate[] | null;
  fatoCircles: Array<{ latitude: number; longitude: number; radius: number }> | null;

  // Building search
  buildingResults: BuildingResult[];
  buildingLoading: boolean;
  buildingMessage: string;

  // Terrain analysis
  terrainExceedances: TerrainExceedance[];
  terrainLoading: boolean;
  terrainMessage: string;

  // Status
  isCalculating: boolean;
  statusMessage: string;

  // Actions
  setAnalysisMode: (mode: AnalysisMode) => void;
  setHelipadCenter: (center: Coordinate | null) => void;
  setFATOConfig: (config: Partial<FATOConfig>) => void;
  clearHelipad: () => void;

  calculateSurface: () => Promise<void>;
  searchBuildings: () => Promise<void>;
  analyzeTerrain: () => Promise<void>;
}

/**
 * Default FATO configuration matching MAP HELI260522 defaults.
 */
const DEFAULT_FATO_CONFIG: FATOConfig = {
  shape: 'circle',
  diameter: 25,
  rotorDiameter: 11,
  elevation: 0,
  flightDirection: 0,
  takeoffDirection: null,
  slopeType: 'A',
  operationMode: 'day',
};

export const useHelipadStore = create<HelipadState>((set, get) => ({
  analysisMode: 'runway',
  helipadCenter: null,
  fatoConfig: DEFAULT_FATO_CONFIG,

  fatoRegion: null,
  surfaceParams: null,
  approachSurfaceParams: null,
  takeoffSurfaceParams: null,
  approachPolygon: null,
  takeoffPolygon: null,
  fatoPolygon: null,
  fatoCircles: null,

  buildingResults: [],
  buildingLoading: false,
  buildingMessage: '',

  terrainExceedances: [],
  terrainLoading: false,
  terrainMessage: '',

  isCalculating: false,
  statusMessage: '点击地图选点设置起降场中心',

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------

  setAnalysisMode: (mode) => set({ analysisMode: mode }),

  setHelipadCenter: (center) =>
    set({ helipadCenter: center, statusMessage: center ? '已选点，请配置起降场参数' : '点击地图选点' }),

  setFATOConfig: (config) =>
    set((state) => ({ fatoConfig: { ...state.fatoConfig, ...config } })),

  clearHelipad: () =>
    set({
      helipadCenter: null,
      fatoConfig: DEFAULT_FATO_CONFIG,
      fatoRegion: null,
      surfaceParams: null,
      approachSurfaceParams: null,
      takeoffSurfaceParams: null,
      approachPolygon: null,
      takeoffPolygon: null,
      fatoPolygon: null,
      fatoCircles: null,
      buildingResults: [],
      buildingMessage: '',
      terrainExceedances: [],
      terrainMessage: '',
      statusMessage: '点击地图选点',
    }),

  // ------------------------------------------------------------------
  // API calls
  // ------------------------------------------------------------------

  calculateSurface: async () => {
    const { helipadCenter, fatoConfig } = get();
    if (!helipadCenter) {
      set({ statusMessage: '请先在地图上点击选择起降场中心点' });
      return;
    }

    set({ isCalculating: true, statusMessage: '正在计算FATO区域和限制面...' });

    try {
      const req: HelipadCalculateRequest = {
        center: helipadCenter,
        config: fatoConfig,
      };
      const result = await apiPost<HelipadCalculateResponse>(
        '/helipad/calculate-surface',
        req,
      );

      set({
        fatoRegion: result.fatoRegion,
        surfaceParams: result.surfaceParams ?? result.approachSurfaceParams ?? null,
        approachSurfaceParams: result.approachSurfaceParams ?? result.surfaceParams ?? null,
        takeoffSurfaceParams: result.takeoffSurfaceParams ?? result.surfaceParams ?? null,
        approachPolygon: result.approachPolygon,
        takeoffPolygon: result.takeoffPolygon,
        fatoPolygon: result.fatoPolygon,
        fatoCircles: result.fatoCircles,
        isCalculating: false,
        statusMessage: 'FATO区域和限制面已计算，正在搜索建筑物...',
      });

      // Automatically trigger building search
      void get().searchBuildings();
    } catch (error) {
      set({
        isCalculating: false,
        statusMessage: `计算失败: ${error instanceof Error ? error.message : '未知错误'}`,
      });
    }
  },

  searchBuildings: async () => {
    const { fatoRegion, approachPolygon, takeoffPolygon } = get();
    if (!fatoRegion) {
      return;
    }

    set({ buildingLoading: true, buildingMessage: '正在搜索范围内建筑/地点...' });

    const polygons = [];
    if (fatoRegion.shape === 'circle') {
      polygons.push({
        name: 'FATO',
        points: generateCirclePoints(fatoRegion.center, fatoRegion.radius, 24),
      });
    }
    if (approachPolygon && approachPolygon.length >= 3) {
      polygons.push({ name: '进近面', points: approachPolygon });
    }
    if (takeoffPolygon && takeoffPolygon.length >= 3) {
      polygons.push({ name: '起飞爬升面', points: takeoffPolygon });
    }

    try {
      const req: BuildingSearchRequest = {
        polygons,
        mode: 'fast',
        pageSize: 10,
      };
      const result = await apiPost<BuildingSearchResponse>('/helipad/buildings', req);

      set({
        buildingResults: result.places || [],
        buildingLoading: false,
        buildingMessage: result.places.length
          ? `已在地图上标注 ${result.places.length} 个建筑/地点，来源：${result.source}`
          : '未找到范围内建筑/地点',
        statusMessage: result.places.length
          ? `找到 ${result.places.length} 个建筑/地点`
          : '未找到建筑/地点',
      });
    } catch (error) {
      set({
        buildingLoading: false,
        buildingMessage: `建筑搜索失败: ${error instanceof Error ? error.message : '未知错误'}`,
      });
    }
  },

  analyzeTerrain: async () => {
    const { fatoRegion, surfaceParams, helipadCenter, fatoConfig } = get();
    if (!fatoRegion || !surfaceParams || !helipadCenter) {
      set({ terrainMessage: '请先计算FATO区域和限制面' });
      return;
    }

    set({ terrainLoading: true, terrainMessage: '正在分析地形高程...' });

    try {
      const req: TerrainAnalysisRequest = {
        fatoCenter: helipadCenter,
        fatoElevation: fatoConfig.elevation,
        surfaceParams,
        fatoRegion,
        flightDirection: fatoConfig.flightDirection,
      };
      const result = await apiPost<TerrainAnalysisResponse>(
        '/helipad/elevation/analyze',
        req,
      );

      set({
        terrainExceedances: result.exceeded || [],
        terrainLoading: false,
        terrainMessage: result.message,
        statusMessage: result.exceeded.length
          ? `地形高程存在 ${result.exceeded.length} 处超限`
          : '地形高程分析完成',
      });
    } catch (error) {
      set({
        terrainLoading: false,
        terrainMessage: `地形分析失败: ${error instanceof Error ? error.message : '未知错误'}`,
      });
    }
  },
}));

// ---------------------------------------------------------------------------
// Helper – generate circle approximation polygon around a lat/lon centre
// ---------------------------------------------------------------------------

function generateCirclePoints(
  center: Coordinate,
  radius: number,
  count: number = 24,
): Coordinate[] {
  const R = 6378137.0;
  const points: Coordinate[] = [];
  for (let i = 0; i < count; i++) {
    const bearing = (i * 360) / count;
    const brng = (bearing * Math.PI) / 180;
    const d = radius / R;
    const lat1 = (center.latitude * Math.PI) / 180;
    const lon1 = (center.longitude * Math.PI) / 180;
    const lat2 = Math.asin(
      Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brng),
    );
    const lon2 =
      lon1 +
      Math.atan2(
        Math.sin(brng) * Math.sin(d) * Math.cos(lat1),
        Math.cos(d) - Math.sin(lat1) * Math.sin(lat2),
      );
    points.push({
      latitude: (lat2 * 180) / Math.PI,
      longitude: ((lon2 * 180) / Math.PI + 540) % 360 - 180,
    });
  }
  return points;
}
