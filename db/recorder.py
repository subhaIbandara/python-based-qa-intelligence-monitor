"""Writes one pytest session (a test run) into the `live` project schema."""
from datetime import datetime

from db.repository import connect, create_schema, use_schema


def record_run(started_at: datetime, environment: str, catalog: dict, results: list, metrics: list,
               build_number: int = None, use_cases: dict = None, duration_ms: int = None) -> dict:
    """
    catalog:   {feature: (criticality, {req_no: (layer, description, automated)})}
    use_cases: {name: (priority, description, [(feature, req_no), ...])}
    results:   [{feature, name, layer, req, status, duration_ms, message}]
    metrics:   [{feature, method, path, latency_ms, status_code, measured_at}]
    """
    conn = connect()
    try:
        create_schema(conn, "live")
        with conn.cursor() as cur:
            use_schema(cur, "live")
            cur.execute("""INSERT INTO environments (name) VALUES (%s)
                           ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id""", (environment,))
            env_id = cur.fetchone()[0]

            feature_ids = {}
            for name, (criticality, reqs) in catalog.items():
                cur.execute("""INSERT INTO features (name, criticality, requirements_count) VALUES (%s, %s, %s)
                               ON CONFLICT (name) DO UPDATE SET criticality = EXCLUDED.criticality,
                                   requirements_count = EXCLUDED.requirements_count
                               RETURNING id""", (name, criticality, len(reqs)))
                feature_ids[name] = cur.fetchone()[0]
                for req_no, (layer, description, automated) in reqs.items():
                    cur.execute("""INSERT INTO requirements (feature_id, req_no, description) VALUES (%s, %s, %s)
                                   ON CONFLICT (feature_id, req_no) DO UPDATE SET description = EXCLUDED.description
                                   """, (feature_ids[name], req_no, description[:300]))
                    if not automated:
                        _upsert_case(cur, feature_ids[name], f"[manual] {description}", layer, req_no, False)

            for uc_name, (priority, description, steps) in (use_cases or {}).items():
                cur.execute("""INSERT INTO use_cases (name, priority, description) VALUES (%s, %s, %s)
                               ON CONFLICT (name) DO UPDATE SET priority = EXCLUDED.priority,
                                   description = EXCLUDED.description RETURNING id""",
                            (uc_name, priority, description))
                uc_id = cur.fetchone()[0]
                cur.execute("DELETE FROM use_case_steps WHERE use_case_id = %s", (uc_id,))
                for step_no, (feature, req_no) in enumerate(steps, start=1):
                    cur.execute("""INSERT INTO use_case_steps (use_case_id, step_no, requirement_id)
                                   SELECT %s, %s, id FROM requirements WHERE feature_id = %s AND req_no = %s""",
                                (uc_id, step_no, feature_ids[feature], req_no))

            if build_number is None:
                cur.execute("SELECT COALESCE(MAX(build_number), 0) + 1 FROM test_runs")
                build_number = cur.fetchone()[0]
            cur.execute("INSERT INTO test_runs (started_at, environment_id, build_number, duration_ms) "
                        "VALUES (%s, %s, %s, %s) RETURNING id", (started_at, env_id, build_number, duration_ms))
            run_id = cur.fetchone()[0]

            for r in results:
                case_id = _upsert_case(cur, feature_ids[r["feature"]], r["name"], r["layer"], r["req"], True)
                cur.execute("""INSERT INTO test_results (run_id, test_case_id, status, duration_ms, message)
                               VALUES (%s, %s, %s, %s, %s)""",
                            (run_id, case_id, r["status"], int(r["duration_ms"]), (r.get("message") or None)))

            for m in metrics:
                cur.execute("""INSERT INTO api_endpoints (feature_id, method, path) VALUES (%s, %s, %s)
                               ON CONFLICT (method, path) DO UPDATE SET method = EXCLUDED.method
                               RETURNING id""", (feature_ids[m["feature"]], m["method"], m["path"]))
                # (no-op update: an endpoint keeps the feature that first exercised it)
                ep_id = cur.fetchone()[0]
                cur.execute("""INSERT INTO api_metrics (endpoint_id, environment_id, measured_at, latency_ms,
                               status_code) VALUES (%s, %s, %s, %s, %s)""",
                            (ep_id, env_id, m["measured_at"], float(m["latency_ms"]), int(m["status_code"])))
        conn.commit()
        statuses = [r["status"] for r in results]
        return {"run_id": run_id, "build": build_number, "passed": statuses.count("PASSED"),
                "failed": statuses.count("FAILED"), "skipped": statuses.count("SKIPPED"), "metrics": len(metrics)}
    finally:
        conn.close()


def _upsert_case(cur, feature_id, name, layer, req_no, automated) -> int:
    cur.execute("""INSERT INTO test_cases (feature_id, name, layer, requirement_no, automated)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (feature_id, name) DO UPDATE SET layer = EXCLUDED.layer,
                       requirement_no = EXCLUDED.requirement_no, automated = EXCLUDED.automated
                   RETURNING id""", (feature_id, name[:200], layer, req_no, automated))
    return cur.fetchone()[0]
