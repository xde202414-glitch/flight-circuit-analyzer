"""Aircraft database API endpoints."""
import json
from pathlib import Path
from typing import Dict
from fastapi import APIRouter, HTTPException

from app.models.aircraft import Aircraft, AircraftListResponse
from app.responses import success

router = APIRouter()

# Aircraft database path
AIRCRAFT_DATA_PATH = Path(__file__).parent.parent / "data" / "aircrafts.json"


def load_aircraft_database() -> Dict[str, Aircraft]:
    """Load aircraft database from JSON file.
    
    Returns:
        Dictionary mapping aircraft ID to Aircraft model
    """
    if not AIRCRAFT_DATA_PATH.exists():
        return {}
    
    with open(AIRCRAFT_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    aircraft_dict = {}
    for item in data:
        aircraft = Aircraft(**item)
        aircraft_dict[aircraft.id] = aircraft
    
    return aircraft_dict


# Global aircraft database (loaded once)
_aircraft_db: Dict[str, Aircraft] = load_aircraft_database()


@router.get("/aircrafts")
async def list_aircrafts():
    """Get list of all available aircraft (获取机型列表).
    
    Returns:
        Wrapped response with list of all aircraft
    """
    if not _aircraft_db:
        return success(
            data=AircraftListResponse(aircrafts=[], total=0).model_dump(by_alias=True),
            message="Aircraft database is empty"
        )
    
    aircrafts = list(_aircraft_db.values())
    
    return success(
        data=AircraftListResponse(
            aircrafts=aircrafts,
            total=len(aircrafts),
        ).model_dump(by_alias=True),
    )


@router.get("/aircrafts/{aircraft_id}")
async def get_aircraft(aircraft_id: str):
    """Get single aircraft by ID (获取单个机型详情).
    
    Args:
        aircraft_id: Aircraft unique identifier
        
    Returns:
        Wrapped response with aircraft details
    """
    if aircraft_id not in _aircraft_db:
        return success(
            data=None,
            message=f"Aircraft not found: {aircraft_id}"
        )
    
    return success(data=_aircraft_db[aircraft_id].model_dump(by_alias=True))