"""Print the test-suite analysis in the terminal (or export it as CSV).

    python analyze.py                       # live project, last 10 runs
    python analyze.py --project demo        # synthetic demo project, last 28 days
    python analyze.py --window 30 --csv out # also write every table to out/*.csv
"""
import argparse
from pathlib import Path

import pandas as pd

from data.source import load
from engine.analytics import QAAnalytics
from engine.suite import SuiteAnalytics

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 70)


def section(title, df=None, text=None):
    print(f"\n=== {title} " + "=" * max(0, 70 - len(title)))
    if text:
        print(text)
    if df is not None:
        print("(none)" if df.empty else df.to_string(index=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", choices=["live", "demo"], default="live")
    parser.add_argument("--window", type=int, help="bars (runs for live, days for demo)")
    parser.add_argument("--csv", help="directory to write CSV files to")
    args = parser.parse_args()

    data, msg = load(args.project)
    if data is None:
        raise SystemExit(msg)
    a = QAAnalytics(data, "run" if args.project == "live" else "day")
    s = SuiteAnalytics(a, args.window or (10 if args.project == "live" else 28))
    m = s.summary

    section("Summary", text=(
        f"Suite: {m['suite_total']} test cases ({m['automated']} automated, {m['manual']} manual; "
        f"UI {m['ui_tests']} / API {m['api_tests']})\n"
        f"Requirements: {m['req_total']} — verified {m['req_verified']} (passing {m['req_passing']}, failing "
        f"{m['req_failing']}), not executed {m['req_not_executed']}, not automated {m['req_not_automated']}\n"
        f"Use cases: {m['use_cases']} — fully {m['uc_full']}, partially {m['uc_partial']}, not covered {m['uc_none']}\n"
        f"Runs: {m['runs']} — last {m['last_run_s']:.1f}s, median {m['median_run_s']:.1f}s; last run "
        f"{m['last_passed']} passed / {m['last_failed']} failed / {m['last_skipped']} skipped\n"
        f"Flaky: {m['flaky']} detected, {m['flaky_suspected']} suspected\n"
        f"Window for failures / durations / flakiness: last {s.window_label}"))

    uc = s.use_cases.assign(coverage=lambda d: (d.coverage * 100).round(0).astype("Int64").astype(str) + "%")
    fc = s.feature_coverage.copy()
    for col in ("automated_pct", "verified_pct", "passing_pct"):
        fc[col] = (fc[col] * 100).round(0).astype(int).astype(str) + "%"
    tables = {
        "use_case_coverage": uc[["use_case", "priority", "steps", "verified", "passing", "failing", "coverage",
                                 "status", "gaps"]] if len(uc) else uc,
        "feature_coverage": fc,
        "suite_by_feature": s.suite["by_feature"],
        "run_duration_by_feature": s.duration_by_feature().round(2),
        "top_failures": s.top_failures.assign(fail_rate=lambda d: d.fail_rate.round(2)),
        "failure_reasons": s.failure_reasons,
        "slowest_tests": s.slowest.round({"median_s": 2, "p95_s": 2, "last_s": 2, "share": 3, "change": 2}),
        "flaky_tests": s.flaky.drop(columns="feature_id").round(2),
        "runs": s.runs[["id", "started_at", "environment", "tests", "passed", "failed", "skipped",
                        "duration_s"]].tail(20),
    }
    for name, df in tables.items():
        section(name.replace("_", " ").title(), df)

    if args.csv:
        out = Path(args.csv)
        out.mkdir(parents=True, exist_ok=True)
        for name, df in tables.items():
            df.to_csv(out / f"{name}.csv", index=False)
        print(f"\nCSV files written to {out.resolve()}")


if __name__ == "__main__":
    main()
