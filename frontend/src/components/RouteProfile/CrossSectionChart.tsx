import { useMemo } from "react";

type CloudPoint = { distance_m?: number; cross_offset_m?: number; elevation_m?: number; distance?: number; offset_m?: number; offset?: number; source_distance_m?: number; altitude_m?: number; height?: number };
type TerrainPoint = { distance_m?: number; elevation_m?: number; distance?: number; altitude_m?: number; height?: number };
type ProfilePoint = { distance_m?: number; distance?: number };
type LayerBand = { top_height?: number; bottom_height?: number };

interface CrossSectionChartProps {
  cloudPoints?: CloudPoint[];
  terrainPointsFallback?: TerrainPoint[];
  profilePoints?: ProfilePoint[];
  selectedDistance?: number | null;
  flightWidth?: number | null;
  protectionWidth?: number | null;
  layers?: LayerBand[];
  routeBottom?: number | null;
  routeTop?: number | null;
  title?: string;
}

const margin = { left: 48, right: 30, top: 24, bottom: 30 };
const plotWidth = 720 - margin.left - margin.right;
const plotHeight = 180 - margin.top - margin.bottom;
const layerColors = ["#22c55e55", "#06b6d455", "#a855f755", "#f9731655", "#ef444455"];

export default function CrossSectionChart(props: CrossSectionChartProps) {
  const {
    cloudPoints = [],
    terrainPointsFallback = [],
    profilePoints = [],
    selectedDistance: propSelectedDistance,
    flightWidth: propFlightWidth,
    protectionWidth: propProtectionWidth,
    layers: propLayers = [],
    routeBottom: propRouteBottom,
    routeTop: propRouteTop,
    title = "横断面",
  } = props;

  const chart = useMemo(() => {
    const pn = (v: unknown) => { const n = Number(v); return Number.isFinite(n) ? n : NaN; };
    const pon = (v: unknown) => { const n = Number(v); return Number.isFinite(n) ? n : null; };

    const normCloud = cloudPoints
      .map((item) => ({
        distance: pn(item.distance_m ?? item.distance ?? item.source_distance_m),
        crossOffset: pn(item.cross_offset_m ?? item.offset_m ?? item.offset),
        elevation: pn(item.elevation_m ?? item.altitude_m ?? item.height),
      }))
      .filter((item) => Number.isFinite(item.distance) && Number.isFinite(item.crossOffset) && Number.isFinite(item.elevation));

    const terrain = terrainPointsFallback
      .map((item) => ({
        distance: pn(item.distance_m ?? item.distance),
        elevation: pn(item.elevation_m ?? item.altitude_m ?? item.height),
      }))
      .filter((item) => Number.isFinite(item.distance) && Number.isFinite(item.elevation))
      .sort((a, b) => a.distance - b.distance);

    const profDistances = profilePoints
      .map((item) => pn(item.distance_m ?? item.distance))
      .filter((item) => Number.isFinite(item))
      .sort((a, b) => a - b);

    const layers = propLayers
      .map((item) => ({ topHeight: pn(item.top_height), bottomHeight: pn(item.bottom_height) }))
      .filter((item) => Number.isFinite(item.topHeight) && Number.isFinite(item.bottomHeight) && item.topHeight > item.bottomHeight);

    const flightHalf = Math.max(0, Number(propFlightWidth ?? 0) / 2);
    const protectionHalf = Math.max(flightHalf, flightHalf + Math.max(0, Number(propProtectionWidth ?? 0)));
    const maxHalf = Math.max(1, protectionHalf);

    let selectedDist = Number(propSelectedDistance);
    if (!Number.isFinite(selectedDist)) {
      if (profDistances.length) selectedDist = profDistances[Math.floor(profDistances.length / 2)] ?? 0;
      else if (terrain.length) selectedDist = terrain[Math.floor(terrain.length / 2)]?.distance ?? 0;
      else if (normCloud.length) {
        const sorted = [...normCloud].sort((a, b) => a.distance - b.distance);
        selectedDist = sorted[Math.floor(sorted.length / 2)]?.distance ?? 0;
      }
    }

    function interpolateTerrain(distance: number): number | null {
      if (!terrain.length || !Number.isFinite(distance)) return null;
      if (distance <= terrain[0].distance) return terrain[0].elevation;
      if (distance >= terrain[terrain.length - 1].distance) return terrain[terrain.length - 1].elevation;
      for (let i = 1; i < terrain.length; i++) {
        const prev = terrain[i - 1];
        const next = terrain[i];
        if (distance <= next.distance) {
          const span = next.distance - prev.distance;
          if (Math.abs(span) < 0.01) return prev.elevation;
          return prev.elevation + (next.elevation - prev.elevation) * ((distance - prev.distance) / span);
        }
      }
      return null;
    }

    const distanceBuckets = [...new Set(normCloud.map((item) => item.distance))];
    const nearestDist = distanceBuckets.length
      ? distanceBuckets.reduce((best, item) => (Math.abs(item - selectedDist) < Math.abs(best - selectedDist) ? item : best), distanceBuckets[0])
      : null;

    const cloudSlice = nearestDist === null
      ? []
      : normCloud.filter((item) => Math.abs(item.distance - nearestDist) < 0.01).sort((a, b) => a.crossOffset - b.crossOffset);

    const terrainMid = interpolateTerrain(selectedDist);
    let terrainCurve = cloudSlice;
    if (!terrainCurve.length) {
      const fallbackElevation = Number.isFinite(terrainMid) ? Number(terrainMid) : 0;
      terrainCurve = [
        { distance: selectedDist, crossOffset: -maxHalf, elevation: fallbackElevation },
        { distance: selectedDist, crossOffset: 0, elevation: fallbackElevation },
        { distance: selectedDist, crossOffset: maxHalf, elevation: fallbackElevation },
      ];
    }
    if (terrainCurve.length < 2) return null;

    const curveElevations = terrainCurve.map((item) => item.elevation).filter((v) => Number.isFinite(v));
    const routeBottom = pon(propRouteBottom);
    const routeTop = pon(propRouteTop);
    const hasTerrainBase = Number.isFinite(Number(terrainMid));
    const routeBottomAbs = routeBottom === null ? null : (hasTerrainBase ? Number(terrainMid) + routeBottom : routeBottom);
    const routeTopAbs = routeTop === null ? null : (hasTerrainBase ? Number(terrainMid) + routeTop : routeTop);
    const layerTopAbs = layers.map((item) => (hasTerrainBase ? Number(terrainMid) + item.topHeight : item.topHeight));
    const layerBottomAbs = layers.map((item) => (hasTerrainBase ? Number(terrainMid) + item.bottomHeight : item.bottomHeight));

    const maxAltitude = Math.max(
      300,
      ...curveElevations.map((v) => v + 30),
      ...(routeTopAbs === null ? [] : [routeTopAbs + 20]),
      ...layerTopAbs.map((v) => v + 12),
    );
    const minAltitude = Math.min(
      ...curveElevations.map((v) => v - 10),
      ...(routeBottomAbs === null ? [] : [routeBottomAbs - 20]),
      ...layerBottomAbs.map((v) => v - 8),
    );
    const altitudeRange = Math.max(40, maxAltitude - minAltitude);

    const x = (offset: number) => margin.left + ((offset + maxHalf) / (maxHalf * 2)) * plotWidth;
    const y = (altitude: number) => margin.top + ((maxAltitude - altitude) / altitudeRange) * plotHeight;

    const terrainLine = terrainCurve
      .map((sample, i) => `${i === 0 ? "M" : "L"}${x(sample.crossOffset).toFixed(2)},${y(sample.elevation).toFixed(2)}`)
      .join(" ");

    const routeRect = routeBottomAbs !== null && routeTopAbs !== null && routeTopAbs > routeBottomAbs
      ? {
          topY: y(routeTopAbs),
          height: Math.max(1, y(routeBottomAbs) - y(routeTopAbs)),
          protectionX: x(-protectionHalf),
          protectionWidth: Math.max(2, x(protectionHalf) - x(-protectionHalf)),
          flightX: x(-flightHalf),
          flightWidth: Math.max(2, x(flightHalf) - x(-flightHalf)),
        }
      : null;

    const layerRects = layers.map((layer, i) => {
      const top = hasTerrainBase ? Number(terrainMid) + layer.topHeight : layer.topHeight;
      const bottom = hasTerrainBase ? Number(terrainMid) + layer.bottomHeight : layer.bottomHeight;
      return {
        x: x(-flightHalf),
        y: y(top),
        width: Math.max(2, x(flightHalf) - x(-flightHalf)),
        height: Math.max(1, y(bottom) - y(top)),
        fill: layerColors[i % layerColors.length],
      };
    });

    const elevationTicks = Array.from({ length: 5 }, (_, i) => {
      const elevation = minAltitude + ((maxAltitude - minAltitude) / 4) * i;
      return { y: y(elevation), label: `${elevation.toFixed(0)}m` };
    });

    return {
      centerX: x(0),
      routeRect,
      layerRects,
      terrainLine,
      elevationTicks,
      distanceLabel: `${selectedDist.toFixed(1)}m`,
      offsetLabel: `${Math.round(-maxHalf)}m ~ ${Math.round(maxHalf)}m`,
    };
  }, [cloudPoints, terrainPointsFallback, profilePoints, propSelectedDistance, propFlightWidth, propProtectionWidth, propLayers, propRouteBottom, propRouteTop]);

  return (
    <svg className="profile cross-section" viewBox="0 0 720 180" preserveAspectRatio="none" style={{ width: "100%", height: "100%", display: "block" }}>
      <rect x="0" y="0" width="720" height="180" fill="#fbfdff" />
      {chart ? (
        <g>
          <text x="48" y="18" fill="#34516f" fontSize="13" fontWeight="700">{title}</text>
          <rect x="48" y="24" width="642" height="168" fill="#f8fbff" stroke="#d4e1f1" />
          <line x1={chart.centerX} y1="24" x2={chart.centerX} y2="192" stroke="#8aa6c8" strokeDasharray="4 3" />

          {chart.routeRect && (
            <>
              <rect
                x={chart.routeRect.protectionX}
                y={chart.routeRect.topY}
                width={chart.routeRect.protectionWidth}
                height={chart.routeRect.height}
                fill="#f59e0b33"
                stroke="#d97706"
                strokeWidth="1"
              />
              <rect
                x={chart.routeRect.flightX}
                y={chart.routeRect.topY}
                width={chart.routeRect.flightWidth}
                height={chart.routeRect.height}
                fill="#3b82f640"
                stroke="#2563eb"
                strokeWidth="1.2"
              />
            </>
          )}

          {chart.layerRects.map((band, i) => (
            <rect key={`layer-${i}`} x={band.x} y={band.y} width={band.width} height={band.height} fill={band.fill} stroke="#334155" strokeWidth="0.5" />
          ))}

          <path d={chart.terrainLine} fill="none" stroke="#8b5a2b" strokeWidth="2.4" vectorEffect="non-scaling-stroke" />

          {chart.elevationTicks.map((tick) => (
            <g key={tick.label}>
              <line x1="48" y1={tick.y} x2="690" y2={tick.y} stroke="#e7eef8" />
              <text x="42" y={tick.y + 4} textAnchor="end" fill="#667895" fontSize="10">{tick.label}</text>
            </g>
          ))}
          <text x="52" y="214" fill="#667895" fontSize="12">里程 {chart.distanceLabel}，横向偏移 {chart.offsetLabel}</text>
          <text x="684" y="214" textAnchor="end" fill="#667895" fontSize="12">蓝色：飞行区 / 橙色：保护区 / 棕色：地形</text>
        </g>
      ) : (
        <text x="360" y="122" textAnchor="middle" fill="#667895">暂无横断面数据</text>
      )}
    </svg>
  );
}
