"""Algorithms ported from 'Forex Algorithmic Trading.pdf' / 'Foundation forex.pdf'.

Each function keeps the original computation and states the Forex original it
comes from. Inputs are pandas DataFrames, following the PDF style
(df.loc[cond], column sums).
"""
import numpy as np
import pandas as pd

# Refernce: mt5.TIMEFRAME_D1 / W1 / MN1  →  pandas resample rules
TIMEFRAMES = {"D1": "D", "W1": "W-MON", "MN1": "MS"}


def to_candles(df: pd.DataFrame, time_col: str, value_col: str, timeframe: str = "D1") -> pd.DataFrame:
    """PDF: copy_rates_from_pos(symbol, TIMEFRAME, 0, n) → OHLC bars.

    QA: OHLC of a metric (test duration, API latency) per bar.
    open = first sample, high = max, low = min, close = last, volume = samples.
    """
    s = df.set_index(time_col)[value_col].sort_index()
    rule = TIMEFRAMES.get(timeframe, timeframe)
    out = s.resample(rule).agg(["first", "max", "min", "last", "count"])
    out.columns = ["open", "high", "low", "close", "volume"]
    return out.dropna()


def latency_spread(latencies: pd.Series) -> float:
    """PDF: spread = ask - bid.  QA: spread = p95 - p50 (tail heaviness, ms)."""
    if latencies.empty:
        return float("nan")
    return float(latencies.quantile(0.95) - latencies.quantile(0.50))


def net_results(results: pd.DataFrame) -> dict:
    """PDF: cal_profit / cal_volume = df['profit'].sum(), df['volume'].sum().

    QA: totals over executed results (SKIPPED excluded from the rate).
    """
    executed = results.loc[results.status != "SKIPPED"]
    passed = int((executed.status == "PASSED").sum())
    failed = int((executed.status == "FAILED").sum())
    total = passed + failed
    return {"passed": passed, "failed": failed, "executed": total,
            "skipped": int((results.status == "SKIPPED").sum()),
            "pass_rate": passed / total if total else float("nan")}


def results_by_layer(results: pd.DataFrame) -> dict:
    """PDF: cal_buy_profit (df.type == 0) / cal_sell_profit (df.type == 1).

    QA: the same aggregation, split by test layer (UI / API).
    """
    return {layer: net_results(results.loc[results.layer == layer])
            for layer in sorted(results.layer.dropna().unique())}


def coverage_leverage(exposure: float, coverage: float, floor: float = 0.05) -> float:
    """PDF: margin = notional / leverage  ⇒  leverage = notional / margin.

    QA: exposure (criticality × change volume, normalised 0-1) held on a
    'margin' of automated coverage (0-1). Higher = more risk per unit of
    protection. floor avoids division blow-up on zero coverage.
    """
    return float(exposure / max(coverage, floor))


def defect_yield(failures_caught: int, coverage: float) -> float:
    """PDF: pct_profit = profit / margin * 100.

    QA: failures caught per 100% of requirement coverage — where the
    existing tests are actually finding problems.
    """
    if coverage <= 0:
        return float("nan")
    return float(failures_caught / coverage)


def threshold_ladder(baseline: float, current: float, step_pct: float = 10.0, levels: int = 5) -> list:
    """PDF: draw_grid — price = (pct_change / (100*100)) * current + current,
    pct_change stepping 1, 2, 3 … above and -1, -2 … below.

    QA: alert levels around a latency/duration baseline. Uses step_pct per level
    (the PDF's 1/10000 factor is a pip-scale artefact). Returns
    [(level_no, threshold, breached), ...] for the upper side, which is the
    side that matters for latency/duration.
    """
    ladder = []
    for i in range(1, levels + 1):
        threshold = (i * step_pct / 100.0) * baseline + baseline
        ladder.append((i, threshold, current >= threshold))
    return ladder


def quality_gate(signals: dict, targets: dict) -> list:
    """PDF: while True: if pct_profit >= profit_target: close_all(symbol).

    QA: evaluate each signal against its target; a breach fails the gate.
    `signals` and `targets` are {name: value}; a target is (op, threshold)
    with op in {'>=', '<='} meaning "breach when value op threshold".
    Returns a list of breach descriptions (empty = gate PASS).
    """
    breaches = []
    for name, (op, threshold) in targets.items():
        value = signals.get(name)
        if value is None or (isinstance(value, float) and np.isnan(value)):
            continue
        if (op == ">=" and value >= threshold) or (op == "<=" and value <= threshold):
            breaches.append(f"{name} = {value:.2f} (limit {op} {threshold})")
    return breaches


def allocate_test_budget(risk: pd.Series, budget: float, floor_share: float = 0.03,
                         cap_share: float = 0.35) -> pd.Series:
    """Position sizing: size each 'position' in proportion to its risk, under
    a total budget, with a minimum floor (every feature gets some smoke
    coverage) and a cap (no single feature eats the whole run).

    risk: Series indexed by feature, non-negative scores. budget: e.g. minutes.
    """
    risk = risk.clip(lower=0).astype(float)
    n = len(risk)
    if n == 0 or budget <= 0:
        return pd.Series(dtype=float)
    floor = budget * floor_share
    remaining = budget - floor * n
    if remaining <= 0:
        return pd.Series(budget / n, index=risk.index)
    weights = risk / risk.sum() if risk.sum() > 0 else pd.Series(1.0 / n, index=risk.index)
    alloc = floor + weights * remaining
    cap = budget * cap_share
    # Redistribute anything above the cap to the uncapped features.
    for _ in range(n):
        over = alloc > cap
        if not over.any():
            break
        excess = (alloc[over] - cap).sum()
        alloc[over] = cap
        free = ~over
        if not free.any():
            break
        alloc[free] += excess * weights[free] / weights[free].sum()
    return alloc.round(1)
