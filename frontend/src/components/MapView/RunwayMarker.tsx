/**
 * RunwayMarker Component - Renders runway visualization on map
 * 跑道标记组件 - 在地图上可视化跑道
 */
import React from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';

interface RunwayMarkerProps {
  /** Runway center position [latitude, longitude] */
  position: [number, number];
  /** Magnetic bearing in degrees */
  bearing: number;
  /** Runway length in meters */
  length: number;
}

/**
 * Calculate runway endpoints from center, bearing, and length
 */
function calculateRunwayEndpoints(
  center: [number, number],
  bearing: number,
  length: number
): { threshold1: [number, number]; threshold2: [number, number] } {
  // Earth radius in meters
  const R = 6378137;
  
  // Convert to radians
  const lat1 = (center[0] * Math.PI) / 180;
  const lon1 = (center[1] * Math.PI) / 180;
  const brng1 = (bearing * Math.PI) / 180;
  const brng2 = ((bearing + 180) % 360 * Math.PI) / 180;
  
  // Half length
  const halfLength = length / 2;
  
  // Angular distance
  const d = halfLength / R;
  
  // Calculate threshold 1 (bearing direction)
  const lat2_1 = Math.asin(
    Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brng1)
  );
  const lon2_1 =
    lon1 +
    Math.atan2(
      Math.sin(brng1) * Math.sin(d) * Math.cos(lat1),
      Math.cos(d) - Math.sin(lat1) * Math.sin(lat2_1)
    );
  
  // Calculate threshold 2 (opposite direction)
  const lat2_2 = Math.asin(
    Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brng2)
  );
  const lon2_2 =
    lon1 +
    Math.atan2(
      Math.sin(brng2) * Math.sin(d) * Math.cos(lat1),
      Math.cos(d) - Math.sin(lat1) * Math.sin(lat2_2)
    );
  
  return {
    threshold1: [(lat2_1 * 180) / Math.PI, ((lon2_1 * 180) / Math.PI + 540) % 360 - 180],
    threshold2: [(lat2_2 * 180) / Math.PI, ((lon2_2 * 180) / Math.PI + 540) % 360 - 180],
  };
}

/**
 * RunwayMarker Component
 * Renders runway as a line with direction indicator
 */
const RunwayMarker: React.FC<RunwayMarkerProps> = ({ position, bearing, length }) => {
  const map = useMap();
  
  React.useEffect(() => {
    // Calculate runway endpoints
    const endpoints = calculateRunwayEndpoints(position, bearing, length);
    
    // Create runway line
    const runwayLine = L.polyline(
      [
        new L.LatLng(endpoints.threshold1[0], endpoints.threshold1[1]),
        new L.LatLng(endpoints.threshold2[0], endpoints.threshold2[1]),
      ],
      {
        color: '#333',
        weight: 4,
        opacity: 1,
      }
    );
    
    runwayLine.bindTooltip(`跑道\n方向: ${bearing.toFixed(0)}°\n长度: ${length}m`, {
      permanent: false,
    });
    
    runwayLine.addTo(map);
    
    // Create runway center marker
    const centerMarker = L.marker(new L.LatLng(position[0], position[1]), {
      icon: L.divIcon({
        className: 'runway-center-marker',
        html: `<div style="background: #1976d2; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;">跑道中心 ${bearing.toFixed(0)}°/${((bearing + 180) % 360).toFixed(0)}°</div>`,
        iconSize: [120, 24],
        iconAnchor: [60, 12],
      }),
    });
    
    centerMarker.addTo(map);
    
    // Create direction arrow indicator
    // Arrow pointing in bearing direction
    const arrowPosition = endpoints.threshold1;
    const arrowIcon = L.divIcon({
      className: 'runway-direction-arrow',
      html: `<div style="transform: rotate(${bearing}deg); font-size: 24px; color: #1976d2;">➤</div>`,
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    });
    
    const arrowMarker = L.marker(new L.LatLng(arrowPosition[0], arrowPosition[1]), {
      icon: arrowIcon,
    });
    
    arrowMarker.addTo(map);
    
    // Cleanup on unmount
    return () => {
      runwayLine.remove();
      centerMarker.remove();
      arrowMarker.remove();
    };
  }, [map, position, bearing, length]);
  
  return null;
};

export default RunwayMarker;