from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Iterable, Dict, Any, Tuple, Optional

DB_FILENAME = "songsearch.db"

BASE_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    title TEXT,
    artist TEXT,
    album TEXT,
    album_artist TEXT,
    year INTEGER,
    genre TEXT,
    track_no INTEGER,
    disc_no INTEGER,

    duration REAL,
    bitrate INTEGER,
    samplerate INTEGER,
    channels INTEGER,
    format TEXT,

    mtime REAL,
    file_size INTEGER,
    missing INTEGER DEFAULT 0,

    fp_status TEXT,
    acoustid_id TEXT,
    mb_recording_id TEXT,
    mb_release_id TEXT,
    mb_release_group_id TEXT,
    mb_confidence REAL,
    cover_art_url TEXT,
    -- Nuevas columnas para carátulas cacheadas y hash parcial
    hash_partial TEXT,
    cover_local_path TEXT,
    cover_fetched INTEGER DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
    title, artist, album, genre, path
);
"""

MIGRATION_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("album_artist", "TEXT"),
    ("track_no", "INTEGER"),
    ("disc_no", "INTEGER"),
    ("fp_status", "TEXT"),
    ("acoustid_id", "TEXT"),
    ("mb_recording_id", "TEXT"),
    ("mb_release_id", "TEXT"),
    ("mb_release_group_id", "TEXT"),
    ("mb_confidence", "REAL"),
    ("cover_art_url", "TEXT"),
    ("hash_partial", "TEXT"),
    ("cover_local_path", "TEXT"),
    ("cover_fetched", "INTEGER"),
)

def connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con

def _table_has_column(con: sqlite3.Connection, table: str, column: str) -> bool:
    cur = con.execute(f"PRAGMA table_info({table})")
    return any(r["name"] == column for r in cur.fetchall())

def _run_schema(con: sqlite3.Connection):
    with con:
        con.executescript(BASE_SCHEMA)

def _migrate_columns(con: sqlite3.Connection):
    for col, ctype in MIGRATION_COLUMNS:
        if not _table_has_column(con, "tracks", col):
            with con:
                con.execute(f"ALTER TABLE tracks ADD COLUMN {col} {ctype}")

def init_db(db_dir: Path) -> Path:
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / DB_FILENAME
    con = connect(db_path)
    _run_schema(con)
    _migrate_columns(con)
    return db_path

def upsert_track(con: sqlite3.Connection, data: Dict[str, Any]) -> int:
    cur = con.execute("PRAGMA table_info(tracks)")
    cols = [r["name"] for r in cur.fetchall()]
    fields = [k for k in (
        "path","title","artist","album","album_artist","year","genre",
        "track_no","disc_no","duration","bitrate","samplerate","channels","format",
        "mtime","file_size","missing","fp_status","acoustid_id","mb_recording_id",
        "mb_release_id","mb_release_group_id","mb_confidence","cover_art_url",
        "hash_partial","cover_local_path","cover_fetched"
    ) if k in cols and k in data]
    placeholders = ",".join("?" for _ in fields)
    values = [data.get(k) for k in fields]

    with con:
        con.execute(f"""
            INSERT INTO tracks ({','.join(fields)})
            VALUES ({placeholders})
            ON CONFLICT(path) DO UPDATE SET
              {','.join(f'{k}=excluded.{k}' for k in fields if k != 'path')}
        """, values)
        rowid = con.execute("SELECT id FROM tracks WHERE path=?", (data["path"],)).fetchone()["id"]
        con.execute("DELETE FROM tracks_fts WHERE path=?", (data["path"],))
        con.execute("INSERT INTO tracks_fts (title,artist,album,genre,path) VALUES (?,?,?,?,?)",
                    (data.get("title"), data.get("artist"), data.get("album"),
                     data.get("genre"), data.get("path")))
    return rowid

def update_fields(con: sqlite3.Connection, path: str, updates: Dict[str, Any]):
    if not updates:
        return
    old_path = path
    new_path = updates.get("path", old_path)
    cols = list(updates.keys())
    vals = [updates[c] for c in cols]
    with con:
        con.execute(f"UPDATE tracks SET {', '.join(c+'=?' for c in cols)} WHERE path=?", (*vals, old_path))
        r = con.execute("SELECT title,artist,album,genre,path FROM tracks WHERE path=?", (new_path,)).fetchone()
        if r:
            con.execute("DELETE FROM tracks_fts WHERE path=?", (old_path,))
            con.execute("INSERT INTO tracks_fts (title,artist,album,genre,path) VALUES (?,?,?,?,?)",
                        (r["title"], r["artist"], r["album"], r["genre"], r["path"]))

def query_tracks(con: sqlite3.Connection, where: str = "", params: Iterable[Any] = ()) -> Iterable[sqlite3.Row]:
    sql = "SELECT * FROM tracks"
    if where:
        sql += " WHERE " + where
    sql += " ORDER BY artist, album, title"
    return con.execute(sql, tuple(params)).fetchall()

def get_by_path(con: sqlite3.Connection, path: str) -> Optional[sqlite3.Row]:
    return con.execute("SELECT * FROM tracks WHERE path=?", (path,)).fetchone()
