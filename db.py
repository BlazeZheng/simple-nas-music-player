import sqlite3
import os
import time
import config

DATABASE_PATH = config.DATABASE_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS songs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL UNIQUE,
    filename    TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    artist      TEXT NOT NULL DEFAULT '未知艺术家',
    album       TEXT NOT NULL DEFAULT '未知专辑',
    file_size   TEXT DEFAULT '0 MB',
    file_mtime  REAL DEFAULT 0,
    has_cover   INTEGER DEFAULT 0,
    has_lyrics  INTEGER DEFAULT 0,

    title_initial  TEXT DEFAULT '#',
    artist_initial TEXT DEFAULT '#',
    album_initial  TEXT DEFAULT '#',
    title_sort     TEXT DEFAULT '',
    artist_sort    TEXT DEFAULT '',
    album_sort     TEXT DEFAULT '',

    updated_at  REAL DEFAULT (strftime('%s','now'))
);

CREATE INDEX IF NOT EXISTS idx_songs_path ON songs(path);
CREATE INDEX IF NOT EXISTS idx_songs_title_sort ON songs(title_sort);
CREATE INDEX IF NOT EXISTS idx_songs_artist_sort ON songs(artist_sort);
CREATE INDEX IF NOT EXISTS idx_songs_album_sort ON songs(album_sort);

CREATE TABLE IF NOT EXISTS lyrics (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    song_path TEXT NOT NULL UNIQUE,
    lrc_text  TEXT NOT NULL DEFAULT '',
    source    TEXT DEFAULT '',
    updated_at REAL DEFAULT (strftime('%s','now'))
);

CREATE INDEX IF NOT EXISTS idx_lyrics_path ON lyrics(song_path);

CREATE TABLE IF NOT EXISTS covers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    song_path  TEXT NOT NULL UNIQUE,
    cover_file TEXT NOT NULL,
    source     TEXT DEFAULT '',
    updated_at REAL DEFAULT (strftime('%s','now'))
);

CREATE INDEX IF NOT EXISTS idx_covers_path ON covers(song_path);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

SORT_COLUMNS = {
    "title": "title_sort",
    "artist": "artist_sort",
    "album": "album_sort",
    "filename": "filename",
}


def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def row_to_song(row):
    if row is None:
        return None
    return dict(row)


def query_songs(search="", sort_by="title", sort_order="asc", page=1, page_size=0):
    conn = get_conn()
    try:
        sort_col = SORT_COLUMNS.get(sort_by, "title_sort")
        direction = "ASC" if sort_order == "asc" else "DESC"

        params = []
        where = ""
        if search:
            where = (
                "WHERE filename LIKE ? OR title LIKE ? "
                "OR artist LIKE ? OR album LIKE ?"
            )
            s = f"%{search}%"
            params = [s, s, s, s]

        count_sql = f"SELECT COUNT(*) FROM songs {where}"
        total = conn.execute(count_sql, params).fetchone()[0]

        sql = f"SELECT * FROM songs {where} ORDER BY {sort_col} {direction}"
        if page_size > 0:
            offset = (page - 1) * page_size
            sql += f" LIMIT {page_size} OFFSET {offset}"

        rows = conn.execute(sql, params).fetchall()
        return [row_to_song(r) for r in rows], total
    finally:
        conn.close()


def get_song_by_path(path):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM songs WHERE path = ?", (path,)).fetchone()
        return row_to_song(row)
    finally:
        conn.close()


def get_cover_cache(song_path):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT cover_file FROM covers WHERE song_path = ?", (song_path,)
        ).fetchone()
        if row and row["cover_file"] and os.path.exists(row["cover_file"]):
            return row["cover_file"]
        return None
    finally:
        conn.close()


def set_cover_cache(song_path, cover_file, source=""):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO covers (song_path, cover_file, source, updated_at) VALUES (?, ?, ?, ?)",
            (song_path, cover_file, source, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def get_lyrics_cache(song_path):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT lrc_text FROM lyrics WHERE song_path = ?", (song_path,)
        ).fetchone()
        if row:
            return row["lrc_text"]
        return None
    finally:
        conn.close()


def set_lyrics_cache(song_path, lrc_text, source=""):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO lyrics (song_path, lrc_text, source, updated_at) VALUES (?, ?, ?, ?)",
            (song_path, lrc_text, source, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def get_songs_needing_scrape():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM songs WHERE has_lyrics = 0 OR has_cover = 0"
        ).fetchall()
        return [row_to_song(r) for r in rows]
    finally:
        conn.close()


def upsert_song(data):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO songs (
                path, filename, title, artist, album, file_size, file_mtime,
                has_cover, has_lyrics,
                title_initial, artist_initial, album_initial,
                title_sort, artist_sort, album_sort,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["path"], data["filename"], data["title"], data["artist"],
                data["album"], data["file_size"], data["file_mtime"],
                data["has_cover"], data["has_lyrics"],
                data["title_initial"], data["artist_initial"], data["album_initial"],
                data["title_sort"], data["artist_sort"], data["album_sort"],
                time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_song(path):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM songs WHERE path = ?", (path,))
        conn.execute("DELETE FROM lyrics WHERE song_path = ?", (path,))
        conn.execute("DELETE FROM covers WHERE song_path = ?", (path,))
        conn.commit()
    finally:
        conn.close()


def update_song_flag(path, has_cover=None, has_lyrics=None):
    conn = get_conn()
    try:
        sets = []
        vals = []
        if has_cover is not None:
            sets.append("has_cover = ?")
            vals.append(1 if has_cover else 0)
        if has_lyrics is not None:
            sets.append("has_lyrics = ?")
            vals.append(1 if has_lyrics else 0)
        if sets:
            sets.append("updated_at = ?")
            vals.append(time.time())
            vals.append(path)
            conn.execute(f"UPDATE songs SET {', '.join(sets)} WHERE path = ?", vals)
            conn.commit()
    finally:
        conn.close()
