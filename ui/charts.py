"""Time-series chart drawn on a tk.Canvas (no plotting dependency).

chart.plot(x, layers) where x is a sequence of timestamps and each layer is a
dict with a "type":
  line    {values, color, width=2, dash=None, label}
  band    {upper, lower, color}                      (drawn first, behind lines)
  bar     {values, pos=color, neg=color, label}
  candles {df(open, high, low, close)}
  markers {points=[(index, value, color, symbol)], label}
  hline   {y, color, dash=(3, 3), label}
Hovering shows the bar's timestamp and the value of every labelled layer.
"""
import math
import tkinter as tk

import numpy as np
import pandas as pd

from ui import theme as T

PAD_L, PAD_R, PAD_T, PAD_B = 58, 16, 34, 26


def _vals(v, n):
    if v is None:
        return [float("nan")] * n
    arr = np.asarray(v, dtype=float)
    return list(arr) if len(arr) == n else [float("nan")] * n


def _nice_ticks(lo, hi, count=4):
    if hi - lo <= 0:
        hi = lo + 1
    raw = (hi - lo) / count
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=raw)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t <= hi + step * 0.01:
        if t >= lo - step * 0.01:
            ticks.append(t)
        t += step
    return ticks


class Chart(tk.Canvas):
    def __init__(self, parent, height=230, title="", y_fmt=None, y_range=None, x_fmt="%d %b"):
        super().__init__(parent, height=height, bg=T.CARD, highlightthickness=0)
        self.title = title
        self.y_fmt = y_fmt or (lambda v: f"{v:,.0f}")
        self.y_range = y_range
        self.x_fmt = x_fmt
        self.x, self.layers = [], []
        self.empty_text = "No data"
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Motion>", self._hover)
        self.bind("<Leave>", lambda e: self.delete("hover"))

    def plot(self, x, layers, title=None, y_fmt=None, y_range="keep", x_fmt=None):
        self.x = list(pd.to_datetime(pd.Index(x))) if len(x) else []
        self.layers = layers
        if title is not None:
            self.title = title
        if y_fmt is not None:
            self.y_fmt = y_fmt
        if y_range != "keep":
            self.y_range = y_range
        if x_fmt is not None:
            self.x_fmt = x_fmt
        self._draw()

    # --------------------------------------------------------------- geometry
    def _extent(self):
        n = len(self.x)
        values = []
        for layer in self.layers:
            t = layer["type"]
            if t in ("line", "bar"):
                values += _vals(layer.get("values"), n)
            elif t == "band":
                values += _vals(layer.get("upper"), n) + _vals(layer.get("lower"), n)
            elif t == "candles":
                df = layer["df"]
                values += list(df["high"].astype(float)) + list(df["low"].astype(float))
            elif t == "markers":
                values += [p[1] for p in layer.get("points", [])]
            elif t == "hline":
                values.append(layer["y"])
            elif t == "stack":
                tops = np.zeros(n)
                for s in layer["series"]:
                    tops += np.nan_to_num(np.asarray(_vals(s["values"], n)))
                values += list(tops) + [0.0]
        values = [v for v in values if v is not None and not math.isnan(v)]
        if not values:
            return None
        lo, hi = min(values), max(values)
        if any(l["type"] == "bar" for l in self.layers):
            lo, hi = min(lo, 0), max(hi, 0)
        if self.y_range:
            lo = self.y_range[0] if self.y_range[0] is not None else lo
            hi = self.y_range[1] if self.y_range[1] is not None else hi
        pad = (hi - lo) * 0.08 or abs(hi) * 0.1 or 1
        return lo - (pad if not self.y_range or self.y_range[0] is None else 0), \
            hi + (pad if not self.y_range or self.y_range[1] is None else 0)

    def _geom(self):
        w, h = max(self.winfo_width(), 200), max(self.winfo_height(), 120)
        return PAD_L, PAD_T, w - PAD_R, h - PAD_B

    def _xp(self, i):
        x0, _, x1, _ = self._geom()
        n = len(self.x)
        return (x0 + x1) / 2 if n <= 1 else x0 + (x1 - x0) * i / (n - 1)

    def _yp(self, v):
        _, y0, _, y1 = self._geom()
        lo, hi = self._yr
        return y1 - (y1 - y0) * (v - lo) / (hi - lo)

    # ------------------------------------------------------------------ draw
    def _draw(self):
        self.delete("all")
        w = max(self.winfo_width(), 200)
        self.create_text(12, 14, text=self.title, anchor="w", fill=T.TEXT, font=T.F_H3)
        self._legend(w)
        ext = self._extent() if self.x else None
        x0, y0, x1, y1 = self._geom()
        if ext is None:
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=self.empty_text, fill=T.MUTED, font=T.F_BODY)
            return
        self._yr = ext
        for t in _nice_ticks(*ext):
            y = self._yp(t)
            self.create_line(x0, y, x1, y, fill=T.GRID)
            self.create_text(x0 - 6, y, text=self.y_fmt(t), anchor="e", fill=T.MUTED, font=T.F_SMALL)
        n = len(self.x)
        for k in range(min(6, n)):
            i = round(k * (n - 1) / max(min(6, n) - 1, 1))
            self.create_text(self._xp(i), y1 + 13, text=self.x[i].strftime(self.x_fmt), fill=T.MUTED,
                             font=T.F_SMALL)
        order = {"band": 0, "hline": 1, "bar": 2, "stack": 2, "candles": 3, "line": 4, "markers": 5}
        for layer in sorted(self.layers, key=lambda l: order[l["type"]]):
            getattr(self, "_draw_" + layer["type"])(layer)

    def _legend(self, w):
        x = w - PAD_R
        entries = []
        for layer in self.layers:
            entries += [{"label": s["label"], "color": s["color"], "type": "stack"}
                        for s in layer["series"]] if layer["type"] == "stack" else [layer]
        for layer in reversed(entries):
            label = layer.get("label")
            if not label or layer["type"] == "hline":
                continue
            color = layer.get("color") or layer.get("pos") or T.TEXT
            tid = self.create_text(x, 14, text=label, anchor="e", fill=T.MUTED, font=T.F_SMALL)
            bx0 = self.bbox(tid)[0]
            self.create_rectangle(bx0 - 14, 9, bx0 - 4, 19, fill=color, outline="")
            x = bx0 - 24

    def _segments(self, values):
        seg = []
        for i, v in enumerate(values):
            if v is None or math.isnan(v):
                if len(seg) >= 2:
                    yield seg
                seg = []
            else:
                seg += [self._xp(i), self._yp(v)]
        if len(seg) >= 2:
            yield seg

    def _draw_line(self, layer):
        vals = _vals(layer["values"], len(self.x))
        for seg in self._segments(vals):
            if len(seg) == 2:
                self.create_oval(seg[0] - 3, seg[1] - 3, seg[0] + 3, seg[1] + 3, fill=layer["color"], outline="")
            else:
                self.create_line(*seg, fill=layer["color"], width=layer.get("width", 2), dash=layer.get("dash"),
                                 smooth=False)

    def _draw_band(self, layer):
        n = len(self.x)
        up, lo = _vals(layer["upper"], n), _vals(layer["lower"], n)
        idx = [i for i in range(n) if not (math.isnan(up[i]) or math.isnan(lo[i]))]
        if len(idx) < 2:
            return
        pts = [c for i in idx for c in (self._xp(i), self._yp(up[i]))]
        pts += [c for i in reversed(idx) for c in (self._xp(i), self._yp(lo[i]))]
        self.create_polygon(*pts, fill=layer.get("color", T.BAND), outline="")

    def _draw_bar(self, layer):
        n = len(self.x)
        vals = _vals(layer["values"], n)
        x0, _, x1, _ = self._geom()
        bw = max(1.0, (x1 - x0) / max(n, 1) * 0.7)
        zero = self._yp(0)
        for i, v in enumerate(vals):
            if math.isnan(v):
                continue
            color = layer.get("pos", T.GOOD) if v >= 0 else layer.get("neg", T.BAD)
            xc = self._xp(i)
            self.create_rectangle(xc - bw / 2, zero, xc + bw / 2, self._yp(v), fill=color, outline="")

    def _draw_stack(self, layer):
        n = len(self.x)
        x0, _, x1, _ = self._geom()
        bw = max(2.0, (x1 - x0) / max(n, 1) * 0.65)
        base = np.zeros(n)
        for s in layer["series"]:
            vals = np.nan_to_num(np.asarray(_vals(s["values"], n)))
            for i in range(n):
                if vals[i] <= 0:
                    continue
                xc = self._xp(i)
                self.create_rectangle(xc - bw / 2, self._yp(base[i]), xc + bw / 2, self._yp(base[i] + vals[i]),
                                      fill=s["color"], outline="")
            base += vals

    def _draw_candles(self, layer):
        df = layer["df"].reset_index(drop=True)
        n = len(self.x)
        x0, _, x1, _ = self._geom()
        bw = max(2.0, (x1 - x0) / max(n, 1) * 0.6)
        for i in range(min(n, len(df))):
            o, h, l, c = (float(df.loc[i, k]) for k in ("open", "high", "low", "close"))
            if any(math.isnan(v) for v in (o, h, l, c)):
                continue
            color = T.BAD if c > o else T.GOOD     # rising duration/latency is bad
            xc = self._xp(i)
            self.create_line(xc, self._yp(h), xc, self._yp(l), fill=color)
            top, bot = self._yp(max(o, c)), self._yp(min(o, c))
            self.create_rectangle(xc - bw / 2, top, xc + bw / 2, max(bot, top + 1), fill=color, outline=color)

    def _draw_markers(self, layer):
        for i, v, color, symbol in layer.get("points", []):
            if v is None or math.isnan(v):
                continue
            x, y = self._xp(i), self._yp(v)
            if symbol == "down":
                self.create_polygon(x - 6, y - 12, x + 6, y - 12, x, y - 3, fill=color, outline="")
            elif symbol == "up":
                self.create_polygon(x - 6, y + 12, x + 6, y + 12, x, y + 3, fill=color, outline="")
            else:
                self.create_oval(x - 4, y - 4, x + 4, y + 4, outline=color, width=2)

    def _draw_hline(self, layer):
        x0, _, x1, _ = self._geom()
        y = self._yp(layer["y"])
        self.create_line(x0, y, x1, y, fill=layer.get("color", T.MUTED), dash=layer.get("dash", (3, 3)))
        if layer.get("label"):
            self.create_text(x1 - 4, y - 8, text=layer["label"], anchor="e", fill=layer.get("color", T.MUTED),
                             font=T.F_SMALL)

    # ----------------------------------------------------------------- hover
    def _hover(self, event):
        self.delete("hover")
        if not self.x or not hasattr(self, "_yr"):
            return
        x0, y0, x1, y1 = self._geom()
        if not (x0 <= event.x <= x1):
            return
        n = len(self.x)
        i = 0 if n == 1 else int(round((event.x - x0) / (x1 - x0) * (n - 1)))
        i = max(0, min(n - 1, i))
        xp = self._xp(i)
        self.create_line(xp, y0, xp, y1, fill=T.MUTED, dash=(2, 2), tags="hover")
        fmt = "%d %b %Y" if self.x_fmt == "%d %b" else "%d %b %H:%M"
        lines = [self.x[i].strftime(fmt)]
        for layer in self.layers:
            if layer.get("label") and layer["type"] in ("line", "bar"):
                v = _vals(layer["values"], n)[i]
                if not math.isnan(v):
                    lines.append(f"{layer['label']}: {self.y_fmt(v)}")
            elif layer["type"] == "stack":
                for s in layer["series"]:
                    v = _vals(s["values"], n)[i]
                    if not math.isnan(v):
                        lines.append(f"{s['label']}: {self.y_fmt(v)}")
            elif layer["type"] == "candles" and i < len(layer["df"]):
                row = layer["df"].iloc[i]
                lines.append("O {} H {} L {} C {}".format(*(self.y_fmt(row[k]) for k in ("open", "high", "low", "close"))))
        text = "\n".join(lines)
        tx = xp + 10 if xp < (x0 + x1) / 2 else xp - 10
        tid = self.create_text(tx, y0 + 6, text=text, anchor="nw" if tx > xp else "ne", fill=T.TEXT,
                               font=T.F_SMALL, tags="hover")
        bx = self.bbox(tid)
        rid = self.create_rectangle(bx[0] - 6, bx[1] - 4, bx[2] + 6, bx[3] + 4, fill=T.PANEL, outline=T.BORDER,
                                    tags="hover")
        self.tag_lower(rid, tid)
