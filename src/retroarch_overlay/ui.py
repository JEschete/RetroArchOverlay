import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

from PIL import Image, ImageTk

from .adapters.base import AdapterRegistry
from .models import MapPosition, OverlaySnapshot, PanelRow, PanelSection
from .retroarch import RetroArchClient, RetroArchError


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


class CoordinateMapWindow:
    MAP_ROOT = Path(__file__).resolve().parents[2] / "resources" / "dragon_warrior_3"
    MAPS = {
        "world": ("Main World", MAP_ROOT / "world.png"),
        "underworld": ("Alefgard", MAP_ROOT / "underworld.png"),
    }

    def __init__(self, owner: tk.Tk, compact: bool = False) -> None:
        self.compact = compact
        self.position: MapPosition | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._images = {
            key: Image.open(path).convert("RGB")
            for key, (_, path) in self.MAPS.items()
        }
        self.window = tk.Toplevel(owner)
        self.window.title("Dragon Warrior III Minimap" if compact else "Dragon Warrior III Map")
        self.window.attributes("-topmost", True)
        self.window.geometry("184x208" if compact else "760x800")
        if compact:
            self.window.resizable(False, False)
        self.window.configure(background=OverlayWindow.BACKGROUND)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.mode = tk.StringVar(value="world")
        if not compact:
            toolbar = tk.Frame(self.window, background=OverlayWindow.FOREGROUND, padx=10, pady=8)
            toolbar.pack(fill="x")
            for value, (text, _) in self.MAPS.items():
                tk.Radiobutton(
                    toolbar,
                    text=text.upper(),
                    value=value,
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
        self.canvas = tk.Canvas(
            self.window,
            background="#050a12",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self._redraw())
        self.window.withdraw()

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self._redraw()

    def hide(self) -> None:
        self.window.withdraw()

    def destroy(self) -> None:
        for image in self._images.values():
            image.close()
        self.window.destroy()

    def update(self, position: MapPosition) -> None:
        previous = self.position
        self.position = position
        if not self.compact and previous is None and position.area == "Underworld":
            self.mode.set("underworld")
        self._redraw()

    def _map_key(self) -> str:
        if not self.compact:
            return self.mode.get()
        return "underworld" if self.position and self.position.area == "Underworld" else "world"

    @staticmethod
    def _source_point(position: MapPosition, map_key: str) -> tuple[int, int]:
        border = 16 if map_key == "underworld" else 0
        return border + position.x * 16 + 8, border + position.y * 16 + 8

    def _redraw(self) -> None:
        self.canvas.delete("all")
        if self.position is None:
            return
        width = max(self.canvas.winfo_width(), 100)
        height = max(self.canvas.winfo_height(), 100)
        if self.compact and not self.position.is_world:
            self.heading.configure(text=f"Map {self.position.map_id:04X} · indoors")
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
        source = self._images[map_key]
        source_x, source_y = self._source_point(self.position, map_key)
        if self.compact:
            crop_size = 18 * 16
            crop = source.crop(
                (
                    source_x - crop_size // 2,
                    source_y - crop_size // 2,
                    source_x + crop_size // 2,
                    source_y + crop_size // 2,
                )
            )
            side = min(width, height)
            rendered = crop.resize((side, side), Image.Resampling.NEAREST)
            image_x = (width - side) / 2
            image_y = (height - side) / 2
            marker_x = width / 2
            marker_y = height / 2
        else:
            scale = min(width / source.width, height / source.height)
            image_width = max(1, int(source.width * scale))
            image_height = max(1, int(source.height * scale))
            rendered = source.resize(
                (image_width, image_height), Image.Resampling.NEAREST
            )
            image_x = (width - image_width) / 2
            image_y = (height - image_height) / 2
            marker_x = image_x + source_x * scale
            marker_y = image_y + source_y * scale
        self._photo = ImageTk.PhotoImage(rendered)
        self.canvas.create_image(image_x, image_y, image=self._photo, anchor="nw")
        matching_area = (
            self.position.area == "World" and map_key == "world"
        ) or (
            self.position.area == "Underworld" and map_key == "underworld"
        )
        if self.compact or matching_area:
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
        map_name = self.MAPS[map_key][0]
        self.heading.configure(
            text=f"{map_name} · ({self.position.x},{self.position.y})"
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
        self, client: RetroArchClient, registry: AdapterRegistry, opacity: float = 0.72
    ):
        if not 0.3 <= opacity <= 1.0:
            raise ValueError("Opacity must be between 0.3 and 1.0")
        self.client = client
        self.registry = registry
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
        self._map_window: CoordinateMapWindow | None = None
        self._minimap_window: CoordinateMapWindow | None = None

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
            ("WORLD MAP", self._show_map),
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
        self.hide_caught_toggle.pack(side="right")

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
        self.root.destroy()

    def _show_map(self) -> None:
        if self._map_position is None:
            return
        if self._map_window is None:
            self._map_window = CoordinateMapWindow(self.root)
        self._map_window.update(self._map_position)
        self._map_window.show()

    def _show_minimap(self) -> None:
        if self._map_position is None:
            return
        if self._minimap_window is None:
            self._minimap_window = CoordinateMapWindow(self.root, compact=True)
        self._minimap_window.update(self._map_position)
        self._minimap_window.show()

    def _destroy_map_windows(self) -> None:
        for window in (self._map_window, self._minimap_window):
            if window is not None:
                window.destroy()
        self._map_window = None
        self._minimap_window = None

    def _sync_map_tools(self, result: OverlaySnapshot | Exception | str) -> None:
        position = result.map_position if isinstance(result, OverlaySnapshot) else None
        if position is None:
            self._map_position = None
            self.map_controls.pack_forget()
            self._destroy_map_windows()
            return
        self._map_position = position
        if not self._collapsed and not self.map_controls.winfo_manager():
            self.map_controls.pack(fill="x", before=self.scrollbar)
        for window in (self._map_window, self._minimap_window):
            if window is not None:
                window.update(position)

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
            if self._map_position is not None:
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
                    self._results.put(f"RetroArch is {status.state.lower()}")
                else:
                    adapter = self.registry.find(status)
                    if adapter is None:
                        self._results.put(f"No adapter for {status.core}: {status.content}")
                    else:
                        self._results.put(adapter.snapshot(self.client))
            except (OSError, RetroArchError, ValueError) as error:
                self._results.put(error)
            self._stop.wait(0.5)

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
        self._sync_map_tools(result)
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
        for section in filter_caught_sections(result.sections, self._hide_caught.get()):
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
            (section_key, section.alert, tuple(row.caught for row in rows), hidden_count)
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
