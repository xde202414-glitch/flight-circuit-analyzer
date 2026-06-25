from collections.abc import Callable

from pyproj import CRS, Transformer


def build_local_transformers(ref_lon: float, ref_lat: float) -> tuple[Callable, Callable]:
    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={ref_lat} +lon_0={ref_lon} +datum=WGS84 +units=m +no_defs"
    )
    wgs84 = CRS.from_epsg(4326)
    to_local_transformer = Transformer.from_crs(wgs84, local_crs, always_xy=True)
    to_wgs84_transformer = Transformer.from_crs(local_crs, wgs84, always_xy=True)
    return to_local_transformer.transform, to_wgs84_transformer.transform

