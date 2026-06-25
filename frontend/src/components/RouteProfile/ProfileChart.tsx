import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Sample = {
  distance: number;
  elevation: number;
  longitude: number | null;
  latitude: number | null;
  raw: Record<string, unknown>;
};

type LayerBand = {
  topHeight: number;
  bottomHeight: number;
  name: string;
};

interface ProfileChartProps {
  points?: Array<Record<string, unknown>>;
  profilePoints?: Array<Record<string, unknown>>;
  terrainPoints?: Array<Record<string, unknown>>;
  layers?: Array<Record<string, unknown>>;
  routeBottom?: number | null;
  routeTop?: number | null;
  interactive?: boolean;
  selectedDistance?: number | null;
  title?: string;
  altitudeChangeMin?: number;
  focusTrackEnabled?: boolean;
  onTrace?: (payload: { distance: number; elevation: number; point: Record<string, unknown> }) => void;
  onFocusPoint?: (payload: { longitude: number | null; latitude: number | null; distance: number }) => void;
}

const margin = { left: 48, right: 30, top: 22, bottom: 30 };
const plotWidth = 720 - margin.left - margin.right;
const plotHeight = 180 - margin.top - margin.bottom;
const bandColors = ["#fce8d4", "#fdeedc", "#e5f1ff", "#dbeafe", "#d1fae5", "#fee2e2"];
const gradientId = `profileBg-${Math.random().toString(36).slice(2)}`;

function pn(v: unknown): number { const n = Number(v); return Number.isFinite(n) ? n : NaN; }
function pon(v: unknown): number | null { const n = Number(v); return Number.isFinite(n) ? n : null; }

