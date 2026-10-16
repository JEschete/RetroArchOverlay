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
class PanelChip:
    """A small colored badge rendered after a row's text (type, status, verdict)."""

    text: str
    background: str = "#687064"
    foreground: str = "#ffffff"


@dataclass(frozen=True, slots=True)
class PanelMeter:
    label: str
    value: int
    maximum: int
    color: str = ""
    infinite: bool = False


@dataclass(frozen=True, slots=True)
class PanelRow:
    text: str
    caught: bool | None = None
    tooltip: str = ""
    # Optional structure. Hosts that predate these fields ignore them.
    emphasis: str = ""  # "", "heading", "muted", "success", "warning", "danger"
    progress: float | None = None  # 0.0-1.0 renders a bar under the text
    progress_color: str = ""  # "" picks a color from the progress value
    icon: str = ""  # absolute path to a small image rendered before the text
    chips: tuple[PanelChip, ...] = ()
    meters: tuple[PanelMeter, ...] = ()
    detail: str = ""  # secondary lines rendered muted under the text


@dataclass(frozen=True, slots=True)
class PanelColumn:
    key: str
    title: str
    rows: tuple[PanelRow, ...] = ()


@dataclass(frozen=True, slots=True)
class PanelAction:
    label: str
    title: str
    rows: tuple[PanelRow, ...]
    compact: bool = False
    key: str = ""
    map_layer_key: str = ""
    command: Callable[[], None] | None = None
    # Scrolls the section's markdown document to this heading anchor.
    document_anchor: str = ""


@dataclass(frozen=True, slots=True)
class PanelNumberInput:
    label: str
    value: int
    minimum: int = 0
    maximum: int = 2_147_483_647
    step: int = 1
    key: str = ""
    enabled: bool = True
    command: Callable[[int], None] | None = None


@dataclass(frozen=True, slots=True)
class PanelSection:
    title: str
    rows: tuple[PanelRow, ...]
    preview_limit: int | None = None
    alert: bool = False
    actions: tuple[PanelAction, ...] = ()
    priority: int = 50
    role: str = "context"
    compact_rows: tuple[PanelRow, ...] = ()
    key: str = ""
    columns: tuple[PanelColumn, ...] = ()
    markdown: str = ""
    collapsible: bool = True
    inputs: tuple[PanelNumberInput, ...] = ()


@dataclass(frozen=True, slots=True)
class GameDisplaySpec:
    layout_key: str
    native_width: int
    native_height: int
    scaling: str = "fit"
    preferred_integer_scale: int | None = None


@dataclass(frozen=True, slots=True)
class ScreenRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass(frozen=True, slots=True)
class LayoutProfile:
    mode: str = "auto"
    rail_side: str = "right"
    rail_width: int = 360
    density: str = "compact"
    game_scaling: str = "auto"
    manage_retroarch_window: bool = True


@dataclass(frozen=True, slots=True)
class WindowGeometry:
    handle: int
    window_rect: ScreenRect
    client_rect: ScreenRect
    work_area: ScreenRect
    dpi: int = 96
    resizable: bool = False


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
    completed: bool | None = False
    marker: str = ""
    # A sprite to draw in place of the marker glyph, for plugins that can decode
    # the real actor graphics out of the cartridge.
    image_path: Path | None = None


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
    label: str = ""
    compact_label: str = ""


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
    # True only for genuinely toroidal maps, where walking off one edge brings
    # you out of the other. Everything else clamps at its borders.
    wraps: bool = False
    image_variants: tuple[MapLayer, ...] = ()


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
    display_spec: GameDisplaySpec | None = None