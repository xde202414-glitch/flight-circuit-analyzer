import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { MapContainer, Polyline, Polygon, Marker, Popup } from 'react-leaflet';
import BaseMapLayer from '../../components/MapView/BaseMapLayer';
import L from 'leaflet';
import { apiClient } from '../../api/client';
import type { RouteInfo, AnalysisCatalogItem, AnalysisFactorResult } from '../../api/types';
import { CrossSectionChart, ProfileChart } from '../../components/RouteProfile';
import { normalizeProfileBundle, getNearestProfilePoint, interpolateTerrainElevation, estimateSlope } from '../../utils/profile-data';

const CATEGORY_NAMES: Record<string, string> = {
  general_building: '建筑/构筑物类',
  infrastructure: '公共基础设施类',
  electromagnetic: '电磁环境保护类',
  cultural: '文物保护类',
};

const COMPLIANCE_LABELS: Record<string, string> = {
  pass: '通过', fail: '不通过', unknown: '未知',
};

const RouteAnalysisPage: React.FC = () => {
  const [routes, setRoutes] = useState<RouteInfo[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<number | null>(null);
  const [catalog, setCatalog] = useState<AnalysisCatalogItem[]>([]);
  const [analysisView, setAnalysisView] = useState<any>(null);
  const [results, setResults] = useState<Map<string, AnalysisFactorResult>>(new Map());
  const [running, setRunning] = useState(false);
  const [aircraftType, setAircraftType] = useState<'micro' | 'light'>('micro');
  const [selectedFactor, setSelectedFactor] = useState<AnalysisCatalogItem | null>(null);
  const [showProfiles, setShowProfiles] = useState(false);
  const [focusTrackEnabled, setFocusTrackEnabled] = useState(false);
  const [profileDistance, setProfileDistance] = useState<number | null>(null);
  const [mapDisplayMode, setMapDisplayMode] = useState<'current' | 'all'>('current');

  const loadRoutes = useCallback(async () => {
    try { const res = await apiClient.getRoutes(); setRoutes(res.items || []); } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadRoutes(); }, [loadRoutes]);

  const loadAnalysisView = useCallback(async (routeId: number) => {
    try {
      const view = await apiClient.getRouteAnalysis(routeId);
      setAnalysisView(view);
      setCatalog(view.factors || []);
      const resultMap = new Map<string, AnalysisFactorResult>();
      (view.factors || []).forEach((f: any) => {
        if (f.latest_result) resultMap.set(f.id, f.latest_result);
      });
      setResults(resultMap);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (selectedRouteId) loadAnalysisView(selectedRouteId);
  }, [selectedRouteId, loadAnalysisView]);

  const handleRunAll = async () => {
    if (!selectedRouteId) return;
    setRunning(true);
    try {
      await apiClient.runAnalysis(selectedRouteId, { aircraft_type: aircraftType });
      await loadAnalysisView(selectedRouteId);
    } catch (e: any) { alert(e?.message || '分析失败'); }
    setRunning(false);
  };

  const handleRunSingle = async (factorId: string) => {
    if (!selectedRouteId) return;
    try {
      await apiClient.runSingleFactor(selectedRouteId, factorId, { aircraft_type: aircraftType });
      await loadAnalysisView(selectedRouteId);
    } catch (e: any) { alert(e?.message || '分析失败'); }
  };

  // Profile data
  const visual = analysisView?.visual;
  const profileBundle = useMemo(() => {
    const profile = visual?.profile ?? null;
    const terrain = visual?.geo?.terrain ?? null;
    return normalizeProfileBundle(profile, terrain);
  }, [visual]);

  const profilePointsForChart = useMemo(() =>
    profileBundle.profilePoints.map(p => ({ distance_m: p.distance, altitude_m: p.altitude, longitude: p.longitude, latitude: p.latitude })),
    [profileBundle]);
  const terrainPointsForChart = useMemo(() =>
    profileBundle.terrainPoints.map(p => ({ distance_m: p.distance, elevation_m: p.elevation, longitude: p.longitude, latitude: p.latitude })),
    [profileBundle]);
  const layersForChart = useMemo(() =>
    profileBundle.layers.map(l => ({ sequence: l.sequence, name: l.name, bottom_height: l.bottomHeight, top_height: l.topHeight })),
    [profileBundle]);

  const traceDistanceSource = useMemo(() =>
    profileBundle.profilePoints.length ? profileBundle.profilePoints.map(p => p.distance) : profileBundle.terrainPoints.map(p => p.distance),
    [profileBundle]);

  const effectiveTraceDistance = useMemo(() => {
    if (Number.isFinite(Number(profileDistance))) return Number(profileDistance);
    if (!traceDistanceSource.length) return null;
    return traceDistanceSource[Math.floor(traceDistanceSource.length / 2)] ?? traceDistanceSource[0];
  }, [profileDistance, traceDistanceSource]);

  const tracePoint = useMemo(() =>
    getNearestProfilePoint(profileBundle.profilePoints, effectiveTraceDistance),
    [profileBundle, effectiveTraceDistance]);

  const traceInfo = useMemo(() => {
    const d = effectiveTraceDistance;
    if (d === null) return { distance: '-', elevation: '-', slope: '-', coords: '-' };
    const el = interpolateTerrainElevation(profileBundle.terrainPoints, d);
    const slope = estimateSlope(profileBundle.profilePoints, d);
    return {
      distance: `${d.toFixed(1)} m`,
      elevation: Number.isFinite(Number(el)) ? `${Number(el).toFixed(1)} m` : '-',
      slope: Number.isFinite(Number(slope)) ? `${Number(slope).toFixed(1)}%` : '-',
      coords: Number.isFinite(Number(tracePoint?.longitude)) && Number.isFinite(Number(tracePoint?.latitude))
        ? `${Number(tracePoint?.longitude).toFixed(6)}, ${Number(tracePoint?.latitude).toFixed(6)}` : '-',
    };
  }, [effectiveTraceDistance, profileBundle, tracePoint]);

  const handleTrace = useCallback((payload: { distance: number }) => {
    setProfileDistance(Number(payload.distance));
  }, []);

  const handleFocusPoint = useCallback((_payload: { longitude: number | null; latitude: number | null; distance: number }) => {
    // Focus tracking for map centering
  }, []);

  // Group factors
  const groupedFactors: Record<string, AnalysisCatalogItem[]> = {};
  catalog.forEach(f => {
    const catId = f.category_id || 'other';
    if (!groupedFactors[catId]) groupedFactors[catId] = [];
    groupedFactors[catId].push(f);
  });

  // Map data
  const centerline = visual?.centerline?.coordinates?.map((c: number[]) => [c[1], c[0]] as [number, number]) || [];
  const flightZone = visual?.flight_zone?.coordinates?.[0]?.map((c: number[]) => [c[1], c[0]] as [number, number]) || [];
  const protectionZone = visual?.protection_zone?.coordinates?.[0]?.map((c: number[]) => [c[1], c[0]] as [number, number]) || [];

  const failCount = Array.from(results.values()).filter(r => r.compliance === 'fail').length;
  const hitCount = Array.from(results.values()).filter(r => r.compliance !== 'unknown').length;

  // Map features from analysis
  const mapFeatures = useMemo(() => {
    if (mapDisplayMode === 'current' && selectedFactor) {
      const result = results.get(selectedFactor.id);
      return result?.evidence_json?.features || [];
    }
    // All factors
    const allFeatures: any[] = [];
    results.forEach(r => {
      if (r.evidence_json?.features) allFeatures.push(...r.evidence_json.features);
    });
    return allFeatures;
  }, [selectedFactor, results, mapDisplayMode]);

  const mapCenter: [number, number] = visual?.route
    ? [visual.route.latitude || 31.2304, visual.route.longitude || 121.4737]
    : [31.2304, 121.4737];

  const route = routes.find(r => r.id === selectedRouteId);

  return (
    <div className="module-layout" style={{ display: 'flex', gap: 8, height: 'calc(100vh - 100px)' }}>
      {/* Left Panel */}
      <div className="module-panel" style={{ width: 300, minWidth: 300 }}>
        <div className="module-panel-header">
          <span>适飞空域影响因素</span>
          <select className="form-input sm" style={{ width: 120 }} value={aircraftType}
            onChange={e => setAircraftType(e.target.value as 'micro' | 'light')}>
            <option value="micro">微型航空器</option>
            <option value="light">轻型航空器</option>
          </select>
        </div>

        <div className="form-group">
          <label className="form-label">选择航路</label>
          <select className="form-input sm" value={selectedRouteId || ''}
            onChange={e => setSelectedRouteId(e.target.value ? parseInt(e.target.value) : null)}>
            <option value="">-- 选择航路 --</option>
            {routes.map(r => <option key={r.id} value={r.id}>#{r.id} {r.name}</option>)}
          </select>
        </div>

        <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
          <button className="btn btn-primary btn-sm" style={{ flex: 1 }} disabled={!selectedRouteId || running} onClick={handleRunAll}>
            {running ? '分析中...' : '一键全量分析'}
          </button>
          <button className="btn btn-sm" disabled={!selectedRouteId} onClick={() => selectedRouteId && loadAnalysisView(selectedRouteId)}>刷新</button>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <div className="metric"><div className="metric-label">因子</div><div className="metric-value">{catalog.length}</div></div>
          <div className="metric"><div className="metric-label">不通过</div><div className="metric-value" style={{ color: '#dc2626' }}>{failCount}</div></div>
          <div className="metric"><div className="metric-label">命中</div><div className="metric-value" style={{ color: '#2563eb' }}>{hitCount}</div></div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {Object.entries(groupedFactors).map(([catId, factors]) => (
            <div key={catId} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', marginBottom: 4 }}>
                {CATEGORY_NAMES[catId] || catId} ({factors.length})
              </div>
              {factors.map((factor, i) => {
                const result = results.get(factor.id);
                const compliance = result?.compliance || 'unknown';
                return (
                  <div key={factor.id}
                    onClick={() => setSelectedFactor(factor)}
                    style={{
                      padding: '6px 10px', marginBottom: 3, borderRadius: 6, cursor: 'pointer', fontSize: 12,
                      background: selectedFactor?.id === factor.id ? '#fef3c7' : '#fafafa',
                      border: selectedFactor?.id === factor.id ? '1px solid #fcd34d' : '1px solid #e5e7eb',
                    }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 500 }}>{i + 1}. {factor.name}</span>
                      <span className={`status-pill ${compliance === 'pass' ? 'pass' : compliance === 'fail' ? 'fail' : 'unknown'}`}
                        style={{ fontSize: 10 }}>
                        {COMPLIANCE_LABELS[compliance] || compliance}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                      {factor.control_requirement?.substring(0, 40)}
                    </div>
                    <button className="btn btn-xs btn-secondary" style={{ marginTop: 3 }}
                      onClick={e => { e.stopPropagation(); handleRunSingle(factor.id); }}>单独运行</button>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Center - Map & Profile */}
      <div className="module-map-panel" style={{ flex: 1, minWidth: 0 }}>
        <div className="module-panel-header" style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>地图与剖面</span>
          <div style={{ display: 'flex', gap: 4 }}>
            <select className="form-input sm" style={{ width: 110, fontSize: 11 }} value={mapDisplayMode}
              onChange={e => setMapDisplayMode(e.target.value as any)}>
              <option value="current">当前因子</option>
              <option value="all">全部因子</option>
            </select>
            <button className="btn btn-xs" onClick={() => setShowProfiles(!showProfiles)}>
              {showProfiles ? '隐藏剖面' : '显示剖面'}
            </button>
            <button className={`btn btn-xs ${focusTrackEnabled ? 'btn-primary' : ''}`}
              onClick={() => setFocusTrackEnabled(!focusTrackEnabled)}>
              {focusTrackEnabled ? '关闭焦点跟踪' : '焦点跟踪'}
            </button>
          </div>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: showProfiles ? '0 0 55%' : 1, position: 'relative', minHeight: 250 }}>
            <MapContainer center={mapCenter} zoom={12} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}>
              <BaseMapLayer />
              {protectionZone.length >= 3 && <Polygon positions={protectionZone} color="#f97316" fillColor="#f97316" fillOpacity={0.1} weight={2} dashArray="8,4" />}
              {flightZone.length >= 3 && <Polygon positions={flightZone} color="#3b82f6" fillColor="#3b82f6" fillOpacity={0.15} weight={2} />}
              {centerline.length >= 2 && <Polyline positions={centerline} color="#1d4ed8" weight={4} />}
              {mapFeatures.filter((f: any) => f.geometry?.type === 'Point').map((f: any, i: number) => (
                <Marker key={`af-${i}`} position={[f.geometry.coordinates[1], f.geometry.coordinates[0]]}
                  icon={L.divIcon({
                    className: '', html: '<div style="background:#fb8c00;color:white;width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;border:2px solid white;box-shadow:0 2px 4px rgba(0,0,0,0.3)">因</div>',
                    iconSize: [20, 20], iconAnchor: [10, 10],
                  })}>
                  <Popup><div style={{ fontSize: 11 }}>{f.properties?.name || '证据点'}</div></Popup>
                </Marker>
              ))}
            </MapContainer>
          </div>

          {showProfiles && profileBundle.hasTerrain && (
            <div style={{ flex: '0 0 45%', display: 'flex', flexDirection: 'column', borderTop: '1px solid #e2e8f0' }}>
              <div style={{ display: 'flex', gap: 12, padding: '4px 8px', fontSize: 11, color: '#64748b', background: '#f8fafc' }}>
                <span>里程：{traceInfo.distance}</span>
                <span>地形高程：{traceInfo.elevation}</span>
                <span>坡度：{traceInfo.slope}</span>
                <span>坐标：{traceInfo.coords}</span>
              </div>
              <div style={{ flex: 1, display: 'flex', gap: 4 }}>
                <div style={{ flex: 1 }}>
                  <CrossSectionChart
                    cloudPoints={[]}
                    terrainPointsFallback={terrainPointsForChart}
                    profilePoints={profilePointsForChart}
                    layers={layersForChart}
                    routeBottom={profileBundle.routeBottom}
                    routeTop={profileBundle.routeTop}
                    selectedDistance={effectiveTraceDistance}
                    flightWidth={route?.flight_width ?? 40}
                    protectionWidth={route?.protection_width ?? 100}
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
                    selectedDistance={effectiveTraceDistance}
                    focusTrackEnabled={focusTrackEnabled}
                    title="纵断面"
                    onTrace={handleTrace}
                    onFocusPoint={handleFocusPoint}
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right Panel */}
      <div className="module-panel" style={{ width: 280, minWidth: 280 }}>
        <div className="module-panel-header">因子详情</div>
        {!selectedFactor ? (
          <div className="empty-state"><div className="empty-state-text">选择分析因子查看详情</div></div>
        ) : (
          <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{selectedFactor.name}</h3>
            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>{selectedFactor.control_requirement}</div>

            <div className="card" style={{ marginBottom: 12 }}>
              <div className="card-header">参数配置</div>
              {selectedFactor.parameter_schema?.map((param: any) => (
                <div className="form-group" key={param.key}>
                  <label className="form-label">{param.label}</label>
                  {param.type === 'enum' ? (
                    <select className="form-input sm" defaultValue={param.default}>
                      {param.options?.map((opt: string) => <option key={opt} value={opt}>{opt}</option>)}
                    </select>
                  ) : (
                    <input className="form-input sm" type="number" defaultValue={param.default} />
                  )}
                </div>
              ))}
            </div>

            {results.get(selectedFactor.id) && (
              <div className="card">
                <div className="card-header">分析结果</div>
                <div style={{ fontSize: 12 }}>
                  <p>合规状态: <span className={`status-pill ${results.get(selectedFactor.id)!.compliance === 'pass' ? 'pass' : results.get(selectedFactor.id)!.compliance === 'fail' ? 'fail' : 'unknown'}`}>
                    {COMPLIANCE_LABELS[results.get(selectedFactor.id)!.compliance] || '未知'}
                  </span></p>
                  <p>数据状态: {results.get(selectedFactor.id)!.data_status || '--'}</p>
                  {results.get(selectedFactor.id)!.next_action && (
                    <p style={{ color: '#2563eb' }}>建议: {results.get(selectedFactor.id)!.next_action}</p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default RouteAnalysisPage;
