import React from 'react';

const IotLayoutPage: React.FC = () => (
  <div className="module-layout two-col">
    <div className="module-panel">
      <div className="module-panel-header">🔗 智联网布局</div>
      <div className="empty-state" style={{ padding: '80px 20px' }}>
        <div className="empty-state-icon">🔗</div>
        <div className="empty-state-text" style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>
          智联网布局模块
        </div>
        <div className="empty-state-text">该模块预留用于未来物联网设备布局规划功能</div>
      </div>
    </div>
    <div className="module-map-panel" />
  </div>
);

export default IotLayoutPage;
