"""Track calculation API endpoints."""
import json
from pathlib import Path
from typing import Dict
from fastapi import APIRouter, HTTPException

from app.models.track import GeometryPreviewRequest, TrackRequest
from app.models.aircraft import Aircraft
from app.core.calculator import calculator
from app.core.validator import validator
from app.responses import success

router = APIRouter()

# Aircraft database path
AIRCRAFT_DATA_PATH = Path(__file__).parent.parent / "data" / "aircrafts.json"


def load_aircraft_database() -> Dict[str, Aircraft]:
    """Load aircraft database from JSON file."""
    if not AIRCRAFT_DATA_PATH.exists():
        return {}
    
    with open(AIRCRAFT_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    aircraft_dict = {}
    for item in data:
        aircraft = Aircraft(**item)
        aircraft_dict[aircraft.id] = aircraft
    
    return aircraft_dict


# Global aircraft database
_aircraft_db: Dict[str, Aircraft] = load_aircraft_database()


@router.post("/track/calculate")
async def calculate_track(request: TrackRequest):
    """Calculate flight circuit track (计算五边航迹).
    
    Args:
        request: Track calculation request with runway, aircraft, and config
        
    Returns:
        Wrapped track result with all segments and validation
    """
    # Validate runway parameters first
    runway_validation = validator.validate_runway(request.runway)
    if not runway_validation.is_valid:
        error_msgs = [e.message for e in runway_validation.errors if e.severity == 'error']
        return success(
            data=runway_validation.model_dump(by_alias=True),
            message=f"Runway parameters invalid: {error_msgs}"
        )
    
    # Get aircraft by ID
    if request.aircraft_id not in _aircraft_db:
        return success(
            data=None,
            message=f"Aircraft not found: {request.aircraft_id}"
        )
    
    aircraft = _aircraft_db[request.aircraft_id]
    
    try:
        # Calculate track
        result = calculator.calculate_circuit(
            runway=request.runway,
            aircraft=aircraft,
            config=request.config,
        )
        
        return success(data=result.model_dump(by_alias=True))
    except Exception as e:
        return success(
            data=None,
            message=f"Track calculation failed: {str(e)}"
        )


@router.post("/track/geometry-preview")
async def preview_track_geometry(request: GeometryPreviewRequest):
    """Resolve automatic/custom visual traffic pattern geometry parameters."""
    if request.aircraft_id not in _aircraft_db:
        return success(
            data=None,
            message=f"Aircraft not found: {request.aircraft_id}"
        )

    aircraft = _aircraft_db[request.aircraft_id]

    try:
        result = calculator.resolve_geometry_parameters(
            aircraft=aircraft,
            config=request.config,
        )
        return success(data=result.model_dump(by_alias=True))
    except Exception as e:
        return success(
            data=None,
            message=f"Geometry preview failed: {str(e)}"
        )


@router.post("/track/parameter-preview")
async def preview_track_parameters(request: GeometryPreviewRequest):
    """Resolve optional visual, OLS, and flight camp airspace parameters."""
    if request.aircraft_id not in _aircraft_db:
        return success(
            data=None,
            message=f"Aircraft not found: {request.aircraft_id}"
        )

    aircraft = _aircraft_db[request.aircraft_id]

    try:
        result = calculator.resolve_parameter_preview(
            aircraft=aircraft,
            config=request.config,
        )
        return success(data=result.model_dump(by_alias=True))
    except Exception as e:
        return success(
            data=None,
            message=f"Parameter preview failed: {str(e)}"
        )
