import logging
import tkinter as tk
import time
import webbrowser
from tkinter import font as tkfont

from PIL import Image, ImageChops, ImageTk

from .app.controller import OverlayController, OverlayDiagnostic, SnapshotCadence
from .adapters.base import AdapterRegistry
from .core.layout import sections_for_role
from .infrastructure.accessibility import windows_high_contrast_enabled
from .infrastructure.logging_config import UIHangWatchdog
from .models import LayoutProfile, MapDocument, MapLayer, MapOverlay, MapPosition, MapRegion, MapWaypoint, OverlaySnapshot, PanelAction, PanelRow, PanelSection, ScreenRect
from .local_settings import LocalPluginSettings
from .presentation.tk.layout import ResponsiveLayoutManager
from .presentation.tk.layout_dialog import LayoutSettingsDialog
from .retroarch import RetroArchClient


LOGGER = logging.getLogger(__name__)


def clamp_overlay_size(
    width: int,
    height: int,
    screen_width: int,
    screen_height: int,
    *,
    minimum_width: int = 280,
    minimum_height: int = 180,
) -> tuple[int, int]:
    maximum_width = max(minimum_width, screen_width - 24)
    maximum_height = max(minimum_height, screen_height - 24)
    return (
        min(max(int(width), minimum_width), maximum_width),
        min(max(int(height), minimum_height), maximum_height),
    )


