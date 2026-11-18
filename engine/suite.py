"""Test-suite analytics: coverage (requirements, features, use cases), suite
size, run duration, flaky tests, top failures and slowest tests.

Builds on QAAnalytics (same results, same bar/window semantics).

Requirement status, from each automated test's most recent result:
  Passing        – automated, executed, all latest executions passed
  Failing        – automated, executed, at least one latest execution failed
  Not executed   – automated, but latest results were skipped / never ran
  Not automated  – no automated test covers it
A requirement is *verified* when it is Passing or Failing (a test really ran).
"""
import re

import numpy as np
import pandas as pd

from engine.analytics import QAAnalytics

REQ_STATES = ["Passing", "Failing", "Not executed", "Not automated"]


class SuiteAnalytics:
    def __init__(self, a: QAAnalytics, window: int = 28):
        self.a = a
        self.window = min(window, a.n_bars)
        self.window_label = a.w(window)
        d = a.data
        self.cases = d["test_cases"].merge(a.features[["name"]].rename(columns={"name": "feature"}),
                                           left_on="feature_id", right_index=True)
        r = a.results
        self.win = a._in_window(r, self.window)            # results inside the analysis window
        self.win_exec = self.win[self.win.is_executed]
        self.latest = r.sort_values("started_at").groupby("test_case_id").tail(1)

        self.requirements = self._requirement_status()
        self.feature_coverage = self._feature_coverage()
        self.use_cases = self._use_case_coverage()
        self.runs = self._runs()
        self.suite = self._suite_size()
        self.flaky = self._flaky()
        self.top_failures = self._top_failures()
        self.failure_reasons = self._failure_reasons()
        self.slowest = self._slowest()
        self.summary = self._summary()

    # ------------------------------------------------------------- coverage
    def _requirements_frame(self) -> pd.DataFrame:
        req = self.a.data.get("requirements")
        if req is not None and len(req):
            return req[["feature_id", "req_no", "description"]].copy()
        # older data without a requirements table: derive numbered requirements
        rows = [(fid, k, f"{f['name']} requirement {k}") for fid, f in self.a.features.iterrows()
                for k in range(1, int(f.requirements_count) + 1)]
        return pd.DataFrame(rows, columns=["feature_id", "req_no", "description"])

    def _requirement_status(self) -> pd.DataFrame:
        req = self._requirements_frame()
        auto = self.cases[self.cases.automated & self.cases.requirement_no.notna()].copy()
        auto["req_no"] = auto["requirement_no"].astype(int)
        last = self.latest.set_index("test_case_id")["status"]
        auto["last_status"] = auto["id"].map(last)
        rows = []
        for (fid, k), g in auto.groupby(["feature_id", "req_no"]):
            executed = g[g.last_status.isin(["PASSED", "FAILED"])]
            if executed.empty:
                state = "Not executed"
            elif (executed.last_status == "FAILED").any():
                state = "Failing"
            else:
                state = "Passing"
            rows.append((fid, k, state, len(g)))
        st = pd.DataFrame(rows, columns=["feature_id", "req_no", "status", "tests"])
        out = req.merge(st, on=["feature_id", "req_no"], how="left")
        out["status"] = out["status"].fillna("Not automated")
        out["tests"] = out["tests"].fillna(0).astype(int)
        out["feature"] = out["feature_id"].map(self.a.features["name"])
        return out

    def _feature_coverage(self) -> pd.DataFrame:
        req = self.requirements
        counts = req.pivot_table(index="feature", columns="status", values="req_no", aggfunc="count",
                                 fill_value=0).reindex(columns=REQ_STATES, fill_value=0)
        counts["total"] = counts.sum(axis=1)
        counts["automated_pct"] = (counts.total - counts["Not automated"]) / counts.total
        counts["verified_pct"] = (counts.Passing + counts.Failing) / counts.total
        counts["passing_pct"] = counts.Passing / counts.total
        crit = self.a.features.set_index("name")["criticality"]
        counts["criticality"] = crit.reindex(counts.index).astype(int)
        return counts.sort_values(["verified_pct", "criticality"], ascending=[True, False]).reset_index()

    def _use_case_coverage(self) -> pd.DataFrame:
        d = self.a.data
        uc, steps = d.get("use_cases"), d.get("use_case_steps")
        cols = ["use_case", "priority", "steps", "verified", "passing", "failing", "not_executed",
                "not_automated", "coverage", "status", "health", "gaps"]
        if uc is None or steps is None or uc.empty or steps.empty:
            return pd.DataFrame(columns=cols)
        req_ids = d["requirements"][["id", "feature_id", "req_no"]]
        s = steps.merge(req_ids, left_on="requirement_id", right_on="id", suffixes=("", "_req"))
        s = s.merge(self.requirements, on=["feature_id", "req_no"])
        rows = []
        for uid, g in s.groupby("use_case_id"):
            u = uc[uc.id == uid].iloc[0]
            n = len(g)
            c = g.status.value_counts()
            verified = c.get("Passing", 0) + c.get("Failing", 0)
            status = "Fully covered" if verified == n else "Not covered" if verified == 0 else "Partially covered"
            health = "Failing" if c.get("Failing", 0) else ("Passing" if verified else "—")
            gaps = "; ".join(f"{r.feature} #{r.req_no} ({r.status.lower()})"
                             for r in g.sort_values("step_no").itertuples() if r.status not in ("Passing", "Failing"))
            rows.append((u["name"], int(u.priority), n, verified, c.get("Passing", 0), c.get("Failing", 0),
                         c.get("Not executed", 0), c.get("Not automated", 0), verified / n, status, health, gaps))
        out = pd.DataFrame(rows, columns=cols)
        return out.sort_values(["coverage", "priority"], ascending=[True, False]).reset_index(drop=True)

    # --------------------------------------------------------------- runs
    def _runs(self) -> pd.DataFrame:
        a = self.a
        runs = a.data["test_runs"].copy()
        per_run = a.results.groupby("run_id").agg(
            tests=("test_case_id", "nunique"), executed=("is_executed", "sum"), failed=("is_failed", "sum"),
            test_ms=("duration_ms", "sum"))
        runs = runs.merge(per_run, left_on="id", right_index=True)
        if "duration_ms" not in runs:
            runs["duration_ms"] = np.nan
        runs["duration_s"] = runs["duration_ms"].fillna(runs["test_ms"]) / 1000.0
        runs["environment"] = runs["environment_id"].map(a.envs["name"])
        runs["passed"] = runs["executed"] - runs["failed"]
        runs["skipped"] = runs["tests"] - runs["executed"]
        runs["bar"] = runs["started_at"].dt.normalize() if a.mode == "day" else runs["started_at"]
        return runs.sort_values("started_at").reset_index(drop=True)

    def run_duration_stats(self, env_id=None) -> dict:
        r = self.runs if env_id is None else self.runs[self.runs.environment_id == env_id]
        if r.empty:
            return {}
        recent, before = r.duration_s.tail(5), r.duration_s.iloc[:-5].tail(30)
        trend = (recent.median() / before.median() - 1) if len(before) else np.nan
        return {"last": float(r.duration_s.iloc[-1]), "median": float(r.duration_s.median()),
                "p95": float(r.duration_s.quantile(0.95)), "trend": float(trend), "runs": len(r)}

    def duration_by_feature(self) -> pd.DataFrame:
        """Average seconds each feature adds to a run, over the window."""
        w = self.win_exec
        if w.empty:
            return pd.DataFrame(columns=["feature", "seconds_per_run", "share"])
        per = w.groupby("feature_id")["duration_ms"].sum() / w.run_id.nunique() / 1000.0
        out = pd.DataFrame({"feature": per.index.map(self.a.features["name"]), "seconds_per_run": per.values})
        out["share"] = out.seconds_per_run / out.seconds_per_run.sum()
        return out.sort_values("seconds_per_run", ascending=False).reset_index(drop=True)

    def execution_status(self, max_bars: int = 30) -> pd.DataFrame:
        """Passed / failed / skipped counts per period: per week (day mode) or per run."""
        r = self.a.results
        if self.a.mode == "day":
            key = r["started_at"].dt.to_period("W-SUN").dt.start_time
            max_bars = 13
        else:
            key = r["started_at"]
        out = r.groupby([key, "status"]).size().unstack(fill_value=0)
        out = out.reindex(columns=["PASSED", "FAILED", "SKIPPED"], fill_value=0)
        return out.tail(max_bars)

    # ---------------------------------------------------------- suite size
    def _suite_size(self) -> dict:
        c = self.cases
        auto = c[c.automated]
        by_feature = (c.assign(kind=np.where(c.automated, "automated", "manual"))
                      .pivot_table(index="feature", columns="kind", values="id", aggfunc="count", fill_value=0)
                      .reindex(columns=["automated", "manual"], fill_value=0))
        by_feature["total"] = by_feature.sum(axis=1)
        history = self.runs.set_index("started_at")["tests"]
        first_seen = self.a.results.groupby("test_case_id")["started_at"].min()
        # "new" = first executed inside the window, but after the very first run
        cut = self.a._cutoff(self.window)[0]
        first_run = self.a.results["started_at"].min()
        new_ids = first_seen[(first_seen >= cut) & (first_seen > first_run)].index
        new_tests = c[c.id.isin(new_ids)][["name", "feature", "layer"]]
        return {
            "total": len(c), "automated": len(auto), "manual": int((~c.automated).sum()),
            "automation_rate": len(auto) / len(c) if len(c) else np.nan,
            "ui": int((auto.layer == "UI").sum()), "api": int((auto.layer == "API").sum()),
            "by_feature": by_feature.sort_values("total", ascending=False).reset_index(),
            "history": history, "new_tests": new_tests,
            "growth": int(history.iloc[-1] - history.iloc[0]) if len(history) else 0,
        }

    # -------------------------------------------------------------- flaky
    def _flaky(self) -> pd.DataFrame:
        detected = self.a.flaky
        rows = [(r.name, r.feature_id, int(min(40, (self.a.results.test_case_id == r.test_case_id).sum())),
                 r.flip_rate, r.fail_share, "Flaky") for r in detected[detected.flaky].itertuples()]
        # suspects: alternating results, but not enough executions yet to confirm
        r = self.a.results[self.a.results.is_executed]
        known = set(detected.test_case_id)
        for tid, g in r.groupby("test_case_id"):
            if tid in known:
                continue
            f = g["is_failed"].to_numpy()
            if len(f) >= 2 and (f[1:] != f[:-1]).any() and f.mean() <= 0.7:
                rows.append((g["name"].iloc[0], int(g["feature_id"].iloc[0]), len(f),
                             float((f[1:] != f[:-1]).mean()), float(f.mean()), "Suspected (needs ≥10 runs)"))
        out = pd.DataFrame(rows, columns=["test", "feature_id", "executions", "flip_rate", "fail_share", "verdict"])
        out["feature"] = out["feature_id"].map(self.a.features["name"])
        return out.sort_values(["verdict", "flip_rate"], ascending=[True, False]).reset_index(drop=True)

    # ------------------------------------------------------------ failures
    def _top_failures(self, n: int = 15) -> pd.DataFrame:
        w = self.win_exec
        cols = ["test", "feature", "layer", "failures", "executions", "fail_rate", "streak", "last_failed",
                "last_message", "status_now"]
        if w.empty or not w.is_failed.any():
            return pd.DataFrame(columns=cols)
        rows = []
        all_exec = self.a.results[self.a.results.is_executed]
        for tid, g in w.groupby("test_case_id"):
            fails = g[g.is_failed]
            if fails.empty:
                continue
            hist = all_exec[all_exec.test_case_id == tid]["is_failed"].to_numpy()[::-1]
            streak = int(np.argmin(hist)) if not hist.all() else len(hist)    # consecutive failures at the end
            rows.append((g["name"].iloc[0], self.a.features.loc[g.feature_id.iloc[0], "name"], g.layer.iloc[0],
                         len(fails), len(g), len(fails) / len(g), streak, fails.started_at.max(),
                         fails.sort_values("started_at")["message"].iloc[-1], "FAILED" if hist[0] else "PASSED"))
        out = pd.DataFrame(rows, columns=cols)
        return out.sort_values(["failures", "fail_rate"], ascending=False).head(n).reset_index(drop=True)

    @staticmethod
    def normalize_message(msg) -> str:
        if msg is None or (isinstance(msg, float) and np.isnan(msg)) or not str(msg).strip():
            return "(no message)"
        m = str(msg).strip().splitlines()[0]
        m = re.sub(r"'[^']*'|\"[^\"]*\"", "'…'", m)
        m = re.sub(r"\{[^}]*\}|\[[^\]]*\]", "{…}", m)
        m = re.sub(r"(?<![A-Za-z])\d+", "#", m)      # numbers, but keep names like "h2" or "utf8"
        return m[:110]

    def _failure_reasons(self, n: int = 10) -> pd.DataFrame:
        f = self.win_exec[self.win_exec.is_failed]
        cols = ["reason", "occurrences", "tests", "features", "last_seen"]
        if f.empty:
            return pd.DataFrame(columns=cols)
        f = f.assign(reason=f["message"].map(self.normalize_message))
        g = f.groupby("reason").agg(occurrences=("id", "size"), tests=("test_case_id", "nunique"),
                                    features=("feature_id", lambda s: ", ".join(
                                        sorted(self.a.features.loc[s.unique(), "name"]))),
                                    last_seen=("started_at", "max"))
        return g.sort_values("occurrences", ascending=False).head(n).reset_index()

    # ------------------------------------------------------------- slowest
    def _slowest(self, n: int = 15) -> pd.DataFrame:
        w = self.win_exec
        cols = ["test", "feature", "layer", "median_s", "p95_s", "last_s", "runs", "share", "change"]
        if w.empty:
            return pd.DataFrame(columns=cols)
        total = w.duration_ms.sum()
        recent_cut = self.a._cutoff(7)[0]
        rows = []
        for tid, g in w.groupby("test_case_id"):
            d = g.duration_ms / 1000.0
            recent, base = d[g.bar >= recent_cut], d[g.bar < recent_cut]
            change = (recent.median() / base.median() - 1) if len(recent) and len(base) else np.nan
            rows.append((g["name"].iloc[0], self.a.features.loc[g.feature_id.iloc[0], "name"], g.layer.iloc[0],
                         d.median(), d.quantile(0.95), d.iloc[-1], len(g), g.duration_ms.sum() / total, change))
        out = pd.DataFrame(rows, columns=cols)
        return out.sort_values("median_s", ascending=False).head(n).reset_index(drop=True)

    # ------------------------------------------------------------- summary
    def _summary(self) -> dict:
        req = self.requirements.status.value_counts()
        total_req = len(self.requirements)
        uc = self.use_cases.status.value_counts()
        last = self.runs.iloc[-1]
        stats = self.run_duration_stats()
        return {
            "suite_total": self.suite["total"], "automated": self.suite["automated"], "manual": self.suite["manual"],
            "automation_rate": self.suite["automation_rate"], "ui_tests": self.suite["ui"],
            "api_tests": self.suite["api"],
            "req_total": total_req, "req_verified": int(req.get("Passing", 0) + req.get("Failing", 0)),
            "req_passing": int(req.get("Passing", 0)), "req_failing": int(req.get("Failing", 0)),
            "req_not_executed": int(req.get("Not executed", 0)), "req_not_automated": int(req.get("Not automated", 0)),
            "use_cases": len(self.use_cases), "uc_full": int(uc.get("Fully covered", 0)),
            "uc_partial": int(uc.get("Partially covered", 0)), "uc_none": int(uc.get("Not covered", 0)),
            "runs": len(self.runs), "last_run_s": stats.get("last"), "median_run_s": stats.get("median"),
            "run_trend": stats.get("trend"), "last_passed": int(last.passed), "last_failed": int(last.failed),
            "last_skipped": int(last.skipped), "flaky": int((self.flaky.verdict == "Flaky").sum()),
            "flaky_suspected": int((self.flaky.verdict != "Flaky").sum()),
        }
