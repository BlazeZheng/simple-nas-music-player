import os
import re
import hashlib
import sqlite3
import requests
import threading
import time
import urllib.parse
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import mutagen
from pydantic import BaseModel
from typing import List, Optional
from io import BytesIO
from pypinyin import lazy_pinyin, Style
import config
import db
from db import (
    init_db, query_songs, get_song_by_path,
    get_cover_cache, set_cover_cache,
    get_lyrics_cache, set_lyrics_cache,
    get_songs_needing_scrape, upsert_song, delete_song,
    update_song_flag,
)

# 网易云音乐 API 配置
NETEASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://music.163.com/",
}
NETEASE_SEARCH_URL = "http://music.163.com/api/search/get"
NETEASE_LYRIC_URL = "http://music.163.com/api/song/lyric"
NETEASE_DETAIL_URL = "http://music.163.com/api/song/detail/"
NETEASE_SCRAPE_DELAY = 1.0  # 每首歌刮削间隔（秒），避免触发反爬

LRC_CX_LYRIC_URL = "https://api.lrc.cx/api/v1/lyrics/single"
LRC_CX_LYRIC_ADV_URL = "https://api.lrc.cx/api/v1/lyrics/advance"
LRC_CX_COVER_MUSIC_URL = "https://api.lrc.cx/api/v1/cover/music"
LRC_CX_COVER_ALBUM_URL = "https://api.lrc.cx/api/v1/cover/album"
LRC_CX_ENABLED = os.environ.get("LRC_CX_ENABLED", "1").lower() in ("1", "true", "yes")

app = FastAPI()

# CORS配置 - 使用正则表达式匹配允许的域名
# FastAPI 的 allow_origins 不支持 glob 通配符，改用 allow_origin_regex
ALLOWED_ORIGINS_REGEX = (
    r"^https?://localhost(:\d+)?$|"
    r"^https?://127\.0\.0\.1(:\d+)?$|"
    r"^https?://[a-zA-Z0-9.-]*\.local(:\d+)?$|"
    r"^https?://192\.168\.\d{1,3}\.\d{1,3}(:\d+)?$|"
    r"^https?://10\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?$|"
    r"^https?://172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}(:\d+)?$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=ALLOWED_ORIGINS_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

MUSIC_DIR = config.MUSIC_DIR
CACHE_DIR = config.CACHE_DIR
LYRIC_DIR = config.LYRIC_DIR
COVER_DIR = config.COVER_DIR

# 创建缓存目录
os.makedirs(LYRIC_DIR, exist_ok=True)
os.makedirs(COVER_DIR, exist_ok=True)

# 路径安全验证函数
def validate_and_safe_path(user_path: str, base_dir: str = MUSIC_DIR) -> str:
    """
    验证用户提供的路径是否在允许的目录内，防止目录遍历攻击
    
    Args:
        user_path: 用户提供的路径
        base_dir: 允许访问的基础目录
        
    Returns:
        安全的绝对路径
        
    Raises:
        HTTPException: 如果路径不安全
    """
    try:
        # 解码URL编码的路径
        decoded_path = urllib.parse.unquote(user_path)
        
        # 获取绝对路径
        abs_user_path = os.path.abspath(decoded_path)
        abs_base_dir = os.path.abspath(base_dir)
        
        # 检查路径是否在基础目录内（Windows 上忽略大小写）
        if not os.path.normcase(abs_user_path).startswith(os.path.normcase(abs_base_dir)):
            raise HTTPException(
                status_code=403, 
                detail="Access to this path is not allowed"
            )
        
        # 检查文件是否存在
        if not os.path.exists(abs_user_path):
            raise HTTPException(
                status_code=404,
                detail="File not found"
            )
        
        # 检查是否为普通文件（不是目录或特殊文件）
        if not os.path.isfile(abs_user_path):
            raise HTTPException(
                status_code=400,
                detail="Path must be a file, not a directory"
            )
        
        # 检查文件扩展名（仅限于音乐文件）
        allowed_extensions = ('.mp3', '.flac', '.m4a', '.wav', '.ogg')
        if not abs_user_path.lower().endswith(allowed_extensions):
            raise HTTPException(
                status_code=400,
                detail="File type not allowed. Only audio files are permitted"
            )
        
        return abs_user_path
        
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid path encoding"
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=500,
            detail=f"Error validating path: {str(e)}"
        )

