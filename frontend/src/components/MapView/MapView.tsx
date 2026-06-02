import React from 'react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import { MapContainer, Marker, Popup, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import TrackLayer from './TrackLayer';
import RunwayMarker from './RunwayMarker';
import HelipadLayer from './HelipadLayer';
import Map3DView from './Map3DView';
import MapLibre3DView from './MapLibre3DView';
import Enhanced3DView from './Enhanced3DView';
import { useTrackStore } from '../../store/useTrackStore';
import { useRunwayStore } from '../../store/useRunwayStore';
import { useMapSettingsStore } from '../../store/useMapSettingsStore';
import { useHelipadStore } from '../../store/useHelipadStore';
import {
  BASE_MAP_LABELS,
  BASE_MAP_TYPES,
  BaseMapType,
  PoiSearchBounds,
  PoiSearchResult,
} from '../../types/map';
import { Coordinate } from '../../types/runway';
import { searchPoi } from '../../utils/poiSearch';

const DefaultIcon = L.icon({
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});

L.Marker.prototype.options.icon = DefaultIcon;

interface MapViewProps {
  center: [number, number];
  zoom: number;
}

interface PendingRunwayCoordinate {
  latitude: number;
  longitude: number;
}

type MapMode = '2d' | '3d';

const TIANDITU_SUBDOMAINS = ['0', '1', '2', '3', '4', '5', '6', '7'];
const POI_SEARCH_RADIUS_METERS = 5000;

function getTiandituWMTSUrl(endpoint: string, apiKey: string): string {
  const layerName = endpoint.replace('_w', '');
  return (
    `https://t{s}.tianditu.gov.cn/${endpoint}/wmts?` +
    `SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layerName}` +
    `&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}` +
    `&TILEROW={y}&TILECOL={x}&tk=${apiKey}`
  );
}

function boundsAroundCoordinate(
  coordinate: Coordinate,
  radiusMeters = POI_SEARCH_RADIUS_METERS
): PoiSearchBounds {
  const latitudeDelta = radiusMeters / 111_320;
  const longitudeScale = Math.max(Math.cos((coordinate.latitude * Math.PI) / 180), 0.1);
  const longitudeDelta = radiusMeters / (111_320 * longitudeScale);

  return {
    west: coordinate.longitude - longitudeDelta,
    south: coordinate.latitude - latitudeDelta,
    east: coordinate.longitude + longitudeDelta,
    north: coordinate.latitude + latitudeDelta,
  };
}

function stopToolbarEvent(event: React.SyntheticEvent): void {
  event.stopPropagation();
  L.DomEvent.stopPropagation(event.nativeEvent);
}

const MapCenterUpdater: React.FC<{ center: [number, number] }> = ({ center }) => {
  const map = useMap();

  React.useEffect(() => {
    map.setView(center, map.getZoom());
  }, [center, map]);

  return null;
};

const MapInstanceBridge: React.FC<{ onReady: (map: L.Map | null) => void }> = ({ onReady }) => {
  const map = useMap();

  React.useEffect(() => {
    onReady(map);
    return () => onReady(null);
  }, [map, onReady]);

  return null;
};

const MapVisibilityUpdater: React.FC<{ visible: boolean }> = ({ visible }) => {
  const map = useMap();

  React.useEffect(() => {
    if (visible) {
      window.setTimeout(() => map.invalidateSize(), 0);
    }
  }, [map, visible]);

  return null;
};

