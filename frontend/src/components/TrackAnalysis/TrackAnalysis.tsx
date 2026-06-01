import React, { useEffect, useState } from 'react';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  CircularProgress,
  Divider,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Slider,
  Stack,
  Switch,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { useRunwayStore } from '../../store/useRunwayStore';
import {
  useTrackStore,
  selectEstimatedTime,
  selectTotalDistance,
  selectTrackSegments,
} from '../../store/useTrackStore';
import { TRACK_SEGMENT_NAMES_CN } from '../../types/track';
import type {
  ActiveRunwayEnd,
  FlightCampType,
  ParameterPreviewItem,
  RunwayCodeNumber,
  RunwayOperationType,
  TrackConfig,
  TrafficPatternSide,
} from '../../types/track';
import { apiPost } from '../../api/client';
import type {
  TrackCalculateRequest,
  TrackParameterPreviewResponse,
  TrackResult,
} from '../../api/types';
import { useStatusStore } from '../../store/useStatusStore';

const RUNWAY_OPERATION_OPTIONS: Array<{ value: RunwayOperationType; label: string }> = [
  { value: 'non_instrument', label: '非仪表跑道' },
  { value: 'non_precision', label: '非精密进近跑道' },
  { value: 'precision_cat_i', label: 'I 类精密进近跑道' },
  { value: 'precision_cat_ii_iii', label: 'II/III 类精密进近跑道' },
];

const FLIGHT_CAMP_OPTIONS: Array<{ value: FlightCampType; label: string }> = [
  { value: 'glider', label: '滑翔机' },
  { value: 'aerobatic', label: '特技飞行' },
  { value: 'powered_hang_glider', label: '动力悬挂滑翔机/动力三角翼' },
  { value: 'light_aircraft', label: '轻型飞机' },
  { value: 'helicopter', label: '直升机' },
  { value: 'gyroplane', label: '自转旋翼机' },
  { value: 'balloon_airship', label: '热气球与飞艇' },
  { value: 'hang_glider', label: '悬挂滑翔翼' },
  { value: 'paraglider', label: '滑翔伞' },
  { value: 'powered_paraglider', label: '动力伞' },
  { value: 'aero_model', label: '航空模型' },
  { value: 'water_sport_aircraft', label: '运动类航空器水上飞行' },
  { value: 'skydiving', label: '跳伞' },
];

const formatPreviewValue = (item?: ParameterPreviewItem): string => {
  if (!item) {
    return '自动';
  }
  const unit = item.unit ? ` ${item.unit}` : '';
  return `自动：${item.automaticValue}${unit}`;
};

const previewHelperText = (inputValue: string, item?: ParameterPreviewItem): string => {
  const base = formatPreviewValue(item);
  if (inputValue.trim()) {
    return `手动值，清空后恢复${base}`;
  }
  return base;
};