class Song(BaseModel):
    path: str
    filename: str
    title: Optional[str] = None
    artist: Optional[str] = "未知艺术家"
    album: Optional[str] = "未知专辑"
    size: str = "0 MB"
    has_cover: bool = False
    has_lyrics: bool = False
    scraped: bool = False
    title_initial: Optional[str] = ""
    artist_initial: Optional[str] = ""
    album_initial: Optional[str] = ""
    title_sort: Optional[str] = ""
    artist_sort: Optional[str] = ""
    album_sort: Optional[str] = ""

class SongListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    songs: List[Song]

# --- 工具函数 ---
def get_cache_filename(artist, title):
    """生成缓存文件名 hash"""
    raw = f"{artist}-{title}".strip().lower()
    return hashlib.md5(raw.encode('utf-8')).hexdigest()

def get_file_size_mb(path):
    try:
        size = os.path.getsize(path)
        return f"{size / (1024 * 1024):.2f} MB"
    except:
        return "Unknown"

def get_initials(text: str) -> str:
    """获取文本的首字母"""
    if not text or text.strip() == "":
        return "#"
    
    # 处理中文转拼音首字母
    try:
        # 获取拼音首字母
        initials = lazy_pinyin(
            text, 
            style=Style.FIRST_LETTER,
            strict=False
        )
        # 连接首字母并转为大写
        result = "".join(initials).upper()
        # 确保只返回字母，非字母字符返回 #
        if result and result[0].isalpha():
            return result[0]
        else:
            return "#"
    except:
        return "#"

def get_sort_key(text: str) -> str:
    """生成排序用的键值：基于首字母分组，英文在前，中文在后"""
    if not text or text.strip() == "":
        return "ZZZZZZ"  # 空值排最后
    
    # 获取首字母
    initial = get_initials(text)
    
    # 检查第一个字符是否为英文字母
    first_char = text[0]
    if first_char.isalpha() and first_char.isascii():
        # 英文：在首字母后加0确保英文在前
        return initial + "0" + text.upper()
    else:
        # 中文：转换为拼音，在首字母后加1确保中文在后
        try:
            pinyin = lazy_pinyin(text, style=Style.NORMAL, strict=False)
            pinyin_str = "".join(pinyin).upper()
            return initial + "1" + pinyin_str
        except:
            return initial + "1" + text


def sync_index():
    """后台线程：增量扫描 /music 目录，同步歌曲元数据到 SQLite"""
    print("[索引] 开始扫描音乐库...")
    t0 = time.time()

    disk_paths = set()
    for root, dirs, files in os.walk(MUSIC_DIR):
        for file in files:
            if file.lower().endswith(('.mp3', '.flac', '.m4a', '.wav', '.ogg')):
                disk_paths.add(os.path.join(root, file))

    conn = db.get_conn()
    try:
        db_rows = conn.execute("SELECT path, file_mtime FROM songs").fetchall()
    finally:
        conn.close()

    db_paths = {row["path"]: row["file_mtime"] for row in db_rows}

    new_or_changed = []
    for path in disk_paths:
        if path not in db_paths:
            new_or_changed.append(path)
        else:
            try:
                disk_mtime = os.path.getmtime(path)
                if abs(disk_mtime - db_paths[path]) > 1:
                    new_or_changed.append(path)
            except OSError:
                new_or_changed.append(path)

    deleted = set(db_paths.keys()) - disk_paths

    for path in new_or_changed:
        try:
            info = _parse_song_file(path)
            if info:
                upsert_song(info)
        except Exception as e:
            print(f"[索引] 解析失败 {path}: {e}")

    for path in deleted:
        delete_song(path)
        print(f"[索引] 已删除: {os.path.basename(path)}")

    elapsed = time.time() - t0
    print(f"[索引] 完成: {len(disk_paths)} 首, 新增/更新 {len(new_or_changed)}, 删除 {len(deleted)}, 耗时 {elapsed:.1f}s")


