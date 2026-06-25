/**
 * API client configuration using Axios
 */
import axios, { AxiosInstance, AxiosError, AxiosResponse } from 'axios';
import type {
  RouteInfo, RouteCreatePayload, RoutePoint, RoutePointPayload,
  LandingSite, LandingSitePayload, RouteFullState, GenerateResult,
  AnalysisCatalogItem, AnalysisFactorResult, AnalysisRunResult,
  ImportProject, ImportItem, TakeoffFlightState, FlightPlanRequest,
} from './types';

export interface ApiResponse<T> {
  code: number;
  data: T;
  message: string;
}

export const ERROR_CODES = {
  SUCCESS: 200, BAD_REQUEST: 400, NOT_FOUND: 404,
  BUSINESS_ERROR: 422, SERVER_ERROR: 500,
};

const axiosInstance: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

axiosInstance.interceptors.request.use(
  (config) => {
    console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`);
    return config;
  },
  (error: AxiosError) => { console.error('[API Error]', error.message); return Promise.reject(error); }
);

axiosInstance.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError) => {
    const msg = (error.response?.data as any)?.detail || error.message || '服务器错误';
    return Promise.reject(new Error(msg));
  }
);

// ====== Route 10 API Methods ======

export const apiClient = {
  // Routes
  getRoutes: async (): Promise<{ items: RouteInfo[] }> => {
    const res = await axiosInstance.get('/routes');
    return res.data;
  },
  getRoute: async (id: number): Promise<RouteInfo> => {
    const res = await axiosInstance.get(`/routes/${id}`);
    return res.data;
  },
  createRoute: async (payload: RouteCreatePayload): Promise<RouteInfo> => {
    const res = await axiosInstance.post('/routes', {
      ...payload,
      enable_layering: payload.enable_layering ?? true,
      layer_step: payload.layer_step ?? 50,
      layer_scheme: payload.layer_scheme ?? '60-90,90-120,120-180,180-240,240-300',
      min_turn_radius: payload.min_turn_radius ?? 0,
      turn_mode: payload.turn_mode ?? 'angle',
      altitude_reference_mode: payload.altitude_reference_mode ?? 'asl',
      altitude_change_min: payload.altitude_change_min ?? 10,
    });
    return res.data;
  },
  updateRoute: async (id: number, payload: RouteCreatePayload): Promise<RouteInfo> => {
    const res = await axiosInstance.put(`/routes/${id}`, {
      ...payload,
      enable_layering: payload.enable_layering ?? true,
      layer_step: payload.layer_step ?? 50,
      layer_scheme: payload.layer_scheme ?? '60-90,90-120,120-180,180-240,240-300',
      min_turn_radius: payload.min_turn_radius ?? 0,
      turn_mode: payload.turn_mode ?? 'angle',
      altitude_reference_mode: payload.altitude_reference_mode ?? 'asl',
      altitude_change_min: payload.altitude_change_min ?? 10,
    });
    return res.data;
  },
  deleteRoute: async (id: number): Promise<void> => { await axiosInstance.delete(`/routes/${id}`); },
  duplicateRoute: async (id: number, name?: string): Promise<RouteInfo> => {
    const res = await axiosInstance.post(`/routes/${id}/duplicate`, { name });
    return res.data;
  },
  generateRoute: async (id: number): Promise<GenerateResult> => {
    const res = await axiosInstance.post(`/routes/${id}/generate`);
    return res.data;
  },
  getRouteFull: async (id: number): Promise<RouteFullState> => {
    const res = await axiosInstance.get(`/routes/${id}/full`);
    return res.data;
  },
  getRouteCompleteness: async (id: number): Promise<any> => {
    const res = await axiosInstance.get(`/routes/${id}/completeness`);
    return res.data;
  },

  // Route Points
  getRoutePoints: async (routeId: number): Promise<{ items: RoutePoint[] }> => {
    const res = await axiosInstance.get(`/routes/${routeId}/points`);
    return res.data;
  },
  createRoutePoint: async (routeId: number, payload: RoutePointPayload): Promise<RoutePoint> => {
    const res = await axiosInstance.post(`/routes/${routeId}/points`, payload);
    return res.data;
  },
  updateRoutePoint: async (routeId: number, pointId: number, payload: RoutePointPayload): Promise<RoutePoint> => {
    const res = await axiosInstance.put(`/routes/${routeId}/points/${pointId}`, payload);
    return res.data;
  },
  deleteRoutePoint: async (routeId: number, pointId: number): Promise<void> => {
    await axiosInstance.delete(`/routes/${routeId}/points/${pointId}`);
  },

  // Landing Sites
  getLandingSites: async (routeId: number): Promise<{ items: LandingSite[] }> => {
    const res = await axiosInstance.get(`/routes/${routeId}/landing-sites`);
    return res.data;
  },
  createLandingSite: async (routeId: number, payload: LandingSitePayload): Promise<LandingSite> => {
    const res = await axiosInstance.post(`/routes/${routeId}/landing-sites`, payload);
    return res.data;
  },
  updateLandingSite: async (routeId: number, id: number, payload: LandingSitePayload): Promise<LandingSite> => {
    const res = await axiosInstance.put(`/routes/${routeId}/landing-sites/${id}`, payload);
    return res.data;
  },
  deleteLandingSite: async (routeId: number, id: number): Promise<void> => {
    await axiosInstance.delete(`/routes/${routeId}/landing-sites/${id}`);
  },
  suggestLandingElevation: async (routeId: number, id: number): Promise<any> => {
    const res = await axiosInstance.post(`/routes/${routeId}/landing-sites/${id}/elevation/suggest`);
    return res.data;
  },

  // Geo
  extractRouteGeo: async (routeId: number): Promise<any> => {
    const res = await axiosInstance.post(`/routes/${routeId}/geo/extract`);
    return res.data;
  },
  getRouteGeo: async (routeId: number): Promise<any> => {
    const res = await axiosInstance.get(`/routes/${routeId}/geo`);
    return res.data;
  },

  // Sub Routes
  extractSubRoute: async (routeId: number, seq: number, name?: string): Promise<RouteInfo> => {
    const res = await axiosInstance.post(`/routes/${routeId}/sub-routes/${seq}/extract`, { name });
    return res.data;
  },

  // Takeoff Flight
  getTakeoffFlightState: async (routeId: number): Promise<TakeoffFlightState> => {
    const res = await axiosInstance.get(`/routes/${routeId}/takeoff-flight`);
    return res.data;
  },
  previewTakeoffFlight: async (routeId: number, payload: FlightPlanRequest): Promise<any> => {
    const res = await axiosInstance.post(`/routes/${routeId}/takeoff-flight/preview`, payload);
    return res.data;
  },
  createFlightPlan: async (routeId: number, payload: FlightPlanRequest): Promise<any> => {
    const res = await axiosInstance.post(`/routes/${routeId}/takeoff-flight/plans`, payload);
    return res.data;
  },

  // Analysis
  getAnalysisCatalog: async (): Promise<{ categories: any[]; factors: AnalysisCatalogItem[] }> => {
    const res = await axiosInstance.get('/analysis/catalog');
    return res.data;
  },
  getRouteAnalysis: async (routeId: number): Promise<any> => {
    const res = await axiosInstance.get(`/routes/${routeId}/analysis`);
    return res.data;
  },
  runAnalysis: async (routeId: number, payload?: any): Promise<AnalysisRunResult> => {
    const res = await axiosInstance.post(`/routes/${routeId}/analysis/run`, payload || {});
    return res.data;
  },
  runSingleFactor: async (routeId: number, factorId: string, payload?: any): Promise<AnalysisFactorResult> => {
    const res = await axiosInstance.post(`/routes/${routeId}/analysis/factors/${factorId}/run`, payload || {});
    return res.data;
  },
  updateFactorInput: async (routeId: number, factorId: string, payload: any): Promise<any> => {
    const res = await axiosInstance.put(`/routes/${routeId}/analysis/factors/${factorId}/input`, payload);
    return res.data;
  },

  // Import
  getImportProjects: async (): Promise<{ items: ImportProject[] }> => {
    const res = await axiosInstance.get('/imports/projects');
    return res.data;
  },
  getImportProject: async (id: number): Promise<ImportProject> => {
    const res = await axiosInstance.get(`/imports/projects/${id}`);
    return res.data;
  },
  deleteImportProject: async (id: number): Promise<void> => {
    await axiosInstance.delete(`/imports/projects/${id}`);
  },
  getImportItems: async (projectId?: number): Promise<{ items: ImportItem[] }> => {
    const res = await axiosInstance.get('/imports/items', { params: projectId ? { project_id: projectId } : {} });
    return res.data;
  },
  getImportItem: async (id: number): Promise<ImportItem> => {
    const res = await axiosInstance.get(`/imports/items/${id}`);
    return res.data;
  },
  updateImportItem: async (id: number, payload: any): Promise<ImportItem> => {
    const res = await axiosInstance.patch(`/imports/items/${id}`, payload);
    return res.data;
  },
  deleteImportItem: async (id: number): Promise<void> => {
    await axiosInstance.delete(`/imports/items/${id}`);
  },
  getImportMapFeatures: async (bbox: string): Promise<any> => {
    const res = await axiosInstance.get('/imports/map-features', { params: { bbox } });
    return res.data;
  },
  listImportedDatasets: async (): Promise<any[]> => {
    const res = await axiosInstance.get('/imports/datasets');
    return res.data.items || [];
  },
  getImportedDataset: async (id: number): Promise<any> => {
    const res = await axiosInstance.get(`/imports/datasets/${id}`);
    return res.data;
  },
  deleteImportedDataset: async (id: number): Promise<void> => {
    await axiosInstance.delete(`/imports/datasets/${id}`);
  },
  createImportedDatasetFromGeoJson: async (payload: {
    name: string; import_type: string; source_crs?: string; target_crs?: string; feature_collection: Record<string, unknown>;
  }): Promise<any> => {
    const res = await axiosInstance.post('/imports/datasets/geojson', payload);
    return res.data;
  },
  uploadObstacleSurfaceDataset: async (file: File, payload: { name?: string; sourceCrs?: string; targetCrs?: string }): Promise<any> => {
    const form = new FormData();
    form.append('file', file);
    if (payload.name?.trim()) form.append('name', payload.name.trim());
    if (payload.sourceCrs?.trim()) form.append('source_crs', payload.sourceCrs.trim());
    if (payload.targetCrs?.trim()) form.append('target_crs', payload.targetCrs.trim());
    const response = await fetch('/api/v1/imports/datasets/obstacle-surface/upload', { method: 'POST', body: form });
    if (!response.ok) throw new Error('上传失败');
    return response.json();
  },

  // Map config
  getMapConfig: async (): Promise<any> => {
    const res = await axiosInstance.get('/config/map');
    return res.data;
  },

  // Export
  exportKml: async (routeId: number): Promise<string> => {
    const response = await fetch('/api/v1/export/kml', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ route_id: routeId }),
    });
    if (!response.ok) throw new Error('导出KML失败');
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  },
  exportSHP: async (routeId: number): Promise<any> => {
    const res = await axiosInstance.post('/export/shp', { route_id: routeId });
    return res.data;
  },

  // Takeoff flight plans list
  listTakeoffFlightPlans: async (routeId: number): Promise<any[]> => {
    const res = await axiosInstance.get(`/routes/${routeId}/takeoff-flight/plans`);
    return res.data.items || [];
  },

  // Import capabilities
  getImportCapabilities: async (): Promise<any> => {
    const res = await axiosInstance.get('/imports/capabilities');
    return res.data;
  },

  // Dataset upload
  uploadImportedDataset: async (file: File, payload: { name?: string; sourceCrs?: string; targetCrs?: string }): Promise<any> => {
    const form = new FormData();
    form.append('file', file);
    if (payload.name?.trim()) form.append('name', payload.name.trim());
    if (payload.sourceCrs?.trim()) form.append('source_crs', payload.sourceCrs.trim());
    if (payload.targetCrs?.trim()) form.append('target_crs', payload.targetCrs.trim());
    const response = await fetch('/api/v1/imports/datasets/upload', { method: 'POST', body: form });
    if (!response.ok) throw new Error('上传失败');
    return response.json();
  },

  // Import project update
  updateImportProject: async (id: number, payload: { name?: string; is_visible?: boolean }): Promise<ImportProject> => {
    const res = await axiosInstance.patch(`/imports/projects/${id}`, { name: payload.name, is_visible: payload.is_visible });
    return res.data;
  },

  // Combine import projects
  combineImportProjects: async (payload: { name: string; project_ids?: number[]; item_ids?: number[] }): Promise<ImportProject> => {
    const res = await axiosInstance.post('/imports/projects/combine', payload);
    return res.data;
  },

  // Merge import items
  mergeImportItems: async (payload: { name: string; item_ids: number[] }): Promise<ImportProject> => {
    const res = await axiosInstance.post('/imports/items/merge', payload);
    return res.data;
  },

  // Import job status
  getImportJob: async (id: number): Promise<any> => {
    const res = await axiosInstance.get(`/imports/jobs/${id}`);
    return res.data;
  },

  // Export import GeoJSON
  exportImportGeoJson: (payload: { project_ids?: number[]; item_ids?: number[] }): string => {
    const params = new URLSearchParams();
    if (payload.project_ids?.length) params.set('project_ids', payload.project_ids.join(','));
    if (payload.item_ids?.length) params.set('item_ids', payload.item_ids.join(','));
    return `/api/v1/imports/export.geojson?${params.toString()}`;
  },

  // Query import map features with full params
  queryImportMapFeatures: async (payload: {
    bbox?: { west: number; south: number; east: number; north: number };
    zoom?: number;
    item_ids?: number[];
    project_ids?: number[];
    max_features?: number;
  }): Promise<any> => {
    const params = new URLSearchParams();
    if (payload.bbox) params.set('bbox', `${payload.bbox.west},${payload.bbox.south},${payload.bbox.east},${payload.bbox.north}`);
    if (payload.zoom !== undefined) params.set('zoom', String(payload.zoom));
    if (payload.item_ids?.length) params.set('item_ids', payload.item_ids.join(','));
    if (payload.project_ids?.length) params.set('project_ids', payload.project_ids.join(','));
    if (payload.max_features) params.set('max_features', String(payload.max_features));
    const res = await axiosInstance.get(`/imports/map-features?${params.toString()}`);
    return res.data;
  },

  // AI import analyze
  analyzeAiImport: async (
    files: File[],
    payload: { name?: string; provider: string; model?: string; apiKey: string; baseUrl?: string; text?: string; instruction?: string },
  ): Promise<any> => {
    const form = new FormData();
    files.forEach(f => form.append('files', f));
    if (payload.name?.trim()) form.append('name', payload.name.trim());
    form.append('provider', payload.provider);
    if (payload.model?.trim()) form.append('model', payload.model.trim());
    form.append('api_key', payload.apiKey.trim());
    if (payload.baseUrl?.trim()) form.append('base_url', payload.baseUrl.trim());
    if (payload.text?.trim()) form.append('text', payload.text.trim());
    if (payload.instruction?.trim()) form.append('instruction', payload.instruction.trim());
    const response = await fetch('/api/v1/imports/ai/analyze', { method: 'POST', body: form });
    if (!response.ok) throw new Error('AI分析失败');
    return response.json();
  },

  // Commit AI import
  commitAiImport: async (payload: { name: string; items: any[]; metadata?: Record<string, unknown> }): Promise<ImportProject> => {
    const res = await axiosInstance.post('/imports/ai/commit', payload);
    return res.data;
  },
};

export default axiosInstance;

// Backward compatibility exports for existing components
export async function apiRequest<T>(method: 'GET' | 'POST' | 'PUT' | 'DELETE', url: string, data?: unknown): Promise<T> {
  const response = await axiosInstance.request<T>({ method, url, data });
  return (response.data as any)?.data ?? response.data;
}

export async function apiGet<T>(url: string): Promise<T> {
  return apiRequest<T>('GET', url);
}

export async function apiPost<T>(url: string, data: unknown): Promise<T> {
  return apiRequest<T>('POST', url, data);
}