const TrackAnalysis: React.FC = () => {
  const { runwayParams, validationResult } = useRunwayStore();
  const {
    selectedAircraft,
    trackConfig,
    setTrackConfig,
    trackResult,
    setTrackResult,
    isCalculating,
    setIsCalculating,
    error,
    setError,
  } = useTrackStore();

  const segments = useTrackStore(selectTrackSegments);
  const totalDistance = useTrackStore(selectTotalDistance);
  const estimatedTime = useTrackStore(selectEstimatedTime);
  const setStatus = useStatusStore((state) => state.setStatus);

  const [circuitHeight, setCircuitHeight] = useState(trackConfig.circuitHeight);
  const [bankAngle, setBankAngle] = useState(trackConfig.bankAngle);
  const [activeRunwayEnd, setActiveRunwayEnd] = useState<ActiveRunwayEnd>(
    trackConfig.activeRunwayEnd
  );
  const [trafficPatternSide, setTrafficPatternSide] = useState<TrafficPatternSide>(
    trackConfig.trafficPatternSide
  );
  const [bidirectional, setBidirectional] = useState(
    trackConfig.bidirectional ?? false
  );

  const [departureLegLength, setDepartureLegLength] = useState(
    trackConfig.departureLegLength?.toString() ?? ''
  );
  const [finalLegLength, setFinalLegLength] = useState(
    trackConfig.finalLegLength?.toString() ?? ''
  );
  const [turnRadius, setTurnRadius] = useState(trackConfig.turnRadius?.toString() ?? '');
  const [downwindOffset, setDownwindOffset] = useState(
    trackConfig.downwindOffset?.toString() ?? ''
  );
  const [stableFinalDistance, setStableFinalDistance] = useState(
    trackConfig.visualPattern?.stableFinalDistance?.toString() ?? ''
  );
  const [firstTurnMinHeight, setFirstTurnMinHeight] = useState(
    trackConfig.visualPattern?.firstTurnMinHeight?.toString() ?? ''
  );
  const [finalTurnMinHeight, setFinalTurnMinHeight] = useState(
    trackConfig.visualPattern?.finalTurnMinHeight?.toString() ?? ''
  );
  const [maxIasKmh, setMaxIasKmh] = useState(
    trackConfig.visualPattern?.maxIasKmh?.toString() ?? ''
  );

  const [runwayCodeNumber, setRunwayCodeNumber] = useState<RunwayCodeNumber>(
    trackConfig.obstacleSurfaces?.codeNumber ?? 'auto'
  );
  const [runwayOperationType, setRunwayOperationType] = useState<RunwayOperationType>(
    trackConfig.obstacleSurfaces?.runwayOperationType ?? 'non_instrument'
  );
  const [takeoffEnabled, setTakeoffEnabled] = useState(
    trackConfig.obstacleSurfaces?.takeoffEnabled ?? true
  );
  const bidirectionalEnvelopeEnabled = trackConfig.obstacleSurfaces?.bidirectionalEnvelopeEnabled ?? true;
  const [showIndividualSurfaces, setShowIndividualSurfaces] = useState(
    trackConfig.obstacleSurfaces?.showIndividualSurfaces ?? true
  );

  const recommendedCampType = selectedAircraft?.flightCampCategory ?? 'light_aircraft';
  const [campTypeTouched, setCampTypeTouched] = useState(Boolean(trackConfig.flightCampAirspace));
  const [flightCampEnabled, setFlightCampEnabled] = useState(
    trackConfig.flightCampAirspace?.enabled ?? true
  );
  const [campType, setCampType] = useState<FlightCampType>(
    trackConfig.flightCampAirspace?.campType ?? recommendedCampType
  );
  const [flightCampRadius, setFlightCampRadius] = useState(
    trackConfig.flightCampAirspace?.radiusM?.toString() ?? ''
  );
  const [flightCampHeight, setFlightCampHeight] = useState(
    trackConfig.flightCampAirspace?.trueHeightM?.toString() ?? ''
  );
  const [clearanceRadius, setClearanceRadius] = useState(
    trackConfig.flightCampAirspace?.clearanceRadiusM?.toString() ?? ''
  );
  const [overlaySpecialAirspace, setOverlaySpecialAirspace] = useState(
    trackConfig.flightCampAirspace?.overlaySpecialAirspace ?? false
  );

  const [parameterPreview, setParameterPreview] =
    useState<TrackParameterPreviewResponse | null>(null);
  const [, setParameterPreviewError] = useState<string | null>(null);
  const visualPreview = parameterPreview?.visualPattern ?? {};
  const obstaclePreview = parameterPreview?.obstacleSurfaces ?? {};
  const airspacePreview = parameterPreview?.flightCampAirspace ?? {};

  const showParameterInfo = (title: string, item?: ParameterPreviewItem) => {
    if (!item) {
      return;
    }
    setStatus({
      severity: item.source === 'custom' ? 'warning' : 'info',
      title,
      message: `${previewHelperText('', item)}。${item.description || '无补充说明。'}`,
      source: [item.sourceCode, item.clause].filter(Boolean).join(' '),
    });
  };

  useEffect(() => {
    if (!campTypeTouched) {
      setCampType(recommendedCampType);
    }
  }, [campTypeTouched, recommendedCampType]);

  useEffect(() => {
    if (!selectedAircraft) {
      setStatus({
        severity: 'info',
        title: '机型待选择',
        message: '请选择机型后，系统会自动推荐 VFR 类别、最大 IAS 和飞行营地空域类型。',
      });
      return;
    }

    setStatus({
      severity: 'info',
      title: '机型参数已载入',
      message: `规范类别 ${selectedAircraft.vfrPatternClass}，最大 IAS ${selectedAircraft.vfrMaxIasKmh} km/h，推荐空域 ${FLIGHT_CAMP_OPTIONS.find((item) => item.value === recommendedCampType)?.label ?? recommendedCampType}。`,
      source: 'AC-97-FS-005R1 / 航空飞行营地设施及空域标准细则',
    });
  }, [recommendedCampType, selectedAircraft, setStatus]);

  const parseOptionalNumber = (value: string): number | undefined => {
    const trimmed = value.trim();
    if (!trimmed) {
      return undefined;
    }
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : undefined;
  };

  const buildTrackConfig = (): TrackConfig => ({
    ...trackConfig,
    circuitHeight,
    bankAngle,
    activeRunwayEnd,
    trafficPatternSide,
    bidirectional,
    departureLegLength: parseOptionalNumber(departureLegLength),
    finalLegLength: parseOptionalNumber(finalLegLength),
    turnRadius: parseOptionalNumber(turnRadius),
    downwindOffset: parseOptionalNumber(downwindOffset),
    visualPattern: {
      ...(trackConfig.visualPattern ?? {}),
      joinMethod: 'standard',
      stableFinalDistance: parseOptionalNumber(stableFinalDistance),
      firstTurnMinHeight: parseOptionalNumber(firstTurnMinHeight),
      finalTurnMinHeight: parseOptionalNumber(finalTurnMinHeight),
      maxIasKmh: parseOptionalNumber(maxIasKmh),
    },
    obstacleSurfaces: {
      codeNumber: runwayCodeNumber,
      runwayOperationType,
      takeoffEnabled,
      bidirectionalEnvelopeEnabled,
      showIndividualSurfaces,
    },
    flightCampAirspace: {
      enabled: flightCampEnabled,
      campType,
      radiusM: parseOptionalNumber(flightCampRadius),
      trueHeightM: parseOptionalNumber(flightCampHeight),
      clearanceRadiusM: parseOptionalNumber(clearanceRadius),
      overlaySpecialAirspace,
    },
  });

  useEffect(() => {
    if (!selectedAircraft) {
      setParameterPreview(null);
      setParameterPreviewError(null);
      return;
    }

    let cancelled = false;
    const previewConfig = buildTrackConfig();

    apiPost<TrackParameterPreviewResponse>('/track/parameter-preview', {
      aircraft_id: selectedAircraft.id,
      config: previewConfig,
    })
      .then((result) => {
        if (!cancelled) {
          setParameterPreview(result);
          setParameterPreviewError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.error('Parameter preview failed:', err);
          setParameterPreview(null);
          setParameterPreviewError('自动参数预览失败');
          setStatus({
            severity: 'warning',
            title: '自动参数预览失败',
            message: err instanceof Error ? err.message : '请检查后端服务和当前参数。',
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    selectedAircraft,
    trackConfig,
    circuitHeight,
    bankAngle,
    activeRunwayEnd,
    trafficPatternSide,
    bidirectional,
    departureLegLength,
    finalLegLength,
    turnRadius,
    downwindOffset,
    stableFinalDistance,
    firstTurnMinHeight,
    finalTurnMinHeight,
    maxIasKmh,
    runwayCodeNumber,
    runwayOperationType,
    takeoffEnabled,
    bidirectionalEnvelopeEnabled,
    showIndividualSurfaces,
    flightCampEnabled,
    campType,
    flightCampRadius,
    flightCampHeight,
    clearanceRadius,
    overlaySpecialAirspace,
    setStatus,
  ]);

  useEffect(() => {
    if (!parameterPreview) {
      return;
    }

    setStatus({
      severity: 'info',
      title: '自动参数已更新',
      message: `一边 ${parameterPreview.visualPattern.departureLegLength?.automaticValue ?? '-'}m，五边 ${parameterPreview.visualPattern.finalLegLength?.automaticValue ?? '-'}m，限制面 ${parameterPreview.obstacleSurfaces.runwayOperationType?.value ?? '-'}，营地空域半径 ${parameterPreview.flightCampAirspace.radius?.automaticValue ?? '-'}m。`,
      source: '参数预览接口 /track/parameter-preview',
    });
  }, [parameterPreview, setStatus]);

  useEffect(() => {
    if (!parameterPreview) {
      return;
    }

    const selectedOperation = RUNWAY_OPERATION_OPTIONS.find(
      (item) => item.value === runwayOperationType
    )?.label;
    setStatus({
      severity: runwayOperationType === 'non_instrument' ? 'info' : 'warning',
      title: '障碍物限制面参数',
      message:
        runwayOperationType === 'non_instrument'
          ? `${selectedOperation}按 MH5001 基础 OLS 面绘制；进近面尺寸由指标 I 决定，不随跑道长度改变；内水平面、锥形面和双向包络按跑道两端生成，会随跑道长度改变。`
          : `${selectedOperation}当前按基础 OLS 面绘制；进近面尺寸由指标 I 决定，内水平面/锥形面/双向包络随跑道长度改变；内进近面、内过渡面和复飞面需要结合正式表值复核。`,
      source: `${obstaclePreview.approachLength?.sourceCode ?? 'MH 5001-2021'} ${obstaclePreview.approachLength?.clause ?? ''}`,
    });
  }, [obstaclePreview.approachLength, parameterPreview, runwayOperationType, setStatus]);

  useEffect(() => {
    if (error) {
      setStatus({
        severity: 'error',
        title: '计算输入错误',
        message: error,
      });
    }
  }, [error, setStatus]);

  useEffect(() => {
    if (!trackResult) {
      return;
    }

    const validation = trackResult.validationReport;
    const firstError = validation.errors[0];
    const firstWarning = validation.warnings[0];
    const firstCompliance = trackResult.compliance.find((item) => item.severity !== 'info');

    if (firstError) {
      setStatus({
        severity: 'error',
        title: '程序校验未通过',
        message: firstError.message,
        source: firstError.code,
      });
      return;
    }

    if (firstWarning || firstCompliance) {
      setStatus({
        severity: 'warning',
        title: '程序生成完成，有规范提示',
        message: firstWarning?.message ?? firstCompliance?.message ?? '请查看历史信息。',
        source: firstWarning?.code ?? [firstCompliance?.sourceCode, firstCompliance?.clause].filter(Boolean).join(' '),
      });
      return;
    }

    setStatus({
      severity: 'success',
      title: '程序生成完成',
      message: `生成 ${trackResult.segments.length} 个航段、${trackResult.surfaces.length} 个限制面、${trackResult.airspaces.length} 个营地空域、${trackResult.compliance.length} 条规范提示。`,
      source: '计算接口 /track/calculate',
    });
  }, [setStatus, trackResult]);

  const handleCalculate = async () => {
    if (!runwayParams || !selectedAircraft) {
      setError('请先配置跑道参数并选择机型');
      return;
    }

    if (validationResult && !validationResult.isValid) {
      setError('跑道参数校验未通过，请先修正错误');
      return;
    }

    setIsCalculating(true);
    setError(null);

    const newConfig = buildTrackConfig();
    setTrackConfig(newConfig);

    try {
      const request: TrackCalculateRequest = {
        runway: runwayParams,
        aircraft_id: selectedAircraft.id,
        config: newConfig,
      };

      const result = await apiPost<TrackResult>('/track/calculate', request);
      setTrackResult(result);
    } catch (err) {
      console.error('Track calculation failed:', err);
      setError(`计算失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setIsCalculating(false);
    }
  };

  const clearVisualOptionalParameters = () => {
    setDepartureLegLength('');
    setFinalLegLength('');
    setTurnRadius('');
    setDownwindOffset('');
    setStableFinalDistance('');
    setFirstTurnMinHeight('');
    setFinalTurnMinHeight('');
    setMaxIasKmh('');
  };

  const clearFlightCampOptionalParameters = () => {
    setFlightCampRadius('');
    setFlightCampHeight('');
    setClearanceRadius('');
  };

  const formatTime = (seconds: number): string => {
    const minutes = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${minutes}分${secs}秒`;
  };

  const formatDistance = (meters: number): string => {
    if (meters >= 1000) {
      return `${(meters / 1000).toFixed(2)} km`;
    }
    return `${meters.toFixed(0)} m`;
  };

  return (
    <Box sx={{ p: 2 }}>
      <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 600 }}>
        目视飞行程序与空域配置
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        详细提示、条款说明和校验结果统一显示在底部信息栏。
      </Typography>

      <Accordion defaultExpanded disableGutters>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle2">起落航线参数（AC-97 / AP-91）</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={12} sm={4}>
              <Typography variant="body2" gutterBottom>
                使用跑道入口
              </Typography>
              <ToggleButtonGroup
                exclusive
                fullWidth
                size="small"
                value={activeRunwayEnd}
                onChange={(_, value: ActiveRunwayEnd | null) => {
                  if (value) {
                    setActiveRunwayEnd(value);
                  }
                }}
                disabled={isCalculating}
              >
                <ToggleButton value="primary">主向</ToggleButton>
                <ToggleButton value="reciprocal">反向</ToggleButton>
              </ToggleButtonGroup>
            </Grid>
            <Grid item xs={12} sm={4}>
              <Typography variant="body2" gutterBottom>
                航线方向
              </Typography>
              <ToggleButtonGroup
                exclusive
                fullWidth
                size="small"
                value={trafficPatternSide}
                onChange={(_, value: TrafficPatternSide | null) => {
                  if (value) {
                    setTrafficPatternSide(value);
                  }
                }}
                disabled={isCalculating}
              >
                <ToggleButton value="left">左航线</ToggleButton>
                <ToggleButton value="right">右航线</ToggleButton>
              </ToggleButtonGroup>
            </Grid>
            <Grid item xs={12} sm={4}>
              <Typography variant="body2" gutterBottom>
                限制面方向
              </Typography>
              <ToggleButtonGroup
                exclusive
                fullWidth
                size="small"
                value={bidirectional ? 'both' : 'single'}
                onChange={(_, value: string | null) => {
                  if (value) {
                    setBidirectional(value === 'both');
                  }
                }}
                disabled={isCalculating}
              >
                <ToggleButton value="single">单向</ToggleButton>
                <ToggleButton value="both">双向</ToggleButton>
              </ToggleButtonGroup>
            </Grid>
          </Grid>

          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" gutterBottom>
              起落航线高度: {circuitHeight} m
            </Typography>
            <Slider
              value={circuitHeight}
              onChange={(_, value) => setCircuitHeight(value as number)}
              min={100}
              max={1000}
              step={10}
              marks={[
                { value: 100, label: '100m' },
                { value: 300, label: '300m' },
                { value: 500, label: '500m' },
                { value: 1000, label: '1000m' },
              ]}
              valueLabelDisplay="auto"
              disabled={isCalculating}
            />
          </Box>

          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" gutterBottom>
              转弯坡度: {bankAngle}°
            </Typography>
            <Slider
              value={bankAngle}
              onChange={(_, value) => setBankAngle(value as number)}
              min={5}
              max={30}
              step={1}
              marks={[
                { value: 5, label: '5°' },
                { value: 15, label: '15°' },
                { value: 20, label: '20°' },
                { value: 30, label: '30°' },
              ]}
              valueLabelDisplay="auto"
              disabled={isCalculating}
            />
          </Box>

          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="subtitle2">可选几何与运行参数</Typography>
            <Button size="small" onClick={clearVisualOptionalParameters}>
              恢复自动
            </Button>
          </Stack>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            留空使用自动值；字段说明见底部信息栏。
          </Typography>

          <Grid container spacing={1.5}>
            <Grid item xs={6}>
              <TextField
                fullWidth
                size="small"
                type="number"
                label="一边长度"
                value={departureLegLength}
                onChange={(event) => setDepartureLegLength(event.target.value)}
                inputProps={{ min: 500, max: 10000, step: 50 }}
                InputProps={{ endAdornment: 'm' }}
                placeholder={formatPreviewValue(visualPreview.departureLegLength)}
                helperText={previewHelperText(departureLegLength, visualPreview.departureLegLength)}
                onFocus={() => showParameterInfo('一边长度', visualPreview.departureLegLength)}
                disabled={isCalculating}
              />
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                size="small"
                type="number"
                label="五边长度"
                value={finalLegLength}
                onChange={(event) => setFinalLegLength(event.target.value)}
                inputProps={{ min: 500, max: 10000, step: 50 }}
                InputProps={{ endAdornment: 'm' }}
                placeholder={formatPreviewValue(visualPreview.finalLegLength)}
                helperText={previewHelperText(finalLegLength, visualPreview.finalLegLength)}
                onFocus={() => showParameterInfo('五边长度', visualPreview.finalLegLength)}
                disabled={isCalculating}
              />
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                size="small"
                type="number"
                label="转弯半径"
                value={turnRadius}
                onChange={(event) => setTurnRadius(event.target.value)}
                inputProps={{ min: 100, max: 5000, step: 50 }}
                InputProps={{ endAdornment: 'm' }}
                placeholder={formatPreviewValue(visualPreview.turnRadius)}
                helperText={previewHelperText(turnRadius, visualPreview.turnRadius)}
                onFocus={() => showParameterInfo('转弯半径', visualPreview.turnRadius)}
                disabled={isCalculating}
              />
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                size="small"
                type="number"
                label="一边三边间隔"
                value={downwindOffset}
                onChange={(event) => setDownwindOffset(event.target.value)}
                inputProps={{ min: 500, max: 10000, step: 50 }}
                InputProps={{ endAdornment: 'm' }}
                placeholder={formatPreviewValue(visualPreview.downwindOffset)}
                helperText={previewHelperText(downwindOffset, visualPreview.downwindOffset)}
                onFocus={() => showParameterInfo('一边三边间隔', visualPreview.downwindOffset)}
                disabled={isCalculating}
              />
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                size="small"
                type="number"
                label="稳定五边参考距离"
                value={stableFinalDistance}
                onChange={(event) => setStableFinalDistance(event.target.value)}
                inputProps={{ min: 500, max: 10000, step: 50 }}
                InputProps={{ endAdornment: 'm' }}
                placeholder={formatPreviewValue(visualPreview.stableFinalDistance)}
                helperText={previewHelperText(stableFinalDistance, visualPreview.stableFinalDistance)}
                onFocus={() =>
                  showParameterInfo('稳定五边参考距离', visualPreview.stableFinalDistance)
                }
                disabled={isCalculating}
              />
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                size="small"
                type="number"
                label="程序最大 IAS"
                value={maxIasKmh}
                onChange={(event) => setMaxIasKmh(event.target.value)}
                inputProps={{ min: 80, max: 500, step: 5 }}
                InputProps={{ endAdornment: 'km/h' }}
                placeholder={formatPreviewValue(visualPreview.maxIasKmh)}
                helperText={previewHelperText(maxIasKmh, visualPreview.maxIasKmh)}
                onFocus={() => showParameterInfo('程序最大 IAS', visualPreview.maxIasKmh)}
                disabled={isCalculating}
              />
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                size="small"
                type="number"
                label="一转弯最低真高"
                value={firstTurnMinHeight}
                onChange={(event) => setFirstTurnMinHeight(event.target.value)}
                inputProps={{ min: 0, max: 1000, step: 10 }}
                InputProps={{ endAdornment: 'm' }}
                placeholder={formatPreviewValue(visualPreview.firstTurnMinHeight)}
                helperText={previewHelperText(firstTurnMinHeight, visualPreview.firstTurnMinHeight)}
                onFocus={() =>
                  showParameterInfo('一转弯最低真高', visualPreview.firstTurnMinHeight)
                }
                disabled={isCalculating}
              />
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                size="small"
                type="number"
                label="四转弯最低真高"
                value={finalTurnMinHeight}
                onChange={(event) => setFinalTurnMinHeight(event.target.value)}
                inputProps={{ min: 0, max: 1000, step: 10 }}
                InputProps={{ endAdornment: 'm' }}
                placeholder={formatPreviewValue(visualPreview.finalTurnMinHeight)}
                helperText={previewHelperText(finalTurnMinHeight, visualPreview.finalTurnMinHeight)}
                onFocus={() =>
                  showParameterInfo('四转弯最低真高', visualPreview.finalTurnMinHeight)
                }
                disabled={isCalculating}
              />
            </Grid>
          </Grid>
        </AccordionDetails>
      </Accordion>

      <Accordion defaultExpanded disableGutters>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle2">障碍物限制面参数（MH5001 / ICAO Annex 14）</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Grid container spacing={1.5}>
            <Grid item xs={6}>
              <FormControl size="small" fullWidth>
                <InputLabel>飞行区指标 I</InputLabel>
                <Select
                  label="飞行区指标 I"
                  value={runwayCodeNumber}
                  onChange={(event) => setRunwayCodeNumber(event.target.value as RunwayCodeNumber)}
                  disabled={isCalculating}
                >
                  <MenuItem value="auto">
                    自动（根据跑道长度）{runwayCodeNumber === 'auto' && runwayParams ? ` → 指标 ${runwayParams.length < 800 ? '1' : runwayParams.length < 1200 ? '2' : runwayParams.length < 1800 ? '3' : '4'}` : ''}
                  </MenuItem>
                  <MenuItem value="1">指标 1（跑道 &lt; 800m）</MenuItem>
                  <MenuItem value="2">指标 2（800m ≤ 跑道 &lt; 1200m）</MenuItem>
                  <MenuItem value="3">指标 3（1200m ≤ 跑道 &lt; 1800m）</MenuItem>
                  <MenuItem value="4">指标 4（跑道 ≥ 1800m）</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={6}>
              <FormControl size="small" fullWidth>
                <InputLabel>跑道运行类型</InputLabel>
                <Select
                  label="跑道运行类型"
                  value={runwayOperationType}
                  onChange={(event) =>
                    setRunwayOperationType(event.target.value as RunwayOperationType)
                  }
                  disabled={isCalculating}
                >
                  {RUNWAY_OPERATION_OPTIONS.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
          </Grid>

          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5 }}>
            飞行区指标 I 选择"自动"时，根据跑道长度自动确定（≤800m→指标1, 800-1200m→指标2, ≥1200m→指标3, ≥1800m→指标4）。
          </Typography>

          <Stack spacing={0.5} sx={{ mt: 1.5 }}>
            <FormControlLabel
              control={
                <Switch
                  checked={takeoffEnabled}
                  onChange={(event) => setTakeoffEnabled(event.target.checked)}
                  size="small"
                />
              }
              label="绘制起飞爬升面"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={showIndividualSurfaces}
                  onChange={(event) => setShowIndividualSurfaces(event.target.checked)}
                  size="small"
                />
              }
              label="显示各限制面详情"
            />
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Accordion defaultExpanded disableGutters>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle2">飞行营地空域参数</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={1.5}>
            <FormControlLabel
              control={
                <Switch
                  checked={flightCampEnabled}
                  onChange={(event) => setFlightCampEnabled(event.target.checked)}
                  size="small"
                />
              }
              label="绘制飞行营地空域"
            />
            <FormControl size="small" fullWidth>
              <InputLabel>飞行器/项目类型</InputLabel>
              <Select
                label="飞行器/项目类型"
                value={campType}
                onChange={(event) => {
                  setCampType(event.target.value as FlightCampType);
                  setCampTypeTouched(true);
                }}
                disabled={isCalculating || !flightCampEnabled}
              >
                {FLIGHT_CAMP_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              size="small"
              onClick={() => {
                setCampTypeTouched(false);
                setCampType(recommendedCampType);
                clearFlightCampOptionalParameters();
              }}
            >
              恢复机型推荐空域
            </Button>
            <Grid container spacing={1.5}>
              <Grid item xs={4}>
                <TextField
                  fullWidth
                  size="small"
                  type="number"
                  label="半径"
                  value={flightCampRadius}
                  onChange={(event) => setFlightCampRadius(event.target.value)}
                  inputProps={{ min: 100, max: 50000, step: 100 }}
                  InputProps={{ endAdornment: 'm' }}
                  placeholder={formatPreviewValue(airspacePreview.radius)}
                  helperText={previewHelperText(flightCampRadius, airspacePreview.radius)}
                  onFocus={() => showParameterInfo('飞行营地空域半径', airspacePreview.radius)}
                  disabled={isCalculating || !flightCampEnabled}
                />
              </Grid>
              <Grid item xs={4}>
                <TextField
                  fullWidth
                  size="small"
                  type="number"
                  label="真高"
                  value={flightCampHeight}
                  onChange={(event) => setFlightCampHeight(event.target.value)}
                  inputProps={{ min: 30, max: 6000, step: 10 }}
                  InputProps={{ endAdornment: 'm' }}
                  placeholder={formatPreviewValue(airspacePreview.trueHeight)}
                  helperText={previewHelperText(flightCampHeight, airspacePreview.trueHeight)}
                  onFocus={() => showParameterInfo('飞行营地空域真高', airspacePreview.trueHeight)}
                  disabled={isCalculating || !flightCampEnabled}
                />
              </Grid>
              <Grid item xs={4}>
                <TextField
                  fullWidth
                  size="small"
                  type="number"
                  label="净空半径"
                  value={clearanceRadius}
                  onChange={(event) => setClearanceRadius(event.target.value)}
                  inputProps={{ min: 0, max: 10000, step: 50 }}
                  InputProps={{ endAdornment: 'm' }}
                  placeholder={formatPreviewValue(airspacePreview.clearanceRadius)}
                  helperText={previewHelperText(clearanceRadius, airspacePreview.clearanceRadius)}
                  onFocus={() => showParameterInfo('净空检查半径', airspacePreview.clearanceRadius)}
                  disabled={isCalculating || !flightCampEnabled}
                />
              </Grid>
            </Grid>
            <FormControlLabel
              control={
                <Switch
                  checked={overlaySpecialAirspace}
                  onChange={(event) => setOverlaySpecialAirspace(event.target.checked)}
                  size="small"
                />
              }
              label="叠加特殊飞行空域预留示意"
            />
            <Typography variant="caption" color="text.secondary">
              半径、真高和净空要求说明见底部信息栏。
            </Typography>
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Button
        variant="contained"
        fullWidth
        onClick={handleCalculate}
        disabled={isCalculating || !selectedAircraft}
        startIcon={isCalculating ? <CircularProgress size={20} /> : null}
        sx={{ mt: 2 }}
      >
        {isCalculating ? '计算中...' : '生成目视飞行程序图层'}
      </Button>

      {trackResult && (
        <Paper variant="outlined" sx={{ mt: 2, p: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            计算结果摘要
          </Typography>

          <Grid container spacing={2}>
            <Grid item xs={6} sm={3}>
              <Typography variant="body2" color="text.secondary">
                总航迹距离
              </Typography>
              <Typography variant="h6" color="primary">
                {formatDistance(totalDistance)}
              </Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="body2" color="text.secondary">
                预计飞行时间
              </Typography>
              <Typography variant="h6" color="primary">
                {formatTime(estimatedTime)}
              </Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="body2" color="text.secondary">
                限制面 / 空域
              </Typography>
              <Typography variant="h6" color="primary">
                {trackResult?.surfaces.length ?? 0} / {trackResult?.airspaces.length ?? 0}
              </Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="body2" color="text.secondary">
                关键点 / 合规项
              </Typography>
              <Typography variant="h6" color="primary">
                {trackResult?.keyPoints.length ?? 0} / {trackResult?.compliance.length ?? 0}
              </Typography>
            </Grid>
          </Grid>

          <Divider sx={{ my: 2 }} />

          <Typography variant="subtitle2" gutterBottom>
            航段详情
          </Typography>

          <Box sx={{ maxHeight: 150, overflow: 'auto' }}>
            {segments.map((segment, index) => (
              <Box
                key={index}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  py: 0.5,
                  borderBottom: '1px solid #eee',
                }}
              >
                <Typography variant="body2" sx={{ flex: 1 }}>
                  {TRACK_SEGMENT_NAMES_CN[segment.name]}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mr: 2 }}>
                  {formatDistance(segment.distance)}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mr: 2 }}>
                  {segment.heading.toFixed(0)}°
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {segment.verticalAngle.toFixed(1)}°
                </Typography>
              </Box>
            ))}
          </Box>

          <Divider sx={{ my: 2 }} />
          <Typography variant="caption" color="text.secondary">
            规范提示和校验详情已写入底部信息栏；右上角图层开关可控制航线、限制面、包络和营地空域显示。
          </Typography>
        </Paper>
      )}
    </Box>
  );
};

export default TrackAnalysis;
