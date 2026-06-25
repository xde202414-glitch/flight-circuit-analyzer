/**
 * RunwayForm Component - Runway parameters input form
 * 跑道参数表单组件 - 用于输入跑道配置
 */
import React, { useState } from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  Slider,
  Grid,
  Alert,
  Collapse,
} from '@mui/material';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import CoordinateInput from './CoordinateInput';
import { useRunwayStore } from '../../store/useRunwayStore';
import { RunwayParams, CoordinateSystem } from '../../types/runway';
import { apiPost } from '../../api/client';
import { RunwayValidationResult } from '../../api/types';

// Zod validation schema
const runwaySchema = z.object({
  magneticBearing: z.number().min(0).max(360, '磁方位角必须在0-360度之间'),
  length: z.number().min(200, '跑道长度至少200米').max(5000, '跑道长度不超过5000米'),
  elevation: z.number().min(-500, '标高不低于-500米').max(5000, '标高不超过5000米'),
});

type RunwayFormData = z.infer<typeof runwaySchema>;

/**
 * Auto-detect runway width based on code number derived from runway length
 * Per MH 5001-2021: code 1→18m, code 2→23m, code 3→30m, code 4→45m
 */
function resolveAutoRunwayWidth(length: number): string {
  if (length <= 800) return '18';
  if (length < 1200) return '23';
  if (length < 1800) return '30';
  return '45';
}

/**
 * RunwayForm Component
 * Provides form for runway parameter input with validation
 */
const RunwayForm: React.FC = () => {
  const { runwayParams, setRunwayParams, setValidationResult, validationResult } = useRunwayStore();
  const [coordinateSystem, setCoordinateSystem] = useState<CoordinateSystem>('WGS84');
  const [coordinate, setCoordinate] = useState<{ latitude: number; longitude: number }>(
    runwayParams.coordinate
  );
  const [isValidating, setIsValidating] = useState(false);

  const getAutoRunwayWidth = () => resolveAutoRunwayWidth(runwayParams.length);

  React.useEffect(() => {
    setCoordinate(runwayParams.coordinate);
    setCoordinateSystem(runwayParams.coordinateSystem);
  }, [runwayParams.coordinate, runwayParams.coordinateSystem]);
  
  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<RunwayFormData>({
    resolver: zodResolver(runwaySchema),
    defaultValues: {
      magneticBearing: runwayParams.magneticBearing,
      length: runwayParams.length,
      elevation: runwayParams.elevation,
    },
  });
  
  /**
   * Handle form submission
   */
  const onSubmit = async (data: RunwayFormData) => {
    const elevation = Number(data.elevation.toFixed(1));
    // Update runway parameters
    const newParams: RunwayParams = {
      coordinate,
      magneticBearing: data.magneticBearing,
      length: data.length,
      elevation,
      coordinateSystem,
    };
    
    setRunwayParams(newParams);
    
    // Validate via backend API
    setIsValidating(true);
    try {
      const result = await apiPost<RunwayValidationResult>('/runway/validate', newParams);
      setValidationResult(result);
    } catch (error) {
      console.error('Validation failed:', error);
      setValidationResult({
        isValid: false,
        errors: [{ field: 'unknown', message: '校验请求失败', severity: 'error' }],
      });
    } finally {
      setIsValidating(false);
    }
  };
  
  /**
   * Handle coordinate change
   */
  const handleCoordinateChange = (lat: number, lon: number) => {
    setCoordinate({ latitude: lat, longitude: lon });
  };
  
  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 600 }}>
        跑道参数配置
      </Typography>
      
      {/* Coordinate Input */}
      <CoordinateInput
        value={coordinate}
        coordinateSystem={coordinateSystem}
        onCoordinateChange={handleCoordinateChange}
        onCoordinateSystemChange={setCoordinateSystem}
      />
      
      {/* Form Fields */}
      <form onSubmit={handleSubmit(onSubmit)}>
        <Grid container spacing={2} sx={{ mt: 1 }}>
          {/* Magnetic Bearing */}
          <Grid item xs={12}>
            <Controller
              name="magneticBearing"
              control={control}
              render={({ field }) => (
                <Box>
                  <Typography variant="body2" gutterBottom>
                    磁方位角: {field.value}°
                  </Typography>
                  <Slider
                    value={field.value}
                    onChange={(_, value) => {
                      field.onChange(value);
                      setRunwayParams({ magneticBearing: value as number });
                    }}
                    min={0}
                    max={360}
                    step={1}
                    marks={[
                      { value: 0, label: '0°' },
                      { value: 90, label: '90°' },
                      { value: 180, label: '180°' },
                      { value: 270, label: '270°' },
                      { value: 360, label: '360°' },
                    ]}
                    valueLabelDisplay="auto"
                  />
                  {errors.magneticBearing && (
                    <Typography variant="caption" color="error">
                      {errors.magneticBearing.message}
                    </Typography>
                  )}
                </Box>
              )}
            />
          </Grid>
          
          {/* Runway Length */}
          <Grid item xs={12} sm={4}>
            <Controller
              name="length"
              control={control}
              render={({ field }) => (
                <TextField
                  {...field}
                  label="跑道长度 (米)"
                  type="number"
                  fullWidth
                  size="small"
                  error={!!errors.length}
                  helperText={errors.length?.message || '推荐: 600米以上'}
                  onChange={(e) => field.onChange(Number(e.target.value))}
                />
              )}
            />
          </Grid>

          {/* Runway Width */}
          <Grid item xs={12} sm={4}>
            <Box>
              <TextField
                label="跑道宽度 (米)"
                type="number"
                fullWidth
                size="small"
                value={runwayParams.runwayWidth ?? ''}
                placeholder={getAutoRunwayWidth()}
                helperText={runwayParams.runwayWidth ? '手动值' : `自动：${getAutoRunwayWidth()}m（根据飞行区指标）`}
                onChange={(e) => {
                  const val = e.target.value;
                  setRunwayParams({ runwayWidth: val ? Number(val) : undefined });
                }}
              />
            </Box>
          </Grid>

          {/* Elevation */}
          <Grid item xs={12} sm={4}>
            <Controller
              name="elevation"
              control={control}
              render={({ field }) => (
                <TextField
                  {...field}
                  label="跑道标高 (米)"
                  type="number"
                  fullWidth
                  size="small"
                  error={!!errors.elevation}
                  helperText={errors.elevation?.message || '相对海平面高度'}
                  inputProps={{ step: 0.1 }}
                  onChange={(e) => field.onChange(Number(e.target.value))}
                />
              )}
            />
          </Grid>
          
          {/* Submit Button */}
          <Grid item xs={12}>
            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={isValidating}
              sx={{ mt: 1 }}
            >
              {isValidating ? '校验中...' : '校验跑道参数'}
            </Button>
          </Grid>
        </Grid>
      </form>
      
      {/* Validation Result */}
      <Collapse in={validationResult !== null}>
        <Box sx={{ mt: 2 }}>
          {validationResult?.isValid ? (
            <Alert severity="success">跑道参数校验通过</Alert>
          ) : (
            <Box>
              {validationResult?.errors
                .filter((e) => e.severity === 'error')
                .map((error, index) => (
                  <Alert key={index} severity="error" sx={{ mb: 1 }}>
                    {error.message}
                  </Alert>
                ))}
              {validationResult?.errors
                .filter((e) => e.severity === 'warning')
                .map((warning, index) => (
                  <Alert key={index} severity="warning" sx={{ mb: 1 }}>
                    {warning.message}
                  </Alert>
                ))}
            </Box>
          )}
        </Box>
      </Collapse>
    </Box>
  );
};

export default RunwayForm;
