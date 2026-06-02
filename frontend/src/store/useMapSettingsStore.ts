import { create } from 'zustand';
import { apiGet } from '../api/client';
import { BaseMapType, isBaseMapType, MapConfig } from '../types/map';

const TIANDITU_KEY_STORAGE = 'tianditu_api_key';
const GEOVIS_TOKEN_STORAGE = 'geovis_token';
const BASE_MAP_STORAGE = 'base_map_type';

interface MapSettingsState {
  baseMapType: BaseMapType;
  tiandituKey: string;
  geovisToken: string;
  isInitialized: boolean;
  isLoadingConfig: boolean;
  configError: string | null;
  initialize: () => Promise<void>;
  setBaseMapType: (type: BaseMapType) => void;
  saveTiandituKey: (key: string) => void;
  clearTiandituKey: () => void;
}

function readStoredKey(): string {
  try {
    return localStorage.getItem(TIANDITU_KEY_STORAGE) ?? '';
  } catch {
    return '';
  }
}

function readStoredBaseMap(): BaseMapType {
  try {
    const value = localStorage.getItem(BASE_MAP_STORAGE);
    return isBaseMapType(value) ? value : 'osm';
  } catch {
    return 'osm';
  }
}

function writeStoredBaseMap(type: BaseMapType): void {
  try {
    localStorage.setItem(BASE_MAP_STORAGE, type);
  } catch {
    // Ignore storage failures in restricted browser contexts.
  }
}

function writeStoredKey(key: string): void {
  try {
    if (key) {
      localStorage.setItem(TIANDITU_KEY_STORAGE, key);
    } else {
      localStorage.removeItem(TIANDITU_KEY_STORAGE);
      localStorage.setItem(BASE_MAP_STORAGE, 'osm');
    }
  } catch {
    // Ignore storage failures in restricted browser contexts.
  }
}

function writeStoredGeovisToken(token: string): void {
  try {
    if (token) {
      localStorage.setItem(GEOVIS_TOKEN_STORAGE, token);
    } else {
      localStorage.removeItem(GEOVIS_TOKEN_STORAGE);
    }
  } catch {
    // Ignore
  }
}

function readStoredGeovisToken(): string {
  try {
    return localStorage.getItem(GEOVIS_TOKEN_STORAGE) ?? '';
  } catch {
    return '';
  }
}

export const useMapSettingsStore = create<MapSettingsState>((set, get) => ({
  baseMapType: 'osm',
  tiandituKey: '',
  geovisToken: '',
  isInitialized: false,
  isLoadingConfig: false,
  configError: null,

  initialize: async () => {
    if (get().isInitialized || get().isLoadingConfig) {
      return;
    }

    set({ isLoadingConfig: true, configError: null });

    const storedKey = readStoredKey();
    const storedBaseMap = readStoredBaseMap();
    const storedGeovis = readStoredGeovisToken();
    let serverConfig: MapConfig | null = null;
    let configError: string | null = null;

    try {
      serverConfig = await apiGet<MapConfig>('/config/map');
    } catch (error) {
      configError = error instanceof Error ? error.message : '地图配置读取失败';
    }

    const tiandituKey = storedKey || serverConfig?.tiandituKey || '';
    const geovisToken = storedGeovis || serverConfig?.geovisToken || '';
    // Persist geovis token from server config so MapLibre3DView can read it
    if (geovisToken && !storedGeovis) {
      writeStoredGeovisToken(geovisToken);
    }
    set({
      tiandituKey,
      geovisToken,
      baseMapType: tiandituKey ? storedBaseMap : 'osm',
      isInitialized: true,
      isLoadingConfig: false,
      configError,
    });
  },

  setBaseMapType: (type) => {
    const nextType = type === 'osm' || get().tiandituKey ? type : 'osm';
    writeStoredBaseMap(nextType);
    set({ baseMapType: nextType });
  },

  saveTiandituKey: (key) => {
    const normalizedKey = key.trim();
    writeStoredKey(normalizedKey);
    set((state) => ({
      tiandituKey: normalizedKey,
      baseMapType: normalizedKey ? state.baseMapType : 'osm',
    }));
  },

  clearTiandituKey: () => {
    writeStoredKey('');
    set({ tiandituKey: '', baseMapType: 'osm' });
  },
}));
