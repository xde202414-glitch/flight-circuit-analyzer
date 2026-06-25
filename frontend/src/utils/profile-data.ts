export type ProfileSample = {
  distance: number;
  altitude: number;
  longitude: number | null;
  latitude: number | null;
  raw: Record<string, unknown>;
};

export type TerrainSample = {
  distance: number;
  elevation: number;
  longitude: number | null;
  latitude: number | null;
  raw: Record<string, unknown>;
};

export type CloudSample = {
  distance: number | null;
  crossOffset: number | null;
  elevation: number;
  longitude: number | null;
  latitude: number | null;
  raw: Record<string, unknown>;
};

export type ProfileLayer = {
  sequence: number;
  name: string;
  bottomHeight: number;
  topHeight: number;
};

export type ProfileBundle = {
  profilePoints: ProfileSample[];
  terrainPoints: TerrainSample[];
  cloudPoints: CloudSample[];
  layers: ProfileLayer[];
  routeBottom: number | null;
  routeTop: number | null;
  hasTerrain: boolean;
  hasCloud: boolean;
};

type UnknownRecord = Record<string, unknown>;

function arrayValue(value: unknown): UnknownRecord[] {
  return Array.isArray(value) ? (value as UnknownRecord[]) : [];
}

function numberOrNull(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function numberOrNaN(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function normalizedProfilePoint(item: UnknownRecord): ProfileSample | null {
  const distance = numberOrNaN(item.distance_m ?? item.distance);
  const altitude = numberOrNaN(item.altitude_m ?? item.altitude ?? item.height);
  if (!Number.isFinite(distance) || !Number.isFinite(altitude)) return null;
  return {
    distance,
    altitude,
    longitude: numberOrNull(item.longitude ?? item.lon),
    latitude: numberOrNull(item.latitude ?? item.lat),
    raw: item,
  };
}

function normalizedTerrainPoint(item: UnknownRecord): TerrainSample | null {
  const distance = numberOrNaN(item.distance_m ?? item.distance);
  const elevation = numberOrNaN(item.elevation_m ?? item.altitude_m ?? item.height);
  if (!Number.isFinite(distance) || !Number.isFinite(elevation)) return null;
  return {
    distance,
    elevation,
    longitude: numberOrNull(item.longitude ?? item.lon),
    latitude: numberOrNull(item.latitude ?? item.lat),
    raw: item,
  };
}

function normalizedCloudPoint(item: UnknownRecord): CloudSample | null {
  const elevation = numberOrNaN(item.elevation_m ?? item.altitude_m ?? item.height);
  if (!Number.isFinite(elevation)) return null;
  return {
    distance: numberOrNull(item.distance_m ?? item.distance ?? item.source_distance_m),
    crossOffset: numberOrNull(item.cross_offset_m ?? item.offset_m ?? item.offset),
    elevation,
    longitude: numberOrNull(item.longitude ?? item.lon),
    latitude: numberOrNull(item.latitude ?? item.lat),
    raw: item,
  };
}

function normalizedLayers(profile: UnknownRecord | null | undefined): ProfileLayer[] {
  return arrayValue(profile?.layers)
    .map((item, index) => {
      const bottomHeight = numberOrNaN(item.bottom_height);
      const topHeight = numberOrNaN(item.top_height);
      if (!Number.isFinite(bottomHeight) || !Number.isFinite(topHeight) || topHeight <= bottomHeight) {
        return null;
      }
      return {
        sequence: Number(item.sequence ?? index + 1),
        name: String(item.name || `子航路${index + 1}`),
        bottomHeight,
        topHeight,
      };
    })
    .filter((item): item is ProfileLayer => Boolean(item))
    .sort((a, b) => a.sequence - b.sequence);
}

function applyAltitudeSmoothing(
  points: UnknownRecord[],
  minChange: number,
): UnknownRecord[] {
  if (!points.length || minChange <= 0) return points;

  const threshold = Math.max(0, minChange);
  const result: UnknownRecord[] = [];
  let prevAltitude: number | null = null;

  for (const point of points) {
    const altitude = Number(point.altitude_m ?? point.altitude ?? point.height);
    if (!Number.isFinite(altitude)) {
      result.push(point);
      continue;
    }

    if (prevAltitude === null) {
      result.push(point);
      prevAltitude = altitude;
      continue;
    }

    if (Math.abs(altitude - prevAltitude) < threshold) {
      result.push({
        ...point,
        altitude_m: prevAltitude,
        altitude: prevAltitude,
      });
    } else {
      result.push(point);
      prevAltitude = altitude;
    }
  }

  return result;
}

export function normalizeProfileBundle(
  profile: UnknownRecord | null | undefined,
  geoTerrain?: UnknownRecord | null,
): ProfileBundle {
  const profilePointSource = arrayValue(profile?.altitude_profile_points).length
    ? arrayValue(profile?.altitude_profile_points)
    : arrayValue(profile?.points);

  const altitudeChangeMin = Number(profile?.altitude_change_min ?? 10);
  const altitudeReferenceMode = String(profile?.altitude_reference_mode ?? 'asl');

  let processedPoints = profilePointSource;
  if (altitudeReferenceMode === 'asl' && profilePointSource.length > 0) {
    processedPoints = applyAltitudeSmoothing(profilePointSource, altitudeChangeMin);
  }

  const profilePoints = processedPoints
    .map(normalizedProfilePoint)
    .filter((item): item is ProfileSample => Boolean(item))
    .sort((a, b) => a.distance - b.distance);

  const geoTerrainPoints = arrayValue(geoTerrain?.points);
  const terrainPointSource = geoTerrainPoints.length ? geoTerrainPoints : arrayValue(profile?.terrain_points);
  const terrainPoints = terrainPointSource
    .map(normalizedTerrainPoint)
    .filter((item): item is TerrainSample => Boolean(item))
    .sort((a, b) => a.distance - b.distance);

  const geoCloudPoints = arrayValue(geoTerrain?.cloud_points);
  const profileCloudPoints = arrayValue(profile?.terrain_cloud_points).length
    ? arrayValue(profile?.terrain_cloud_points)
    : arrayValue(profile?.cloud_points);
  const cloudPointSource = geoCloudPoints.length ? geoCloudPoints : profileCloudPoints;
  let cloudPoints = cloudPointSource
    .map(normalizedCloudPoint)
    .filter((item): item is CloudSample => Boolean(item));

  if (!cloudPoints.length && terrainPoints.length) {
    cloudPoints = terrainPoints.map((point) => ({
      distance: point.distance,
      crossOffset: 0,
      elevation: point.elevation,
      longitude: point.longitude,
      latitude: point.latitude,
      raw: point.raw,
    }));
  }

  const routeBottom = numberOrNull(profile?.route_bottom);
  const routeTop = numberOrNull(profile?.route_top);

  return {
    profilePoints,
    terrainPoints,
    cloudPoints,
    layers: normalizedLayers(profile),
    routeBottom,
    routeTop,
    hasTerrain: terrainPoints.length > 0,
    hasCloud: cloudPoints.some((item) => Number.isFinite(Number(item.distance)) && Number.isFinite(Number(item.crossOffset))),
  };
}

export function interpolateTerrainElevation(terrainPoints: TerrainSample[], distance: number): number | null {
  if (!terrainPoints.length || !Number.isFinite(distance)) return null;
  if (distance <= terrainPoints[0].distance) return terrainPoints[0].elevation;
  if (distance >= terrainPoints[terrainPoints.length - 1].distance) return terrainPoints[terrainPoints.length - 1].elevation;
  for (let index = 1; index < terrainPoints.length; index += 1) {
    const prev = terrainPoints[index - 1];
    const next = terrainPoints[index];
    if (distance <= next.distance) {
      const span = next.distance - prev.distance;
      if (Math.abs(span) < 0.01) return prev.elevation;
      const ratio = (distance - prev.distance) / span;
      return prev.elevation + (next.elevation - prev.elevation) * ratio;
    }
  }
  return null;
}

export function getNearestProfilePoint(profilePoints: ProfileSample[], distance: number | null): ProfileSample | null {
  if (!profilePoints.length) return null;
  const target = Number(distance);
  if (!Number.isFinite(target)) return profilePoints[Math.floor(profilePoints.length / 2)] ?? profilePoints[0];
  return profilePoints.reduce((best, item) => (Math.abs(item.distance - target) < Math.abs(best.distance - target) ? item : best), profilePoints[0]);
}

export function estimateSlope(profilePoints: ProfileSample[], distance: number): number | null {
  if (profilePoints.length < 2 || !Number.isFinite(distance)) return null;
  let index = profilePoints.findIndex((item) => item.distance >= distance);
  if (index < 0) index = profilePoints.length - 1;
  const prev = profilePoints[Math.max(0, index - 1)];
  const next = profilePoints[Math.min(profilePoints.length - 1, index + 1)];
  const run = next.distance - prev.distance;
  if (Math.abs(run) < 0.01) return null;
  return ((next.altitude - prev.altitude) / run) * 100;
}
