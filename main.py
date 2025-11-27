import os
import hashlib
import requests
import threading
import time
import urllib.parse
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import mutagen
from pydantic import BaseModel
from typing import List, Optional
from io import BytesIO

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MUSIC_DIR = "/music"
CACHE_DIR = "/app/cache"
LYRIC_DIR = os.path.join(CACHE_DIR, "lyrics")
COVER_DIR = os.path.join(CACHE_DIR, "covers")

# 创建缓存目录
os.makedirs(LYRIC_DIR, exist_ok=True)
os.makedirs(COVER_DIR, exist_ok=True)

class Song(BaseModel):
    path: str
    filename: str
    title: Optional[str] = None
    artist: Optional[str] = "未知艺术家"
    album: Optional[str] = "未知专辑"
    size: str = "0 MB"
    has_cover: bool = False
    lyrics: str = "" 
    scraped: bool = False # 标记是否已经完成刮削

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

@app.on_event("startup")
async def startup_event():
    """
    服务器启动时，读取一次列表，然后启动后台线程去刮削
    """
    # 这里我们只做触发，具体扫描在 get_songs 第一次调用或者单独逻辑里
    # 为了简化，我们让第一次访问列表时触发，或者在这里先扫一遍
    pass 

@app.get("/api/songs", response_model=List[Song])
def get_songs():
    songs = []
    need_scrape_list = []

    for root, dirs, files in os.walk(MUSIC_DIR):
        for file in files:
            if file.lower().endswith(('.mp3', '.flac', '.m4a')):
                full_path = os.path.join(root, file)
                song_info = Song(path=full_path, filename=file, title=os.path.splitext(file)[0])
                
                try:
                    song_info.size = get_file_size_mb(full_path)
                    try:
                        audio = mutagen.File(full_path)
                        if audio:
                            if 'TIT2' in audio: song_info.title = str(audio['TIT2'])
                            elif 'title' in audio: song_info.title = str(audio['title'][0])
                            
                            if 'TPE1' in audio: song_info.artist = str(audio['TPE1'])
                            elif 'artist' in audio: song_info.artist = str(audio['artist'][0])
                            
                            if 'TALB' in audio: song_info.album = str(audio['TALB'])
                            elif 'album' in audio: song_info.album = str(audio['album'][0])

                            # 检查内嵌封面
                            if hasattr(audio, 'tags'):
                                if 'APIC:' in audio.tags or 'APIC' in audio.tags: song_info.has_cover = True
                                elif 'covr' in audio.tags: song_info.has_cover = True
                                elif hasattr(audio, 'pictures') and audio.pictures: song_info.has_cover = True
                    except: pass
                    
                    # 关联缓存歌词
                    # 1. 本地 lrc
                    lrc_path = os.path.splitext(full_path)[0] + ".lrc"
                    if os.path.exists(lrc_path):
                        with open(lrc_path, 'r', encoding='utf-8', errors='ignore') as f:
                            song_info.lyrics = f.read()
                    else:
                        # 2. 缓存 lrc
                        cache_name = get_cache_filename(song_info.artist, song_info.title)
                        cached_lrc = os.path.join(LYRIC_DIR, cache_name + ".lrc")
                        if os.path.exists(cached_lrc):
                            with open(cached_lrc, 'r', encoding='utf-8') as f:
                                song_info.lyrics = f.read()

                    # 如果没有内嵌封面，检查有没有缓存封面，更新标记
                    if not song_info.has_cover:
                        cache_name = get_cache_filename(song_info.artist, song_info.title)
                        if os.path.exists(os.path.join(COVER_DIR, cache_name + ".jpg")):
                            song_info.has_cover = True # 欺骗前端说有封面，前端会来调 /api/cover

                except Exception as e:
                    print(f"Error: {e}")
                
                songs.append(song_info)
                need_scrape_list.append(song_info)

    songs.sort(key=lambda x: x.filename)

    # 启动后台线程进行刮削 (只在未运行时启动，防止多重线程)
    # 使用 Daemon 线程，主程序退出它也会退出
    if threading.active_count() < 5: # 简单判断，防止重复开启大量线程
        t = threading.Thread(target=scrape_metadata_background, args=(need_scrape_list,), daemon=True)
        t.start()

    return songs

@app.get("/api/stream")
def stream_music(path: str):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="audio/mpeg", filename=os.path.basename(path))

@app.get("/api/cover")
def get_cover(path: str):
    """获取封面：优先内嵌 -> 其次缓存"""
    # 1. 尝试读取文件内嵌
    try:
        audio = mutagen.File(path)
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
    except: pass

    # 2. 如果内嵌失败，尝试查找缓存文件
    try:
        # 重新解析一下 Artist/Title 算 Hash
        audio = mutagen.File(path) # 再读一次为了保险获取 Tag
        artist = "未知艺术家"
        title = os.path.splitext(os.path.basename(path))[0]
        if audio:
            if 'TIT2' in audio: title = str(audio['TIT2'])
            elif 'title' in audio: title = str(audio['title'][0])
            if 'TPE1' in audio: artist = str(audio['TPE1'])
            elif 'artist' in audio: artist = str(audio['artist'][0])
        
        cache_name = get_cache_filename(artist, title)
        cached_cover = os.path.join(COVER_DIR, cache_name + ".jpg")
        
        if os.path.exists(cached_cover):
             return FileResponse(cached_cover)
    except: pass

    # 都没有
    raise HTTPException(status_code=404)

app.mount("/", StaticFiles(directory="static", html=True), name="static")