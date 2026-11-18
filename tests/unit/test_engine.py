"""Engine tests: indicator math and detection of the planted demo scenarios."""
import numpy as np
import pandas as pd
import pytest

from data.generator import generate
from engine import forex_core as fx
from engine import indicators as ind
from engine.analytics import QAAnalytics


def series(values):
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values)), dtype=float)


def test_rsi_bounds_and_direction():
    rising = ind.rsi(series(np.linspace(0, 0.5, 40)))
    falling = ind.rsi(series(np.linspace(0.5, 0, 40)))
    assert rising.dropna().between(0, 100).all()
    assert rising.iloc[-1] > 90 and falling.iloc[-1] < 10


def test_atr_uses_true_range():
    c = pd.DataFrame({"open": [10, 10, 10], "high": [11, 11, 20], "low": [9, 9, 19], "close": [10, 10, 19.5]})
    tr_last = max(20 - 19, abs(20 - 10), abs(19 - 10))      # gap up: |high - prev close| dominates
    assert ind.atr(c, n=1).iloc[-1] == pytest.approx(tr_last)


def test_bollinger_flags_outlier():
    s = series([0.97, 0.98] * 15 + [0.70])
    assert bool(ind.bollinger(s).outside.iloc[-1])


def test_support_resistance_needs_evidence():
    assert ind.support_resistance(series([0.02] * 30)) == (None, None)


def test_allocation_respects_budget_floor_and_cap():
    alloc = fx.allocate_test_budget(pd.Series({"a": 90, "b": 5, "c": 5, "d": 0}), 100)
    assert alloc.sum() == pytest.approx(100, abs=0.5)
    assert alloc.min() >= 3 - 1e-9 and alloc.max() <= 35 + 1e-9


def test_threshold_ladder():
    ladder = fx.threshold_ladder(100, 125, step_pct=10, levels=3)
    assert [hit for _, _, hit in ladder] == [True, True, False]


def test_quality_gate():
    assert fx.quality_gate({"fail": 0.2}, {"fail": (">=", 0.1)})
    assert not fx.quality_gate({"fail": 0.05}, {"fail": (">=", 0.1)})


@pytest.fixture(scope="module")
def demo():
    return QAAnalytics(generate(seed=42), "day")


def test_planted_regression_ranks_first(demo):
    top = demo.feature_table.iloc[0]
    assert top.feature == "Checkout" and top.gate


def test_planted_scenarios_produce_insights(demo):
    titles = " | ".join(i.title for i in demo.insights)
    for expected in ("Checkout has increasing failure momentum", "Payments has insufficient automation coverage",
                     "Search has high execution-time volatility", "staging environment",
                     "Reporting has recovered", "flaky test"):
        assert expected in titles, expected


def test_environment_noise_not_reported_as_endpoint_trend(demo):
    flagged = set(demo.endpoint_table[demo.endpoint_table.ladder_level >= 2].feature)
    assert flagged <= {"Checkout", "Notifications"}


def test_sparse_run_mode_does_not_crash():
    g = generate(seed=1)
    keep = g["test_runs"].head(1)
    g["test_runs"] = keep
    g["test_results"] = g["test_results"][g["test_results"].run_id.isin(keep.id)]
    a = QAAnalytics(g, "run")
    assert a.n_bars == 1 and any("warming up" in i.title for i in a.insights)