def _parse_song_file(full_path):
    """解析单个音频文件的元数据，返回字典"""
    file = os.path.basename(full_path)
    default_title = os.path.splitext(file)[0]

    data = {
        "path": full_path,
        "filename": file,
        "title": default_title,
        "artist": "未知艺术家",
        "album": "未知专辑",
        "file_size": "0 MB",
        "file_mtime": 0.0,
        "has_cover": 0,
        "has_lyrics": 0,
        "title_initial": get_initials(default_title),
        "artist_initial": "#",
        "album_initial": "#",
        "title_sort": get_sort_key(default_title),
        "artist_sort": get_sort_key("未知艺术家"),
        "album_sort": get_sort_key("未知专辑"),
    }

    try:
        data["file_size"] = get_file_size_mb(full_path)
        data["file_mtime"] = os.path.getmtime(full_path)

        audio = mutagen.File(full_path)
        if audio:
            if 'TIT2' in audio:
                data["title"] = str(audio['TIT2'])
            elif 'title' in audio:
                data["title"] = str(audio['title'][0])

            if 'TPE1' in audio:
                data["artist"] = str(audio['TPE1'])
            elif 'artist' in audio:
                data["artist"] = str(audio['artist'][0])

            if 'TALB' in audio:
                data["album"] = str(audio['TALB'])
            elif 'album' in audio:
                data["album"] = str(audio['album'][0])

            data["title_initial"] = get_initials(data["title"])
            data["artist_initial"] = get_initials(data["artist"])
            data["album_initial"] = get_initials(data["album"])
            data["title_sort"] = get_sort_key(data["title"])
            data["artist_sort"] = get_sort_key(data["artist"])
            data["album_sort"] = get_sort_key(data["album"])

            if hasattr(audio, 'tags'):
                if 'APIC:' in audio.tags or 'APIC' in audio.tags:
                    data["has_cover"] = 1
                elif 'covr' in audio.tags:
                    data["has_cover"] = 1
            if hasattr(audio, 'pictures') and audio.pictures:
                data["has_cover"] = 1

        lrc_path = os.path.splitext(full_path)[0] + ".lrc"
        if os.path.exists(lrc_path):
            data["has_lyrics"] = 1

        if not data["has_cover"]:
            cache_name = get_cache_filename(data["artist"], data["title"])
            if os.path.exists(os.path.join(COVER_DIR, cache_name + ".jpg")):
                data["has_cover"] = 1

        if not data["has_lyrics"]:
            cache_name = get_cache_filename(data["artist"], data["title"])
            if os.path.exists(os.path.join(LYRIC_DIR, cache_name + ".lrc")):
                data["has_lyrics"] = 1

    except Exception as e:
        print(f"[解析] {file}: {e}")

    return data

def _normalize_text(text):
    """规范化文本：去除括号内容、多余空格、统一小写，用于匹配比较"""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[（(][^)）]*[)）]', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s]', '', text)
    return text.strip()


def _match_best_result(songs, artist, title):
    """从搜索结果中找出最佳匹配的歌曲"""
    if not songs:
        return None

    norm_title = _normalize_text(title)
    norm_artist = _normalize_text(artist)

    scored = []
    for song in songs:
        s_name = _normalize_text(song.get("name", ""))
        s_artists = song.get("artists", [])
        s_artist_names = " ".join(_normalize_text(a.get("name", "")) for a in s_artists)
        s_album = _normalize_text(song.get("album", {}).get("name", ""))

        score = 0
        if s_name == norm_title:
            score += 50
        elif norm_title and norm_title in s_name:
            score += 35
        elif s_name and s_name in norm_title:
            score += 30

        if norm_artist and norm_artist in s_artist_names:
            score += 40
        elif s_artist_names and s_artist_names in norm_artist:
            score += 25

        if norm_artist and any(norm_artist in _normalize_text(a.get("name", "")) for a in s_artists):
            score += 20

        album = song.get("album", {})
        if album.get("name") == "未知专辑" or album.get("name") == "":
            score -= 10

        scored.append((score, song))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else songs[0]


