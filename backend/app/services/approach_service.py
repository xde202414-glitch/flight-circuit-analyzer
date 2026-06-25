from shapely import LineString, Point


def build_approach_lines(centerline_local: LineString, landing_points_local: list[Point]) -> list[LineString]:
    lines: list[LineString] = []
    for landing in landing_points_local:
        distance = centerline_local.project(landing)
        nearest_on_route = centerline_local.interpolate(distance)
        lines.append(LineString([landing, nearest_on_route]))
    return lines

