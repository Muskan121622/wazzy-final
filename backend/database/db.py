import os
import re
import sqlite3
from datetime import datetime

from dotenv import load_dotenv

# Load backend/.env so DATABASE_URL etc. resolve regardless of entrypoint
# (uvicorn, seed.py, standalone scripts).
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

# ─────────────────────────────────────────────────────────────
# Dual-engine data layer:
#   • DATABASE_URL set (Neon/Render Postgres) → PostgreSQL
#   • Otherwise                                → local SQLite (dev)
# All app code uses the same tiny API:
#   conn = get_connection(); cur = conn.cursor()
#   cur.execute("... ?", (params,)); cur.fetchone() -> dict
# ─────────────────────────────────────────────────────────────

DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
IS_POSTGRES = DATABASE_URL.startswith("postgres")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "tripos.db")


class _SqliteCursor:
    """Wraps sqlite3 cursor so rows come back as plain dicts."""

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        self._cur.execute(sql, params or ())
        return self

    def executemany(self, sql, seq):
        self._cur.executemany(sql, seq)
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description


class _SqliteConn:
    def __init__(self):
        self._conn = sqlite3.connect(DB_PATH, timeout=15.0)
        self._conn.row_factory = sqlite3.Row
        # WAL: concurrent readers + single writer without blocking reads
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error:
            pass

    def cursor(self):
        return _SqliteCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def set_autocommit(self, val):
        self._conn.isolation_level = None if val else ""

    def close(self):
        self._conn.close()


class _PgCursor:
    """Wraps psycopg2 cursor: converts SQLite-style '?' placeholders to '%s'."""

    def __init__(self, cur):
        self._cur = cur

    @staticmethod
    def _convert(sql):
        # No literal '?' characters are used inside SQL string constants in this app.
        return sql.replace("?", "%s")

    def execute(self, sql, params=None):
        self._cur.execute(self._convert(sql), params or None)
        return self

    def executemany(self, sql, seq):
        self._cur.executemany(self._convert(sql), seq)
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        rows = self._cur.fetchall()
        return [dict(r) for r in rows]

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description


class _PgConn:
    def __init__(self):
        import psycopg2
        # The DSN may already carry sslmode / channel_binding (Neon does), so
        # only add sslmode when it's absent to avoid a duplicate-parameter error.
        _kw = {} if "sslmode" in DATABASE_URL.lower() else {"sslmode": "prefer"}
        self._conn = psycopg2.connect(DATABASE_URL, connect_timeout=10, **_kw)

    def cursor(self):
        from psycopg2.extras import RealDictCursor
        return _PgCursor(self._conn.cursor(cursor_factory=RealDictCursor))

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def set_autocommit(self, val):
        # psycopg2 client-side autocommit: commits after each execute. Pooler-safe
        # (no SET SESSION), and prevents one failing DDL from poisoning the txn.
        self._conn.autocommit = bool(val)

    def close(self):
        self._conn.close()


def get_connection():
    return _PgConn() if IS_POSTGRES else _SqliteConn()


def _now_iso():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────────────────────
# Schema (portable DDL; dialect-specific bits handled below)
# ─────────────────────────────────────────────────────────────

