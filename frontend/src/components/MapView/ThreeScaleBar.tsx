/**
 * Dynamic scale bar overlay for Three.js 3D views.
 *
 * Computes meters-per-pixel from the perspective camera and renders
 * a bar showing a round-number ground distance.
 */
import React from 'react';
import * as THREE from 'three';
import { SCALE_UNITS } from '../../types/map';
import type { ScaleUnit } from '../../types/map';

interface ThreeScaleBarProps {
  camera: THREE.PerspectiveCamera;
  /** DOM element the camera renders into (used to read viewport size) */
  container: HTMLElement;
  unit: ScaleUnit;
}

/** Pick a "nice" round number for the scale bar from the raw meter value. */
function niceScaleValue(rawMeters: number): number {
  const magnitudes = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000];
  for (const m of magnitudes) {
    if (rawMeters <= m) return m;
  }
  return magnitudes[magnitudes.length - 1];
}

const TARGET_BAR_PX = 120;

const ThreeScaleBar: React.FC<ThreeScaleBarProps> = ({ camera, container, unit }) => {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const rafRef = React.useRef(0);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const unitDef = SCALE_UNITS.find((u) => u.value === unit) ?? SCALE_UNITS[0];

    const draw = () => {
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (w === 0 || h === 0) {
        rafRef.current = requestAnimationFrame(draw);
        return;
      }

      // Viewport height in world units at the camera's look-at point (controls.target is at origin)
      const vFov = camera.fov * (Math.PI / 180);
      const dist = camera.position.length(); // distance to origin (0,0,0) where target is
      const worldHeight = 2 * dist * Math.tan(vFov / 2);
      const metersPerPixel = worldHeight / h;
      const rawMeters = metersPerPixel * TARGET_BAR_PX;

      const niceMeters = niceScaleValue(rawMeters);
      const barPx = niceMeters / metersPerPixel;

      // Convert to display unit
      const displayValue = niceMeters / unitDef.metersPerUnit;
      const formatted = displayValue >= 1000
        ? displayValue.toFixed(0)
        : displayValue >= 100
          ? displayValue.toFixed(0)
          : displayValue >= 10
            ? displayValue.toFixed(1)
            : displayValue.toFixed(2);
      const label = `${formatted} ${unitDef.value === 'NM' ? 'NM' : unitDef.value}`;

      // Render
      canvas.width = barPx + 20;
      canvas.height = 24;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Bar line
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(4, 6);
      ctx.lineTo(4 + barPx, 6);
      ctx.stroke();

      // End ticks
      ctx.beginPath();
      ctx.moveTo(4, 2);
      ctx.lineTo(4, 14);
      ctx.moveTo(4 + barPx, 2);
      ctx.lineTo(4 + barPx, 14);
      ctx.stroke();

      // Label
      ctx.fillStyle = '#ffffff';
      ctx.font = '11px Inter, Roboto, Helvetica, Arial, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(label, 4 + barPx / 2, 22);

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [camera, container, unit]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        bottom: 10,
        left: 10,
        zIndex: 10,
        pointerEvents: 'none',
      }}
    />
  );
};

export default ThreeScaleBar;
