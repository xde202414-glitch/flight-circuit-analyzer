"""Test track API endpoints."""
import asyncio
import json

from app.api.track import preview_track_geometry, preview_track_parameters
from app.api.config import get_map_config
from app.models.track import (
    FlightCampAirspaceConfig,
    GeometryPreviewRequest,
    ObstacleSurfaceConfig,
    TrackConfig,
)


def test_geometry_preview_endpoint_returns_auto_values():
    """Test geometry preview endpoint returns automatic geometry values."""
    response = asyncio.run(preview_track_geometry(
        GeometryPreviewRequest(
            aircraft_id="cessna-172",
            config=TrackConfig(
                circuit_height=300,
                bank_angle=15,
                active_runway_end="primary",
                traffic_pattern_side="left",
                wind_correction=False,
            ),
        )
    ))

    assert response.status_code == 200
    data = json.loads(response.body)["data"]
    assert data["departureLegLength"]["source"] == "auto"
    assert data["departureLegLength"]["value"] == 2000
    assert data["departureLegLength"]["automaticValue"] == 2000
    assert data["finalLegLength"]["value"] == 2600


def test_geometry_preview_endpoint_returns_custom_values():
    """Test geometry preview endpoint marks custom geometry values."""
    response = asyncio.run(preview_track_geometry(
        GeometryPreviewRequest(
            aircraft_id="cessna-172",
            config=TrackConfig(
                circuit_height=300,
                bank_angle=15,
                active_runway_end="primary",
                traffic_pattern_side="left",
                departure_leg_length=2700,
                final_leg_length=2700,
                turn_radius=1400,
                downwind_offset=2800,
                wind_correction=False,
            ),
        )
    ))

    assert response.status_code == 200
    data = json.loads(response.body)["data"]
    assert data["departureLegLength"]["value"] == 2700.0
    assert data["departureLegLength"]["automaticValue"] == 2000.0
    assert data["departureLegLength"]["source"] == "custom"
    assert data["finalLegLength"]["source"] == "custom"
    assert data["turnRadius"]["source"] == "custom"
    assert data["downwindOffset"]["source"] == "custom"


def test_parameter_preview_endpoint_returns_normative_sections():
    """Test parameter preview endpoint returns visual, OLS, and flight camp sections."""
    response = asyncio.run(preview_track_parameters(
        GeometryPreviewRequest(
            aircraft_id="cessna-172",
            config=TrackConfig(
                circuit_height=300,
                bank_angle=15,
                obstacle_surfaces=ObstacleSurfaceConfig(code_number="2"),
                flight_camp_airspace=FlightCampAirspaceConfig(
                    camp_type="helicopter",
                    radius_m=5000,
                    true_height_m=300,
                ),
            ),
        )
    ))

    assert response.status_code == 200
    data = json.loads(response.body)["data"]
    assert data["visualPattern"]["departureLegLength"]["value"] == 2000
    assert data["obstacleSurfaces"]["approachLength"]["value"] == 2500
    assert data["obstacleSurfaces"]["codeNumber"]["value"] == "2"
    assert data["flightCampAirspace"]["campType"]["value"] == "helicopter"
    assert data["flightCampAirspace"]["radius"]["value"] == 5000


def test_map_config_endpoint_returns_defaults():
    """Test map config endpoint returns frontend map defaults."""
    response = asyncio.run(get_map_config())

    assert response.status_code == 200
    data = json.loads(response.body)["data"]
    assert data["defaultCenter"]["latitude"] == 30.2741
    assert data["defaultCenter"]["longitude"] == 120.1551
    assert data["defaultZoom"] == 13
    assert "tiandituKey" in data
