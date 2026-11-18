"""Suite analytics: coverage states, use cases, failures, slowest, flaky, sizes."""
import pytest

from data.generator import generate
from engine.analytics import QAAnalytics
from engine.suite import SuiteAnalytics


@pytest.fixture(scope="module")
def suite():
    return SuiteAnalytics(QAAnalytics(generate(seed=42), "day"), window=28)


def test_requirement_states_partition_all_requirements(suite):
    m = suite.summary
    assert m["req_passing"] + m["req_failing"] + m["req_not_executed"] + m["req_not_automated"] == m["req_total"]
    assert m["req_total"] == int(suite.a.features.requirements_count.sum())


def test_use_case_statuses(suite):
    uc = suite.use_cases.set_index("use_case")
    assert uc.loc["Bulk user administration", "status"] == "Not covered"      # no automated steps
    assert uc.loc["Get a refund", "status"] == "Partially covered"
    assert uc.loc["Find and buy a product", "status"] == "Fully covered"
    assert uc.loc["Find and buy a product", "health"] == "Failing"            # planted Checkout regression


def test_feature_coverage_lowest_is_payments(suite):
    assert suite.feature_coverage.iloc[0]["feature"] == "Payments"


def test_top_failures_show_broken_checkout_streak(suite):
    tf = suite.top_failures
    checkout = tf[tf.feature == "Checkout"]
    assert len(checkout) and checkout.streak.max() >= 5 and (checkout.status_now == "FAILED").any()


def test_failure_reasons_group_messages(suite):
    reasons = " | ".join(suite.failure_reasons.reason)
    assert "Timeout #ms exceeded" in reasons and "upstream connect error" in reasons
    assert SuiteAnalytics.normalize_message("h2 heading on qa-practice.com took 1234 ms") == \
        "h2 heading on qa-practice.com took # ms"


def test_slowest_sorted_and_shares_sum_below_one(suite):
    sl = suite.slowest
    assert list(sl.median_s) == sorted(sl.median_s, reverse=True)
    assert 0 < sl.share.sum() <= 1


def test_flaky_and_suite_growth(suite):
    assert (suite.flaky.verdict == "Flaky").sum() >= 4
    assert suite.suite["growth"] > 0 and suite.suite["automated"] + suite.suite["manual"] == suite.suite["total"]


def test_run_duration_stats(suite):
    stats = suite.run_duration_stats()
    assert stats["runs"] == len(suite.runs) and stats["p95"] >= stats["median"] > 0
