from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DataSourceDefinition:
    key: str
    aliases: tuple[str, ...]
    probe_url: str
    extraction_key: str | None


DATA_SOURCE_DEFINITIONS: tuple[DataSourceDefinition, ...] = (
    DataSourceDefinition(
        key="overpass",
        aliases=("overpass-api.de", "openstreetmap.org"),
        probe_url="https://overpass-api.de/api/status",
        extraction_key="overpass",
    ),
    DataSourceDefinition(
        key="open_topo_data",
        aliases=("opentopodata.org", "opentopography.org"),
        probe_url="https://api.opentopodata.org/v1/aster30m?locations=39.9042,116.4074",
        extraction_key="open_topo_data",
    ),
    DataSourceDefinition(
        key="open_elevation",
        aliases=("open-elevation.com",),
        probe_url="https://api.open-elevation.com/api/v1/lookup?locations=39.9042,116.4074",
        extraction_key="open_elevation",
    ),
    DataSourceDefinition(
        key="open_meteo",
        aliases=("open-meteo.com",),
        probe_url="https://api.open-meteo.com/v1/elevation?latitude=39.9042&longitude=116.4074",
        extraction_key="open_meteo",
    ),
    DataSourceDefinition(
        key="tianditu",
        aliases=("tianditu.cn",),
        probe_url="https://t0.tianditu.gov.cn",
        extraction_key=None,
    ),
    DataSourceDefinition(
        key="amap",
        aliases=("amap.com",),
        probe_url="https://restapi.amap.com/v3/elevation/coords",
        extraction_key=None,
    ),
    DataSourceDefinition(
        key="mapbar",
        aliases=("mapbar.com",),
        probe_url="https://www.mapbar.com",
        extraction_key=None,
    ),
)

_DEFAULT_TIMEOUT_S = 12.0


def _normalize_url(raw_url: str) -> str:
    value = str(raw_url or "").strip()
    if not value:
        raise ValueError("URL cannot be empty")
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value


def _find_definition_by_url(url: str) -> DataSourceDefinition | None:
    lower_url = url.lower()
    for definition in DATA_SOURCE_DEFINITIONS:
        if any(alias in lower_url for alias in definition.aliases):
            return definition
    return None


def identify_datasource(url: str) -> dict[str, Any]:
    normalized_url = _normalize_url(url)
    definition = _find_definition_by_url(normalized_url)
    return {
        "input_url": str(url or "").strip(),
        "normalized_url": normalized_url,
        "source_key": definition.key if definition else "custom",
        "source_type": definition.key if definition else None,
        "extraction_key": definition.extraction_key if definition else None,
        "extraction_supported": bool(definition and definition.extraction_key),
        "probe_url": definition.probe_url if definition else normalized_url,
    }


def _decode_json_payload(payload: bytes) -> Any | None:
    try:
        return json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _probe_once(url: str, timeout_s: float, verify_ssl: bool) -> tuple[int, int, str]:
    start = time.perf_counter()
    request = urllib.request.Request(url, headers={"User-Agent": "route-designer/1.0"})
    context = None if verify_ssl else ssl._create_unverified_context()
    with urllib.request.urlopen(request, timeout=timeout_s, context=context) as response:
        payload = response.read(2048)
        status_code = int(getattr(response, "status", 200))
        content_type = str(response.headers.get("content-type", ""))
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    # Some services return 200 with a JSON error payload; keep this observable.
    payload_json = _decode_json_payload(payload)
    if isinstance(payload_json, dict) and payload_json.get("error"):
        return status_code, elapsed_ms, f"JSON error payload: {payload_json.get('error')}"
    if "text/html" in content_type.lower() and "opentopography.org" in url.lower():
        return status_code, elapsed_ms, "Portal reachable"
    return status_code, elapsed_ms, "OK"


def test_datasource_access(url: str, timeout: int = 10) -> dict[str, Any]:
    info = identify_datasource(url)
    probe_url = info["probe_url"]
    timeout_s = float(timeout or _DEFAULT_TIMEOUT_S)
    attempts: list[str] = []

    parsed = urllib.parse.urlparse(probe_url)
    candidate_urls = [probe_url]
    if parsed.scheme == "https":
        candidate_urls.append(urllib.parse.urlunparse(("http",) + parsed[1:]))

    for candidate in candidate_urls:
        for verify_ssl in (True, False):
            try:
                status_code, elapsed_ms, note = _probe_once(candidate, timeout_s, verify_ssl)
                accessible = 200 <= status_code < 400
                return {
                    **info,
                    "accessible": accessible,
                    "status_code": status_code,
                    "response_time_ms": elapsed_ms,
                    "message": note if accessible else f"HTTP {status_code}",
                    "used_probe_url": candidate,
                    "ssl_verification": verify_ssl,
                }
            except (urllib.error.URLError, TimeoutError, ssl.SSLError, ValueError) as exc:
                attempts.append(f"{candidate} verify={verify_ssl}: {exc}")

    detail = " | ".join(attempts[-6:]) if attempts else "unknown error"
    return {
        **info,
        "accessible": False,
        "status_code": None,
        "response_time_ms": None,
        "message": f"Connection failed: {detail}",
        "used_probe_url": probe_url,
        "ssl_verification": None,
    }


def terrain_provider_priority(preferred_source: str | None) -> list[str]:
    default_order = [
        "osm_ele_tags",
        "open_topo_data",
        "open_topo_srtm90m",
        "open_meteo",
        "open_elevation",
    ]
    if not preferred_source:
        return default_order

    source = preferred_source.strip().lower()
    source_alias_map = {
        "overpass": "osm_ele_tags",
        "open_topo_data": "open_topo_data",
        "open_topography": "open_topo_data",
        "open_meteo": "open_meteo",
        "open_elevation": "open_elevation",
    }
    preferred_provider = source_alias_map.get(source)
    if not preferred_provider:
        return default_order

    order = [preferred_provider]
    for item in default_order:
        if item != preferred_provider:
            order.append(item)
    return order
