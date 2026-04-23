"""Shared tkinter styling for the user and hospital frontends.

Keeps palette, fonts, and button helpers in one place so the two apps
look like siblings instead of different projects.
"""

import tkinter as tk


# ── Palette ─────────────────────────────────────────────────────────────────
BG          = "#f5f7fa"   # window background
BG_PANEL    = "#ffffff"   # card / panel background
BG_SUBTLE   = "#eef2f7"   # muted panel / log background
BG_ACCENT   = "#1e3a5f"   # header bar
FG          = "#1a202c"
FG_MUTED    = "#6b7280"
FG_ON_BAR   = "#ffffff"
BORDER      = "#d6dde6"

BTN_PRIMARY_BG   = "#2563eb"
BTN_PRIMARY_FG   = "#ffffff"
BTN_SUCCESS_BG   = "#16a34a"
BTN_SUCCESS_FG   = "#ffffff"
BTN_DANGER_BG    = "#dc2626"
BTN_DANGER_FG    = "#ffffff"
BTN_NEUTRAL_BG   = "#e5e7eb"
BTN_NEUTRAL_FG   = "#1f2937"

STATUS_COLORS = {
    "docked":                      "#dcfce7",
    "assigned":                    "#ede9fe",
    "loading medicine":            "#fef9c3",
    "flight started":              "#dbeafe",
    "arrived, unloading medicine": "#fce7f3",
    "delivered, returning":        "#fce7f3",
    "returning":                   "#fce7f3",
    "cancel, returning":           "#ffe4e6",
    "timed out, returning":        "#ffedd5",
    "returned":                    "#dcfce7",
    "docking":                     "#dcfce7",
    "emergency_landed_empty":      "#fee2e2",
    "offline":                     "#e5e7eb",
}

# Per-drone identity colour (for map markers, hospital list stripes, etc.)
# Order matches the DRONES roster in application_server.config.
# No green in this palette — green is reserved for planned-path LEDs so the
# drone dot never blends into its own route.
DRONE_COLORS = [
    "#2563eb",  # blue     — drone-01
    "#dc2626",  # red      — drone-02
    "#ea580c",  # orange   — drone-03
    "#ca8a04",  # amber    — drone-04
    "#9333ea",  # purple   — drone-05
]


def drone_color(drone_id: str, index: int | None = None) -> str:
    if index is None:
        try:
            index = int(drone_id.split("-")[-1]) - 1
        except (ValueError, IndexError):
            index = 0
    return DRONE_COLORS[index % len(DRONE_COLORS)]


# ── Fonts ───────────────────────────────────────────────────────────────────
FONT_TITLE   = ("Helvetica", 16, "bold")
FONT_HEADER  = ("Helvetica", 12, "bold")
FONT_LABEL   = ("Helvetica", 10, "bold")
FONT_BODY    = ("Helvetica", 10)
FONT_SMALL   = ("Helvetica", 9)
FONT_MONO    = ("Courier", 9)
FONT_MONO_SM = ("Courier", 8)


# ── Helpers ────────────────────────────────────────────────────────────────
def apply_window(root: tk.Tk, title: str, width: int, height: int,
                 resizable: bool = False) -> None:
    root.title(title)
    root.geometry(f"{width}x{height}")
    root.configure(bg=BG)
    root.resizable(resizable, resizable)


def header_bar(parent: tk.Misc, title_text: str,
               subtitle_var: tk.StringVar | None = None,
               right_var: tk.StringVar | None = None) -> tk.Frame:
    bar = tk.Frame(parent, bg=BG_ACCENT)
    bar.pack(fill="x")
    inner = tk.Frame(bar, bg=BG_ACCENT)
    inner.pack(fill="x", padx=18, pady=12)
    tk.Label(inner, text=title_text, bg=BG_ACCENT, fg=FG_ON_BAR,
             font=FONT_TITLE).pack(side="left")
    if subtitle_var is not None:
        tk.Label(inner, textvariable=subtitle_var, bg=BG_ACCENT,
                 fg="#b7c4d6", font=FONT_BODY).pack(side="left", padx=(12, 0))
    if right_var is not None:
        tk.Label(inner, textvariable=right_var, bg=BG_ACCENT,
                 fg="#b7c4d6", font=FONT_MONO).pack(side="right")
    return bar


def card(parent: tk.Misc, **pack_kwargs) -> tk.Frame:
    frame = tk.Frame(parent, bg=BG_PANEL, highlightthickness=1,
                     highlightbackground=BORDER)
    defaults = {"fill": "x", "padx": 16, "pady": 8}
    defaults.update(pack_kwargs)
    frame.pack(**defaults)
    return frame


def _btn(parent: tk.Misc, text: str, command, bg: str, fg: str,
         width: int | None = None) -> tk.Button:
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
        relief="flat", borderwidth=0,
        font=FONT_LABEL, padx=14, pady=8,
        cursor="hand2",
    )
    if width is not None:
        btn.configure(width=width)
    return btn


def primary_button(parent, text, command, width=None):
    return _btn(parent, text, command, BTN_PRIMARY_BG, BTN_PRIMARY_FG, width)


def success_button(parent, text, command, width=None):
    return _btn(parent, text, command, BTN_SUCCESS_BG, BTN_SUCCESS_FG, width)


def danger_button(parent, text, command, width=None):
    return _btn(parent, text, command, BTN_DANGER_BG, BTN_DANGER_FG, width)


def neutral_button(parent, text, command, width=None):
    return _btn(parent, text, command, BTN_NEUTRAL_BG, BTN_NEUTRAL_FG, width)


def status_pill(parent: tk.Misc, text_var: tk.StringVar) -> tk.Label:
    """A rounded-looking label strip used for the current state."""
    return tk.Label(parent, textvariable=text_var, bg=BG_SUBTLE, fg=FG,
                    font=FONT_LABEL, padx=14, pady=6)
