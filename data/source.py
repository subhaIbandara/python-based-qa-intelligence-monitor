"""Loads a project's data from PostgreSQL for the dashboard."""
from config import QA_BASE_URL
from data.generator import generate
from db import repository


def load(project: str):
    """Returns (data, message). data is None when the project has no runs yet."""
    conn = repository.connect()
    try:
        repository.create_schema(conn, project)
        if repository.run_count(conn, project) == 0:
            if project == "demo":
                counts = repository.save_all(conn, generate(), "demo")
                return repository.load_all(conn, project), f"Seeded demo history ({counts['test_results']:,} results)."
            return None, f"No test runs recorded against {QA_BASE_URL} yet — use “Run tests” or run pytest."
        return repository.load_all(conn, project), "Loaded from PostgreSQL."
    finally:
        conn.close()


def latest_marker(project: str):
    conn = repository.connect()
    try:
        return repository.latest_run_marker(conn, project)
    finally:
        conn.close()


def reseed_demo(seed: int = 42) -> dict:
    conn = repository.connect()
    try:
        return repository.save_all(conn, generate(seed=seed), "demo")
    finally:
        conn.close()
