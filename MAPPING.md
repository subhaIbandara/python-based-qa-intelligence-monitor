# Forex → QA Algorithm Mapping

This is the inspection step: what the source material contains, what each
algorithm computes, and whether it has an honest QA meaning.

## 0. What the "existing project" actually is

There was no source code in the workspace. The existing project is the course
material in the PDFs:

| PDF | What it contributes |
|---|---|
| `Forex Algorithmic Trading.pdf` | MT5 grid bot: candles per timeframe, `cal_profit`, `cal_volume`, buy/sell split, `cal_*_margin`, `cal_*_pct_profit`, `draw_grid`, profit-target loop, `close_all` |
| `Foundation forex.pdf` | Spread, pip, lot, margin = notional / leverage, P/L arithmetic, limit/stop orders, grid formula `price = pct/(100·leverage)·current + current` |
| `UI design with Tkinter.pdf` | Stack: `tk`/`ttk`, sidebar + stacked frames switched with `tkraise()`, `ttk.Treeview` tables, `ttk.Combobox`, `Menu`, `messagebox`, **`Canvas` for drawing** |
| `Python - Mysql.pdf` | DB-API usage: `connect`, `cursor.execute(q, params)`, `executemany`, `commit`, one-to-many FKs |
| `pandas basics.pdf` | `DataFrame`, `df.loc[cond]`, column selection, iterating `df.index` |

**Gap to be explicit about:** the PDFs contain **no** SMA, EMA, RSI, MACD,
Bollinger Bands, ATR, momentum, or Fibonacci code. Those are implemented from
their standard published formulas in `engine/indicators.py` and are labelled
*new* below. The PDF algorithms are ported in `engine/forex_core.py` and are
labelled *ported*.

Stack decisions kept from the PDFs: Tkinter + ttk, Canvas-drawn charts (no
matplotlib), pandas, DB-API cursor pattern. Database is PostgreSQL (per
request) via `psycopg2`, which uses the same `execute`/`%s`/`commit` API as the
MySQL connector in the PDF.

## 1. Algorithms ported from the PDFs

| Forex algorithm (PDF) | Formula | QA reinterpretation | Where |
|---|---|---|---|
| `copy_rates_from_pos(sym, TIMEFRAME_D1, …)` → OHLC candles | open = first, high = max, low = min, close = last within each bar | **Metric candles**: daily/weekly/monthly OHLC of test duration or API latency per feature/endpoint. The input for ATR and the candlestick chart. | `forex_core.to_candles` |
| `TIMEFRAME_M1 … MN1` | bar size | Run / day / week / month windows for multi-timeframe analysis | `forex_core.TIMEFRAMES` |
| Spread = ask − bid | difference between two quotes of the same instrument | **Latency spread** = p95 − p50. A wide spread means a heavy tail, even when the median looks healthy. | `forex_core.latency_spread` |
| `cal_profit` / `cal_volume` = `sum(df.profit)`, `sum(df.volume)` | aggregation over open positions | `net_results`: passed, failed, executed counts over a window | `forex_core.net_results` |
| `cal_buy_profit` / `cal_sell_profit` (`df.loc[df.type == 0/1]`) | same sum, split by side | Same aggregation split by **test layer** (UI vs API) | `forex_core.results_by_layer` |
| Margin = notional / leverage | capital locked to hold the exposure | **Coverage margin**: how much automated protection backs a feature's risk exposure. *Coverage leverage* = exposure ÷ coverage. High leverage = a lot of change risk on thin protection. | `forex_core.coverage_leverage` |
| `pct_profit = profit / margin × 100` | return on margin | **Defect yield on coverage** = failures caught per 100 % covered requirements. Shows where the existing tests are actively finding problems. | `forex_core.defect_yield` |
| `draw_grid(levels)` with `price = (pct/10000)·current + current` | ladder of levels at ±1, ±2 … steps around current price | **Alert threshold ladder** around a latency/duration baseline, e.g. +10 %, +20 %, +30 % warning levels. The current value is placed on the ladder. | `forex_core.threshold_ladder` |
| Profit-target loop: `if pct_profit >= target: close_all()` | threshold-triggered action | **Quality gate**: `if signal >= threshold → gate FAIL` for each feature, evaluated over the same loop structure | `forex_core.quality_gate` |
| Position sizing (lot size under a risk limit) | size ∝ risk budget | **Test budget allocation**: split a run-time budget across features in proportion to risk score, with a per-feature floor and cap | `forex_core.allocate_test_budget` |

