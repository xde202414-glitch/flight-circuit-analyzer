import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Typography,
} from '@mui/material';
import { useTrackStore } from '../../store/useTrackStore';
import { Aircraft } from '../../types/aircraft';
import { apiGet } from '../../api/client';
import { AircraftListResponse } from '../../api/types';

const AircraftSelector: React.FC = () => {
  const { selectedAircraft, setSelectedAircraft } = useTrackStore();
  const [aircrafts, setAircrafts] = useState<Aircraft[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadAircrafts = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const result = await apiGet<AircraftListResponse>('/aircrafts');
        setAircrafts(result.aircrafts);

        const defaultAircraft = result.aircrafts.find((aircraft) => aircraft.id === 'cessna-172');
        if (defaultAircraft && !selectedAircraft) {
          setSelectedAircraft(defaultAircraft);
        }
      } catch (err) {
        console.error('Failed to load aircrafts:', err);
        setError('加载机型列表失败，请检查后端服务');
      } finally {
        setIsLoading(false);
      }
    };

    loadAircrafts();
  }, [setSelectedAircraft, selectedAircraft]);

  const handleAircraftChange = (aircraftId: string) => {
    const aircraft = aircrafts.find((item) => item.id === aircraftId);
    if (aircraft) {
      setSelectedAircraft(aircraft);
    }
  };

  const getCategoryColor = (category: string): 'success' | 'warning' | 'error' | 'default' => {
    switch (category) {
      case 'light':
        return 'success';
      case 'medium':
        return 'warning';
      case 'heavy':
        return 'error';
      default:
        return 'default';
    }
  };

  const getEngineTypeColor = (engineType: string): 'primary' | 'secondary' | 'error' | 'default' => {
    switch (engineType) {
      case 'piston':
        return 'primary';
      case 'turboprop':
        return 'secondary';
      case 'jet':
        return 'error';
      default:
        return 'default';
    }
  };

  return (
    <Box sx={{ mt: 3 }}>
      <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 600 }}>
        机型选择
      </Typography>

      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
          <CircularProgress size={24} />
        </Box>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
          <Button size="small" onClick={() => window.location.reload()} sx={{ ml: 2 }}>
            重试
          </Button>
        </Alert>
      )}

      {!isLoading && !error && (
        <FormControl fullWidth size="small" sx={{ mb: 2 }}>
          <InputLabel>选择机型</InputLabel>
          <Select
            value={selectedAircraft?.id || ''}
            label="选择机型"
            onChange={(event) => handleAircraftChange(event.target.value)}
          >
            {aircrafts.map((aircraft) => (
              <MenuItem key={aircraft.id} value={aircraft.id}>
                {aircraft.name} ({aircraft.manufacturer})
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      )}

      {selectedAircraft && (
        <Card variant="outlined" sx={{ mt: 2 }}>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>
              {selectedAircraft.name}
            </Typography>

            <Box sx={{ mb: 1, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              <Chip
                label={selectedAircraft.category}
                color={getCategoryColor(selectedAircraft.category)}
                size="small"
              />
              <Chip
                label={selectedAircraft.engineType}
                color={getEngineTypeColor(selectedAircraft.engineType)}
                size="small"
                variant="outlined"
              />
              <Chip
                label={`VFR ${selectedAircraft.vfrPatternClass}`}
                color="info"
                size="small"
                variant="outlined"
              />
            </Box>

            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {selectedAircraft.description}
            </Typography>

            <Grid container spacing={1}>
              <Grid item xs={6}>
                <Typography variant="caption" color="text.secondary">
                  巡航速度: {selectedAircraft.cruiseSpeed} km/h
                </Typography>
              </Grid>
              <Grid item xs={6}>
                <Typography variant="caption" color="text.secondary">
                  爬升率: {selectedAircraft.climbRate} m/s
                </Typography>
              </Grid>
              <Grid item xs={6}>
                <Typography variant="caption" color="text.secondary">
                  转弯半径: {selectedAircraft.turnRadius} m
                </Typography>
              </Grid>
              <Grid item xs={6}>
                <Typography variant="caption" color="text.secondary">
                  进近速度: {selectedAircraft.approachSpeed} km/h
                </Typography>
              </Grid>
              <Grid item xs={6}>
                <Typography variant="caption" color="text.secondary">
                  程序最大IAS: {selectedAircraft.vfrMaxIasKmh} km/h
                </Typography>
              </Grid>
              <Grid item xs={6}>
                <Typography variant="caption" color="text.secondary">
                  最大高度: {selectedAircraft.maxAltitude} m
                </Typography>
              </Grid>
            </Grid>
          </CardContent>
        </Card>
      )}
    </Box>
  );
};

export default AircraftSelector;
