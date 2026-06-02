import React from 'react';
import { Circle, Marker, Polygon, Popup, Tooltip, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Stack, Typography } from '@mui/material';
import { useHelipadStore } from '../../store/useHelipadStore';
import type { Coordinate } from '../../types/runway';

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------

const helipadIcon = L.divIcon({
  className: 'helipad-marker-icon',
  html: '<div style="background:#0066ff;color:white;border-radius:50%;width:32px;height:32px;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:bold;border:2px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.3);">H</div>',
  iconSize: [32, 32],
  iconAnchor: [16, 16],
});

const buildingIcon = L.divIcon({
  className: 'building-marker-icon',
  html: '<div style="background:#f97316;color:white;border-radius:4px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:14px;border:1px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.3);">🏢</div>',
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

// ---------------------------------------------------------------------------
// Coordinate helpers
// ---------------------------------------------------------------------------

function toLatLng(c: Coordinate): [number, number] {
  return [c.latitude, c.longitude];
}

function toLatLngArray(points: Coordinate[]): [number, number][] {
  return points.map(toLatLng);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/** A click-handling bridge that hooks into useMapEvents */
const HelipadClickHandler: React.FC = () => {
  const map = useMap();
  const { helipadCenter, setHelipadCenter, clearHelipad } = useHelipadStore();

  React.useEffect(() => {
    const handler = (e: L.LeafletMouseEvent) => {
      // Skip if clicking on UI elements
      const target = e.originalEvent.target as HTMLElement | null;
      if (target?.closest('.leaflet-control, .leaflet-popup, .helipad-marker-icon')) {
        return;
      }

      if (helipadCenter) {
        // Ask to clear existing helipad
        if (window.confirm('已存在起降场配置，是否清除并重新选点？')) {
          clearHelipad();
          setHelipadCenter({
            latitude: Number(e.latlng.lat.toFixed(6)),
            longitude: Number(e.latlng.lng.toFixed(6)),
          });
        }
      } else {
        setHelipadCenter({
          latitude: Number(e.latlng.lat.toFixed(6)),
          longitude: Number(e.latlng.lng.toFixed(6)),
        });
      }
    };

    map.on('click', handler);
    return () => {
      map.off('click', handler);
    };
  }, [map, helipadCenter, setHelipadCenter, clearHelipad]);

  return null;
};

/**
 * Renders helipad/FATO analysis layers on the Leaflet map.
 */
const HelipadLayer: React.FC = () => {
  const {
    helipadCenter,
    fatoRegion,
    approachPolygon,
    takeoffPolygon,
    fatoPolygon,
    fatoCircles,
    buildingResults,
    terrainExceedances,
    fatoConfig,
  } = useHelipadStore();

  return (
    <>
      <HelipadClickHandler />

      {/* ----- Helipad centre marker ----- */}
      {helipadCenter && (
        <Marker position={[helipadCenter.latitude, helipadCenter.longitude]} icon={helipadIcon}>
          <Popup>
            <Typography variant="subtitle2">起降场中心</Typography>
            <Typography variant="caption" display="block">
              纬度: {helipadCenter.latitude.toFixed(6)}
            </Typography>
            <Typography variant="caption" display="block">
              经度: {helipadCenter.longitude.toFixed(6)}
            </Typography>
          </Popup>
          <Tooltip direction="top" offset={[0, -20]} permanent={Boolean(fatoRegion)}>
            <span style={{ fontSize: 12, background: '#fff', padding: '2px 6px', borderRadius: 4 }}>
              起降场中心
            </span>
          </Tooltip>
        </Marker>
      )}

      {/* ----- FATO region (circle mode) ----- */}
      {fatoCircles && fatoCircles.length > 0 && fatoConfig?.shape === 'circle' && (
        <>
          {/* FATO circle */}
          <Circle
            center={[fatoCircles[0].latitude, fatoCircles[0].longitude]}
            radius={fatoCircles[0].radius}
            pathOptions={{ color: '#0066ff', fillColor: '#0066ff', fillOpacity: 0.2, weight: 2 }}
          >
            <Tooltip>FATO (半径 {fatoCircles[0].radius.toFixed(1)}m)</Tooltip>
          </Circle>
          {/* Safety area circle */}
          {fatoCircles.length > 1 && (
            <Circle
              center={[fatoCircles[1].latitude, fatoCircles[1].longitude]}
              radius={fatoCircles[1].radius}
              pathOptions={{ color: '#ffcc00', fillColor: '#ffcc00', fillOpacity: 0.2, weight: 2 }}
            >
              <Tooltip>安全区 (半径 {fatoCircles[1].radius.toFixed(1)}m)</Tooltip>
            </Circle>
          )}
        </>
      )}

      {/* ----- FATO region (square mode) ----- */}
      {fatoPolygon && fatoPolygon.length >= 3 && fatoConfig?.shape === 'square' && (
        <Polygon
          positions={toLatLngArray(fatoPolygon)}
          pathOptions={{ color: '#0066ff', fillColor: '#0066ff', fillOpacity: 0.2, weight: 2 }}
        >
          <Tooltip>FATO (正方形)</Tooltip>
        </Polygon>
      )}

      {/* ----- Approach surface polygon ----- */}
      {approachPolygon && approachPolygon.length >= 3 && (
        <Polygon
          positions={toLatLngArray(approachPolygon)}
          pathOptions={{ color: '#1677ff', fillColor: '#1677ff', fillOpacity: 0.13, weight: 2 }}
        >
          <Tooltip>进近面</Tooltip>
        </Polygon>
      )}

      {/* ----- Takeoff surface polygon ----- */}
      {takeoffPolygon && takeoffPolygon.length >= 3 && (
        <Polygon
          positions={toLatLngArray(takeoffPolygon)}
          pathOptions={{ color: '#13a8a8', fillColor: '#13a8a8', fillOpacity: 0.13, weight: 2 }}
        >
          <Tooltip>起飞爬升面</Tooltip>
        </Polygon>
      )}

      {/* ----- Building markers ----- */}
      {buildingResults.map((b) => (
        <Marker
          key={b.id}
          position={[b.latitude, b.longitude]}
          icon={buildingIcon}
        >
          <Popup>
            <Stack spacing={0.5} sx={{ minWidth: 200 }}>
              <Typography variant="subtitle2">{b.name}</Typography>
              {b.category && (
                <Typography variant="caption" color="text.secondary">
                  类别: {b.category}
                </Typography>
              )}
              {b.address && (
                <Typography variant="caption" color="text.secondary">
                  地址: {b.address}
                </Typography>
              )}
              {b.height != null && (
                <Typography variant="caption" color="text.secondary">
                  高度: {b.height} m
                </Typography>
              )}
              {b.levels != null && (
                <Typography variant="caption" color="text.secondary">
                  层数: {b.levels} 层
                </Typography>
              )}
              <Typography variant="caption" color="text.secondary">
                来源: {b.source}
              </Typography>
            </Stack>
          </Popup>
        </Marker>
      ))}

      {/* ----- Terrain warning polygons ----- */}
      {terrainExceedances.map((ex, idx) => (
        <React.Fragment key={`terrain-${idx}`}>
          <Polygon
            positions={toLatLngArray(ex.cellPoints || [])}
            pathOptions={{
              color: '#dc2626',
              fillColor: '#dc2626',
              fillOpacity: 0.4,
              weight: 2,
            }}
          >
            <Tooltip>
              {ex.surfaceName}: 地面 {ex.groundElevation}m &gt; 控制 {ex.controlElevation}m (+{ex.exceedance}m)
            </Tooltip>
          </Polygon>
        </React.Fragment>
      ))}
    </>
  );
};

export default HelipadLayer;
