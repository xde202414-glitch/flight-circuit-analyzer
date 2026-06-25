import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { MapContainer, Polyline, Polygon, Marker, Popup } from 'react-leaflet';
import BaseMapLayer from '../../components/MapView/BaseMapLayer';
import L from 'leaflet';
import { apiClient } from '../../api/client';
import type { RouteInfo, LandingSite, TakeoffFlightState, FlightPlanRequest } from '../../api/types';

const AIRCRAFT_PRESETS: Record<string, any> = {
  micro: {
    cruise_speed_kmh: 54, max_climb_rate_ms: 3, max_descent_rate_ms: 2.5,
    min_turn_radius_m: 20, max_flight_time_min: 35, reserve_time_min: 5,
    horizontal_deviation_m: 15, vertical_deviation_m: 10, waiting_height_agl_m: 30,
    max_attach_distance_m: 2000, min_clearance_m: 15, wingspan_m: 18,
    max_ground_speed_ms: 55, response_time_s: 3, max_roll_angle_deg: 25,
    climb_gradient: 0.065, descent_gradient: 0.041,
    fte_horizontal_m: 10, nse_horizontal_m: 10, fte_vertical_m: 5, nse_vertical_m: 5,
    body_height_m: 6, altitude_measurement_error_m: 5,
    pitch_deviation_deg: 5, max_pitch_adjust_deg: 15, additional_moc_m: 0,
    abnormal_area_enabled: true, abnormal_height_enabled: true,
  },
  light: {
    cruise_speed_kmh: 80, max_climb_rate_ms: 5, max_descent_rate_ms: 4,
    min_turn_radius_m: 30, max_flight_time_min: 60, reserve_time_min: 10,
    horizontal_deviation_m: 25, vertical_deviation_m: 15, waiting_height_agl_m: 50,
    max_attach_distance_m: 5000, min_clearance_m: 20, wingspan_m: 25,
    max_ground_speed_ms: 80, response_time_s: 5, max_roll_angle_deg: 30,
    climb_gradient: 0.08, descent_gradient: 0.05,
    fte_horizontal_m: 15, nse_horizontal_m: 15, fte_vertical_m: 10, nse_vertical_m: 10,
    body_height_m: 8, altitude_measurement_error_m: 8,
    pitch_deviation_deg: 8, max_pitch_adjust_deg: 20, additional_moc_m: 0,
    abnormal_area_enabled: true, abnormal_height_enabled: true,
  },
  fp98: {
    cruise_speed_kmh: 65, max_climb_rate_ms: 4, max_descent_rate_ms: 3,
    min_turn_radius_m: 25, max_flight_time_min: 45, reserve_time_min: 8,
    horizontal_deviation_m: 20, vertical_deviation_m: 12, waiting_height_agl_m: 40,
    max_attach_distance_m: 3500, min_clearance_m: 18, wingspan_m: 20,
    max_ground_speed_ms: 70, response_time_s: 4, max_roll_angle_deg: 28,
    climb_gradient: 0.07, descent_gradient: 0.045,
    fte_horizontal_m: 12, nse_horizontal_m: 12, fte_vertical_m: 8, nse_vertical_m: 8,
    body_height_m: 7, altitude_measurement_error_m: 6,
    pitch_deviation_deg: 6, max_pitch_adjust_deg: 18, additional_moc_m: 0,
    abnormal_area_enabled: true, abnormal_height_enabled: true,
  },
};

const NUMERIC_PARAMS = [
  { key: 'cruise_speed_kmh', label: '巡航速度(km/h)', step: 1 },
  { key: 'max_climb_rate_ms', label: '最大爬升率(m/s)', step: 0.1 },
  { key: 'max_descent_rate_ms', label: '最大下降率(m/s)', step: 0.1 },
  { key: 'min_turn_radius_m', label: '最小转弯半径(m)', step: 1 },
  { key: 'max_flight_time_min', label: '最大飞行时间(min)', step: 1 },
  { key: 'reserve_time_min', label: '预留时间(min)', step: 1 },
  { key: 'wingspan_m', label: '翼展(m)', step: 0.1 },
  { key: 'min_clearance_m', label: '最小安全间距(m)', step: 1 },
  { key: 'max_attach_distance_m', label: '最大接入距离(m)', step: 100 },
  { key: 'climb_gradient', label: '爬升梯度', step: 0.001 },
  { key: 'descent_gradient', label: '下降梯度', step: 0.001 },
];

