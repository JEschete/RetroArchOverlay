import tkinter as tk
from collections.abc import Callable

from ...core.models import LayoutProfile


class LayoutSettingsDialog:
    def __init__(
        self,
        owner: tk.Misc,
        profile: LayoutProfile,
        theme: str,
        opacity: float,
        on_save: Callable[[LayoutProfile, str, float], None],
    ) -> None:
        self.window = tk.Toplevel(owner)
        self.window.title("Overlay Layout")
        self.window.attributes("-topmost", True)
        self.window.resizable(False, False)
        self.window.configure(background="#f4f1e8")
        self._on_save = on_save
        self.mode = tk.StringVar(value=profile.mode)
        self.side = tk.StringVar(value=profile.rail_side)
        self.width = tk.IntVar(value=profile.rail_width)
        self.density = tk.StringVar(value=profile.density)
        self.scaling = tk.StringVar(value=profile.game_scaling)
        self.manage_window = tk.BooleanVar(value=profile.manage_retroarch_window)
        self.theme = tk.StringVar(value=theme)
        self.opacity_percent = tk.IntVar(value=int(round(opacity * 100)))

        header = tk.Frame(self.window, background="#20251f", padx=16, pady=12)
        header.pack(fill="x")
        tk.Label(
            header,
            text="OVERLAY LAYOUT",
            background="#20251f",
            foreground="#ffffff",
            font=("Segoe UI Semibold", 11),
        ).pack(anchor="w")
        body = tk.Frame(self.window, background="#f4f1e8", padx=16, pady=12)
        body.pack(fill="both", expand=True)
        self._choice(body, "MODE", self.mode, ("auto", "rail", "dual-strips", "overlay"))
        self._choice(body, "SIDE", self.side, ("left", "right"))
        self._choice(body, "DENSITY", self.density, ("compact", "normal"))
        self._choice(body, "GAME SCALE", self.scaling, ("auto", "integer", "fit"))
        self._choice(
            body, "THEME", self.theme, ("auto", "light", "dark", "high-contrast")
        )

        width_row = tk.Frame(body, background="#f4f1e8")
        width_row.pack(fill="x", pady=(8, 0))
        tk.Label(
            width_row,
            text="RAIL WIDTH",
            background="#f4f1e8",
            foreground="#20251f",
            font=("Segoe UI Semibold", 9),
        ).pack(side="left")
        tk.Spinbox(
            width_row,
            from_=280,
            to=640,
            increment=20,
            textvariable=self.width,
            width=6,
            font=("Consolas", 10),
        ).pack(side="right")

        opacity_row = tk.Frame(body, background="#f4f1e8")
        opacity_row.pack(fill="x", pady=(8, 0))
        tk.Label(
            opacity_row,
            text="OPACITY %",
            background="#f4f1e8",
            foreground="#20251f",
            font=("Segoe UI Semibold", 9),
        ).pack(side="left")
        tk.Spinbox(
            opacity_row,
            from_=30,
            to=100,
            increment=5,
            textvariable=self.opacity_percent,
            width=6,
            font=("Consolas", 10),
        ).pack(side="right")
        tk.Checkbutton(
            body,
            text="Resize windowed RetroArch",
            variable=self.manage_window,
            background="#f4f1e8",
            activebackground="#f4f1e8",
            foreground="#20251f",
            selectcolor="#f4f1e8",
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x", pady=(8, 0))
        footer = tk.Frame(self.window, background="#e6e1d4", padx=16, pady=10)
        footer.pack(fill="x")
        tk.Button(
            footer,
            text="CANCEL",
            command=self.window.destroy,
            borderwidth=0,
            background="#e6e1d4",
            foreground="#687064",
            font=("Segoe UI Semibold", 9),
            padx=10,
            pady=5,
        ).pack(side="right")
        tk.Button(
            footer,
            text="SAVE",
            command=self._save,
            borderwidth=0,
            background="#bb3e2f",
            foreground="#ffffff",
            activebackground="#20251f",
            activeforeground="#ffffff",
            font=("Segoe UI Semibold", 9),
            padx=12,
            pady=5,
        ).pack(side="right", padx=(0, 8))
        self.window.update_idletasks()
        owner_x = owner.winfo_rootx()
        owner_y = owner.winfo_rooty()
        self.window.geometry(f"+{owner_x + 24}+{owner_y + 48}")

    @staticmethod
    def _choice(
        parent: tk.Misc,
        label: str,
        variable: tk.StringVar,
        values: tuple[str, ...],
    ) -> None:
        tk.Label(
            parent,
            text=label,
            background="#f4f1e8",
            foreground="#20251f",
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w", pady=(8, 3))
        row = tk.Frame(parent, background="#f4f1e8")
        row.pack(fill="x")
        for value in values:
            tk.Radiobutton(
                row,
                text=value.replace("-", " ").upper(),
                value=value,
                variable=variable,
                indicatoron=False,
                borderwidth=0,
                background="#e6e1d4",
                foreground="#20251f",
                selectcolor="#bb3e2f",
                activebackground="#cbc8bd",
                activeforeground="#20251f",
                font=("Segoe UI Semibold", 8),
                padx=7,
                pady=5,
            ).pack(side="left", padx=(0, 3))

    def _save(self) -> None:
        profile = LayoutProfile(
            mode=self.mode.get(),
            rail_side=self.side.get(),
            rail_width=max(280, min(640, self.width.get())),
            density=self.density.get(),
            game_scaling=self.scaling.get(),
            manage_retroarch_window=self.manage_window.get(),
        )
        opacity = max(30, min(100, self.opacity_percent.get())) / 100
        self._on_save(profile, self.theme.get(), opacity)
        self.window.destroy()