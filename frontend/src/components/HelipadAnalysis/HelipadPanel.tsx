import React, { useState } from 'react';
import {
  Box,
  Button,
  CircularProgress,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { useHelipadStore } from '../../store/useHelipadStore';
import type { FATOSlopeType, FATOShape, OperationMode } from '../../types/helipad';
import { useStatusStore } from '../../store/useStatusStore';

const SHAPE_OPTIONS: Array<{ value: FATOShape; label: string }> = [
  { value: 'circle', label: '圆形' },
  { value: 'square', label: '正方形' },
];

const SLOPE_OPTIONS: Array<{ value: FATOSlopeType; label: string }> = [
  { value: 'A', label: 'A' },
  { value: 'B', label: 'B' },
  { value: 'C', label: 'C' },
];

const HelipadPanel: React.FC = () => {
  const {
    helipadCenter,
    fatoConfig,
    setFATOConfig,
    fatoRegion,
    surfaceParams,
    buildingResults,
    buildingMessage,
    terrainExceedances,
    terrainLoading,
    terrainMessage,
    isCalculating,
    statusMessage,
    calculateSurface,
    analyzeTerrain,
    clearHelipad,
  } = useHelipadStore();

  const setStatus = useStatusStore((s) => s.setStatus);

  // Local draft state for the config form
  const [draftShape, setDraftShape] = useState<FATOShape>(fatoConfig.shape);
  const [draftDiameter, setDraftDiameter] = useState(String(fatoConfig.diameter || ''));
  const [draftRotorDiameter, setDraftRotorDiameter] = useState(String(fatoConfig.rotorDiameter || ''));
  const [draftElevation, setDraftElevation] = useState(String(fatoConfig.elevation || ''));
  const [draftDirection, setDraftDirection] = useState(String(fatoConfig.flightDirection || ''));
  const [draftSlopeType, setDraftSlopeType] = useState<FATOSlopeType>(fatoConfig.slopeType);
  const [draftOperationMode, setDraftOperationMode] = useState<OperationMode>(fatoConfig.operationMode);
  // Independent takeoff horizontal direction
  const [useCustomTakeoffDir, setUseCustomTakeoffDir] = useState(fatoConfig.takeoffDirection != null);
  const [draftTakeoffDir, setDraftTakeoffDir] = useState(
    fatoConfig.takeoffDirection != null ? String(fatoConfig.takeoffDirection) : '',
  );

  const handleApply = () => {
    const diameter = parseFloat(draftDiameter);
    if (isNaN(diameter) || diameter <= 0) {
      setStatus({ severity: 'error', title: '参数错误', message: '请输入有效的 FATO 尺寸' });
      return;
    }
    const rotorDiameter = parseFloat(draftRotorDiameter);
    if (isNaN(rotorDiameter) || rotorDiameter <= 0) {
      setStatus({ severity: 'error', title: '参数错误', message: '请输入有效的旋翼直径 RD' });
      return;
    }
    const elevation = parseFloat(draftElevation);
    if (isNaN(elevation)) {
      setStatus({ severity: 'error', title: '参数错误', message: '请输入有效的 FATO 海拔' });
      return;
    }
    const direction = parseFloat(draftDirection);
    if (isNaN(direction) || direction < 0 || direction > 360) {
      setStatus({ severity: 'error', title: '参数错误', message: '请输入 0-360 之间的飞行方向' });
      return;
    }

    // Independent takeoff direction
    let takeoffDirection: number | null = null;
    if (useCustomTakeoffDir) {
      const td = parseFloat(draftTakeoffDir);
      if (isNaN(td) || td < 0 || td > 360) {
        setStatus({ severity: 'error', title: '参数错误', message: '起飞方向需在 0°-360° 之间' });
        return;
      }
      takeoffDirection = td;
    }

    setFATOConfig({
      shape: draftShape,
      diameter,
      rotorDiameter,
      elevation,
      flightDirection: direction,
      takeoffDirection,
      slopeType: draftSlopeType,
      operationMode: draftOperationMode,
    });

    // Trigger calculation
    void calculateSurface();
  };

  const handleAnalyzeTerrain = () => {
    void analyzeTerrain();
  };

  const handleClear = () => {
    clearHelipad();
    setDraftDiameter('');
    setDraftRotorDiameter('');
    setDraftElevation('');
    setDraftDirection('');
  };

  return (
    <Box sx={{ p: 2 }}>
      <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 600 }}>
        起降场分析（FATO）
      </Typography>

      {/* Status */}
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
        {statusMessage}
      </Typography>

      {/* Compliance note */}
      <Box
        sx={{
          p: 1.5,
          mb: 2,
          border: '1px solid #f2d39b',
          borderRadius: 1,
          bgcolor: '#fff8e8',
        }}
      >
        <Typography variant="caption" color="#76531c" sx={{ lineHeight: 1.45 }}>
          本工具结果仅供飞行场地技术分析参考，不作为飞行许可、空域审批或运行安全结论。
        </Typography>
      </Box>

      {/* Coordinates display */}
      {helipadCenter && (
        <Grid container spacing={1.5} sx={{ mb: 2 }}>
          <Grid item xs={6}>
            <TextField
              fullWidth
              size="small"
              label="纬度"
              value={helipadCenter.latitude.toFixed(6)}
              InputProps={{ readOnly: true }}
            />
          </Grid>
          <Grid item xs={6}>
            <TextField
              fullWidth
              size="small"
              label="经度"
              value={helipadCenter.longitude.toFixed(6)}
              InputProps={{ readOnly: true }}
            />
          </Grid>
        </Grid>
      )}

      {/* FATO Config Form */}
      <Stack spacing={2} sx={{ mb: 2 }}>
        {/* Shape */}
        <FormControl size="small" fullWidth>
          <InputLabel>FATO 形状</InputLabel>
          <Select
            label="FATO 形状"
            value={draftShape}
            onChange={(e) => setDraftShape(e.target.value as FATOShape)}
            disabled={isCalculating}
          >
            {SHAPE_OPTIONS.map((opt) => (
              <MenuItem key={opt.value} value={opt.value}>
                {opt.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {/* FATO Diameter */}
        <TextField
          fullWidth
          size="small"
          type="number"
          label="FATO 尺寸（米）"
          value={draftDiameter}
          onChange={(e) => setDraftDiameter(e.target.value)}
          placeholder={draftShape === 'circle' ? '圆形填直径' : '正方形填边长'}
          inputProps={{ min: 1, step: 1 }}
          disabled={isCalculating}
        />

        {/* Rotor Diameter */}
        <TextField
          fullWidth
          size="small"
          type="number"
          label="旋翼直径 RD（米）"
          value={draftRotorDiameter}
          onChange={(e) => setDraftRotorDiameter(e.target.value)}
          placeholder="用于计算 7RD / 10RD 外边宽度"
          inputProps={{ min: 1, step: 0.5 }}
          disabled={isCalculating}
        />

        {/* FATO Elevation */}
        <TextField
          fullWidth
          size="small"
          type="number"
          label="FATO 海拔（米）"
          value={draftElevation}
          onChange={(e) => setDraftElevation(e.target.value)}
          placeholder="请输入 FATO 标高/海拔"
          inputProps={{ step: 0.1 }}
          disabled={isCalculating}
        />

        {/* Flight Direction */}
        <TextField
          fullWidth
          size="small"
          type="number"
          label="进近面方向（度）"
          value={draftDirection}
          onChange={(e) => setDraftDirection(e.target.value)}
          placeholder="请输入 0-360 的方向角"
          inputProps={{ min: 0, max: 360, step: 1 }}
          disabled={isCalculating}
        />

        {/* Slope Type */}
        <FormControl size="small" fullWidth>
          <InputLabel>坡度类别</InputLabel>
          <Select
            label="坡度类别"
            value={draftSlopeType}
            onChange={(e) => setDraftSlopeType(e.target.value as FATOSlopeType)}
            disabled={isCalculating}
          >
            {SLOPE_OPTIONS.map((opt) => (
              <MenuItem key={opt.value} value={opt.value}>
                {opt.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {/* --- Independent Takeoff Direction --- */}
        <Box sx={{ border: '1px solid #e0e0e0', borderRadius: 1, p: 1.5 }}>
          <FormControlLabel
            control={
              <Switch
                size="small"
                checked={useCustomTakeoffDir}
                onChange={(e) => setUseCustomTakeoffDir(e.target.checked)}
                disabled={isCalculating}
              />
            }
            label={
              <Typography variant="body2" fontWeight={500}>
                独立调整起飞面方向
              </Typography>
            }
          />
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            {useCustomTakeoffDir
              ? '起飞面将使用下方指定的方向，不再自动设为进近方向+180°'
              : `起飞面自动 = 进近方向 + 180° = ${((parseFloat(draftDirection) || 0) + 180) % 360}°`}
          </Typography>
          <TextField
            fullWidth
            size="small"
            type="number"
            label="起飞爬升面水平方向（度）"
            value={draftTakeoffDir}
            onChange={(e) => setDraftTakeoffDir(e.target.value)}
            disabled={isCalculating || !useCustomTakeoffDir}
            inputProps={{ min: 0, max: 360, step: 1 }}
            placeholder="例如 90 表示朝东起飞"
          />
        </Box>

        {/* Operation Mode */}
        <Box>
          <Typography variant="body2" gutterBottom>
            运行模式
          </Typography>
          <ToggleButtonGroup
            exclusive
            fullWidth
            size="small"
            value={draftOperationMode}
            onChange={(_, val: OperationMode | null) => {
              if (val) setDraftOperationMode(val);
            }}
            disabled={isCalculating}
          >
            <ToggleButton value="day">白天</ToggleButton>
            <ToggleButton value="night">夜间</ToggleButton>
          </ToggleButtonGroup>
        </Box>
      </Stack>

      {/* Actions */}
      <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
        <Button
          variant="contained"
          fullWidth
          onClick={handleApply}
          disabled={isCalculating || !helipadCenter}
          startIcon={isCalculating ? <CircularProgress size={18} /> : null}
        >
          {isCalculating ? '计算中...' : '计算FATO与限制面'}
        </Button>
        {helipadCenter && (
          <Button variant="outlined" color="error" onClick={handleClear} sx={{ minWidth: 80 }}>
            清除
          </Button>
        )}
      </Stack>

      {/* Helipad Info (after calculation) */}
      {fatoRegion && surfaceParams && (
        <Box sx={{ p: 1.5, border: '1px solid #dce3e8', borderRadius: 1, bgcolor: '#f8fafb', mb: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            起降场参数
          </Typography>
          <Grid container spacing={1}>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">FATO 形状</Typography>
              <Typography variant="body2" fontWeight={500}>{fatoConfig.shape === 'circle' ? '圆形' : '正方形'}</Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">FATO 尺寸</Typography>
              <Typography variant="body2" fontWeight={500}>{fatoConfig.diameter} m</Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">旋翼直径 RD</Typography>
              <Typography variant="body2" fontWeight={500}>{fatoConfig.rotorDiameter} m</Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">FATO 海拔</Typography>
              <Typography variant="body2" fontWeight={500}>{fatoConfig.elevation} m</Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">进近方向</Typography>
              <Typography variant="body2" fontWeight={500}>{fatoConfig.flightDirection}°</Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">起飞方向</Typography>
              <Typography variant="body2" fontWeight={500}>
                {fatoConfig.takeoffDirection != null ? `${fatoConfig.takeoffDirection}°` : `${(fatoConfig.flightDirection + 180) % 360}°（自动）`}
              </Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">坡度类别</Typography>
              <Typography variant="body2" fontWeight={500}>{surfaceParams.slopeType}</Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">运行模式</Typography>
              <Typography variant="body2" fontWeight={500}>{fatoConfig.operationMode === 'day' ? '白天' : '夜间'}</Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">散开率</Typography>
              <Typography variant="body2" fontWeight={500}>{(surfaceParams.divergence * 100).toFixed(0)}%</Typography>
            </Grid>
          </Grid>
        </Box>
      )}

      {/* Terrain Analysis Button */}
      {fatoRegion && (
        <Button
          variant="contained"
          color="secondary"
          fullWidth
          onClick={handleAnalyzeTerrain}
          disabled={terrainLoading}
          startIcon={terrainLoading ? <CircularProgress size={18} /> : null}
          sx={{ mb: 1 }}
        >
          {terrainLoading ? '正在分析地形...' : '地形高程分析'}
        </Button>
      )}

      {/* Terrain Result */}
      {terrainMessage && (
        <Typography
          variant="caption"
          color={terrainExceedances.length > 0 ? 'error' : 'text.secondary'}
          sx={{ display: 'block', mb: 1 }}
        >
          {terrainMessage}
        </Typography>
      )}

      {/* Building Search Result */}
      {buildingMessage && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          {buildingMessage}
        </Typography>
      )}

      {/* Building list */}
      {buildingResults.length > 0 && (
        <Box sx={{ maxHeight: 200, overflow: 'auto', mt: 1 }}>
          <Typography variant="subtitle2" gutterBottom>
            范围内建筑/地点 ({buildingResults.length})
          </Typography>
          {buildingResults.map((b) => (
            <Box
              key={b.id}
              sx={{
                py: 0.5,
                px: 1,
                borderBottom: '1px solid #eee',
                fontSize: '0.8rem',
              }}
            >
              <Typography variant="caption" fontWeight={500}>
                {b.name}
              </Typography>
              <Typography variant="caption" color="text.secondary" display="block">
                {[b.category, b.address].filter(Boolean).join(' · ')}
              </Typography>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
};

export default HelipadPanel;