def _search_netease(artist, title, album=""):
    """
    搜索网易云音乐，用多种查询格式回退
    依次尝试: artist+album+title → title+album+artist → artist+title → title
    返回最佳匹配的歌曲信息，未找到返回 None
    """
    has_artist = artist and artist != "未知艺术家"
    has_album = album and album != "未知专辑"

    queries = []
    if has_artist and has_album:
        queries.append(f"{artist} {album} {title}")
        queries.append(f"{title} {album} {artist}")
    if has_artist:
        queries.append(f"{artist} {title}")
        queries.append(f"{title} {artist}")
    queries.append(title)

    best_all = None
    for query in queries:
        try:
            resp = requests.get(
                NETEASE_SEARCH_URL,
                params={"s": query, "type": 1, "limit": 15},
                headers=NETEASE_HEADERS,
                timeout=10
            )
            if resp.status_code != 200:
                continue

            data = resp.json()
            if data.get("code") != 200:
                continue

            songs = data.get("result", {}).get("songs", [])
            if not songs:
                continue

            best = _match_best_result(songs, artist, title)
            if best and _normalize_text(best.get("name", "")) == _normalize_text(title):
                return best

            if best_all is None:
                best_all = best

        except Exception as e:
            print(f"[搜索] {query}: {e}")
            continue

    return best_all


def _fetch_lyrics_netease(song_id):
    """根据 song_id 获取 LRC 歌词，失败时重试一次"""
    for attempt in range(2):
        try:
            resp = requests.get(
                NETEASE_LYRIC_URL,
                params={"id": song_id, "lv": 1, "tv": -1},
                headers=NETEASE_HEADERS,
                timeout=10
            )
            if resp.status_code != 200:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                return ""

            data = resp.json()
            lrc = data.get("lrc", {}).get("lyric", "")
            if not lrc:
                return ""
            return lrc

        except Exception as e:
            if attempt == 0:
                time.sleep(0.5)
                continue
            print(f"[歌词获取失败] song_id={song_id}: {e}")

    return ""


def _fetch_cover_netease(song_id, cover_save_path):
    """根据 song_id 下载封面图片到本地，失败时重试一次"""
    for attempt in range(2):
        try:
            resp = requests.get(
                NETEASE_DETAIL_URL,
                params={"id": song_id, "ids": f"[{song_id}]"},
                headers=NETEASE_HEADERS,
                timeout=10
            )
            if resp.status_code != 200:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                return False

            data = resp.json()
            songs_list = data.get("songs", [])
            if not songs_list:
                return False

            pic_url = songs_list[0].get("album", {}).get("picUrl", "")
            if not pic_url:
                return False

            img_resp = requests.get(pic_url, headers=NETEASE_HEADERS, timeout=15)
            if img_resp.status_code == 200 and "image" in img_resp.headers.get("content-type", ""):
                with open(cover_save_path, 'wb') as f:
                    f.write(img_resp.content)
                return True

            if attempt == 0:
                time.sleep(0.5)
                continue
            return False

        except Exception as e:
            if attempt == 0:
                time.sleep(0.5)
                continue
            print(f"[封面获取失败] song_id={song_id}: {e}")

    return False


def _fetch_lyrics_lrc(title, artist, album=""):
    """lrc.cx v1 歌词，返回 LRC 文本"""
    if not LRC_CX_ENABLED:
        return ""
    params = {"title": title}
    if artist and artist != "未知艺术家":
        params["artist"] = artist
    if album and album != "未知专辑":
        params["album"] = album
    try:
        resp = requests.get(LRC_CX_LYRIC_URL, params=params, timeout=10)
        if resp.status_code == 200 and resp.text.strip():
            return resp.text.strip()
    except Exception as e:
        print(f"[lrc.cx歌词] {title}: {e}")
    return ""