## 2. Standard indicators (new, not in the PDFs)

All are computed on **daily series** per feature, environment, or endpoint.
Signals used: pass rate, failure rate, test duration, API latency, flakiness.

| Indicator | Standard formula | QA adaptation and why |
|---|---|---|
| **SMA / EMA** | SMA = mean of last n; EMA αₜ = 2/(n+1) | Short (7-day EMA) vs long (28-day SMA) pass rate. Short below long = deteriorating quality; short crossing back above = recovery. |
| **RSI → Failure Pressure Index (FPI)** | Wilder: RS = avg gain / avg loss over 14; RSI = 100 − 100/(1+RS) | Applied to the **daily failure rate**. A "gain" is a day the failure rate increased. FPI > 70 means failure rate increases have dominated recent change; < 30 means sustained recovery. **Adaptation:** RSI measures the consistency of direction, not the level, so 0.5 % → 1 % can score high. FPI is only escalated when the absolute failure rate is also above a floor (default 5 %). |
| **MACD** | EMA12 − EMA26; signal = EMA9 of MACD; histogram = MACD − signal | On pass rate. Histogram turning negative = pass-rate momentum is falling, an early sign of a regression period. Crossovers are logged as reversal events. |
| **Bollinger Bands** | SMA20 ± 2σ | On pass rate and API latency. Points outside the band = unusual results. **Bandwidth** (upper − lower)/mid = instability of a suite or endpoint. |
| **ATR** | TR = max(H − L, \|H − Cₚ\|, \|L − Cₚ\|); ATR = Wilder mean (14) | On the **daily OHLC candles** of duration and latency (§1), so the price formula is not applied blindly to a non-OHLC series. Reported as **ATR %** = ATR / close so features with different absolute durations can be compared. |
| **Momentum / ROC** | xₜ − xₜ₋ₙ | Failure-rate momentum in **percentage points** over 7 days. Percent-ROC is not used on rates because it explodes near 0 % (1 % → 2 % = +100 %). For duration and latency, percent change is used. |
| **Support / resistance** | recurring turning-point levels | From local minima and maxima of the daily failure rate: **support** = the median of trough levels (where failures typically recover to); **resistance** = the median of peak levels (the typical ceiling of past regressions). Only reported with ≥ 3 turning points. |
| **Fibonacci retracement** | 23.6 / 38.2 / 61.8 % ratios | **Not used.** There is no reason failure recovery should stop at Fibonacci ratios. The useful part of the idea is kept as a **recovery ratio** = (peak − current)/(peak − baseline): how much of a regression has been recovered. |
| **Trend reversal** | MA crossover, MACD signal cross, band break | Events: *Regression start* (EMA7 crosses below SMA28 and MACD histogram is negative), *Recovery* (the opposite), *Anomaly* (close outside the Bollinger band). |
| **Multi-timeframe** | same signal on several bar sizes | Pass rate over the last 5 runs, 7 d, 28 d and 90 d, per feature vs the whole app. Classified as *short-term blip*, *chronic*, *improving* or *stable*. |

## 3. Composite: regression risk score

Each component is scaled to 0–1 with fixed caps (e.g. failure rate / 25 %), so
the worst feature is not automatically "high risk" when everything is healthy;
then weighted:

| Component | Source | Weight |
|---|---|---|
| Recent failure rate (7 d) | `net_results` | 0.25 |
| Failure momentum | ROC pp (7 d) + MACD histogram sign | 0.15 |
| Volatility | ATR % of duration + pass-rate Bollinger bandwidth | 0.15 |
| Criticality | feature metadata (1–5) | 0.20 |
| Coverage gap | 1 − requirement coverage | 0.15 |
| Recent change volume | lines changed in 14 d | 0.10 |

Score = 100 × Σ wᵢ·cᵢ. The UI shows every component's contribution, so the
ranking can always be traced back to its evidence.

> **Caveat (shown in the app):** this is a transparent prioritisation
> heuristic. The weights are judgement calls, not fitted or validated
> parameters. Use it to decide where to look first, not as a prediction of
> defects.

## 4. Not carried over

`order_send`, `close_position`, `delete_pending`, account info, and symbol
lists are broker I/O with no QA counterpart. They are dropped.
