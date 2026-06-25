import React from 'react';
import { TileLayer } from 'react-leaflet';
import { useMapSettingsStore } from '../../store/useMapSettingsStore';
import type { BaseMapType } from '../../types/map';

const TIANDITU_SUBDOMAINS = ['0', '1', '2', '3', '4', '5', '6', '7'];

function getTiandituWMTSUrl(endpoint: string, apiKey: string): string {
  const layerName = endpoint.replace('_w', '');
  return (
    `https://t{s}.tianditu.gov.cn/${endpoint}/wmts?` +
    `SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layerName}` +
    `&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}` +
    `&TILEROW={y}&TILECOL={x}&tk=${apiKey}`
  );
}

const BaseMapLayer: React.FC = () => {
  const baseMapType = useMapSettingsStore((state) => state.baseMapType);
  const tiandituKey = useMapSettingsStore((state) => state.tiandituKey);
  const effectiveBaseMap: BaseMapType =
    tiandituKey ? (baseMapType !== 'osm' ? baseMapType : 'tianditu-vector') : 'osm';

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

export default BaseMapLayer;