const BaseMapLayer: React.FC = () => {
  const baseMapType = useMapSettingsStore((state) => state.baseMapType);
  const tiandituKey = useMapSettingsStore((state) => state.tiandituKey);
  const effectiveBaseMap: BaseMapType =
    baseMapType === 'osm' || tiandituKey ? baseMapType : 'osm';

  if (effectiveBaseMap === 'tianditu-vector') {
    return (
      <>
        <TileLayer
          key="tianditu-vector-base"
          attribution="天地图"
          maxZoom={18}
          subdomains={TIANDITU_SUBDOMAINS}
          url={getTiandituWMTSUrl('vec_w', tiandituKey)}
        />
        <TileLayer
          key="tianditu-vector-label"
          maxZoom={18}
          subdomains={TIANDITU_SUBDOMAINS}
          url={getTiandituWMTSUrl('cva_w', tiandituKey)}
        />
      </>
    );
  }

  if (effectiveBaseMap === 'tianditu-image') {
    return (
      <>
        <TileLayer
          key="tianditu-image-base"
          attribution="天地图"
          maxZoom={18}
          subdomains={TIANDITU_SUBDOMAINS}
          url={getTiandituWMTSUrl('img_w', tiandituKey)}
        />
        <TileLayer
          key="tianditu-image-label"
          maxZoom={18}
          subdomains={TIANDITU_SUBDOMAINS}
          url={getTiandituWMTSUrl('cia_w', tiandituKey)}
        />
      </>
    );
  }

  if (effectiveBaseMap === 'tianditu-terrain') {
    return (
      <>
        <TileLayer
          key="tianditu-terrain-base"
          attribution="天地图"
          maxZoom={18}
          subdomains={TIANDITU_SUBDOMAINS}
          url={getTiandituWMTSUrl('ter_w', tiandituKey)}
        />
        <TileLayer
          key="tianditu-terrain-label"
          maxZoom={18}
          subdomains={TIANDITU_SUBDOMAINS}
          url={getTiandituWMTSUrl('cta_w', tiandituKey)}
        />
      </>
    );
  }

  return (
    <TileLayer
      key="osm"
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      maxZoom={19}
      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    />
  );
};

const RunwayClickSelector: React.FC = () => {
  const setRunwayParams = useRunwayStore((state) => state.setRunwayParams);
  const clearTrackData = useTrackStore((state) => state.clearTrackData);
  const [pendingCoordinate, setPendingCoordinate] =
    React.useState<PendingRunwayCoordinate | null>(null);

  useMapEvents({
    click: (event) => {
      const target = event.originalEvent.target;
      if (target instanceof HTMLElement && target.closest('.runway-confirm-popup')) {
        return;
      }

      setPendingCoordinate({
        latitude: Number(event.latlng.lat.toFixed(6)),
        longitude: Number(event.latlng.lng.toFixed(6)),
      });
    },
  });

  const handleCancel = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    setPendingCoordinate(null);
  };

  const handleConfirm = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (!pendingCoordinate) {
      return;
    }

    setRunwayParams({
      coordinate: pendingCoordinate,
      coordinateSystem: 'WGS84',
    });
    clearTrackData();
    setPendingCoordinate(null);
  };

  if (!pendingCoordinate) {
    return null;
  }

  return (
    <>
      <Marker position={[pendingCoordinate.latitude, pendingCoordinate.longitude]} />
      <Popup
        position={[pendingCoordinate.latitude, pendingCoordinate.longitude]}
        closeButton={false}
        closeOnClick={false}
        autoClose={false}
        className="runway-confirm-popup"
      >
        <Stack spacing={1} sx={{ minWidth: 210 }}>
          <Typography variant="subtitle2">确认切换跑道中心点？</Typography>
          <Typography variant="caption" color="text.secondary">
            纬度 {pendingCoordinate.latitude.toFixed(6)}
            <br />
            经度 {pendingCoordinate.longitude.toFixed(6)}
          </Typography>
          <Stack direction="row" spacing={1} justifyContent="flex-end">
            <Button size="small" onClick={handleCancel}>
              取消
            </Button>
            <Button size="small" variant="contained" onClick={handleConfirm}>
              确认切换
            </Button>
          </Stack>
        </Stack>
      </Popup>
    </>
  );
};

