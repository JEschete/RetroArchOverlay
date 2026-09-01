import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk


def prompt_ra_api_key(username: str) -> str:
    root = tk.Tk()
    root.title("RetroAchievements API Key")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="RetroAchievements", font=("Segoe UI", 14, "bold")).pack(anchor="w")
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
    link.bind("<Button-1>", lambda _: webbrowser.open("https://retroachievements.org/settings"))
    result = {"key": ""}

    def save() -> None:
        value = api_key.get().strip()
        if not value:
            messagebox.showerror("API key required", "Enter your RA Web API key.", parent=root)
            return
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