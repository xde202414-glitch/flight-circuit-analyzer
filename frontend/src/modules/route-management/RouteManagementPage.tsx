import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { MapContainer, Polyline, Polygon, Marker, Popup, useMapEvents, useMap } from 'react-leaflet';
import L from 'leaflet';
import { apiClient } from '../../api/client';
import type { RouteInfo, RoutePoint, LandingSite, RouteFullState, RouteCreatePayload } from '../../api/types';
import { CrossSectionChart, ProfileChart } from '../../components/RouteProfile';
import BaseMapLayer from '../../components/MapView/BaseMapLayer';
import { normalizeProfileBundle, getNearestProfilePoint, interpolateTerrainElevation, estimateSlope } from '../../utils/profile-data';

const MAP_DEFAULT: [number, number] = [31.2304, 121.4737];

interface Snapshot {
  points: { name: string; point_type: 'start' | 'waypoint' | 'end'; longitude: number; latitude: number; altitude: number; order_index: number }[];
  landings: { name: string; longitude: number; latitude: number; altitude: number }[];
}

function MapClickHandler({ onMapClick }: { onMapClick: (latlng: L.LatLng) => void }) {
  useMapEvents({ click: (e) => onMapClick(e.latlng) });
  return null;
}

function MapFocusUpdater({ center, zoom }: { center: [number, number]; zoom: number }) {
  const map = useMap();
  useEffect(() => { map.setView(center, zoom); }, [center, zoom, map]);
  return null;
}

function MapResizeObserver() {
  const map = useMap();
  useEffect(() => {
    const container = map.getContainer().parentElement;
    if (!container) return;
    const ro = new ResizeObserver(() => { map.invalidateSize(); });
    ro.observe(container);
    return () => ro.disconnect();
  }, [map]);
  return null;
}

const ResizeHandle: React.FC<{ direction?: 'horizontal' | 'vertical'; onResize: (delta: number) => void }> = ({ direction = 'vertical', onResize }) => {
  const dragging = useRef(false);
  const onResizeRef = useRef(onResize);
  onResizeRef.current = onResize;
  const isVertical = direction === 'vertical';

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      e.preventDefault();
      onResizeRef.current(isVertical ? e.movementX : e.movementY);
    };
    const onMouseUp = () => { dragging.current = false; };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [isVertical]);

  return (
    <div
      onMouseDown={() => { dragging.current = true; }}
      style={{
        [isVertical ? 'width' : 'height']: 6,
        cursor: isVertical ? 'col-resize' : 'row-resize',
        flexShrink: 0,
        background: 'transparent',
        transition: 'background 0.15s',
      }}
      onMouseEnter={e => { (e.target as HTMLElement).style.background = '#93c5fd'; }}
      onMouseLeave={e => { (e.target as HTMLElement).style.background = 'transparent'; }}
    />
  );
};

