import React, { useEffect } from 'react';
import HelipadPanel from '../../components/HelipadAnalysis/HelipadPanel';
import MapView from '../../components/MapView/MapView';
import { useHelipadStore } from '../../store/useHelipadStore';

const HelipadPage: React.FC = () => {
  const { helipadCenter, setAnalysisMode } = useHelipadStore();

  useEffect(() => {
    setAnalysisMode('helipad');
    return () => setAnalysisMode('runway');
  }, [setAnalysisMode]);
  const mapCenter: [number, number] = helipadCenter
    ? [helipadCenter.latitude, helipadCenter.longitude]
    : [30.2741, 120.1551];

  return (
    <div className="module-layout">
      <div className="module-panel">
        <div className="module-panel-header">🚁 起降场参数配置</div>
        <HelipadPanel />
      </div>
      <div className="module-map-panel">
        <MapView center={mapCenter} zoom={13} />
      </div>
      <div className="module-panel">
        <div className="module-panel-header">📊 分析结果</div>
        <div className="empty-state">
          <div className="empty-state-icon">🚁</div>
          <div className="empty-state-text">配置参数并计算后查看起降场分析结果</div>
        </div>
      </div>
    </div>
  );
};

export default HelipadPage;
