import React from 'react';
import { Routes, Route, NavLink, useLocation } from 'react-router-dom';
import RunwayPage from './modules/runway/RunwayPage';
import HelipadPage from './modules/helipad/HelipadPage';
import RouteManagementPage from './modules/route-management/RouteManagementPage';
import DataImportPage from './modules/data-import/DataImportPage';
import RouteAnalysisPage from './modules/route-analysis/RouteAnalysisPage';
import TakeoffFlightPage from './modules/takeoff-flight/TakeoffFlightPage';
import IotLayoutPage from './modules/iot-layout/IotLayoutPage';
import StatusBar from './components/StatusBar/StatusBar';

const NAV_ITEMS = [
  { path: '/runway', label: '跑道程序', icon: '🛫', id: 'runway' },
  { path: '/helipad', label: '起降场分析', icon: '🚁', id: 'helipad' },
  { path: '/routes', label: '航路管理', icon: '🛣️', id: 'routes' },
  { path: '/import', label: '数据导入', icon: '📥', id: 'import' },
  { path: '/analysis', label: '航路分析', icon: '📊', id: 'analysis' },
  { path: '/takeoff', label: '起降场飞行', icon: '✈️', id: 'takeoff' },
  { path: '/iot', label: '智联网布局', icon: '🔗', id: 'iot' },
];

const App: React.FC = () => {
  const location = useLocation();

  const currentNav = NAV_ITEMS.find(item =>
    location.pathname === item.path || location.pathname.startsWith(item.path + '/')
  );

  return (
    <div className="dashboard">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">✈</div>
          <span className="sidebar-logo-text">飞行程序分析系统</span>
        </div>
        <nav className="sidebar-nav">
          {NAV_ITEMS.map(item => (
            <NavLink
              key={item.id}
              to={item.path}
              className={({ isActive }) =>
                `sidebar-nav-item${isActive ? ' active' : ''}`
              }
            >
              <span className="sidebar-nav-icon">{item.icon}</span>
              <span className="sidebar-nav-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">Flight Procedure Analyzer v2.0</div>
      </aside>

      {/* Main Content */}
      <div className="main-content">
        <header className="topbar">
          <span className="topbar-breadcrumb">飞行程序分析系统</span>
          <span style={{ color: '#cbd5e1' }}>/</span>
          <span className="topbar-title">{currentNav?.label || '首页'}</span>
          <div className="topbar-spacer" />
        </header>

        <div className="page-content">
          <Routes>
            <Route path="/" element={<RunwayPage />} />
            <Route path="/runway" element={<RunwayPage />} />
            <Route path="/helipad" element={<HelipadPage />} />
            <Route path="/routes" element={<RouteManagementPage />} />
            <Route path="/import" element={<DataImportPage />} />
            <Route path="/analysis" element={<RouteAnalysisPage />} />
            <Route path="/takeoff" element={<TakeoffFlightPage />} />
            <Route path="/iot" element={<IotLayoutPage />} />
          </Routes>
        </div>
        <StatusBar />
      </div>
    </div>
  );
};

export default App;
