"""Runway-related Pydantic models."""
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Literal, List


def to_camel(string: str) -> str:
    """Convert snake_case to camelCase."""
    components = string.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])


class Coordinate(BaseModel):
    """Coordinate representation (坐标点表示)."""
    
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
    
    latitude: float = Field(
        ...,
        description="纬度，单位：度",
        ge=-90,
        le=90,
        examples=[39.9]
    )
    longitude: float = Field(
        ...,
        description="经度，单位：度",
        ge=-180,
        le=180,
        examples=[116.4]
    )
    
    @field_validator('latitude', 'longitude')
    @classmethod
    def validate_coordinate_precision(cls, v: float) -> float:
        """Validate coordinate has reasonable precision."""
        # Round to 6 decimal places for ~0.1m precision
        return round(v, 6)


class ValidationError(BaseModel):
    """Validation error for runway parameters (跑道参数校验错误)."""
    
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
    
    field: str = Field(..., description="错误字段名")
    message: str = Field(..., description="错误消息")
    severity: Literal["error", "warning"] = Field(
        default="error",
        description="错误级别"
    )


class RunwayValidationResult(BaseModel):
    """Runway validation result (跑道参数校验结果)."""
    
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
    
    is_valid: bool = Field(..., description="是否有效")
    errors: List[ValidationError] = Field(
        default_factory=list,
        description="校验错误列表"
    )


class RunwayParams(BaseModel):
    """Runway parameters for flight circuit calculation (跑道参数定义)."""
    
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
    
    coordinate: Coordinate = Field(
        ...,
        description="跑道中心点坐标"
    )
    magnetic_bearing: float = Field(
        ...,
        description="磁方位角，单位：度，范围0-360",
        ge=0,
        le=360,
        examples=[180]
    )
    length: int = Field(
        ...,
        description="跑道长度，单位：米",
        ge=200,
        le=5000,
        examples=[800]
    )
    elevation: float = Field(
        ...,
        description="跑道标高，单位：米",
        ge=-500,
        le=5000,
        examples=[50.0]
    )
    runway_width: float = Field(
        default=0,
        description="跑道宽度，单位：米（0=自动根据飞行区指标确定，>0=手动设定）",
        ge=0,
        le=100,
        examples=[18]
    )
    coordinate_system: Literal["WGS84", "GCJ02"] = Field(
        default="WGS84",
        description="输入坐标系类型"
    )
    
    @field_validator('magnetic_bearing')
    @classmethod
    def validate_magnetic_bearing(cls, v: float) -> float:
        """Normalize magnetic bearing to 0-360 range."""
        # Normalize to 0-360 if outside range
        if v < 0 or v > 360:
            v = v % 360
        return round(v, 1)
    
    @field_validator('length')
    @classmethod
    def validate_runway_length(cls, v: int) -> int:
        """Validate runway length is reasonable for light aircraft."""
        if v < 600:
            # Warning but still valid for ultra-light aircraft
            pass
        return v

    @field_validator('elevation')
    @classmethod
    def validate_elevation_precision(cls, v: float) -> float:
        """Keep runway elevation to 0.1m precision."""
        return round(v, 1)


class CoordinateInternal(BaseModel):
    """Internal coordinate with system tracking (内部坐标表示)."""
    
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
    
    lat: float = Field(..., description="WGS84纬度")
    lng: float = Field(..., description="WGS84经度")
    original_system: Literal["WGS84", "GCJ02"] = Field(
        default="WGS84",
        description="用户输入时的坐标系"
    )