def _fetch_cover_lrc(title, artist, album="", cover_save_path=""):
    """lrc.cx v1 封面，下载到本地"""
    if not LRC_CX_ENABLED:
        return False
    params = {"title": title}
    if artist and artist != "未知艺术家":
        params["artist"] = artist
    if album and album != "未知专辑":
        params["album"] = album
    try:
        resp = requests.get(LRC_CX_COVER_MUSIC_URL, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            img_url = data.get("img", "")
            if img_url:
                return _download_cover_img(img_url, cover_save_path)
    except Exception as e:
        print(f"[lrc.cx封面music] {title}: {e}")

    if album and album != "未知专辑":
        try:
            p = {"album": album}
            if artist and artist != "未知艺术家":
                p["artist"] = artist
            resp = requests.get(LRC_CX_COVER_ALBUM_URL, params=p, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                img_url = data.get("img", "")
                if img_url:
                    return _download_cover_img(img_url, cover_save_path)
        except Exception as e:
            print(f"[lrc.cx封面album] {title}: {e}")

    return False


def _download_cover_img(img_url, save_path):
    try:
        r = requests.get(img_url, headers=NETEASE_HEADERS, timeout=15)
        if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
            with open(save_path, 'wb') as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"[下载封面] {img_url[:60]}: {e}")
    return False


# --- 刮削去重锁 ---
_scrape_in_progress = False
_scrape_lock = threading.Lock()


# --- 刮削逻辑（四级回退） ---

def _scrape_one_song(song):
    """
    刮削单首歌曲的歌词和封面
    song: dict, 必须包含 path / artist / title / has_cover / album 字段
    四级回退: 网易(全) → lrc.cx(全) → 网易(无专辑) → lrc.cx(无专辑)
    返回: dict { "lyrics": True/False, "cover": True/False }
    """
    if not song["title"]:
        return {"lyrics": False, "cover": False}

    title = song["title"]
    artist = song.get("artist", "未知艺术家")
    album = song.get("album", "未知专辑")

    cache_name = get_cache_filename(artist, title)
    lrc_file = os.path.join(LYRIC_DIR, cache_name + ".lrc")
    cover_file = os.path.join(COVER_DIR, cache_name + ".jpg")

    need_lyrics = not os.path.exists(lrc_file)
    need_cover = not os.path.exists(cover_file)

    if not need_lyrics and not need_cover:
        return {"lyrics": True, "cover": True}

    result = {"lyrics": False, "cover": False}
    tried = []

    # Level 1: 网易云 (artist + title + album)
    ne = _search_netease(artist, title, album)
    if ne:
        tried.append("网易+album")
        if need_lyrics:
            lrc = _fetch_lyrics_netease(ne["id"])
            if lrc:
                with open(lrc_file, 'w', encoding='utf-8') as f:
                    f.write(lrc)
                set_lyrics_cache(song["path"], lrc, source="netease")
                update_song_flag(song["path"], has_lyrics=True)
                result["lyrics"] = True
        if need_cover:
            if _fetch_cover_netease(ne["id"], cover_file):
                set_cover_cache(song["path"], cover_file, source="netease")
                update_song_flag(song["path"], has_cover=True)
                result["cover"] = True

    # Level 2: lrc.cx (title + artist + album)
    if not result["lyrics"] or not result["cover"]:
        tried.append("lrc.cx+album")
        if need_lyrics and not result["lyrics"]:
            lrc = _fetch_lyrics_lrc(title, artist, album)
            if lrc:
                with open(lrc_file, 'w', encoding='utf-8') as f:
                    f.write(lrc)
                set_lyrics_cache(song["path"], lrc, source="lrc.cx")
                update_song_flag(song["path"], has_lyrics=True)
                result["lyrics"] = True
        if need_cover and not result["cover"]:
            if _fetch_cover_lrc(title, artist, album, cover_file):
                set_cover_cache(song["path"], cover_file, source="lrc.cx")
                update_song_flag(song["path"], has_cover=True)
                result["cover"] = True

    # Level 3: 网易云 仅 artist + title（无 album）
    # 条件：Level 1/2 没搜全，且 Level 1 用的是带 album 的方式（即有专辑信息）
    # 如果本来就没专辑信息，Level 1 已经用无专辑方式搜过了，不需要重复
    if (not result["lyrics"] or not result["cover"]) and album and album != "未知专辑":
        ne2 = _search_netease(artist, title)
        if ne2:
            tried.append("网易+无专辑")
            if need_lyrics and not result["lyrics"]:
                lrc = _fetch_lyrics_netease(ne2["id"])
                if lrc:
                    with open(lrc_file, 'w', encoding='utf-8') as f:
                        f.write(lrc)
                    set_lyrics_cache(song["path"], lrc, source="netease")
                    update_song_flag(song["path"], has_lyrics=True)
                    result["lyrics"] = True
            if need_cover and not result["cover"]:
                if _fetch_cover_netease(ne2["id"], cover_file):
                    set_cover_cache(song["path"], cover_file, source="netease")
                    update_song_flag(song["path"], has_cover=True)
                    result["cover"] = True

    # Level 4: lrc.cx (title + artist 无 album)
    # 条件：Level 2 用的是带 album 的方式（即有专辑信息）
    if (not result["lyrics"] or not result["cover"]) and album and album != "未知专辑":
        tried.append("lrc.cx+无专辑")
        if need_lyrics and not result["lyrics"]:
            lrc = _fetch_lyrics_lrc(title, artist)
            if lrc:
                with open(lrc_file, 'w', encoding='utf-8') as f:
                    f.write(lrc)
                set_lyrics_cache(song["path"], lrc, source="lrc.cx")
                update_song_flag(song["path"], has_lyrics=True)
                result["lyrics"] = True
        if need_cover and not result["cover"]:
            if _fetch_cover_lrc(title, artist, "", cover_file):
                set_cover_cache(song["path"], cover_file, source="lrc.cx")
                update_song_flag(song["path"], has_cover=True)
                result["cover"] = True

    lyric_ok = "✓" if result["lyrics"] else "✗"
    cover_ok = "✓" if result["cover"] else "✗"
    chain = " → ".join(tried)
    print(f"[刮削] {title} - {artist} 歌词{lyric_ok} 封面{cover_ok} [{chain}]")

    time.sleep(NETEASE_SCRAPE_DELAY)
    return result


def scrape_metadata_background(songs_list):
    """
    后台线程：遍历所有歌曲，通过网易云音乐 API 下载歌词和封面
    使用全局锁确保同时只有一个刮削线程在运行
    """
    global _scrape_in_progress
    print(f"[刮削] 启动，待处理: {len(songs_list)} 首")

    try:
        for song in songs_list:
            _scrape_one_song(song)

        print("[刮削] 全部完成")

    except Exception as e:
        print(f"[刮削] 线程异常: {e}")
        import traceback
        traceback.print_exc()

    finally:
        with _scrape_lock:
            _scrape_in_progress = False


@app.get("/api/scrape")
def scrape_song(path: str = Query(..., description="歌曲文件路径")):
    """
    按需刮削单首歌曲的歌词和封面（后台线程执行，立即返回）

    Args:
        path: 经过URL编码的音乐文件路径

    Returns:
        JSON: { accepted: bool, reason: str }
    """
    safe_path = validate_and_safe_path(path)

    song_row = get_song_by_path(safe_path)
    if not song_row:
        return {"accepted": False, "reason": "歌曲不在索引中"}

    need_lyrics = not song_row["has_lyrics"]
    need_cover = not song_row["has_cover"]

    if not need_lyrics and not need_cover:
        return {"accepted": False, "reason": "已有歌词和封面"}

    def _bg_scrape():
        _scrape_one_song(song_row)

    threading.Thread(target=_bg_scrape, daemon=True).start()
    return {"accepted": True, "reason": "已提交后台刮削"}


# --- 核心接口 ---

# 启动事件：初始化数据库 + 后台同步索引
_scanned = False


@app.on_event("startup")
def startup():
    global _scanned
    init_db()
    print("[启动] 数据库初始化完成")

    def _index_then_scrape():
        global _scanned
        sync_index()
        _scanned = True
        need = get_songs_needing_scrape()
        if need:
            print(f"[启动] 触发刮削: {len(need)} 首缺少歌词或封面")
            global _scrape_in_progress
            with _scrape_lock:
                if not _scrape_in_progress:
                    _scrape_in_progress = True
                    t = threading.Thread(
                        target=scrape_metadata_background,
                        args=(need,),
                        daemon=True,
                    )
                    t.start()

    threading.Thread(target=_index_then_scrape, daemon=True).start()


@app.get("/api/songs", response_model=SongListResponse)
def get_songs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(0, ge=0, description="每页数量，0 表示返回全部"),
    search: str = Query("", description="搜索关键词（匹配文件名、标题、艺术家）"),
):
    sort_by = "title"
    sort_order = "asc"

    db_songs, total = query_songs(
        search=search, sort_by=sort_by, sort_order=sort_order,
        page=page, page_size=page_size,
    )

    songs = []
    for row in db_songs:
        song = Song(
            path=row["path"],
            filename=row["filename"],
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
            size=row["file_size"],
            has_cover=bool(row["has_cover"]),
            has_lyrics=bool(row["has_lyrics"]),
            title_initial=row["title_initial"],
            artist_initial=row["artist_initial"],
            album_initial=row["album_initial"],
            title_sort=row["title_sort"],
            artist_sort=row["artist_sort"],
            album_sort=row["album_sort"],
        )
        songs.append(song)

    final_total = total
    final_page_size = page_size if page_size > 0 else total

    return SongListResponse(
        total=final_total,
        page=page,
        page_size=final_page_size,
        songs=songs,
    )

