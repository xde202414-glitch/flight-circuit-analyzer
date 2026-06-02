import React from 'react';
import { ThemeProvider, createTheme, CssBaseline, AppBar, Toolbar, Typography, Box, ToggleButtonGroup, ToggleButton } from '@mui/material';
import RunwayForm from './components/RunwayForm/RunwayForm';
import AircraftSelector from './components/AircraftSelector/AircraftSelector';
import MapView from './components/MapView/MapView';
import TrackAnalysis from './components/TrackAnalysis/TrackAnalysis';
import StatusBar from './components/StatusBar/StatusBar';
import HelipadPanel from './components/HelipadAnalysis/HelipadPanel';
import { useRunwayStore } from './store/useRunwayStore';
import { useHelipadStore } from './store/useHelipadStore';
import type { AnalysisMode } from './store/useHelipadStore';

// Create MUI theme
const theme = createTheme({
  palette: {
    primary: {
      main: '#1976d2',
    },
    secondary: {
      main: '#dc004e',
    },
    background: {
      default: '#f5f5f5',
    },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
    h6: {
      fontWeight: 600,
    },
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
        },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            borderRadius: 8,
          },
        },
      },
    },
  },
});

/**
 * Main Application Component
 * Flight Circuit Analyzer - 飞行营地飞行程序分析工具
 */
const App: React.FC = () => {
  const { runwayParams } = useRunwayStore();
  const { analysisMode, setAnalysisMode, helipadCenter } = useHelipadStore();

  const mapCenter: [number, number] =
    analysisMode === 'helipad' && helipadCenter
      ? [helipadCenter.latitude, helipadCenter.longitude]
      : runwayParams?.coordinate
        ? [runwayParams.coordinate.latitude, runwayParams.coordinate.longitude]
        : [30.2741, 120.1551];

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ flexGrow: 1, height: '100vh', display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <AppBar position="static" elevation={1}>
          <Toolbar>
            <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
              飞行营地飞行程序分析工具
            </Typography>

            {/* Mode Toggle */}
            <ToggleButtonGroup
              exclusive
              size="small"
              value={analysisMode}
              onChange={(_, val: AnalysisMode | null) => {
                if (val) setAnalysisMode(val);
              }}
              sx={{
                bgcolor: 'rgba(255,255,255,0.15)',
                '& .MuiToggleButton-root': {
                  color: 'rgba(255,255,255,0.7)',
                  borderColor: 'rgba(255,255,255,0.3)',
                  px: 2,
                },
                '& .Mui-selected': {
                  bgcolor: 'rgba(255,255,255,0.25)',
                  color: '#fff',
                },
              }}
            >
              <ToggleButton value="runway">跑道程序</ToggleButton>
              <ToggleButton value="helipad">起降场分析</ToggleButton>
            </ToggleButtonGroup>
          </Toolbar>
        </AppBar>

        {/* Main Content */}
        <Box className="main-container">
          {/* Left Panel - Parameter Input */}
          <Box className="left-panel">
            <Typography variant="h6" gutterBottom sx={{ color: 'primary.main', mb: 2 }}>
              {analysisMode === 'helipad' ? '起降场参数配置' : '参数配置'}
            </Typography>

            {analysisMode === 'helipad' ? (
              <HelipadPanel />
            ) : (
              <>
                {/* Runway Parameters Form */}
                <RunwayForm />

                {/* Aircraft Selector */}
                <AircraftSelector />
              </>
            )}
          </Box>

          {/* Right Panel - Map & Analysis */}
          <Box className="right-panel">
            {/* Map Container */}
            <Box className="map-container">
              <MapView
                center={mapCenter}
                zoom={13}
              />
            </Box>

            {/* Analysis Panel (runway mode only) */}
            {analysisMode === 'runway' && (
              <Box className="analysis-panel">
                <TrackAnalysis />
              </Box>
            )}
          </Box>
        </Box>
        <StatusBar />
      </Box>
    </ThemeProvider>
  );
};

export default App;