const TakeoffFlightPage: React.FC = () => {
  const [routes, setRoutes] = useState<RouteInfo[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState<number | null>(null);
  const [state, setState] = useState<TakeoffFlightState | null>(null);
  const [landings, setLandings] = useState<LandingSite[]>([]);
  const [selectedLandingId, setSelectedLandingId] = useState<number | null>(null);
  const [platform, setPlatform] = useState<'vtol' | 'fixed_wing'>('vtol');
  const [preset, setPreset] = useState<string>('micro');
  const [params, setParams] = useState<Record<string, any>>(AIRCRAFT_PRESETS.micro);
  const [planResult, setPlanResult] = useState<any>(null);
  const [plans, setPlans] = useState<any[]>([]);
  const [targetLayer, setTargetLayer] = useState<string>('');
  const [subRouteLayers, setSubRouteLayers] = useState<any[]>([]);
  const [calculating, setCalculating] = useState(false);

  const loadRoutes = useCallback(async () => {
    try { const res = await apiClient.getRoutes(); setRoutes(res.items || []); } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadRoutes(); }, [loadRoutes]);

  const loadState = useCallback(async (routeId: number) => {
    try {
      const [s, plansList] = await Promise.all([
        apiClient.getTakeoffFlightState(routeId),
        apiClient.listTakeoffFlightPlans(routeId).catch(() => []),
      ]);
      setState(s);
      setLandings(s.landings || []);
      setPlans(plansList);
      setSubRouteLayers(s.visual?.sub_routes || []);
    } catch { setState(null); setLandings([]); setPlans([]); setSubRouteLayers([]); }
  }, []);

  useEffect(() => {
    if (selectedRouteId) { loadState(selectedRouteId); }
    else { setState(null); setLandings([]); setPlans([]); setPlanResult(null); setSubRouteLayers([]); }
  }, [selectedRouteId, loadState]);

  const handlePresetChange = (presetName: string) => {
    setPreset(presetName);
    if (presetName !== 'custom') {
      setParams(AIRCRAFT_PRESETS[presetName] || AIRCRAFT_PRESETS.micro);
    }
  };

  const handleParamChange = (key: string, value: number) => {
    setParams(prev => ({ ...prev, [key]: value }));
    setPreset('custom');
  };

  const canCalculate = selectedRouteId && selectedLandingId;

  const handlePreview = async () => {
    if (!canCalculate) return;
    setCalculating(true);
    try {
      const payload: FlightPlanRequest = {
        landing_id: selectedLandingId!,
        aircraft_platform: platform,
        aircraft_preset: preset as any,
        aircraft_params: params,
        target_layer_sequence: targetLayer ? parseInt(targetLayer) : undefined,
      };
      const result = await apiClient.previewTakeoffFlight(selectedRouteId!, payload);
      setPlanResult(result);
    } catch (e: any) { alert(e?.message || '计算失败'); }
    setCalculating(false);
  };

  const handleSavePlan = async () => {
    if (!canCalculate) return;
    try {
      const payload: FlightPlanRequest = {
        landing_id: selectedLandingId!,
        aircraft_platform: platform,
        aircraft_preset: preset as any,
        aircraft_params: params,
        target_layer_sequence: targetLayer ? parseInt(targetLayer) : undefined,
      };
      await apiClient.createFlightPlan(selectedRouteId!, payload);
      await loadState(selectedRouteId!);
    } catch (e: any) { alert(e?.message || '保存失败'); }
  };

  // Map data
  const visual = state?.visual;
  const centerline = visual?.centerline?.coordinates?.map((c: number[]) => [c[1], c[0]] as [number, number]) || [];
  const flightZone = visual?.flight_zone?.coordinates?.[0]?.map((c: number[]) => [c[1], c[0]] as [number, number]) || [];
  const protectionZone = visual?.protection_zone?.coordinates?.[0]?.map((c: number[]) => [c[1], c[0]] as [number, number]) || [];

  const planPaths = useMemo(() => {
    if (!planResult?.path_geojson?.features) return [];
    return planResult.path_geojson.features
      .filter((f: any) => f.geometry?.type === 'LineString')
      .map((f: any) => f.geometry.coordinates.map((c: number[]) => [c[1], c[0]] as [number, number]));
  }, [planResult]);

  const mapCenter: [number, number] = selectedLandingId
    ? (() => {
        const l = landings.find(ls => ls.id === selectedLandingId);
        return l ? [l.latitude, l.longitude] as [number, number] : [31.2304, 121.4737] as [number, number];
      })()
    : [31.2304, 121.4737];

  const planStatus = planResult?.result?.status || 'unknown';
  const planStatusText = planStatus === 'pass' ? '可行' : planStatus === 'warning' ? '警告' : planStatus === 'fail' ? '不可行' : '等待分析';

  return (
    <div className="module-layout" style={{ display: 'flex', gap: 8, height: 'calc(100vh - 100px)' }}>
      {/* Left Panel */}
      <div className="module-panel" style={{ width: 300, minWidth: 300 }}>
        <div className="module-panel-header">
          <span>起降场飞行</span>
          <button className="btn btn-xs" disabled={!selectedRouteId} onClick={() => selectedRouteId && loadState(selectedRouteId)}>刷新</button>
        </div>

        <div className="form-group">
          <label className="form-label">选择航路</label>
          <select className="form-input sm" value={selectedRouteId || ''}
            onChange={e => setSelectedRouteId(e.target.value ? parseInt(e.target.value) : null)}>
            <option value="">-- 选择航路 --</option>
            {routes.map(r => <option key={r.id} value={r.id}>#{r.id} {r.name}</option>)}
          </select>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <div className="metric"><div className="metric-label">起降场</div><div className="metric-value">{landings.length}</div></div>
          <div className="metric"><div className="metric-label">方案</div><div className="metric-value">{plans.length}</div></div>
          <div className="metric"><div className="metric-label">层高</div><div className="metric-value">{subRouteLayers.length || 1}</div></div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          <h2 className="section-title" style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: '#64748b' }}>起降场与层高</h2>
          {landings.length > 0 ? (
            <>
              <div className="form-group">
                <label className="form-label">起降场</label>
                <select className="form-input sm" value={selectedLandingId || ''}
                  onChange={e => setSelectedLandingId(e.target.value ? parseInt(e.target.value) : null)}>
                  <option value="">-- 选择 --</option>
                  {landings.map(l => <option key={l.id} value={l.id}>{l.name} ({l.altitude}m)</option>)}
                </select>
              </div>
              {subRouteLayers.length > 0 && (
                <div className="form-group">
                  <label className="form-label">进入/退出层高</label>
                  <select className="form-input sm" value={targetLayer}
                    onChange={e => setTargetLayer(e.target.value)}>
                    <option value="">当前航路高度窗</option>
                    {subRouteLayers.map((layer: any, i: number) => (
                      <option key={i} value={layer.sequence}>
                        {layer.name || `层${layer.sequence}`} ({layer.bottom_height}-{layer.top_height}m)
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </>
          ) : (
            <div className="empty-state" style={{ padding: 12 }}>
              <div className="empty-state-text" style={{ fontSize: 12 }}>所选航路暂无起降场</div>
            </div>
          )}

          <h2 className="section-title" style={{ fontSize: 13, fontWeight: 600, margin: '8px 0 6px', color: '#64748b' }}>无人机性能</h2>
          <div className="form-group">
            <label className="form-label">航空器类型</label>
            <select className="form-input sm" value={platform} onChange={e => setPlatform(e.target.value as any)}>
              <option value="vtol">垂直起降航空器</option>
              <option value="fixed_wing">固定翼航空器</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">参数预设</label>
            <select className="form-input sm" value={preset} onChange={e => handlePresetChange(e.target.value)}>
              <option value="fp98">FP-98 示例参数</option>
              <option value="micro">微型航空器</option>
              <option value="light">轻型航空器</option>
              <option value="custom">自定义</option>
            </select>
          </div>

          {NUMERIC_PARAMS.slice(0, 8).map(f => (
            <div className="form-group" key={f.key}>
              <label className="form-label">{f.label}</label>
              <input className="form-input sm" type="number" step={f.step}
                value={params[f.key] || 0}
                onChange={e => handleParamChange(f.key, parseFloat(e.target.value) || 0)} />
            </div>
          ))}

          {preset === 'custom' && (
            <details style={{ marginTop: 4 }}>
              <summary style={{ fontSize: 11, color: '#64748b', cursor: 'pointer' }}>高级参数</summary>
              {NUMERIC_PARAMS.slice(8).map(f => (
                <div className="form-group" key={f.key}>
                  <label className="form-label">{f.label}</label>
                  <input className="form-input sm" type="number" step={f.step}
                    value={params[f.key] || 0}
                    onChange={e => handleParamChange(f.key, parseFloat(e.target.value) || 0)} />
                </div>
              ))}
            </details>
          )}

          <div style={{ display: 'flex', gap: 8, marginTop: 12, marginBottom: 12 }}>
            <button className="btn btn-primary btn-sm" style={{ flex: 1 }}
              onClick={handlePreview} disabled={!canCalculate || calculating}>
              {calculating ? '计算中...' : '计算预览'}
            </button>
            <button className="btn btn-sm" onClick={handleSavePlan} disabled={!canCalculate || calculating}>保存方案</button>
          </div>
        </div>
      </div>

      {/* Center - Map */}
      <div className="module-map-panel" style={{ flex: 1, minWidth: 0 }}>
        <div className="module-panel-header" style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>进入与退出主航路</span>
          <span className={`status-pill ${planStatus === 'pass' ? 'pass' : planStatus === 'fail' ? 'fail' : 'unknown'}`}>
            {planStatusText}
          </span>
        </div>
        <div style={{ flex: 1, position: 'relative' }}>
          <MapContainer center={mapCenter} zoom={14} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}>
            <BaseMapLayer />
            {protectionZone.length >= 3 && <Polygon positions={protectionZone} color="#f97316" fillColor="#f97316" fillOpacity={0.1} weight={2} dashArray="8,4" />}
            {flightZone.length >= 3 && <Polygon positions={flightZone} color="#3b82f6" fillColor="#3b82f6" fillOpacity={0.15} weight={2} />}
            {centerline.length >= 2 && <Polyline positions={centerline} color="#1d4ed8" weight={4} />}

            {/* Plan paths */}
            {planPaths.map((coords: [number, number][], i: number) => (
              <Polyline key={`plan-${i}`} positions={coords} color={i === 0 ? '#16a34a' : '#dc2626'} weight={3} />
            ))}

            {/* Landing sites */}
            {landings.map(ls => (
              <Marker key={ls.id} position={[ls.latitude, ls.longitude]}
                icon={L.divIcon({
                  className: '',
                  html: `<div style="background:${selectedLandingId === ls.id ? '#dc2626' : '#8b5cf6'};color:white;width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;border:2px solid white;box-shadow:0 2px 6px rgba(0,0,0,0.3)">降</div>`,
                  iconSize: [24, 24], iconAnchor: [12, 12],
                })}>
                <Popup>
                  <div style={{ fontSize: 12 }}>
                    <strong>{ls.name}</strong><br />
                    高度: {ls.altitude}m<br />
                    <button className="btn btn-xs btn-primary" onClick={() => setSelectedLandingId(ls.id)}>选择</button>
                  </div>
                </Popup>
              </Marker>
            ))}
          </MapContainer>
        </div>
      </div>

      {/* Right Panel - Results */}
      <div className="module-panel" style={{ width: 300, minWidth: 300 }}>
        <div className="module-panel-header">计算结果</div>
        {!planResult ? (
          <div className="empty-state">
            <div className="empty-state-text">配置参数后点击"计算预览"查看飞行方案</div>
          </div>
        ) : (
          <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
            <div className="card" style={{ marginBottom: 12 }}>
              <div className="card-header">飞行概要</div>
              <div style={{ fontSize: 12, lineHeight: 1.8 }}>
                {planResult.result?.summary && Object.entries(planResult.result.summary).map(([k, v]) => (
                  <p key={k}>{k}: <strong>{String(v)}</strong></p>
                ))}
                {planResult.result?.issues?.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <p style={{ fontWeight: 600, color: '#ea580c' }}>退出/进入问题:</p>
                    {planResult.result.issues.map((issue: string, i: number) => (
                      <div key={i} className="status-pill fail" style={{ marginBottom: 4 }}>{issue}</div>
                    ))}
                  </div>
                )}
                {planResult.result?.warnings?.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <p style={{ fontWeight: 600, color: '#f59e0b' }}>警告:</p>
                    {planResult.result.warnings.map((w: string, i: number) => (
                      <div key={i} className="status-pill unknown" style={{ marginBottom: 4 }}>{w}</div>
                    ))}
                  </div>
                )}
                {!planResult.result?.issues?.length && !planResult.result?.warnings?.length && (
                  <span className="status-pill pass">无问题</span>
                )}
              </div>
            </div>

            {plans.length > 0 && (
              <div className="card">
                <div className="card-header">历史方案 ({plans.length})</div>
                {plans.map((plan: any, i: number) => (
                  <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #e2e8f0', fontSize: 11 }}>
                    <div style={{ fontWeight: 500 }}>
                      {plan.aircraft_platform === 'vtol' ? 'VTOL' : '固定翼'} · {plan.aircraft_preset}
                    </div>
                    <div style={{ color: '#64748b' }}>
                      状态: <span className={`status-pill ${plan.result?.status === 'pass' ? 'pass' : plan.result?.status === 'fail' ? 'fail' : 'unknown'}`}>
                        {plan.result?.status || 'unknown'}
                      </span>
                      {plan.created_at && <span style={{ marginLeft: 8 }}>{new Date(plan.created_at).toLocaleDateString()}</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default TakeoffFlightPage;
