"""Dashboard pages. Each page builds its widgets once and redraws in update(a)."""
import tkinter as tk
from tkinter import ttk

import numpy as np
import pandas as pd

import config as C
from engine import indicators as ind
from engine.analytics import SIGNALS, MIN_BARS_FOR_TREND
from ui import theme as T
from ui.charts import Chart
from engine.suite import SuiteAnalytics
from ui.widgets import (Card, Donut, FlatButton, Gauge, HBars, KpiTile, ScrollFrame, Sparkline, StackedHBars,
                        SummaryCard, Table)

ENV_COLORS = [T.ACCENT, T.PURPLE, T.ORANGE, T.INFO, T.GOOD]


def pct_axis(v):
    return f"{round(v * 100, 2):g}%"


def x_fmt(a):
    return "%d %b" if a.mode == "day" else "%d %b %H:%M"


def signal_fmt(signal):
    if signal in ("Pass rate", "Failure rate"):
        return pct_axis
    if signal.startswith("Suite"):
        return lambda v: f"{v:,.1f}s"
    return lambda v: f"{v:,.0f}"


def grid_cols(frame, n, weight=1):
    for i in range(n):
        frame.grid_columnconfigure(i, weight=weight, uniform="col")


class Page(ScrollFrame):
    title = ""
    subtitle = ""

    def __init__(self, parent):
        super().__init__(parent)
        head = tk.Frame(self.inner, bg=T.BG)
        head.pack(fill="x", padx=24, pady=(20, 8))
        tk.Label(head, text=self.title, font=T.F_TITLE, fg=T.TEXT, bg=T.BG).pack(side="left")
        self.meta = tk.Label(head, text="", font=T.F_SMALL, fg=T.MUTED, bg=T.BG)
        self.meta.pack(side="right")
        if self.subtitle:
            tk.Label(self.inner, text=self.subtitle, font=T.F_BODY, fg=T.MUTED, bg=T.BG, anchor="w",
                     justify="left", wraplength=1100).pack(fill="x", padx=24, pady=(0, 10))
        self.body = tk.Frame(self.inner, bg=T.BG)
        self.body.pack(fill="both", expand=True, padx=24, pady=(0, 24))
        self.a = None
        self.build()

    def build(self):
        pass

    def update(self, a, meta=""):
        self.a = a
        self.meta.configure(text=meta)
        self.render()

    def render(self):
        pass


