import React, { useState, useEffect, useCallback, useRef } from 'react';
import { MapContainer, Polygon, Polyline, Popup, useMapEvents, useMap } from 'react-leaflet';
import BaseMapLayer from '../../components/MapView/BaseMapLayer';
import { apiClient } from '../../api/client';
import type { ImportProject, ImportItem } from '../../api/types';
import type L from 'leaflet';

const MAP_CENTER: [number, number] = [31.2304, 121.4737];

interface Viewport {
  west: number; south: number; east: number; north: number;
}

function ViewportListener({ onChange }: { onChange: (vp: Viewport) => void }) {
  useMapEvents({
    moveend: (e) => {
      const map = e.target;
      const bounds = map.getBounds();
      onChange({
        west: bounds.getWest(), south: bounds.getSouth(),
        east: bounds.getEast(), north: bounds.getNorth(),
      });
    },
  });
  return null;
}

function MapInstanceCapture({ onReady }: { onReady: (map: L.Map) => void }) {
  const map = useMap();
  useEffect(() => { onReady(map); }, [map, onReady]);
  return null;
}

const DataImportPage: React.FC = () => {
  // State
  const [_projects, setProjects] = useState<ImportProject[]>([]);
  const [items, setItems] = useState<ImportItem[]>([]);
  const [selectedItemIds, setSelectedItemIds] = useState<Set<number>>(new Set());
  const [visibleItemIds, setVisibleItemIds] = useState<Set<number>>(new Set());
  const [lockedItemIds, setLockedItemIds] = useState<Set<number>>(new Set());
  const [loadingList, setLoadingList] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [mapFeatures, setMapFeatures] = useState<any[]>([]);
  const [mapResult, setMapResult] = useState({ returned_count: 0, total_count: 0, truncated: false });
  const [viewport, setViewport] = useState<Viewport | null>(null);

  // Accordion state
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['vector']));

  // Forms
  const [vectorFile, setVectorFile] = useState<File | null>(null);
  const [vectorName, setVectorName] = useState('');
  const [vectorSourceCrs, setVectorSourceCrs] = useState('EPSG:4326');

  const [obstacleFile, setObstacleFile] = useState<File | null>(null);
  const [obstacleName, setObstacleName] = useState('');
  const [obstacleSourceCrs, setObstacleSourceCrs] = useState('EPSG:4326');
  const [obstacleJobId, setObstacleJobId] = useState<number | null>(null);
  const [obstacleJob, setObstacleJob] = useState<any>(null);

  // AI form
  const [aiFiles, setAiFiles] = useState<File[]>([]);
  const [aiName, setAiName] = useState('');
  const [aiProvider, setAiProvider] = useState('openai');
  const [aiModel] = useState('');
  const [aiApiKey, setAiApiKey] = useState('');
  const [aiBaseUrl, setAiBaseUrl] = useState('');
  const [aiText, setAiText] = useState('');
  const [aiInstruction, setAiInstruction] = useState('');
  const [aiPreview, setAiPreview] = useState<any>(null);
  const [aiAnalyzing, setAiAnalyzing] = useState(false);

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mapRef = useRef<L.Map | null>(null);

  // Locate item on map
  const locateItem = useCallback(async (itemId: number) => {
    const map = mapRef.current;
    if (!map) return;
    let bounds = items.find(i => i.id === itemId)?.bounds;
    if (!bounds) {
      try {
        const detail = await apiClient.getImportItem(itemId);
        bounds = detail?.bounds;
      } catch { /* ignore */ }
    }
    if (bounds && bounds.west !== undefined) {
      map.flyToBounds([[bounds.south, bounds.west], [bounds.north, bounds.east]], { padding: [40, 40] });
    }
  }, [items]);

  // Data loading
  const reloadAll = useCallback(async () => {
    setLoadingList(true);
    try {
      const [projRes, itemRes] = await Promise.all([
        apiClient.getImportProjects(),
        apiClient.getImportItems(),
      ]);
      const projItems = (projRes.items || []) as ImportProject[];
      const allItems = (itemRes.items || []) as ImportItem[];
      setProjects(projItems);
      setItems(allItems);
      setVisibleItemIds(new Set(allItems.filter(i => i.is_visible).map(i => i.id)));
      setLockedItemIds(new Set(allItems.filter(i => i.is_locked).map(i => i.id)));
    } catch { /* ignore */ }
    setLoadingList(false);
  }, []);

  useEffect(() => { reloadAll(); }, [reloadAll]);

  // Load map features on viewport change or selection change
  useEffect(() => {
    if (!viewport) return;
    let cancelled = false;
    const load = async () => {
      try {
        const params: Record<string, any> = { bbox: viewport, zoom: 10, max_features: 1200 };
        if (selectedItemIds.size > 0) {
          params.item_ids = Array.from(selectedItemIds);
        }
        const result = await apiClient.queryImportMapFeatures(params);
        if (cancelled) return;
        setMapFeatures(result.features || []);
        setMapResult({
          returned_count: result.returned_count ?? result.features?.length ?? 0,
          total_count: result.total_count ?? 0,
          truncated: result.truncated ?? false,
        });
      } catch { /* ignore */ }
    };
    load();
    return () => { cancelled = true; };
  }, [viewport, selectedItemIds]);

  // Poll obstacle job
  useEffect(() => {
    if (obstacleJobId) {
      pollTimerRef.current = setInterval(async () => {
        try {
          const job = await apiClient.getImportJob(obstacleJobId);
          setObstacleJob(job);
          if (job.status === 'completed' || job.status === 'failed') {
            if (pollTimerRef.current) clearInterval(pollTimerRef.current);
            if (job.status === 'completed') {
              setUploading(false);
              setObstacleFile(null);
              setObstacleJobId(null);
              await reloadAll();
            }
          }
        } catch { /* ignore */ }
      }, 1000);
      return () => { if (pollTimerRef.current) clearInterval(pollTimerRef.current); };
    }
  }, [obstacleJobId, reloadAll]);

  // Toggle section
  const toggleSection = (id: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  // Item selection
  const selectOnlyItem = (id: number) => {
    setSelectedItemIds(new Set([id]));
    locateItem(id);
  };
  const toggleSelectedItem = (id: number) => {
    setSelectedItemIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  // Visibility
  const toggleItemVisible = async (item: ImportItem) => {
    try {
      await apiClient.updateImportItem(item.id, { isVisible: !item.is_visible });
      setVisibleItemIds(prev => {
        const next = new Set(prev);
        if (next.has(item.id)) next.delete(item.id); else next.add(item.id);
        return next;
      });
    } catch { /* ignore */ }
  };

  // Airspace level cycle
  const cycleAirspaceLevel = async (item: ImportItem) => {
    const levels = ['suitable', 'limited', 'prohibited'] as const;
    const idx = levels.indexOf(item.airspace_level as any);
    const next = levels[(idx + 1) % levels.length];
    try {
      await apiClient.updateImportItem(item.id, { airspaceLevel: next });
      await reloadAll();
    } catch { /* ignore */ }
  };

  // Lock toggle
  const toggleItemLock = async (itemId: number) => {
    const item = items.find(i => i.id === itemId);
    if (!item) return;
    try {
      await apiClient.updateImportItem(itemId, { isLocked: !item.is_locked });
      setLockedItemIds(prev => {
        const next = new Set(prev);
        if (next.has(itemId)) next.delete(itemId); else next.add(itemId);
        return next;
      });
    } catch { /* ignore */ }
  };

  // Bulk operations
  const showAllItems = async () => {
    for (const item of items) {
      if (!visibleItemIds.has(item.id)) {
        await apiClient.updateImportItem(item.id, { isVisible: true }).catch(() => {});
      }
    }
    setVisibleItemIds(new Set(items.map(i => i.id)));
  };

  const hideAllItems = async () => {
    for (const item of items) {
      if (visibleItemIds.has(item.id)) {
        await apiClient.updateImportItem(item.id, { isVisible: false }).catch(() => {});
      }
    }
    setVisibleItemIds(new Set());
  };

  const clearAllItems = async () => {
    if (!confirm('确认清空所有未锁定的导入数据项？')) return;
    const unlocked = items.filter(i => !lockedItemIds.has(i.id));
    for (const item of unlocked) {
      await apiClient.deleteImportItem(item.id).catch(() => {});
    }
    await reloadAll();
  };

  const removeSelectedItems = async () => {
    for (const id of selectedItemIds) {
      if (!lockedItemIds.has(id)) {
        await apiClient.deleteImportItem(id).catch(() => {});
      }
    }
    setSelectedItemIds(new Set());
    await reloadAll();
  };

  const mergeSelected = async () => {
    if (selectedItemIds.size < 2) return;
    const name = prompt('合并后的项目名称：', '合并项目');
    if (!name) return;
    try {
      await apiClient.mergeImportItems({ name, item_ids: Array.from(selectedItemIds) });
      await reloadAll();
    } catch (e: any) { alert(e?.message || '合并失败'); }
  };

  const exportSelected = () => {
    const url = apiClient.exportImportGeoJson({ item_ids: Array.from(selectedItemIds) });
    window.open(url, '_blank');
  };

  // File uploads
  const submitVectorImport = async () => {
    if (!vectorFile) return;
    setUploading(true);
    try {
      await apiClient.uploadImportedDataset(vectorFile, {
        name: vectorName || undefined,
        sourceCrs: vectorSourceCrs,
        targetCrs: 'EPSG:4326',
      });
      setVectorFile(null);
      setVectorName('');
      await reloadAll();
    } catch (e: any) { alert(e?.message || '导入失败'); }
    setUploading(false);
  };

  const submitObstacleImport = async () => {
    if (!obstacleFile) return;
    setUploading(true);
    try {
      const job = await apiClient.uploadObstacleSurfaceDataset(obstacleFile, {
        name: obstacleName || undefined,
        sourceCrs: obstacleSourceCrs,
        targetCrs: 'EPSG:4326',
      });
      setObstacleJobId(job.id);
      setObstacleJob(job);
    } catch (e: any) { alert(e?.message || '导入失败'); setUploading(false); }
  };

  const submitAiAnalyze = async () => {
    if (!aiFiles.length && !aiText.trim()) return;
    setAiAnalyzing(true);
    try {
      const result = await apiClient.analyzeAiImport(aiFiles, {
        name: aiName || undefined,
        provider: aiProvider,
        model: aiModel || undefined,
        apiKey: aiApiKey,
        baseUrl: aiBaseUrl || undefined,
        text: aiText || undefined,
        instruction: aiInstruction || undefined,
      });
      setAiPreview(result);
    } catch (e: any) { alert(e?.message || 'AI分析失败'); }
    setAiAnalyzing(false);
  };

  const commitAiResult = async () => {
    if (!aiPreview) return;
    try {
      await apiClient.commitAiImport({
        name: aiPreview.name || 'AI识别结果',
        items: aiPreview.items || [],
        metadata: aiPreview.metadata || {},
      });
      setAiPreview(null);
      setAiFiles([]);
      setAiName('');
      setAiText('');
      setAiInstruction('');
      await reloadAll();
    } catch (e: any) { alert(e?.message || '提交失败'); }
  };

  // Helpers
  const airspaceLabel = (level: string) => {
    switch (level) {
      case 'suitable': return '适合飞行';
      case 'limited': return '限制飞行';
      case 'prohibited': return '禁止飞行';
      default: return level;
    }
  };

  const airspaceShort = (level: string) => {
    switch (level) {
      case 'suitable': return '适';
      case 'limited': return '限';
      case 'prohibited': return '禁';
      default: return '?';
    }
  };

  const getFeatureColor = (props: any) => {
    const level = props?.airspace_level || 'suitable';
    switch (level) {
      case 'suitable': return '#16a34a';
      case 'limited': return '#ea580c';
      case 'prohibited': return '#dc2626';
      default: return '#64748b';
    }
  };

  return (
    <div className="module-layout" style={{ display: 'flex', gap: 8, height: 'calc(100vh - 100px)' }}>
      {/* Left Panel - Item Management */}
      <div className="module-panel" style={{ width: 320, minWidth: 320 }}>
        <div className="module-panel-header">
          <span>导入数据项管理</span>
          <button className="btn btn-xs" onClick={reloadAll} disabled={loadingList || uploading}>刷新</button>
        </div>

        <div style={{ display: 'flex', gap: 8, padding: 8 }}>
          <div className="metric"><div className="metric-label">数据项</div><div className="metric-value">{items.length}</div></div>
          <div className="metric"><div className="metric-label">当前视图</div><div className="metric-value">{mapResult.total_count}</div></div>
        </div>

        <div style={{ display: 'flex', gap: 2, padding: '4px 8px', flexWrap: 'wrap' }}>
          <button className="btn btn-xs" onClick={showAllItems} disabled={!items.length}>全部显示</button>
          <button className="btn btn-xs" onClick={hideAllItems} disabled={!items.length}>全部隐藏</button>
          <button className="btn btn-xs btn-danger" onClick={clearAllItems} disabled={!items.length}>全部清空</button>
          <button className="btn btn-xs" disabled={selectedItemIds.size !== 1}
            onClick={async () => {
              const id = [...selectedItemIds][0];
              const item = items.find(i => i.id === id);
              const name = prompt('新名称：', item?.name || '');
              if (name && name.trim()) {
                await apiClient.updateImportItem(id, { name: name.trim() });
                reloadAll();
              }
            }}>重命名</button>
          <button className="btn btn-xs" disabled={!selectedItemIds.size}
            onClick={() => { const id = [...selectedItemIds][0]; if (id) locateItem(id); }}>定位</button>
          <button className="btn btn-xs btn-danger" onClick={removeSelectedItems} disabled={!selectedItemIds.size}>删除</button>
          <button className="btn btn-xs" onClick={mergeSelected} disabled={selectedItemIds.size < 2}>合并</button>
          <button className="btn btn-xs" onClick={exportSelected} disabled={!selectedItemIds.size}>导出</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {!items.length && !loadingList ? (
            <div className="empty-state"><div className="empty-state-text">暂无导入数据项</div></div>
          ) : items.map(item => (
            <div key={item.id}
              onClick={() => selectOnlyItem(item.id)}
              style={{
                padding: '6px 8px', marginBottom: 2, borderRadius: 6, cursor: 'pointer', fontSize: 12,
                background: selectedItemIds.has(item.id) ? '#dbeafe' : '#f8fafc',
                border: selectedItemIds.has(item.id) ? '1px solid #93c5fd' : '1px solid #e2e8f0',
                borderLeft: `3px solid ${item.airspace_level === 'suitable' ? '#16a34a' : item.airspace_level === 'limited' ? '#ea580c' : item.airspace_level === 'prohibited' ? '#dc2626' : '#94a3b8'}`,
              }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <input type="checkbox" checked={selectedItemIds.has(item.id)}
                  onChange={(e) => { e.stopPropagation(); toggleSelectedItem(item.id); }} />
                <button className={`btn btn-xs ${lockedItemIds.has(item.id) ? 'btn-primary' : ''}`}
                  style={{ fontSize: 10, padding: '2px 4px' }}
                  onClick={(e) => { e.stopPropagation(); toggleItemLock(item.id); }}
                  title={lockedItemIds.has(item.id) ? '已锁定' : '未锁定'}>
                  {lockedItemIds.has(item.id) ? '🔒' : '🔓'}
                </button>
                <button className="btn btn-xs" style={{ fontSize: 10, padding: '2px 4px' }}
                  onClick={(e) => { e.stopPropagation(); toggleItemVisible(item); }}>
                  {visibleItemIds.has(item.id) ? '👁' : '—'}
                </button>
                <button className="btn btn-xs" style={{
                  fontSize: 10, padding: '2px 5px', fontWeight: 700,
                  background: item.airspace_level === 'suitable' ? '#dcfce7' : item.airspace_level === 'limited' ? '#fff7ed' : '#fef2f2',
                  color: item.airspace_level === 'suitable' ? '#166534' : item.airspace_level === 'limited' ? '#9a3412' : '#991b1b',
                  border: 'none',
                }} onClick={(e) => { e.stopPropagation(); cycleAirspaceLevel(item); }} title={airspaceLabel(item.airspace_level)}>
                  {airspaceShort(item.airspace_level)}
                </button>
                <span style={{ fontWeight: 600, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.name}
                  {lockedItemIds.has(item.id) && <span style={{ marginLeft: 4, color: '#f59e0b', fontSize: 10 }}>锁定</span>}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Center Panel - Map */}
      <div className="module-map-panel" style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <div className="module-panel-header" style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>导入数据地图</span>
          <span style={{ fontSize: 11, color: '#64748b' }}>
            {mapResult.truncated ? '当前视图要素过多，请放大查看' : `${mapResult.returned_count} / ${mapResult.total_count} 要素`}
          </span>
        </div>
        <div style={{ flex: 1, position: 'relative' }}>
          <MapContainer center={MAP_CENTER} zoom={10} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}>
            <BaseMapLayer />
            <MapInstanceCapture onReady={(map) => { mapRef.current = map; }} />
            <ViewportListener onChange={setViewport} />
            {(() => {
              const itemFeatureIndex = new Map<number, number>();
              const dashPatterns = [null, '6,3', '2,4', '10,5'];
              return mapFeatures.map((feature: any, i: number) => {
              const color = getFeatureColor(feature.properties);
              const itemId = feature.properties?.item_id;
              if (feature.geometry?.type === 'Polygon' || feature.geometry?.type === 'MultiPolygon') {
                const coords = feature.geometry.type === 'Polygon'
                  ? feature.geometry.coordinates[0]?.map((c: number[]) => [c[1], c[0]] as [number, number])
                  : feature.geometry.coordinates[0]?.[0]?.map((c: number[]) => [c[1], c[0]] as [number, number]);
                if (!coords?.length) return null;
                const idx = itemFeatureIndex.get(itemId) ?? 0;
                itemFeatureIndex.set(itemId, idx + 1);
                const dashArray = idx > 0 ? dashPatterns[idx % dashPatterns.length] : undefined;
                return (
                  <Polygon key={`f-${i}`} positions={coords}
                    color={color} fillColor={color}
                    fillOpacity={0.08} weight={2.5}
                    {...(dashArray ? { dashArray } : {})}
                    opacity={0.7}>
                    <Popup>
                      <div style={{ fontSize: 11 }}>
                        <strong>{feature.properties?.name || '未命名'}</strong><br />
                        类型: {feature.properties?.item_type || '未知'}<br />
                        空域: {airspaceLabel(feature.properties?.airspace_level || 'suitable')}
                      </div>
                    </Popup>
                  </Polygon>
                );
              }
              if (feature.geometry?.type === 'LineString') {
                const coords = feature.geometry.coordinates.map((c: number[]) => [c[1], c[0]] as [number, number]);
                return <Polyline key={`f-${i}`} positions={coords} color={color} weight={3} />;
              }
              return null;
            })})()}
          </MapContainer>
        </div>
      </div>

      {/* Right Panel - Import Methods */}
      <div className="module-panel" style={{ width: 320, minWidth: 320 }}>
        <div className="module-panel-header">
          <span>数据导入</span>
          <span style={{ fontSize: 11, color: uploading ? '#ea580c' : '#64748b' }}>{uploading ? '处理中' : '待操作'}</span>
        </div>
        <div style={{ flex: 1, overflowY: 'auto' }}>

          {/* Vector Import */}
          <div style={{ borderBottom: '1px solid #e2e8f0' }}>
            <div style={{
              padding: '8px 12px', background: '#f8fafc', cursor: 'pointer', fontWeight: 600, fontSize: 13,
              display: 'flex', justifyContent: 'space-between',
            }} onClick={() => toggleSection('vector')}>
              <span>矢量导入</span>
              <span>{expandedSections.has('vector') ? '收起' : '展开'}</span>
            </div>
            {expandedSections.has('vector') && (
              <div style={{ padding: '8px 12px' }}>
                <div className="form-group">
                  <label className="form-label">数据名称</label>
                  <input className="form-input sm" placeholder="为空时使用文件名" value={vectorName}
                    onChange={e => setVectorName(e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">导入文件</label>
                  <input type="file" className="form-input sm" accept=".kml,.shp,.zip,.geojson,.json"
                    onChange={e => setVectorFile(e.target.files?.[0] || null)} />
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                    {vectorFile ? vectorFile.name : '支持 KML / SHP / ZIP / GeoJSON'}
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">源坐标系</label>
                  <select className="form-input sm" value={vectorSourceCrs}
                    onChange={e => setVectorSourceCrs(e.target.value)}>
                    <option value="EPSG:4326">WGS84 (EPSG:4326)</option>
                    <option value="EPSG:3857">Web Mercator (EPSG:3857)</option>
                    <option value="EPSG:4490">CGCS2000 (EPSG:4490)</option>
                  </select>
                </div>
                <button className="btn btn-primary btn-sm" style={{ width: '100%' }}
                  onClick={submitVectorImport} disabled={uploading || !vectorFile}>开始导入</button>
              </div>
            )}
          </div>

          {/* Obstacle Surface Import */}
          <div style={{ borderBottom: '1px solid #e2e8f0' }}>
            <div style={{
              padding: '8px 12px', background: '#f8fafc', cursor: 'pointer', fontWeight: 600, fontSize: 13,
              display: 'flex', justifyContent: 'space-between',
            }} onClick={() => toggleSection('obstacle')}>
              <span>障碍物限制面</span>
              <span>{expandedSections.has('obstacle') ? '收起' : '展开'}</span>
            </div>
            {expandedSections.has('obstacle') && (
              <div style={{ padding: '8px 12px' }}>
                <div className="form-group">
                  <label className="form-label">项目名称</label>
                  <input className="form-input sm" placeholder="例如：全国机场障碍物限制面" value={obstacleName}
                    onChange={e => setObstacleName(e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">限制面表格文件</label>
                  <input type="file" className="form-input sm" accept=".xls,.xlsx,.csv"
                    onChange={e => setObstacleFile(e.target.files?.[0] || null)} />
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                    {obstacleFile ? obstacleFile.name : '导入后按机场聚合为独立项'}
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">源坐标系</label>
                  <select className="form-input sm" value={obstacleSourceCrs}
                    onChange={e => setObstacleSourceCrs(e.target.value)}>
                    <option value="EPSG:4326">WGS84 (EPSG:4326)</option>
                    <option value="EPSG:4490">CGCS2000 (EPSG:4490)</option>
                  </select>
                </div>
                {obstacleJobId && (
                  <div style={{ padding: 8, background: '#fffbeb', borderRadius: 4, marginBottom: 8, fontSize: 12 }}>
                    <div>进度：{obstacleJob?.progress ?? 0}%</div>
                    <progress value={obstacleJob?.progress ?? 0} max="100" style={{ width: '100%' }} />
                    <div>{obstacleJob?.message || '处理中...'}</div>
                    {obstacleJob?.total_count && <div>{obstacleJob.processed_count} / {obstacleJob.total_count}</div>}
                  </div>
                )}
                <button className="btn btn-primary btn-sm" style={{ width: '100%' }}
                  onClick={submitObstacleImport} disabled={uploading || !obstacleFile}>上传并生成项目</button>
              </div>
            )}
          </div>

          {/* AI Recognition */}
          <div style={{ borderBottom: '1px solid #e2e8f0' }}>
            <div style={{
              padding: '8px 12px', background: '#f8fafc', cursor: 'pointer', fontWeight: 600, fontSize: 13,
              display: 'flex', justifyContent: 'space-between',
            }} onClick={() => toggleSection('ai')}>
              <span>AI 智能识别</span>
              <span>{expandedSections.has('ai') ? '收起' : '展开'}</span>
            </div>
            {expandedSections.has('ai') && (
              <div style={{ padding: '8px 12px' }}>
                <div className="form-group">
                  <label className="form-label">数据名称</label>
                  <input className="form-input sm" placeholder="AI识别结果" value={aiName}
                    onChange={e => setAiName(e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">上传文件（PDF/图片/文档）</label>
                  <input type="file" className="form-input sm" accept=".pdf,.png,.jpg,.txt,.md,.docx,.xlsx" multiple
                    onChange={e => setAiFiles(Array.from(e.target.files || []))} />
                  {aiFiles.length > 0 && (
                    <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{aiFiles.map(f => f.name).join(', ')}</div>
                  )}
                </div>
                <div className="form-group">
                  <label className="form-label">补充文本</label>
                  <textarea className="form-input sm" rows={2} placeholder="补充说明空域信息..."
                    value={aiText} onChange={e => setAiText(e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">API 提供商</label>
                  <select className="form-input sm" value={aiProvider}
                    onChange={e => setAiProvider(e.target.value)}>
                    <option value="openai">OpenAI</option>
                    <option value="custom">自定义</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">API Key</label>
                  <input className="form-input sm" type="password" value={aiApiKey}
                    onChange={e => setAiApiKey(e.target.value)} />
                </div>
                {aiProvider === 'custom' && (
                  <div className="form-group">
                    <label className="form-label">Base URL</label>
                    <input className="form-input sm" value={aiBaseUrl}
                      onChange={e => setAiBaseUrl(e.target.value)} />
                  </div>
                )}
                <button className="btn btn-primary btn-sm" style={{ width: '100%' }}
                  onClick={submitAiAnalyze} disabled={aiAnalyzing || (!aiFiles.length && !aiText.trim())}>
                  {aiAnalyzing ? '分析中...' : 'AI 分析'}
                </button>

                {aiPreview && (
                  <div style={{ marginTop: 8, padding: 8, background: '#f0fdf4', borderRadius: 4, fontSize: 12 }}>
                    <div style={{ fontWeight: 600 }}>识别结果：{aiPreview.item_count || 0} 项</div>
                    {aiPreview.items?.slice(0, 5).map((item: any, i: number) => (
                      <div key={i} style={{ padding: '2px 0' }}>
                        <span className={`status-pill ${item.airspace_level === 'suitable' ? 'pass' : item.airspace_level === 'prohibited' ? 'fail' : 'unknown'}`}>
                          {airspaceShort(item.airspace_level)}
                        </span> {item.name}
                      </div>
                    ))}
                    <button className="btn btn-primary btn-xs" style={{ marginTop: 4, width: '100%' }} onClick={commitAiResult}>
                      确认导入
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Manual Input */}
          <div style={{ borderBottom: '1px solid #e2e8f0' }}>
            <div style={{
              padding: '8px 12px', background: '#f8fafc', cursor: 'pointer', fontWeight: 600, fontSize: 13,
              display: 'flex', justifyContent: 'space-between',
            }} onClick={() => toggleSection('manual')}>
              <span>手动输入</span>
              <span>{expandedSections.has('manual') ? '收起' : '展开'}</span>
            </div>
            {expandedSections.has('manual') && (
              <div style={{ padding: '8px 12px' }}>
                <div className="form-group">
                  <label className="form-label">名称</label>
                  <input className="form-input sm" placeholder="输入要素名称" />
                </div>
                <div className="form-group">
                  <label className="form-label">GeoJSON</label>
                  <textarea className="form-input sm" rows={4} placeholder='{"type":"FeatureCollection","features":[...]}' />
                </div>
                <div className="form-group">
                  <label className="form-label">空域等级</label>
                  <select className="form-input sm">
                    <option value="suitable">适合飞行</option>
                    <option value="limited">限制飞行</option>
                    <option value="prohibited">禁止飞行</option>
                  </select>
                </div>
                <button className="btn btn-primary btn-sm" style={{ width: '100%' }}>创建要素</button>
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
};

export default DataImportPage;