@app.get("/api/stream")
def stream_music(path: str = Query(..., description="歌曲文件路径")):
    """
    流式传输音乐文件
    
    Args:
        path: 经过URL编码的音乐文件路径
        
    Returns:
        FileResponse: 音频文件流
    """
    # 验证路径安全性
    safe_path = validate_and_safe_path(path)
    
    # 根据文件扩展名确定媒体类型
    ext = os.path.splitext(safe_path)[1].lower()
    media_types = {
        '.mp3': 'audio/mpeg',
        '.flac': 'audio/flac',
        '.m4a': 'audio/mp4',
        '.wav': 'audio/wav',
        '.ogg': 'audio/ogg'
    }
    
    media_type = media_types.get(ext, 'audio/mpeg')
    
    return FileResponse(
        safe_path, 
        media_type=media_type, 
        filename=os.path.basename(safe_path)
    )

@app.get("/api/cover")
def get_cover(path: str = Query(..., description="歌曲文件路径")):
    """
    获取歌曲封面

    Args:
        path: 经过URL编码的音乐文件路径

    Returns:
        StreamingResponse: 图片数据流
    """
    safe_path = validate_and_safe_path(path)

    # 1. 从数据库缓存查询
    cached_cover = get_cover_cache(safe_path)
    if cached_cover:
        return FileResponse(cached_cover)

    # 2. 尝试读取文件内嵌封面 + 同时解析元数据
    artist = "未知艺术家"
    title = os.path.splitext(os.path.basename(safe_path))[0]

    try:
        audio = mutagen.File(safe_path)
        if audio:
            if 'TIT2' in audio:
                title = str(audio['TIT2'])
            elif 'title' in audio:
                title = str(audio['title'][0])
            if 'TPE1' in audio:
                artist = str(audio['TPE1'])
            elif 'artist' in audio:
                artist = str(audio['artist'][0])

            if hasattr(audio, 'tags'):
                for key in audio.tags.keys():
                    if key.startswith('APIC'):
                        pic = audio.tags[key]
                        # 写入数据库缓存
                        cache_name = get_cache_filename(artist, title)
                        cached_file = os.path.join(COVER_DIR, cache_name + ".jpg")
                        try:
                            with open(cached_file, 'wb') as f:
                                f.write(pic.data)
                            set_cover_cache(safe_path, cached_file, source="embedded")
                        except Exception as e:
                            print(f"[警告] 缓存内嵌封面失败: {e}")
                        return StreamingResponse(BytesIO(pic.data), media_type=pic.mime)
                if 'covr' in audio.tags:
                    pic_data = audio.tags['covr'][0]
                    cache_name = get_cache_filename(artist, title)
                    cached_file = os.path.join(COVER_DIR, cache_name + ".jpg")
                    try:
                        with open(cached_file, 'wb') as f:
                            f.write(pic_data)
                        set_cover_cache(safe_path, cached_file, source="embedded")
                    except Exception as e:
                        print(f"[警告] 缓存内嵌封面失败: {e}")
                    return StreamingResponse(BytesIO(pic_data), media_type="image/jpeg")
            if hasattr(audio, 'pictures') and audio.pictures:
                pic = audio.pictures[0]
                cache_name = get_cache_filename(artist, title)
                cached_file = os.path.join(COVER_DIR, cache_name + ".jpg")
                try:
                    with open(cached_file, 'wb') as f:
                        f.write(pic.data)
                    set_cover_cache(safe_path, cached_file, source="embedded")
                except Exception as e:
                    print(f"[警告] 缓存内嵌封面失败: {e}")
                return StreamingResponse(BytesIO(pic.data), media_type=pic.mime)
    except Exception as e:
        print(f"[警告] 读取音频文件失败: {e}")

    # 3. 尝试查找文件缓存封面
    cache_name = get_cache_filename(artist, title)
    cached_file = os.path.join(COVER_DIR, cache_name + ".jpg")
    if os.path.exists(cached_file):
        # 写入数据库缓存
        set_cover_cache(safe_path, cached_file, source="scraped")
        return FileResponse(cached_file)

    # 4. 都没有，返回默认封面
    default_cover_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#334155">
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 14.5c-2.49 0-4.5-2.01-4.5-4.5S9.51 7.5 12 7.5s4.5 2.01 4.5 4.5-2.01 4.5-4.5 4.5zm0-5.5c-.55 0-1 .45-1 1s.45 1 1 1 1-.45 1-1-.45-1-1-1z"/>
    </svg>"""

    return StreamingResponse(
        BytesIO(default_cover_svg.encode('utf-8')),
        media_type="image/svg+xml",
        headers={"Cache-Control": "max-age=3600"}
    )

@app.get("/api/lyrics")
def get_lyrics(path: str = Query(..., description="歌曲文件路径")):
    """
    按需获取歌词内容

    Args:
        path: 经过URL编码的音乐文件路径

    Returns:
        JSON: { lyrics: str }
    """
    safe_path = validate_and_safe_path(path)

    # 1. 从数据库缓存查询
    db_lrc = get_lyrics_cache(safe_path)
    if db_lrc:
        return {"lyrics": db_lrc}

    # 2. 尝试读取同目录下的 .lrc 文件
    lrc_path = os.path.splitext(safe_path)[0] + ".lrc"
    if os.path.exists(lrc_path):
        try:
            with open(lrc_path, 'r', encoding='utf-8', errors='ignore') as f:
                lrc_text = f.read()
                set_lyrics_cache(safe_path, lrc_text, source="local")
                return {"lyrics": lrc_text}
        except Exception as e:
            print(f"[警告] 读取本地歌词失败: {e}")

    # 3. 尝试读取文件缓存歌词（从 DB 取元数据，避免重复解析 mutagen）
    song_row = get_song_by_path(safe_path)
    if song_row:
        artist = song_row["artist"]
        title = song_row["title"]
    else:
        artist = "未知艺术家"
        title = os.path.splitext(os.path.basename(safe_path))[0]

    cache_name = get_cache_filename(artist, title)
    cached_lrc = os.path.join(LYRIC_DIR, cache_name + ".lrc")
    if os.path.exists(cached_lrc):
        try:
            with open(cached_lrc, 'r', encoding='utf-8') as f:
                lrc_text = f.read()
                set_lyrics_cache(safe_path, lrc_text, source="scraped")
                return {"lyrics": lrc_text}
        except Exception as e:
            print(f"[警告] 读取缓存歌词失败: {e}")

    return {"lyrics": ""}

# 健康检查接口
@app.get("/api/health")
def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "music_dir": MUSIC_DIR,
        "cors_allowed_origins_regex": ALLOWED_ORIGINS_REGEX,
        "timestamp": time.time()
    }

# 静态文件服务
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# 404处理
@app.exception_handler(404)
async def custom_404_handler(request, exc):
    return FileResponse("static/index.html")