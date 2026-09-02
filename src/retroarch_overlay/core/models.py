from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class RetroArchStatus:
    state: str
    core: str = ""
    content: str = ""
    content_crc32: str = ""


@dataclass(frozen=True, slots=True)
class PanelRow:
    text: str
    caught: bool | None = None


@dataclass(frozen=True, slots=True)
class PanelAction:
    label: str
    title: str
    rows: tuple[PanelRow, ...]


@dataclass(frozen=True, slots=True)
class PanelSection:
    title: str
    rows: tuple[PanelRow, ...]
    preview_limit: int | None = None
    alert: bool = False
    actions: tuple[PanelAction, ...] = ()


@dataclass(frozen=True, slots=True)
class MapPosition:
    area: str
    map_id: int
    x: int
    y: int
    is_world: bool = False


@dataclass(frozen=True, slots=True)
class MapWaypoint:
    x: int
    y: int
    title: str
    detail: str = ""
    kind: str = "point"
    completed: bool = False


@dataclass(frozen=True, slots=True)
class MapRegion:
    x: int
    y: int
    width: int
    height: int
    title: str
    detail: str = ""
    kind: str = "region"
    color: str = "#f8c24e"


@dataclass(frozen=True, slots=True)
class MapLayer:
    key: str
    title: str
    area: str
    image_path: Path
    source_url: str = ""
    credit: str = ""
    tile_width: int = 16
    tile_height: int = 16
    offset_x: int = 0
    offset_y: int = 0
    anchor_x: int = 0
    anchor_y: int = 0
    wrap_width: int = 256
    wrap_height: int = 256
    map_id: int | None = None
    image_loader: Callable[[], Path] | None = None
    waypoints: tuple[MapWaypoint, ...] = ()
    regions: tuple[MapRegion, ...] = ()


@dataclass(frozen=True, slots=True)
class MapDocument:
    title: str
    layers: tuple[MapLayer, ...]
    overlay_kinds: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MapOverlay:
    layer_key: str
    waypoints: tuple[MapWaypoint, ...]


@dataclass(frozen=True, slots=True)
class OverlaySnapshot:
    game: str
    location: str
    sections: tuple[PanelSection, ...]
    map_position: MapPosition | None = None
    supports_caught_filter: bool = False
    map_document: MapDocument | None = None
    map_overlays: tuple[MapOverlay, ...] = ()