TABLES = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        password_hash TEXT,
        is_guest BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trips (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        destination TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        health_score INTEGER DEFAULT 86,
        current_version INTEGER DEFAULT 1,
        status TEXT DEFAULT 'ACTIVE',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS preferences (
        user_id TEXT PRIMARY KEY,
        quietness REAL DEFAULT 0.9,
        seafood REAL DEFAULT 0.9,
        budget_max INTEGER DEFAULT 2000,
        crowd_tolerance REAL DEFAULT 0.2,
        energy_level TEXT DEFAULT 'medium',
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS places (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        area TEXT NOT NULL,
        category TEXT NOT NULL,
        indoor_flag BOOLEAN DEFAULT FALSE,
        crowd_level TEXT NOT NULL,
        price INTEGER DEFAULT 0,
        rating REAL DEFAULT 4.5,
        opening_hours TEXT,
        lat REAL DEFAULT 15.5553,
        lon REAL DEFAULT 73.7517,
        source TEXT,
        description TEXT,
        plan_b_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS itinerary_items (
        id TEXT PRIMARY KEY,
        trip_id TEXT NOT NULL,
        day_number INTEGER NOT NULL,
        time_slot TEXT NOT NULL,
        time_period TEXT NOT NULL,
        place_id TEXT NOT NULL,
        status TEXT DEFAULT 'SCHEDULED',
        fallback_place_id TEXT,
        version INTEGER DEFAULT 1,
        FOREIGN KEY(trip_id) REFERENCES trips(id),
        FOREIGN KEY(place_id) REFERENCES places(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recovery_proposals (
        id TEXT PRIMARY KEY,
        trip_id TEXT NOT NULL,
        trip_version INTEGER NOT NULL,
        original_item_id TEXT NOT NULL,
        proposed_place_id TEXT,
        proposed_time_slot TEXT,
        type TEXT DEFAULT 'WEATHER',
        reason TEXT NOT NULL,
        score REAL DEFAULT 91.5,
        status TEXT DEFAULT 'PENDING',
        expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(trip_id) REFERENCES trips(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_actions (
        id TEXT PRIMARY KEY,
        trip_id TEXT NOT NULL,
        action TEXT NOT NULL,
        reason TEXT NOT NULL,
        tool_used TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'SUCCESS',
        FOREIGN KEY(trip_id) REFERENCES trips(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS incidents (
        id TEXT PRIMARY KEY,
        trip_id TEXT NOT NULL,
        type TEXT NOT NULL,
        detail TEXT NOT NULL,
        severity TEXT DEFAULT 'INFO',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(trip_id) REFERENCES trips(id)
    )
    """,
]

# trip_versions needs an autoincrement id; dialect-specific
TRIP_VERSIONS_PG = """
    CREATE TABLE IF NOT EXISTS trip_versions (
        id INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
        trip_id TEXT NOT NULL,
        version_number INTEGER NOT NULL,
        change_description TEXT NOT NULL,
        snapshot_json TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(trip_id) REFERENCES trips(id)
    )
"""
TRIP_VERSIONS_SQLITE = """
    CREATE TABLE IF NOT EXISTS trip_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trip_id TEXT NOT NULL,
        version_number INTEGER NOT NULL,
        change_description TEXT NOT NULL,
        snapshot_json TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(trip_id) REFERENCES trips(id)
    )
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_itinerary_trip_day ON itinerary_items(trip_id, day_number)",
    "CREATE INDEX IF NOT EXISTS idx_proposals_trip_status ON recovery_proposals(trip_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_trips_user ON trips(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_actions_trip ON agent_actions(trip_id)",
    "CREATE INDEX IF NOT EXISTS idx_incidents_trip ON incidents(trip_id, created_at)",
    # Only one PENDING proposal per itinerary item at a time (dedupe guard)
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_pending_proposal ON recovery_proposals(trip_id, original_item_id) WHERE status = 'PENDING'",
]

# Columns added to pre-existing tables (idempotent migrations)
MIGRATION_COLUMNS = [
    ("users", "password_hash", "TEXT"),
    ("users", "is_guest", "BOOLEAN DEFAULT FALSE"),
    ("users", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ("trips", "status", "TEXT DEFAULT 'ACTIVE'"),
    ("trips", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ("recovery_proposals", "type", "TEXT DEFAULT 'WEATHER'"),
    ("recovery_proposals", "proposed_time_slot", "TEXT"),
    ("recovery_proposals", "expires_at", "TIMESTAMP"),
    ("trip_versions", "snapshot_json", "TEXT"),
    ("incidents", "id", "TEXT"),
]

DROP_ORDER = [
    "recovery_proposals", "itinerary_items", "agent_actions", "trip_versions",
    "preferences", "incidents", "trips", "users", "places",
]


def _table_exists(cur, table):
    if IS_POSTGRES:
        cur.execute(
            "SELECT 1 AS x FROM information_schema.tables WHERE table_name = ?",
            (table,),
        )
    else:
        cur.execute("SELECT 1 AS x FROM sqlite_master WHERE type='table' AND name = ?", (table,))
    return cur.fetchone() is not None


def _safe_ddl(cur, sql):
    """
    Execute a DDL statement that may legitimately fail (DROP of a missing table,
    ALTER ADD COLUMN already present, CREATE INDEX already present). Under the
    autocommit connection used by init_db, one failure cannot poison the rest.
    """
    try:
        cur.execute(sql)
        return True
    except Exception:
        return False


def init_db(reset=False):
    conn = get_connection()
    conn.set_autocommit(True)  # each statement its own txn — Neon pooler-safe
    cur = conn.cursor()

    if reset:
        for t in DROP_ORDER:
            _safe_ddl(cur, f"DROP TABLE IF EXISTS {t}")

    for ddl in TABLES:
        _safe_ddl(cur, ddl)
    _safe_ddl(cur, TRIP_VERSIONS_PG if IS_POSTGRES else TRIP_VERSIONS_SQLITE)

    # Idempotent column migrations for legacy SQLite files
    for table, column, coltype in MIGRATION_COLUMNS:
        if not _table_exists(cur, table):
            continue
        _safe_ddl(cur, f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

    for idx in INDEXES:
        _safe_ddl(cur, idx)

    conn.close()


if __name__ == "__main__":
    init_db(reset=True)
    print(f"Schema initialized on {'PostgreSQL' if IS_POSTGRES else 'SQLite'}")
