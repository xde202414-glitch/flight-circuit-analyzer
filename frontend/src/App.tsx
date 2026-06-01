import React from 'react';
import { ThemeProvider, createTheme, CssBaseline, AppBar, Toolbar, Typography, Box } from '@mui/material';
import RunwayForm from './components/RunwayForm/RunwayForm';
import AircraftSelector from './components/AircraftSelector/AircraftSelector';
import MapView from './components/MapView/MapView';
import TrackAnalysis from './components/TrackAnalysis/TrackAnalysis';
import StatusBar from './components/StatusBar/StatusBar';
import { useRunwayStore } from './store/useRunwayStore';

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
            <Typography variant="body2" color="inherit" sx={{ opacity: 0.8 }}>
              五边航迹计算与可视化
            </Typography>
          </Toolbar>
        </AppBar>

        {/* Main Content */}
        <Box className="main-container">
          {/* Left Panel - Parameter Input */}
          <Box className="left-panel">
            <Typography variant="h6" gutterBottom sx={{ color: 'primary.main', mb: 2 }}>
              参数配置
            </Typography>
            
            {/* Runway Parameters Form */}
            <RunwayForm />
            
            {/* Aircraft Selector */}
            <AircraftSelector />
          </Box>

          {/* Right Panel - Map & Analysis */}
          <Box className="right-panel">
            {/* Map Container */}
            <Box className="map-container">
              <MapView 
                center={runwayParams?.coordinate ? [runwayParams.coordinate.latitude, runwayParams.coordinate.longitude] : [30.2741, 120.1551]}
                zoom={13}
              />
            </Box>
            
            {/* Track Analysis Panel */}
            <Box className="analysis-panel">
              <TrackAnalysis />
            </Box>
          </Box>
        </Box>
        <StatusBar />
      </Box>
    </ThemeProvider>
  );
};

export default App;
