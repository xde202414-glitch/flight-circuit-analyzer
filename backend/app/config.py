"""Application configuration settings."""
import os
from pydantic_settings import BaseSettings
from typing import Literal

_ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


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
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"]

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
    default_circuit_height: int = 300  # meters, 起落航线高度
    default_bank_angle: int = 15  # degrees, 转弯坡度
    default_safety_margin: int = 100  # meters, 安全场余量

    # Magnetic Variation (磁偏角)
    default_magnetic_variation: float = 0.0  # degrees

    model_config = {
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
    }


# Global settings instance
settings = Settings()
