import os

MUSIC_DIR = os.environ.get("MUSIC_DIR", "/music")
CACHE_DIR = os.environ.get("CACHE_DIR", "/app/cache")
DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join(CACHE_DIR, "music.db"))

LYRIC_DIR = os.path.join(CACHE_DIR, "lyrics")
COVER_DIR = os.path.join(CACHE_DIR, "covers")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
RELOAD = os.environ.get("RELOAD", "").lower() in ("1", "true", "yes")
