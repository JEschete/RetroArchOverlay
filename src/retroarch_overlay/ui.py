import queue
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import font as tkfont

from PIL import Image, ImageChops, ImageTk

from .adapters.base import AdapterRegistry
from .core.errors import GameUnavailableError
from .models import MapDocument, MapLayer, MapOverlay, MapPosition, MapRegion, MapWaypoint, OverlaySnapshot, PanelAction, PanelRow, PanelSection
from .local_settings import LocalPluginSettings
from .retroarch import RetroArchClient, RetroArchError


class SnapshotCadence:
    def __init__(self, interval_seconds: float = 0.25) -> None:
        self.interval_seconds = interval_seconds
        self._content_key: tuple[str, str, str] | None = None
        self._last_snapshot_at = 0.0

    def should_snapshot(self, status: RetroArchStatus, now: float) -> bool:
        if status.state not in {"PLAYING", "PAUSED"}:
            self._content_key = None
            return False
        content_key = (status.core, status.content, status.content_crc32)
        if content_key != self._content_key:
            self._content_key = content_key
            self._last_snapshot_at = now
            return True
        if status.state == "PAUSED" or now - self._last_snapshot_at < self.interval_seconds:
            return False
        self._last_snapshot_at = now
        return True


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
    OVERLAY_LABELS = {
        "player": "Player",
        "path": "Hero's path",
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
        self._images: dict[str, Image.Image] = {}
        self._overlay_waypoints: dict[str, tuple[MapWaypoint, ...]] = {}
        self._hero_paths: dict[str, list[tuple[int, int]]] = {}
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
        self.window.geometry("184x208" if compact else "760x800")
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
                pady=(0, 7),
            )
            overlay_bar.pack(fill="x")
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
        self.canvas.bind("<Configure>", lambda _: self._redraw())
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
                tags=("waypoint-tooltip",),
            )
            self.canvas.tag_lower(background, label)

    def _hide_waypoint(self) -> None:
        self.canvas.delete("waypoint-tooltip")

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self._redraw()

    def toggle(self) -> None:
        if self.window.state() == "withdrawn":
            self.show()
        else:
            self.hide()

    def hide(self) -> None:
        self.window.withdraw()

    def destroy(self) -> None:
        for image in self._images.values():
            image.close()
        self.window.destroy()

    def update(
        self, position: MapPosition, overlays: tuple[MapOverlay, ...] = ()
    ) -> None:
        previous = self.position
        matching = map_layer_for_position(self.document, position)
        self.position = position if matching is not None else tracked_map_position(previous, position)
        self._overlay_waypoints = {
            overlay.layer_key: overlay.waypoints for overlay in overlays
        }
        self._indoor_map_id = None if position.is_world or matching is not None else position.map_id
        if matching is not None and (
            previous is None
            or previous.area != position.area
            or previous.map_id != position.map_id
        ):
            self.mode.set(matching.key)
        if matching is not None:
            append_map_path(
                self._hero_paths.setdefault(matching.key, []),
                map_source_point(position, matching),
            )
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
        image = self._images.get(map_key)
        if image is None:
            layer = self.layers[map_key]
            image_path = layer.image_loader() if layer.image_loader is not None else layer.image_path
            image = Image.open(image_path).convert("RGB")
            self._images[map_key] = image
        return image

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
        self.canvas.delete("all")
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
        self._photo = ImageTk.PhotoImage(rendered)
        self.canvas.create_image(image_x, image_y, image=self._photo, anchor="nw")
        path_visibility = self.waypoint_visibility.get("path")
        if not self.compact and path_visibility is not None and path_visibility.get():
            path = self._hero_paths.get(layer.key, ())
            projected_path = []
            for path_x, path_y in path:
                if self.zoom == 1:
                    projected_path.append((image_x + path_x * scale, image_y + path_y * scale))
                else:
                    projected_path.append(
                        (
                            width / 2 + wrapped_map_delta(path_x, center_x, source.width) * scale,
                            height / 2 + wrapped_map_delta(path_y, center_y, source.height) * scale,
                        )
                    )
            for start, end in zip(projected_path, projected_path[1:]):
                if abs(start[0] - end[0]) > width / 2 or abs(start[1] - end[1]) > height / 2:
                    continue
                if not (
                    -8 <= start[0] <= width + 8
                    and -8 <= start[1] <= height + 8
                    and -8 <= end[0] <= width + 8
                    and -8 <= end[1] <= height + 8
                ):
                    continue
                self.canvas.create_line(
                    *start,
                    *end,
                    fill="#2f8f83",
                    width=2,
                    tags=("hero-path",),
                )
        if not self.compact:
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
                    region_x = (left + right) / 2
                    region_y = (top + bottom) / 2
                    radius = 4
                    self.canvas.create_oval(
                        region_x - radius,
                        region_y - radius,
                        region_x + radius,
                        region_y + radius,
                        fill=OverlayWindow.FOREGROUND,
                        outline=region.color,
                        width=2,
                        tags=(tag, "region"),
                    )
                    tooltip_x, tooltip_y = region_x, region_y
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
            )
        waypoints = layer.waypoints + self._overlay_waypoints.get(layer.key, ())
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
            waypoint_color = {
                "collectibles": "#16817a",
                "npcs": "#3d6da8",
            }.get(waypoint.kind, "#bb3e2f")
            self.canvas.create_oval(
                point_x - 4,
                point_y - 4,
                point_x + 4,
                point_y + 4,
                fill=waypoint_color,
                outline="#ffffff",
                width=1,
                tags=(tag, "waypoint"),
            )
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