export default function ProfileChart(props: ProfileChartProps) {
  const {
    points = [],
    profilePoints = [],
    terrainPoints = [],
    layers: propLayers = [],
    routeBottom: propRouteBottom = null,
    routeTop: propRouteTop = null,
    interactive = false,
    selectedDistance: propSelectedDistance = null,
    title = "纵断面",
    altitudeChangeMin = 10,
    focusTrackEnabled = false,
    onTrace,
    onFocusPoint,
  } = props;

  const wrapperRef = useRef<HTMLDivElement>(null);
  const [showTrace, setShowTrace] = useState(false);
  const [traceX, setTraceX] = useState(0);
  const [traceY, setTraceY] = useState(0);
  const [traceLabel, setTraceLabel] = useState("");
  const lastMouseDistance = useRef(-1);
  const traceEmitRef = useRef<number | null>(null);
  const lastTraceEmitTs = useRef(0);

  const rawProfileSamples = useMemo<Sample[]>(() => {
    const source = (profilePoints.length ? profilePoints : points) ?? [];
    return source
      .map((item) => ({
        distance: pn(item.distance_m ?? item.distance),
        elevation: pn(item.altitude_m ?? item.altitude ?? item.elevation_m ?? item.height),
        longitude: pon(item.longitude ?? item.lon),
        latitude: pon(item.latitude ?? item.lat),
        raw: item,
      }))
      .filter((item) => Number.isFinite(item.distance) && Number.isFinite(item.elevation))
      .sort((a, b) => a.distance - b.distance);
  }, [profilePoints, points]);

  const rawTerrainSamples = useMemo<Sample[]>(() => {
    return terrainPoints
      .map((item) => ({
        distance: pn(item.distance_m ?? item.distance),
        elevation: pn(item.elevation_m ?? item.altitude_m ?? item.height),
        longitude: pon(item.longitude ?? item.lon),
        latitude: pon(item.latitude ?? item.lat),
        raw: item,
      }))
      .filter((item) => Number.isFinite(item.distance) && Number.isFinite(item.elevation))
      .sort((a, b) => a.distance - b.distance);
  }, [terrainPoints]);

  const layers = useMemo<LayerBand[]>(() => {
    return propLayers
      .map((item, index) => ({
        topHeight: pn(item.top_height),
        bottomHeight: pn(item.bottom_height),
        name: String(item.name || `子航路${index + 1}`),
      }))
      .filter((item) => Number.isFinite(item.topHeight) && Number.isFinite(item.bottomHeight) && item.topHeight > item.bottomHeight);
  }, [propLayers]);

  const chart = useMemo(() => {
    const source = rawProfileSamples.length >= 2 ? rawProfileSamples : rawTerrainSamples;
    if (source.length < 2) return null;

    const minD = Math.min(...source.map((item) => item.distance));
    const maxD = Math.max(...source.map((item) => item.distance));
    const dRange = Math.max(1, maxD - minD);
    const x = (distance: number) => margin.left + ((distance - minD) / dRange) * plotWidth;

    const profileAltitudes = rawProfileSamples.map((item) => item.elevation);
    const terrainAltitudes = rawTerrainSamples.map((item) => item.elevation);
    const altitudeBase = [...profileAltitudes, ...terrainAltitudes];

    const layerAbsolute: number[] = [];
    if (layers.length) {
      if (rawTerrainSamples.length) {
        for (const sample of rawTerrainSamples) {
          for (const layer of layers) {
            layerAbsolute.push(sample.elevation + layer.topHeight, sample.elevation + layer.bottomHeight);
          }
        }
      } else {
        for (const layer of layers) {
          layerAbsolute.push(layer.topHeight, layer.bottomHeight);
        }
      }
    }
    const routeBottom = pon(propRouteBottom);
    const routeTop = pon(propRouteTop);
    if (routeBottom !== null) altitudeBase.push(routeBottom);
    if (routeTop !== null) altitudeBase.push(routeTop);
    if (!altitudeBase.length) return null;

    const minE = Math.min(...altitudeBase);
    const maxE = Math.max(...altitudeBase);
    const ePad = Math.max(8, (maxE - minE) * 0.08);
    const chartMinE = minE - ePad;
    const chartMaxE = maxE + ePad;
    const eRange = Math.max(1, chartMaxE - chartMinE);
    const y = (elevation: number) => margin.top + ((chartMaxE - elevation) / eRange) * plotHeight;

    const profileCoords = rawProfileSamples.length
      ? rawProfileSamples.map((item) => [x(item.distance), y(item.elevation)] as const)
      : source.map((item) => [x(item.distance), y(item.elevation)] as const);
    const profileLine = profileCoords.map((coord, i) => `${i === 0 ? "M" : "L"}${coord[0].toFixed(2)},${coord[1].toFixed(2)}`).join(" ");
    const profileArea = `${profileLine} L${margin.left + plotWidth},${margin.top + plotHeight} L${margin.left},${margin.top + plotHeight} Z`;

    const terrainLine = rawTerrainSamples.length >= 2
      ? rawTerrainSamples.map((item, i) => `${i === 0 ? "M" : "L"}${x(item.distance).toFixed(2)},${y(item.elevation).toFixed(2)}`).join(" ")
      : "";

    const layerBands = layers.map((layer, i) => {
      const fill = bandColors[i % bandColors.length];
      if (rawTerrainSamples.length >= 2) {
        const top = rawTerrainSamples.map((item) => ({ distance: item.distance, elevation: item.elevation + layer.topHeight }));
        const bottom = [...rawTerrainSamples].reverse().map((item) => ({ distance: item.distance, elevation: item.elevation + layer.bottomHeight }));
        const merged = [...top, ...bottom];
        const path = merged.map((item, j) => `${j === 0 ? "M" : "L"}${x(item.distance).toFixed(2)},${y(item.elevation).toFixed(2)}`).join(" ");
        return { path: `${path} Z`, fill };
      }
      const topY = y(layer.topHeight);
      const bottomY = y(layer.bottomHeight);
      const path = `M${margin.left},${topY.toFixed(2)} L${(margin.left + plotWidth).toFixed(2)},${topY.toFixed(2)} L${(margin.left + plotWidth).toFixed(2)},${bottomY.toFixed(2)} L${margin.left},${bottomY.toFixed(2)} Z`;
      return { path, fill };
    });

    const ticks = Array.from({ length: 5 }, (_, i) => {
      const elevation = chartMinE + ((chartMaxE - chartMinE) / 4) * i;
      return { y: y(elevation), label: `${elevation.toFixed(0)}m` };
    });

    return {
      minD, dRange, x, y,
      profileLine, profileArea, terrainLine,
      ticks, layerBands,
      totalDistanceLabel: `${Math.round(maxD - minD)}m`,
      legendText: terrainLine ? "蓝色：航路高程 / 棕色虚线：地形高程" : "蓝色：航路高程",
    };
  }, [rawProfileSamples, rawTerrainSamples, layers, propRouteBottom, propRouteTop]);

  const interpolateAtDistance = useCallback((distance: number): { distance: number; elevation: number; raw: Record<string, unknown> } | null => {
    const source = rawProfileSamples.length ? rawProfileSamples : rawTerrainSamples;
    if (!Number.isFinite(distance) || source.length < 2) return null;
    const step = Math.max(1, Number(altitudeChangeMin) || 10);
    const alignedDistance = Math.round(distance / step) * step;

    for (let i = 0; i < source.length - 1; i++) {
      const prev = source[i];
      const next = source[i + 1];
      if (alignedDistance >= prev.distance && alignedDistance <= next.distance) {
        const ratio = (alignedDistance - prev.distance) / (next.distance - prev.distance);
        const elevation = prev.elevation + (next.elevation - prev.elevation) * ratio;
        const longitude = prev.longitude !== null && next.longitude !== null ? prev.longitude + (next.longitude - prev.longitude) * ratio : null;
        const latitude = prev.latitude !== null && next.latitude !== null ? prev.latitude + (next.latitude - prev.latitude) * ratio : null;
        return { distance: alignedDistance, elevation, raw: { ...prev.raw, distance_m: alignedDistance, altitude_m: elevation, longitude, latitude, is_interpolated: true } };
      }
    }
    if (alignedDistance < source[0].distance) return { distance: alignedDistance, elevation: source[0].elevation, raw: source[0].raw };
    if (alignedDistance > source[source.length - 1].distance) return { distance: alignedDistance, elevation: source[source.length - 1].elevation, raw: source[source.length - 1].raw };
    return null;
  }, [rawProfileSamples, rawTerrainSamples, altitudeChangeMin]);

  const emitTrace = useCallback((distance: number) => {
    const interpolated = interpolateAtDistance(distance);
    if (!interpolated) return;
    onTrace?.({
      distance: interpolated.distance,
      elevation: interpolated.elevation,
      point: interpolated.raw,
    });
    if (focusTrackEnabled) {
      onFocusPoint?.({
        longitude: interpolated.raw.longitude as number | null ?? null,
        latitude: interpolated.raw.latitude as number | null ?? null,
        distance: interpolated.distance,
      });
    }
  }, [interpolateAtDistance, onTrace, onFocusPoint, focusTrackEnabled]);

  // Sync selectedDistance prop updates
  useEffect(() => {
    if (propSelectedDistance === null || propSelectedDistance === undefined || !chart) {
      setShowTrace(false);
      lastMouseDistance.current = -1;
      return;
    }
    const interpolated = interpolateAtDistance(Number(propSelectedDistance));
    if (!interpolated) { setShowTrace(false); return; }
    setTraceX(chart.x(interpolated.distance));
    setTraceY(chart.y(interpolated.elevation));
    setTraceLabel(`${Math.round(interpolated.distance)}m / ${Math.round(interpolated.elevation)}m`);
    setShowTrace(true);
  }, [propSelectedDistance, chart, interpolateAtDistance]);

  const handleMouseMove = useCallback((event: React.MouseEvent<SVGSVGElement>) => {
    if (!interactive || !chart) return;
    const rect = (event.currentTarget as SVGSVGElement).getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / Math.max(1, rect.width)) * 720;
    if (svgX < margin.left || svgX > margin.left + plotWidth) return;
    const ratio = (svgX - margin.left) / plotWidth;
    const distance = chart.minD + ratio * chart.dRange;
    const interpolated = interpolateAtDistance(distance);
    if (!interpolated) return;
    const step = Math.max(1, Number(altitudeChangeMin) || 10);
    if (Math.abs(interpolated.distance - lastMouseDistance.current) < step / 2) return;
    lastMouseDistance.current = interpolated.distance;
    setTraceX(chart.x(interpolated.distance));
    setTraceY(chart.y(interpolated.elevation));
    setTraceLabel(`${Math.round(interpolated.distance)}m / ${Math.round(interpolated.elevation)}m`);
    setShowTrace(true);

    const payload = { distance: interpolated.distance, elevation: interpolated.elevation, raw: interpolated.raw };
    if (traceEmitRef.current) cancelAnimationFrame(traceEmitRef.current);
    traceEmitRef.current = requestAnimationFrame((ts) => {
      traceEmitRef.current = null;
      if (ts - lastTraceEmitTs.current < 32) {
        traceEmitRef.current = requestAnimationFrame((ts2) => {
          if (ts2 - lastTraceEmitTs.current < 32) return;
          lastTraceEmitTs.current = ts2;
          onTrace?.({ distance: payload.distance, elevation: payload.elevation, point: payload.raw });
          if (focusTrackEnabled) onFocusPoint?.({ longitude: payload.raw.longitude as number | null ?? null, latitude: payload.raw.latitude as number | null ?? null, distance: payload.distance });
        });
        return;
      }
      lastTraceEmitTs.current = ts;
      onTrace?.({ distance: payload.distance, elevation: payload.elevation, point: payload.raw });
      if (focusTrackEnabled) onFocusPoint?.({ longitude: payload.raw.longitude as number | null ?? null, latitude: payload.raw.latitude as number | null ?? null, distance: payload.distance });
    });
  }, [interactive, chart, interpolateAtDistance, altitudeChangeMin, onTrace, onFocusPoint, focusTrackEnabled]);

  const handleKeyDown = useCallback((event: React.KeyboardEvent) => {
    if (!interactive || !chart) return;
    const step = Math.max(1, Number(altitudeChangeMin) || 10);
    let currentDistance = propSelectedDistance ?? chart.minD + chart.dRange / 2;
    let newDistance = currentDistance;
    let handled = false;
    switch (event.key) {
      case "ArrowLeft": newDistance = currentDistance - step; handled = true; break;
      case "ArrowRight": newDistance = currentDistance + step; handled = true; break;
      case "ArrowUp": newDistance = currentDistance + step * 5; handled = true; break;
      case "ArrowDown": newDistance = currentDistance - step * 5; handled = true; break;
    }
    if (handled) {
      event.preventDefault();
      const minD = chart.minD;
      const maxD = chart.minD + chart.dRange;
      newDistance = Math.max(minD, Math.min(maxD, newDistance));
      emitTrace(newDistance);
    }
  }, [interactive, chart, altitudeChangeMin, propSelectedDistance, emitTrace]);

  // Cleanup
  useEffect(() => {
    return () => {
      if (traceEmitRef.current) cancelAnimationFrame(traceEmitRef.current);
    };
  }, []);

  return (
    <div
      ref={wrapperRef}
      className={`profile-wrapper ${focusTrackEnabled ? "focus-mode" : ""}`}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      style={{
        position: "relative",
        outline: "none",
        borderRadius: 8,
        boxShadow: focusTrackEnabled ? "0 0 0 2px rgba(231, 76, 60, 0.4)" : undefined,
        height: "100%",
      }}
    >
      {focusTrackEnabled && (
        <div style={{
          position: "absolute", top: 4, right: 8,
          background: "rgba(231, 76, 60, 0.9)", color: "white",
          fontSize: 11, padding: "2px 8px", borderRadius: 4,
          zIndex: 10, pointerEvents: "none",
        }}>焦点跟踪模式</div>
      )}
      <svg
        className="profile"
        viewBox="0 0 720 180"
        preserveAspectRatio="none"
        onMouseMove={handleMouseMove}
        onClick={handleMouseMove}
        style={{ width: "100%", height: "100%", cursor: "crosshair" }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f8fcff" />
            <stop offset="100%" stopColor="#ffffff" />
          </linearGradient>
        </defs>
        <rect x="0" y="0" width="720" height="180" fill={`url(#${gradientId})`} />
        {chart ? (
          <g>
            <text x="48" y="14" fill="#34516f" fontSize="12" fontWeight="700">{title}</text>
            <line x1="48" y1="150" x2="690" y2="150" stroke="#d4e1f1" />
            <line x1="48" y1="22" x2="48" y2="150" stroke="#d4e1f1" />
            {chart.ticks.map((tick) => (
              <g key={tick.label}>
                <line x1="48" y1={tick.y} x2="690" y2={tick.y} stroke="#e7eef8" />
                <text x="42" y={tick.y + 3} textAnchor="end" fill="#667895" fontSize="9">{tick.label}</text>
              </g>
            ))}
            {chart.layerBands.map((band, i) => (
              <path key={`layer-${i}`} d={band.path} fill={band.fill} stroke="#c9d8ea" strokeWidth="0.5" opacity="0.58" />
            ))}
            {chart.terrainLine && <path d={chart.terrainLine} fill="none" stroke="#8b5a2b" strokeWidth="2" strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />}
            <path d={chart.profileArea} fill="#dceeff" opacity="0.8" />
            <path d={chart.profileLine} fill="none" stroke="#1677d2" strokeWidth="3" vectorEffect="non-scaling-stroke" />
            {showTrace && (
              <>
                <line x1={traceX} y1="22" x2={traceX} y2="150" stroke="#c0392b" strokeWidth="1.2" strokeDasharray="4 3" />
                <circle cx={traceX} cy={traceY} r="4" fill="#e74c3c" stroke="#fff" strokeWidth="1.5" />
                <text x={traceX + 6} y={Math.max(traceY - 10, 30)} fill="#c0392b" fontSize="10" fontWeight="700" style={{ pointerEvents: "none" }}>{traceLabel}</text>
              </>
            )}
            <text x="52" y="168" fill="#667895" fontSize="11">总里程 {chart.totalDistanceLabel}</text>
            <text x="684" y="168" textAnchor="end" fill="#667895" fontSize="11">{chart.legendText}</text>
            {interactive && <rect x="48" y="22" width="642" height="128" fill="transparent" style={{ cursor: "crosshair" }} />}
          </g>
        ) : (
          <text x="360" y="90" textAnchor="middle" fill="#667895">暂无纵断面数据</text>
        )}
      </svg>
    </div>
  );
}