const RouteManagementPage: React.FC = () => {
  // Core state
  const [routes, setRoutes] = useState<RouteInfo[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<number | null>(null);
  const [fullState, setFullState] = useState<RouteFullState | null>(null);
  const [points, setPoints] = useState<RoutePoint[]>([]);
  const [landings, setLandings] = useState<LandingSite[]>([]);
  const [geoData, setGeoData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [geoLoading, setGeoLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [mapCenter, setMapCenter] = useState<[number, number]>(MAP_DEFAULT);

  // UI state
  const [search, setSearch] = useState('');
  const [sortMode, setSortMode] = useState<'updated' | 'name' | 'points'>('updated');
  const [detailTab, setDetailTab] = useState<'params' | 'points' | 'subRoutes' | 'geo' | 'landings'>('params');
  const [leftWidth, setLeftWidth] = useState(280);
  const [rightWidth, setRightWidth] = useState(320);
  const [mapHeightPx, setMapHeightPx] = useState(400);
  const [addMode, setAddMode] = useState<'start' | 'waypoint' | 'end' | 'landing' | null>(null);
  const [showAllRoutes, setShowAllRoutes] = useState(false);
  const [allRouteLines, setAllRouteLines] = useState<{ id: number; name: string; points: RoutePoint[] }[]>([]);
  const [showProfiles, setShowProfiles] = useState(true);
  const [focusTrackEnabled, setFocusTrackEnabled] = useState(false);
  const [profileDistance, setProfileDistance] = useState<number | null>(null);

  // Undo/redo
  const [undoStack, setUndoStack] = useState<Snapshot[]>([]);
  const [redoStack, setRedoStack] = useState<Snapshot[]>([]);
  const UNDO_LIMIT = 10;

  // Point form
  const [pointForm, setPointForm] = useState({ name: '航路点', point_type: 'waypoint' as 'start' | 'waypoint' | 'end', longitude: 120.16, latitude: 30.25, altitude: 0 });
  // Landing form
  const [landingForm, setLandingForm] = useState({ name: '起降场', longitude: 120.16, latitude: 30.25, altitude: 0 });

  const [formData, setFormData] = useState<RouteCreatePayload>({
    name: '', flight_width: 40, protection_width: 100,
    bottom_height: 60, top_height: 300, turn_mode: 'angle',
    min_turn_radius: 0, altitude_reference_mode: 'asl',
    altitude_change_min: 10, enable_layering: true,
    layer_step: 50, layer_scheme: '60-90,90-120,120-180,180-240,240-300',
  });

  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Derived
  const selectedRoute = useMemo(() => routes.find(r => r.id === selectedRouteId) ?? null, [routes, selectedRouteId]);

  const filteredRoutes = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    let items = keyword ? routes.filter(r => r.name.toLowerCase().includes(keyword)) : [...routes];
    if (sortMode === 'name') items.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'));
    else if (sortMode === 'points') items.sort((a, b) => Number(b.point_count ?? 0) - Number(a.point_count ?? 0));
    return items;
  }, [routes, search, sortMode]);

  const centerline = useMemo(() => {
    const coords: [number, number][] = [];
    const geom = (fullState as any)?.snapshot?.centerline ?? fullState?.centerline;
    if (geom?.coordinates?.length) {
      for (const c of geom.coordinates) {
        if (Array.isArray(c) && c.length >= 2) coords.push([Number(c[1]), Number(c[0])]);
      }
    }
    return coords;
  }, [fullState]);

  const flightZoneCoords: [number, number][] = useMemo(() => {
    const coords: [number, number][] = [];
    const geom = (fullState as any)?.snapshot?.flight_zone ?? fullState?.flight_zone;
    if (geom?.coordinates?.[0]?.length) {
      for (const c of geom.coordinates[0]) {
        if (Array.isArray(c) && c.length >= 2) coords.push([Number(c[1]), Number(c[0])]);
      }
    }
    return coords;
  }, [fullState]);

  const protectionCoords: [number, number][] = useMemo(() => {
    const coords: [number, number][] = [];
    const geom = (fullState as any)?.snapshot?.protection_zone ?? fullState?.protection_zone;
    if (geom?.coordinates?.[0]?.length) {
      for (const c of geom.coordinates[0]) {
        if (Array.isArray(c) && c.length >= 2) coords.push([Number(c[1]), Number(c[0])]);
      }
    }
    return coords;
  }, [fullState]);

  const subRoutes = useMemo(() => {
    return (fullState as any)?.snapshot?.sub_routes ?? fullState?.sub_routes ?? [];
  }, [fullState]);

  const profileBundle = useMemo(() => {
    const profile = (fullState as any)?.snapshot?.profile ?? fullState?.profile ?? null;
    const geoTerrain = geoData?.terrain ?? null;
    return normalizeProfileBundle(profile, geoTerrain);
  }, [fullState, geoData]);

  const turningWarnings = useMemo(() => {
    const turning = (fullState as any)?.snapshot?.turning ?? fullState?.turning;
    return (turning?.warnings ?? []).filter(Boolean);
  }, [fullState]);

  // Profile chart data
  const profilePointsForChart = useMemo(() =>
    profileBundle.profilePoints.map(p => ({ distance_m: p.distance, altitude_m: p.altitude, longitude: p.longitude, latitude: p.latitude })),
    [profileBundle]);
  const terrainPointsForChart = useMemo(() =>
    profileBundle.terrainPoints.map(p => ({ distance_m: p.distance, elevation_m: p.elevation, longitude: p.longitude, latitude: p.latitude })),
    [profileBundle]);
  const cloudPointsForChart = useMemo(() =>
    profileBundle.cloudPoints.map(p => ({ distance_m: p.distance ?? undefined, cross_offset_m: p.crossOffset ?? undefined, elevation_m: p.elevation, longitude: p.longitude, latitude: p.latitude })),
    [profileBundle]);
  const layersForChart = useMemo(() =>
    profileBundle.layers.map(l => ({ sequence: l.sequence, name: l.name, bottom_height: l.bottomHeight, top_height: l.topHeight })),
    [profileBundle]);

  const traceDistanceSource = useMemo(() => {
    if (profileBundle.profilePoints.length) return profileBundle.profilePoints.map(p => p.distance);
    return profileBundle.terrainPoints.map(p => p.distance);
  }, [profileBundle]);

  const effectiveProfileDistance = useMemo(() => {
    if (Number.isFinite(Number(profileDistance))) return Number(profileDistance);
    if (!traceDistanceSource.length) return null;
    return traceDistanceSource[Math.floor(traceDistanceSource.length / 2)] ?? traceDistanceSource[0];
  }, [profileDistance, traceDistanceSource]);

  const traceProfilePoint = useMemo(() =>
    getNearestProfilePoint(profileBundle.profilePoints, effectiveProfileDistance),
    [profileBundle.profilePoints, effectiveProfileDistance]);

  const profileTraceInfo = useMemo(() => {
    const d = effectiveProfileDistance;
    if (d === null) return { distance: '-', elevation: '-', slope: '-', coords: '-' };
    const terrainElevation = interpolateTerrainElevation(profileBundle.terrainPoints, d);
    const slopeValue = estimateSlope(profileBundle.profilePoints, d);
    const point = traceProfilePoint;
    return {
      distance: `${d.toFixed(1)} m`,
      elevation: Number.isFinite(Number(terrainElevation)) ? `${Number(terrainElevation).toFixed(1)} m` : '-',
      slope: Number.isFinite(Number(slopeValue)) ? `${Number(slopeValue).toFixed(1)}%` : '-',
      coords: Number.isFinite(Number(point?.longitude)) && Number.isFinite(Number(point?.latitude))
        ? `${Number(point?.longitude).toFixed(6)}, ${Number(point?.latitude).toFixed(6)}` : '-',
    };
  }, [effectiveProfileDistance, profileBundle, traceProfilePoint]);

  // Data fetching
  const loadRoutes = useCallback(async () => {
    try {
      const res = await apiClient.getRoutes();
      const items = res.items || [];
      setRoutes(items);
      return items;
    } catch { return []; }
  }, []);

  const loadRouteDetail = useCallback(async (routeId: number, opts?: { includeGeo?: boolean; clearGeo?: boolean }) => {
    setLoading(true);
    try {
      const [ptsRes, landRes] = await Promise.all([
        apiClient.getRoutePoints(routeId),
        apiClient.getLandingSites(routeId),
      ]);
      setPoints(ptsRes.items || []);
      setLandings(landRes.items || []);

      let fullStateData: RouteFullState | null = null;
      try {
        fullStateData = await apiClient.getRouteFull(routeId);
        setFullState(fullStateData);
      } catch {
        setFullState(null);
      }

      if (opts?.includeGeo) {
        setGeoLoading(true);
        try {
          const geo = await apiClient.getRouteGeo(routeId);
          if (geo) setGeoData(geo);
        } catch { /* ignore */ }
        setGeoLoading(false);
      }

      // Center map
      if ((fullStateData?.profile?.points?.length ?? 0) > 0) {
        const mid = fullStateData!.profile!.points[Math.floor(fullStateData!.profile!.points.length / 2)];
        setMapCenter([mid.latitude, mid.longitude]);
      } else if (ptsRes.items?.length > 0) {
        setMapCenter([ptsRes.items[0].latitude, ptsRes.items[0].longitude]);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadRoutes(); }, [loadRoutes]);

  useEffect(() => {
    if (selectedRouteId) {
      loadRouteDetail(selectedRouteId, { includeGeo: true, clearGeo: true });
      const route = routes.find(r => r.id === selectedRouteId);
      if (route) {
        setFormData({
          name: route.name, flight_width: route.flight_width,
          protection_width: route.protection_width, bottom_height: route.bottom_height,
          top_height: route.top_height, turn_mode: route.turn_mode,
          min_turn_radius: route.min_turn_radius,
          altitude_reference_mode: route.altitude_reference_mode,
          altitude_change_min: route.altitude_change_min,
          enable_layering: route.enable_layering ?? true,
          layer_step: route.layer_step ?? 50,
          layer_scheme: route.layer_scheme || '60-90,90-120,120-180,180-240,240-300',
        });
      }
      setProfileDistance(null);
      setUndoStack([]);
      setRedoStack([]);
    }
  }, [selectedRouteId]);

  // Auto-save with debounce
  const onParamChange = useCallback((updates: Partial<RouteCreatePayload>) => {
    const newFormData = { ...formData, ...updates };
    setFormData(newFormData);
    if (!selectedRouteId) return;
    if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current);
    autoSaveTimer.current = setTimeout(async () => {
      try {
        await apiClient.updateRoute(selectedRouteId!, { ...newFormData, name: newFormData.name.trim() });
      } catch { /* silent */ }
    }, 500);
  }, [selectedRouteId, formData]);

  // Snapshot management
  const captureSnapshot = useCallback((): Snapshot => ({
    points: [...points].sort((a, b) => a.order_index - b.order_index).map(p => ({
      name: p.name, point_type: p.point_type,
      longitude: Number(p.longitude), latitude: Number(p.latitude),
      altitude: Number(p.altitude ?? 0), order_index: Number(p.order_index ?? 0),
    })),
    landings: landings.map(l => ({
      name: l.name, longitude: Number(l.longitude),
      latitude: Number(l.latitude), altitude: Number(l.altitude ?? 0),
    })),
  }), [points, landings]);

  const pushUndo = useCallback(() => {
    setUndoStack(prev => {
      const next = [...prev, captureSnapshot()];
      if (next.length > UNDO_LIMIT) next.shift();
      return next;
    });
    setRedoStack([]);
  }, [captureSnapshot]);

  const replaceRoutePoints = useCallback(async (routeId: number, nextPoints: Snapshot['points']) => {
    for (const p of points) await apiClient.deleteRoutePoint(routeId, p.id);
    for (const p of nextPoints) {
      await apiClient.createRoutePoint(routeId, {
        name: p.name, point_type: p.point_type,
        longitude: p.longitude, latitude: p.latitude,
        altitude: p.altitude, order_index: p.order_index,
      });
    }
  }, [points]);

  const restoreSnapshot = useCallback(async (snapshot: Snapshot) => {
    if (!selectedRouteId) return;
    const currentLandings = [...landings];
    await replaceRoutePoints(selectedRouteId, snapshot.points);
    for (const l of currentLandings) await apiClient.deleteLandingSite(selectedRouteId, l.id);
    for (const l of snapshot.landings) {
      await apiClient.createLandingSite(selectedRouteId, { ...l, altitude_source: 'manual', altitude_confirmed: false });
    }
    await loadRoutes();
    if (selectedRouteId) await loadRouteDetail(selectedRouteId);
  }, [selectedRouteId, landings, replaceRoutePoints, loadRoutes, loadRouteDetail]);

  const undoEdit = useCallback(async () => {
    const snapshot = undoStack.pop();
    if (!snapshot) return;
    setUndoStack([...undoStack]);
    setRedoStack(prev => [...prev, captureSnapshot()].slice(-UNDO_LIMIT));
    await restoreSnapshot(snapshot);
  }, [undoStack, captureSnapshot, restoreSnapshot]);

  const redoEdit = useCallback(async () => {
    const snapshot = redoStack.pop();
    if (!snapshot) return;
    setRedoStack([...redoStack]);
    setUndoStack(prev => [...prev, captureSnapshot()].slice(-UNDO_LIMIT));
    await restoreSnapshot(snapshot);
  }, [redoStack, captureSnapshot, restoreSnapshot]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      if (e.key === 'z') { e.preventDefault(); undoEdit(); }
      else if (e.key === 'y') { e.preventDefault(); redoEdit(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [undoEdit, redoEdit]);

  // Actions
  const handleCreateRoute = async () => {
    try {
      const res = await apiClient.createRoute({
        ...formData, name: `新建航路 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`,
      });
      setSelectedRouteId(res.id);
      await loadRoutes();
    } catch (e: any) { alert(e?.message || '创建失败'); }
  };

  const handleDeleteRoute = async (id: number) => {
    if (!confirm(`确认删除航路 #${id}？`)) return;
    try {
      await apiClient.deleteRoute(id);
      if (selectedRouteId === id) {
        setSelectedRouteId(null); setPoints([]); setLandings([]); setFullState(null);
      }
      await loadRoutes();
    } catch (e: any) { alert(e?.message || '删除失败'); }
  };

  const handleDuplicateRoute = async (id: number) => {
    const source = routes.find(r => r.id === id);
    try {
      await apiClient.duplicateRoute(id, source ? `${source.name}_copy` : undefined);
      await loadRoutes();
    } catch (e: any) { alert(e?.message || '复制失败'); }
  };

  const handleSelectRoute = async (id: number) => {
    setSelectedRouteId(id);
  };

  const handleGenerate = async () => {
    if (!selectedRouteId) return;
    setGenerating(true);
    try {
      // Save first
      await apiClient.updateRoute(selectedRouteId, { ...formData, name: formData.name.trim() });
      const result = await apiClient.generateRoute(selectedRouteId);
      if (result.ok) {
        await loadRouteDetail(selectedRouteId, { includeGeo: true });
        // Auto-extract geo
        try {
          setGeoLoading(true);
          const geo = await apiClient.extractRouteGeo(selectedRouteId);
          if (geo) setGeoData(geo);
        } catch { /* ignore */ }
        setGeoLoading(false);
      } else {
        alert((result.errors || ['生成失败']).join('\n'));
      }
    } catch (e: any) { alert(e?.message || '生成失败'); }
    setGenerating(false);
  };

  const handleMapClick = async (latlng: L.LatLng) => {
    if (!selectedRouteId || !addMode) return;
    pushUndo();

    if (addMode === 'landing') {
      await apiClient.createLandingSite(selectedRouteId, {
        name: `起降场${landings.length + 1}`,
        longitude: Number(latlng.lng.toFixed(7)), latitude: Number(latlng.lat.toFixed(7)),
        altitude: 0, altitude_source: 'manual', altitude_confirmed: false,
      });
      await loadRouteDetail(selectedRouteId);
      return;
    }

    // Handle start/end/waypoint
    const ordered = [...points].sort((a, b) => a.order_index - b.order_index);
    if (addMode === 'start' || addMode === 'end') {
      const existing = ordered.find(p => p.point_type === addMode);
      const newPoints = ordered.filter(p => p.point_type !== addMode).map(p => ({
        name: p.name, point_type: p.point_type, longitude: p.longitude, latitude: p.latitude, altitude: p.altitude ?? 0, order_index: 0,
      }));
      const endpoint = {
        name: addMode === 'start' ? '起点' : '终点',
        point_type: addMode,
        longitude: Number(latlng.lng.toFixed(7)),
        latitude: Number(latlng.lat.toFixed(7)),
        altitude: existing?.altitude ?? 0,
        order_index: addMode === 'start' ? 0 : newPoints.length,
      };
      const next = addMode === 'start' ? [endpoint, ...newPoints] : [...newPoints, endpoint];
      for (const p of points) await apiClient.deleteRoutePoint(selectedRouteId, p.id);
      for (const p of next) {
        await apiClient.createRoutePoint(selectedRouteId, { ...p, order_index: p.order_index });
      }
    } else {
      // Insert waypoint
      const endpointCount = ordered.filter(p => p.point_type === 'waypoint').length;
      await apiClient.createRoutePoint(selectedRouteId, {
        name: `航路点${endpointCount + 1}`,
        point_type: 'waypoint',
        longitude: Number(latlng.lng.toFixed(7)),
        latitude: Number(latlng.lat.toFixed(7)),
        altitude: 0, order_index: ordered.length,
      });
    }
    await loadRouteDetail(selectedRouteId);
  };

  const handleAddPoint = async () => {
    if (!selectedRouteId) return;
    pushUndo();
    await apiClient.createRoutePoint(selectedRouteId, {
      ...pointForm, name: pointForm.name.trim(),
      longitude: Number(pointForm.longitude), latitude: Number(pointForm.latitude),
    });
    await loadRouteDetail(selectedRouteId);
  };

  const handleDeletePoint = async (pointId: number) => {
    if (!selectedRouteId) return;
    pushUndo();
    await apiClient.deleteRoutePoint(selectedRouteId, pointId);
    await loadRouteDetail(selectedRouteId);
  };

  const handleMovePoint = async (pointId: number, delta: -1 | 1) => {
    if (!selectedRouteId) return;
    const ordered = [...points].sort((a, b) => a.order_index - b.order_index);
    const idx = ordered.findIndex(p => p.id === pointId);
    const targetIdx = idx + delta;
    if (idx < 0 || targetIdx < 0 || targetIdx >= ordered.length) return;
    pushUndo();
    const cur = ordered[idx];
    const tgt = ordered[targetIdx];
    await apiClient.updateRoutePoint(selectedRouteId, cur.id, { name: cur.name, point_type: cur.point_type, longitude: cur.longitude, latitude: cur.latitude, altitude: cur.altitude ?? 0, order_index: tgt.order_index });
    await apiClient.updateRoutePoint(selectedRouteId, tgt.id, { name: tgt.name, point_type: tgt.point_type, longitude: tgt.longitude, latitude: tgt.latitude, altitude: tgt.altitude ?? 0, order_index: cur.order_index });
    await loadRouteDetail(selectedRouteId);
  };

  const handleInsertAfter = async (pointId: number) => {
    if (!selectedRouteId) return;
    const ordered = [...points].sort((a, b) => a.order_index - b.order_index);
    const idx = ordered.findIndex(p => p.id === pointId);
    if (idx < 0) return;
    const cur = ordered[idx];
    const next = ordered[idx + 1];
    pushUndo();
    await apiClient.createRoutePoint(selectedRouteId, {
      name: `航路点${ordered.filter(p => p.point_type === 'waypoint').length + 1}`,
      point_type: 'waypoint',
      longitude: next ? (cur.longitude + next.longitude) / 2 : cur.longitude + 0.001,
      latitude: next ? (cur.latitude + next.latitude) / 2 : cur.latitude + 0.001,
      altitude: cur.altitude ?? 0, order_index: cur.order_index + 1,
    });
    await loadRouteDetail(selectedRouteId);
  };

  const handleClearPoints = async () => {
    if (!selectedRouteId || points.length === 0) return;
    if (!confirm('确认清空当前航路全部点位？此操作可用撤销恢复。')) return;
    pushUndo();
    for (const p of points) await apiClient.deleteRoutePoint(selectedRouteId, p.id);
    await loadRouteDetail(selectedRouteId);
  };

  const handleAddLanding = async () => {
    if (!selectedRouteId) return;
    pushUndo();
    await apiClient.createLandingSite(selectedRouteId, {
      ...landingForm, name: landingForm.name.trim(),
      altitude_source: 'manual', altitude_confirmed: false,
    });
    await loadRouteDetail(selectedRouteId);
  };

  const handleDeleteLanding = async (landingId: number) => {
    if (!selectedRouteId) return;
    pushUndo();
    await apiClient.deleteLandingSite(selectedRouteId, landingId);
    await loadRouteDetail(selectedRouteId);
  };

  const handleExtractSubRoute = async (sequence: number) => {
    if (!selectedRouteId) return;
    try {
      await apiClient.extractSubRoute(selectedRouteId, sequence, `${selectedRoute?.name}_layer_${sequence}`);
      await loadRoutes();
    } catch (e: any) { alert(e?.message || '提取失败'); }
  };

  const handleExportKml = async () => {
    if (!selectedRouteId) return;
    try {
      const url = await apiClient.exportKml(selectedRouteId);
      const link = document.createElement('a');
      link.href = url;
      link.download = `route_${selectedRouteId}.kml`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e: any) { alert(e?.message || '导出失败'); }
  };

  const handleExtractGeo = async () => {
    if (!selectedRouteId) return;
    setGeoLoading(true);
    try {
      const result = await apiClient.extractRouteGeo(selectedRouteId);
      if (result) setGeoData(result);
      await loadRouteDetail(selectedRouteId);
    } catch (e: any) { alert(e?.message || '提取失败'); }
    setGeoLoading(false);
  };

  const handleLoadStoredGeo = async () => {
    if (!selectedRouteId) return;
    setGeoLoading(true);
    try {
      const geo = await apiClient.getRouteGeo(selectedRouteId);
      if (geo) setGeoData(geo);
    } catch { /* ignore */ }
    setGeoLoading(false);
  };

  const handleToggleAllRoutes = async () => {
    const next = !showAllRoutes;
    setShowAllRoutes(next);
    if (next) {
      const otherRoutes = routes.filter(r => r.id !== selectedRouteId);
      const resolved = await Promise.all(
        otherRoutes.map(async r => {
          try {
            const pts = await apiClient.getRoutePoints(r.id);
            return { id: r.id, name: r.name, points: pts.items || [] };
          } catch { return { id: r.id, name: r.name, points: [] }; }
        }),
      );
      setAllRouteLines(resolved.filter(r => r.points.length >= 2));
    } else {
      setAllRouteLines([]);
    }
  };

  const handleTrace = useCallback((payload: { distance: number }) => {
    setProfileDistance(Number(payload.distance));
  }, []);

  const handleFocusPoint = useCallback((payload: { longitude: number | null; latitude: number | null; distance: number }) => {
    if (focusTrackEnabled && payload.longitude !== null && payload.latitude !== null) {
      setMapCenter([Number(payload.latitude), Number(payload.longitude)]);
    }
  }, [focusTrackEnabled]);

  // Map icons
  const pointIcon = (type: string, index: number) => L.divIcon({
    className: '',
    html: `<div style="background:${type === 'start' ? '#16a34a' : type === 'end' ? '#dc2626' : '#2563eb'};color:white;width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;border:2px solid white;box-shadow:0 2px 6px rgba(0,0,0,0.3)">${type === 'start' ? '起' : type === 'end' ? '终' : index}</div>`,
    iconSize: [24, 24], iconAnchor: [12, 12],
  });

  const landingIcon = L.divIcon({
    className: '',
    html: '<div style="background:#8b5cf6;color:white;width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;border:2px solid white;box-shadow:0 2px 6px rgba(0,0,0,0.3)">降</div>',
    iconSize: [22, 22], iconAnchor: [11, 11],
  });

  const warningIcon = L.divIcon({
    className: '',
    html: '<div style="background:#f59e0b;color:white;width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;border:2px solid white;box-shadow:0 2px 6px rgba(0,0,0,0.3)">!</div>',
    iconSize: [20, 20], iconAnchor: [10, 10],
  });

  const zoom = fullState ? 12 : 10;

  return (
    <div className="module-layout" style={{ display: 'flex', gap: 0, height: 'calc(100vh - 100px)' }}>
      {/* Left Panel - Route List */}
      <div className="module-panel" style={{ width: leftWidth, minWidth: 200, maxWidth: 500, flexShrink: 0 }}>
        <div className="module-panel-header">航路管理</div>
        <button className="btn btn-primary btn-sm" style={{ width: '100%', marginBottom: 8 }}
          onClick={handleCreateRoute}>+ 新建</button>
        <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
          <input className="form-input sm" style={{ flex: 1 }} placeholder="搜索航路名称"
            value={search} onChange={e => setSearch(e.target.value)} />
          <select className="form-input sm" style={{ width: 120 }} value={sortMode}
            onChange={e => setSortMode(e.target.value as any)}>
            <option value="updated">按更新时间</option>
            <option value="name">按名称</option>
            <option value="points">按航路点数</option>
          </select>
        </div>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {filteredRoutes.map(route => (
            <div key={route.id} onClick={() => handleSelectRoute(route.id)}
              style={{
                padding: '8px 10px', marginBottom: 4, borderRadius: 8, cursor: 'pointer',
                background: selectedRouteId === route.id ? '#dbeafe' : '#f8fafc',
                border: selectedRouteId === route.id ? '1px solid #93c5fd' : '1px solid #e2e8f0',
              }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>#{route.id} {route.name}</div>
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                点位 {route.point_count ?? 0} · 起降场 {route.landing_count ?? 0}
                <span className={`status-pill ${route.is_complete ? 'pass' : ''}`} style={{ marginLeft: 6 }}>
                  {route.is_complete ? '已生成' : '未生成'}
                </span>
              </div>
              <div style={{ marginTop: 4, display: 'flex', gap: 4 }}>
                <button className="btn btn-xs" onClick={(e) => { e.stopPropagation(); handleSelectRoute(route.id); }}>打开</button>
                <button className="btn btn-xs btn-secondary" onClick={(e) => { e.stopPropagation(); handleDuplicateRoute(route.id); }}>复制</button>
                <button className="btn btn-xs btn-danger" onClick={(e) => { e.stopPropagation(); handleDeleteRoute(route.id); }}>删除</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <ResizeHandle onResize={delta => setLeftWidth(w => Math.max(200, Math.min(500, w + delta)))} />

      {/* Center - Map */}
      <div className="module-map-panel" style={{ flex: 1, minWidth: 300 }}>
        <div className="module-panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>地图工作区</span>
          <div style={{ display: 'flex', gap: 4 }}>
            <button className="btn btn-xs" onClick={handleExportKml} disabled={!selectedRoute}>导出KML</button>
            <button className="btn btn-xs" disabled={!selectedRoute}>定位当前航路</button>
            <button className="btn btn-xs" onClick={handleToggleAllRoutes}>{showAllRoutes ? '隐藏全部' : '显示全部'}</button>
            <button className="btn btn-xs" onClick={() => setShowProfiles(!showProfiles)}>{showProfiles ? '隐藏剖面' : '显示剖面'}</button>
            <button className={`btn btn-xs ${focusTrackEnabled ? 'btn-primary' : ''}`} onClick={() => setFocusTrackEnabled(!focusTrackEnabled)}>
              {focusTrackEnabled ? '关闭焦点跟踪' : '焦点跟踪'}
            </button>
          </div>
        </div>

        {/* Add mode controls */}
        {selectedRouteId && (
          <div style={{ display: 'flex', gap: 4, padding: '4px 8px', background: '#f1f5f9', borderBottom: '1px solid #e2e8f0' }}>
            <span style={{ fontSize: 12, color: '#64748b', lineHeight: '28px' }}>
              标绘：{addMode === 'start' ? '起点' : addMode === 'waypoint' ? '航路点' : addMode === 'end' ? '终点' : addMode === 'landing' ? '起降场' : '关闭'}
            </span>
            {(['start', 'waypoint', 'end', 'landing'] as const).map(mode => (
              <button key={mode} className={`btn btn-xs ${addMode === mode ? 'btn-primary' : ''}`}
                onClick={() => setAddMode(addMode === mode ? null : mode)}>
                {{ start: '起点', waypoint: '航路点', end: '终点', landing: '起降场' }[mode]}
              </button>
            ))}
            <button className="btn btn-xs" onClick={() => setAddMode(null)}>取消</button>
          </div>
        )}

        <div ref={containerRef} style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: showProfiles ? `0 0 ${mapHeightPx}px` : 1, position: 'relative', minHeight: 250 }}>
            <MapContainer center={mapCenter} zoom={zoom} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}>
              <BaseMapLayer />
              <MapResizeObserver />
              <MapClickHandler onMapClick={handleMapClick} />
              <MapFocusUpdater center={mapCenter} zoom={zoom} />

              {/* Protection zone */}
              {protectionCoords.length >= 3 && (
                <Polygon positions={protectionCoords} color="#f97316" fillColor="#f97316" fillOpacity={0.1} weight={2} dashArray="8,4" />
              )}
              {/* Flight zone */}
              {flightZoneCoords.length >= 3 && (
                <Polygon positions={flightZoneCoords} color="#3b82f6" fillColor="#3b82f6" fillOpacity={0.15} weight={2} />
              )}
              {/* Centerline */}
              {centerline.length >= 2 && (
                <Polyline positions={centerline} color="#1d4ed8" weight={4} />
              )}

              {/* Other routes */}
              {showAllRoutes && allRouteLines.map(r => (
                <Polyline key={r.id} positions={r.points.map(p => [p.latitude, p.longitude] as [number, number])}
                  color="#94a3b8" weight={2} opacity={0.5} />
              ))}

              {/* Route points */}
              {points.map((pt) => (
                <Marker key={`pt-${pt.id}`} position={[pt.latitude, pt.longitude]}
                  icon={pointIcon(pt.point_type, pt.order_index)}>
                  <Popup>
                    <div style={{ fontSize: 12 }}>
                      <strong>{pt.name}</strong> ({pt.point_type === 'start' ? '起点' : pt.point_type === 'end' ? '终点' : '航路点'})<br />
                      经度: {pt.longitude.toFixed(5)}<br />
                      纬度: {pt.latitude.toFixed(5)}<br />
                      高度: {pt.altitude}m<br />
                      <button className="btn btn-xs btn-danger" style={{ marginTop: 4 }} onClick={() => handleDeletePoint(pt.id)}>删除</button>
                    </div>
                  </Popup>
                </Marker>
              ))}

              {/* Landing sites */}
              {landings.map(ls => (
                <Marker key={`ls-${ls.id}`} position={[ls.latitude, ls.longitude]} icon={landingIcon}>
                  <Popup>
                    <div style={{ fontSize: 12 }}>
                      <strong>{ls.name}</strong><br />
                      高度: {ls.altitude}m
                    </div>
                  </Popup>
                </Marker>
              ))}

              {/* Turning warnings */}
              {turningWarnings.map((w: any, idx: number) => (
                Number.isFinite(Number(w.longitude)) && Number.isFinite(Number(w.latitude)) ? (
                  <Marker key={`warn-${idx}`} position={[Number(w.latitude), Number(w.longitude)]} icon={warningIcon}>
                    <Popup><div style={{ fontSize: 11 }}>{w.message || '转弯退化'}</div></Popup>
                  </Marker>
                ) : null
              ))}
            </MapContainer>
          </div>

          {/* Profile section */}
          {showProfiles && selectedRouteId && (
            <>
              <ResizeHandle direction="horizontal" onResize={delta => {
                setMapHeightPx(h => {
                  const maxH = (containerRef.current?.clientHeight ?? 600) - 126;
                  return Math.max(200, Math.min(maxH, h + delta));
                });
              }} />
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 120 }}>
              <div className="trace-strip" style={{ display: 'flex', gap: 12, padding: '4px 8px', fontSize: 11, color: '#64748b', background: '#f8fafc' }}>
                <span>里程：{profileTraceInfo.distance}</span>
                <span>地形高程：{profileTraceInfo.elevation}</span>
                <span>坡度：{profileTraceInfo.slope}</span>
                <span>坐标：{profileTraceInfo.coords}</span>
              </div>
              <div style={{ flex: 1, display: 'flex', gap: 4 }}>
                <div style={{ flex: 1 }}>
                  <CrossSectionChart
                    cloudPoints={cloudPointsForChart}
                    terrainPointsFallback={terrainPointsForChart}
                    profilePoints={profilePointsForChart}
                    layers={layersForChart}
                    routeBottom={profileBundle.routeBottom}
                    routeTop={profileBundle.routeTop}
                    selectedDistance={effectiveProfileDistance}
                    flightWidth={selectedRoute?.flight_width ?? 40}
                    protectionWidth={selectedRoute?.protection_width ?? 100}
                    title="横断面"
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <ProfileChart
                    profilePoints={profilePointsForChart}
                    terrainPoints={terrainPointsForChart}
                    layers={layersForChart}
                    routeBottom={profileBundle.routeBottom}
                    routeTop={profileBundle.routeTop}
                    interactive={true}
                    selectedDistance={effectiveProfileDistance}
                    altitudeChangeMin={formData.altitude_change_min || 10}
                    focusTrackEnabled={focusTrackEnabled}
                    title="纵断面"
                    onTrace={handleTrace}
                    onFocusPoint={handleFocusPoint}
                  />
                </div>
              </div>
              {focusTrackEnabled && (
                <div style={{ padding: '2px 8px', fontSize: 10, color: '#ef4444', background: '#fef2f2' }}>
                  焦点跟踪已开启：红点实时跟随，地图仅在接近边缘时平移
                </div>
              )}
            </div>
          </>
          )}
        </div>
      </div>

      <ResizeHandle onResize={delta => setRightWidth(w => Math.max(250, Math.min(600, w - delta)))} />

      {/* Right Panel - Route Detail */}
      <div className="module-panel" style={{ width: rightWidth, minWidth: 250, maxWidth: 600, flexShrink: 0 }}>
        <div className="module-panel-header">
          <span>航路详情</span>
          <button className="btn btn-xs" disabled={!selectedRouteId} onClick={() => selectedRouteId && loadRouteDetail(selectedRouteId)}>刷新</button>
        </div>
        {!selectedRouteId ? (
          <div className="empty-state"><div className="empty-state-text">请选择航路</div></div>
        ) : loading ? (
          <div className="empty-state"><div className="empty-state-text">加载中...</div></div>
        ) : (
          <>
            {/* Tabs */}
            <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid #e2e8f0' }}>
              {(['params', 'points', 'subRoutes', 'geo', 'landings'] as const).map(tab => (
                <button key={tab} className={`btn btn-xs ${detailTab === tab ? 'btn-primary' : ''}`}
                  style={{ borderRadius: 0, borderBottom: detailTab === tab ? '2px solid #2563eb' : 'none' }}
                  onClick={() => setDetailTab(tab)}>
                  {{ params: '参数', points: '航路点', subRoutes: '子航路', geo: '地形/地理', landings: '起降场' }[tab]}
                </button>
              ))}
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
              {/* Params Tab */}
              {detailTab === 'params' && (
                <>
                  <div className="form-group">
                    <label className="form-label">航路名称</label>
                    <input className="form-input sm" value={formData.name}
                      onChange={e => onParamChange({ name: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">飞行区宽度 (m)</label>
                    <input className="form-input sm" type="number" value={formData.flight_width}
                      onChange={e => onParamChange({ flight_width: parseFloat(e.target.value) || 0 })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">保护区宽度 (m)</label>
                    <input className="form-input sm" type="number" value={formData.protection_width}
                      onChange={e => onParamChange({ protection_width: parseFloat(e.target.value) || 0 })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">下限高度 (m)</label>
                    <input className="form-input sm" type="number" value={formData.bottom_height}
                      onChange={e => onParamChange({ bottom_height: parseFloat(e.target.value) || 0 })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">上限高度 (m)</label>
                    <input className="form-input sm" type="number" value={formData.top_height}
                      onChange={e => onParamChange({ top_height: parseFloat(e.target.value) || 0 })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">最小转弯半径 (m)</label>
                    <input className="form-input sm" type="number" value={formData.min_turn_radius}
                      onChange={e => onParamChange({ min_turn_radius: parseFloat(e.target.value) || 0 })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">高度变化最小值 (m)</label>
                    <input className="form-input sm" type="number" value={formData.altitude_change_min}
                      onChange={e => onParamChange({ altitude_change_min: parseFloat(e.target.value) || 10 })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">转弯模式</label>
                    <select className="form-input sm" value={formData.turn_mode}
                      onChange={e => onParamChange({ turn_mode: e.target.value as 'angle' | 'arc' })}>
                      <option value="angle">定点转弯型</option>
                      <option value="arc">协调转弯型</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">高度基准</label>
                    <select className="form-input sm" value={formData.altitude_reference_mode}
                      onChange={e => onParamChange({ altitude_reference_mode: e.target.value as 'asl' | 'agl' })}>
                      <option value="asl">海拔</option>
                      <option value="agl">真高</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">分层方案</label>
                    <input className="form-input sm" value={formData.layer_scheme}
                      onChange={e => onParamChange({ layer_scheme: e.target.value })} />
                  </div>
                  {turningWarnings.length > 0 && formData.turn_mode === 'arc' && (
                    <div style={{ padding: 8, background: '#fef3c7', borderRadius: 4, fontSize: 12, marginBottom: 8 }}>
                      协调转弯型中有 {turningWarnings.filter((w: any) => Number.isFinite(Number(w.longitude))).length} 个折点退化为折角
                    </div>
                  )}
                  <button className="btn btn-primary btn-sm" style={{ width: '100%' }}
                    onClick={handleGenerate} disabled={generating}>
                    {generating ? '生成中...' : '生成航路'}
                  </button>
                </>
              )}

              {/* Points Tab */}
              {detailTab === 'points' && (
                <>
                  <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
                    <button className="btn btn-xs" onClick={undoEdit} disabled={undoStack.length === 0}>撤销</button>
                    <button className="btn btn-xs" onClick={redoEdit} disabled={redoStack.length === 0}>重做</button>
                    <button className="btn btn-xs btn-danger" onClick={handleClearPoints} disabled={points.length === 0}>清空点位</button>
                  </div>
                  <div className="form-group">
                    <label className="form-label">名称</label>
                    <input className="form-input sm" value={pointForm.name} onChange={e => setPointForm({ ...pointForm, name: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">类型</label>
                    <select className="form-input sm" value={pointForm.point_type}
                      onChange={e => setPointForm({ ...pointForm, point_type: e.target.value as 'start' | 'waypoint' | 'end' })}>
                      <option value="start">起点</option>
                      <option value="waypoint">航路点</option>
                      <option value="end">终点</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">经度</label>
                    <input className="form-input sm" type="number" step="0.000001" value={pointForm.longitude}
                      onChange={e => setPointForm({ ...pointForm, longitude: parseFloat(e.target.value) || 0 })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">纬度</label>
                    <input className="form-input sm" type="number" step="0.000001" value={pointForm.latitude}
                      onChange={e => setPointForm({ ...pointForm, latitude: parseFloat(e.target.value) || 0 })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">高度</label>
                    <input className="form-input sm" type="number" value={pointForm.altitude}
                      onChange={e => setPointForm({ ...pointForm, altitude: parseFloat(e.target.value) || 0 })} />
                  </div>
                  <button className="btn btn-sm" style={{ width: '100%', marginBottom: 8 }} onClick={handleAddPoint}>添加航路点</button>
                  <table className="data-table" style={{ fontSize: 11 }}>
                    <thead><tr><th>序号</th><th>名称</th><th>坐标</th><th>操作</th></tr></thead>
                    <tbody>
                      {[...points].sort((a, b) => a.order_index - b.order_index).map((pt, i) => (
                        <tr key={pt.id}>
                          <td>{i + 1}</td>
                          <td>{pt.name}</td>
                          <td className="mono" style={{ fontSize: 10 }}>{pt.longitude.toFixed(5)}, {pt.latitude.toFixed(5)}</td>
                          <td>
                            <button className="btn btn-xs" onClick={() => handleMovePoint(pt.id, -1)}>上移</button>
                            <button className="btn btn-xs" onClick={() => handleMovePoint(pt.id, 1)}>下移</button>
                            <button className="btn btn-xs" onClick={() => handleInsertAfter(pt.id)}>后插</button>
                            <button className="btn btn-xs btn-danger" onClick={() => handleDeletePoint(pt.id)}>删除</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}

              {/* Sub Routes Tab */}
              {detailTab === 'subRoutes' && (
                <div>
                  {Array.isArray(subRoutes) && subRoutes.length > 0 ? subRoutes.map((sr: any, i: number) => (
                    <div key={i} style={{ padding: '8px 10px', marginBottom: 4, borderRadius: 8, border: '1px solid #e2e8f0' }}>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{sr.name || `子航路 ${sr.sequence}`}</div>
                      <div style={{ fontSize: 11, color: '#64748b' }}>序号 {sr.sequence} · {sr.bottom_height}m - {sr.top_height}m</div>
                      <button className="btn btn-xs" style={{ marginTop: 4 }}
                        onClick={() => handleExtractSubRoute(Number(sr.sequence))}>提取为新航路</button>
                    </div>
                  )) : (
                    <div className="empty-state"><div className="empty-state-text">生成航路后显示可提取的子航路。</div></div>
                  )}
                </div>
              )}

              {/* Geo Tab */}
              {detailTab === 'geo' && (
                <div>
                  <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
                    <button className="btn btn-xs btn-primary" disabled={geoLoading} onClick={handleExtractGeo}>
                      {geoLoading ? '提取中...' : '重新提取沿线数据'}
                    </button>
                    <button className="btn btn-xs" disabled={geoLoading} onClick={handleLoadStoredGeo}>重新读取已提取数据</button>
                  </div>
                  {geoLoading && <div style={{ padding: 8, background: '#fef3c7', borderRadius: 4, fontSize: 12, marginBottom: 8 }}>正在提取地形/地理数据...</div>}
                  <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                    <div className="metric"><div className="metric-label">采样点</div><div className="metric-value">{geoData?.terrain?.summary?.sample_count ?? 0}</div></div>
                    <div className="metric"><div className="metric-label">有效高程</div><div className="metric-value">{geoData?.terrain?.summary?.elevation_record_count ?? 0}</div></div>
                    <div className="metric"><div className="metric-label">来源</div><div className="metric-value" style={{ fontSize: 11 }}>{String(geoData?.terrain?.source || '暂无')}</div></div>
                  </div>
                  {Array.isArray(geoData?.modules) && geoData.modules.length > 0 ? geoData.modules.map((m: any, i: number) => (
                    <div key={i} style={{ padding: '6px 8px', marginBottom: 2, borderRadius: 4, border: '1px solid #e2e8f0', fontSize: 12 }}>
                      <div style={{ fontWeight: 600 }}>{String(m.module || '未命名')}</div>
                      <div style={{ color: '#64748b' }}>{m.success === false ? '失败' : '完成'} · {m.message || '-'}</div>
                    </div>
                  )) : <div className="empty-state"><div className="empty-state-text">暂无地形/地理模块结果</div></div>}
                </div>
              )}

              {/* Landings Tab */}
              {detailTab === 'landings' && (
                <>
                  <div className="form-group">
                    <label className="form-label">名称</label>
                    <input className="form-input sm" value={landingForm.name} onChange={e => setLandingForm({ ...landingForm, name: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">高度</label>
                    <input className="form-input sm" type="number" value={landingForm.altitude}
                      onChange={e => setLandingForm({ ...landingForm, altitude: parseFloat(e.target.value) || 0 })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">经度</label>
                    <input className="form-input sm" type="number" step="0.000001" value={landingForm.longitude}
                      onChange={e => setLandingForm({ ...landingForm, longitude: parseFloat(e.target.value) || 0 })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">纬度</label>
                    <input className="form-input sm" type="number" step="0.000001" value={landingForm.latitude}
                      onChange={e => setLandingForm({ ...landingForm, latitude: parseFloat(e.target.value) || 0 })} />
                  </div>
                  <button className="btn btn-sm" style={{ width: '100%', marginBottom: 8 }} onClick={handleAddLanding}>添加起降场</button>
                  <table className="data-table" style={{ fontSize: 11 }}>
                    <thead><tr><th>名称</th><th>坐标</th><th>高度</th><th>操作</th></tr></thead>
                    <tbody>
                      {landings.map(ls => (
                        <tr key={ls.id}>
                          <td>{ls.name}</td>
                          <td className="mono" style={{ fontSize: 10 }}>{ls.longitude.toFixed(5)}, {ls.latitude.toFixed(5)}</td>
                          <td>{ls.altitude}</td>
                          <td><button className="btn btn-xs btn-danger" onClick={() => handleDeleteLanding(ls.id)}>删除</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default RouteManagementPage;
