"""Runway parameters API endpoints."""
from fastapi import APIRouter, HTTPException

from app.models.runway import RunwayParams, RunwayValidationResult
from app.models.track import CoordinateTransformRequest, CoordinateTransformResponse
from app.core.validator import validator
from app.core.coordinate import transformer
from app.responses import success

router = APIRouter()


@router.post("/runway/validate")
async def validate_runway(params: RunwayParams):
    """Validate runway parameters (校验跑道参数).
    
    Args:
        params: Runway parameters to validate
        
    Returns:
        Wrapped validation result with errors and warnings
    """
    result = validator.validate_runway(params)
    return success(data=result.model_dump(by_alias=True))


@router.post("/coordinate/transform")
async def transform_coordinate(request: CoordinateTransformRequest):
    """Transform coordinate between WGS84 and GCJ-02 (坐标系转换).
    
    Args:
        request: Coordinate transformation request
        
    Returns:
        Wrapped transformed coordinate
    """
    try:
        if request.from_system == "WGS84" and request.to_system == "GCJ02":
            transformed = transformer.wgs84_to_gcj02(request.coordinate)
        elif request.from_system == "GCJ02" and request.to_system == "WGS84":
            transformed = transformer.gcj02_to_wgs84(request.coordinate)
        elif request.from_system == request.to_system:
            transformed = request.coordinate
        else:
            return success(
                data=None,
                message=f"Unsupported coordinate transformation: {request.from_system} -> {request.to_system}"
            )
        
        result = CoordinateTransformResponse(
            coordinate=transformed,
            original_system=request.from_system,
            target_system=request.to_system,
        )
        return success(data=result.model_dump(by_alias=True))
    except Exception as e:
        return success(
            data=None,
            message=f"Coordinate transformation failed: {str(e)}"
        )