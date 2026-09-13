from .models import MapDocument, MapLayer, MapPosition, MapWaypoint


MIN_MAP_OPACITY = 0.3


def map_viewport(position: MapPosition, local: bool) -> tuple[int, int, int, int]:
    if not local and position.is_world:
        return 0, 0, 255, 255
    left = (position.x // 16) * 16 - 8
    top = (position.y // 16) * 16 - 8
    return left, top, left + 31, top + 31


def project_map_point(
    x: int,
    y: int,
    viewport: tuple[int, int, int, int],
    width: int,
    height: int,
    padding: int = 24,
) -> tuple[float, float]:
    left, top, right, bottom = viewport
    usable_width = max(width - padding * 2, 1)
    usable_height = max(height - padding * 2, 1)
    return (
        padding + (x - left) * usable_width / max(right - left, 1),
        padding + (y - top) * usable_height / max(bottom - top, 1),
    )


def map_source_point(position: MapPosition, layer: MapLayer) -> tuple[int, int]:
    return (
        ((position.x + layer.offset_x) % layer.wrap_width) * layer.tile_width
        + layer.anchor_x,
        ((position.y + layer.offset_y) % layer.wrap_height) * layer.tile_height
        + layer.anchor_y,
    )


def uses_marker_glyph(waypoint: MapWaypoint) -> bool:
    return bool(waypoint.marker) or waypoint.kind == "npcs"


def clamp_opacity(value: float) -> float:
    return max(MIN_MAP_OPACITY, min(1.0, float(value)))


def waypoint_source_point(waypoint: MapWaypoint, layer: MapLayer) -> tuple[int, int]:
    return (
        ((waypoint.x + layer.offset_x) % layer.wrap_width) * layer.tile_width
        + layer.anchor_x,
        ((waypoint.y + layer.offset_y) % layer.wrap_height) * layer.tile_height
        + layer.anchor_y,
    )


def append_map_path(
    points: list[tuple[int, int]],
    point: tuple[int, int],
    limit: int = 50_000,
) -> None:
    if points and points[-1] == point:
        return
    points.append(point)
    if len(points) > limit:
        del points[: len(points) - limit]


def record_map_path(
    document: MapDocument,
    position: MapPosition,
    paths: dict[str, list[tuple[int, int]]],
) -> None:
    layer = map_layer_for_position(document, position)
    if layer is not None:
        append_map_path(
            paths.setdefault(layer.key, []),
            map_source_point(position, layer),
        )


def wrapped_map_delta(point: float, center: float, span: int) -> float:
    return (point - center + span / 2) % span - span / 2


def tooltip_shift(
    bounds: tuple[float, float, float, float],
    width: float,
    height: float,
    margin: float = 6,
) -> tuple[float, float]:
    left, top, right, bottom = bounds
    shift_x = 0.0
    shift_y = 0.0
    if right + margin > width:
        shift_x = width - margin - right
    if left + shift_x < margin:
        shift_x = margin - left
    if bottom + margin > height:
        shift_y = height - margin - bottom
    if top + shift_y < margin:
        shift_y = margin - top
    return shift_x, shift_y


def clamped_view_origin(center: float, view_span: int, source_span: int) -> int:
    if view_span >= source_span:
        return 0
    return int(max(0, min(source_span - view_span, round(center - view_span / 2))))


def view_origin(
    center: float,
    view_span: int,
    source_span: int,
    wraps: bool,
) -> int:
    if not wraps:
        return clamped_view_origin(center, view_span, source_span)
    return int(round(center - view_span / 2)) % max(source_span, 1)


def view_delta(coord: float, origin: float, span: int, wraps: bool) -> float:
    if not wraps:
        return coord - origin
    return (coord - origin) % max(span, 1)


def tracked_map_position(
    previous: MapPosition | None,
    current: MapPosition,
) -> MapPosition | None:
    return current if current.is_world else previous


def map_layer_for_position(
    document: MapDocument,
    position: MapPosition,
) -> MapLayer | None:
    if not position.is_world:
        matching_id = next(
            (layer for layer in document.layers if layer.map_id == position.map_id),
            None,
        )
        if matching_id is not None:
            return matching_id
    return next(
        (
            layer
            for layer in document.layers
            if layer.map_id is None and layer.area == position.area
        ),
        None,
    )