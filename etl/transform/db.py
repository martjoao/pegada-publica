"""SQLite schema and connection for the canonical store (the system-of-record).

For now the ``transform`` step writes straight into this DB (it doubles as the
``load`` step). DuckDB is intended to layer on later as a read-only analytics
engine for the heavy CPF×QSA cross-reference — it can ``ATTACH`` this SQLite file,
so this is not a lock-in.

Datetimes are stored as ISO-8601 TEXT (SQLite has no datetime type; ISO-8601
sorts correctly lexicographically). ``end_at IS NULL`` means an open interval.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
DROP TABLE IF EXISTS name_history;
DROP TABLE IF EXISTS party_membership;
DROP TABLE IF EXISTS exercicio;
DROP TABLE IF EXISTS mandato;
DROP TABLE IF EXISTS source_meta;
DROP TABLE IF EXISTS deputado;

CREATE TABLE deputado (
  id        INTEGER PRIMARY KEY,            -- Câmara id; also the page URL key
  nome      TEXT NOT NULL,                  -- current/latest parliamentary name
  foto_url  TEXT
);

CREATE TABLE mandato (
  deputy_id    INTEGER NOT NULL REFERENCES deputado(id),
  legislatura  INTEGER NOT NULL,
  uf           TEXT NOT NULL,
  PRIMARY KEY (deputy_id, legislatura)
);

CREATE TABLE exercicio (
  deputy_id    INTEGER NOT NULL REFERENCES deputado(id),
  legislatura  INTEGER NOT NULL,
  condicao     TEXT NOT NULL,               -- "Titular" | "Suplente"
  start_at     TEXT NOT NULL,
  end_at       TEXT,
  PRIMARY KEY (deputy_id, start_at)
);

CREATE TABLE party_membership (
  deputy_id        INTEGER NOT NULL REFERENCES deputado(id),
  sigla_partido    TEXT NOT NULL,
  start_at         TEXT NOT NULL,
  end_at           TEXT,
  legislatura      INTEGER NOT NULL,
  descricao_origem TEXT,
  PRIMARY KEY (deputy_id, start_at)
);

CREATE TABLE name_history (
  deputy_id INTEGER NOT NULL REFERENCES deputado(id),
  nome      TEXT NOT NULL,
  start_at  TEXT NOT NULL,
  end_at    TEXT,
  PRIMARY KEY (deputy_id, start_at)
);

-- audit: one row per ingested raw landing file
CREATE TABLE source_meta (
  source       TEXT,
  endpoint     TEXT,
  legislatura  INTEGER,
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
