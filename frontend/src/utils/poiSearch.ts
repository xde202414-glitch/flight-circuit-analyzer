import { PoiSearchBounds, PoiSearchResult } from '../types/map';

interface TiandituPoi {
  name?: unknown;
  address?: unknown;
  lonlat?: unknown;
  longitude?: unknown;
  latitude?: unknown;
  lon?: unknown;
  lat?: unknown;
  location?: unknown;
  phone?: unknown;
}

interface OSMPlace {
  place_id?: number;
  osm_id?: number;
  display_name?: string;
  name?: string;
  lat?: string;
  lon?: string;
}

export interface PoiSearchOptions {
  query: string;
  bounds: PoiSearchBounds;
  zoom: number;
  tiandituKey: string;
  limit?: number;
}

const DEFAULT_LIMIT = 10;

function isFiniteCoordinate(latitude: number, longitude: number): boolean {
  return (
    Number.isFinite(latitude) &&
    Number.isFinite(longitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    longitude >= -180 &&
    longitude <= 180
  );
}

function parseNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === 'string') {
    const parsed = Number(value.trim());
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
}

function parseTiandituLonLat(item: TiandituPoi): { longitude: number; latitude: number } | null {
  const directLongitude = parseNumber(item.longitude ?? item.lon);
  const directLatitude = parseNumber(item.latitude ?? item.lat);
  if (
    directLongitude !== null &&
    directLatitude !== null &&
    isFiniteCoordinate(directLatitude, directLongitude)
  ) {
    return { longitude: directLongitude, latitude: directLatitude };
  }

  const lonlat = typeof item.lonlat === 'string'
    ? item.lonlat
    : typeof item.location === 'string'
      ? item.location
      : '';
  const parts = lonlat.split(/[,，\s]+/).filter(Boolean).map(Number);
  if (parts.length >= 2 && isFiniteCoordinate(parts[1], parts[0])) {
    return { longitude: parts[0], latitude: parts[1] };
  }

  return null;
}

function normalizeTiandituResponse(payload: unknown, limit: number): PoiSearchResult[] {
  const record = payload as Record<string, unknown>;
  const pois = Array.isArray(record.pois)
    ? record.pois
    : Array.isArray(record.results)
      ? record.results
      : [];

  return pois
    .map((raw, index): PoiSearchResult | null => {
      const item = raw as TiandituPoi;
      const coordinate = parseTiandituLonLat(item);
      const name = typeof item.name === 'string' ? item.name.trim() : '';
      if (!coordinate || !name) {
        return null;
      }

      return {
        id: `tianditu-${index}-${coordinate.longitude}-${coordinate.latitude}`,
        name,
        address: typeof item.address === 'string' ? item.address : undefined,
        coordinate,
        source: 'tianditu',
      };
    })
    .filter((item): item is PoiSearchResult => item !== null)
    .slice(0, limit);
}

function normalizeOSMResponse(payload: unknown, limit: number): PoiSearchResult[] {
  if (!Array.isArray(payload)) {
    return [];
  }

  return payload
    .map((raw, index): PoiSearchResult | null => {
      const item = raw as OSMPlace;
      const latitude = parseNumber(item.lat);
      const longitude = parseNumber(item.lon);
      if (latitude === null || longitude === null || !isFiniteCoordinate(latitude, longitude)) {
        return null;
      }

      const displayName = item.display_name ?? item.name ?? '';
      const [name, ...rest] = displayName.split(',').map((part) => part.trim()).filter(Boolean);
      if (!name) {
        return null;
      }

      return {
        id: `osm-${item.place_id ?? item.osm_id ?? index}`,
        name,
        address: rest.join(', '),
        coordinate: { latitude, longitude },
        source: 'osm',
      };
    })
    .filter((item): item is PoiSearchResult => item !== null)
    .slice(0, limit);
}

async function searchTianditu(options: PoiSearchOptions): Promise<PoiSearchResult[]> {
  const { bounds, query, zoom, tiandituKey, limit = DEFAULT_LIMIT } = options;
  const postStr = {
    keyWord: query,
    queryType: '1',
    mapBound: `${bounds.west},${bounds.south},${bounds.east},${bounds.north}`,
    level: String(Math.max(1, Math.min(18, Math.round(zoom || 13)))),
    start: '0',
    count: String(limit),
  };
  const params = new URLSearchParams({
    postStr: JSON.stringify(postStr),
    type: 'query',
    tk: tiandituKey,
  });

  const response = await fetch(`https://api.tianditu.gov.cn/v2/search?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`天地图搜索失败：HTTP ${response.status}`);
  }

  return normalizeTiandituResponse(await response.json(), limit);
}

async function searchOSM(options: PoiSearchOptions): Promise<PoiSearchResult[]> {
  const { bounds, query, limit = DEFAULT_LIMIT } = options;
  const params = new URLSearchParams({
    format: 'jsonv2',
    q: query,
    limit: String(limit),
    viewbox: `${bounds.west},${bounds.north},${bounds.east},${bounds.south}`,
    bounded: '1',
  });

  const response = await fetch(`https://nominatim.openstreetmap.org/search?${params.toString()}`, {
    headers: {
      Accept: 'application/json',
    },
  });
  if (!response.ok) {
    throw new Error(`OSM 搜索失败：HTTP ${response.status}`);
  }

  return normalizeOSMResponse(await response.json(), limit);
}

export async function searchPoi(options: PoiSearchOptions): Promise<PoiSearchResult[]> {
  if (options.tiandituKey) {
    try {
      return await searchTianditu(options);
    } catch (error) {
      console.warn('[POI] Tianditu search failed, falling back to OSM.', error);
    }
  }

  return searchOSM(options);
}
