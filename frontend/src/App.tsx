import React, { useEffect } from 'react';
import { Routes, Route, NavLink, useLocation, useNavigate } from 'react-router-dom';
import RunwayPage from './modules/runway/RunwayPage';
import HelipadPage from './modules/helipad/HelipadPage';
import RouteManagementPage from './modules/route-management/RouteManagementPage';
import DataImportPage from './modules/data-import/DataImportPage';
import RouteAnalysisPage from './modules/route-analysis/RouteAnalysisPage';
import TakeoffFlightPage from './modules/takeoff-flight/TakeoffFlightPage';
import IotLayoutPage from './modules/iot-layout/IotLayoutPage';
import LoginPage from './modules/auth/LoginPage';
import StatusBar from './components/StatusBar/StatusBar';
import { useAuthStore } from './store/useAuthStore';

const NAV_ITEMS = [
  { path: '/runway', label: '跑道程序', icon: '🛫', id: 'runway' },
  { path: '/helipad', label: '起降场分析', icon: '🚁', id: 'helipad' },
  { path: '/routes', label: '航路管理', icon: '🛣️', id: 'routes' },
  { path: '/import', label: '数据导入', icon: '📥', id: 'import' },
  { path: '/analysis', label: '航路分析', icon: '📊', id: 'analysis' },
  { path: '/takeoff', label: '起降场飞行', icon: '✈️', id: 'takeoff' },
  { path: '/iot', label: '智联网布局', icon: '🔗', id: 'iot' },
];

const AuthGuard: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated } = useAuthStore();
  const navigate = useNavigate();
  useEffect(() => {
    if (!isAuthenticated) navigate('/login', { replace: true });
  }, [isAuthenticated, navigate]);
  if (!isAuthenticated) return null;
  return <>{children}</>;
};

const App: React.FC = () => {
  const location = useLocation();
  const { user, logout, checkAuth } = useAuthStore();

  useEffect(() => { checkAuth(); }, [checkAuth]);

  const currentNav = NAV_ITEMS.find(item =>
    location.pathname === item.path || location.pathname.startsWith(item.path + '/')
  );

  const isLoginPage = location.pathname === '/login';

  if (isLoginPage) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    );
  }

  return (
    <div className="dashboard">
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
        <div className="sidebar-footer">
          {user && (
            <span style={{ fontSize: 11 }}>{user.username}</span>
          )}
        </div>
      </aside>

      <div className="main-content">
        <header className="topbar">
          <span className="topbar-breadcrumb">飞行程序分析系统</span>
          <span style={{ color: '#cbd5e1' }}>/</span>
          <span className="topbar-title">{currentNav?.label || '首页'}</span>
          <div className="topbar-spacer" />
          {user && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: 12, color: '#94a3b8' }}>{user.username}</span>
              <button
                onClick={logout}
                style={{
                  background: 'transparent', border: '1px solid #475569',
                  color: '#cbd5e1', borderRadius: 4, padding: '2px 10px',
                  fontSize: 12, cursor: 'pointer',
                }}
              >
                退出
              </button>
            </div>
          )}
        </header>

        <div className="page-content">
          <Routes>
            <Route path="/" element={<AuthGuard><RunwayPage /></AuthGuard>} />
            <Route path="/runway" element={<AuthGuard><RunwayPage /></AuthGuard>} />
            <Route path="/helipad" element={<AuthGuard><HelipadPage /></AuthGuard>} />
            <Route path="/routes" element={<AuthGuard><RouteManagementPage /></AuthGuard>} />
            <Route path="/import" element={<AuthGuard><DataImportPage /></AuthGuard>} />
            <Route path="/analysis" element={<AuthGuard><RouteAnalysisPage /></AuthGuard>} />
            <Route path="/takeoff" element={<AuthGuard><TakeoffFlightPage /></AuthGuard>} />
            <Route path="/iot" element={<AuthGuard><IotLayoutPage /></AuthGuard>} />
          </Routes>
        </div>
        <StatusBar />
      </div>
    </div>
  );
};

export default App;