# --------------------------------------------------------------------------- Overview
class DashboardPage(Page):
    title = "Quality Overview"

    def build(self):
        top = tk.Frame(self.body, bg=T.BG)
        top.pack(fill="x")
        hc = Card(top, "QA health score")
        hc.pack(side="left", fill="y", padx=(0, 12))
        self.gauge = Gauge(hc.body)
        self.gauge.pack()
        self.health_parts = tk.Frame(hc.body, bg=T.CARD)
        self.health_parts.pack(fill="x", pady=(6, 0))

        grid = tk.Frame(top, bg=T.BG)
        grid.pack(side="left", fill="both", expand=True)
        names = ["Total test cases", "Passed", "Failed", "Pass rate", "Feature coverage", "API coverage",
                 "UI coverage", "Flaky test rate", "Failure momentum", "Test stability", "Regression risk",
                 "Last run"]
        self.tiles = {}
        for i, n in enumerate(names):
            t = KpiTile(grid, n)
            t.grid(row=i // 4, column=i % 4, sticky="nsew", padx=(0, 10), pady=(0, 10))
            self.tiles[n] = t
        grid_cols(grid, 4)

        row = tk.Frame(self.body, bg=T.BG)
        row.pack(fill="x", pady=(4, 12))
        grid_cols(row, 2)
        c1, c2 = Card(row), Card(row)
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        c2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.pass_chart = Chart(c1.body, title="Test execution trend — pass rate", y_fmt=pct_axis)
        self.pass_chart.pack(fill="both", expand=True)
        self.fpi_chart = Chart(c2.body, title="Failure pressure (RSI of failure rate)", y_range=(0, 100))
        self.fpi_chart.pack(fill="both", expand=True)

        row2 = tk.Frame(self.body, bg=T.BG)
        row2.pack(fill="x", pady=(0, 12))
        grid_cols(row2, 2)
        c3 = Card(row2)
        c3.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.lat_chart = Chart(c3.body, title="API / page latency — p95 (ms)")
        self.lat_chart.pack(fill="both", expand=True)
        c4 = Card(row2, "Highest regression risk")
        c4.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.risk_table = Table(c4.body, [("feature", "Feature", 170, "w"), ("risk", "Risk", 60, "e"),
                                          ("pass", "Pass", 70, "e"), ("mom", "Momentum", 90, "e"),
                                          ("trend", "Trend", 120, "w")], height=6)
        self.risk_table.pack(fill="both", expand=True)

        self.insights_card = Card(self.body, "Top insights")
        self.insights_card.pack(fill="x")

    def render(self):
        a, k = self.a, self.a.kpis
        self.gauge.set(k["health"])
        for w in self.health_parts.winfo_children():
            w.destroy()
        for name, (weight, value) in k["health_components"].items():
            r = tk.Frame(self.health_parts, bg=T.CARD)
            r.pack(fill="x")
            tk.Label(r, text=f"{name} ×{weight:.2f}", font=T.F_SMALL, fg=T.MUTED, bg=T.CARD).pack(side="left")
            tk.Label(r, text=T.pct(value, 0), font=T.F_SMALL, fg=T.TEXT, bg=T.CARD).pack(side="right")

        w7, w28 = a.w(7), a.w(28)
        t = self.tiles
        t["Total test cases"].set(f"{k['total_tests']}", f"{k['automated']} automated · {k['manual']} manual")
        t["Passed"].set(f"{k['passed']}", "latest result per test", T.GOOD)
        t["Failed"].set(f"{k['failed']}", "latest result per test", T.BAD if k["failed"] else T.TEXT)
        d = (k["pass_rate_7d"] - k["pass_rate_28d"]) * 100
        t["Pass rate"].set(T.pct(k["pass_rate_7d"]), f"last {w7} · {d:+.1f} pp vs {w28}",
                           T.GOOD if k["pass_rate_7d"] >= 0.95 else T.WARN if k["pass_rate_7d"] >= 0.85 else T.BAD,
                           T.BAD if d < -1 else T.GOOD if d > 1 else T.MUTED)
        t["Feature coverage"].set(T.pct(k["coverage"], 0), "requirements with automated tests",
                                  T.GOOD if k["coverage"] >= 0.8 else T.WARN)
        t["API coverage"].set(T.pct(k["api_coverage"], 0), "requirements covered by API tests")
        t["UI coverage"].set(T.pct(k["ui_coverage"], 0), "requirements covered by UI tests")
        t["Flaky test rate"].set(T.pct(k["flaky_rate"]), f"{k['flaky_count']} flaky test(s)",
                                 T.WARN if k["flaky_count"] else T.GOOD)
        mom = k["momentum_pp"]
        t["Failure momentum"].set(T.num(mom, 1, " pp") if not np.isnan(mom) else "–",
                                  f"failure-rate change, {w7} vs prior · pressure {T.num(k['fpi'])}",
                                  T.BAD if mom > 2 else T.GOOD if mom < -2 else T.TEXT)
        t["Test stability"].set(T.pct(k["stability"], 0), "non-flaky × inside expected band",
                                T.health_color(k["stability"] * 100))
        t["Regression risk"].set(T.num(k["avg_risk"]), f"avg · highest: {k['top_risk']} ({k['top_risk_score']:.0f})",
                                 T.health_color(100 - k["avg_risk"]))
        lr = k["last_run"]
        t["Last run"].set(f"{lr['passed']}/{lr['executed']}", f"{k['last_run_at']:%d %b %H:%M} · {k['runs']} runs total",
                          T.GOOD if lr["failed"] == 0 else T.BAD)

        dr = a.daily_rates()
        pr = dr["pass_rate"]
        b = a.bundle(pr)
        title_suffix = "" if a.n_bars >= MIN_BARS_FOR_TREND else f"  (warming up: {a.n_bars} bars)"
        self.pass_chart.plot(a.bars, [
            {"type": "band", "upper": b["bb"]["upper"].clip(upper=1), "lower": b["bb"]["lower"]},
            {"type": "line", "values": pr, "color": T.TEXT, "width": 1, "label": "Pass rate"},
            {"type": "line", "values": b["ema_short"], "color": T.ACCENT, "label": f"EMA {C.SHORT_MA}"},
            {"type": "line", "values": b["sma_long"], "color": T.ORANGE, "label": f"SMA {C.LONG_MA}"},
        ], title="Test execution trend — pass rate" + title_suffix, x_fmt=x_fmt(a))
        fpi = ind.rsi(dr["fail_rate"], C.RSI_PERIOD)
        self.fpi_chart.plot(a.bars, [
            {"type": "hline", "y": C.FPI_HIGH, "color": T.BAD, "label": "high pressure"},
            {"type": "hline", "y": C.FPI_LOW, "color": T.GOOD, "label": "recovering"},
            {"type": "line", "values": fpi, "color": T.PURPLE, "label": "Failure pressure"},
        ], x_fmt=x_fmt(a))
        lat = a.series("API latency p95 (ms)")
        lb = ind.bollinger(lat, C.BOLLINGER_N, C.BOLLINGER_K)
        self.lat_chart.plot(a.bars, [
            {"type": "band", "upper": lb["upper"], "lower": lb["lower"]},
            {"type": "line", "values": lat, "color": T.INFO, "label": "p95"},
            {"type": "line", "values": ind.ema(lat, C.SHORT_MA), "color": T.ORANGE, "label": f"EMA {C.SHORT_MA}"},
        ], x_fmt=x_fmt(a))

        ft = a.feature_table.head(8)
        self.risk_table.load(
            [(r.feature, f"{r.risk:.0f}", T.pct(r.pass_7d), T.num(r.momentum_pp * 100, 1, " pp"), r.trend)
             for r in ft.itertuples()],
            tags=["High" if r.risk >= 60 else "Medium" if r.risk >= 45 else "" for r in ft.itertuples()])

        body = self.insights_card.body
        for w in body.winfo_children():
            w.destroy()
        for ins in a.insights[:6]:
            insight_row(body, ins)


def insight_row(parent, ins, full=False):
    row = tk.Frame(parent, bg=T.CARD)
    row.pack(fill="x", pady=4)
    color = T.SEVERITY_COLORS[ins.severity]
    tk.Frame(row, bg=color, width=4).pack(side="left", fill="y", padx=(0, 10))
    box = tk.Frame(row, bg=T.CARD)
    box.pack(side="left", fill="x", expand=True)
    head = tk.Frame(box, bg=T.CARD)
    head.pack(fill="x")
    tk.Label(head, text=ins.severity.upper(), font=(T.FAMILY, 9, "bold"), fg=color, bg=T.CARD).pack(side="left")
    tk.Label(head, text=ins.title, font=T.F_H3, fg=T.TEXT, bg=T.CARD).pack(side="left", padx=8)
    tk.Label(head, text=ins.area, font=T.F_SMALL, fg=T.MUTED, bg=T.CARD).pack(side="right")
    tk.Label(box, text=ins.evidence, font=T.F_SMALL, fg=T.MUTED, bg=T.CARD, anchor="w", justify="left",
             wraplength=1000).pack(fill="x")
    if full:
        tk.Label(box, text="→ " + ins.recommendation, font=T.F_SMALL, fg=T.INFO, bg=T.CARD, anchor="w",
                 justify="left", wraplength=1000).pack(fill="x", pady=(2, 0))


# --------------------------------------------------------------------------- Signals
# QA wording per signal: (what "up" means, pressure title, high zone, low zone, change title)
SIGNAL_TERMS = {
    "Pass rate": ("quality improving", "Failure pressure index — how consistently failures have been rising",
                  "Failure spike zone", "Recovery zone", "Pass-rate change"),
    "Failure rate": ("failures accelerating", "Failure pressure index — how consistently failures have been rising",
                     "Failure spike zone", "Recovery zone", "Failure-rate change"),
    "Suite duration (s)": ("runs getting slower", "Slowdown pressure index — how consistently run time has been rising",
                           "Sustained slowdown", "Sustained speed-up", "Run-time change"),
    "API latency p95 (ms)": ("responses getting slower",
                             "Latency pressure index — how consistently response time has been rising",
                             "Sustained degradation", "Sustained improvement", "Latency change"),
}
EVENT_LABELS = {"Regression start": "Regression detected", "Recovery": "Recovered", "Anomaly": "Unusual result"}


class SignalsPage(Page):
    title = "Quality Trends"
    subtitle = ("For any signal, feature and environment: the short-term trend against its baseline, the normal "
                "range, quality momentum, the pressure index and the change over time. "
                "Markers: ▼ regression detected, ▲ recovered, ○ unusual result.")

    def build(self):
        bar = tk.Frame(self.body, bg=T.BG)
        bar.pack(fill="x", pady=(0, 10))
        self.f_feature = self._combo(bar, "Feature", 22)
        self.f_env = self._combo(bar, "Environment", 16)
        self.f_signal = self._combo(bar, "Signal", 22, SIGNALS)
        self.f_signal.set(SIGNALS[0])

        self.readout = Card(self.body, "Current reading")
        self.readout.pack(fill="x", pady=(0, 10))
        self.read_lbl = tk.Label(self.readout.body, text="", font=T.F_BODY, fg=T.TEXT, bg=T.CARD,
                                 justify="left", anchor="w", wraplength=1100)
        self.read_lbl.pack(fill="x")

        self.charts = {}
        for key, h in (("main", 260), ("macd", 170), ("rsi", 170), ("mom", 170)):
            c = Card(self.body)
            c.pack(fill="x", pady=(0, 10))
            self.charts[key] = Chart(c.body, height=h)
            self.charts[key].pack(fill="both", expand=True)
        ec = Card(self.body, "Detected quality events")
        ec.pack(fill="x")
        self.events = Table(ec.body, [("date", "When", 150, "w"), ("kind", "Event", 160, "w"),
                                      ("detail", "Detail", 600, "w")], height=6)
        self.events.pack(fill="x")

    def _combo(self, parent, label, width, values=()):
        tk.Label(parent, text=label, font=T.F_SMALL, fg=T.MUTED, bg=T.BG).pack(side="left", padx=(0, 6))
        cb = ttk.Combobox(parent, values=list(values), state="readonly", width=width)
        cb.pack(side="left", padx=(0, 18))
        cb.bind("<<ComboboxSelected>>", lambda e: self.render())
        return cb

    def render(self):
        a = self.a
        feats = ["All features"] + list(a.features["name"])
        envs = ["All environments"] + list(a.envs["name"])
        self.f_feature.configure(values=feats)
        self.f_env.configure(values=envs)
        if self.f_feature.get() not in feats:
            self.f_feature.set(feats[0])
        if self.f_env.get() not in envs:
            self.f_env.set(envs[0])
        fid = None if self.f_feature.current() <= 0 else int(a.features.index[self.f_feature.current() - 1])
        eid = None if self.f_env.current() <= 0 else int(a.envs.index[self.f_env.current() - 1])
        signal = self.f_signal.get()
        s = a.series(signal, feature_id=fid, env_id=eid)
        b = a.bundle(s)
        fmt = signal_fmt(signal)
        xf = x_fmt(a)
        bars = list(a.bars)

        points, events = [], []
        if signal in ("Pass rate", "Failure rate"):
            dr = a.daily_rates(fid, eid)
            events = a.reversal_events(dr["pass_rate"], dr["executed"])
            for e in events:
                i = bars.index(e.date)
                sym, col = {"Regression start": ("down", T.BAD), "Recovery": ("up", T.GOOD),
                            "Anomaly": ("ring", T.WARN)}[e.kind]
                points.append((i, s.iloc[i], col, sym))
        else:
            for i, out in enumerate(b["bb"]["outside"]):
                if out and s.iloc[i] > b["bb"]["upper"].iloc[i]:
                    points.append((i, s.iloc[i], T.WARN, "ring"))
        unit = "days" if a.mode == "day" else "runs"
        up_means, p_title, p_high, p_low, c_title = SIGNAL_TERMS[signal]
        higher_is_better = signal == "Pass rate"
        good_up, bad_up = (T.GOOD, T.BAD) if higher_is_better else (T.BAD, T.GOOD)

        upper = b["bb"]["upper"].clip(upper=1) if signal in ("Pass rate", "Failure rate") else b["bb"]["upper"]
        lower = b["bb"]["lower"].clip(lower=0)
        self.charts["main"].plot(a.bars, [
            {"type": "band", "upper": upper, "lower": lower, "color": T.BAND, "label": "Normal range"},
            {"type": "line", "values": s, "color": T.TEXT, "width": 1, "label": f"{signal} per {unit[:-1]}"},
            {"type": "line", "values": b["ema_short"], "color": T.ACCENT,
             "label": f"Short-term trend ({C.SHORT_MA} {unit})"},
            {"type": "line", "values": b["sma_long"], "color": T.ORANGE, "label": f"Baseline ({C.LONG_MA} {unit})"},
            {"type": "markers", "points": points},
        ], title=f"{signal} — short-term trend vs baseline", y_fmt=fmt, x_fmt=xf)
        m = b["macd"]
        self.charts["macd"].plot(a.bars, [
            {"type": "bar", "values": m["hist"], "pos": good_up, "neg": bad_up, "label": "Change in momentum"},
            {"type": "line", "values": m["macd"], "color": T.ACCENT, "label": "Momentum"},
            {"type": "line", "values": m["signal"], "color": T.ORANGE, "label": "Momentum average"},
        ], title=f"Quality momentum — above zero: {up_means}",
            y_fmt=lambda v: f"{v:.3f}" if abs(v) < 1 else f"{v:,.0f}", x_fmt=xf)
        rsi_src = a.daily_rates(fid, eid)["fail_rate"] if signal in ("Pass rate", "Failure rate") else s
        rsi = ind.rsi(rsi_src, C.RSI_PERIOD)
        self.charts["rsi"].plot(a.bars, [
            {"type": "hline", "y": C.FPI_HIGH, "color": T.BAD, "label": f"{p_high} ({C.FPI_HIGH}+)"},
            {"type": "hline", "y": C.FPI_LOW, "color": T.GOOD, "label": f"{p_low} (≤{C.FPI_LOW})"},
            {"type": "line", "values": rsi, "color": T.PURPLE, "label": p_title.split(" —")[0]},
        ], title=p_title, y_range=(0, 100), y_fmt=lambda v: f"{v:.0f}", x_fmt=xf)
        if signal in ("Pass rate", "Failure rate"):
            mom = ind.momentum_pp(ind.sma(s, C.MOMENTUM_DAYS), C.MOMENTUM_DAYS) * 100
            mtitle = f"{c_title} vs {C.MOMENTUM_DAYS} {unit} earlier (percentage points)"
            mfmt = lambda v: f"{v:+.1f}"   # noqa: E731
        else:
            mom = ind.roc_pct(ind.sma(s, C.MOMENTUM_DAYS), C.MOMENTUM_DAYS)
            mtitle, mfmt = f"{c_title} vs {C.MOMENTUM_DAYS} {unit} earlier (%)", lambda v: f"{v:+.0f}%"
        self.charts["mom"].plot(a.bars, [{"type": "bar", "values": mom, "pos": good_up, "neg": bad_up,
                                          "label": "Change"}], title=mtitle, y_fmt=mfmt, x_fmt=xf)

        last = lambda x: x.dropna().iloc[-1] if x.notna().any() else np.nan   # noqa: E731
        cur, es, sl, h, r = last(s), last(b["ema_short"]), last(b["sma_long"]), last(m["hist"]), last(rsi)
        is_rate = signal in ("Pass rate", "Failure rate")
        if is_rate:     # rates: half-width in percentage points; times: relative to the mid line
            spread = (last(b["bb"]["upper"]) - last(b["bb"]["lower"])) / 2
            width = "–" if np.isnan(spread) else f"±{spread * 100:.1f} pp"
            fmt = lambda v: T.pct(v)   # noqa: E731
        else:
            bw = last(b["bb"]["bandwidth"])
            width = "–" if np.isnan(bw) else f"±{bw / 2:.0%}"
        trend = ("improving" if (es > sl) == higher_is_better else "deteriorating") if not np.isnan(sl) else "n/a"
        momentum = ("n/a" if np.isnan(h) else
                    "gaining (getting better)" if (h > 0) == higher_is_better else "slipping (getting worse)")
        zone = ("n/a" if np.isnan(r) else p_high.lower() if r >= C.FPI_HIGH else
                p_low.lower() if r <= C.FPI_LOW else "normal")
        self.read_lbl.configure(text=(
            f"{signal} now: {fmt(cur)}    ·    short-term trend {fmt(es)} vs baseline {fmt(sl)} → {trend}    ·    "
            f"momentum {momentum}    ·    pressure index {r:.0f} ({zone})    ·    "
            f"normal range {width}"
            if not np.isnan(cur) else "No data for this selection."))
        self.events.load([(e.date.strftime("%d %b %Y %H:%M" if a.mode == "run" else "%d %b %Y"),
                           EVENT_LABELS[e.kind], e.detail) for e in reversed(events)],
                         tags=[{"Regression start": "bad", "Recovery": "good", "Anomaly": "warn"}[e.kind]
                               for e in reversed(events)])


# --------------------------------------------------------------------------- Risk
class RiskPage(Page):
    title = "Risk & Prioritisation"
    subtitle = ("Regression risk per feature = weighted, capped components (failure rate, momentum, volatility, "
                "criticality, coverage gap, recent change volume). This is a transparent prioritisation heuristic "
                "— the weights are judgement calls, not a validated defect prediction.")

    def build(self):
        tc = Card(self.body, "Features ranked by regression risk", "select a row for the breakdown")
        tc.pack(fill="x", pady=(0, 10))
        self.table = Table(tc.body, [
            ("feature", "Feature", 170, "w"), ("risk", "Risk", 55, "e"), ("crit", "Crit.", 50, "e"),
            ("fail", "Fail rate", 80, "e"), ("mom", "Momentum", 85, "e"), ("vol", "Dur. ATR%", 85, "e"),
            ("cov", "Coverage", 80, "e"), ("lev", "Leverage", 75, "e"), ("chg", "Lines 14d", 85, "e"),
            ("flaky", "Flaky", 55, "e"), ("gate", "Gate", 70, "center")], height=10, on_select=self.show)
        self.table.pack(fill="x")

        row = tk.Frame(self.body, bg=T.BG)
        row.pack(fill="x", pady=(0, 10))
        grid_cols(row, 2)
        dc = Card(row, "Risk breakdown")
        dc.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.d_title = tk.Label(dc.body, text="", font=T.F_H2, fg=T.TEXT, bg=T.CARD, anchor="w")
        self.d_title.pack(fill="x")
        self.bars = HBars(dc.body, height=170)
        self.bars.pack(fill="x", pady=8)
        ec = Card(row, "Evidence")
        ec.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.evidence = tk.Label(ec.body, text="", font=T.F_SMALL, fg=T.TEXT, bg=T.CARD, justify="left",
                                 anchor="nw", wraplength=520)
        self.evidence.pack(fill="both", expand=True)

        ac = Card(self.body, "Test budget allocation", "split a run-time budget in proportion to risk")
        ac.pack(fill="x")
        ctl = tk.Frame(ac.body, bg=T.CARD)
        ctl.pack(fill="x", pady=(0, 8))
        tk.Label(ctl, text="Budget (minutes)", font=T.F_BODY, fg=T.MUTED, bg=T.CARD).pack(side="left")
        self.budget = ttk.Entry(ctl, width=8)
        self.budget.insert(0, "120")
        self.budget.pack(side="left", padx=8)
        FlatButton(ctl, "Allocate", self.allocate, pady=4).pack(side="left")
        self.alloc_bars = HBars(ac.body, height=260)
        self.alloc_bars.pack(fill="x")

    def render(self):
        ft = self.a.feature_table
        self.table.load([
            (r.feature, f"{r.risk:.0f}", r.criticality, T.pct(r.fail_7d), T.num(r.momentum_pp * 100, 1, " pp"),
             T.num(r.atr_pct, 0, "%"), T.pct(r.coverage, 0), f"{r.leverage:.1f}x", f"{r.lines_14d:,}",
             r.flaky_tests, "FAIL" if r.gate else "pass") for r in ft.itertuples()],
            tags=["High" if r.gate else "" for r in ft.itertuples()], iids=list(ft.feature_id))
        self.table.select(ft.feature_id.iloc[0])
        self.show(str(ft.feature_id.iloc[0]))
        self.allocate()

    def show(self, iid):
        if iid is None or self.a is None:
            return
        ft = self.a.feature_table
        f = ft[ft.feature_id == int(iid)].iloc[0]
        self.d_title.configure(text=f"{f.feature} — risk {f.risk:.0f}/100")
        labels = {"failure_rate": "Failure rate", "momentum": "Momentum", "volatility": "Volatility",
                  "criticality": "Criticality", "coverage_gap": "Coverage gap", "change_volume": "Change volume"}
        self.bars.set([(labels[k], f[f"c_{k}"], 100 * w, T.BAD if f[f"c_{k}"] >= 0.6 * 100 * w else T.ACCENT,
                        f"{f[f'c_{k}']:.1f} / {100 * w:.0f}") for k, w in C.RISK_WEIGHTS.items()])
        a = self.a
        lines = [f"Quality gate: " + ("FAIL — " + "; ".join(f.gate) if f.gate else "pass")]
        lines.append(f"Pass rate: last 5 runs {T.pct(f.pass_last5)} · {a.w(7)} {T.pct(f.pass_7d)} · "
                     f"{a.w(28)} {T.pct(f.pass_28d)} · trend {f.trend}")
        lines.append(f"Failure pressure {T.num(f.fpi)} · MACD histogram {f.macd_hist:+.4f} · "
                     f"band width {T.pct(f.bandwidth)}")
        lines.append(f"Coverage {T.pct(f.coverage, 0)} (UI {T.pct(f.ui_coverage, 0)}, API {T.pct(f.api_coverage, 0)}), "
                     f"{f.uncovered} requirement(s) not automated · leverage {f.leverage:.1f}x")
        sr = []
        if f.support is not None and not pd.isna(f.support):
            sr.append(f"support (typical failure floor) {T.pct(f.support)}")
        if f.resistance is not None and not pd.isna(f.resistance):
            sr.append(f"resistance (typical regression ceiling) {T.pct(f.resistance)}")
        if f.recovery is not None and not pd.isna(f.recovery):
            sr.append(f"recovered {T.pct(f.recovery, 0)} of last regression")
        if sr:
            lines.append("Failure-rate levels: " + " · ".join(sr))
        newly = a.newly_failing(int(iid))
        if len(newly):
            lines.append("Newly failing: " + ", ".join(newly.index[:5]))
        flaky = a.flaky[(a.flaky.feature_id == int(iid)) & a.flaky.flaky]
        if len(flaky):
            lines.append("Flaky: " + ", ".join(flaky.name[:5]))
        self.evidence.configure(text="\n\n".join(lines))

    def allocate(self):
        try:
            budget = float(self.budget.get())
        except ValueError:
            budget = 120.0
        if self.a is None or budget <= 0:
            return
        alloc = self.a.allocate(budget).sort_values("minutes", ascending=False)
        top = alloc.minutes.max()
        self.alloc_bars.set([(r.feature, r.minutes, top, T.ACCENT, f"{r.minutes:.1f} min · {r.share:.0%}")
                             for r in alloc.itertuples()])


# --------------------------------------------------------------------------- Timeframes
class TimeframesPage(Page):
    title = "Multi-Timeframe Analysis"
    subtitle = ("The same signal across short and long windows separates short-term blips from chronic problems. "
                "Candles show each bar's open / high / low / close of suite duration or latency; ATR measures how "
                "much it moves.")

    def build(self):
        tc = Card(self.body, "Pass rate by timeframe")
        tc.pack(fill="x", pady=(0, 10))
        self.table = Table(tc.body, [("feature", "Feature", 180, "w"), ("l5", "Last 5 runs", 100, "e"),
                                     ("p7", "", 90, "e"), ("p28", "", 90, "e"), ("p90", "", 90, "e"),
                                     ("trend", "Classification", 150, "w")], height=11)
        self.table.pack(fill="x")
        bar = tk.Frame(self.body, bg=T.BG)
        bar.pack(fill="x", pady=(4, 8))
        self.c_feature = self._combo(bar, "Feature", 22)
        self.c_signal = self._combo(bar, "Signal", 22, ["Suite duration (s)", "API latency p95 (ms)"])
        self.c_signal.set("Suite duration (s)")
        self.c_tf = self._combo(bar, "Bar size", 8)
        c1, c2 = Card(self.body), Card(self.body)
        c1.pack(fill="x", pady=(0, 10))
        c2.pack(fill="x")
        self.candle_chart = Chart(c1.body, height=260)
        self.candle_chart.pack(fill="both", expand=True)
        self.atr_chart = Chart(c2.body, height=170)
        self.atr_chart.pack(fill="both", expand=True)

    def _combo(self, parent, label, width, values=()):
        tk.Label(parent, text=label, font=T.F_SMALL, fg=T.MUTED, bg=T.BG).pack(side="left", padx=(0, 6))
        cb = ttk.Combobox(parent, values=list(values), state="readonly", width=width)
        cb.pack(side="left", padx=(0, 18))
        cb.bind("<<ComboboxSelected>>", lambda e: self.render_candles())
        return cb

    def render(self):
        a = self.a
        for key, n in (("p7", 7), ("p28", 28), ("p90", 90)):
            self.table.tree.heading(key, text=a.w(n))
        ft = a.feature_table.sort_values("feature")
        k = a.kpis
        d = a.daily_rates()
        overall = ("All features", T.pct(a._last_runs_pass_rate(a.results)), T.pct(k["pass_rate_7d"]),
                   T.pct(k["pass_rate_28d"]), T.pct(1 - a._rate_window(d, 90)), "")
        rows = [overall] + [(r.feature, T.pct(r.pass_last5), T.pct(r.pass_7d), T.pct(r.pass_28d), T.pct(r.pass_90d),
                             r.trend) for r in ft.itertuples()]
        tag = {"Chronic": "bad", "Deteriorating": "bad", "Short-term dip": "warn", "Improving": "good",
               "Collecting data": "muted"}
        self.table.load(rows, tags=["total"] + [tag.get(r.trend, "") for r in ft.itertuples()])
        feats = ["All features"] + list(a.features["name"])
        self.c_feature.configure(values=feats)
        if self.c_feature.get() not in feats:
            self.c_feature.set(feats[0])
        tfs = ["D1", "W1", "MN1"] if a.mode == "day" else ["RUN", "D1"]
        self.c_tf.configure(values=tfs)
        if self.c_tf.get() not in tfs:
            self.c_tf.set(tfs[0])
        self.render_candles()

    def render_candles(self):
        a = self.a
        if a is None:
            return
        fid = None if self.c_feature.current() <= 0 else int(a.features.index[self.c_feature.current() - 1])
        signal, tf = self.c_signal.get(), self.c_tf.get()
        c = a.candles(signal, feature_id=fid, timeframe=tf)
        fmt = signal_fmt(signal)
        xf = "%d %b %H:%M" if tf == "RUN" else "%d %b"
        self.candle_chart.plot(c.index, [{"type": "candles", "df": c},
                                         {"type": "line", "values": ind.ema(c["close"], C.SHORT_MA),
                                          "color": T.ACCENT, "label": f"EMA {C.SHORT_MA} of close"}],
                               title=f"{signal} — {tf} candles (red = slower than open)", y_fmt=fmt, x_fmt=xf)
        n = min(C.ATR_PERIOD, max(2, len(c) // 3))
        self.atr_chart.plot(c.index, [{"type": "line", "values": ind.atr_pct(c, n), "color": T.ORANGE,
                                       "label": f"ATR({n}) % of close"}],
                            title="Volatility — average true range as % of close", y_fmt=lambda v: f"{v:.0f}%",
                            x_fmt=xf)


# --------------------------------------------------------------------------- Environments & APIs
class EnvironmentsPage(Page):
    title = "Environments & APIs"
    subtitle = ("Environment stability and API / page latency. Latency spread = p95 − p50 (tail heaviness). "
                "The alert ladder places the current p95 on +10% steps above its baseline.")

    def build(self):
        ec = Card(self.body, "Environment stability")
        ec.pack(fill="x", pady=(0, 10))
        self.env_table = Table(ec.body, [
            ("env", "Environment", 120, "w"), ("p7", "Pass rate", 85, "e"), ("base", "Baseline", 85, "e"),
            ("chg", "Δ failures", 90, "e"), ("fpi", "Pressure", 75, "e"), ("atr", "ATR fail", 80, "e"),
            ("p95", "p95 ms", 80, "e"), ("dp95", "Δ p95", 75, "e"), ("spread", "Spread", 75, "e"),
            ("err", "Errors", 70, "e"), ("status", "Status", 90, "w")], height=4)
        self.env_table.pack(fill="x")
        c = Card(self.body)
        c.pack(fill="x", pady=(0, 10))
        self.env_chart = Chart(c.body, height=230, title="Pass rate by environment (EMA)", y_fmt=pct_axis)
        self.env_chart.pack(fill="both", expand=True)
        pc = Card(self.body, "Endpoints and pages", "select a row for its latency chart")
        pc.pack(fill="x", pady=(0, 10))
        self.ep_table = Table(pc.body, [
            ("ep", "Endpoint / page", 260, "w"), ("feature", "Feature", 130, "w"), ("p50", "p50", 65, "e"),
            ("p95", "p95", 65, "e"), ("base", "Baseline", 75, "e"), ("chg", "Change", 70, "e"),
            ("spread", "Spread", 70, "e"), ("ladder", "Ladder", 65, "center"), ("err", "Errors", 65, "e"),
            ("n", "Samples", 70, "e")], height=8, on_select=self.show_endpoint)
        self.ep_table.pack(fill="x")
        c2 = Card(self.body)
        c2.pack(fill="x")
        self.ep_chart = Chart(c2.body, height=240)
        self.ep_chart.pack(fill="both", expand=True)

    def render(self):
        a = self.a
        et = a.env_table
        self.env_table.load([
            (r.environment, T.pct(r.pass_7d), T.pct(r.pass_baseline), T.num(r.fail_change_pp, 1, " pp"),
             T.num(r.fpi), T.num(r.atr_fail_pp, 1, " pp"), T.num(r.p95_7d), T.num(r.p95_change_pct, 0, "%"),
             T.num(r.spread), T.pct(r.error_rate), r.status) for r in et.itertuples()],
            tags=["bad" if r.status == "Unstable" else "" for r in et.itertuples()])
        layers = []
        for i, (eid, env) in enumerate(a.envs.iterrows()):
            pr = a.daily_rates(env_id=eid)["pass_rate"]
            layers.append({"type": "line", "values": ind.ema(pr, 3), "color": ENV_COLORS[i % len(ENV_COLORS)],
                           "label": env["name"]})
        self.env_chart.plot(a.bars, layers, x_fmt=x_fmt(a))
        ept = a.endpoint_table
        self.ep_table.load([
            (r.endpoint, r.feature, T.num(r.p50_7d), T.num(r.p95_7d), T.num(r.baseline_p95),
             T.num(r.change_pct, 0, "%"), T.num(r.spread), f"{r.ladder_level}/5", T.pct(r.error_rate), r.samples)
            for r in ept.itertuples()],
            tags=["bad" if r.ladder_level >= 4 or r.error_rate >= 0.05 else "warn" if r.ladder_level >= 2 else ""
                  for r in ept.itertuples()], iids=list(ept.endpoint_id))
        if len(ept):
            self.ep_table.select(ept.endpoint_id.iloc[0])
            self.show_endpoint(str(ept.endpoint_id.iloc[0]))
        else:
            self.ep_chart.plot([], [], title="No latency samples yet")

    def show_endpoint(self, iid):
        if iid is None or self.a is None:
            return
        a = self.a
        row = a.endpoint_table[a.endpoint_table.endpoint_id == int(iid)].iloc[0]
        p95 = a.endpoint_p95(int(iid))
        bb = ind.bollinger(p95, C.BOLLINGER_N, C.BOLLINGER_K)
        layers = [{"type": "band", "upper": bb["upper"], "lower": bb["lower"].clip(lower=0)},
                  {"type": "line", "values": p95, "color": T.INFO, "label": "p95"},
                  {"type": "line", "values": ind.ema(p95, C.SHORT_MA), "color": T.ORANGE, "label": f"EMA {C.SHORT_MA}"}]
        if not np.isnan(row.baseline_p95):
            layers.append({"type": "hline", "y": row.baseline_p95, "color": T.GOOD, "label": "baseline"})
            for lvl, thr, _ in row.ladder[:3]:
                layers.append({"type": "hline", "y": thr, "color": T.WARN if lvl < 3 else T.BAD,
                               "label": f"+{lvl * 10}%"})
        self.ep_chart.plot(a.bars, layers, title=f"{row.endpoint} — p95 latency (ms)", x_fmt=x_fmt(a))


# --------------------------------------------------------------------------- Insights
class InsightsPage(Page):
    title = "Insights & Recommendations"
    subtitle = ("Every insight states the evidence behind it. They are rule-based readings of the indicators, "
                "meant to direct attention — not validated predictions.")

    def build(self):
        bar = tk.Frame(self.body, bg=T.BG)
        bar.pack(fill="x", pady=(0, 10))
        tk.Label(bar, text="Severity", font=T.F_SMALL, fg=T.MUTED, bg=T.BG).pack(side="left", padx=(0, 6))
        self.sev = ttk.Combobox(bar, values=["All", "High", "Medium", "Low", "Info"], state="readonly", width=10)
        self.sev.set("All")
        self.sev.pack(side="left")
        self.sev.bind("<<ComboboxSelected>>", lambda e: self.render())
        self.count = tk.Label(bar, text="", font=T.F_SMALL, fg=T.MUTED, bg=T.BG)
        self.count.pack(side="left", padx=12)
        self.card = Card(self.body)
        self.card.pack(fill="x")

    def render(self):
        for w in self.card.body.winfo_children():
            w.destroy()
        sel = self.sev.get()
        items = [i for i in self.a.insights if sel == "All" or i.severity == sel]
        self.count.configure(text=f"{len(items)} insight(s)")
        if not items:
            tk.Label(self.card.body, text="Nothing to report for this filter.", font=T.F_BODY, fg=T.MUTED,
                     bg=T.CARD).pack(anchor="w")
        for ins in items:
            insight_row(self.card.body, ins, full=True)
            tk.Frame(self.card.body, bg=T.BORDER, height=1).pack(fill="x", pady=4)


# --------------------------------------------------------------------------- Test analytics
REQ_COLORS = {"Passing": T.GOOD, "Failing": T.BAD, "Not executed": T.WARN, "Not automated": "#55607a"}


def fmt_secs(s):
    if s is None or s != s:
        return "–"
    s = float(s)
    return f"{s:.1f}s" if s < 60 else f"{int(s // 60)}m {int(s % 60):02d}s" if s < 3600 else f"{s / 3600:.1f}h"


class TestAnalyticsPage(Page):
    title = "Test Analytics"
    subtitle = ("Use-case and feature coverage, suite size, run duration, flaky tests, top failures and slowest "
                "tests. A requirement counts as verified only when an automated test for it actually executed in "
                "its latest run.")

    def build(self):
        bar = tk.Frame(self.body, bg=T.BG)
        bar.pack(fill="x", pady=(0, 10))
        tk.Label(bar, text="Analysis window", font=T.F_SMALL, fg=T.MUTED, bg=T.BG).pack(side="left", padx=(0, 6))
        self.win_cb = ttk.Combobox(bar, state="readonly", width=12)
        self.win_cb.pack(side="left")
        self.win_cb.bind("<<ComboboxSelected>>", lambda e: self._recompute())
        self.win_note = tk.Label(bar, text="", font=T.F_SMALL, fg=T.MUTED, bg=T.BG)
        self.win_note.pack(side="left", padx=12)

        cards = tk.Frame(self.body, bg=T.BG)
        cards.pack(fill="x")
        grid_cols(cards, 4)
        self.c_suite, self.c_req, self.c_uc, self.c_runs = (SummaryCard(cards, t) for t in (
            "Test suite", "Requirement coverage", "Use case coverage", "Execution runs"))
        for i, c in enumerate((self.c_suite, self.c_req, self.c_uc, self.c_runs)):
            c.grid(row=0, column=i, sticky="nsew", padx=(0, 10) if i < 3 else 0)
        self.suite_donut = Donut(self.c_suite.visual, size=110, legend=False)
        self.suite_donut.pack()
        self.req_gauge = Gauge(self.c_req.visual, size=130)
        self.req_gauge.pack()
        self.uc_donut = Donut(self.c_uc.visual, size=110, legend=False)
        self.uc_donut.pack()
        self.run_spark = Sparkline(self.c_runs.visual, width=130, height=70)
        self.run_spark.pack()

        row = tk.Frame(self.body, bg=T.BG)
        row.pack(fill="x", pady=12)
        row.grid_columnconfigure(0, weight=3)
        row.grid_columnconfigure(1, weight=2)
        c1 = Card(row)
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.status_chart = Chart(c1.body, height=260, y_fmt=lambda v: f"{v:,.0f}")
        self.status_chart.pack(fill="both", expand=True)
        c2 = Card(row, "Requirement coverage analysis")
        c2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.req_donut = Donut(c2.body, size=200)
        self.req_donut.pack(pady=6)

        uc = Card(self.body, "Use case coverage", "end-to-end journeys; gaps list the steps not verified")
        uc.pack(fill="x", pady=(0, 12))
        self.uc_table = Table(uc.body, [
            ("uc", "Use case", 210, "w"), ("prio", "Priority", 60, "e"), ("steps", "Steps", 50, "e"),
            ("ver", "Verified", 65, "e"), ("pass", "Passing", 65, "e"), ("fail", "Failing", 60, "e"),
            ("cov", "Coverage", 75, "e"), ("status", "Status", 120, "w"), ("gaps", "Gaps", 420, "w")], height=7)
        self.uc_table.pack(fill="x")

        fc = Card(self.body, "Feature coverage", "requirements per feature by verification status")
        fc.pack(fill="x", pady=(0, 12))
        legend = tk.Frame(fc.body, bg=T.CARD)
        legend.pack(fill="x", pady=(0, 6))
        for name, color in REQ_COLORS.items():
            tk.Label(legend, text="■", fg=color, bg=T.CARD, font=T.F_BODY).pack(side="left")
            tk.Label(legend, text=name, fg=T.MUTED, bg=T.CARD, font=T.F_SMALL).pack(side="left", padx=(2, 14))
        self.feat_bars = StackedHBars(fc.body)
        self.feat_bars.pack(fill="x")

        row = tk.Frame(self.body, bg=T.BG)
        row.pack(fill="x", pady=(0, 12))
        grid_cols(row, 2)
        c3, c4 = Card(row), Card(row)
        c3.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        c4.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.dur_chart = Chart(c3.body, height=230, y_fmt=fmt_secs)
        self.dur_chart.pack(fill="both", expand=True)
        self.size_chart = Chart(c4.body, height=230, y_fmt=lambda v: f"{v:,.0f}")
        self.size_chart.pack(fill="both", expand=True)

        row = tk.Frame(self.body, bg=T.BG)
        row.pack(fill="x", pady=(0, 12))
        grid_cols(row, 2)
        c5 = Card(row, "Run time per feature", "average seconds each feature adds to a run")
        c5.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.time_bars = HBars(c5.body, height=230)
        self.time_bars.pack(fill="x")
        c6 = Card(row, "Suite size by feature")
        c6.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.size_table = Table(c6.body, [("feature", "Feature", 170, "w"), ("auto", "Automated", 85, "e"),
                                          ("manual", "Manual", 70, "e"), ("total", "Total", 60, "e")], height=8)
        self.size_table.pack(fill="x")

        tf = Card(self.body, "Top failures", "most failures in the window; streak = consecutive failures up to now")
        tf.pack(fill="x", pady=(0, 12))
        self.fail_table = Table(tf.body, [
            ("test", "Test", 250, "w"), ("feature", "Feature", 130, "w"), ("fails", "Failures", 65, "e"),
            ("rate", "Rate", 60, "e"), ("streak", "Streak", 60, "e"), ("now", "Now", 70, "center"),
            ("last", "Last failed", 115, "w"), ("msg", "Last error", 420, "w")], height=8)
        self.fail_table.pack(fill="x")

        row = tk.Frame(self.body, bg=T.BG)
        row.pack(fill="x", pady=(0, 12))
        grid_cols(row, 2)
        c7 = Card(row, "Top failure reasons", "errors grouped by normalised message")
        c7.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.reason_table = Table(c7.body, [("reason", "Reason", 330, "w"), ("n", "Count", 55, "e"),
                                            ("tests", "Tests", 50, "e"), ("feat", "Features", 160, "w")], height=8)
        self.reason_table.pack(fill="x")
        c8 = Card(row, "Slowest tests", "change = recent median vs earlier in the window")
        c8.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.slow_table = Table(c8.body, [("test", "Test", 220, "w"), ("med", "Median", 70, "e"),
                                          ("p95", "p95", 70, "e"), ("share", "Run share", 75, "e"),
                                          ("chg", "Change", 65, "e")], height=8)
        self.slow_table.pack(fill="x")

        fl = Card(self.body, "Flaky tests", "flaky = flip rate ≥ 0.2 and failure share 5–70% over ≥ 10 executions")
        fl.pack(fill="x")
        self.flaky_table = Table(fl.body, [
            ("test", "Test", 280, "w"), ("feature", "Feature", 150, "w"), ("n", "Executions", 85, "e"),
            ("flip", "Flip rate", 75, "e"), ("share", "Fail share", 80, "e"), ("verdict", "Verdict", 220, "w")],
            height=6)
        self.flaky_table.pack(fill="x")

    # ---------------------------------------------------------------- render
    def render(self):
        a = self.a
        options = (["7 days", "28 days", "90 days"] if a.mode == "day" else ["5 runs", "10 runs", "30 runs", "All runs"])
        self.win_cb.configure(values=options)
        if self.win_cb.get() not in options:
            self.win_cb.set(options[1])
        self.s = getattr(a, "suite", None) or SuiteAnalytics(a, self._window())
        if self.s.window != min(self._window(), a.n_bars):
            self.s = SuiteAnalytics(a, self._window())
        self._draw()

    def _window(self):
        text = self.win_cb.get()
        return self.a.n_bars if text.startswith("All") else int(text.split()[0])

    def _recompute(self):
        self.s = SuiteAnalytics(self.a, self._window())
        self._draw()

    def _draw(self):
        a, s, m = self.a, self.s, self.s.summary
        self.win_note.configure(text=f"failures, durations and flakiness over the last {s.window_label}; "
                                     "coverage uses each test's latest result")
        self.c_suite.set("Total test cases", f"{m['suite_total']:,}", [
            ("Automated", f"{m['automated']:,}", T.GOOD), ("Manual", f"{m['manual']:,}", T.INFO),
            ("UI / API", f"{m['ui_tests']} / {m['api_tests']}", T.TEXT)])
        self.suite_donut.set([("Automated", m["automated"], T.GOOD), ("Manual", m["manual"], T.INFO)],
                             T.pct(m["automation_rate"], 0), "automated")
        verified = m["req_verified"] / m["req_total"] if m["req_total"] else 0
        self.c_req.set("Total requirements", f"{m['req_total']}", [
            ("Verified", f"{m['req_verified']}", T.GOOD), ("Not executed", f"{m['req_not_executed']}", T.WARN),
            ("Not automated", f"{m['req_not_automated']}", T.BAD)])
        self.req_gauge.set(verified * 100, "verified")
        if m["use_cases"]:
            self.c_uc.set("Use cases", f"{m['use_cases']}", [
                ("Fully covered", f"{m['uc_full']}", T.GOOD), ("Partially", f"{m['uc_partial']}", T.WARN),
                ("Not covered", f"{m['uc_none']}", T.BAD)])
            self.uc_donut.set([("Full", m["uc_full"], T.GOOD), ("Partial", m["uc_partial"], T.WARN),
                               ("None", m["uc_none"], T.BAD)],
                              T.pct(m["uc_full"] / m["use_cases"], 0), "fully covered")
        else:
            self.c_uc.set("Use cases", "–", [("Recorded with the next test run", "", T.MUTED)])
            self.uc_donut.set([], "–", "")
        trend = m["run_trend"]
        self.c_runs.set("Total runs", f"{m['runs']:,}", [
            ("Last run", fmt_secs(m["last_run_s"]), T.TEXT),
            ("Median", fmt_secs(m["median_run_s"]) + ("" if trend != trend else f"  ({trend:+.0%})"),
             T.BAD if trend == trend and trend > 0.1 else T.TEXT),
            ("Last: pass / fail / skip", f"{m['last_passed']} / {m['last_failed']} / {m['last_skipped']}",
             T.BAD if m["last_failed"] else T.GOOD),
            ("Flaky", f"{m['flaky']} detected · {m['flaky_suspected']} suspected", T.WARN if m["flaky"] else T.TEXT)])
        self.run_spark.set(list(s.runs.duration_s.tail(40)))

        es = s.execution_status()
        period = "week" if a.mode == "day" else "run"
        self.status_chart.plot(es.index, [{"type": "stack", "series": [
            {"values": es["PASSED"], "color": T.GOOD, "label": "Passed"},
            {"values": es["FAILED"], "color": T.BAD, "label": "Failed"},
            {"values": es["SKIPPED"], "color": T.WARN, "label": "Skipped"}]}],
            title=f"Test execution status (per {period})", x_fmt="%d %b" if a.mode == "day" else "%d %b %H:%M")
        req_counts = s.requirements.status.value_counts()
        self.req_donut.set([(k, int(req_counts.get(k, 0)), c) for k, c in REQ_COLORS.items()],
                           str(len(s.requirements)), "requirements")

        uc = s.use_cases
        self.uc_table.load([(r.use_case, r.priority, r.steps, r.verified, r.passing, r.failing, T.pct(r.coverage, 0),
                             r.status, r.gaps or "—") for r in uc.itertuples()],
                           tags=[{"Fully covered": "good", "Partially covered": "warn", "Not covered": "bad"}[r.status]
                                 for r in uc.itertuples()])
        fc = s.feature_coverage
        self.feat_bars.set([
            (f"{row['feature']} (crit. {row['criticality']})",
             [(row[state], color) for state, color in REQ_COLORS.items()],
             f"{T.pct(row['verified_pct'], 0)} verified")
            for _, row in fc.iterrows()])

        runs = s.runs.tail(60)
        dur = runs.duration_s
        self.dur_chart.plot(runs.started_at, [
            {"type": "line", "values": dur, "color": T.INFO, "width": 1, "label": "Run duration"},
            {"type": "line", "values": ind.ema(dur, 7), "color": T.ORANGE, "label": "EMA 7"},
            {"type": "hline", "y": float(dur.median()), "color": T.MUTED, "label": "median"}],
            title="Run duration (last 60 runs)", y_fmt=fmt_secs,
            x_fmt="%d %b" if a.mode == "day" else "%d %b %H:%M")
        hist = s.suite["history"].tail(60)
        self.size_chart.plot(hist.index, [
            {"type": "line", "values": hist.values, "color": T.PURPLE, "label": "Tests per run"}],
            title=f"Test suite size (growth {s.suite['growth']:+d} tests)", y_fmt=lambda v: f"{v:,.0f}",
            x_fmt="%d %b" if a.mode == "day" else "%d %b %H:%M")

        tbf = s.duration_by_feature()
        top = tbf.seconds_per_run.max() if len(tbf) else 1
        self.time_bars.set([(r.feature, r.seconds_per_run, top, T.ACCENT, f"{fmt_secs(r.seconds_per_run)} · "
                                                                           f"{r.share:.0%}") for r in tbf.itertuples()])
        bf = s.suite["by_feature"]
        self.size_table.load([(r.feature, r.automated, r.manual, r.total) for r in bf.itertuples()])

        tf = s.top_failures
        fmt_t = "%d %b" if a.mode == "day" else "%d %b %H:%M"
        self.fail_table.load([(r.test, r.feature, r.failures, T.pct(r.fail_rate, 0), r.streak, r.status_now,
                               r.last_failed.strftime(fmt_t), (r.last_message or "")[:160]) for r in tf.itertuples()],
                             tags=["bad" if r.status_now == "FAILED" else "" for r in tf.itertuples()])
        rs = s.failure_reasons
        self.reason_table.load([(r.reason, r.occurrences, r.tests, r.features) for r in rs.itertuples()])
        sl = s.slowest
        self.slow_table.load([(r.test, fmt_secs(r.median_s), fmt_secs(r.p95_s), T.pct(r.share, 1),
                               "–" if r.change != r.change else f"{r.change:+.0%}") for r in sl.itertuples()],
                             tags=["bad" if r.change == r.change and r.change > 0.2 else "" for r in sl.itertuples()])
        fl = s.flaky
        if fl.empty:
            self.flaky_table.load([("No flaky or suspected tests", "", "", "", "",
                                    f"based on {a.kpis['runs']} run(s)")], tags=["muted"])
        else:
            self.flaky_table.load([(r.test, r.feature, r.executions, T.pct(r.flip_rate, 0), T.pct(r.fail_share, 0),
                                    r.verdict) for r in fl.itertuples()],
                                  tags=["warn" if r.verdict == "Flaky" else "muted" for r in fl.itertuples()])


# --------------------------------------------------------------------------- Methodology
METHODS = [
    ("Pass-rate trend", "EMA(7) vs SMA(28) of pass rate per bar",
     "Short average below long average = quality deteriorating; crossing back = recovery."),
    ("Expected range", "Bollinger band: SMA(20) ± 2σ; band width = (upper − lower) / mid",
     "Results outside the band are unusual; a wide band means an unstable suite or endpoint."),
    ("Momentum", "MACD = EMA(12) − EMA(26); signal = EMA(9); histogram = MACD − signal",
     "Negative histogram = pass-rate momentum falling — early sign of a regression period."),
    ("Failure pressure", "RSI(14), Wilder smoothing, on the failure rate",
     "≥ 70: failure increases dominate recent change. Escalated only if failure rate ≥ 5%."),
    ("Rate of change", "Δ of 7-bar SMA over 7 bars (pp for rates, % for time/latency)",
     "How fast failures or durations are rising or falling."),
    ("Volatility (ATR)", "Average true range of OHLC candles of suite duration / latency, as % of close",
     "Execution-time and latency instability, comparable across features."),
    ("Latency spread", "p95 − p50", "Tail heaviness: slow outliers even when the median looks fine."),
    ("Alert ladder", "baseline × (1 + 10% · level), levels 1–5", "Where the current p95 sits relative to normal."),
    ("Support / resistance", "Median of failure-rate troughs / peaks (≥ 3 turning points)",
     "Typical failure floor a feature recovers to, and typical regression ceiling."),
    ("Recovery ratio", "(peak − current) / (peak − baseline)", "Share of the last regression that has been recovered."),
    ("Regression events", "EMA–SMA gap beyond noise-scaled threshold (3·1.4826·MAD) + negative MACD",
     "Marks regression start and recovery; anomalies need ≥ 2 excess failures."),
    ("Multi-timeframe", "Pass rate over last 5 runs, 7, 28, 90 bars",
     "Short-term dip vs deteriorating vs chronic vs improving."),
    ("Flaky tests", "Flip rate ≥ 0.2 and failure share 5–70% over the last 40 executions",
     "Tests that alternate rather than stay broken."),
    ("Coverage", "Requirements with ≥ 1 automated test / total requirements (per layer for UI / API)",
     "Gaps in automated protection."),
    ("Coverage leverage", "exposure (criticality + change volume) ÷ coverage", "Risk carried per unit of protection."),
    ("Quality gate", "Fail if failure rate ≥ 10%, pressure ≥ 70 (with floor), or coverage ≤ 50% on critical features",
     "A simple release signal per feature."),
    ("Regression risk", "100 × Σ weight · component (capped 0–1)",
     "Prioritisation heuristic; weights are judgement calls, not fitted."),
    ("Test budget", "Risk-proportional split with 3% floor and 35% cap per feature",
     "Where to spend limited execution time."),
]


class MethodologyPage(Page):
    title = "Methodology"
    subtitle = "How every number on this dashboard is computed. Windows are counted in bars (days or runs)."

    def build(self):
        c = Card(self.body)
        c.pack(fill="both", expand=True)
        t = Table(c.body, [("name", "Signal", 170, "w"), ("how", "Computation", 430, "w"),
                           ("why", "What it tells you", 480, "w")], height=len(METHODS))
        t.pack(fill="both", expand=True)
        t.load(METHODS)
