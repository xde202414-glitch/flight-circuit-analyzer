/**
 * Shared satellite-tile helpers for 3D views.
 *
 * Fetches 天地图 WMTS img_w tiles at a given zoom level and stitches them
 * into a single CanvasTexture suitable for terrain or ground-plane materials.
 */
import * as THREE from 'three';

const SATELLITE_ZOOM = 15;
const TILE_SIZE = 256;

// ---------------------------------------------------------------------------
// Mercator helpers
// ---------------------------------------------------------------------------
export function lonToTileX(lon: number, z: number): number {
  return ((lon + 180) / 360) * Math.pow(2, z);
}
export function latToTileY(lat: number, z: number): number {
  const rad = (lat * Math.PI) / 180;
  return ((1 - Math.asinh(Math.tan(rad)) / Math.PI) / 2) * Math.pow(2, z);
}

// ---------------------------------------------------------------------------
// Tile rect
// ---------------------------------------------------------------------------
export interface TileRect {
  minX: number; maxX: number;
  minY: number; maxY: number;
  zoom: number;
}

export function computeTileRect(
  bounds: { north: number; south: number; west: number; east: number },
  zoom: number = SATELLITE_ZOOM,
): TileRect {
  const minX = Math.floor(lonToTileX(bounds.west, zoom));
  const maxX = Math.floor(lonToTileX(bounds.east, zoom));
  const minY = Math.floor(latToTileY(bounds.north, zoom));
  const maxY = Math.floor(latToTileY(bounds.south, zoom));
  return { minX, maxX, minY, maxY, zoom };
}

// ---------------------------------------------------------------------------
// Tile fetching
// ---------------------------------------------------------------------------
async function fetchSatelliteTile(
  tx: number, ty: number, zoom: number, tk: string,
): Promise<HTMLImageElement | null> {
  const sub = ['0', '1', '2', '3'][(tx + ty) % 4];
  const url =
    `https://t${sub}.tianditu.gov.cn/img_w/wmts?` +
    `SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0` +
    `&LAYER=img&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles` +
    `&TILEMATRIX=${zoom}&TILEROW=${ty}&TILECOL=${tx}&tk=${tk}`;
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

// ---------------------------------------------------------------------------
// Stitch tiles into a canvas texture
// ---------------------------------------------------------------------------
export async function buildSatelliteTexture(
  bounds: { north: number; south: number; west: number; east: number },
  tk: string,
): Promise<THREE.CanvasTexture | null> {
  const rect = computeTileRect(bounds, SATELLITE_ZOOM);
  const cols = rect.maxX - rect.minX + 1;
  const rows = rect.maxY - rect.minY + 1;
  if (cols <= 0 || rows <= 0 || cols > 6 || rows > 6) return null;

  const tiles: (HTMLImageElement | null)[][] = [];
  for (let row = 0; row < rows; row++) {
    tiles[row] = [];
    for (let col = 0; col < cols; col++) {
      tiles[row][col] = await fetchSatelliteTile(
        rect.minX + col, rect.minY + row, rect.zoom, tk,
      );
    }
  }

  const loaded = tiles.flat().filter(Boolean).length;
  if (loaded === 0) return null;

  const canvas = document.createElement('canvas');
  canvas.width = cols * TILE_SIZE;
  canvas.height = rows * TILE_SIZE;
  const ctx = canvas.getContext('2d')!;

  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const img = tiles[row][col];
      if (img) {
        ctx.drawImage(img, col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE);
      }
    }
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.generateMipmaps = true;
  return texture;
}

/** Compute UV for a geographic point within the tile rect. */
export function geoToUV(
  lat: number, lon: number,
  rect: TileRect,
): [number, number] {
  const tx = lonToTileX(lon, rect.zoom);
  const ty = latToTileY(lat, rect.zoom);
  const u = (tx - rect.minX) / (rect.maxX - rect.minX + 1);
  const v = (ty - rect.minY) / (rect.maxY - rect.minY + 1);
  return [u, v];
}
