"""Create the schemas and (re)load the synthetic demo project.

    python seed.py                  # seed 42
    python seed.py --seed 7         # different random history
    python seed.py --archive-live   # also move the live run history aside (e.g. after
                                    # changing QA_BASE_URL) and start an empty live project
"""
import argparse
import time

from config import QA_BASE_URL
from data.source import reseed_demo
from db.repository import archive_schema, check_connection, connect, create_schema

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--archive-live", action="store_true",
                        help="rename schema live to live_archive_<timestamp> and create an empty one")
    args = parser.parse_args()
    ok, msg = check_connection()
    if not ok:
        raise SystemExit(f"Cannot connect to PostgreSQL: {msg}")
    print(f"Connected: {msg}")
    conn = connect()
    if args.archive_live:
        archive = archive_schema(conn, "live")
        print(f"Live history archived to schema {archive}" if archive else "No live history to archive")
        print(f"Live project now records runs against {QA_BASE_URL}")
    else:
        create_schema(conn, "live")
    conn.close()
    t = time.time()
    counts = reseed_demo(args.seed)
    for table, n in counts.items():
        print(f"  demo.{table:<14} {n:>8,} rows")
    print(f"Done in {time.time() - t:.1f}s")
