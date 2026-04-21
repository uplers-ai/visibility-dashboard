"""SQLite storage for the dashboard."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "data" / "audits.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_company TEXT NOT NULL,
    location_country TEXT,
    location_state TEXT,
    location_city TEXT,
    llms TEXT NOT NULL,
    runs_per_prompt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending',
    progress_message TEXT,
    total_queries INTEGER DEFAULT 0,
    completed_queries INTEGER DEFAULT 0,
    error_message TEXT,
    analysis_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    intent TEXT,
    FOREIGN KEY (audit_id) REFERENCES audits(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id INTEGER NOT NULL,
    query_id INTEGER NOT NULL,
    llm TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    response TEXT,
    companies_mentioned TEXT,
    companies_classified_json TEXT,
    target_mentioned INTEGER NOT NULL DEFAULT 0,
    target_mention_count INTEGER NOT NULL DEFAULT 0,
    target_citation_count INTEGER NOT NULL DEFAULT 0,
    links_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (audit_id) REFERENCES audits(id) ON DELETE CASCADE,
    FOREIGN KEY (query_id) REFERENCES queries(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS query_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    queries_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_results_audit ON results(audit_id);
CREATE INDEX IF NOT EXISTS idx_queries_audit ON queries(audit_id);
"""

_RESULTS_NEW_COLUMNS = [
    ("companies_classified_json", "TEXT"),
    ("target_mention_count", "INTEGER NOT NULL DEFAULT 0"),
    ("target_citation_count", "INTEGER NOT NULL DEFAULT 0"),
    ("links_json", "TEXT"),
]


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Migration: add newer columns to older databases
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(results)")}
        for col_name, col_def in _RESULTS_NEW_COLUMNS:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE results ADD COLUMN {col_name} {col_def}")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.utcnow().isoformat()


# ---------- audits ----------

def create_audit(
    name: str,
    target_company: str,
    country: str | None,
    state: str | None,
    city: str | None,
    llms: list[str],
    runs_per_prompt: int,
    queries: list[dict],
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO audits (
                name, target_company, location_country, location_state, location_city,
                llms, runs_per_prompt, status, total_queries, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                name,
                target_company,
                country,
                state,
                city,
                json.dumps(llms),
                runs_per_prompt,
                len(queries) * len(llms) * runs_per_prompt,
                _now(),
            ),
        )
        audit_id = cur.lastrowid
        for q in queries:
            conn.execute(
                "INSERT INTO queries (audit_id, text, intent) VALUES (?, ?, ?)",
                (audit_id, q["text"], q.get("intent") or "General"),
            )
        return audit_id


def get_audit(audit_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
        if not row:
            return None
        audit = _audit_row_to_dict(row)
        audit["queries"] = [
            dict(r) for r in conn.execute(
                "SELECT id, text, intent FROM queries WHERE audit_id = ? ORDER BY id",
                (audit_id,),
            ).fetchall()
        ]
        return audit


def list_audits() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audits ORDER BY id DESC"
        ).fetchall()
        return [_audit_row_to_dict(r) for r in rows]


def update_audit_status(
    audit_id: int,
    status: str | None = None,
    progress_message: str | None = None,
    completed_queries: int | None = None,
    error_message: str | None = None,
    analysis: dict | None = None,
    mark_started: bool = False,
    mark_completed: bool = False,
) -> None:
    fields, values = [], []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if progress_message is not None:
        fields.append("progress_message = ?")
        values.append(progress_message)
    if completed_queries is not None:
        fields.append("completed_queries = ?")
        values.append(completed_queries)
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)
    if analysis is not None:
        fields.append("analysis_json = ?")
        values.append(json.dumps(analysis))
    if mark_started:
        fields.append("started_at = ?")
        values.append(_now())
    if mark_completed:
        fields.append("completed_at = ?")
        values.append(_now())
    if not fields:
        return
    values.append(audit_id)
    with connect() as conn:
        conn.execute(f"UPDATE audits SET {', '.join(fields)} WHERE id = ?", values)


def delete_audit(audit_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM audits WHERE id = ?", (audit_id,))


def _audit_row_to_dict(row: sqlite3.Row) -> dict:
    audit = dict(row)
    audit["llms"] = json.loads(audit["llms"]) if audit.get("llms") else []
    if audit.get("analysis_json"):
        audit["analysis"] = json.loads(audit["analysis_json"])
    audit.pop("analysis_json", None)
    return audit


# ---------- results ----------

def insert_result(
    audit_id: int,
    query_id: int,
    llm: str,
    run_number: int,
    response: str,
    companies_mentioned: dict,
    target_mentioned: bool,
    companies_classified: dict | None = None,
    target_mention_count: int = 0,
    target_citation_count: int = 0,
    links: list | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO results (
                audit_id, query_id, llm, run_number,
                response, companies_mentioned, companies_classified_json,
                target_mentioned, target_mention_count, target_citation_count,
                links_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                query_id,
                llm,
                run_number,
                response,
                json.dumps(companies_mentioned),
                json.dumps(companies_classified or {}),
                1 if target_mentioned else 0,
                int(target_mention_count or 0),
                int(target_citation_count or 0),
                json.dumps(links or []),
                _now(),
            ),
        )


def get_results(audit_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.*, q.text AS query_text, q.intent AS query_intent
            FROM results r
            JOIN queries q ON q.id = r.query_id
            WHERE r.audit_id = ?
            ORDER BY r.id
            """,
            (audit_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["companies_mentioned"] = json.loads(d["companies_mentioned"]) if d.get("companies_mentioned") else {}
            d["companies_classified"] = json.loads(d["companies_classified_json"]) if d.get("companies_classified_json") else {}
            d["links"] = json.loads(d["links_json"]) if d.get("links_json") else []
            d["target_mentioned"] = bool(d["target_mentioned"])
            d["target_mention_count"] = int(d.get("target_mention_count") or 0)
            d["target_citation_count"] = int(d.get("target_citation_count") or 0)
            # drop raw json columns from output
            d.pop("companies_classified_json", None)
            d.pop("links_json", None)
            out.append(d)
        return out


# ---------- query sets ----------

def list_query_sets() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM query_sets ORDER BY name").fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "queries": json.loads(r["queries_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]


def upsert_query_set(name: str, queries: list[dict]) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO query_sets (name, queries_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET queries_json = excluded.queries_json
            """,
            (name, json.dumps(queries), _now()),
        )
        if cur.lastrowid:
            return cur.lastrowid
        existing = conn.execute("SELECT id FROM query_sets WHERE name = ?", (name,)).fetchone()
        return existing["id"] if existing else 0


def delete_query_set(set_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM query_sets WHERE id = ?", (set_id,))
