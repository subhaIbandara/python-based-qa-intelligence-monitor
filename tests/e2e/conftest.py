"""Fixtures and result recording for the target-site suite.

Every test carries @pytest.mark.qa(feature, requirement_no, layer). At the end of
the session all outcomes, durations and timings are written to PostgreSQL
(schema `live`), and the dashboard picks them up on its next refresh.

Environment variables:
  QA_BASE_URL   site under test           (default https://www.qa-practice.com, see config.py)
  QA_ENV_NAME   environment label          (default production)
  QA_RECORD     set to 0 to skip recording (default 1)
  BUILD_NUMBER  CI build number            (default: previous + 1)
"""
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config import QA_BASE_URL  # noqa: E402
from tests.e2e.catalog import FEATURES, USE_CASES  # noqa: E402

BASE_URL = QA_BASE_URL
_BASE = urlparse(BASE_URL)
# Third-party analytics are blocked in the browser so test traffic doesn't skew the site's stats.
TRACKERS = re.compile(r"https?://([^/]+\.)?(google-analytics|googletagmanager|doubleclick)\.(com|net)/")
CHALLENGE_TITLES = ("just a moment", "attention required")
BOT_BLOCK_REASON = ("Blocked by bot protection (Cloudflare managed challenge) — the browser never reached "
                    "the page. Allowlist the test runner or use QA_BASE_URL for an unprotected host.")

_results, _metrics = [], []
_session_start = datetime.now()


def pytest_configure(config):
    config.addinivalue_line("markers", "qa(feature, req, layer): map a test to a catalog requirement")


# ------------------------------------------------------------------ fixtures
@pytest.fixture(scope="session")
def base_url_str():
    return BASE_URL


@pytest.fixture(scope="session")
def http(playwright):
    ctx = playwright.request.new_context(base_url=BASE_URL, timeout=30_000)
    yield ctx
    ctx.dispose()


class TimedHttp:
    """Wraps APIRequestContext: every request's latency/status is recorded
    against the calling test's feature."""

    def __init__(self, ctx, feature):
        self.ctx, self.feature = ctx, feature

    def get(self, path, **kwargs):
        start = time.perf_counter()
        resp = self.ctx.get(path, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000
        parsed = urlparse(path)
        label = parsed.path or "/"            # same-origin URLs are labelled by path
        if parsed.scheme and (parsed.scheme, parsed.netloc) != (_BASE.scheme, _BASE.netloc):
            label = f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}"
        _metrics.append({"feature": self.feature, "method": "GET", "path": label, "latency_ms": elapsed,
                         "status_code": resp.status, "measured_at": datetime.now()})
        resp.elapsed_ms = elapsed
        return resp


def _qa(request):
    marker = request.node.get_closest_marker("qa")
    if marker is None:
        raise pytest.UsageError(f"{request.node.nodeid} is missing @pytest.mark.qa(feature, req, layer)")
    return marker.args


@pytest.fixture
def api(http, request):
    feature, _, _ = _qa(request)
    return TimedHttp(http, feature)


@pytest.fixture
def site(page, request):
    """Open a path in the browser. Records page-load time; skips (not fails)
    when bot protection serves a challenge instead of the site."""
    feature, _, _ = _qa(request)
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.context.route(TRACKERS, lambda route: route.abort())   # also covers tabs the test opens

    def open_path(path="/"):
        resp = page.goto(BASE_URL + path, wait_until="load", timeout=45_000)
        title = page.title().lower()
        if any(t in title for t in CHALLENGE_TITLES) or (resp and resp.headers.get("cf-mitigated") == "challenge"):
            pytest.skip(BOT_BLOCK_REASON)
        timing = page.evaluate("() => { const n = performance.getEntriesByType('navigation')[0];"
                               " return n ? n.loadEventEnd : null; }")
        if timing:
            _metrics.append({"feature": feature, "method": "PAGE", "path": path, "latency_ms": timing,
                             "status_code": resp.status if resp else 0, "measured_at": datetime.now()})
        return resp

    open_path.errors = errors
    return open_path


# ------------------------------------------------------------- result hooks
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    marker = item.get_closest_marker("qa")
    if marker is None:
        return
    store = item.stash.setdefault(_KEY, {"duration": 0.0, "status": "PASSED", "message": None})
    store["duration"] += report.duration
    if report.skipped and store["status"] == "PASSED":
        store["status"] = "SKIPPED"
        store["message"] = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
    elif report.failed:
        store["status"] = "FAILED"
        store["message"] = _first_line(report)
    if report.when == "teardown":
        feature, req, layer = marker.args
        _results.append({"feature": feature, "req": req, "layer": layer,
                         "name": item.nodeid.split("::", 1)[-1], "status": store["status"],
                         "duration_ms": store["duration"] * 1000, "message": (store["message"] or "")[:500]})


_KEY = pytest.StashKey[dict]()


def _first_line(report):
    text = getattr(report, "longreprtext", "") or str(report.longrepr)
    for line in text.splitlines():
        if line.startswith("E "):
            return line[2:].strip()
    return text.strip().splitlines()[-1] if text.strip() else "failed"


def pytest_sessionfinish(session, exitstatus):
    if not _results or os.environ.get("QA_RECORD", "1") == "0":
        return
    from db.recorder import record_run
    build = os.environ.get("BUILD_NUMBER")
    wall_ms = int((datetime.now() - _session_start).total_seconds() * 1000)
    try:
        summary = record_run(_session_start, os.environ.get("QA_ENV_NAME", "production"), FEATURES,
                             _results, _metrics, int(build) if build else None,
                             use_cases=USE_CASES, duration_ms=wall_ms)
        msg = (f"QA recorder: run #{summary['run_id']} (build {summary['build']}) saved — "
               f"{summary['passed']} passed, {summary['failed']} failed, {summary['skipped']} skipped, "
               f"{summary['metrics']} timings")
    except Exception as err:  # noqa: BLE001 — never hide test results because recording failed
        msg = f"QA recorder: could not save results to PostgreSQL ({str(err).splitlines()[0]})"
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter:
        reporter.write_line(msg)
