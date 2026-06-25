import React, { useEffect } from 'react';
import RunwayForm from '../../components/RunwayForm/RunwayForm';
import AircraftSelector from '../../components/AircraftSelector/AircraftSelector';
import MapView from '../../components/MapView/MapView';
import TrackAnalysis from '../../components/TrackAnalysis/TrackAnalysis';
import { useRunwayStore } from '../../store/useRunwayStore';
import { useHelipadStore } from '../../store/useHelipadStore';

const RunwayPage: React.FC = () => {
  const { runwayParams } = useRunwayStore();
  const setAnalysisMode = useHelipadStore((s) => s.setAnalysisMode);

  useEffect(() => {
    setAnalysisMode('runway');
  }, [setAnalysisMode]);
  const mapCenter: [number, number] = runwayParams?.coordinate
    ? [runwayParams.coordinate.latitude, runwayParams.coordinate.longitude]
    : [30.2741, 120.1551];

  return (
    <div className="module-layout">
      {/* Left Panel */}
      <div className="module-panel">
        <div className="module-panel-header">🛫 参数配置</div>
        <RunwayForm />
        <AircraftSelector />
      </div>

      {/* Center - Map */}
      <div className="module-map-panel">
        <MapView center={mapCenter} zoom={13} />
      </div>

      {/* Right Panel */}
      <div className="module-panel">
        <div className="module-panel-header">📋 航迹分析</div>
        <TrackAnalysis />
      </div>
    </div>
  );
};

export default RunwayPage;
