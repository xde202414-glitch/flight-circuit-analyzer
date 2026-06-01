/**
 * ValidationReport Component - Displays track validation results
 * 合规校验报告组件 - 显示航迹校验结果
 */
import React from 'react';
import {
  Box,
  Alert,
  AlertTitle,
  Chip,
  Collapse,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import {
  CheckCircle as CheckIcon,
  Warning as WarningIcon,
  Error as ErrorIcon,
} from '@mui/icons-material';
import { ValidationReport as ValidationReportType } from '../../types/track';

interface ValidationReportProps {
  /** Validation report data */
  report?: ValidationReportType;
}

/**
 * ValidationReport Component
 * Visualizes track validation errors and warnings
 */
const ValidationReport: React.FC<ValidationReportProps> = ({ report }) => {
  if (!report) {
    return null;
  }
  
  const hasErrors = report.errors.length > 0;
  const hasWarnings = report.warnings.length > 0;
  
  return (
    <Box sx={{ mt: 1 }}>
      {/* Overall Status */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
        {report.isValid ? (
          <Chip
            icon={<CheckIcon />}
            label="航迹有效"
            color="success"
            size="small"
          />
        ) : (
          <Chip
            icon={<ErrorIcon />}
            label="航迹无效"
            color="error"
            size="small"
          />
        )}
        
        {hasWarnings && (
          <Chip
            icon={<WarningIcon />}
            label={`${report.warnings.length} 个警告`}
            color="warning"
            size="small"
            sx={{ ml: 1 }}
          />
        )}
        
        {hasErrors && (
          <Chip
            icon={<ErrorIcon />}
            label={`${report.errors.length} 个错误`}
            color="error"
            size="small"
            sx={{ ml: 1 }}
          />
        )}
      </Box>
      
      {/* Errors List */}
      <Collapse in={hasErrors}>
        <Alert severity="error" sx={{ mb: 1 }}>
          <AlertTitle>错误 ({report.errors.length})</AlertTitle>
          <List dense disablePadding>
            {report.errors.map((error, index) => (
              <ListItem key={index} dense disableGutters>
                <ListItemIcon sx={{ minWidth: 30 }}>
                  <ErrorIcon color="error" fontSize="small" />
                </ListItemIcon>
                <ListItemText
                  primary={error.message}
                  secondary={error.code}
                  primaryTypographyProps={{ variant: 'body2' }}
                  secondaryTypographyProps={{ variant: 'caption' }}
                />
              </ListItem>
            ))}
          </List>
        </Alert>
      </Collapse>
      
      {/* Warnings List */}
      <Collapse in={hasWarnings}>
        <Alert severity="warning">
          <AlertTitle>警告 ({report.warnings.length})</AlertTitle>
          <List dense disablePadding>
            {report.warnings.map((warning, index) => (
              <ListItem key={index} dense disableGutters>
                <ListItemIcon sx={{ minWidth: 30 }}>
                  <WarningIcon color="warning" fontSize="small" />
                </ListItemIcon>
                <ListItemText
                  primary={warning.message}
                  secondary={warning.code}
                  primaryTypographyProps={{ variant: 'body2' }}
                  secondaryTypographyProps={{ variant: 'caption' }}
                />
              </ListItem>
            ))}
          </List>
        </Alert>
      </Collapse>
      
      {/* Success Message */}
      <Collapse in={report.isValid && !hasWarnings}>
        <Alert severity="success" icon={<CheckIcon />}>
          航迹计算完成，所有参数符合目视飞行程序设计规范
        </Alert>
      </Collapse>
    </Box>
  );
};

export default ValidationReport;
