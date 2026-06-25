import React from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import {
  GeometryOverlay,
  ProcedureAnnotation,
  ProcedureAnnotationStyleKey,
  TrackResult,
  TrackSegment,
  TRACK_COLORS,
} from '../../types/track';

interface TrackLayerProps {
  result: TrackResult;
  showAnnotations?: boolean;
  showKeyPoints?: boolean;
  showTrack?: boolean;
  showSurfaces?: boolean;
  showEnvelope?: boolean;
  showAirspaces?: boolean;
}

interface OverlayStyle {
  color: string;
  fillColor: string;
  fillOpacity: number;
  weight: number;
  opacity: number;
  dashArray?: string;
}

const OVERLAY_STYLES: Record<string, OverlayStyle> = {
  airspace: {
    color: '#dc2626',
    fillColor: '#dc2626',
    fillOpacity: 0.04,
    weight: 2,
    opacity: 0.9,
  },
  'runway-surface': {
    color: '#334155',
    fillColor: '#64748b',
    fillOpacity: 0.14,
    weight: 1,
    opacity: 0.8,
  },
  'runway-area': {
    color: '#1e293b',
    fillColor: '#475569',
    fillOpacity: 0.55,
    weight: 2,
    opacity: 0.95,
  },
  'obstacle-envelope': {
    color: '#6b7280',
    fillColor: '#6b7280',
    fillOpacity: 0.03,
    weight: 2,
    opacity: 0.85,
    dashArray: '8 6',
  },
  'ols-envelope': {
    color: '#6b7280',
    fillColor: '#6b7280',
    fillOpacity: 0.025,
    weight: 2,
    opacity: 0.85,
    dashArray: '10 7',
  },
  'ols-approach': {
    color: '#0284c7',
    fillColor: '#38bdf8',
    fillOpacity: 0.12,
    weight: 2,
    opacity: 0.9,
    dashArray: '6 4',
  },
  'ols-approach-second': {
    color: '#0369a1',
    fillColor: '#7dd3fc',
    fillOpacity: 0.08,
    weight: 2,
    opacity: 0.75,
    dashArray: '4 6',
  },
  'ols-approach-horizontal': {
    color: '#075985',
    fillColor: '#bae6fd',
    fillOpacity: 0.05,
    weight: 1,
    opacity: 0.6,
    dashArray: '3 8',
  },
  'ols-takeoff-climb': {
    color: '#16a34a',
    fillColor: '#22c55e',
    fillOpacity: 0.1,
    weight: 2,
    opacity: 0.9,
    dashArray: '6 4',
  },
  'ols-transitional': {
    color: '#f97316',
    fillColor: '#fb923c',
    fillOpacity: 0.15,
    weight: 2,
    opacity: 0.85,
    dashArray: '5 5',
  },
  'ols-approach-ih-intersection': {
    color: '#e11d48',
    fillColor: '#e11d48',
    fillOpacity: 0,
    weight: 3.5,
    opacity: 0.95,
    dashArray: '8 3',
  },
  'ols-inner-transitional': {
    color: '#ea580c',
    fillColor: '#fdba74',
    fillOpacity: 0.10,
    weight: 1,
    opacity: 0.7,
    dashArray: '3 4',
  },
  'ols-inner-horizontal': {
    color: '#7c3aed',
    fillColor: '#a78bfa',
    fillOpacity: 0.07,
    weight: 2.5,
    opacity: 0.8,
  },
  'ols-conical': {
    color: '#9333ea',
    fillColor: '#c084fc',
    fillOpacity: 0.12,
    weight: 2.5,
    opacity: 0.85,
    dashArray: '12 6',
  },
  'ols-conical-inner-edge': {
    color: '#a855f7',
    fillColor: '#a855f7',
    fillOpacity: 0,
    weight: 2.5,
    opacity: 0.8,
    dashArray: '8 4',
  },
  'ols-inner-approach': {
    color: '#0d9488',
    fillColor: '#5eead4',
    fillOpacity: 0.1,
    weight: 2,
    opacity: 0.85,
    dashArray: '4 3',
  },
  'ols-balked-landing': {
    color: '#b91c1c',
    fillColor: '#fca5a5',
    fillOpacity: 0.08,
    weight: 2,
    opacity: 0.8,
    dashArray: '6 3',
  },
  'flight-camp-airspace': {
    color: '#0f766e',
    fillColor: '#14b8a6',
    fillOpacity: 0.045,
    weight: 2,
    opacity: 0.9,
  },
  'flight-camp-clearance': {
    color: '#ca8a04',
    fillColor: '#facc15',
    fillOpacity: 0.04,
    weight: 1,
    opacity: 0.85,
    dashArray: '4 4',
  },
  'flight-camp-special-airspace': {
    color: '#0891b2',
    fillColor: '#67e8f9',
    fillOpacity: 0.035,
    weight: 2,
    opacity: 0.75,
    dashArray: '14 8',
  },
  'approach-surface': {
    color: '#0284c7',
    fillColor: '#38bdf8',
    fillOpacity: 0.12,
    weight: 2,
    opacity: 0.9,
    dashArray: '6 4',
  },
  'takeoff-surface': {
    color: '#16a34a',
    fillColor: '#22c55e',
    fillOpacity: 0.1,
    weight: 2,
    opacity: 0.9,
    dashArray: '6 4',
  },
  default: {
    color: '#2563eb',
    fillColor: '#2563eb',
    fillOpacity: 0.12,
    weight: 2,
    opacity: 0.85,
  },
};

