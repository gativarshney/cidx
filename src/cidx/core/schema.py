"""The cidx index schema, exactly as specified in ARCHITECTURE.md.

``schema_version`` in ``meta`` lets a newer cidx detect an old index and
rebuild instead of misreading it. ``ON DELETE CASCADE`` makes "remove a
file's rows" one statement.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE files (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  language TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  mtime REAL NOT NULL,
  indexed_at REAL NOT NULL
);
CREATE TABLE symbols (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  qualified_name TEXT NOT NULL,
  kind TEXT NOT NULL,             -- function | class | method | const | import
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  signature TEXT,
  parent_id INTEGER REFERENCES symbols(id)
);
CREATE TABLE refs (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  line INTEGER NOT NULL,
  resolved_symbol_id INTEGER REFERENCES symbols(id),
  confidence TEXT NOT NULL        -- exact | import | name-only
);
CREATE VIRTUAL TABLE symbols_fts USING fts5(
  name, qualified_name, signature, content='symbols', content_rowid='id'
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);  -- schema_version, engine_version
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_refs_name ON refs(name);
CREATE INDEX idx_refs_symbol ON refs(resolved_symbol_id);
"""

#: Every named object the DDL creates, dropped in reverse-dependency order
#: when an old or foreign schema_version forces a rebuild.
DROP_SQL = """
DROP TABLE IF EXISTS refs;
DROP TABLE IF EXISTS symbols_fts;
DROP TABLE IF EXISTS symbols;
DROP TABLE IF EXISTS files;
DROP TABLE IF EXISTS meta;
"""
