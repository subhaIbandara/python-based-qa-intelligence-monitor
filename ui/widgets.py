"""Reusable Tkinter widgets: scrollable page, cards, KPI tiles, gauge, tables."""
import math
import threading
import tkinter as tk
from tkinter import ttk

from ui import theme as T


def run_async(widget, work, done, poll_ms=50):
    """Run work() in a background thread; call done(value, error) on the Tk
    main thread. Tkinter is not thread-safe, so the worker never touches widgets."""
    result = {}

    def target():
        try:
            result["value"] = work()
        except Exception as err:  # noqa: BLE001 — handed to done()
            result["error"] = err

    thread = threading.Thread(target=target, daemon=True)
    thread.start()

    def check():
        if thread.is_alive():
            widget.after(poll_ms, check)
        else:
            done(result.get("value"), result.get("error"))

    widget.after(poll_ms, check)


class FlatButton(tk.Label):
    """Label-based button: tk.Button ignores bg/fg on macOS, this does not."""

    def __init__(self, parent, text, command, bg=T.ACCENT, fg="#ffffff", hover=None, font=None,
                 padx=16, pady=8):
        super().__init__(parent, text=text, bg=bg, fg=fg, font=font or (T.FAMILY, 12, "bold"),
                         padx=padx, pady=pady, cursor="hand2")
        self._bg, self._hover, self.command, self.enabled = bg, hover or _shade(bg), command, True
        self.bind("<Enter>", lambda e: self.enabled and self.configure(bg=self._hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg))
        self.bind("<Button-1>", lambda e: self.enabled and self.command())

    def set_enabled(self, enabled: bool, text: str = None):
        self.enabled = enabled
        self.configure(fg="#ffffff" if enabled else T.MUTED, cursor="hand2" if enabled else "arrow")
        if text:
            self.configure(text=text)


def _shade(hex_color, factor=1.15):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(min(255, int(c * factor)) for c in (r, g, b))


class ScrollFrame(tk.Frame):
    """A page whose content (self.inner) scrolls vertically."""

    def __init__(self, parent):
        super().__init__(parent, bg=T.BG)
        self.canvas = tk.Canvas(self, bg=T.BG, highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=T.BG)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event):
        # macOS gives small deltas; Windows multiples of 120
        delta = event.delta if abs(event.delta) < 120 else event.delta // 120
        self.canvas.yview_scroll(-delta, "units")


class Card(tk.Frame):
    """Panel with an optional title row; put content in self.body."""

    def __init__(self, parent, title=None, subtitle=None, padx=14, pady=12):
        super().__init__(parent, bg=T.CARD, highlightbackground=T.BORDER, highlightthickness=1)
        if title:
            head = tk.Frame(self, bg=T.CARD)
            head.pack(fill="x", padx=padx, pady=(pady, 0))
            tk.Label(head, text=title, font=T.F_H3, fg=T.TEXT, bg=T.CARD).pack(side="left")
            if subtitle:
                tk.Label(head, text=subtitle, font=T.F_SMALL, fg=T.MUTED, bg=T.CARD).pack(side="left", padx=8)
            self.head = head
        self.body = tk.Frame(self, bg=T.CARD)
        self.body.pack(fill="both", expand=True, padx=padx, pady=pady)


class KpiTile(tk.Frame):
    def __init__(self, parent, title, hint=""):
        super().__init__(parent, bg=T.CARD, highlightbackground=T.BORDER, highlightthickness=1)
        tk.Label(self, text=title.upper(), font=(T.FAMILY, 9, "bold"), fg=T.MUTED, bg=T.CARD,
                 anchor="w").pack(fill="x", padx=12, pady=(10, 0))
        self.value = tk.Label(self, text="–", font=T.F_KPI, fg=T.TEXT, bg=T.CARD, anchor="w")
        self.value.pack(fill="x", padx=12)
        self.sub = tk.Label(self, text=hint, font=T.F_SMALL, fg=T.MUTED, bg=T.CARD, anchor="w",
                            justify="left", wraplength=180)
        self.sub.pack(fill="x", padx=12, pady=(0, 10))

    def set(self, value, sub="", color=T.TEXT, sub_color=T.MUTED):
        self.value.configure(text=value, fg=color)
        self.sub.configure(text=sub, fg=sub_color)