const ANNOTATION_CLASS_NAMES: Record<ProcedureAnnotationStyleKey, string> = {
  'segment-label': 'procedure-annotation procedure-annotation-segment',
  'point-label': 'procedure-annotation procedure-annotation-point',
  'performance-label': 'procedure-annotation procedure-annotation-performance',
  'turn-label': 'procedure-annotation procedure-annotation-turn',
};

const toLatLngs = (overlay: GeometryOverlay): L.LatLng[] =>
  overlay.coordinates.map((point) => new L.LatLng(point.latitude, point.longitude));

const segmentCoordinates = (segment: TrackSegment): L.LatLng[] => {
  if (segment.pathPoints && segment.pathPoints.length > 0) {
    return segment.pathPoints.map((point) => new L.LatLng(point.latitude, point.longitude));
  }

  return [
    new L.LatLng(segment.startPoint.latitude, segment.startPoint.longitude),
    new L.LatLng(segment.endPoint.latitude, segment.endPoint.longitude),
  ];
};

const formatVerticalAngle = (angle: number): string => {
  if (angle > 0) {
    return `爬升角 +${angle.toFixed(1)}°`;
  }
  if (angle < 0) {
    return `下降角 ${angle.toFixed(1)}°`;
  }
  return '平飞 0.0°';
};

const buildDonutPolygon = (
  overlay: GeometryOverlay,
  style: OverlayStyle
): L.Polygon | null => {
  const outerRing = toLatLngs(overlay);
  if (outerRing.length < 3) return null;

  const holeRings: L.LatLng[][] | undefined = overlay.metadata?.holeRings
    ? (overlay.metadata.holeRings as Array<Array<{ lat: number; lng: number }>>).map(
        (ring) => ring.map((p) => new L.LatLng(p.lat, p.lng))
      )
    : undefined;

  const latLngs: L.LatLng[][] | L.LatLng[] = holeRings ? [outerRing, ...holeRings] : outerRing;

  return L.polygon(latLngs, {
    color: style.color,
    fillColor: style.fillColor,
    fillOpacity: style.fillOpacity,
    weight: style.weight,
    opacity: style.opacity,
    dashArray: style.dashArray,
    className: 'procedure-surface',
  }).bindTooltip(overlay.label, { sticky: true });
};

