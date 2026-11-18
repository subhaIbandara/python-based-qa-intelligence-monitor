"""QA Intelligence engine.

Turns raw test results, durations and HTTP/page timings into explainable QA
signals: trends, failure pressure, momentum, volatility, anomalies, risk and
recommendations. Pure pandas — no Tkinter, no database.

Time is measured in *bars*:
  mode="day" – one bar per calendar day (long histories, several runs/day)
  mode="run" – one bar per test run (young projects: trends after a few runs)
All windows (short = 7 bars, long = 28 bars …) are counted in bars.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

import config as C
from engine import forex_core as fx
from engine import indicators as ind

SIGNALS = ["Pass rate", "Failure rate", "Suite duration (s)", "API latency p95 (ms)"]
SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}
REVERSAL_THRESHOLD = 0.025      # minimum EMA-short vs SMA-long gap (2.5 pp) to call a regression
MIN_BARS_FOR_TREND = 10


@dataclass
class Insight:
    severity: str
    area: str
    title: str
    evidence: str
    recommendation: str


@dataclass
class Event:
    date: pd.Timestamp
    kind: str            # "Regression start" | "Recovery" | "Anomaly"
    detail: str


def _nz(v, default=0.0):
    return default if v is None or (isinstance(v, float) and np.isnan(v)) else v


class QAAnalytics:
    def __init__(self, data: dict, mode: str = "day"):
        self.data = data
        self.mode = mode
        self.features = data["features"].set_index("id")
        self.envs = data["environments"].set_index("id")
        cases = data["test_cases"]
        runs = data["test_runs"]

        r = data["test_results"].merge(runs, left_on="run_id", right_on="id", suffixes=("", "_run"))
        r = r.merge(cases[["id", "feature_id", "layer", "name"]], left_on="test_case_id",
                    right_on="id", suffixes=("", "_case"))
        if "message" not in r:
            r["message"] = None
        r["bar"] = r["started_at"].dt.normalize() if mode == "day" else r["started_at"]
        r["is_failed"] = r["status"] == "FAILED"
        r["is_executed"] = r["status"] != "SKIPPED"
        self.results = r.sort_values(["started_at", "test_case_id"]).reset_index(drop=True)

        if mode == "day":
            self.bars = pd.date_range(r["bar"].min(), r["bar"].max(), freq="D")
        else:
            self.bars = pd.DatetimeIndex(sorted(r["bar"].unique()))
        self.end = self.bars[-1]

        m = data["api_metrics"].merge(data["api_endpoints"], left_on="endpoint_id", right_on="id",
                                      suffixes=("", "_ep")).sort_values("measured_at")
        if mode == "day":
            m["bar"] = m["measured_at"].dt.normalize()
        else:   # attach each sample to the run that was executing when it was measured
            starts = pd.DataFrame({"bar": self.bars})
            m = pd.merge_asof(m, starts, left_on="measured_at", right_on="bar", direction="backward")
            m = m.dropna(subset=["bar"])
        self.metrics = m
        self.endpoints = data["api_endpoints"].set_index("id")
        self.endpoints["label"] = self.endpoints["method"] + " " + self.endpoints["path"]

        executed = self.results[self.results.is_executed]
        self.suite_runs = (executed.groupby(["run_id", "feature_id", "environment_id"])
                           .agg(started_at=("started_at", "first"), bar=("bar", "first"),
                                duration_ms=("duration_ms", "sum"))
                           .reset_index())
        self.suite_runs["duration_s"] = self.suite_runs["duration_ms"] / 1000.0

        self.coverage = self._coverage()
        self.flaky = self._flaky_tests()
        self.feature_table = self._feature_table()
        self.env_table = self._env_table()
        self.endpoint_table = self._endpoint_table()
        self.kpis = self._kpis()
        self.insights = self._insights()

    # ------------------------------------------------------------- bar helpers
    @property
    def n_bars(self) -> int:
        return len(self.bars)

    def w(self, n: int) -> str:
        """Human label for a window of n bars."""
        if self.mode == "day":
            return f"{n}d"
        n = min(n, self.n_bars)
        return f"{n} run" if n == 1 else f"{n} runs"

    def latest_failures(self, feature_id=None) -> pd.DataFrame:
        """Failed tests (name, message) in the most recent run."""
        r = self.results[self.results.run_id == self.results.run_id.max()]
        if feature_id is not None:
            r = r[r.feature_id == feature_id]
        return r[r.is_failed][["name", "message"]]

    def _cutoff(self, n: int, offset: int = 0):
        """(lo, hi) bar timestamps covering the n bars ending `offset` bars ago."""
        hi_pos = self.n_bars - 1 - offset
        if hi_pos < 0:
            return None
        return self.bars[max(0, hi_pos - n + 1)], self.bars[hi_pos]

    def _in_window(self, df: pd.DataFrame, n: int, offset: int = 0) -> pd.DataFrame:
        cut = self._cutoff(n, offset)
        if cut is None:
            return df.iloc[0:0]
        return df[(df.bar >= cut[0]) & (df.bar <= cut[1])]

    def _rate_window(self, d: pd.DataFrame, n: int, offset: int = 0) -> float:
        end = len(d) - offset
        if end <= 0:
            return float("nan")
        part = d.iloc[max(0, end - n):end]
        executed = part["executed"].sum()
        return float(part["failed"].sum() / executed) if executed else float("nan")

    def _bar_candles(self, df: pd.DataFrame, time_col: str, value_col: str, timeframe: str = None):
        timeframe = timeframe or ("D1" if self.mode == "day" else "RUN")
        if timeframe != "RUN":
            return fx.to_candles(df, time_col, value_col, timeframe)
        g = df.sort_values(time_col).groupby("bar")[value_col]
        out = g.agg(["first", "max", "min", "last", "count"])
        out.columns = ["open", "high", "low", "close", "volume"]
        return out

    # ------------------------------------------------------------------ series
    def _filter_results(self, feature_id=None, env_id=None):
        r = self.results
        if feature_id is not None:
            r = r[r.feature_id == feature_id]
        if env_id is not None:
            r = r[r.environment_id == env_id]
        return r

    def daily_rates(self, feature_id=None, env_id=None) -> pd.DataFrame:
        """Per-bar executed/failed counts and pass/fail rate."""
        r = self._filter_results(feature_id, env_id)
        r = r[r.is_executed]
        g = r.groupby("bar").agg(executed=("is_executed", "size"), failed=("is_failed", "sum"))
        g = g.reindex(self.bars)
        g["fail_rate"] = g["failed"] / g["executed"]
        g["pass_rate"] = 1 - g["fail_rate"]
        g[["fail_rate", "pass_rate"]] = g[["fail_rate", "pass_rate"]].interpolate(limit_direction="both")
        return g

    def _filter_metrics(self, feature_id=None, env_id=None, endpoint_id=None):
        m = self.metrics
        if feature_id is not None:
            m = m[m.feature_id == feature_id]
        if env_id is not None:
            m = m[m.environment_id == env_id]
        if endpoint_id is not None:
            m = m[m.endpoint_id == endpoint_id]
        return m

    def series(self, signal: str, feature_id=None, env_id=None, endpoint_id=None) -> pd.Series:
        if signal in ("Pass rate", "Failure rate"):
            d = self.daily_rates(feature_id, env_id)
            return d["pass_rate" if signal == "Pass rate" else "fail_rate"]
        if signal == "Suite duration (s)":
            c = self.candles(signal, feature_id, env_id)
            return c["close"].reindex(self.bars).interpolate(limit_direction="both")
        m = self._filter_metrics(feature_id, env_id, endpoint_id)
        return m.groupby("bar")["latency_ms"].quantile(0.95).reindex(self.bars).interpolate(
            limit_direction="both")

    def candles(self, signal: str, feature_id=None, env_id=None, endpoint_id=None,
                timeframe: str = None) -> pd.DataFrame:
        """OHLC bars of suite duration or latency."""
        if signal == "API latency p95 (ms)":
            m = self._filter_metrics(feature_id, env_id, endpoint_id)
            return self._bar_candles(m, "measured_at", "latency_ms", timeframe)
        s = self.suite_runs
        if env_id is not None:
            s = s[s.environment_id == env_id]
        if feature_id is not None:
            return self._bar_candles(s[s.feature_id == feature_id], "started_at", "duration_s", timeframe)
        total = (s.groupby("run_id").agg(started_at=("started_at", "first"), bar=("bar", "first"),
                                         duration_s=("duration_s", "sum")).reset_index())
        return self._bar_candles(total, "started_at", "duration_s", timeframe)

    def bundle(self, s: pd.Series) -> dict:
        """All indicators for one series."""
        return {
            "ema_short": ind.ema(s, C.SHORT_MA),
            "sma_long": ind.sma(s, C.LONG_MA),
            "bb": ind.bollinger(s, C.BOLLINGER_N, C.BOLLINGER_K),
            "macd": ind.macd(s),
            "rsi": ind.rsi(s, C.RSI_PERIOD),
            "momentum": ind.momentum_pp(ind.sma(s, C.MOMENTUM_DAYS), C.MOMENTUM_DAYS),
        }

    def reversal_events(self, pass_rate: pd.Series, executed: pd.Series = None) -> list:
        """Regression start / recovery (short EMA vs long SMA gap, confirmed by a
        negative MACD histogram, with hysteresis) and lower-band anomalies.

        The regression threshold scales with the series' own noise
        (3 × 1.4826·MAD of the gap), so noisy suites need a bigger move.
        executed: per-bar execution counts; an anomaly then also needs >= 2
        failures more than the band mid predicts.
        """
        es = ind.ema(pass_rate, C.SHORT_MA)
        sl = ind.sma(pass_rate, C.LONG_MA)
        hist = ind.macd(pass_rate)["hist"]
        bb = ind.bollinger(pass_rate, C.BOLLINGER_N, C.BOLLINGER_K)
        gap_all = (es - sl).dropna()
        mad = float((gap_all - gap_all.median()).abs().median()) if len(gap_all) else 0.0
        threshold = max(REVERSAL_THRESHOLD, 3 * 1.4826 * mad)
        events, regressed, prev_low = [], False, False
        unit = "day" if self.mode == "day" else "run"
        for bar in pass_rate.index[C.LONG_MA // 2:]:
            gap = es[bar] - sl[bar]
            if np.isnan(gap):
                continue
            if not regressed and gap < -threshold and hist[bar] < 0:
                regressed = True
                events.append(Event(bar, "Regression start",
                                    f"short-term pass rate {es[bar]:.1%} dropped {abs(gap) * 100:.1f} pp below its "
                                    f"{C.LONG_MA}-{unit} baseline {sl[bar]:.1%}, and quality momentum turned negative"))
            elif regressed and gap > -threshold / 3:
                regressed = False
                events.append(Event(bar, "Recovery", f"short-term pass rate {es[bar]:.1%} is back within "
                                                     f"{abs(gap) * 100:.1f} pp of its baseline"))
            low = (not np.isnan(bb["lower"][bar]) and pass_rate[bar] < bb["lower"][bar]
                   and bb["mid"][bar] - pass_rate[bar] >= 0.02)
            if low and executed is not None and not np.isnan(executed.get(bar, np.nan)):
                low = (bb["mid"][bar] - pass_rate[bar]) * executed[bar] >= 2
            if low and not prev_low:
                events.append(Event(bar, "Anomaly", f"pass rate {pass_rate[bar]:.1%} fell below its normal range "
                                                    f"(lowest expected {bb['lower'][bar]:.1%})"))
            prev_low = low
        return events

    # ------------------------------------------------------------- components
    def _coverage(self) -> pd.DataFrame:
        cases = self.data["test_cases"]
        auto = cases[cases.automated & cases.requirement_no.notna()]
        out = self.features[["name", "criticality", "requirements_count"]].copy()
        out["covered"] = auto.groupby("feature_id")["requirement_no"].nunique().reindex(out.index).fillna(0)
        for layer in ("UI", "API"):
            out[f"covered_{layer}"] = (auto[auto.layer == layer].groupby("feature_id")["requirement_no"]
                                       .nunique().reindex(out.index).fillna(0))
        out["coverage"] = out["covered"] / out["requirements_count"]
        out["ui_coverage"] = out["covered_UI"] / out["requirements_count"]
        out["api_coverage"] = out["covered_API"] / out["requirements_count"]
        out["automated_tests"] = cases[cases.automated].groupby("feature_id").size().reindex(out.index).fillna(0)
        out["manual_tests"] = cases[~cases.automated].groupby("feature_id").size().reindex(out.index).fillna(0)
        return out

    def _flaky_tests(self, last_n: int = 40, min_n: int = 10) -> pd.DataFrame:
        """Flaky = alternates pass/fail rather than staying broken.
        flip rate = status changes / (n-1) over the last n executions; flaky when
        flip rate >= 0.2 and failure share between 5% and 70%."""
        r = self.results[self.results.is_executed]
        rows = []
        for tid, g in r.groupby("test_case_id"):
            g = g.tail(last_n)
            f = g["is_failed"].to_numpy()
            if len(f) < min_n:
                continue
            flip_rate = int((f[1:] != f[:-1]).sum()) / (len(f) - 1)
            share = float(f.mean())
            rows.append((tid, g["name"].iloc[0], int(g["feature_id"].iloc[0]), flip_rate, share,
                         flip_rate >= 0.2 and 0.05 <= share <= 0.7))
        df = pd.DataFrame(rows, columns=["test_case_id", "name", "feature_id", "flip_rate", "fail_share", "flaky"])
        df["flaky"] = df["flaky"].astype(bool)
        return df.sort_values("flip_rate", ascending=False).reset_index(drop=True)

    def _last_runs_pass_rate(self, r: pd.DataFrame, n: int = 5) -> float:
        r = r[r.is_executed]
        last_runs = r["run_id"].drop_duplicates().tail(n)
        sub = r[r.run_id.isin(last_runs)]
        return float(1 - sub["is_failed"].mean()) if len(sub) else float("nan")

    def newly_failing(self, feature_id: int) -> pd.DataFrame:
        """Tests failing >= 50% in the last 7 bars that were < 10% before."""
        r = self._filter_results(feature_id)
        r = r[r.is_executed]
        recent = self._in_window(r, 7).groupby("name")["is_failed"].mean()
        before = self._in_window(r, 21, offset=7).groupby("name")["is_failed"].mean()
        both = pd.DataFrame({"recent": recent, "before": before}).fillna(0)
        both = both[(both.recent >= 0.5) & (both.before < 0.1)]
        first = self._in_window(r[r.name.isin(both.index) & r.is_failed], 14).groupby("name")["started_at"].min()
        both["first_failed"] = first
        return both.sort_values("first_failed")

    def env_attribution(self, feature_id: int, n: int = 7):
        """If one environment holds >= 60% of a feature's recent failures while
        running < 40% of its executions, return that environment's name."""
        if len(self.envs) < 2:
            return None
        r = self._in_window(self._filter_results(feature_id), n)
        r = r[r.is_executed]
        if r.is_failed.sum() < 3:
            return None
        fail_share = r[r.is_failed].groupby("environment_id").size() / r.is_failed.sum()
        exec_share = r.groupby("environment_id").size() / len(r)
        for eid, share in fail_share.items():
            if share >= 0.6 and exec_share.get(eid, 1) < 0.4:
                return self.envs.loc[eid, "name"]
        return None

    def _feature_table(self) -> pd.DataFrame:
        rows = []
        changes = self.data["code_changes"]
        recent_changes = changes[changes.changed_at > self.end - pd.Timedelta(days=14)]
        lines14 = recent_changes.groupby("feature_id")["lines_changed"].sum()
        commits14 = recent_changes.groupby("feature_id").size()
        flaky_count = self.flaky[self.flaky.flaky].groupby("feature_id").size()
        for fid_, feat in self.features.iterrows():
            d = self.daily_rates(fid_)
            pr = d["pass_rate"]
            b = self.bundle(pr)
            dur_candles = self.candles("Suite duration (s)", fid_)
            atrp = (float(ind.atr_pct(dur_candles, C.ATR_PERIOD).iloc[-1])
                    if len(dur_candles) > C.ATR_PERIOD else np.nan)
            fail7, fail_prev7 = self._rate_window(d, 7), self._rate_window(d, 7, offset=7)
            fail28, fail90 = self._rate_window(d, 28), self._rate_window(d, 90)
            mom = fail7 - fail_prev7
            fpi = float(ind.rsi(d["fail_rate"], C.RSI_PERIOD).iloc[-1])
            hist = float(b["macd"]["hist"].iloc[-1])
            bw = float(b["bb"]["bandwidth"].iloc[-7:].mean())
            cov = self.coverage.loc[fid_]
            smooth_fail = d["fail_rate"].rolling(3, min_periods=1).mean()
            support, resistance = ind.support_resistance(smooth_fail)
            rec = ind.recovery_ratio(smooth_fail)
            events = self.reversal_events(pr, d["executed"])
            last5 = self._last_runs_pass_rate(self._filter_results(fid_))
            lines = int(lines14.get(fid_, 0))
            exposure = ((feat.criticality - 1) / 4) * 0.5 + min(lines / 3000, 1) * 0.5

            # Each component scaled to 0..1 with fixed, documented caps.
            comps = {
                "failure_rate": min(_nz(fail7) / 0.25, 1.0),
                "momentum": min(max(_nz(mom), 0) / 0.10, 1.0) * 0.8 + (0.2 if hist < 0 else 0.0),
                "volatility": min(_nz(atrp) / 40, 1.0) * 0.5 + min(_nz(bw) / 0.3, 1.0) * 0.5,
                "criticality": (feat.criticality - 1) / 4,
                "coverage_gap": 1 - cov.coverage,
                "change_volume": min(lines / 3000, 1.0),
            }
            contrib = {k: 100 * C.RISK_WEIGHTS[k] * v for k, v in comps.items()}
            gate = fx.quality_gate(
                {f"Failure rate ({self.w(7)})": fail7,
                 "Failure pressure": fpi if _nz(fail7) >= C.FPI_FLOOR else np.nan,
                 "Coverage": cov.coverage if feat.criticality >= 4 else np.nan},
                {f"Failure rate ({self.w(7)})": (">=", 0.10), "Failure pressure": (">=", C.FPI_HIGH),
                 "Coverage": ("<=", 0.5)})
            trend = ("Collecting data" if self.n_bars < MIN_BARS_FOR_TREND
                     else self._classify_timeframes(last5, 1 - fail7, 1 - fail28, 1 - fail90))
            rows.append({
                "feature_id": fid_, "feature": feat["name"], "criticality": int(feat.criticality),
                "pass_last5": last5, "pass_7d": 1 - fail7, "pass_28d": 1 - fail28, "pass_90d": 1 - fail90,
                "fail_7d": fail7, "fail_prev7": fail_prev7, "momentum_pp": mom, "fpi": fpi, "macd_hist": hist,
                "bandwidth": bw, "atr_pct": atrp, "coverage": cov.coverage, "ui_coverage": cov.ui_coverage,
                "api_coverage": cov.api_coverage, "uncovered": int(cov.requirements_count - cov.covered),
                "lines_14d": lines, "commits_14d": int(commits14.get(fid_, 0)),
                "flaky_tests": int(flaky_count.get(fid_, 0)),
                "leverage": fx.coverage_leverage(exposure, cov.coverage),
                "defect_yield": fx.defect_yield(int(d["failed"].iloc[-7:].sum()), cov.coverage),
                "support": support, "resistance": resistance, "recovery": rec,
                "events": events, "gate": gate,
                "risk": sum(contrib.values()), **{f"c_{k}": v for k, v in contrib.items()},
                "trend": trend,
            })
        return pd.DataFrame(rows).sort_values("risk", ascending=False).reset_index(drop=True)

    @staticmethod
    def _classify_timeframes(last5, p7, p28, p90) -> str:
        """Multi-timeframe classification (thresholds in pass-rate points)."""
        if p28 < 0.92 and p90 < 0.95 and p7 < 0.95:
            return "Chronic"
        if p7 < p28 - 0.03 or last5 < p28 - 0.08:
            return "Deteriorating" if p7 < p90 - 0.05 else "Short-term dip"
        if p7 > p28 + 0.03:
            return "Improving"
        return "Stable"

    def _env_table(self) -> pd.DataFrame:
        rows = []
        for eid, env in self.envs.iterrows():
            d = self.daily_rates(env_id=eid)
            if d["executed"].sum() == 0:
                continue
            fail7, fail_base = self._rate_window(d, 7), self._rate_window(d, 28, offset=7)
            r = self._filter_results(env_id=eid)
            per_run = (r[r.is_executed].groupby("run_id")
                       .agg(started_at=("started_at", "first"), bar=("bar", "first"),
                            fail_rate=("is_failed", "mean")).reset_index())
            fr_candles = self._bar_candles(per_run, "started_at", "fail_rate")
            atr_fr = float(ind.atr(fr_candles, C.ATR_PERIOD).iloc[-1] * 100) if len(fr_candles) else np.nan
            m = self._filter_metrics(env_id=eid)
            m7, mprev = self._in_window(m, 7), self._in_window(m, 28, offset=7)
            p95_7 = m7.latency_ms.quantile(0.95) if len(m7) else np.nan
            p95_prev = mprev.latency_ms.quantile(0.95) if len(mprev) else np.nan
            events = self.reversal_events(d["pass_rate"], d["executed"])
            recent_cut = self._cutoff(14)[0]
            change = _nz(fail7) - _nz(fail_base, _nz(fail7))
            rows.append({
                "env_id": eid, "environment": env["name"], "pass_7d": 1 - fail7, "pass_baseline": 1 - fail_base,
                "fail_change_pp": change * 100, "fpi": float(ind.rsi(d["fail_rate"]).iloc[-1]),
                "atr_fail_pp": atr_fr, "p95_7d": p95_7,
                "p95_change_pct": 100 * (p95_7 - p95_prev) / p95_prev if p95_prev else np.nan,
                "spread": fx.latency_spread(m7.latency_ms),
                "error_rate": float((m7.status_code >= 500).mean()) if len(m7) else np.nan,
                "events": events,
                "status": ("Unstable" if change > 0.03 or any(
                    e.kind == "Regression start" and e.date >= recent_cut for e in events) else "Stable"),
            })
        return pd.DataFrame(rows, columns=["env_id", "environment", "pass_7d", "pass_baseline", "fail_change_pp",
                                           "fpi", "atr_fail_pp", "p95_7d", "p95_change_pct", "spread",
                                           "error_rate", "events", "status"])

    def endpoint_p95(self, endpoint_id: int) -> pd.Series:
        """Per-bar p95 per environment, then the median across environments, so
        one unstable environment does not masquerade as an endpoint trend."""
        m = self.metrics[self.metrics.endpoint_id == endpoint_id]
        if m.empty:
            return pd.Series(np.nan, index=self.bars)
        per_env = m.groupby(["bar", "environment_id"])["latency_ms"].quantile(0.95).unstack()
        return per_env.median(axis=1).reindex(self.bars).interpolate(limit_direction="both")

    def _endpoint_table(self) -> pd.DataFrame:
        rows = []
        for eid, ep in self.endpoints.iterrows():
            m = self.metrics[self.metrics.endpoint_id == eid]
            if m.empty:
                continue
            p95 = self.endpoint_p95(eid)
            bb = ind.bollinger(p95, C.BOLLINGER_N, C.BOLLINGER_K)
            m7 = self._in_window(m, 7)
            p95_7 = float(p95.iloc[-7:].median())
            base = p95.iloc[max(0, len(p95) - 35):max(0, len(p95) - 7)]
            baseline = float(base.median()) if len(base) else np.nan
            ladder = fx.threshold_ladder(baseline, p95_7, step_pct=10, levels=5)
            level = max([lvl for lvl, _, hit in ladder if hit], default=0)
            candles = self._bar_candles(m, "measured_at", "latency_ms")
            rows.append({
                "endpoint_id": eid, "endpoint": ep["label"], "feature": self.features.loc[ep.feature_id, "name"],
                "p50_7d": float(m7.latency_ms.median()), "p95_7d": p95_7, "baseline_p95": baseline,
                "change_pct": 100 * (p95_7 - baseline) / baseline if baseline else np.nan,
                "spread": fx.latency_spread(m7.latency_ms),
                "ladder_level": level, "ladder": ladder,
                "anomaly_bars": int(bb["outside"].iloc[-7:].sum()),
                "error_rate": float((m7.status_code >= 400).mean()),
                "atr_pct": float(ind.atr_pct(candles).iloc[-1]) if len(candles) > C.ATR_PERIOD else np.nan,
                "samples": len(m),
            })
        cols = ["endpoint_id", "endpoint", "feature", "p50_7d", "p95_7d", "baseline_p95", "change_pct", "spread",
                "ladder_level", "ladder", "anomaly_bars", "error_rate", "atr_pct", "samples"]
        return pd.DataFrame(rows, columns=cols).sort_values("change_pct", ascending=False,
                                                            na_position="last").reset_index(drop=True)

    def _kpis(self) -> dict:
        cases = self.data["test_cases"]
        latest = self.results[self.results.is_executed].groupby("test_case_id").tail(1)
        d = self.daily_rates()
        fail7 = self._rate_window(d, 7)
        pass7 = 1 - fail7
        b = self.bundle(d["pass_rate"])
        inside = 1 - float(b["bb"]["outside"].iloc[-14:].mean())
        n_auto = int(cases.automated.sum())
        flaky_rate = float(self.flaky.flaky.sum() / n_auto) if n_auto else 0.0
        stability = (1 - flaky_rate) * inside
        cov = self.coverage
        req_total = cov.requirements_count.sum()
        coverage = float(cov.covered.sum() / req_total)
        fpi = float(ind.rsi(d["fail_rate"]).iloc[-1])
        pressure_ok = 1 - max(0.0, (_nz(fpi, 50) - 50) / 50) if _nz(fail7) >= C.FPI_FLOOR else 1.0
        et = self.endpoint_table
        # share of endpoints whose recent p95 is within +20% of baseline (ladder level < 2)
        latency_ok = float((et.ladder_level < 2).mean()) if len(et) else 1.0
        components = {f"Pass rate ({self.w(7)})": (0.35, pass7), "Stability": (0.20, stability),
                      "Coverage": (0.20, coverage), "Failure pressure": (0.10, pressure_ok),
                      "Latency": (0.15, latency_ok)}
        health = 100 * sum(w * _nz(v) for w, v in components.values())
        mom = fail7 - self._rate_window(d, 7, offset=7)
        last_run = self.results[self.results.run_id == self.results.run_id.max()]
        return {
            "health": health, "health_components": components,
            "total_tests": len(cases), "automated": n_auto, "manual": int((~cases.automated).sum()),
            "passed": int((latest.status == "PASSED").sum()), "failed": int((latest.status == "FAILED").sum()),
            "pass_rate_7d": pass7, "pass_rate_28d": 1 - self._rate_window(d, 28),
            "coverage": coverage,
            "ui_coverage": float(cov.covered_UI.sum() / req_total),
            "api_coverage": float(cov.covered_API.sum() / req_total),
            "flaky_rate": flaky_rate, "flaky_count": int(self.flaky.flaky.sum()),
            "stability": stability, "momentum_pp": mom * 100, "fpi": fpi,
            "avg_risk": float(self.feature_table.risk.mean()),
            "top_risk": self.feature_table.iloc[0]["feature"], "top_risk_score": float(self.feature_table.risk.iloc[0]),
            "layers": fx.results_by_layer(self._in_window(self.results, 7)),
            "runs": int(self.results.run_id.nunique()),
            "executions": int(self.results.is_executed.sum()),
            "last_run_at": self.results.started_at.max(),
            "last_run": fx.net_results(last_run),
        }

    # ---------------------------------------------------------------- insights
    def _insights(self) -> list:
        out = []
        ft = self.feature_table
        w7 = self.w(7)
        last_run = self.results[self.results.run_id == self.results.run_id.max()]
        blocked = last_run[(last_run.status == "SKIPPED") &
                           last_run.message.fillna("").str.contains("bot protection", case=False)]
        if len(blocked):
            out.append(Insight(
                "High", "Test infrastructure", f"{len(blocked)} UI test(s) blocked by bot protection",
                "In the latest run the browser received a bot-challenge page instead of the site, so these "
                "tests were skipped (not counted as failures): " + ", ".join(blocked.name[:5]) + ". "
                "UI coverage is not effective until this is resolved.",
                "Ask the site owners to allowlist the test runner (e.g. a WAF skip rule for the CI egress IP or "
                "a secret request header), or point QA_BASE_URL at an unprotected staging host."))
        median_atr = float(ft.atr_pct.median()) if ft.atr_pct.notna().any() else np.nan
        recent_cut = self._cutoff(14)[0]
        for _, f in ft.iterrows():
            name = f.feature
            rising = _nz(f.momentum_pp) >= 0.03 and _nz(f.fail_7d) >= C.FPI_FLOOR
            if rising:
                newly = self.newly_failing(f.feature_id)
                since = newly.first_failed.min()
                env = self.env_attribution(f.feature_id)
                if env:
                    out.append(Insight("Low", name, f"{name} failures rising, concentrated in {env}",
                                       f"Failure rate {f.fail_7d:.1%} over the last {w7} "
                                       f"(+{f.momentum_pp * 100:.1f} pp); most recent failures come from {env}.",
                                       f"Likely environmental — check {env} before the code."))
                else:
                    out.append(Insight(
                        "High" if f.fail_7d >= 0.10 else "Medium", name,
                        f"{name} has increasing failure momentum",
                        f"Failure rate {f.fail_7d:.1%} over the last {w7} vs {_nz(f.fail_prev7):.1%} before "
                        f"(+{f.momentum_pp * 100:.1f} pp); failure pressure {_nz(f.fpi, 50):.0f}; MACD histogram "
                        f"{'negative' if f.macd_hist < 0 else 'positive'}. {len(newly)} test(s) started failing"
                        + (f" since {since:%d %b %H:%M}" if pd.notna(since) else "") + ".",
                        "Triage the newly failing tests first"
                        + (f" ({', '.join(newly.index[:3])})" if len(newly) else "")
                        + (f"; review the {f.commits_14d} changes ({f.lines_14d:,} lines) merged in the last 14 days."
                           if f.commits_14d else ".")))
            elif f.fail_7d >= 0.10 and self.n_bars < MIN_BARS_FOR_TREND:
                fails = self.latest_failures(f.feature_id)
                recent = self._in_window(self._filter_results(f.feature_id), 7)
                detail = "; ".join(f"{n} — {(m or 'failed')[:120]}" for n, m in fails.itertuples(index=False))
                out.append(Insight(
                    "High" if f.fail_7d >= 0.25 else "Medium", name, f"{name} is failing",
                    f"Failure rate {f.fail_7d:.1%} over the last {w7} ({int(recent.is_failed.sum())} of "
                    f"{int(recent.is_executed.sum())} executed; {int((~recent.is_executed).sum())} skipped). "
                    + (f"Latest run: {detail}." if detail else ""),
                    "Confirm the failure in a browser, then fix or file a defect; failures from a real defect "
                    "should stay red until it is fixed."))
            if not np.isnan(_nz(f.atr_pct, np.nan)) and f.atr_pct >= 2 * median_atr and f.atr_pct >= 10:
                out.append(Insight(
                    "Medium", name, f"{name} has high execution-time volatility",
                    f"Suite duration ATR is {f.atr_pct:.0f}% of the closing value vs a median of "
                    f"{median_atr:.0f}% across features.",
                    "Look for fixed sleeps, unstable test data or slow dependencies; volatile duration often "
                    "precedes timeouts."))
            if f.criticality >= 4 and f.coverage < 0.6:
                out.append(Insight(
                    "High" if f.coverage < 0.4 else "Medium", name,
                    f"{name} has insufficient automation coverage",
                    f"Criticality {f.criticality}/5 but only {f.coverage:.0%} of requirements automated "
                    f"({f.uncovered} uncovered); coverage leverage {f.leverage:.1f}x.",
                    f"Automate the {f.uncovered} uncovered requirement(s), API layer first (fast, stable), then "
                    f"the critical UI journeys."))
            recent_reg = [e for e in f.events if e.kind == "Regression start" and e.date >= recent_cut]
            if recent_reg and not rising:
                env = self.env_attribution(f.feature_id)
                out.append(Insight(
                    "Low" if env else "Medium", name, f"{name} shows an unusual stability decline",
                    f"Regression signal on {recent_reg[-1].date:%d %b}: {recent_reg[-1].detail}."
                    + (f" Failures are concentrated in {env}." if env else ""),
                    f"Likely environmental — check {env} before the code." if env
                    else "Compare failing runs against the last green build."))
            last_rec = [e for e in f.events if e.kind == "Recovery"]
            if f.recovery is not None and not np.isnan(f.recovery) and f.recovery >= 0.8 and last_rec:
                sup = (f" — back near its historical support (typical failure-rate floor) of {f.support:.1%}"
                       if f.support is not None and not np.isnan(f.support) else "")
                out.append(Insight("Info", name, f"{name} has recovered from its regression",
                                   f"Recovered {f.recovery:.0%} of the peak failure rate; recovery signal on "
                                   f"{last_rec[-1].date:%d %b}{sup}.",
                                   "Keep the regression tests added during the fix in the suite."))
        flaky = self.flaky[self.flaky.flaky]
        if len(flaky):
            top = ", ".join(f"{n} ({fr:.0%} flips)" for n, fr in zip(flaky.name[:3], flaky.flip_rate[:3]))
            out.append(Insight("Medium", "Suite", f"{len(flaky)} flaky test(s) detected",
                               f"Tests alternating pass/fail: {top}.",
                               "Quarantine or fix: flaky failures inflate failure signals and hide real regressions."))
        for _, e in self.env_table.iterrows():
            if e.status == "Unstable" and len(self.env_table) > 1:
                out.append(Insight(
                    "High" if e.fail_change_pp >= 5 else "Medium", f"Env: {e.environment}",
                    f"The {e.environment} environment shows an unusual stability decline",
                    f"Pass rate {e.pass_7d:.1%} over the last {w7} vs {e.pass_baseline:.1%} baseline "
                    f"({e.fail_change_pp:+.1f} pp failures); p95 latency {_nz(e.p95_change_pct):+.0f}%; "
                    f"5xx rate {_nz(e.error_rate):.1%}.",
                    "Failures spread across features in a single environment usually point to infrastructure, "
                    "config or data, not code — check recent environment changes."))
        for _, ep in self.endpoint_table.iterrows():
            if _nz(ep.change_pct) >= 25 and ep.ladder_level >= 2:
                out.append(Insight(
                    "Medium" if ep.change_pct < 50 else "High", ep.feature,
                    f"{ep.endpoint} latency is trending up",
                    f"p95 {ep.p95_7d:.0f} ms vs {ep.baseline_p95:.0f} ms baseline ({ep.change_pct:+.0f}%), "
                    f"alert ladder level {ep.ladder_level}/5.",
                    "Profile the endpoint and add a latency assertion to its tests."))
            elif ep.p50_7d > 0 and _nz(ep.spread) / ep.p50_7d >= 2:
                out.append(Insight("Low", ep.feature, f"{ep.endpoint} has a heavy latency tail",
                                   f"p95 − p50 spread {ep.spread:.0f} ms is {ep.spread / ep.p50_7d:.1f}x the median.",
                                   "Investigate intermittent slow paths (cold caches, CDN misses, lock contention)."))
            if _nz(ep.error_rate) >= 0.05:
                out.append(Insight("High", ep.feature, f"{ep.endpoint} is returning errors",
                                   f"{ep.error_rate:.0%} of requests over the last {w7} returned HTTP >= 400.",
                                   "Check the endpoint's availability and recent deployments."))
        if self.n_bars < MIN_BARS_FOR_TREND:
            out.append(Insight("Info", "History", f"Trend indicators warming up ({self.n_bars} bars)",
                               f"Moving averages, failure pressure and anomaly bands need ~{MIN_BARS_FOR_TREND}+ "
                               "bars; until then only current failures, coverage and latency levels are reliable.",
                               "Run the suite regularly (e.g. hourly in CI) to build history."))
        out.sort(key=lambda i: SEVERITY_ORDER[i.severity])
        return out

    # --------------------------------------------------------------- planning
    def allocate(self, budget_minutes: float) -> pd.DataFrame:
        risk = self.feature_table.set_index("feature")["risk"]
        alloc = fx.allocate_test_budget(risk, budget_minutes)
        out = pd.DataFrame({"risk": risk, "minutes": alloc})
        out["share"] = out["minutes"] / budget_minutes
        return out.reset_index()