class Gauge(tk.Canvas):
    """Semicircular 0–100 gauge."""

    def __init__(self, parent, size=190):
        super().__init__(parent, width=size, height=size * 0.62, bg=T.CARD, highlightthickness=0)
        self.size = size

    def set(self, value, label="Health"):
        self.delete("all")
        s, pad = self.size, 14
        box = (pad, pad, s - pad, s - pad)
        self.create_arc(*box, start=0, extent=180, style="arc", width=14, outline=T.GRID)
        color = T.health_color(value)
        self.create_arc(*box, start=180, extent=-180 * max(0, min(value, 100)) / 100, style="arc",
                        width=14, outline=color)
        self.create_text(s / 2, s / 2 - 14, text=f"{value:.0f}", font=(T.FAMILY, 34, "bold"), fill=color)
        self.create_text(s / 2, s / 2 + 14, text=label, font=T.F_SMALL, fill=T.MUTED)


class Table(tk.Frame):
    """ttk.Treeview + scrollbar. columns: [(key, heading, width, anchor), ...]."""

    def __init__(self, parent, columns, height=8, on_select=None):
        super().__init__(parent, bg=T.CARD)
        self.keys = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=self.keys, show="headings", height=height, selectmode="browse")
        for key, heading, width, anchor in columns:
            self.tree.heading(key, text=heading, anchor=anchor)
            self.tree.column(key, width=width, anchor=anchor, stretch=key == self.keys[0])
        vbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")
        for name, color in {"High": T.BAD, "Medium": T.WARN, "Low": T.INFO, "Info": T.GOOD,
                            "bad": T.BAD, "warn": T.WARN, "good": T.GOOD, "muted": T.MUTED}.items():
            self.tree.tag_configure(name, foreground=color)
        self.tree.tag_configure("total", background=T.CARD_HI, font=(T.FAMILY, 12, "bold"))
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda e: on_select(self.selected()))

    def load(self, rows, tags=None, iids=None):
        """rows: list of value tuples (PDF: table.insert('', 'end', values=row))."""
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(rows):
            self.tree.insert("", "end", iid=str(iids[i]) if iids else None, values=row,
                             tags=(tags[i],) if tags and tags[i] else ())

    def selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def select(self, iid):
        if self.tree.exists(str(iid)):
            self.tree.selection_set(str(iid))
            self.tree.see(str(iid))