def mouse_wheel_units(event: object) -> int:
    delta = getattr(event, "delta", 0)
    if isinstance(delta, int) and delta:
        units = max(1, abs(delta) // 120)
        return -units if delta > 0 else units
    button = getattr(event, "num", 0)
    if button == 4:
        return -1
    if button == 5:
        return 1
    return 0


def party_detail_row_role(text: str) -> str:
    if text.startswith("Stats |"):
        return "stats"
    if text.startswith("DVs |"):
        return "dvs"
    if text.startswith("Stat EXP |"):
        return "stat_exp"
    if text.startswith("Moves |"):
        return "moves"
    if " | EXP " in text and " | OT " in text:
        return "pokemon"
    return "generic"


def filter_caught_sections(
    sections: tuple[PanelSection, ...], hide_caught: bool
) -> tuple[PanelSection, ...]:
    if not hide_caught:
        return sections
    return tuple(
        PanelSection(
            section.title,
            tuple(row for row in section.rows if row.caught is not True),
            section.preview_limit,
            section.alert,
            section.actions,
            section.priority,
            section.role,
            tuple(row for row in section.compact_rows if row.caught is not True),
        )
        for section in sections
        if any(row.caught is not True for row in section.rows)
    )


def preview_section_rows(
    section: PanelSection, expanded: bool
) -> tuple[tuple[PanelRow, ...], int]:
    if expanded or section.preview_limit is None:
        return section.rows, 0
    visible = section.rows[: section.preview_limit]
    return visible, len(section.rows) - len(visible)


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


def waypoint_source_point(waypoint: MapWaypoint, layer: MapLayer) -> tuple[int, int]:
    return (
        ((waypoint.x + layer.offset_x) % layer.wrap_width) * layer.tile_width
        + layer.anchor_x,
        ((waypoint.y + layer.offset_y) % layer.wrap_height) * layer.tile_height
        + layer.anchor_y,
    )


def append_map_path(
    points: list[tuple[int, int]], point: tuple[int, int], limit: int = 50_000
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


def tracked_map_position(
    previous: MapPosition | None, current: MapPosition
) -> MapPosition | None:
    return current if current.is_world else previous


def map_layer_for_position(
    document: MapDocument, position: MapPosition
) -> MapLayer | None:
    if not position.is_world:
        matching_id = next(
            (layer for layer in document.layers if layer.map_id == position.map_id),
            None,
        )
        if matching_id is not None:
            return matching_id
    return next(
        (layer for layer in document.layers if layer.map_id is None and layer.area == position.area),
        None,
    )


class CoordinateMapWindow:
    ZOOM_LEVELS = (1, 2, 4, 8, 16)
    IMAGE_CACHE_LIMIT = 4
    PATH_CHUNK_POINTS = 1024
    PATH_INCREMENT_LIMIT = 128
    RESIZE_REDRAW_DELAY_MS = 50
    OBJECTIVE_FLASH_INTERVAL_MS = 450
    OVERLAY_LABELS = {
        "player": "Player",
        "path": "Hero's path",
        "objective": "Next objective",
        "entrance": "Entrances",
        "collectibles": "Collectibles",
        "npcs": "NPCs",
        "encounters": "Enemies",
    }
    HIDDEN_OVERLAYS = frozenset(("path", "collectibles", "npcs", "encounters"))

    def __init__(
        self,
        owner: tk.Tk,
        document: MapDocument,
        compact: bool = False,
        initial_geometry: ScreenRect | None = None,
        hero_paths: dict[str, list[tuple[int, int]]] | None = None,
        hang_watchdog: UIHangWatchdog | None = None,
    ) -> None:
        if not document.layers:
            raise ValueError("Map document must contain at least one layer")
        self.document = document
        self.layers = {layer.key: layer for layer in document.layers}
        self.compact = compact
        self.position: MapPosition | None = None
        self._indoor_map_id: int | None = None
        self.zoom = 1
        self._pan_source = (0.0, 0.0)
        self._pan_drag_start = (0, 0)
        self._pan_drag_origin = (0.0, 0.0)
        self._photo: ImageTk.PhotoImage | None = None
        self._photo_key: tuple[object, ...] | None = None
        self._images: dict[str, Image.Image] = {}
        self._fit_images: dict[tuple[str, int, int], Image.Image] = {}
        self._redraw_job: str | None = None
        self._objective_flash_job: str | None = None
        self._objective_flash_visible = True
        self._destroyed = False
        self._drawn_path_lengths: dict[str, int] = {}
        self._overlay_waypoints: dict[str, tuple[MapWaypoint, ...]] = {}
        self._hero_paths = hero_paths if hero_paths is not None else {}
        self._hang_watchdog = hang_watchdog
        self._dynamic_update_count = 0
        available_kinds = (
            set(document.overlay_kinds)
            | {waypoint.kind for layer in document.layers for waypoint in layer.waypoints}
            | {region.kind for layer in document.layers for region in layer.regions}
            | {"player", "path"}
        )
        preferred_order = tuple(self.OVERLAY_LABELS)
        waypoint_kinds = tuple(kind for kind in preferred_order if kind in available_kinds) + tuple(
            sorted(available_kinds - set(preferred_order))
        )
        self.waypoint_visibility = {
            kind: tk.BooleanVar(value=kind not in self.HIDDEN_OVERLAYS)
            for kind in waypoint_kinds
        }
        self.hide_completed_waypoints = tk.BooleanVar(value=False)
        self.window = tk.Toplevel(owner)
        self.window.title(f"{document.title} {'Minimap' if compact else 'Map'}")
        self.window.attributes("-topmost", True)
        if initial_geometry is None:
            self.window.geometry("184x208" if compact else "760x800")
        else:
            self.window.geometry(
                f"{initial_geometry.width}x{initial_geometry.height}"
                f"{initial_geometry.left:+d}{initial_geometry.top:+d}"
            )
        if compact:
            self.window.minsize(160, 184)
        self.window.configure(background=OverlayWindow.BACKGROUND)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.mode = tk.StringVar(value=document.layers[0].key)
        if not compact:
            toolbar = tk.Frame(self.window, background=OverlayWindow.FOREGROUND, padx=10, pady=8)
            toolbar.pack(fill="x")
            for layer in (item for item in document.layers if item.map_id is None):
                tk.Radiobutton(
                    toolbar,
                    text=layer.title.upper(),
                    value=layer.key,
                    variable=self.mode,
                    command=self._redraw,
                    indicatoron=False,
                    background=OverlayWindow.FOREGROUND,
                    foreground="#ffffff",
                    selectcolor=OverlayWindow.ACCENT,
                    activebackground=OverlayWindow.ACCENT,
                    activeforeground="#ffffff",
                    borderwidth=0,
                    font=("Segoe UI Semibold", 9),
                    padx=12,
                    pady=4,
                ).pack(side="left", padx=(0, 4))
            self.zoom_label = tk.Label(
                toolbar,
                text="1×",
                width=3,
                background=OverlayWindow.FOREGROUND,
                foreground="#ffffff",
                font=("Segoe UI Semibold", 9),
            )
            self.zoom_label.pack(side="right")
            tk.Button(
                toolbar,
                text="CENTER",
                command=self._recenter,
                background=OverlayWindow.FOREGROUND,
                foreground="#ffffff",
                activebackground=OverlayWindow.ACCENT,
                activeforeground="#ffffff",
                borderwidth=0,
                font=("Segoe UI Semibold", 9),
                padx=8,
            ).pack(side="right", padx=(4, 0))
            for text, delta in (("+", 1), ("−", -1)):
                tk.Button(
                    toolbar,
                    text=text,
                    command=lambda change=delta: self._change_zoom(change),
                    background=OverlayWindow.FOREGROUND,
                    foreground="#ffffff",
                    activebackground=OverlayWindow.ACCENT,
                    activeforeground="#ffffff",
                    borderwidth=0,
                    font=("Segoe UI Semibold", 12),
                    width=2,
                ).pack(side="right", padx=(4, 0))
            overlay_bar = tk.Frame(
                self.window,
                background=OverlayWindow.FOREGROUND,
                padx=10,
                pady=0,
            )
            overlay_bar.pack(fill="x", pady=(0, 7))
            tk.Label(
                overlay_bar,
                text="OVERLAYS",
                background=OverlayWindow.FOREGROUND,
                foreground="#b9c1bc",
                font=("Segoe UI Semibold", 8),
            ).pack(side="left", padx=(0, 8))
            for kind, visible in self.waypoint_visibility.items():
                tk.Checkbutton(
                    overlay_bar,
                    text=self.OVERLAY_LABELS.get(kind, kind.replace("_", " ").title()),
                    variable=visible,
                    command=self._redraw,
                    background=OverlayWindow.FOREGROUND,
                    foreground="#ffffff",
                    selectcolor=OverlayWindow.FOREGROUND,
                    activebackground=OverlayWindow.FOREGROUND,
                    activeforeground="#ffffff",
                    borderwidth=0,
                    font=("Segoe UI", 8),
                    padx=3,
                    pady=1,
                ).pack(side="left", padx=(0, 6))
            tk.Checkbutton(
                overlay_bar,
                text="Hide collected",
                variable=self.hide_completed_waypoints,
                command=self._redraw,
                background=OverlayWindow.FOREGROUND,
                foreground="#ffffff",
                selectcolor=OverlayWindow.FOREGROUND,
                activebackground=OverlayWindow.FOREGROUND,
                activeforeground="#ffffff",
                borderwidth=0,
                font=("Segoe UI", 8),
                padx=3,
                pady=1,
            ).pack(side="right")
        self.heading = tk.Label(
            self.window,
            background=OverlayWindow.BACKGROUND,
            foreground=OverlayWindow.FOREGROUND,
            font=("Georgia", 9 if compact else 12, "bold"),
            anchor="w",
            padx=8 if compact else 12,
            pady=5 if compact else 8,
        )
        self.heading.pack(fill="x")
        self.credit = tk.Label(
            self.window,
            text="",
            background=OverlayWindow.FOREGROUND,
            foreground="#d5ddd8",
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=8,
            pady=4,
        )
        self.credit.pack(side="bottom", fill="x")
        self.credit.bind(
            "<Button-1>",
            lambda _: self._open_source(),
        )
        self.canvas = tk.Canvas(
            self.window,
            background="#050a12",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._schedule_redraw)
        if not compact:
            self.canvas.bind("<MouseWheel>", self._zoom_wheel)
            self.canvas.bind("<ButtonPress-1>", self._start_pan)
            self.canvas.bind("<B1-Motion>", self._pan)
            self.canvas.bind("<ButtonRelease-1>", self._finish_pan)
        self.window.withdraw()

    def _show_waypoint(self, waypoint: MapWaypoint, x: float, y: float) -> None:
        self.canvas.delete("waypoint-tooltip")
        text = waypoint.title + (f"\n{waypoint.detail}" if waypoint.detail else "")
        label = self.canvas.create_text(
            x + 10,
            y - 10,
            text=text,
            anchor="sw",
            justify="left",
            fill="#ffffff",
            font=("Segoe UI Semibold", 9),
            state="disabled",
            tags=("waypoint-tooltip",),
        )
        bounds = self.canvas.bbox(label)
        if bounds is not None:
            background = self.canvas.create_rectangle(
                bounds[0] - 6,
                bounds[1] - 4,
                bounds[2] + 6,
                bounds[3] + 4,
                fill="#20251f",
                outline="#f8c24e",
                state="disabled",
                tags=("waypoint-tooltip",),
            )
            self.canvas.tag_lower(background, label)

    def _show_region(self, region: MapRegion, x: float, y: float) -> None:
        self.canvas.delete("waypoint-tooltip")
        text = region.title + (f"\n{region.detail}" if region.detail else "")
        label = self.canvas.create_text(
            x + 10,
            y - 10,
            text=text,
            anchor="sw",
            justify="left",
            fill="#ffffff",
            font=("Segoe UI Semibold", 9),
            state="disabled",
            tags=("waypoint-tooltip",),
        )
        bounds = self.canvas.bbox(label)
        if bounds is not None:
            background = self.canvas.create_rectangle(
                bounds[0] - 6,
                bounds[1] - 4,
                bounds[2] + 6,
                bounds[3] + 4,
                fill="#20251f",
                outline=region.color,
                state="disabled",
                tags=("waypoint-tooltip",),
            )
            self.canvas.tag_lower(background, label)

    def _hide_waypoint(self) -> None:
        self.canvas.delete("waypoint-tooltip")

    def show(self) -> None:
        LOGGER.info(
            "Map window show compact=%s zoom=%s position=%s",
            self.compact,
            self.zoom,
            self.position,
        )
        self.window.deiconify()
        self.window.lift()
        self._redraw()

    def toggle(self) -> None:
        if self.window.state() == "withdrawn":
            self.show()
        else:
            self.hide()

    def hide(self) -> None:
        LOGGER.info("Map window hide compact=%s", self.compact)
        self._cancel_redraw()
        self._cancel_objective_flash()
        self.window.withdraw()

    def destroy(self) -> None:
        LOGGER.info(
            "Map window destroy compact=%s source_cache=%d fit_cache=%d",
            self.compact,
            len(self._images),
            len(self._fit_images),
        )
        self._destroyed = True
        self._cancel_redraw()
        self._cancel_objective_flash()
        self._photo = None
        self._photo_key = None
        for image in self._fit_images.values():
            image.close()
        for image in self._images.values():
            image.close()
        self.window.destroy()

    def update(
        self, position: MapPosition, overlays: tuple[MapOverlay, ...] = ()
    ) -> None:
        previous = self.position
        previous_map_key = self._map_key() if previous is not None else None
        previous_indoor_map_id = self._indoor_map_id
        previous_overlays = self._overlay_waypoints
        matching = map_layer_for_position(self.document, position)
        self.position = position if matching is not None else tracked_map_position(previous, position)
        overlay_waypoints: dict[str, tuple[MapWaypoint, ...]] = {}
        for overlay in overlays:
            overlay_waypoints[overlay.layer_key] = (
                overlay_waypoints.get(overlay.layer_key, ()) + overlay.waypoints
            )
        self._overlay_waypoints = overlay_waypoints
        self._indoor_map_id = None if position.is_world or matching is not None else position.map_id
        if matching is not None and (
            previous is None
            or previous.area != position.area
            or previous.map_id != position.map_id
        ):
            self.mode.set(matching.key)
        changed = (
            self.position != previous
            or self._indoor_map_id != previous_indoor_map_id
            or self._overlay_waypoints != previous_overlays
        )
        if changed and self._is_visible():
            map_key = self._map_key()
            static_view_unchanged = (
                not self.compact
                and self.zoom == 1
                and self._photo is not None
                and map_key == previous_map_key
                and self._indoor_map_id == previous_indoor_map_id
                and self._overlay_waypoints == previous_overlays
            )
            if static_view_unchanged:
                self._update_dynamic_items()
            else:
                self._redraw()

    def _map_key(self) -> str:
        if not self.compact:
            return self.mode.get()
        if self.position is not None:
            layer = map_layer_for_position(self.document, self.position)
            matching = layer.key if layer is not None else None
            if matching is not None:
                return matching
        return self.document.layers[0].key

    def _image(self, map_key: str) -> Image.Image:
        image = self._images.pop(map_key, None)
        if image is None:
            layer = self.layers[map_key]
            image_path = layer.image_loader() if layer.image_loader is not None else layer.image_path
            self._set_hang_context(f"image-load key={map_key} path={image_path}")
            started = time.perf_counter()
            LOGGER.info("Map image load begin key=%s path=%s", map_key, image_path)
            image = Image.open(image_path).convert("RGB")
            LOGGER.info(
                "Map image load end key=%s size=%sx%s elapsed_ms=%.1f",
                map_key,
                image.width,
                image.height,
                (time.perf_counter() - started) * 1000,
            )
        self._store_cached_image(self._images, map_key, image)
        return image

    def _set_hang_context(self, stage: str) -> None:
        watchdog = getattr(self, "_hang_watchdog", None)
        if watchdog is None:
            return
        position = self.position
        coordinates = (
            f"{position.area}:{position.map_id:02X}@{position.x},{position.y}"
            if position is not None
            else "none"
        )
        try:
            map_key = self._map_key()
        except (KeyError, tk.TclError):
            map_key = "unknown"
        watchdog.set_context(
            f"map={map_key} compact={self.compact} zoom={self.zoom} "
            f"position={coordinates} stage={stage}"
        )

    @staticmethod
    def _store_cached_image(
        cache: dict[object, Image.Image],
        key: object,
        image: Image.Image,
        limit: int = IMAGE_CACHE_LIMIT,
    ) -> None:
        previous = cache.pop(key, None)
        if previous is not None and previous is not image:
            previous.close()
        cache[key] = image
        while len(cache) > limit:
            oldest_key = next(iter(cache))
            stale = cache.pop(oldest_key)
            if stale is not image:
                stale.close()

    def _is_visible(self) -> bool:
        if getattr(self, "_destroyed", False):
            return False
        try:
            return self.window.state() != "withdrawn"
        except tk.TclError:
            return False

    def _cancel_redraw(self) -> None:
        job = self._redraw_job
        self._redraw_job = None
        if job is None:
            return
        try:
            self.window.after_cancel(job)
        except tk.TclError:
            pass

    def _cancel_objective_flash(self) -> None:
        job = getattr(self, "_objective_flash_job", None)
        self._objective_flash_job = None
        if job is None:
            return
        try:
            self.window.after_cancel(job)
        except tk.TclError:
            pass

    def _start_objective_flash(self) -> None:
        self._cancel_objective_flash()
        if not hasattr(self, "window"):
            return
        if not self._is_visible() or not self.canvas.find_withtag("objective-flash"):
            return
        self._objective_flash_visible = True
        self.canvas.itemconfigure("objective-flash", state="normal")
        self._objective_flash_job = self.window.after(
            self.OBJECTIVE_FLASH_INTERVAL_MS,
            self._toggle_objective_flash,
        )

    def _toggle_objective_flash(self) -> None:
        self._objective_flash_job = None
        if not self._is_visible() or not self.canvas.find_withtag("objective-flash"):
            return
        self._objective_flash_visible = not self._objective_flash_visible
        self.canvas.itemconfigure(
            "objective-flash",
            state="normal" if self._objective_flash_visible else "hidden",
        )
        self._objective_flash_job = self.window.after(
            self.OBJECTIVE_FLASH_INTERVAL_MS,
            self._toggle_objective_flash,
        )

    def _schedule_redraw(self, _event: tk.Event | None = None) -> None:
        if self._destroyed:
            return
        self._cancel_redraw()
        try:
            self._redraw_job = self.window.after(
                self.RESIZE_REDRAW_DELAY_MS,
                self._run_scheduled_redraw,
            )
        except tk.TclError:
            self._redraw_job = None

    def _run_scheduled_redraw(self) -> None:
        self._redraw_job = None
        if self._is_visible():
            self._redraw()

    def _open_source(self) -> None:
        source_url = self.layers[self._map_key()].source_url
        if source_url:
            webbrowser.open(source_url)

    def _change_zoom(self, delta: int) -> None:
        index = max(
            0,
            min(
                self.ZOOM_LEVELS.index(self.zoom) + delta,
                len(self.ZOOM_LEVELS) - 1,
            ),
        )
        self.zoom = self.ZOOM_LEVELS[index]
        if self.zoom == 1:
            self._pan_source = (0.0, 0.0)
        self.zoom_label.configure(text=f"{self.zoom}×")
        self._redraw()

    def _zoom_wheel(self, event: tk.Event) -> None:
        self._change_zoom(1 if event.delta > 0 else -1)

    def _recenter(self) -> None:
        self._pan_source = (0.0, 0.0)
        self._redraw()

    def _start_pan(self, event: tk.Event) -> None:
        if self.zoom == 1:
            return
        self._pan_drag_start = (event.x, event.y)
        self._pan_drag_origin = self._pan_source
        self.canvas.configure(cursor="fleur")

    def _pan(self, event: tk.Event) -> None:
        if self.zoom == 1:
            return
        map_key = self._map_key()
        source = self._image(map_key)
        canvas_width = max(self.canvas.winfo_width(), 1)
        canvas_height = max(self.canvas.winfo_height(), 1)
        crop_width = source.width / self.zoom
        crop_height = source.height / self.zoom
        scale = min(canvas_width / crop_width, canvas_height / crop_height)
        delta_x = (event.x - self._pan_drag_start[0]) / scale
        delta_y = (event.y - self._pan_drag_start[1]) / scale
        self._pan_source = (
            (self._pan_drag_origin[0] - delta_x) % source.width,
            (self._pan_drag_origin[1] - delta_y) % source.height,
        )
        self._redraw()

    def _finish_pan(self, _event: tk.Event) -> None:
        self.canvas.configure(cursor="")

    def _redraw(self) -> None:
        if self._destroyed:
            return
        started = time.perf_counter()
        self._set_hang_context("full-redraw-begin")
        LOGGER.info(
            "Map full redraw begin key=%s compact=%s zoom=%s position=%s",
            self._map_key() if self.position is not None else "none",
            self.compact,
            self.zoom,
            self.position,
        )
        try:
            self._draw()
        except Exception as error:
            LOGGER.exception("Map redraw failed")
            try:
                self.canvas.delete("all")
                self.canvas.create_text(
                    max(self.canvas.winfo_width(), 100) / 2,
                    max(self.canvas.winfo_height(), 100) / 2,
                    text=f"Map could not be drawn\n{error}",
                    justify="center",
                    fill=OverlayWindow.ACCENT,
                    font=("Segoe UI Semibold", 9),
                )
            except tk.TclError:
                pass
        finally:
            elapsed = time.perf_counter() - started
            level = logging.WARNING if elapsed >= 0.25 else logging.INFO
            LOGGER.log(
                level,
                "Map full redraw end elapsed_ms=%.1f source_cache=%d fit_cache=%d",
                elapsed * 1000,
                len(self._images),
                len(self._fit_images),
            )
            self._set_hang_context("idle-after-full-redraw")

    def _draw(self) -> None:
        self._cancel_objective_flash()
        self.canvas.delete("all")
        self._drawn_path_lengths.clear()
        if self.position is None:
            if self._indoor_map_id is not None:
                self.heading.configure(text=f"Map {self._indoor_map_id:04X} · indoors")
            return
        width = max(self.canvas.winfo_width(), 100)
        height = max(self.canvas.winfo_height(), 100)
        if self.compact and self._indoor_map_id is not None:
            self.heading.configure(text=f"Map {self._indoor_map_id:04X} · indoors")
            self.canvas.create_text(
                width / 2,
                height / 2,
                text="No calibrated\nlocal map image",
                justify="center",
                fill="#d5ddd8",
                font=("Segoe UI Semibold", 9),
            )
            return

        map_key = self._map_key()
        layer = self.layers[map_key]
        self._set_hang_context("full-redraw-source-image")
        source = self._image(map_key)
        source_x, source_y = map_source_point(self.position, layer)
        if self.compact:
            crop_size = 18 * 16
            shifted = ImageChops.offset(
                source,
                source.width // 2 - source_x,
                source.height // 2 - source_y,
            )
            crop = shifted.crop(
                (
                    source.width // 2 - crop_size // 2,
                    source.height // 2 - crop_size // 2,
                    source.width // 2 + crop_size // 2,
                    source.height // 2 + crop_size // 2,
                )
            )
            side = min(width, height)
            rendered = crop.resize((side, side), Image.Resampling.NEAREST)
            image_x = (width - side) / 2
            image_y = (height - side) / 2
            marker_x = width / 2
            marker_y = height / 2
        else:
            view = source
            if self.zoom > 1:
                center_x = (source_x + self._pan_source[0]) % source.width
                center_y = (source_y + self._pan_source[1]) % source.height
                shifted = ImageChops.offset(
                    source,
                    round(source.width / 2 - center_x),
                    round(source.height / 2 - center_y),
                )
                crop_width = source.width // self.zoom
                crop_height = source.height // self.zoom
                view = shifted.crop(
                    (
                        (source.width - crop_width) // 2,
                        (source.height - crop_height) // 2,
                        (source.width + crop_width) // 2,
                        (source.height + crop_height) // 2,
                    )
                )
            scale = min(width / view.width, height / view.height)
            image_width = max(1, int(view.width * scale))
            image_height = max(1, int(view.height * scale))
            if self.zoom == 1:
                fit_key = (map_key, image_width, image_height)
                rendered = self._fit_images.pop(fit_key, None)
                if rendered is None:
                    self._set_hang_context(
                        f"full-redraw-resize target={image_width}x{image_height}"
                    )
                    rendered = view.resize(
                        (image_width, image_height), Image.Resampling.NEAREST
                    )
                self._store_cached_image(self._fit_images, fit_key, rendered)
            else:
                rendered = view.resize(
                    (image_width, image_height), Image.Resampling.NEAREST
                )
            image_x = (width - image_width) / 2
            image_y = (height - image_height) / 2
            if self.zoom == 1:
                marker_x = image_x + source_x * scale
                marker_y = image_y + source_y * scale
            else:
                marker_x = width / 2 + wrapped_map_delta(
                    source_x, center_x, source.width
                ) * scale
                marker_y = height / 2 + wrapped_map_delta(
                    source_y, center_y, source.height
                ) * scale
        photo_key = (
            (map_key, image_width, image_height)
            if not self.compact and self.zoom == 1
            else None
        )
        if photo_key is None or self._photo is None or photo_key != self._photo_key:
            self._set_hang_context("full-redraw-photoimage")
            self._photo = ImageTk.PhotoImage(rendered)
            self._photo_key = photo_key
        self.canvas.create_image(image_x, image_y, image=self._photo, anchor="nw")
        if not self.compact:
            self._set_hang_context("full-redraw-hero-path")
            self._draw_hero_path(
                layer,
                source,
                width,
                height,
                image_x,
                image_y,
                scale,
                center_x if self.zoom > 1 else None,
                center_y if self.zoom > 1 else None,
            )
        if not self.compact:
            self._set_hang_context(
                f"full-redraw-regions count={len(layer.regions)}"
            )
            for index, region in enumerate(layer.regions):
                visibility = self.waypoint_visibility.get(region.kind)
                if visibility is not None and not visibility.get():
                    continue
                source_left = (region.x + layer.offset_x) * layer.tile_width
                source_top = (region.y + layer.offset_y) * layer.tile_height
                if self.zoom == 1:
                    left = image_x + source_left * scale
                    top = image_y + source_top * scale
                else:
                    left = width / 2 + wrapped_map_delta(source_left, center_x, source.width) * scale
                    top = height / 2 + wrapped_map_delta(source_top, center_y, source.height) * scale
                right = left + region.width * layer.tile_width * scale
                bottom = top + region.height * layer.tile_height * scale
                if right < 0 or bottom < 0 or left > width or top > height:
                    continue
                tag = f"region-{index}"
                if region.kind == "encounters":
                    self._create_encounter_region(
                        region,
                        left,
                        top,
                        right,
                        bottom,
                        tag,
                    )
                    tooltip_x, tooltip_y = left, top
                else:
                    self.canvas.create_rectangle(
                        left,
                        top,
                        right,
                        bottom,
                        fill=region.color,
                        stipple="gray50",
                        outline=region.color,
                        width=1,
                        tags=(tag, "region"),
                    )
                    tooltip_x, tooltip_y = left, top
                self.canvas.tag_bind(
                    tag,
                    "<Enter>",
                    lambda _event, item=region, x=tooltip_x, y=tooltip_y: self._show_region(item, x, y),
                )
                self.canvas.tag_bind(tag, "<Leave>", lambda _event: self._hide_waypoint())
        matching_area = self.position.area == layer.area
        player_visibility = self.waypoint_visibility.get("player")
        if (self.compact or matching_area) and (
            player_visibility is None or player_visibility.get()
        ):
            radius = 6 if self.compact else 7
            self.canvas.create_oval(
                marker_x - radius,
                marker_y - radius,
                marker_x + radius,
                marker_y + radius,
                fill="#f8c24e",
                outline="#20251f",
                width=2,
                tags=("player-marker",),
            )
        waypoints = layer.waypoints + self._overlay_waypoints.get(layer.key, ())
        self._set_hang_context(
            f"full-redraw-waypoints count={len(waypoints)}"
        )
        for index, waypoint in enumerate(waypoints):
            visibility = self.waypoint_visibility.get(waypoint.kind)
            if visibility is not None and not visibility.get():
                continue
            if waypoint.completed and self.hide_completed_waypoints.get():
                continue
            waypoint_x, waypoint_y = waypoint_source_point(waypoint, layer)
            if self.compact:
                point_x = width / 2 + wrapped_map_delta(
                    waypoint_x, source_x, source.width
                ) * side / crop_size
                point_y = height / 2 + wrapped_map_delta(
                    waypoint_y, source_y, source.height
                ) * side / crop_size
            elif self.zoom == 1:
                point_x = image_x + waypoint_x * scale
                point_y = image_y + waypoint_y * scale
            else:
                point_x = width / 2 + wrapped_map_delta(
                    waypoint_x, center_x, source.width
                ) * scale
                point_y = height / 2 + wrapped_map_delta(
                    waypoint_y, center_y, source.height
                ) * scale
            if not 0 <= point_x <= width or not 0 <= point_y <= height:
                continue
            tag = f"waypoint-{index}"
            self._create_waypoint_marker(waypoint, point_x, point_y, tag)
            self.canvas.tag_bind(
                tag,
                "<Enter>",
                lambda _event, item=waypoint, x=point_x, y=point_y: self._show_waypoint(item, x, y),
            )
            self.canvas.tag_bind(tag, "<Leave>", lambda _event: self._hide_waypoint())
        self.credit.configure(text=layer.credit)
        map_name = layer.title
        location_note = " · indoors · last outside" if self._indoor_map_id is not None else ""
        self.heading.configure(
            text=f"{map_name} · ({self.position.x},{self.position.y}){location_note}"
        )
        self._start_objective_flash()

    def _create_encounter_region(
        self,
        region: MapRegion,
        left: float,
        top: float,
        right: float,
        bottom: float,
        tag: str,
    ) -> None:
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=region.color,
            stipple="gray12",
            outline=region.color,
            width=2,
            tags=(tag, "region", "encounter-cell"),
        )
        cell_size = min(right - left, bottom - top)
        label = (
            region.label
            if cell_size >= 72
            else region.compact_label or region.label
        )
        if not label:
            return
        center_x = (left + right) / 2
        center_y = (top + bottom) / 2
        wrap_width = max(12, int(right - left) - 6)
        font_size = 8 if cell_size >= 72 else 6
        for offset, color in ((1, "#10151a"), (0, "#ffffff")):
            self.canvas.create_text(
                center_x + offset,
                center_y + offset,
                text=label,
                width=wrap_width,
                justify="center",
                fill=color,
                font=("Segoe UI Semibold", font_size),
                state="disabled",
                tags=(tag, "region-label"),
            )

    def _create_waypoint_marker(
        self,
        waypoint: MapWaypoint,
        point_x: float,
        point_y: float,
        tag: str,
    ) -> None:
        if waypoint.kind == "objective":
            self.canvas.create_oval(
                point_x - 11,
                point_y - 11,
                point_x + 11,
                point_y + 11,
                outline="#f8c24e",
                width=3,
                tags=(tag, "waypoint", "objective-flash"),
            )
            self.canvas.create_polygon(
                point_x,
                point_y - 7,
                point_x + 7,
                point_y,
                point_x,
                point_y + 7,
                point_x - 7,
                point_y,
                fill="#bb3e2f",
                outline="#ffffff",
                width=2,
                tags=(tag, "waypoint", "objective-marker"),
            )
            return
        if waypoint.kind != "npcs":
            color = (
                "#16817a" if waypoint.kind == "collectibles" else "#bb3e2f"
            )
            self.canvas.create_oval(
                point_x - 4,
                point_y - 4,
                point_x + 4,
                point_y + 4,
                fill=color,
                outline="#ffffff",
                width=1,
                tags=(tag, "waypoint"),
            )
            return

        marker = waypoint.marker or "person"
        color, symbol = {
            "shop": ("#16817a", "$"),
            "service": ("#3d6da8", "+"),
            "quest": ("#d38a17", "!"),
            "item": ("#f0b429", "*"),
            "boss": ("#b83232", "X"),
            "person": ("#6b7280", ""),
        }.get(marker, ("#6b7280", ""))
        fill = "#767b77" if waypoint.completed else color
        if marker == "shop":
            self.canvas.create_polygon(
                point_x,
                point_y - 6,
                point_x + 6,
                point_y,
                point_x,
                point_y + 6,
                point_x - 6,
                point_y,
                fill=fill,
                outline="#ffffff",
                width=1,
                tags=(tag, "waypoint"),
            )
        elif marker in {"quest", "item"}:
            self.canvas.create_polygon(
                point_x,
                point_y - 6,
                point_x + 6,
                point_y + 5,
                point_x - 6,
                point_y + 5,
                fill=fill,
                outline="#ffffff",
                width=1,
                tags=(tag, "waypoint"),
            )
        elif marker == "service":
            self.canvas.create_rectangle(
                point_x - 5,
                point_y - 5,
                point_x + 5,
                point_y + 5,
                fill=fill,
                outline="#ffffff",
                width=1,
                tags=(tag, "waypoint"),
            )
        else:
            self.canvas.create_oval(
                point_x - 5,
                point_y - 5,
                point_x + 5,
                point_y + 5,
                fill=fill,
                outline="#ffffff",
                width=1,
                tags=(tag, "waypoint"),
            )
        if symbol:
            self.canvas.create_text(
                point_x,
                point_y,
                text=symbol,
                fill="#ffffff",
                font=("Segoe UI Semibold", 7),
                tags=(tag, "waypoint"),
            )

    def _update_dynamic_items(self) -> None:
        if self.position is None:
            return
        started = time.perf_counter()
        self._set_hang_context("dynamic-update-begin")
        try:
            self._update_dynamic_items_impl()
        except Exception:
            LOGGER.exception("Map dynamic update failed")
            self._redraw()
        finally:
            elapsed = time.perf_counter() - started
            self._dynamic_update_count += 1
            if elapsed >= 0.1:
                LOGGER.warning(
                    "Map dynamic update slow elapsed_ms=%.1f position=%s",
                    elapsed * 1000,
                    self.position,
                )
            elif self._dynamic_update_count % 20 == 0:
                LOGGER.info(
                    "Map dynamic updates count=%d latest_ms=%.1f source_cache=%d "
                    "fit_cache=%d path_points=%d",
                    self._dynamic_update_count,
                    elapsed * 1000,
                    len(self._images),
                    len(self._fit_images),
                    len(self._hero_paths.get(self._map_key(), ())),
                )
            self._set_hang_context("idle-after-dynamic-update")

    def _update_dynamic_items_impl(self) -> None:
        assert self.position is not None
        width = max(self.canvas.winfo_width(), 100)
        height = max(self.canvas.winfo_height(), 100)
        map_key = self._map_key()
        layer = self.layers[map_key]
        source = self._image(map_key)
        source_x, source_y = map_source_point(self.position, layer)
        scale = min(width / source.width, height / source.height)
        image_width = max(1, int(source.width * scale))
        image_height = max(1, int(source.height * scale))
        image_x = (width - image_width) / 2
        image_y = (height - image_height) / 2

        self._append_hero_path(
            layer,
            source,
            width,
            height,
            image_x,
            image_y,
            scale,
        )
        self.canvas.delete("player-marker")
        player_visibility = self.waypoint_visibility.get("player")
        if self.position.area == layer.area and (
            player_visibility is None or player_visibility.get()
        ):
            marker_x = image_x + source_x * scale
            marker_y = image_y + source_y * scale
            self.canvas.create_oval(
                marker_x - 7,
                marker_y - 7,
                marker_x + 7,
                marker_y + 7,
                fill="#f8c24e",
                outline="#20251f",
                width=2,
                tags=("player-marker",),
            )
        location_note = (
            " · indoors · last outside" if self._indoor_map_id is not None else ""
        )
        self.heading.configure(
            text=f"{layer.title} · ({self.position.x},{self.position.y}){location_note}"
        )

    def _draw_hero_path(
        self,
        layer: MapLayer,
        source: Image.Image,
        width: int,
        height: int,
        image_x: float,
        image_y: float,
        scale: float,
        center_x: float | None,
        center_y: float | None,
    ) -> None:
        self.canvas.delete("hero-path")
        path = self._hero_paths.get(layer.key, ())
        self._drawn_path_lengths[layer.key] = len(path)
        visibility = self.waypoint_visibility.get("path")
        if self.compact or visibility is None or not visibility.get() or len(path) < 2:
            return
        projected = [
            self._project_path_point(
                point,
                source,
                width,
                height,
                image_x,
                image_y,
                scale,
                center_x,
                center_y,
            )
            for point in path
        ]
        run: list[tuple[float, float]] = []
        for start, end in zip(projected, projected[1:]):
            if not self._path_segment_visible(start, end, width, height):
                self._create_path_run(run)
                run = []
                continue
            if not run:
                run = [start, end]
            elif run[-1] == start:
                run.append(end)
            else:
                self._create_path_run(run)
                run = [start, end]
        self._create_path_run(run)

    def _append_hero_path(
        self,
        layer: MapLayer,
        source: Image.Image,
        width: int,
        height: int,
        image_x: float,
        image_y: float,
        scale: float,
    ) -> None:
        path = self._hero_paths.get(layer.key, ())
        drawn = self._drawn_path_lengths.get(layer.key, 0)
        visibility = self.waypoint_visibility.get("path")
        if visibility is None or not visibility.get():
            self._drawn_path_lengths[layer.key] = len(path)
            return
        if drawn > len(path) or drawn == 0:
            self._draw_hero_path(
                layer, source, width, height, image_x, image_y, scale, None, None
            )
            return
        for index in range(max(1, drawn), len(path)):
            start = self._project_path_point(
                path[index - 1],
                source,
                width,
                height,
                image_x,
                image_y,
                scale,
                None,
                None,
            )
            end = self._project_path_point(
                path[index],
                source,
                width,
                height,
                image_x,
                image_y,
                scale,
                None,
                None,
            )
            if self._path_segment_visible(start, end, width, height):
                self.canvas.create_line(
                    *start,
                    *end,
                    fill="#2f8f83",
                    width=2,
                    tags=("hero-path", "hero-path-increment"),
                )
        self._drawn_path_lengths[layer.key] = len(path)
        if len(self.canvas.find_withtag("hero-path-increment")) >= self.PATH_INCREMENT_LIMIT:
            self._draw_hero_path(
                layer, source, width, height, image_x, image_y, scale, None, None
            )

    def _project_path_point(
        self,
        point: tuple[int, int],
        source: Image.Image,
        width: int,
        height: int,
        image_x: float,
        image_y: float,
        scale: float,
        center_x: float | None,
        center_y: float | None,
    ) -> tuple[float, float]:
        path_x, path_y = point
        if center_x is None or center_y is None:
            return image_x + path_x * scale, image_y + path_y * scale
        return (
            width / 2 + wrapped_map_delta(path_x, center_x, source.width) * scale,
            height / 2 + wrapped_map_delta(path_y, center_y, source.height) * scale,
        )

    @staticmethod
    def _path_segment_visible(
        start: tuple[float, float],
        end: tuple[float, float],
        width: int,
        height: int,
    ) -> bool:
        return (
            abs(start[0] - end[0]) <= width / 2
            and abs(start[1] - end[1]) <= height / 2
            and -8 <= start[0] <= width + 8
            and -8 <= start[1] <= height + 8
            and -8 <= end[0] <= width + 8
            and -8 <= end[1] <= height + 8
        )

    def _create_path_run(self, points: list[tuple[float, float]]) -> None:
        start = 0
        while start + 1 < len(points):
            chunk = points[start:start + self.PATH_CHUNK_POINTS]
            coordinates = [coordinate for point in chunk for coordinate in point]
            self.canvas.create_line(
                *coordinates,
                fill="#2f8f83",
                width=2,
                tags=("hero-path",),
            )
            start += self.PATH_CHUNK_POINTS - 1


class OverlayWindow:
    WIDTH = 320
    MIN_WIDTH = 280
    MIN_HEIGHT = 180
    SCREEN_MARGIN = 12
    BACKGROUND = "#f4f1e8"
    FOREGROUND = "#20251f"
    MUTED = "#687064"
    ACCENT = "#bb3e2f"
    DIVIDER = "#cbc8bd"
    ALERT_BACKGROUND = "#ffe9e5"
    ALERT_FOREGROUND = "#9d1717"

    def __init__(
        self,
        client: RetroArchClient,
        registry: AdapterRegistry,
        opacity: float = 0.72,
        local_settings: LocalPluginSettings | None = None,
        controller: OverlayController | None = None,
        hang_watchdog: UIHangWatchdog | None = None,
    ):
        if not 0.3 <= opacity <= 1.0:
            raise ValueError("Opacity must be between 0.3 and 1.0")
        self._controller = controller or OverlayController(client, registry)
        self._local_settings = local_settings
        self._hang_watchdog = hang_watchdog or (
            UIHangWatchdog(
                local_settings.path.parent
                / "logs"
                / "retroarch-overlay-hang.log"
            )
            if local_settings is not None
            else None
        )
        self._heartbeat_job: str | None = None
        high_contrast = (
            local_settings.high_contrast_override()
            if local_settings is not None
            else None
        )
        if high_contrast is None:
            high_contrast = windows_high_contrast_enabled()
        self._high_contrast = high_contrast
        if high_contrast:
            self.BACKGROUND = "#ffffff"
            self.FOREGROUND = "#000000"
            self.MUTED = "#333333"
            self.ACCENT = "#0046b8"
            self.DIVIDER = "#000000"
            self.ALERT_BACKGROUND = "#ffffff"
            self.ALERT_FOREGROUND = "#a00000"
        profile = (
            local_settings.layout_profile()
            if local_settings is not None
            else LayoutProfile(mode="overlay", manage_retroarch_window=False)
        )
        self._layout_manager = ResponsiveLayoutManager(profile)
        self._active_layout = None
        self._idle_opacity = opacity
        self.root = tk.Tk()
        self.root.resizable(True, True)
        self.root.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.root.title("RetroArch Overlay")
        saved_geometry = (
            local_settings.window_geometry("main")
            if local_settings is not None
            else None
        )
        saved_user_size = (
            local_settings.window_geometry("main-native")
            if local_settings is not None
            else None
        )
        if saved_user_size is not None:
            self.WIDTH, initial_height = clamp_overlay_size(
                saved_user_size.width,
                saved_user_size.height,
                self.root.winfo_screenwidth(),
                self.root.winfo_screenheight(),
            )
        else:
            _, initial_height = clamp_overlay_size(
                self.WIDTH,
                640,
                self.root.winfo_screenwidth(),
                self.root.winfo_screenheight(),
            )
        self._manual_dimensions = (self.WIDTH, initial_height)
        if saved_geometry is None:
            x_position = self.root.winfo_screenwidth() - self.WIDTH - self.SCREEN_MARGIN
            y_position = self.SCREEN_MARGIN
        else:
            x_position = saved_geometry.left
            y_position = saved_geometry.top
        self.root.geometry(
            f"{self.WIDTH}x{initial_height}{x_position:+d}{y_position:+d}"
        )
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self._idle_opacity)
        self.root.configure(background=self.BACKGROUND)
        self._last_result: OverlaySnapshot | OverlayDiagnostic | Exception | str | None = None
        self._drag_offset = (0, 0)
        self._drag_start = (0, 0)
        self._resize_start = (0, 0, self.WIDTH, initial_height)
        self._window_initialized = False
        self._main_geometry_job: str | None = None
        self._collapsed = False
        self._expanded_sections: set[tuple[str, str]] = set()
        self._hide_caught = tk.BooleanVar(value=False)
        self._active_role = tk.StringVar(value="area")
        self._role_buttons: dict[str, tk.Button] = {}
        self._rendered_layout: tuple[object, ...] | None = None
        self._section_labels: list[tk.Label] = []
        self._row_labels: list[tk.Label] = []
        self._row_tooltips: dict[tk.Label, str] = {}
        self._tooltip_window: tk.Toplevel | None = None
        self._tooltip_label: tk.Label | None = None
        self._tooltip_widget: tk.Label | None = None
        self._map_position: MapPosition | None = None
        self._map_document: MapDocument | None = None
        self._map_overlays: tuple[MapOverlay, ...] = ()
        self._hero_paths: dict[str, list[tuple[int, int]]] = {}
        self._map_window: CoordinateMapWindow | None = None
        self._minimap_window: CoordinateMapWindow | None = None
        self._secondary_window: tk.Toplevel | None = None
        self._secondary_body: tk.Frame | None = None
        self._secondary_signature: tuple[object, ...] | None = None
        self._layout_dialog: LayoutSettingsDialog | None = None
        self._detail_windows: dict[
            tuple[str, str, str], tuple[tk.Toplevel, tk.Frame, tuple[PanelRow, ...]]
        ] = {}
        self._detail_position_jobs: dict[tuple[str, str, str], str] = {}
        self._title_font = tkfont.Font(family="Georgia", size=18, weight="bold")
        self._section_font = tkfont.Font(family="Segoe UI Semibold", size=10)
        self._body_font = tkfont.Font(family="Consolas", size=10)
        self._build()
        self._configure_accessibility(self.root)
        self.root.bind("<Enter>", lambda _: self.root.attributes("-alpha", 0.96))
        self.root.bind("<Leave>", lambda _: self.root.attributes("-alpha", self._idle_opacity))
        self.root.bind("<Escape>", lambda _: self._toggle_collapsed())
        self.root.bind("<Alt-m>", lambda _: self._show_map())
        self.root.bind("<Alt-n>", lambda _: self._show_minimap())
        self.root.bind("<Prior>", lambda _: self.canvas.yview_scroll(-1, "pages"))
        self.root.bind("<Next>", lambda _: self.canvas.yview_scroll(1, "pages"))
        self.root.bind("<MouseWheel>", self._scroll_main_panel)
        self.root.bind("<Button-4>", self._scroll_main_panel)
        self.root.bind("<Button-5>", self._scroll_main_panel)
        self.root.bind("<Configure>", self._main_window_configured)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_accessibility(self, widget: tk.Misc) -> None:
        for child in widget.winfo_children():
            if isinstance(child, (tk.Button, tk.Checkbutton, tk.Radiobutton)):
                child.configure(
                    takefocus=True,
                    highlightthickness=2,
                    highlightbackground=self.BACKGROUND,
                    highlightcolor=self.ACCENT,
                )
            self._configure_accessibility(child)

    def _build(self) -> None:
        self.header = tk.Frame(self.root, background=self.FOREGROUND, padx=14, pady=9)
        self.header.pack(fill="x")
        close_button = tk.Button(
            self.header,
            text="X",
            command=self.close,
            background=self.FOREGROUND,
            foreground="#ffffff",
            activebackground=self.ACCENT,
            activeforeground="#ffffff",
            borderwidth=0,
            font=("Segoe UI Semibold", 9),
            padx=6,
            pady=2,
        )
        close_button.pack(side="right", anchor="n")
        tk.Button(
            self.header,
            text="⚙",
            command=self._show_layout_settings,
            background=self.FOREGROUND,
            foreground="#ffffff",
            activebackground=self.ACCENT,
            activeforeground="#ffffff",
            borderwidth=0,
            font=("Segoe UI Symbol", 11),
            padx=6,
            pady=1,
        ).pack(side="right", anchor="n", padx=(0, 4))
        title_block = tk.Frame(self.header, background=self.FOREGROUND)
        title_block.pack(side="left", fill="x", expand=True)
        self.game_label = tk.Label(
            title_block, text="RETROARCH OVERLAY", background=self.FOREGROUND,
            foreground="#ffffff", font=self._section_font, anchor="w",
        )
        self.game_label.pack(fill="x")
        self.location_label = tk.Label(
            title_block, text="Waiting for RetroArch", background=self.FOREGROUND,
            foreground="#ffffff", font=self._title_font, anchor="w", wraplength=255,
        )
        self.location_label.pack(fill="x", pady=(1, 0))
        for widget in (self.header, title_block, self.game_label, self.location_label):
            widget.bind("<Double-Button-1>", lambda _: self._toggle_collapsed())

        self.status_bar = tk.Frame(self.root, background=self.BACKGROUND)
        self.status_bar.pack(fill="x")
        self.status_label = tk.Label(
            self.status_bar, text="Connecting to 127.0.0.1:55355", background=self.BACKGROUND,
            foreground=self.MUTED, font=("Segoe UI", 8), anchor="w", padx=14, pady=6,
        )
        self.status_label.pack(side="left", fill="x", expand=True)
        self.role_tabs = tk.Frame(self.root, background="#e6e1d4", padx=10, pady=6)
        for role in ("area", "party", "goals"):
            button = tk.Button(
                self.role_tabs,
                text=role.upper(),
                command=lambda value=role: self._select_role(value),
                activebackground=self.DIVIDER,
                activeforeground=self.FOREGROUND,
                borderwidth=0,
                font=("Segoe UI Semibold", 8),
                padx=10,
                pady=4,
            )
            button.pack(side="left", expand=True, fill="x", padx=2)
            self._role_buttons[role] = button
        self._update_role_tabs()
        self.map_controls = tk.Frame(self.root, background="#e6e1d4", padx=14, pady=7)
        tk.Label(
            self.map_controls,
            text="MAPS",
            background="#e6e1d4",
            foreground=self.MUTED,
            font=self._section_font,
        ).pack(side="left", padx=(0, 10))
        for text, command in (
            ("MAP", self._show_map),
            ("MINIMAP", self._show_minimap),
        ):
            tk.Button(
                self.map_controls,
                text=text,
                command=command,
                background="#e6e1d4",
                foreground=self.ACCENT,
                activebackground="#e6e1d4",
                activeforeground=self.FOREGROUND,
                borderwidth=0,
                font=("Segoe UI Semibold", 8),
                padx=8,
                pady=2,
            ).pack(side="left", padx=(0, 4))
        self.hide_caught_toggle = tk.Checkbutton(
            self.status_bar,
            text="Hide completed",
            variable=self._hide_caught,
            command=self._toggle_hide_caught,
            background=self.BACKGROUND,
            foreground=self.MUTED,
            activebackground=self.BACKGROUND,
            activeforeground=self.FOREGROUND,
            selectcolor=self.BACKGROUND,
            font=("Segoe UI", 8),
            borderwidth=0,
            padx=8,
        )

        self.canvas = tk.Canvas(
            self.root,
            width=self.WIDTH - 18,
            background=self.BACKGROUND,
            highlightthickness=0,
        )
        self.scrollbar = tk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.content = tk.Frame(self.canvas, background=self.BACKGROUND)
        self.content.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.canvas_window, width=event.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.root.update_idletasks()
        self._window_initialized = True

    def run(self) -> None:
        if self._hang_watchdog is not None:
            self._hang_watchdog.start()
            self._hang_watchdog.heartbeat("Tk mainloop starting")
        self._controller.start()
        self.root.after(100, self._drain_results)
        self._heartbeat_job = self.root.after(250, self._ui_heartbeat)
        try:
            self.root.mainloop()
        finally:
            if self._hang_watchdog is not None:
                self._hang_watchdog.stop()

    def close(self) -> None:
        if self._hang_watchdog is not None:
            self._hang_watchdog.stop()
        if self._heartbeat_job is not None:
            try:
                self.root.after_cancel(self._heartbeat_job)
            except tk.TclError:
                pass
            self._heartbeat_job = None
        self._controller.stop()
        self._save_window_geometry("main", self.root)
        if self._manual_dimensions is not None:
            self._save_window_geometry("main-native", self.root)
        self._layout_manager.close()
        self._destroy_map_windows()
        self._destroy_secondary_window()
        self._hide_row_tooltip()
        if self._tooltip_window is not None:
            self._tooltip_window.destroy()
            self._tooltip_window = None
            self._tooltip_label = None
        for key, (window, _, _) in self._detail_windows.items():
            self._save_detail_window_position(key, window)
            window.destroy()
        self._detail_windows.clear()
        self._detail_position_jobs.clear()
        self.root.destroy()

    def _bind_row_tooltip(self, label: tk.Label, tooltip: str) -> None:
        self._update_row_tooltip(label, tooltip)
        label.bind(
            "<Enter>",
            lambda _event, widget=label: self._show_row_tooltip(widget),
        )
        label.bind("<Leave>", lambda _event: self._hide_row_tooltip())
        label.bind(
            "<FocusIn>",
            lambda _event, widget=label: self._show_row_tooltip(widget),
        )
        label.bind("<FocusOut>", lambda _event: self._hide_row_tooltip())

    def _update_row_tooltip(self, label: tk.Label, tooltip: str) -> None:
        self._row_tooltips[label] = tooltip
        label.configure(
            cursor="question_arrow" if tooltip else "",
            takefocus=bool(tooltip),
        )
        if self._tooltip_widget is label:
            self._show_row_tooltip(label)

    def _show_row_tooltip(
        self,
        widget: tk.Label,
    ) -> None:
        text = self._row_tooltips.get(widget, "")
        if not text:
            self._hide_row_tooltip()
            return
        if self._tooltip_window is None:
            self._tooltip_window = tk.Toplevel(self.root)
            self._tooltip_window.withdraw()
            self._tooltip_window.overrideredirect(True)
            self._tooltip_window.attributes("-topmost", True)
            self._tooltip_window.configure(background=self.FOREGROUND)
            self._tooltip_label = tk.Label(
                self._tooltip_window,
                background=self.FOREGROUND,
                foreground="#ffffff",
                font=self._body_font,
                justify="left",
                anchor="w",
                padx=10,
                pady=8,
                wraplength=340,
            )
            self._tooltip_label.pack()
        assert self._tooltip_label is not None
        self._tooltip_label.configure(text=text)
        self._tooltip_window.update_idletasks()
        width = self._tooltip_window.winfo_reqwidth()
        height = self._tooltip_window.winfo_reqheight()
        widget_left = widget.winfo_rootx()
        widget_top = widget.winfo_rooty()
        widget_right = widget_left + widget.winfo_width()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        if widget_right + width + 8 <= screen_width:
            x = widget_right + 8
            y = widget_top
        elif widget_left - width - 8 >= 0:
            x = widget_left - width - 8
            y = widget_top
        else:
            x = max(4, min(widget_left, screen_width - width - 4))
            below = widget_top + widget.winfo_height() + 8
            y = below if below + height <= screen_height else widget_top - height - 8
        y = max(4, min(y, screen_height - height - 4))
        self._tooltip_window.geometry(f"+{x}+{y}")
        self._tooltip_window.deiconify()
        self._tooltip_window.lift()
        self._tooltip_widget = widget

    def _hide_row_tooltip(self) -> None:
        if self._tooltip_window is not None:
            self._tooltip_window.withdraw()
        self._tooltip_widget = None

    def _show_map(self) -> None:
        if self._map_position is None or self._map_document is None:
            return
        if self._map_window is None:
            self._map_window = CoordinateMapWindow(
                self.root,
                self._map_document,
                initial_geometry=self._window_geometry("map"),
                hero_paths=self._hero_paths,
                hang_watchdog=self._hang_watchdog,
            )
        self._map_window.update(self._map_position, self._map_overlays)
        self._map_window.toggle()

    def _show_minimap(self) -> None:
        if self._map_position is None or self._map_document is None:
            return
        if self._minimap_window is None:
            self._minimap_window = CoordinateMapWindow(
                self.root,
                self._map_document,
                compact=True,
                initial_geometry=self._window_geometry("minimap"),
                hero_paths=self._hero_paths,
                hang_watchdog=self._hang_watchdog,
            )
        self._minimap_window.update(self._map_position, self._map_overlays)
        self._minimap_window.toggle()

    def _destroy_map_windows(self) -> None:
        for key, window in (("map", self._map_window), ("minimap", self._minimap_window)):
            if window is not None:
                self._save_window_geometry(key, window.window)
                window.destroy()
        self._map_window = None
        self._minimap_window = None

    def _show_detail(self, action: PanelAction) -> None:
        game = self._last_result.game if isinstance(self._last_result, OverlaySnapshot) else ""
        key = (game, action.label, action.title)
        existing = self._detail_windows.get(key)
        if existing is not None:
            window, _, _ = existing
            if window.state() == "withdrawn":
                window.deiconify()
                window.lift()
            else:
                window.withdraw()
            return
        window = tk.Toplevel(self.root)
        window.title(action.title)
        window.attributes("-topmost", True)
        window.configure(background=self.BACKGROUND)
        compact_layout = action.compact
        if compact_layout:
            detail_width = self.WIDTH
            detail_height = 180
        else:
            detail_width = min(720, max(520, int(window.winfo_screenwidth() * 0.38)))
            detail_height = min(720, max(560, int(window.winfo_screenheight() * 0.72)))
        saved_geometry = self._window_geometry(
            f"detail|{self._detail_position_key(key)}"
        )
        autosize_detail = saved_geometry is None
        if saved_geometry is not None:
            detail_width = saved_geometry.width
            detail_height = saved_geometry.height
            placement = f"{saved_geometry.left:+d}{saved_geometry.top:+d}"
        else:
            position = self._detail_window_position(key)
            placement = (
                f"{position[0]:+d}{position[1]:+d}"
                if position is not None
                else ""
            )
        window.geometry(f"{detail_width}x{detail_height}{placement}")
        window.bind(
            "<Configure>",
            lambda event, key=key, window=window: self._schedule_detail_position_save(
                key, window
            )
            if event.widget is window
            else None,
        )
        window.protocol("WM_DELETE_WINDOW", window.withdraw)
        header = tk.Frame(window, background=self.FOREGROUND, padx=14, pady=10)
        header.pack(fill="x")
        tk.Label(
            header,
            text=action.title.upper(),
            background=self.FOREGROUND,
            foreground="#ffffff",
            font=self._section_font,
            anchor="w",
            justify="left",
            wraplength=detail_width - 52,
        ).pack(side="left", fill="x", expand=True)
        tk.Button(
            header,
            text="X",
            command=window.withdraw,
            background=self.FOREGROUND,
            foreground="#ffffff",
            activebackground=self.ACCENT,
            activeforeground="#ffffff",
            borderwidth=0,
            font=("Segoe UI Semibold", 9),
            padx=6,
            pady=2,
        ).pack(side="right")
        canvas = tk.Canvas(window, background=self.BACKGROUND, highlightthickness=0)
        scrollbar = tk.Scrollbar(window, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, background=self.BACKGROUND)
        setattr(body, "detail_wraplength", detail_width - 72)
        setattr(body, "detail_kind", "party" if action.label == "PARTY DETAILS" else "generic")
        if autosize_detail:
            setattr(
                body,
                "detail_autosize",
                (
                    window,
                    header,
                    scrollbar,
                    detail_width,
                    260 if compact_layout else 320,
                    detail_height,
                ),
            )
        rows = self._detail_rows(action.rows)
        self._detail_windows[key] = (window, body, rows)
        body.bind(
            "<Configure>",
            lambda _: self._sync_detail_scrollbar(canvas, scrollbar),
        )
        canvas_window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._render_detail_rows(body, rows)

    def _detail_rows(
        self,
        rows: tuple[PanelRow, ...],
        result: OverlaySnapshot | None = None,
    ) -> tuple[PanelRow, ...]:
        result = result or getattr(self, "_last_result", None)
        if (
            isinstance(result, OverlaySnapshot)
            and result.supports_caught_filter
            and self._hide_caught.get()
        ):
            return tuple(row for row in rows if row.caught is not True)
        return rows

    @staticmethod
    def _sync_detail_scrollbar(canvas: tk.Canvas, scrollbar: tk.Scrollbar) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
        first, last = canvas.yview()
        if first <= 0 and last >= 1:
            scrollbar.pack_forget()
        elif not scrollbar.winfo_manager():
            scrollbar.pack(side="right", fill="y")

    def _render_detail_rows(
        self, body: tk.Frame, rows: tuple[PanelRow, ...]
    ) -> None:
        for child in body.winfo_children():
            child.destroy()
        party_detail = getattr(body, "detail_kind", "generic") == "party"
        for row in rows:
            role = party_detail_row_role(row.text) if party_detail else "generic"
            if role == "pokemon":
                if body.winfo_children():
                    tk.Frame(
                        body,
                        background=self.DIVIDER,
                        height=1,
                    ).pack(fill="x", padx=14, pady=(8, 0))
                row_frame = tk.Frame(
                    body,
                    background="#e6e1d4",
                    padx=16,
                    pady=9,
                )
                row_frame.pack(fill="x", padx=10, pady=(0, 2))
                name, _, metadata = row.text.partition(" | ")
                tk.Label(
                    row_frame,
                    text=name,
                    background="#e6e1d4",
                    foreground=self.ACCENT,
                    font=self._section_font,
                    anchor="w",
                ).pack(fill="x")
                if metadata:
                    tk.Label(
                        row_frame,
                        text=metadata,
                        background="#e6e1d4",
                        foreground=self.MUTED,
                        font=self._body_font,
                        anchor="w",
                        justify="left",
                        wraplength=max(
                            180,
                            getattr(body, "detail_wraplength", 440) - 24,
                        ),
                    ).pack(fill="x", pady=(3, 0))
                continue
            if role != "generic":
                row_frame = tk.Frame(
                    body,
                    background=self.BACKGROUND,
                    padx=24,
                    pady=3,
                )
                row_frame.pack(
                    fill="x",
                    pady=(0, 8) if role == "moves" else 0,
                )
                row_frame.grid_columnconfigure(1, weight=1)
                label, _, values = row.text.partition(" | ")
                tk.Label(
                    row_frame,
                    text=label.upper(),
                    width=9,
                    background=self.BACKGROUND,
                    foreground=self.ACCENT if role in {"stats", "moves"} else self.MUTED,
                    font=("Segoe UI Semibold", 8),
                    anchor="nw",
                    justify="left",
                ).grid(row=0, column=0, sticky="nw")
                values_frame = tk.Frame(
                    row_frame,
                    background=self.BACKGROUND,
                )
                values_frame.grid(row=0, column=1, sticky="ew")
                columns = 2 if role == "moves" else 3
                value_wraplength = max(
                    92,
                    (getattr(body, "detail_wraplength", 440) - 160) // columns,
                )
                for column in range(columns):
                    values_frame.grid_columnconfigure(column, weight=1, uniform=role)
                for index, value in enumerate(values.split(" | ")):
                    tk.Label(
                        values_frame,
                        text=value,
                        background=self.BACKGROUND,
                        foreground=(
                            self.MUTED if role == "stat_exp" else self.FOREGROUND
                        ),
                        font=self._body_font,
                        anchor="w",
                        justify="left",
                        wraplength=value_wraplength,
                    ).grid(
                        row=index // columns,
                        column=index % columns,
                        sticky="w",
                        padx=(0, 12),
                        pady=(0, 2),
                    )
                continue
            heading = row.caught is None and row.text.isupper()
            row_frame = tk.Frame(
                body,
                background=self.BACKGROUND,
                padx=14,
                pady=(8 if heading else 2),
            )
            row_frame.pack(fill="x")
            indicator = "●" if row.caught else "○" if row.caught is False else ""
            indicator_color = "#27824a" if row.caught else self.MUTED
            tk.Label(
                row_frame,
                text=indicator,
                width=2,
                background=self.BACKGROUND,
                foreground=indicator_color,
                font=self._body_font,
                anchor="w",
            ).pack(side="left")
            tk.Label(
                row_frame,
                text=row.text,
                background=self.BACKGROUND,
                foreground=self.ACCENT if heading else self.FOREGROUND,
                font=self._section_font if heading else self._body_font,
                anchor="w",
                justify="left",
                wraplength=getattr(body, "detail_wraplength", 440),
            ).pack(side="left", fill="x", expand=True)
        autosize = getattr(body, "detail_autosize", None)
        if autosize is not None:
            window, header, scrollbar, width, minimum_height, height_cap = autosize
            window.update_idletasks()
            desired_height = max(
                minimum_height,
                header.winfo_reqheight() + body.winfo_reqheight() + 8,
            )
            maximum_height = min(
                height_cap,
                window.winfo_screenheight() - 2 * self.SCREEN_MARGIN,
            )
            window.geometry(f"{width}x{min(desired_height, maximum_height)}")
            window.update_idletasks()
            self._sync_detail_scrollbar(body.master, scrollbar)

    @staticmethod
    def _detail_position_key(key: tuple[str, str, str]) -> str:
        return "|".join(key)

    def _detail_window_position(
        self, key: tuple[str, str, str]
    ) -> tuple[int, int] | None:
        local_settings = getattr(self, "_local_settings", None)
        if local_settings is None:
            return None
        return local_settings.detail_window_position(
            self._detail_position_key(key)
        )

    def _schedule_detail_position_save(
        self, key: tuple[str, str, str], window: tk.Toplevel
    ) -> None:
        previous = self._detail_position_jobs.pop(key, None)
        if previous is not None:
            self.root.after_cancel(previous)
        self._detail_position_jobs[key] = self.root.after(
            250, lambda: self._save_detail_window_position(key, window)
        )

    def _save_detail_window_position(
        self, key: tuple[str, str, str], window: tk.Toplevel
    ) -> None:
        pending = getattr(self, "_detail_position_jobs", {}).pop(key, None)
        if pending is not None:
            self.root.after_cancel(pending)
        local_settings = getattr(self, "_local_settings", None)
        if local_settings is not None:
            local_settings.save_detail_window_position(
                self._detail_position_key(key), window.winfo_x(), window.winfo_y()
            )
            self._save_window_geometry(
                f"detail|{self._detail_position_key(key)}", window
            )

    def _sync_detail_windows(self, result: OverlaySnapshot | Exception | str) -> None:
        if not isinstance(result, OverlaySnapshot):
            for key, (window, _, _) in self._detail_windows.items():
                self._save_detail_window_position(key, window)
                window.destroy()
            self._detail_windows.clear()
            return
        actions = {
            (action.label, action.title): action
            for section in result.sections
            for action in section.actions
        }
        for key, (window, body, current_rows) in tuple(self._detail_windows.items()):
            game, label, title = key
            if game != result.game:
                self._save_detail_window_position(key, window)
                window.destroy()
                self._detail_windows.pop(key)
                continue
            action = actions.get((label, title))
            rows = (
                self._detail_rows(action.rows, result)
                if action is not None
                else current_rows
            )
            if rows != current_rows:
                self._render_detail_rows(body, rows)
                self._detail_windows[key] = (window, body, rows)

    def _sync_map_tools(self, result: OverlaySnapshot | Exception | str) -> None:
        position = result.map_position if isinstance(result, OverlaySnapshot) else None
        document = result.map_document if isinstance(result, OverlaySnapshot) else None
        if position is None or document is None:
            self._map_position = None
            self._map_document = None
            self._map_overlays = ()
            self._hero_paths.clear()
            self.map_controls.pack_forget()
            self._destroy_map_windows()
            return
        if document != self._map_document:
            if self._map_document is not None and document.title != self._map_document.title:
                self._hero_paths.clear()
            self._destroy_map_windows()
        self._map_document = document
        self._map_position = position
        self._map_overlays = result.map_overlays
        record_map_path(document, position, self._hero_paths)
        if not self._collapsed and not self.map_controls.winfo_manager():
            self.map_controls.pack(fill="x", before=self.scrollbar)
        for window in (self._map_window, self._minimap_window):
            if window is not None:
                window.update(position, self._map_overlays)

    def _sync_caught_filter(self, result: OverlaySnapshot | Exception | str) -> None:
        supported = isinstance(result, OverlaySnapshot) and result.supports_caught_filter
        if supported and not self.hide_caught_toggle.winfo_manager():
            self.hide_caught_toggle.pack(side="right")
        elif not supported and self.hide_caught_toggle.winfo_manager():
            self.hide_caught_toggle.pack_forget()

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_start = (event.x_root, event.y_root)
        self._drag_offset = (
            event.x_root - self.root.winfo_x(),
            event.y_root - self.root.winfo_y(),
        )

    def _drag(self, event: tk.Event) -> None:
        x_position = event.x_root - self._drag_offset[0]
        y_position = event.y_root - self._drag_offset[1]
        self.root.geometry(f"+{x_position}+{y_position}")

    def _scroll_main_panel(self, event: tk.Event) -> str | None:
        if self._collapsed or not self.canvas.winfo_manager():
            return None
        units = mouse_wheel_units(event)
        if units:
            self.canvas.yview_scroll(units, "units")
            return "break"
        return None

    def _main_window_configured(self, event: tk.Event) -> None:
        if (
            event.widget is not self.root
            or not self._window_initialized
            or self._collapsed
        ):
            return
        width, height = clamp_overlay_size(
            event.width,
            event.height,
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
        )
        self._manual_dimensions = (width, height)
        self.WIDTH = width
        self.canvas.configure(width=max(width - 18, 1))
        self.location_label.configure(wraplength=max(160, width - 65))
        for label in self._section_labels:
            label.configure(wraplength=max(120, width - 28))
        for label in self._row_labels:
            label.configure(wraplength=max(100, width - 76))
        if self._main_geometry_job is not None:
            self.root.after_cancel(self._main_geometry_job)
        self._main_geometry_job = self.root.after(
            250, self._save_native_main_geometry
        )

    def _save_native_main_geometry(self) -> None:
        self._main_geometry_job = None
        if self._collapsed:
            return
        self._save_window_geometry("main", self.root)
        self._save_window_geometry("main-native", self.root)

    def _finish_header_interaction(self, event: tk.Event) -> None:
        distance = abs(event.x_root - self._drag_start[0]) + abs(event.y_root - self._drag_start[1])
        if distance <= 4:
            self._toggle_collapsed()
        else:
            self._save_window_geometry("main", self.root)

    def _toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.status_bar.pack_forget()
            self.role_tabs.pack_forget()
            self.map_controls.pack_forget()
            self.scrollbar.pack_forget()
            self.canvas.pack_forget()
            self.root.update_idletasks()
            self._set_geometry(self.header.winfo_reqheight())
        else:
            width, height = self._manual_dimensions
            self.WIDTH = width
            self.status_bar.pack(fill="x")
            if self._role_tabs_supported():
                self.role_tabs.pack(fill="x")
            if self._map_position is not None and self._map_document is not None:
                self.map_controls.pack(fill="x")
            self.scrollbar.pack(side="right", fill="y")
            self.canvas.pack(side="left", fill="both", expand=True)
            self._set_geometry(height)
            self._resize_to_content()

    def _toggle_hide_caught(self) -> None:
        if isinstance(self._last_result, OverlaySnapshot):
            snapshot = self._last_result
            self._last_result = None
            self._render(snapshot)

    def _toggle_role(self) -> None:
        self._update_role_tabs()
        if isinstance(self._last_result, OverlaySnapshot):
            snapshot = self._last_result
            self._last_result = None
            self._render(snapshot)

    def _select_role(self, role: str) -> None:
        self._active_role.set(role)
        self._toggle_role()

    def _update_role_tabs(self) -> None:
        selected = self._active_role.get()
        for role, button in self._role_buttons.items():
            active = role == selected
            button.configure(
                background=self.ACCENT if active else "#e6e1d4",
                foreground="#ffffff" if active else self.FOREGROUND,
                activebackground=self.FOREGROUND if active else self.DIVIDER,
                activeforeground="#ffffff" if active else self.FOREGROUND,
            )

    def _show_layout_settings(self) -> None:
        if self._layout_dialog is not None and self._layout_dialog.window.winfo_exists():
            self._layout_dialog.window.lift()
            return
        self._layout_dialog = LayoutSettingsDialog(
            self.root,
            self._layout_manager.profile,
            self._high_contrast,
            self._save_layout_settings,
        )

    def _save_layout_settings(
        self, profile: LayoutProfile, high_contrast: bool
    ) -> None:
        self._layout_manager.profile = profile
        self._layout_manager.current = None
        contrast_changed = high_contrast != self._high_contrast
        self._high_contrast = high_contrast
        if self._local_settings is not None:
            self._local_settings.save_layout_profile(profile)
            self._local_settings.save_high_contrast_override(high_contrast)
        if contrast_changed:
            self._apply_contrast_palette(high_contrast)
        if isinstance(self._last_result, OverlaySnapshot):
            snapshot = self._last_result
            self._last_result = None
            self._render(snapshot)

    def _apply_contrast_palette(self, enabled: bool) -> None:
        old_values = {
            self.BACKGROUND,
            self.FOREGROUND,
            self.MUTED,
            self.ACCENT,
            self.DIVIDER,
            self.ALERT_BACKGROUND,
            self.ALERT_FOREGROUND,
            "#e6e1d4",
        }
        if enabled:
            palette = (
                "#ffffff",
                "#000000",
                "#333333",
                "#0046b8",
                "#000000",
                "#ffffff",
                "#a00000",
            )
        else:
            palette = (
                "#f4f1e8",
                "#20251f",
                "#687064",
                "#bb3e2f",
                "#cbc8bd",
                "#ffe9e5",
                "#9d1717",
            )
        (
            self.BACKGROUND,
            self.FOREGROUND,
            self.MUTED,
            self.ACCENT,
            self.DIVIDER,
            self.ALERT_BACKGROUND,
            self.ALERT_FOREGROUND,
        ) = palette
        replacements = {
            "#f4f1e8": self.BACKGROUND,
            "#20251f": self.FOREGROUND,
            "#687064": self.MUTED,
            "#bb3e2f": self.ACCENT,
            "#cbc8bd": self.DIVIDER,
            "#ffe9e5": self.ALERT_BACKGROUND,
            "#9d1717": self.ALERT_FOREGROUND,
            "#e6e1d4": "#ffffff" if enabled else "#e6e1d4",
            "#000000": self.FOREGROUND,
            "#333333": self.MUTED,
            "#0046b8": self.ACCENT,
            "#ffffff": self.BACKGROUND,
            "#a00000": self.ALERT_FOREGROUND,
        }
        for widget in self._widget_tree(self.root):
            for option in (
                "background",
                "foreground",
                "activebackground",
                "activeforeground",
                "highlightbackground",
                "highlightcolor",
                "selectcolor",
            ):
                try:
                    current = str(widget.cget(option)).casefold()
                except tk.TclError:
                    continue
                if current in {value.casefold() for value in old_values}:
                    replacement = replacements.get(current, current)
                    widget.configure(**{option: replacement})
        self.root.configure(background=self.BACKGROUND)
        self._update_role_tabs()

    @staticmethod
    def _widget_tree(root: tk.Misc) -> tuple[tk.Misc, ...]:
        widgets = [root]
        for child in root.winfo_children():
            widgets.extend(OverlayWindow._widget_tree(child))
        return tuple(widgets)

    def _toggle_section(self, key: tuple[str, str]) -> None:
        if key in self._expanded_sections:
            self._expanded_sections.remove(key)
        else:
            self._expanded_sections.add(key)
        if isinstance(self._last_result, OverlaySnapshot):
            snapshot = self._last_result
            self._last_result = None
            self._render(snapshot)

    def _drain_results(self) -> None:
        latest = self._controller.drain_latest()
        if latest is not None:
            self._render(latest)
        if not self._controller.stopped:
            self.root.after(100, self._drain_results)

    def _ui_heartbeat(self) -> None:
        if self._hang_watchdog is not None:
            self._hang_watchdog.heartbeat("Tk event loop idle")
        if not self._controller.stopped:
            self._heartbeat_job = self.root.after(250, self._ui_heartbeat)

    def _refresh_layout(self) -> None:
        if isinstance(self._last_result, OverlaySnapshot):
            snapshot = self._last_result
            if self._sync_layout(snapshot):
                self._last_result = None
                self._render(snapshot)
        if not self._controller.stopped:
            self.root.after(500, self._refresh_layout)

    def _sync_layout(self, result: OverlaySnapshot) -> bool:
        if result.display_spec is None:
            return False
        status = self._controller.last_status
        layout, changed = self._layout_manager.apply(
            self.root,
            result.display_spec,
            paused=status is not None and status.state == "PAUSED",
        )
        self._active_layout = layout
        if self.WIDTH != layout.primary_panel.width:
            self.WIDTH = layout.primary_panel.width
            self.location_label.configure(
                wraplength=max(160, self.WIDTH - 90)
            )
            changed = True
        if changed:
            self._rendered_layout = None
        return changed

    def _sync_role_tabs(self, result: OverlaySnapshot) -> None:
        supported = any(
            section.role in {"area", "party", "goals", "urgent"}
            for section in result.sections
        ) and (self._active_layout is None or self._active_layout.mode != "dual-strips")
        if supported and not self._collapsed and not self.role_tabs.winfo_manager():
            self.role_tabs.pack(fill="x", before=self.scrollbar)
        elif not supported and self.role_tabs.winfo_manager():
            self.role_tabs.pack_forget()

    def _role_tabs_supported(self) -> bool:
        return (
            isinstance(self._last_result, OverlaySnapshot)
            and any(
                section.role in {"area", "party", "goals", "urgent"}
                for section in self._last_result.sections
            )
            and (self._active_layout is None or self._active_layout.mode != "dual-strips")
        )

    def _sync_secondary_panel(self, result: OverlaySnapshot) -> None:
        panel = self._active_layout.secondary_panel if self._active_layout is not None else None
        if self._active_layout is None or self._active_layout.mode != "dual-strips" or panel is None:
            self._destroy_secondary_window()
            return
        sections = tuple(
            section
            for section in sorted(result.sections, key=lambda item: (not item.alert, item.priority))
            if section.role in {"urgent", "party", "goals"}
        )
        signature = tuple(
            (section.title, section.compact_rows or section.rows[:1])
            for section in sections
        )
        if self._secondary_window is None:
            self._secondary_window = tk.Toplevel(self.root)
            self._secondary_window.overrideredirect(True)
            self._secondary_window.attributes("-topmost", True)
            self._secondary_window.configure(background=self.FOREGROUND)
            self._secondary_body = tk.Frame(
                self._secondary_window, background=self.BACKGROUND, padx=10, pady=10
            )
            self._secondary_body.pack(fill="both", expand=True)
        self._secondary_window.geometry(
            f"{panel.width}x{panel.height}{panel.left:+d}{panel.top:+d}"
        )
        if signature == self._secondary_signature:
            return
        self._secondary_signature = signature
        assert self._secondary_body is not None
        for child in self._secondary_body.winfo_children():
            child.destroy()
        for section in sections:
            tk.Label(
                self._secondary_body,
                text=section.title.upper(),
                background=self.BACKGROUND,
                foreground=self.ALERT_FOREGROUND if section.alert else self.ACCENT,
                font=("Segoe UI Semibold", 8),
                anchor="w",
                justify="left",
                wraplength=max(60, panel.width - 20),
            ).pack(fill="x", pady=(5, 2))
            for row in (section.compact_rows or section.rows[:1]):
                tk.Label(
                    self._secondary_body,
                    text=row.text,
                    background=self.BACKGROUND,
                    foreground=self.FOREGROUND,
                    font=("Consolas", 8),
                    anchor="w",
                    justify="left",
                    wraplength=max(60, panel.width - 20),
                ).pack(fill="x", pady=(0, 3))

    def _destroy_secondary_window(self) -> None:
        if self._secondary_window is not None:
            self._secondary_window.destroy()
        self._secondary_window = None
        self._secondary_body = None
        self._secondary_signature = None

    def _render(
        self, result: OverlaySnapshot | OverlayDiagnostic | Exception | str
    ) -> None:
        if result == self._last_result:
            return
        self._sync_caught_filter(result)
        self._sync_map_tools(result)
        self._sync_detail_windows(result)
        section_views = self._section_views(result) if isinstance(result, OverlaySnapshot) else ()
        layout = self._layout_signature(section_views)
        if isinstance(result, OverlaySnapshot) and layout == self._rendered_layout:
            self._last_result = result
            self.game_label.configure(text=result.game.upper())
            self.location_label.configure(text=result.location)
            self.status_label.configure(
                text=(
                    "Live · read-only · Hardcore compatible · "
                    f"{self._controller.metrics.snapshot_seconds * 1000:.0f} ms"
                ),
                foreground=self.MUTED,
            )
            for label, (section, _, _, _) in zip(self._section_labels, section_views):
                label.configure(text=section.title.upper())
            visible_rows = [row for _, rows, _, _ in section_views for row in rows]
            for label, row in zip(self._row_labels, visible_rows):
                label.configure(text=row.text)
                self._update_row_tooltip(label, row.tooltip)
            return
        self._last_result = result
        self._rendered_layout = layout if isinstance(result, OverlaySnapshot) else None
        self._section_labels = []
        self._row_labels = []
        self._row_tooltips = {}
        self._hide_row_tooltip()
        previous_content = self.content
        self.content = tk.Frame(self.canvas, background=self.BACKGROUND)
        self.content.bind(
            "<Configure>",
            lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        if not isinstance(result, OverlaySnapshot):
            message = str(result)
            title = result.title if isinstance(result, OverlayDiagnostic) else "Not connected"
            self.location_label.configure(text=title)
            self.status_label.configure(text=message, foreground=self.ACCENT)
            self._swap_content(previous_content)
            self._resize_to_content()
            return

        self.game_label.configure(text=result.game.upper())
        self.location_label.configure(text=result.location)
        self.status_label.configure(
            text=(
                "Live · read-only · Hardcore compatible · "
                f"{self._controller.metrics.snapshot_seconds * 1000:.0f} ms"
            ),
            foreground=self.MUTED,
        )
        if not result.sections:
            tk.Label(
                self.content, text="No wild encounters on this map", background=self.BACKGROUND,
                foreground=self.MUTED, font=("Segoe UI", 9), padx=14, pady=12,
            ).pack(fill="x")
            self._swap_content(previous_content)
            self._resize_to_content()
            return

        for section, rows, hidden_count, section_key in section_views:
            block_background = self.ALERT_BACKGROUND if section.alert else self.BACKGROUND
            section_color = self.ALERT_FOREGROUND if section.alert else self.ACCENT
            block = tk.Frame(self.content, background=block_background, padx=14, pady=5)
            block.pack(fill="x")
            section_label = tk.Label(
                block, text=section.title.upper(), background=block_background,
                foreground=section_color, font=self._section_font, anchor="w",
                justify="left", wraplength=self.WIDTH - 28,
            )
            section_label.pack(fill="x", pady=(0, 5))
            self._section_labels.append(section_label)
            for row in rows:
                row_frame = tk.Frame(block, background=block_background)
                row_frame.pack(fill="x", pady=1)
                indicator = "●" if row.caught else "○" if row.caught is False else ""
                indicator_color = "#27824a" if row.caught else self.MUTED
                tk.Label(
                    row_frame, text=indicator, width=2, background=block_background,
                    foreground=indicator_color, font=self._body_font, anchor="w",
                ).pack(side="left")
                row_label = tk.Label(
                    row_frame, text=row.text, background=block_background,
                    foreground=self.FOREGROUND, font=self._body_font, anchor="w",
                    justify="left", wraplength=max(120, self.WIDTH - 76),
                )
                row_label.pack(side="left", fill="x", expand=True)
                self._row_labels.append(row_label)
                self._bind_row_tooltip(row_label, row.tooltip)
            for action in section.actions:
                tk.Button(
                    block,
                    text=action.label,
                    command=lambda action=action: self._show_detail(action),
                    background=block_background,
                    foreground=section_color,
                    activebackground=block_background,
                    activeforeground=self.FOREGROUND,
                    borderwidth=0,
                    font=("Segoe UI Semibold", 9),
                    anchor="w",
                    padx=0,
                    pady=3,
                ).pack(fill="x")
            if hidden_count or section_key in self._expanded_sections:
                label = f"+{hidden_count} more" if hidden_count else "Show less"
                tk.Button(
                    block,
                    text=label,
                    command=lambda key=section_key: self._toggle_section(key),
                    background=block_background,
                    foreground=section_color,
                    activebackground=block_background,
                    activeforeground=self.FOREGROUND,
                    borderwidth=0,
                    font=("Segoe UI Semibold", 9),
                    anchor="w",
                    padx=0,
                    pady=3,
                ).pack(fill="x")
            tk.Frame(
                block,
                height=1,
                background=section_color if section.alert else self.DIVIDER,
            ).pack(fill="x", pady=(7, 0))
        self._swap_content(previous_content)
        self._resize_to_content()

    def _section_views(
        self, result: OverlaySnapshot
    ) -> tuple[tuple[PanelSection, tuple[PanelRow, ...], int, tuple[str, str]], ...]:
        views = []
        hide_caught = result.supports_caught_filter and self._hide_caught.get()
        sections = sorted(
            filter_caught_sections(result.sections, hide_caught),
            key=lambda section: (not section.alert, section.priority),
        )
        for section in sections:
            section_identity = section.title.split(" · You (", 1)[0]
            section_key = (result.game, section_identity)
            expanded = section_key in self._expanded_sections
            rows, hidden_count = preview_section_rows(section, expanded)
            views.append((section, rows, hidden_count, section_key))
        return tuple(views)

    def _layout_signature(
        self,
        section_views: tuple[
            tuple[PanelSection, tuple[PanelRow, ...], int, tuple[str, str]], ...
        ],
    ) -> tuple[object, ...]:
        return tuple(
            (
                section_key,
                section.alert,
                tuple(row.caught for row in rows),
                tuple(action.label for action in section.actions),
                hidden_count,
            )
            for section, rows, hidden_count, section_key in section_views
        )

    def _swap_content(self, previous_content: tk.Frame) -> None:
        scroll_position = self.canvas.yview()[0]
        self.canvas.itemconfigure(self.canvas_window, window=self.content)
        previous_content.destroy()
        self.root.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(scroll_position)

    def _resize_to_content(self) -> None:
        if self._collapsed:
            return
        self.root.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _set_geometry(self, height: int) -> None:
        self.root.geometry(
            f"{self.WIDTH}x{height}{self.root.winfo_x():+d}{self.root.winfo_y():+d}"
        )

    def _window_geometry(self, key: str) -> ScreenRect | None:
        if self._local_settings is None:
            return None
        return self._local_settings.window_geometry(key)

    def _save_window_geometry(self, key: str, window: tk.Misc) -> None:
        if self._local_settings is None:
            return
        width = window.winfo_width()
        height = window.winfo_height()
        if not all(
            isinstance(value, int) and not isinstance(value, bool) and value > 1
            for value in (width, height)
        ):
            return
        left = window.winfo_x()
        top = window.winfo_y()
        self._local_settings.save_window_geometry(
            key, ScreenRect(left, top, left + width, top + height)
        )
