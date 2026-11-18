"""Deterministic synthetic QA history for demos and tests.

Planted scenarios (so the indicators can be checked against a known truth):
  * Checkout        – regression starting ~11 days ago, tests break one by one;
                      heavy recent code churn.
  * Reporting       – regression ~40-22 days ago, since recovered.
  * Search          – high execution-time and latency volatility.
  * Payments        – critical feature with thin automation coverage.
  * Inventory Sync  – flaky tests (random ~30% failures).
  * Notifications   – API latency drifting upward over the last 30 days.
  * staging env     – becomes unstable in the last 7 days.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from config import HISTORY_DAYS

FEATURES = [
    # name, criticality, requirements, automated tests (UI, API), coverage share
    ("Login & Auth",    5, 18, (5, 7), 0.90),
    ("Checkout",        5, 22, (6, 8), 0.80),
    ("Payments",        5, 30, (2, 4), 0.30),
    ("Search",          3, 14, (4, 6), 0.75),
    ("Product Catalog", 3, 16, (4, 5), 0.70),
    ("User Profile",    2, 10, (3, 3), 0.80),
    ("Notifications",   2, 12, (2, 4), 0.60),
    ("Reporting",       3, 15, (4, 4), 0.65),
    ("Admin Console",   2, 12, (3, 2), 0.50),
    ("Inventory Sync",  4, 14, (2, 6), 0.70),
]
ENVIRONMENTS = [("dev", 3), ("qa", 2), ("staging", 1)]   # runs per day
ENDPOINTS = {
    "Login & Auth": [("POST", "/api/auth/login"), ("POST", "/api/auth/refresh")],
    "Checkout": [("POST", "/api/cart/checkout"), ("GET", "/api/cart")],
    "Payments": [("POST", "/api/payments/charge"), ("POST", "/api/payments/refund")],
    "Search": [("GET", "/api/search"), ("GET", "/api/search/suggest")],
    "Product Catalog": [("GET", "/api/products"), ("GET", "/api/products/{id}")],
    "User Profile": [("GET", "/api/users/me")],
    "Notifications": [("GET", "/api/notifications"), ("POST", "/api/notifications/send")],
    "Reporting": [("GET", "/api/reports/sales")],
    "Admin Console": [("GET", "/api/admin/users")],
    "Inventory Sync": [("POST", "/api/inventory/sync")],
}


USE_CASES = [
    # name, priority, [(feature, requirement no.), ...]
    ("Sign up and sign in", 5, [("Login & Auth", 1), ("Login & Auth", 2), ("Login & Auth", 3),
                                ("Login & Auth", 17), ("User Profile", 1)]),
    ("Find and buy a product", 5, [("Search", 1), ("Search", 2), ("Product Catalog", 1), ("Product Catalog", 3),
                                   ("Checkout", 1), ("Checkout", 2), ("Checkout", 5), ("Payments", 1),
                                   ("Payments", 2)]),
    ("Get a refund", 4, [("Payments", 8), ("Payments", 13), ("Payments", 14), ("Notifications", 3)]),
    ("Restock from supplier feed", 4, [("Inventory Sync", 1), ("Inventory Sync", 2), ("Inventory Sync", 3),
                                       ("Product Catalog", 5)]),
    ("Monthly sales report", 3, [("Reporting", 1), ("Reporting", 2), ("Reporting", 3), ("Admin Console", 2)]),
    ("Manage account preferences", 2, [("User Profile", 2), ("User Profile", 3), ("Notifications", 1),
                                       ("Notifications", 2)]),
    ("Bulk user administration", 2, [("Admin Console", 8), ("Admin Console", 9), ("Admin Console", 10),
                                     ("Login & Auth", 18)]),
]
NOISE_MESSAGES = ["AssertionError: expected element to be visible",
                  "TimeoutError: page.goto: Timeout 45000ms exceeded",
                  "AssertionError: expected text 'Saved' but got ''"]


def generate(seed: int = 42, days: int = HISTORY_DAYS, end: datetime = None) -> dict:
    rng = np.random.default_rng(seed)
    end = (end or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days - 1)
    last = days - 1                                    # index of "today"

    # --- features, environments ---------------------------------------------
    features = pd.DataFrame(
        [(i + 1, n, c, r) for i, (n, c, r, _, _) in enumerate(FEATURES)],
        columns=["id", "name", "criticality", "requirements_count"])
    fid = dict(zip(features.name, features.id))
    environments = pd.DataFrame([(i + 1, n) for i, (n, _) in enumerate(ENVIRONMENTS)],
                                columns=["id", "name"])
    env_id = dict(zip(environments.name, environments.id))

    # --- requirements and use cases -----------------------------------------
    requirements = pd.DataFrame(
        [(fid[n], k, f"{n} requirement {k}") for n, _, reqs, _, _ in FEATURES for k in range(1, reqs + 1)],
        columns=["feature_id", "req_no", "description"])
    requirements.insert(0, "id", np.arange(1, len(requirements) + 1))
    req_id = {(f, k): i for i, f, k in zip(requirements.id, requirements.feature_id, requirements.req_no)}
    use_cases = pd.DataFrame([(i + 1, n, p, None) for i, (n, p, _) in enumerate(USE_CASES)],
                             columns=["id", "name", "priority", "description"])
    steps = [(uc + 1, s + 1, req_id[(fid[f], k)]) for uc, (_, _, st) in enumerate(USE_CASES)
             for s, (f, k) in enumerate(st)]
    use_case_steps = pd.DataFrame(steps, columns=["use_case_id", "step_no", "requirement_id"])
    use_case_steps.insert(0, "id", np.arange(1, len(use_case_steps) + 1))

    # --- test cases (automated + some manual, uncovered requirements) -------
    cases = []
    for name, _, reqs, (n_ui, n_api), cov in FEATURES:
        covered = max(1, round(reqs * cov))
        req_pool = list(range(1, covered + 1))
        for layer, n in (("UI", n_ui), ("API", n_api)):
            for k in range(n):
                cases.append((fid[name], f"{name} – {layer} #{k + 1}", layer,
                              req_pool[(len(cases) + k) % len(req_pool)], True))
        # each covered requirement gets at least one automated test
        for r in req_pool:
            if not any(c[0] == fid[name] and c[3] == r and c[4] for c in cases):
                cases.append((fid[name], f"{name} – API req {r}", "API", r, True))
        # two manual (non-automated) cases per feature: they don't count as coverage
        for k in range(2):
            cases.append((fid[name], f"{name} – manual #{k + 1}", "UI", None, False))
    test_cases = pd.DataFrame(cases, columns=["feature_id", "name", "layer", "requirement_no", "automated"])
    test_cases.insert(0, "id", np.arange(1, len(test_cases) + 1))
    test_cases["requirement_no"] = test_cases["requirement_no"].astype("Int64")
    auto = test_cases[test_cases.automated].reset_index(drop=True)

    # per-test behaviour
    base_dur = np.where(auto.layer == "UI", rng.uniform(15_000, 90_000, len(auto)),
                        rng.uniform(300, 3_000, len(auto)))
    dur_sigma = np.full(len(auto), 0.08)
    fail_p = np.full(len(auto), 0.006)
    feat_name = auto.feature_id.map(dict(zip(features.id, features.name))).to_numpy()
    dur_sigma[feat_name == "Search"] = 0.45
    fail_p[feat_name == "Search"] = 0.02

    def pick(feature, n):
        return list(auto.index[feat_name == feature][:n])

    flaky = pick("Inventory Sync", 3) + pick("Search", 1)[:1] + pick("Login & Auth", 1)
    fail_p[flaky] = 0.30
    breaks = []  # (test idx, start day, end day exclusive)
    for idx, day in zip(pick("Checkout", 5), [last - 10, last - 7, last - 5, last - 3, last - 1]):
        breaks.append((idx, day, days + 1))
    for idx, (s, e) in zip(pick("Reporting", 4), [(last - 40, last - 28), (last - 38, last - 25),
                                                  (last - 36, last - 23), (last - 35, last - 22)]):
        breaks.append((idx, s, e))
    flaky_mask = np.zeros(len(auto), dtype=bool)
    flaky_mask[flaky] = True
    # the suite grows: some later tests in each feature were added during the period
    pos_in_feature = auto.groupby("feature_id").cumcount().to_numpy()
    start_day = np.where((pos_in_feature >= 5) & (rng.random(len(auto)) < 0.35),
                         rng.integers(15, last - 5, len(auto)), 0)

    # --- runs and results ----------------------------------------------------
    runs, results = [], []
    run_id, result_id, build = 0, 0, 1000
    for d in range(days):
        day = start + timedelta(days=d)
        build += 1
        for env, per_day in ENVIRONMENTS:
            for k in range(per_day):
                run_id += 1
                started = day + timedelta(hours=int(2 + k * 7 + rng.integers(0, 3)),
                                          minutes=int(rng.integers(0, 60)))
                p = fail_p.copy()
                broken = np.zeros(len(auto), dtype=bool)
                for idx, s, e in breaks:
                    if s <= d < e:
                        p[idx] = 0.92
                        broken[idx] = True
                dur = base_dur * rng.lognormal(0, dur_sigma)
                spikes = (feat_name == "Search") & (rng.random(len(auto)) < 0.05)
                dur[spikes] *= rng.uniform(2, 4, spikes.sum())
                unstable_env = env == "staging" and d > last - 7
                if unstable_env:
                    p = p + 0.10
                    dur *= 1.35
                status = np.where(rng.random(len(auto)) < p, "FAILED", "PASSED").astype(object)
                status[rng.random(len(auto)) < 0.008] = "SKIPPED"
                active = start_day <= d
                for i in np.flatnonzero(active):
                    result_id += 1
                    msg = None
                    if status[i] == "FAILED":
                        if broken[i]:
                            msg = f"AssertionError: expected HTTP 200 from {feat_name[i]} API but got 500"
                        elif flaky_mask[i]:
                            msg = "TimeoutError: locator.click: Timeout 30000ms exceeded"
                        elif unstable_env:
                            msg = "ConnectionError: upstream connect error or disconnect (503)"
                        else:
                            msg = NOISE_MESSAGES[rng.integers(len(NOISE_MESSAGES))]
                    results.append((result_id, run_id, int(auto.id[i]), status[i], int(dur[i]), msg))
                run_ms = int(dur[active].sum() * 1.04 + 20_000)
                runs.append((run_id, started, env_id[env], build, run_ms))
    test_runs = pd.DataFrame(runs, columns=["id", "started_at", "environment_id", "build_number", "duration_ms"])
    test_results = pd.DataFrame(results, columns=["id", "run_id", "test_case_id", "status", "duration_ms",
                                                  "message"])

    # --- API endpoints and latency samples (every 2h per env) ----------------
    eps = [(fid[f], m, p) for f, lst in ENDPOINTS.items() for m, p in lst]
    api_endpoints = pd.DataFrame(eps, columns=["feature_id", "method", "path"])
    api_endpoints.insert(0, "id", np.arange(1, len(api_endpoints) + 1))
    ep_feat = api_endpoints.feature_id.map(dict(zip(features.id, features.name))).to_numpy()
    ep_base = rng.uniform(60, 350, len(api_endpoints))
    ep_sigma = np.where(ep_feat == "Search", 0.55, 0.18)
    metrics, mid = [], 0
    for d in range(days):
        for env, _ in ENVIRONMENTS:
            factor = np.ones(len(api_endpoints))
            if env == "staging" and d > last - 7:
                factor *= 1.6
            drift = (ep_feat == "Notifications") & (d > last - 30)
            factor[drift] *= 1 + 0.025 * (d - (last - 30))
            factor[ep_feat == "Checkout"] *= 1.4 if d > last - 10 else 1.0
            for h in range(0, 24, 2):
                ts = start + timedelta(days=d, hours=h, minutes=int(rng.integers(0, 60)))
                lat = ep_base * factor * rng.lognormal(0, ep_sigma)
                err_p = 0.004 + (0.05 if env == "staging" and d > last - 7 else 0)
                codes = np.where(rng.random(len(api_endpoints)) < err_p, 500, 200)
                for e in range(len(api_endpoints)):
                    mid += 1
                    metrics.append((mid, int(api_endpoints.id[e]), env_id[env], ts,
                                    round(float(lat[e]), 1), int(codes[e])))
    api_metrics = pd.DataFrame(metrics, columns=["id", "endpoint_id", "environment_id",
                                                 "measured_at", "latency_ms", "status_code"])

    # --- code changes --------------------------------------------------------
    changes, cid = [], 0
    for d in range(days):
        for name, *_ in FEATURES:
            rate = 0.4
            if name == "Checkout" and d > last - 14:
                rate = 3.0
            elif name == "Reporting" and last - 44 < d < last - 34:
                rate = 2.0
            elif name in ("Search", "Payments"):
                rate = 0.8
            for _ in range(rng.poisson(rate)):
                cid += 1
                changes.append((cid, fid[name], start + timedelta(days=d, hours=int(rng.integers(8, 19))),
                                int(rng.integers(5, 400))))
    code_changes = pd.DataFrame(changes, columns=["id", "feature_id", "changed_at", "lines_changed"])

    return {"features": features, "environments": environments, "requirements": requirements,
            "use_cases": use_cases, "use_case_steps": use_case_steps, "test_cases": test_cases,
            "test_runs": test_runs, "test_results": test_results, "api_endpoints": api_endpoints,
            "api_metrics": api_metrics, "code_changes": code_changes}
