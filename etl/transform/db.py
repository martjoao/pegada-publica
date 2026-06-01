"""SQLite schema and connection for the canonical store (the system-of-record).

For now the ``transform`` step writes straight into this DB (it doubles as the
``load`` step). DuckDB is intended to layer on later as a read-only analytics
engine for the heavy CPF×QSA cross-reference — it can ``ATTACH`` this SQLite file,
so this is not a lock-in.

Identifiers are canonical English (see ``docs/glossario.md``). Datetimes are stored
as ISO-8601 TEXT (SQLite has no datetime type; ISO-8601 sorts correctly
lexicographically). ``end_at IS NULL`` means an open interval.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
DROP TABLE IF EXISTS name_history;
DROP TABLE IF EXISTS party_affiliation;
DROP TABLE IF EXISTS office_period;
DROP TABLE IF EXISTS mandate;
DROP TABLE IF EXISTS senator_name_history;
DROP TABLE IF EXISTS senator_party_affiliation;
DROP TABLE IF EXISTS senator_office_period;
DROP TABLE IF EXISTS senate_term;
DROP TABLE IF EXISTS source;
DROP TABLE IF EXISTS deputy;
DROP TABLE IF EXISTS senator;

CREATE TABLE deputy (
  id             INTEGER PRIMARY KEY,   -- Câmara id; also the page URL key
  name           TEXT NOT NULL,         -- current/latest parliamentary name
  photo_url      TEXT,
  current_status TEXT                   -- in_office|substitute|on_leave|suspended|vacated|term_ended|NULL
);

CREATE TABLE mandate (
  deputy_id    INTEGER NOT NULL REFERENCES deputy(id),
  legislature  INTEGER NOT NULL,
  state        TEXT NOT NULL,
  PRIMARY KEY (deputy_id, legislature)
);

CREATE TABLE office_period (
  deputy_id    INTEGER NOT NULL REFERENCES deputy(id),
  legislature  INTEGER NOT NULL,
  condition    TEXT NOT NULL,           -- titular | alternate
  start_at     TEXT NOT NULL,
  end_at       TEXT,
  PRIMARY KEY (deputy_id, start_at)
);

CREATE TABLE party_affiliation (
  deputy_id    INTEGER NOT NULL REFERENCES deputy(id),
  party        TEXT NOT NULL,
  start_at     TEXT NOT NULL,
  end_at       TEXT,
  legislature  INTEGER NOT NULL,
  source_note  TEXT,
  PRIMARY KEY (deputy_id, start_at)
);

CREATE TABLE name_history (
  deputy_id INTEGER NOT NULL REFERENCES deputy(id),
  name      TEXT NOT NULL,
  start_at  TEXT NOT NULL,
  end_at    TEXT,
  PRIMARY KEY (deputy_id, start_at)
);

-- Senators (Senado Federal) — parallel tables mirroring the deputy ones, so the
-- deputy pipeline is untouched (decision 019). id = Senado CodigoParlamentar.
CREATE TABLE senator (
  id             INTEGER PRIMARY KEY,   -- CodigoParlamentar; also the page URL key
  name           TEXT NOT NULL,         -- current/latest parliamentary name
  photo_url      TEXT,
  current_status TEXT                   -- in_office|substitute|on_leave|...|NULL
);

-- One row per legislature a mandate covers (the 8-year mandate spans two terms).
CREATE TABLE senate_term (
  senator_id   INTEGER NOT NULL REFERENCES senator(id),
  legislature  INTEGER NOT NULL,
  state        TEXT NOT NULL,
  condition    TEXT NOT NULL,           -- titular | alternate
  PRIMARY KEY (senator_id, legislature)
);

CREATE TABLE senator_office_period (
  senator_id   INTEGER NOT NULL REFERENCES senator(id),
  legislature  INTEGER,
  condition    TEXT NOT NULL,           -- titular | alternate
  start_at     TEXT NOT NULL,
  end_at       TEXT,
  cause        TEXT,                    -- raw afastamento cause (PT) that closed it
  PRIMARY KEY (senator_id, start_at)
);

CREATE TABLE senator_party_affiliation (
  senator_id   INTEGER NOT NULL REFERENCES senator(id),
  party        TEXT NOT NULL,
  start_at     TEXT NOT NULL,
  end_at       TEXT,
  source_note  TEXT,
  PRIMARY KEY (senator_id, start_at)
);

CREATE TABLE senator_name_history (
  senator_id INTEGER NOT NULL REFERENCES senator(id),
  name      TEXT NOT NULL,
  start_at  TEXT NOT NULL,
  end_at    TEXT,
  PRIMARY KEY (senator_id, start_at)
);

-- audit: one row per ingested raw landing file (fields nullable — minimal _meta tolerated)
CREATE TABLE source (
  source       TEXT,
  endpoint     TEXT,
  legislature  INTEGER,
  fetched_at   TEXT,
  record_count INTEGER
);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection with foreign keys enforced and Row access."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """(Re)create all tables from scratch — transform is a full rebuild."""
    conn.executescript(SCHEMA)
    conn.commit()