const PoiMarkerLayer: React.FC<{ poi: PoiSearchResult | null }> = ({ poi }) => {
  const map = useMap();
  const markerRef = React.useRef<L.Marker | null>(null);

  React.useEffect(() => {
    if (!poi) {
      return;
    }

    map.setView(
      [poi.coordinate.latitude, poi.coordinate.longitude],
      Math.max(map.getZoom(), 16)
    );
    window.setTimeout(() => markerRef.current?.openPopup(), 0);
  }, [map, poi]);

  if (!poi) {
    return null;
  }

  return (
    <Marker ref={markerRef} position={[poi.coordinate.latitude, poi.coordinate.longitude]}>
      <Popup>
        <Stack spacing={0.5} sx={{ minWidth: 210 }}>
          <Typography variant="subtitle2">{poi.name}</Typography>
          {poi.address && (
            <Typography variant="caption" color="text.secondary">
              {poi.address}
            </Typography>
          )}
          <Typography variant="caption" color="text.secondary">
            {poi.source === 'tianditu' ? '天地图' : 'OpenStreetMap'}
            <br />
            纬度 {poi.coordinate.latitude.toFixed(6)}
            <br />
            经度 {poi.coordinate.longitude.toFixed(6)}
          </Typography>
        </Stack>
      </Popup>
    </Marker>
  );
};

interface MapSettingsDialogProps {
  open: boolean;
  onClose: () => void;
}

const MapSettingsDialog: React.FC<MapSettingsDialogProps> = ({ open, onClose }) => {
  const tiandituKey = useMapSettingsStore((state) => state.tiandituKey);
  const saveTiandituKey = useMapSettingsStore((state) => state.saveTiandituKey);
  const clearTiandituKey = useMapSettingsStore((state) => state.clearTiandituKey);
  const [draftKey, setDraftKey] = React.useState('');
  const [showKey, setShowKey] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setDraftKey(tiandituKey);
      setShowKey(false);
    }
  }, [open, tiandituKey]);

  const handleSave = () => {
    saveTiandituKey(draftKey);
    onClose();
  };

  const handleClear = () => {
    clearTiandituKey();
    setDraftKey('');
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>天地图设置</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField
            label="天地图 API Key"
            type={showKey ? 'text' : 'password'}
            value={draftKey}
            onChange={(event) => setDraftKey(event.target.value)}
            fullWidth
            size="small"
            placeholder="请输入天地图浏览器端 Key"
          />
          <Stack direction="row" spacing={1}>
            <Button size="small" onClick={() => setShowKey((value) => !value)}>
              {showKey ? '隐藏 Key' : '显示 Key'}
            </Button>
            <Button
              size="small"
              component="a"
              href="https://console.tianditu.gov.cn/api/key"
              target="_blank"
              rel="noreferrer"
            >
              前往申请
            </Button>
          </Stack>
          <Typography variant="body2" color="text.secondary">
            未配置 Key 时使用 OpenStreetMap，天地图矢量、影像和地形底图不可用。
          </Typography>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClear}>清空 Key</Button>
        <Button onClick={onClose}>取消</Button>
        <Button variant="contained" onClick={handleSave}>
          保存
        </Button>
      </DialogActions>
    </Dialog>
  );
};

interface PoiSearchControlProps {
  disabled: boolean;
  getSearchContext: () => { bounds: PoiSearchBounds; zoom: number };
  onPoiSelected: (poi: PoiSearchResult) => void;
}