const addOverlay = (layerGroup: L.LayerGroup, overlay: GeometryOverlay) => {
  const style = OVERLAY_STYLES[overlay.styleKey] ?? OVERLAY_STYLES.default;

  if (overlay.kind === 'polygon') {
    const hasHoles = !!overlay.metadata?.holeRings;
    const polygon = hasHoles
      ? buildDonutPolygon(overlay, style)
      : (() => {
          const points = toLatLngs(overlay);
          if (points.length < 3) return null;
          return L.polygon(points, {
            color: style.color,
            fillColor: style.fillColor,
            fillOpacity: style.fillOpacity,
            weight: style.weight,
            opacity: style.opacity,
            dashArray: style.dashArray,
            className: 'procedure-surface',
          }).bindTooltip(overlay.label, { sticky: true });
        })();

    if (polygon) polygon.addTo(layerGroup);
    return;
  }

  if (overlay.kind === 'polyline' || overlay.kind === 'arc') {
    const points = toLatLngs(overlay);
    const styleKey = overlay.styleKey;

    if (styleKey === 'runway-centerline') {
      L.polyline(points, {
        color: '#ef4444',
        weight: 3,
        opacity: 0.9,
        dashArray: '8 4',
        className: 'procedure-line',
      })
        .bindTooltip(overlay.label, { sticky: true })
        .addTo(layerGroup);
      return;
    }

    if (points.length >= 2) {
      L.polyline(points, {
        color: style.color,
        weight: style.weight,
        opacity: style.opacity,
        dashArray: style.dashArray,
        className: 'procedure-line',
      })
        .bindTooltip(overlay.label, { sticky: true })
        .addTo(layerGroup);
    }
    return;
  }

  if (overlay.kind === 'marker') {
    const points = toLatLngs(overlay);
    if (points.length === 0) return;

    const marker = L.circleMarker(points[0], {
      radius: overlay.styleKey === 'threshold' ? 7 : 5,
      color: '#ffffff',
      weight: 2,
      fillColor: overlay.styleKey === 'threshold' ? '#dc2626' : '#0f766e',
      fillOpacity: 0.95,
    });
    marker.bindTooltip(
      `${overlay.label}${overlay.altitude !== null && overlay.altitude !== undefined ? `\n高度: ${overlay.altitude.toFixed(1)}m` : ''}`,
      { sticky: true }
    );
    marker.addTo(layerGroup);

    L.marker(points[0], {
      icon: L.divIcon({
        className: 'track-marker-label',
        html: `<span>${overlay.label}</span>`,
        iconSize: [90, 22],
        iconAnchor: [45, -8],
      }),
      interactive: false,
    }).addTo(layerGroup);
  }
};

const escapeHtml = (value: string): string =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');

const addAnnotation = (layerGroup: L.LayerGroup, annotation: ProcedureAnnotation) => {
  const className =
    ANNOTATION_CLASS_NAMES[annotation.styleKey] ?? 'procedure-annotation';
  const html = `
    <div class="${className}">
      <div class="procedure-annotation-title">${escapeHtml(annotation.label)}</div>
      ${annotation.lines.map((line) => `<div>${escapeHtml(line)}</div>`).join('')}
    </div>
  `;

  L.marker([annotation.coordinate.latitude, annotation.coordinate.longitude], {
    icon: L.divIcon({
      className: 'procedure-annotation-anchor',
      html,
      iconSize: [150, 76],
      iconAnchor: [75, 38],
    }),
    interactive: false,
  }).addTo(layerGroup);
};

const TrackLayer: React.FC<TrackLayerProps> = ({
  result,
  showAnnotations = true,
  showKeyPoints = true,
  showTrack = true,
  showSurfaces = true,
  showEnvelope = true,
  showAirspaces = true,
}) => {
  const map = useMap();

  React.useEffect(() => {
    const layerGroup = L.layerGroup();

    if (showAirspaces) {
      result.airspaces?.forEach((airspace) => addOverlay(layerGroup, airspace));
    }

    if (showSurfaces || showEnvelope) {
      result.surfaces
        .filter((surface) => {
          const isEnvelope =
            surface.styleKey === 'obstacle-envelope' || surface.styleKey === 'ols-envelope';
          // Threshold midpoint markers are controlled by showKeyPoints instead
          if (surface.styleKey === 'threshold') return false;
          return isEnvelope ? showEnvelope : showSurfaces;
        })
        .forEach((surface) => addOverlay(layerGroup, surface));
    }

    if (showTrack) {
      result.segments.forEach((segment) => {
        const color = TRACK_COLORS[segment.name];
        const line = L.polyline(segmentCoordinates(segment), {
          color,
          weight: 4,
          opacity: 0.9,
          className: 'track-path',
        });

        line.bindTooltip(
          `${segment.nameCN}\n距离: ${segment.distance.toFixed(0)}m\n航向: ${segment.heading.toFixed(0)}°\n高度: ${segment.altitude.toFixed(1)}m\n${formatVerticalAngle(segment.verticalAngle)}`,
          { sticky: true }
        );
        layerGroup.addLayer(line);
      });
    }

    if (showKeyPoints) {
      result.keyPoints.forEach((point) => addOverlay(layerGroup, point));
      result.surfaces
        .filter((surface) => surface.styleKey === 'threshold')
        .forEach((surface) => addOverlay(layerGroup, surface));
    }

    if (showAnnotations) {
      result.annotations.forEach((annotation) => addAnnotation(layerGroup, annotation));
    }

    layerGroup.addTo(map);

    return () => {
      layerGroup.remove();
    };
  }, [map, result, showAnnotations, showKeyPoints, showAirspaces, showEnvelope, showSurfaces, showTrack]);

  return null;
};

export default TrackLayer;