class OverlayWindow:
    WIDTH = 320
    SCREEN_MARGIN = 12
    BACKGROUND = "#f4f1e8"
    FOREGROUND = "#20251f"
    MUTED = "#687064"
    ACCENT = "#bb3e2f"
    DIVIDER = "#cbc8bd"

    def __init__(
        self,
        client: RetroArchClient,
        registry: AdapterRegistry,
        opacity: float = 0.72,
        local_settings: LocalPluginSettings | None = None,
    ):
        if not 0.3 <= opacity <= 1.0:
            raise ValueError("Opacity must be between 0.3 and 1.0")
        self.client = client
        self.registry = registry
        self._local_settings = local_settings
        self._idle_opacity = opacity
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.title("RetroArch Overlay")
        screen_width = self.root.winfo_screenwidth()
        x_position = screen_width - self.WIDTH - self.SCREEN_MARGIN
        self.root.geometry(f"{self.WIDTH}x180+{x_position}+{self.SCREEN_MARGIN}")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self._idle_opacity)
        self.root.configure(background=self.BACKGROUND)
        self._results: queue.SimpleQueue[OverlaySnapshot | Exception | str] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._last_result: OverlaySnapshot | Exception | str | None = None
        self._drag_offset = (0, 0)
        self._drag_start = (0, 0)
        self._collapsed = False
        self._expanded_sections: set[tuple[str, str, str]] = set()
        self._hide_caught = tk.BooleanVar(value=False)
        self._rendered_layout: tuple[object, ...] | None = None
        self._section_labels: list[tk.Label] = []
        self._row_labels: list[tk.Label] = []
        self._map_position: MapPosition | None = None
        self._map_document: MapDocument | None = None
        self._map_overlays: tuple[MapOverlay, ...] = ()
        self._map_window: CoordinateMapWindow | None = None
        self._minimap_window: CoordinateMapWindow | None = None
        self._detail_windows: dict[
            tuple[str, str, str], tuple[tk.Toplevel, tk.Frame, tuple[PanelRow, ...]]
        ] = {}
        self._detail_position_jobs: dict[tuple[str, str, str], str] = {}
        self._snapshot_cadence = SnapshotCadence()

        self._title_font = tkfont.Font(family="Georgia", size=18, weight="bold")
        self._section_font = tkfont.Font(family="Segoe UI Semibold", size=10)
        self._body_font = tkfont.Font(family="Consolas", size=10)
        self._build()
        self.root.bind("<Enter>", lambda _: self.root.attributes("-alpha", 0.96))
        self.root.bind("<Leave>", lambda _: self.root.attributes("-alpha", self._idle_opacity))
        self.root.protocol("WM_DELETE_WINDOW", self.close)

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
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", self._finish_header_interaction)

        self.status_bar = tk.Frame(self.root, background=self.BACKGROUND)
        self.status_bar.pack(fill="x")
        self.status_label = tk.Label(
            self.status_bar, text="Connecting to 127.0.0.1:55355", background=self.BACKGROUND,
            foreground=self.MUTED, font=("Segoe UI", 8), anchor="w", padx=14, pady=6,
        )
        self.status_label.pack(side="left", fill="x", expand=True)
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
            text="Hide caught",
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

    def run(self) -> None:
        threading.Thread(target=self._poll, daemon=True).start()
        self.root.after(100, self._drain_results)
        self.root.mainloop()

    def close(self) -> None:
        self._stop.set()
        self._destroy_map_windows()
        for key, (window, _, _) in self._detail_windows.items():
            self._save_detail_window_position(key, window)
            window.destroy()
        self._detail_windows.clear()
        self._detail_position_jobs.clear()
        self.root.destroy()

    def _show_map(self) -> None:
        if self._map_position is None or self._map_document is None:
            return
        if self._map_window is None:
            self._map_window = CoordinateMapWindow(self.root, self._map_document)
        self._map_window.update(self._map_position, self._map_overlays)
        self._map_window.toggle()

    def _show_minimap(self) -> None:
        if self._map_position is None or self._map_document is None:
            return
        if self._minimap_window is None:
            self._minimap_window = CoordinateMapWindow(
                self.root, self._map_document, compact=True
            )
        self._minimap_window.update(self._map_position, self._map_overlays)
        self._minimap_window.toggle()

    def _destroy_map_windows(self) -> None:
        for window in (self._map_window, self._minimap_window):
            if window is not None:
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
        poc_layout = action.title == "Professor Oak Challenge"
        if poc_layout:
            detail_width = self.WIDTH
            detail_height = 180
        else:
            detail_width = min(720, max(520, int(window.winfo_screenwidth() * 0.38)))
            detail_height = min(720, max(560, int(window.winfo_screenheight() * 0.72)))
        position = self._detail_window_position(key)
        placement = (
            f"{position[0]:+d}{position[1]:+d}" if position is not None else ""
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
        if poc_layout:
            setattr(body, "detail_autosize", (window, header, scrollbar))
        self._detail_windows[key] = (window, body, action.rows)
        body.bind(
            "<Configure>",
            lambda _: self._sync_detail_scrollbar(canvas, scrollbar),
        )
        canvas_window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._render_detail_rows(body, action.rows)

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
        for row in rows:
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
            window, header, scrollbar = autosize
            window.update_idletasks()
            desired_height = header.winfo_reqheight() + body.winfo_reqheight()
            maximum_height = window.winfo_screenheight() - 2 * self.SCREEN_MARGIN
            window.geometry(f"{self.WIDTH}x{min(desired_height, maximum_height)}")
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
            if action is not None and action.rows != current_rows:
                self._render_detail_rows(body, action.rows)
                self._detail_windows[key] = (window, body, action.rows)

    def _sync_map_tools(self, result: OverlaySnapshot | Exception | str) -> None:
        position = result.map_position if isinstance(result, OverlaySnapshot) else None
        document = result.map_document if isinstance(result, OverlaySnapshot) else None
        if position is None or document is None:
            self._map_position = None
            self._map_document = None
            self._map_overlays = ()
            self.map_controls.pack_forget()
            self._destroy_map_windows()
            return
        if document != self._map_document:
            self._destroy_map_windows()
        self._map_document = document
        self._map_position = position
        self._map_overlays = result.map_overlays
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

    def _finish_header_interaction(self, event: tk.Event) -> None:
        distance = abs(event.x_root - self._drag_start[0]) + abs(event.y_root - self._drag_start[1])
        if distance <= 4:
            self._toggle_collapsed()

    def _toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.status_bar.pack_forget()
            self.map_controls.pack_forget()
            self.scrollbar.pack_forget()
            self.canvas.pack_forget()
            self.root.update_idletasks()
            self._set_geometry(self.header.winfo_reqheight())
        else:
            self.status_bar.pack(fill="x")
            if self._map_position is not None and self._map_document is not None:
                self.map_controls.pack(fill="x")
            self.scrollbar.pack(side="right", fill="y")
            self.canvas.pack(side="left", fill="both", expand=True)
            self._resize_to_content()

    def _toggle_hide_caught(self) -> None:
        if isinstance(self._last_result, OverlaySnapshot):
            snapshot = self._last_result
            self._last_result = None
            self._render(snapshot)

    def _toggle_section(self, key: tuple[str, str, str]) -> None:
        if key in self._expanded_sections:
            self._expanded_sections.remove(key)
        else:
            self._expanded_sections.add(key)
        if isinstance(self._last_result, OverlaySnapshot):
            snapshot = self._last_result
            self._last_result = None
            self._render(snapshot)

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                status = self.client.get_status()
                if status.state not in {"PLAYING", "PAUSED"}:
                    self._snapshot_cadence.should_snapshot(status, time.monotonic())
                    self._results.put(f"RetroArch is {status.state.lower()}")
                elif self._snapshot_cadence.should_snapshot(status, time.monotonic()):
                    adapter = self.registry.find(status)
                    if adapter is None:
                        self._results.put(f"No adapter for {status.core}: {status.content}")
                    else:
                        self._results.put(adapter.snapshot(self.client))
            except (GameUnavailableError, OSError, RetroArchError, ValueError) as error:
                self._results.put(error)
            self._stop.wait(0.1)

    def _drain_results(self) -> None:
        latest: OverlaySnapshot | Exception | str | None = None
        while True:
            try:
                latest = self._results.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self._render(latest)
        if not self._stop.is_set():
            self.root.after(100, self._drain_results)

    def _render(self, result: OverlaySnapshot | Exception | str) -> None:
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
                text="Live · read-only · Hardcore compatible", foreground=self.MUTED
            )
            for label, (section, _, _, _) in zip(self._section_labels, section_views):
                label.configure(text=section.title.upper())
            visible_rows = [row for _, rows, _, _ in section_views for row in rows]
            for label, row in zip(self._row_labels, visible_rows):
                label.configure(text=row.text)
            return
        self._last_result = result
        self._rendered_layout = layout if isinstance(result, OverlaySnapshot) else None
        self._section_labels = []
        self._row_labels = []
        previous_content = self.content
        self.content = tk.Frame(self.canvas, background=self.BACKGROUND)
        self.content.bind(
            "<Configure>",
            lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        if not isinstance(result, OverlaySnapshot):
            message = str(result)
            self.location_label.configure(text="Not connected")
            self.status_label.configure(text=message, foreground=self.ACCENT)
            self._swap_content(previous_content)
            self._resize_to_content()
            return

        self.game_label.configure(text=result.game.upper())
        self.location_label.configure(text=result.location)
        self.status_label.configure(text="Live · read-only · Hardcore compatible", foreground=self.MUTED)
        if not result.sections:
            tk.Label(
                self.content, text="No wild encounters on this map", background=self.BACKGROUND,
                foreground=self.MUTED, font=("Segoe UI", 9), padx=14, pady=12,
            ).pack(fill="x")
            self._swap_content(previous_content)
            self._resize_to_content()
            return

        for section, rows, hidden_count, section_key in section_views:
            block_background = "#ffe9e5" if section.alert else self.BACKGROUND
            section_color = "#9d1717" if section.alert else self.ACCENT
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
                    justify="left", wraplength=self.WIDTH - 58,
                )
                row_label.pack(side="left", fill="x", expand=True)
                self._row_labels.append(row_label)
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
    ) -> tuple[tuple[PanelSection, tuple[PanelRow, ...], int, tuple[str, str, str]], ...]:
        views = []
        hide_caught = result.supports_caught_filter and self._hide_caught.get()
        for section in filter_caught_sections(result.sections, hide_caught):
            section_identity = section.title.split(" · You (", 1)[0]
            section_key = (result.game, result.location, section_identity)
            rows, hidden_count = preview_section_rows(
                section, section_key in self._expanded_sections
            )
            views.append((section, rows, hidden_count, section_key))
        return tuple(views)

    def _layout_signature(
        self,
        section_views: tuple[
            tuple[PanelSection, tuple[PanelRow, ...], int, tuple[str, str, str]], ...
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
        fixed_height = self.header.winfo_reqheight() + self.status_bar.winfo_reqheight()
        if self.map_controls.winfo_manager():
            fixed_height += self.map_controls.winfo_reqheight()
        desired_height = fixed_height + self.content.winfo_reqheight() + 4
        maximum_height = int(self.root.winfo_screenheight() * 0.7)
        height = min(max(desired_height, 130), maximum_height)
        self.canvas.configure(height=max(height - fixed_height, 1))
        self._set_geometry(height)

    def _set_geometry(self, height: int) -> None:
        self.root.geometry(
            f"{self.WIDTH}x{height}+{self.root.winfo_x()}+{self.root.winfo_y()}"
        )
