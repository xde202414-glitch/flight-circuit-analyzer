"""Aircraft-related Pydantic models."""
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal, List


def to_camel(string: str) -> str:
    """Convert snake_case to camelCase."""
    components = string.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])


class Aircraft(BaseModel):
    """Aircraft performance parameters (机型性能参数)."""
    
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
    
    id: str = Field(..., description="机型唯一标识")
    name: str = Field(..., description="机型名称")
    manufacturer: str = Field(..., description="制造商")
    cruise_speed: int = Field(
        ...,
        description="巡航速度，单位：km/h",
        ge=40,
        le=900,
        examples=[222]
    )
    climb_rate: float = Field(
        ...,
        description="爬升率，单位：m/s",
        ge=1,
        le=50,
        examples=[3.5]
    )
    turn_radius: int = Field(
        ...,
        description="转弯半径，单位：米",
        ge=100,
        le=5000,
        examples=[350]
    )
    approach_speed: int = Field(
        ...,
        description="进近速度，单位：km/h",
        ge=35,
        le=300,
        examples=[130]
    )
    max_altitude: int = Field(
        ...,
        description="最大高度，单位：米",
        ge=1000,
        le=15000,
        examples=[4300]
    )
    stall_speed: int = Field(
        ...,
        description="失速速度，单位：km/h",
        ge=20,
        le=200,
        examples=[93]
    )
    category: Literal["light", "medium", "heavy"] = Field(
        default="light",
        description="机型类别"
    )
    vfr_pattern_class: Literal["A", "B", "C", "D"] = Field(
        default="B",
        description="VFR traffic pattern design class",
    )
    vfr_max_ias_kmh: int = Field(
        default=250,
        description="Maximum IAS for the VFR procedure in km/h",
        ge=80,
        le=500,
    )
    engine_type: Literal["piston", "turboprop", "jet"] = Field(
        default="piston",
        description="发动机类型"
    )
    flight_camp_category: Literal[
        "glider",
        "aerobatic",
        "powered_hang_glider",
        "light_aircraft",
        "helicopter",
        "gyroplane",
        "balloon_airship",
        "hang_glider",
        "paraglider",
        "powered_paraglider",
        "aero_model",
        "water_sport_aircraft",
        "skydiving",
    ] = Field(
        default="light_aircraft",
        description="Recommended flight camp airspace category",
    )
    description: str = Field(
        default="",
        description="机型描述"
    )


class AircraftListResponse(BaseModel):
    """Aircraft list response (机型列表响应)."""
    
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
    
    aircrafts: List[Aircraft] = Field(
        default_factory=list,
        description="机型列表"
    )
    total: int = Field(
        default=0,
        description="总数"
    )
