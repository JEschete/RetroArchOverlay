import json
import re
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import keyring


KEYRING_SERVICE = "RetroArch Overlay"

@dataclass(frozen=True, slots=True)
class RAProgress:
    username: str
    unlocked_ids: frozenset[int]
    message: str = ""


def retroarch_setting(config_path: Path, name: str) -> str:
    if not config_path.is_file():
        return ""
    match = re.search(
        rf'^{re.escape(name)}\s*=\s*"([^"]*)"',
        config_path.read_text(encoding="utf-8", errors="replace"),
        re.MULTILINE,
    )
    return match.group(1) if match else ""


def clear_ra_api_key(config_path: Path) -> None:
    username = retroarch_setting(config_path, "cheevos_username")
    if not username:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, username)
    except keyring.errors.PasswordDeleteError:
        pass


def get_ra_api_key(config_path: Path) -> str:
    username = retroarch_setting(config_path, "cheevos_username")
    if not username:
        return ""
    stored = keyring.get_password(KEYRING_SERVICE, username)
    if stored:
        return stored

    root = tk.Tk()
    root.title("RetroAchievements API Key")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="RetroAchievements", font=("Segoe UI", 14, "bold")).pack(
        anchor="w"
    )
    ttk.Label(frame, text=f"Account: {username}").pack(anchor="w", pady=(8, 0))
    ttk.Label(frame, text="Enter your Web API key:").pack(anchor="w", pady=(12, 3))
    api_key = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=api_key, width=42, show="*")
    entry.pack(fill="x")
    link = tk.Label(
        frame,
        text="Get API key from retroachievements.org/settings",
        foreground="#1769aa",
        cursor="hand2",
        font=("Segoe UI", 9, "underline"),
    )
    link.pack(anchor="w", pady=(8, 12))
    link.bind(
        "<Button-1>", lambda _: webbrowser.open("https://retroachievements.org/settings")
    )
    result = {"key": ""}

    def save() -> None:
        value = api_key.get().strip()
        if not value:
            messagebox.showerror("API key required", "Enter your RA Web API key.", parent=root)
            return
        keyring.set_password(KEYRING_SERVICE, username, value)
        result["key"] = value
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")
    ttk.Button(buttons, text="Cancel", command=root.destroy).pack(side="right")
    ttk.Button(buttons, text="Save", command=save).pack(side="right", padx=(0, 8))
    root.bind("<Return>", lambda _: save())
    root.bind("<Escape>", lambda _: root.destroy())
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.update_idletasks()
    x = (root.winfo_screenwidth() - root.winfo_reqwidth()) // 2
    y = (root.winfo_screenheight() - root.winfo_reqheight()) // 2
    root.geometry(f"+{x}+{y}")
    entry.focus_set()
    root.mainloop()
    return result["key"]


def load_ra_progress(
    config_path: Path,
    game_id: int,
    api_key: str,
    opener: Callable[..., object] = urlopen,
) -> RAProgress:
    username = retroarch_setting(config_path, "cheevos_username")
    if not username:
        return RAProgress("", frozenset(), "RetroAchievements username not configured")
    if not api_key:
        return RAProgress(
            username,
            frozenset(),
            "RA account progress not loaded",
        )

    query = urlencode({"z": username, "y": api_key, "u": username, "g": game_id})
    request = Request(
        "https://retroachievements.org/API/API_GetGameInfoAndUserProgress.php?"
        + query,
        headers={"User-Agent": "RetroArchOverlay/1.0"},
    )
    try:
        with opener(request, timeout=8) as response:
            document = json.load(response)
    except (OSError, ValueError) as error:
        return RAProgress(username, frozenset(), f"Account progress unavailable: {error}")

    achievements = document.get("Achievements", {})
    unlocked = frozenset(
        int(achievement_id)
        for achievement_id, details in achievements.items()
        if details.get("DateEarned") or details.get("DateEarnedHardcore")
    )
    return RAProgress(username, unlocked)