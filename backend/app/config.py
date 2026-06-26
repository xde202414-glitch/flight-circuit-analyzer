"""Application configuration settings."""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Literal

_ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
_BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Settings
    app_name: str = "飞行营地飞行程序分析工具"
    app_version: str = "1.0.0"
    api_prefix: str = "/api/v1"

    # Server Settings
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # CORS Settings
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001", "*"]

    # Coordinate System Settings
    default_coordinate_system: Literal["WGS84", "GCJ02"] = "WGS84"

    # Map Settings
    default_map_latitude: float = 30.2741
    default_map_longitude: float = 120.1551
    default_map_zoom: int = 13
    tianditu_key: str = ""
    amap_key: str = ""
    geovis_token: str = ""

    # Calculation Settings
    default_circuit_height: int = 300
    default_bank_angle: int = 15
    default_safety_margin: int = 100

    # Magnetic Variation
    default_magnetic_variation: float = 0.0

    # Auth Settings
    secret_key: str = "change-me-to-a-random-secret-in-production"
    access_token_expire_minutes: int = 480  # 8 hours
    algorithm: str = "HS256"

    # Route 10 Integration Settings
    route_data_dir: str = ""

    model_config = {
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "allow",
    }


# Global settings instance
settings = Settings()

# Route 10 compatibility constants (computed from settings)
if settings.route_data_dir:
    DATA_DIR = Path(settings.route_data_dir)
else:
    DATA_DIR = _BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
EXPORT_DIR = DATA_DIR / "exports"
CACHE_DIR = DATA_DIR / "cache"
IMPORT_DIR = DATA_DIR / "imports"
DEFAULT_MAP_CENTER = (settings.default_map_latitude, settings.default_map_longitude)
DEFAULT_MAP_ZOOM = settings.default_map_zoom
TIANDITU_KEY = settings.tianditu_key
