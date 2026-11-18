"""Colours, fonts and ttk styling (dark theme)."""
import tkinter as tk
from tkinter import ttk

BG = "#0f1420"
PANEL = "#151c2b"
CARD = "#1b2335"
CARD_HI = "#222c42"
BORDER = "#2a3550"
GRID = "#243049"
TEXT = "#e6ebf5"
MUTED = "#8a96b0"
ACCENT = "#4f8cff"
GOOD = "#2ecc8f"
WARN = "#f5b942"
BAD = "#ff5c6c"
INFO = "#6cc4ff"
PURPLE = "#a78bfa"
ORANGE = "#ff9f5a"
BAND = "#1f3050"

SEVERITY_COLORS = {"High": BAD, "Medium": WARN, "Low": INFO, "Info": GOOD}
TREND_COLORS = {"Chronic": BAD, "Deteriorating": BAD, "Short-term dip": WARN,
                "Improving": GOOD, "Stable": TEXT}

FAMILY = "Helvetica"
F_TITLE = (FAMILY, 20, "bold")
F_H2 = (FAMILY, 14, "bold")
F_H3 = (FAMILY, 12, "bold")
F_BODY = (FAMILY, 12)
F_SMALL = (FAMILY, 10)
F_KPI = (FAMILY, 22, "bold")
F_MONO = ("Menlo", 11)


def apply(root: tk.Tk) -> None:
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, font=F_BODY)
    style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
                    rowheight=26, borderwidth=0, font=F_BODY)
    style.map("Treeview", background=[("selected", "#2b4a86")], foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=PANEL, foreground=MUTED, relief="flat",
                    font=(FAMILY, 11, "bold"), padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", CARD_HI)])
    style.configure("TCombobox", fieldbackground=CARD_HI, background=CARD_HI, foreground=TEXT,
                    arrowcolor=TEXT, bordercolor=BORDER, lightcolor=CARD_HI, darkcolor=CARD_HI, padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", CARD_HI)], foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", CARD_HI)], selectforeground=[("readonly", TEXT)])
    style.configure("Vertical.TScrollbar", background=PANEL, troughcolor=BG, bordercolor=BG,
                    arrowcolor=MUTED, lightcolor=PANEL, darkcolor=PANEL)
    style.configure("TEntry", fieldbackground=CARD_HI, foreground=TEXT, insertcolor=TEXT,
                    bordercolor=BORDER, lightcolor=CARD_HI, darkcolor=CARD_HI, padding=4)
    root.option_add("*TCombobox*Listbox.background", CARD_HI)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.font", F_BODY)


def pct(v, digits=1):
    try:
        return "–" if v != v else f"{v * 100:.{digits}f}%"
    except TypeError:
        return "–"


def num(v, digits=0, suffix=""):
    try:
        return "–" if v is None or v != v else f"{v:,.{digits}f}{suffix}"
    except TypeError:
        return "–"


def health_color(score):
    return GOOD if score >= 80 else WARN if score >= 60 else BAD
