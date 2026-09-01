from dataclasses import dataclass


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
class OverlaySnapshot:
    game: str
    location: str
    sections: tuple[PanelSection, ...]
    map_position: MapPosition | None = None
    supports_caught_filter: bool = False