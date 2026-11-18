"""Standard technical indicators, adapted to QA time series.

These are NOT in the course PDFs; they are implemented from their standard
formulas. Each function takes a pandas Series indexed by time (one value per
bar, e.g. per day) and returns a Series/DataFrame aligned to the same index.
See MAPPING.md §2 for the QA interpretation of each.
"""
import numpy as np
import pandas as pd


# --- Moving averages ---------------------------------------------------------

def sma(series: pd.Series, n: int) -> pd.Series:
    """Simple moving average. min_periods keeps early bars from being NaN-heavy."""
    return series.rolling(n, min_periods=max(2, n // 2)).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    """Exponential moving average, alpha = 2/(n+1)."""
    return series.ewm(span=n, adjust=False, min_periods=1).mean()


def _wilder(series: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing (alpha = 1/n), used by RSI and ATR."""
    return series.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


# --- RSI → Failure Pressure Index -------------------------------------------

def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI.

    QA use (Failure Pressure Index): feed the daily FAILURE rate. A 'gain' is a
    day where failure rate rose. High values = increases have dominated recent
    change. It measures direction consistency, not level — callers must combine
    it with the absolute failure rate (see analytics.FPI_FLOOR).
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _wilder(gain, n)
    avg_loss = _wilder(loss, n)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    # No losses at all → maximal pressure if there were gains, neutral otherwise.
    out = out.where(avg_loss != 0, np.where(avg_gain > 0, 100.0, 50.0))
    return out


# --- MACD --------------------------------------------------------------------

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line, signal line and histogram.

    QA use: on pass rate. Histogram < 0 means pass-rate momentum is falling.
    """
    line = ema(series, fast) - ema(series, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


# --- Bollinger Bands ---------------------------------------------------------

def bollinger(series: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """Middle = SMA(n), upper/lower = ±k·σ. Bandwidth = (upper-lower)/|mid|.

    QA use: values outside the band are unusual results; bandwidth is a
    stability measure for a suite/endpoint.
    """
    mid = series.rolling(n, min_periods=max(5, n // 2)).mean()
    sd = series.rolling(n, min_periods=max(5, n // 2)).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    bandwidth = (upper - lower) / mid.abs().replace(0, np.nan)
    outside = (series > upper) | (series < lower)
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower,
                         "bandwidth": bandwidth, "outside": outside})


# --- ATR on metric candles --------------------------------------------------

def atr(candles: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range on OHLC candles (columns open/high/low/close).

    QA use: candles are daily OHLC of test duration or API latency
    (see forex_core.to_candles), so true range is meaningful here.
    """
    prev_close = candles["close"].shift(1)
    tr = pd.concat([
        candles["high"] - candles["low"],
        (candles["high"] - prev_close).abs(),
        (candles["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return _wilder(tr, n)


def atr_pct(candles: pd.DataFrame, n: int = 14) -> pd.Series:
    """ATR normalised by close, in % — comparable across features."""
    return 100 * atr(candles, n) / candles["close"].replace(0, np.nan)


# --- Momentum ----------------------------------------------------------------

def momentum_pp(series: pd.Series, n: int = 7) -> pd.Series:
    """Absolute change over n bars. Used for RATES (percentage points), because
    percent-ROC on a rate near 0 explodes (1% → 2% = +100%)."""
    return series - series.shift(n)


def roc_pct(series: pd.Series, n: int = 7) -> pd.Series:
    """Percent rate of change. Used for durations / latency."""
    prev = series.shift(n)
    return 100 * (series - prev) / prev.replace(0, np.nan)


# --- Support / resistance and recovery --------------------------------------

def turning_points(series: pd.Series, window: int = 3):
    """Local minima / maxima using a centred rolling window."""
    s = series.dropna()
    roll_max = s.rolling(2 * window + 1, center=True).max()
    roll_min = s.rolling(2 * window + 1, center=True).min()
    peaks = s[(s == roll_max) & (s > s.median())]
    troughs = s[(s == roll_min) & (s < s.median())]
    return peaks, troughs


def support_resistance(series: pd.Series, window: int = 3, min_points: int = 3):
    """Support = median trough level, resistance = median peak level.

    Returns (support, resistance), each None when there is not enough
    evidence (fewer than min_points turning points) — we do not invent levels.
    """
    peaks, troughs = turning_points(series, window)
    support = float(troughs.median()) if len(troughs) >= min_points else None
    resistance = float(peaks.median()) if len(peaks) >= min_points else None
    return support, resistance


def recovery_ratio(series: pd.Series, lookback: int = 30, baseline_days: int = 28):
    """Share of the most recent regression that has been recovered.

    (peak - current) / (peak - baseline), where peak is the max of the last
    `lookback` bars and baseline is the median of the `baseline_days` before it.
    Replaces Fibonacci retracement: same idea, no magic ratios.
    Returns None if there was no meaningful regression.
    """
    s = series.dropna()
    if len(s) < lookback + 7:
        return None
    recent = s.iloc[-lookback:]
    baseline = float(s.iloc[-(lookback + baseline_days):-lookback].median())
    peak = float(recent.max())
    current = float(s.iloc[-1])
    if peak - baseline < 0.03:          # < 3 pp regression: nothing to recover from
        return None
    return float(np.clip((peak - current) / (peak - baseline), 0.0, 1.0))