const PoiSearchControl: React.FC<PoiSearchControlProps> = ({
  disabled,
  getSearchContext,
  onPoiSelected,
}) => {
  const tiandituKey = useMapSettingsStore((state) => state.tiandituKey);
  const [query, setQuery] = React.useState('');
  const [results, setResults] = React.useState<PoiSearchResult[]>([]);
  const [isSearching, setIsSearching] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);

  const handleSearch = async () => {
    const trimmedQuery = query.trim();
    if (trimmedQuery.length < 2) {
      setResults([]);
      setMessage('请输入至少 2 个字符');
      return;
    }

    setIsSearching(true);
    setMessage(null);

    try {
      const context = getSearchContext();
      const nextResults = await searchPoi({
        query: trimmedQuery,
        bounds: context.bounds,
        zoom: context.zoom,
        tiandituKey,
      });
      setResults(nextResults);
      setMessage(nextResults.length > 0 ? null : '当前范围内未找到 POI');
    } catch (error) {
      setResults([]);
      setMessage(error instanceof Error ? error.message : 'POI 搜索失败');
    } finally {
      setIsSearching(false);
    }
  };

  const handleSelect = (poi: PoiSearchResult) => {
    onPoiSelected(poi);
    setQuery(poi.name);
    setResults([]);
    setMessage(null);
  };

  return (
    <Box sx={{ minWidth: 280 }}>
      <Stack direction="row" spacing={1}>
        <TextField
          size="small"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void handleSearch();
            }
          }}
          placeholder={disabled ? '二维地图下搜索 POI' : '搜索 POI'}
          disabled={disabled}
          sx={{ bgcolor: 'white', minWidth: 190 }}
        />
        <Button
          size="small"
          variant="contained"
          onClick={() => void handleSearch()}
          disabled={disabled || isSearching}
        >
          {isSearching ? '搜索中' : '搜索'}
        </Button>
      </Stack>
      {(message || results.length > 0) && !disabled && (
        <Paper
          elevation={4}
          sx={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            right: 0,
            width: 360,
            maxWidth: 'calc(100vw - 32px)',
            overflow: 'hidden',
          }}
        >
          {message && (
            <Alert severity={results.length > 0 ? 'info' : 'warning'} sx={{ borderRadius: 0 }}>
              {message}
            </Alert>
          )}
          {results.length > 0 && (
            <List dense disablePadding>
              {results.map((poi, index) => (
                <React.Fragment key={poi.id}>
                  {index > 0 && <Divider />}
                  <ListItemButton onClick={() => handleSelect(poi)}>
                    <ListItemText
                      primary={poi.name}
                      secondary={`${poi.source === 'tianditu' ? '天地图' : 'OSM'}${
                        poi.address ? ` · ${poi.address}` : ''
                      }`}
                    />
                  </ListItemButton>
                </React.Fragment>
              ))}
            </List>
          )}
        </Paper>
      )}
    </Box>
  );
};

interface MapToolbarProps {
  mapMode: MapMode;
  setMapMode: (mode: MapMode) => void;
  showAnnotations: boolean;
  setShowAnnotations: (show: boolean) => void;
  showTrack: boolean;
  setShowTrack: (show: boolean) => void;
  showSurfaces: boolean;
  setShowSurfaces: (show: boolean) => void;
  showEnvelope: boolean;
  setShowEnvelope: (show: boolean) => void;
  showAirspaces: boolean;
  setShowAirspaces: (show: boolean) => void;
  hasTrackResult: boolean;
  getSearchContext: () => { bounds: PoiSearchBounds; zoom: number };
  onPoiSelected: (poi: PoiSearchResult) => void;
}

