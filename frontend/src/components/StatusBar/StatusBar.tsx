import React from 'react';
import {
  Box,
  Button,
  Chip,
  Collapse,
  Divider,
  Stack,
  Typography,
} from '@mui/material';
import { useStatusStore, StatusSeverity } from '../../store/useStatusStore';

const STATUS_LABELS: Record<StatusSeverity, string> = {
  info: '信息',
  success: '完成',
  warning: '提示',
  error: '错误',
};

const STATUS_COLORS: Record<StatusSeverity, string> = {
  info: '#2563eb',
  success: '#15803d',
  warning: '#b45309',
  error: '#dc2626',
};

const formatTime = (timestamp: number): string =>
  new Date(timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

const StatusBar: React.FC = () => {
  const current = useStatusStore((state) => state.current);
  const history = useStatusStore((state) => state.history);
  const clearHistory = useStatusStore((state) => state.clearHistory);
  const [expanded, setExpanded] = React.useState(false);

  return (
    <Box
      sx={{
        height: expanded ? 220 : 72,
        flexShrink: 0,
        borderTop: '1px solid #d6dde8',
        bgcolor: '#f8fafc',
        boxShadow: '0 -2px 12px rgba(15, 23, 42, 0.08)',
        transition: 'height 160ms ease',
        overflow: 'hidden',
      }}
    >
      <Stack
        direction="row"
        spacing={1.5}
        alignItems="center"
        sx={{ height: 72, px: 2 }}
      >
        <Chip
          size="small"
          label={STATUS_LABELS[current.severity]}
          sx={{
            bgcolor: STATUS_COLORS[current.severity],
            color: 'white',
            fontWeight: 700,
            minWidth: 58,
          }}
        />
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography variant="subtitle2" noWrap>
            {current.title}
          </Typography>
          <Typography variant="body2" color="text.secondary" noWrap>
            {current.message}
          </Typography>
          {current.source && (
            <Typography variant="caption" color="text.secondary" noWrap>
              {current.source}
            </Typography>
          )}
        </Box>
        <Typography variant="caption" color="text.secondary">
          {formatTime(current.timestamp)}
        </Typography>
        <Button size="small" onClick={() => setExpanded((value) => !value)}>
          {expanded ? '收起' : '历史'}
        </Button>
        <Button size="small" onClick={clearHistory}>
          清空
        </Button>
      </Stack>

      <Collapse in={expanded}>
        <Divider />
        <Box sx={{ maxHeight: 146, overflow: 'auto', px: 2, py: 1 }}>
          {history.map((item) => (
            <Stack
              key={item.id}
              direction="row"
              spacing={1}
              alignItems="baseline"
              sx={{ py: 0.5 }}
            >
              <Typography
                variant="caption"
                sx={{ width: 72, color: STATUS_COLORS[item.severity], fontWeight: 700 }}
              >
                {STATUS_LABELS[item.severity]}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ width: 72 }}>
                {formatTime(item.timestamp)}
              </Typography>
              <Typography variant="body2" sx={{ minWidth: 130 }}>
                {item.title}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
                {item.message}
              </Typography>
            </Stack>
          ))}
        </Box>
      </Collapse>
    </Box>
  );
};

export default StatusBar;
