import os
import hashlib
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

app = FastAPI()

# CORS配置 - 限制允许的域名
# 在生产环境中应设置为具体的域名，如 ["https://yourdomain.com", "http://localhost:8080"]
# 这里假设允许本地开发和NAS内网访问
ALLOWED_ORIGINS = [
    "http://localhost:*",
    "http://127.0.0.1:*",
    "http://*.local",
    "https://*.local",
    "http://192.168.*.*",  # 内网IP段
    "http://10.*.*.*",     # 内网IP段
    "http://172.16.*.*",   # 内网IP段
    "http://172.17.*.*",
    "http://172.18.*.*",
    "http://172.19.*.*",
    "http://172.20.*.*",
    "http://172.21.*.*",
    "http://172.22.*.*",
    "http://172.23.*.*",
    "http://172.24.*.*",
    "http://172.25.*.*",
    "http://172.26.*.*",
    "http://172.27.*.*",
    "http://172.28.*.*",
    "http://172.29.*.*",
    "http://172.30.*.*",
    "http://172.31.*.*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

MUSIC_DIR = "/music"
CACHE_DIR = "/app/cache"
LYRIC_DIR = os.path.join(CACHE_DIR, "lyrics")
COVER_DIR = os.path.join(CACHE_DIR, "covers")

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
        
        # 检查路径是否在基础目录内
        if not abs_user_path.startswith(abs_base_dir):
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
    lyrics: str = "" 
    scraped: bool = False
    # 新增首字母字段
    title_initial: Optional[str] = ""
    artist_initial: Optional[str] = ""
    album_initial: Optional[str] = ""
    # 新增排序字段
    title_sort: Optional[str] = ""
    artist_sort: Optional[str] = ""
    album_sort: Optional[str] = ""

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

# --- 新 API 刮削逻辑 (api.lrc.cx) ---
def scrape_metadata_background(songs_list):
    """
    后台线程：遍历所有歌曲，如果没有缓存，就去下载
    """
    print(f"--- 后台刮削服务启动，待处理歌曲: {len(songs_list)} 首 ---")
    
    for song in songs_list:
        # 如果是未知艺术家，通常没法刮削，跳过
        if song.artist == "未知艺术家" or not song.title:
            continue

        cache_name = get_cache_filename(song.artist, song.title)
        lrc_file = os.path.join(LYRIC_DIR, cache_name + ".lrc")
        cover_file = os.path.join(COVER_DIR, cache_name + ".jpg")

        # 1. 处理歌词
        if not os.path.exists(lrc_file):
            try:
                # API: https://api.lrc.cx/lyrics?title=xxx&artist=xxx
                params = {"title": song.title, "artist": song.artist}
                if song.album != "未知专辑":
                    params["album"] = song.album
                
                print(f"[刮削歌词] {song.title} - {song.artist}")
                resp = requests.get("https://api.lrc.cx/lyrics", params=params, timeout=10)
                
                if resp.status_code == 200 and resp.text:
                    with open(lrc_file, 'w', encoding='utf-8') as f:
                        f.write(resp.text)
            except Exception as e:
                print(f"[错误] 歌词下载失败: {e}")

        # 2. 处理封面
        if not os.path.exists(cover_file) and not song.has_cover:
            try:
                # API: https://api.lrc.cx/cover?title=xxx&artist=xxx
                params = {"title": song.title, "artist": song.artist}
                if song.album != "未知专辑":
                    params["album"] = song.album

                print(f"[刮削封面] {song.title} - {song.artist}")
                resp = requests.get("https://api.lrc.cx/cover", params=params, timeout=10)
                
                # 检查返回的是否是图片
                content_type = resp.headers.get('content-type', '')
                if resp.status_code == 200 and 'image' in content_type:
                    with open(cover_file, 'wb') as f:
                        f.write(resp.content)
            except Exception as e:
                print(f"[错误] 封面下载失败: {e}")

        # 礼貌等待，避免触发 API 速率限制 (每首歌间隔 1 秒)
        time.sleep(1)

    print("--- 后台刮削任务完成 ---")

# --- 核心接口 ---

@app.get("/api/songs", response_model=List[Song])
def get_songs():
    songs = []
    need_scrape_list = []

    for root, dirs, files in os.walk(MUSIC_DIR):
        for file in files:
            if file.lower().endswith(('.mp3', '.flac', '.m4a')):
                full_path = os.path.join(root, file)
                # 使用文件名作为默认标题
                default_title = os.path.splitext(file)[0]
                song_info = Song(
                    path=full_path, 
                    filename=file, 
                    title=default_title,
                    # 初始化首字母字段
                    title_initial=get_initials(default_title),
                    artist_initial="#",
                    album_initial="#",
                    # 初始化排序字段
                    title_sort=get_sort_key(default_title),
                    artist_sort=get_sort_key("未知艺术家"),
                    album_sort=get_sort_key("未知专辑")
                )
                
                try:
                    song_info.size = get_file_size_mb(full_path)
                    try:
                        audio = mutagen.File(full_path)
                        if audio:
                            # 读取元数据
                            if 'TIT2' in audio: 
                                song_info.title = str(audio['TIT2'])
                            elif 'title' in audio: 
                                song_info.title = str(audio['title'][0])
                            
                            if 'TPE1' in audio: 
                                song_info.artist = str(audio['TPE1'])
                            elif 'artist' in audio: 
                                song_info.artist = str(audio['artist'][0])
                            
                            if 'TALB' in audio: 
                                song_info.album = str(audio['TALB'])
                            elif 'album' in audio: 
                                song_info.album = str(audio['album'][0])

                            # 计算首字母和排序键
                            song_info.title_initial = get_initials(song_info.title)
                            song_info.artist_initial = get_initials(song_info.artist)
                            song_info.album_initial = get_initials(song_info.album)
                            
                            song_info.title_sort = get_sort_key(song_info.title)
                            song_info.artist_sort = get_sort_key(song_info.artist)
                            song_info.album_sort = get_sort_key(song_info.album)

                            # 检查内嵌封面
                            if hasattr(audio, 'tags'):
                                if 'APIC:' in audio.tags or 'APIC' in audio.tags: 
                                    song_info.has_cover = True
                                elif 'covr' in audio.tags: 
                                    song_info.has_cover = True
                                elif hasattr(audio, 'pictures') and audio.pictures: 
                                    song_info.has_cover = True
                    except Exception as e:
                        print(f"Error reading audio metadata: {e}")
                    
                    # 关联缓存歌词
                    lrc_path = os.path.splitext(full_path)[0] + ".lrc"
                    if os.path.exists(lrc_path):
                        with open(lrc_path, 'r', encoding='utf-8', errors='ignore') as f:
                            song_info.lyrics = f.read()
                    else:
                        cache_name = get_cache_filename(song_info.artist, song_info.title)
                        cached_lrc = os.path.join(LYRIC_DIR, cache_name + ".lrc")
                        if os.path.exists(cached_lrc):
                            with open(cached_lrc, 'r', encoding='utf-8') as f:
                                song_info.lyrics = f.read()

                    # 检查缓存封面
                    if not song_info.has_cover:
                        cache_name = get_cache_filename(song_info.artist, song_info.title)
                        if os.path.exists(os.path.join(COVER_DIR, cache_name + ".jpg")):
                            song_info.has_cover = True

                except Exception as e:
                    print(f"Error processing song {file}: {e}")
                
                songs.append(song_info)
                need_scrape_list.append(song_info)

    # 默认按文件名排序
    songs.sort(key=lambda x: x.filename)

    # 启动后台刮削线程
    if threading.active_count() < 5:
        t = threading.Thread(target=scrape_metadata_background, args=(need_scrape_list,), daemon=True)
        t.start()

    return songs

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
    # 验证路径安全性
    safe_path = validate_and_safe_path(path)
    
    # 1. 尝试读取文件内嵌
    try:
        audio = mutagen.File(safe_path)
        if audio:
            # MP3
            if hasattr(audio, 'tags'):
                for key in audio.tags.keys():
                    if key.startswith('APIC'):
                        pic = audio.tags[key]
                        return StreamingResponse(BytesIO(pic.data), media_type=pic.mime)
                # M4A
                if 'covr' in audio.tags:
                    return StreamingResponse(BytesIO(audio.tags['covr'][0]), media_type="image/jpeg")
            # FLAC
            if hasattr(audio, 'pictures') and audio.pictures:
                pic = audio.pictures[0]
                return StreamingResponse(BytesIO(pic.data), media_type=pic.mime)
    except Exception as e:
        print(f"[警告] 读取内嵌封面失败: {e}")
        pass

    # 2. 如果内嵌失败，尝试查找缓存文件
    try:
        # 重新解析一下 Artist/Title 算 Hash
        audio = mutagen.File(safe_path)  # 再读一次为了保险获取 Tag
        artist = "未知艺术家"
        title = os.path.splitext(os.path.basename(safe_path))[0]
        if audio:
            if 'TIT2' in audio: 
                title = str(audio['TIT2'])
            elif 'title' in audio: 
                title = str(audio['title'][0])
            if 'TPE1' in audio: 
                artist = str(audio['TPE1'])
            elif 'artist' in audio: 
                artist = str(audio['artist'][0])
        
        cache_name = get_cache_filename(artist, title)
        cached_cover = os.path.join(COVER_DIR, cache_name + ".jpg")
        
        if os.path.exists(cached_cover):
             return FileResponse(cached_cover)
    except Exception as e:
        print(f"[警告] 读取缓存封面失败: {e}")
        pass

    # 3. 都没有，返回默认封面
    default_cover_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#334155">
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 14.5c-2.49 0-4.5-2.01-4.5-4.5S9.51 7.5 12 7.5s4.5 2.01 4.5 4.5-2.01 4.5-4.5 4.5zm0-5.5c-.55 0-1 .45-1 1s.45 1 1 1 1-.45 1-1-.45-1-1-1z"/>
    </svg>"""
    
    return StreamingResponse(
        BytesIO(default_cover_svg.encode('utf-8')),
        media_type="image/svg+xml",
        headers={"Cache-Control": "max-age=3600"}
    )

# 健康检查接口
@app.get("/api/health")
def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "music_dir": MUSIC_DIR,
        "cors_allowed_origins": ALLOWED_ORIGINS[:3] if len(ALLOWED_ORIGINS) > 3 else ALLOWED_ORIGINS,
        "timestamp": time.time()
    }

# 静态文件服务
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# 404处理
@app.exception_handler(404)
async def custom_404_handler(request, exc):
    return FileResponse("static/index.html")