class Donut(tk.Canvas):
    """Ring chart: segments = [(label, value, color)], with a centre label and legend."""

    def __init__(self, parent, size=190, legend=True):
        width = size + (170 if legend else 0)
        super().__init__(parent, width=width, height=size, bg=T.CARD, highlightthickness=0)
        self.size, self.legend = size, legend

    def set(self, segments, center="", caption=""):
        self.delete("all")
        s, pad, ring = self.size, 10, max(14, self.size // 7)
        total = sum(v for _, v, _ in segments)
        start = 90.0
        if total <= 0:
            self.create_oval(pad, pad, s - pad, s - pad, outline=T.GRID, width=ring)
        for label, value, color in segments:
            if value <= 0:
                continue
            extent = -360.0 * value / total
            if abs(extent) >= 359.99:
                self.create_oval(pad + ring / 2, pad + ring / 2, s - pad - ring / 2, s - pad - ring / 2,
                                 outline=color, width=ring)
            else:
                self.create_arc(pad + ring / 2, pad + ring / 2, s - pad - ring / 2, s - pad - ring / 2,
                                start=start, extent=extent, style="arc", outline=color, width=ring)
            start += extent
        self.create_text(s / 2, s / 2 - 8, text=center, font=(T.FAMILY, max(14, s // 8), "bold"), fill=T.TEXT)
        self.create_text(s / 2, s / 2 + s // 9, text=caption, font=T.F_SMALL, fill=T.MUTED)
        if self.legend:
            y = s / 2 - len(segments) * 11
            for label, value, color in segments:
                share = f"{value / total:.0%}" if total else "–"
                self.create_rectangle(s + 10, y - 5, s + 20, y + 5, fill=color, outline="")
                self.create_text(s + 28, y, text=f"{label}  {value} · {share}", anchor="w", fill=T.TEXT,
                                 font=T.F_SMALL)
                y += 22


class Sparkline(tk.Canvas):
    def __init__(self, parent, width=150, height=60, color=T.ACCENT):
        super().__init__(parent, width=width, height=height, bg=T.CARD, highlightthickness=0)
        self.w, self.h, self.color = width, height, color

    def set(self, values):
        self.delete("all")
        vals = [float(v) for v in values if v == v]
        if len(vals) < 2:
            self.create_text(self.w / 2, self.h / 2, text="needs 2+ runs", fill=T.MUTED, font=T.F_SMALL)
            return
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1
        pts = []
        for i, v in enumerate(vals):
            pts += [4 + (self.w - 8) * i / (len(vals) - 1), self.h - 6 - (self.h - 12) * (v - lo) / span]
        self.create_polygon(pts[0], self.h, *pts, pts[-2], self.h, fill=T.BAND, outline="")
        self.create_line(*pts, fill=self.color, width=2)
        self.create_oval(pts[-2] - 3, pts[-1] - 3, pts[-2] + 3, pts[-1] + 3, fill=self.color, outline="")


class SummaryCard(tk.Frame):
    """Headline card: title, big number, a few labelled lines, optional visual on the right."""

    def __init__(self, parent, title):
        super().__init__(parent, bg=T.CARD, highlightbackground=T.BORDER, highlightthickness=1)
        left = tk.Frame(self, bg=T.CARD)
        left.pack(side="left", fill="both", expand=True, padx=(16, 4), pady=12)
        tk.Label(left, text=title, font=T.F_H3, fg=T.TEXT, bg=T.CARD, anchor="w").pack(fill="x")
        self.caption = tk.Label(left, text="", font=T.F_SMALL, fg=T.MUTED, bg=T.CARD, anchor="w")
        self.caption.pack(fill="x", pady=(6, 0))
        self.big = tk.Label(left, text="–", font=(T.FAMILY, 26, "bold"), fg=T.TEXT, bg=T.CARD, anchor="w")
        self.big.pack(fill="x")
        self.lines = tk.Frame(left, bg=T.CARD)
        self.lines.pack(fill="x")
        self.visual = tk.Frame(self, bg=T.CARD)
        self.visual.pack(side="right", padx=(0, 12), pady=12)

    def set(self, caption, big, lines, big_color=T.TEXT):
        self.caption.configure(text=caption)
        self.big.configure(text=big, fg=big_color)
        for w in self.lines.winfo_children():
            w.destroy()
        for label, value, color in lines:
            row = tk.Frame(self.lines, bg=T.CARD)
            row.pack(fill="x")
            tk.Label(row, text=f"{label}: ", font=T.F_BODY, fg=T.TEXT, bg=T.CARD).pack(side="left")
            tk.Label(row, text=value, font=(T.FAMILY, 12, "bold"), fg=color, bg=T.CARD).pack(side="left")


class StackedHBars(tk.Canvas):
    """Rows of stacked horizontal bars: rows = [(label, [(value, color), ...], right_text)]."""

    def __init__(self, parent, row_height=28, label_width=170):
        super().__init__(parent, height=80, bg=T.CARD, highlightthickness=0)
        self.row_h, self.label_w, self.rows = row_height, label_width, []
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, rows):
        self.rows = rows
        self.configure(height=max(40, len(rows) * self.row_h + 4))
        self._draw()

    def _draw(self):
        self.delete("all")
        w = max(self.winfo_width(), 300)
        x0, x1 = self.label_w, w - 90
        for i, (label, parts, text) in enumerate(self.rows):
            y = i * self.row_h + self.row_h / 2
            self.create_text(0, y, text=label, anchor="w", fill=T.TEXT, font=T.F_SMALL)
            total = sum(v for v, _ in parts) or 1
            x = x0
            for value, color in parts:
                dx = (x1 - x0) * value / total
                if dx > 0:
                    self.create_rectangle(x, y - 8, x + dx, y + 8, fill=color, outline=T.CARD)
                x += dx
            self.create_text(w - 4, y, text=text, anchor="e", fill=T.MUTED, font=T.F_SMALL)


class HBars(tk.Canvas):
    """Horizontal contribution bars: items = [(label, value, max_value, color, text)]."""

    def __init__(self, parent, height=170):
        super().__init__(parent, height=height, bg=T.CARD, highlightthickness=0)
        self.items = []
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, items):
        self.items = items
        self._draw()

    def _draw(self):
        self.delete("all")
        if not self.items:
            return
        w = max(self.winfo_width(), 200)
        h = max(self.winfo_height(), 50)
        row_h = h / len(self.items)
        label_w = 130
        for i, (label, value, vmax, color, text) in enumerate(self.items):
            y = i * row_h + row_h / 2
            self.create_text(0, y, text=label, anchor="w", fill=T.MUTED, font=T.F_SMALL)
            x0, x1 = label_w, w - 70
            self.create_rectangle(x0, y - 7, x1, y + 7, fill=T.GRID, outline="")
            frac = 0 if vmax <= 0 or math.isnan(value) else max(0, min(value / vmax, 1))
            self.create_rectangle(x0, y - 7, x0 + (x1 - x0) * frac, y + 7, fill=color, outline="")
            self.create_text(w - 4, y, text=text, anchor="e", fill=T.TEXT, font=T.F_SMALL)