const MapToolbar: React.FC<MapToolbarProps> = ({
  mapMode,
  setMapMode,
  showAnnotations,
  setShowAnnotations,
  showTrack,
  setShowTrack,
  showSurfaces,
  setShowSurfaces,
  showEnvelope,
  setShowEnvelope,
  showAirspaces,
  setShowAirspaces,
  hasTrackResult,
  getSearchContext,
  onPoiSelected,
}) => {
  const baseMapType = useMapSettingsStore((state) => state.baseMapType);
  const tiandituKey = useMapSettingsStore((state) => state.tiandituKey);
  const setBaseMapType = useMapSettingsStore((state) => state.setBaseMapType);
  const configError = useMapSettingsStore((state) => state.configError);
  const [settingsOpen, setSettingsOpen] = React.useState(false);

  return (
    <>
      <Box
        onClick={stopToolbarEvent}
        onDoubleClick={stopToolbarEvent}
        onMouseDown={stopToolbarEvent}
        sx={{
          position: 'absolute',
          top: 12,
          right: 12,
          zIndex: 1000,
          px: 1,
          py: 0.75,
          bgcolor: 'rgba(255, 255, 255, 0.94)',
          borderRadius: 1.5,
          boxShadow: '0 1px 8px rgba(15, 23, 42, 0.2)',
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          flexWrap: 'wrap',
          justifyContent: 'flex-end',
          maxWidth: 'calc(100% - 24px)',
        }}
      >
        <Stack direction="row" spacing={1}>
          <Button
            size="small"
            variant={mapMode === '2d' ? 'contained' : 'outlined'}
            onClick={() => setMapMode('2d')}
          >
            二维地图
          </Button>
          <Button
            size="small"
            variant={mapMode === '3d' ? 'contained' : 'outlined'}
            onClick={() => setMapMode('3d')}
          >
            三维场景
          </Button>
        </Stack>

        {mapMode === '2d' && (
          <>
            <FormControl size="small" sx={{ minWidth: 140, bgcolor: 'white' }}>
              <Select
                value={baseMapType}
                onChange={(event) => setBaseMapType(event.target.value as BaseMapType)}
              >
                {BASE_MAP_TYPES.map((type) => (
                  <MenuItem key={type} value={type} disabled={type !== 'osm' && !tiandituKey}>
                    {BASE_MAP_LABELS[type]}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button size="small" variant="outlined" onClick={() => setSettingsOpen(true)}>
              天地图设置
            </Button>
            <PoiSearchControl
              disabled={mapMode !== '2d'}
              getSearchContext={getSearchContext}
              onPoiSelected={onPoiSelected}
            />
            {hasTrackResult && (
              <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap' }}>
                <FormControlLabel
                  control={
                    <Switch
                      checked={showTrack}
                      onChange={(event) => setShowTrack(event.target.checked)}
                      size="small"
                    />
                  }
                  label="五边航线"
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={showSurfaces}
                      onChange={(event) => setShowSurfaces(event.target.checked)}
                      size="small"
                    />
                  }
                  label="限制面"
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={showEnvelope}
                      onChange={(event) => setShowEnvelope(event.target.checked)}
                      size="small"
                    />
                  }
                  label="双向包络"
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={showAirspaces}
                      onChange={(event) => setShowAirspaces(event.target.checked)}
                      size="small"
                    />
                  }
                  label="营地空域"
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={
                    <Switch
                      checked={showAnnotations}
                      onChange={(event) => setShowAnnotations(event.target.checked)}
                      size="small"
                    />
                  }
                  label="程序标注"
                  sx={{ m: 0 }}
                />
              </Stack>
            )}
          </>
        )}

        {configError && mapMode === '2d' && (
          <Typography variant="caption" color="warning.main">
            地图配置接口不可用，已使用本地配置
          </Typography>
        )}
      </Box>
      <MapSettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
};

const MapView: React.FC<MapViewProps> = ({ center, zoom }) => {
  const { runwayParams } = useRunwayStore();
  const trackResult = useTrackStore((state) => state.trackResult);
  const { analysisMode } = useHelipadStore();
  const tiandituKey = useMapSettingsStore((state) => state.tiandituKey);
  const initializeMapSettings = useMapSettingsStore((state) => state.initialize);
  const [showAnnotations, setShowAnnotations] = React.useState(true);
  const [showTrack, setShowTrack] = React.useState(true);
  const [showSurfaces, setShowSurfaces] = React.useState(true);
  const [showEnvelope, setShowEnvelope] = React.useState(true);
  const [showAirspaces, setShowAirspaces] = React.useState(true);
  const [mapMode, setMapMode] = React.useState<MapMode>('2d');
  const [useAnalyticView, setUseAnalyticView] = React.useState(false);
  const [selectedPoi, setSelectedPoi] = React.useState<PoiSearchResult | null>(null);
  const mapRef = React.useRef<L.Map | null>(null);
  const isHelipadMode = analysisMode === 'helipad';

  React.useEffect(() => {
    void initializeMapSettings();
  }, [initializeMapSettings]);

  const handleMapReady = React.useCallback((map: L.Map | null) => {
    mapRef.current = map;
  }, []);

  const getSearchContext = React.useCallback(() => {
    const map = mapRef.current;
    if (map) {
      const bounds = map.getBounds();
      return {
        bounds: {
          west: bounds.getWest(),
          south: bounds.getSouth(),
          east: bounds.getEast(),
          north: bounds.getNorth(),
        },
        zoom: map.getZoom(),
      };
    }

    return {
      bounds: boundsAroundCoordinate(
        runwayParams?.coordinate ?? { latitude: center[0], longitude: center[1] }
      ),
      zoom,
    };
  }, [center, runwayParams?.coordinate, zoom]);

  return (
    <Box sx={{ position: 'relative', height: '100%', width: '100%' }}>
      <Box sx={{ display: mapMode === '2d' ? 'block' : 'none', height: '100%', width: '100%' }}>
        <MapContainer
          center={center}
          zoom={zoom}
          style={{ height: '100%', width: '100%' }}
          className="z-0"
        >
          <BaseMapLayer />

          <MapCenterUpdater center={center} />
          <MapInstanceBridge onReady={handleMapReady} />
          <MapVisibilityUpdater visible={mapMode === '2d'} />
          <RunwayClickSelector />

          {runwayParams && !isHelipadMode && (
            <RunwayMarker
              position={[runwayParams.coordinate.latitude, runwayParams.coordinate.longitude]}
              bearing={runwayParams.magneticBearing}
              length={runwayParams.length}
            />
          )}

          {trackResult && !isHelipadMode && (
            <TrackLayer
              result={trackResult}
              showAnnotations={showAnnotations}
              showTrack={showTrack}
              showSurfaces={showSurfaces}
              showEnvelope={showEnvelope}
              showAirspaces={showAirspaces}
            />
          )}

          {isHelipadMode && <HelipadLayer />}

          <PoiMarkerLayer poi={selectedPoi} />
        </MapContainer>
      </Box>

      <Box sx={{ display: mapMode === '3d' ? 'block' : 'none', height: '100%', width: '100%', position: 'relative' }}>
        {isHelipadMode ? (
          <>
            {/* 3D view type toggle for helipad */}
            <Box sx={{ position: 'absolute', top: 8, left: 8, zIndex: 1000, display: 'flex', gap: 0.5 }}>
              <Button
                variant={useAnalyticView ? 'outlined' : 'contained'}
                size="small"
                onClick={() => setUseAnalyticView(false)}
                sx={{ fontSize: 11 }}
              >
                卫星地形
              </Button>
              <Button
                variant={useAnalyticView ? 'contained' : 'outlined'}
                size="small"
                onClick={() => setUseAnalyticView(true)}
                sx={{ fontSize: 11 }}
              >
                分析空域
              </Button>
            </Box>
            {useAnalyticView ? (
              <Enhanced3DView enabled={mapMode === '3d'} />
            ) : (
              <MapLibre3DView mode="helipad" enabled={mapMode === '3d'} tiandituKey={tiandituKey} />
            )}
          </>
        ) : runwayParams ? (
          <Map3DView runwayParams={runwayParams} trackResult={trackResult} enabled={mapMode === '3d'} />
        ) : (
          <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Alert severity="info">请先配置跑道参数</Alert>
          </Box>
        )}
      </Box>

      <MapToolbar
        mapMode={mapMode}
        setMapMode={setMapMode}
        showAnnotations={showAnnotations}
        setShowAnnotations={setShowAnnotations}
        showTrack={showTrack}
        setShowTrack={setShowTrack}
        showSurfaces={showSurfaces}
        setShowSurfaces={setShowSurfaces}
        showEnvelope={showEnvelope}
        setShowEnvelope={setShowEnvelope}
        showAirspaces={showAirspaces}
        setShowAirspaces={setShowAirspaces}
        hasTrackResult={Boolean(trackResult)}
        getSearchContext={getSearchContext}
        onPoiSelected={setSelectedPoi}
      />
    </Box>
  );
};

export default MapView;
