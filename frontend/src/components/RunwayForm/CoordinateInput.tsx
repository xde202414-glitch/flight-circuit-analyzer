/**
 * CoordinateInput Component - Coordinate input with system selector
 * 坐标输入组件 - 支持坐标系选择
 */
import React, { useState } from 'react';
import {
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Grid,
  Typography,
  Tooltip,
  IconButton,
} from '@mui/material';
import { Info as InfoIcon } from '@mui/icons-material';
import { CoordinateSystem } from '../../types/runway';
import { apiPost } from '../../api/client';
import { CoordinateTransformResponse, CoordinateTransformRequest } from '../../api/types';

interface CoordinateInputProps {
  /** Current coordinate value */
  value: { latitude: number; longitude: number };
  /** Current coordinate system */
  coordinateSystem: CoordinateSystem;
  /** Handle coordinate change */
  onCoordinateChange: (lat: number, lon: number) => void;
  /** Handle coordinate system change */
  onCoordinateSystemChange: (system: CoordinateSystem) => void;
}

/**
 * CoordinateInput Component
 * Provides latitude/longitude input with coordinate system selection
 */
const CoordinateInput: React.FC<CoordinateInputProps> = ({
  value,
  coordinateSystem,
  onCoordinateChange,
  onCoordinateSystemChange,
}) => {
  const [displayValue, setDisplayValue] = useState({
    latitude: value.latitude.toString(),
    longitude: value.longitude.toString(),
  });
  const [isConverting, setIsConverting] = useState(false);

  React.useEffect(() => {
    const displayLat = Number(displayValue.latitude);
    const displayLon = Number(displayValue.longitude);
    const valueChanged =
      !Number.isFinite(displayLat) ||
      !Number.isFinite(displayLon) ||
      Math.abs(displayLat - value.latitude) > 0.0000005 ||
      Math.abs(displayLon - value.longitude) > 0.0000005;

    if (valueChanged) {
      setDisplayValue({
        latitude: value.latitude.toFixed(6),
        longitude: value.longitude.toFixed(6),
      });
    }
  }, [displayValue.latitude, displayValue.longitude, value.latitude, value.longitude]);
  
  /**
   * Handle latitude input change
   */
  const handleLatitudeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const latStr = e.target.value;
    setDisplayValue((prev) => ({ ...prev, latitude: latStr }));
    
    const lat = parseFloat(latStr);
    if (!isNaN(lat) && lat >= -90 && lat <= 90) {
      onCoordinateChange(lat, value.longitude);
    }
  };
  
  /**
   * Handle longitude input change
   */
  const handleLongitudeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const lonStr = e.target.value;
    setDisplayValue((prev) => ({ ...prev, longitude: lonStr }));
    
    const lon = parseFloat(lonStr);
    if (!isNaN(lon) && lon >= -180 && lon <= 180) {
      onCoordinateChange(value.latitude, lon);
    }
  };
  
  /**
   * Handle coordinate system change
   */
  const handleSystemChange = async (system: CoordinateSystem) => {
    onCoordinateSystemChange(system);
    
    // If switching from GCJ02 to WGS84, convert coordinates
    if (coordinateSystem === 'GCJ02' && system === 'WGS84') {
      setIsConverting(true);
      try {
        const request: CoordinateTransformRequest = {
          coordinate: { latitude: value.latitude, longitude: value.longitude },
          fromSystem: 'GCJ02',
          toSystem: 'WGS84',
        };
        
        const result = await apiPost<CoordinateTransformResponse>('/coordinate/transform', request);
        
        onCoordinateChange(result.coordinate.latitude, result.coordinate.longitude);
        setDisplayValue({
          latitude: result.coordinate.latitude.toFixed(6),
          longitude: result.coordinate.longitude.toFixed(6),
        });
      } catch (error) {
        console.error('Coordinate conversion failed:', error);
      } finally {
        setIsConverting(false);
      }
    }
    
    // If switching from WGS84 to GCJ02, convert coordinates
    if (coordinateSystem === 'WGS84' && system === 'GCJ02') {
      setIsConverting(true);
      try {
        const request: CoordinateTransformRequest = {
          coordinate: { latitude: value.latitude, longitude: value.longitude },
          fromSystem: 'WGS84',
          toSystem: 'GCJ02',
        };
        
        const result = await apiPost<CoordinateTransformResponse>('/coordinate/transform', request);
        
        onCoordinateChange(result.coordinate.latitude, result.coordinate.longitude);
        setDisplayValue({
          latitude: result.coordinate.latitude.toFixed(6),
          longitude: result.coordinate.longitude.toFixed(6),
        });
      } catch (error) {
        console.error('Coordinate conversion failed:', error);
      } finally {
        setIsConverting(false);
      }
    }
  };
  
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>
          跑道中心点坐标
        </Typography>
        <Tooltip title="WGS84: GPS标准坐标系, GCJ02: 高德/百度坐标系">
          <IconButton size="small">
            <InfoIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </div>
      
      {/* Coordinate System Selector */}
      <FormControl fullWidth size="small" sx={{ mb: 2 }}>
        <InputLabel>坐标系</InputLabel>
        <Select
          value={coordinateSystem}
          label="坐标系"
          onChange={(e) => handleSystemChange(e.target.value as CoordinateSystem)}
          disabled={isConverting}
        >
          <MenuItem value="WGS84">WGS84 (GPS)</MenuItem>
          <MenuItem value="GCJ02">GCJ-02 (高德/百度)</MenuItem>
        </Select>
      </FormControl>
      
      {/* Latitude & Longitude Inputs */}
      <Grid container spacing={2}>
        <Grid item xs={6}>
          <TextField
            label="纬度 (°)"
            value={displayValue.latitude}
            onChange={handleLatitudeChange}
            fullWidth
            size="small"
            type="number"
            disabled={isConverting}
            helperText="-90 ~ 90"
            inputProps={{
              step: 0.000001,
              min: -90,
              max: 90,
            }}
          />
        </Grid>
        <Grid item xs={6}>
          <TextField
            label="经度 (°)"
            value={displayValue.longitude}
            onChange={handleLongitudeChange}
            fullWidth
            size="small"
            type="number"
            disabled={isConverting}
            helperText="-180 ~ 180"
            inputProps={{
              step: 0.000001,
              min: -180,
              max: 180,
            }}
          />
        </Grid>
      </Grid>
      
      {isConverting && (
        <Typography variant="caption" color="primary" sx={{ mt: 1 }}>
          正在转换坐标系...
        </Typography>
      )}
    </div>
  );
};

export default CoordinateInput;
