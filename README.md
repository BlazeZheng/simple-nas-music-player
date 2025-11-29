# Simple NAS Music Player (光辉永恒播放器)

## 关于这个音乐播放器的由来
我在单位和家里工作时经常会开播放器听歌，但是收集的歌曲太多，导致单位电脑要存一份，家里电脑还要存一份，自从搭建的家里的NAS环境后就一直想把歌曲放在NAS上面用网页版播放器听歌。找了很多款都不太适合我的需求，我要求很简单，随机播放、歌词封面刮削，就这两个，于是决定自己动手写一个简单的播放器，用了半天的时间就有了下面这个项目，个人使用，纯娱乐编程。

## The Origin of This Music Player
I often listen to music while working, both at the office and at home. However, with such a large collection of songs, I had to store a copy on my work computer and another on my home computer. After setting up my home NAS, I’ve been wanting to host my music library on the NAS and use a web-based player to listen to my songs. I tried many options, but none quite fit my needs. My requirements are simple: shuffle play and lyrics/cover scraping. So, I decided to create a simple player myself. In just half a day, this project came to life—made for personal use, purely as a hobby programming endeavor.

![image](https://github.com/BlazeZheng/simple-nas-music-player/blob/main/%E5%85%89%E8%BE%89%E6%92%AD%E6%94%BE%E5%99%A8.png)

[English](#-english) | [中文](#-中文说明)

<a name="-english"></a>
## 🇬🇧 English

A lightweight, modern, and aesthetically pleasing web-based music player designed for NAS (Network Attached Storage). Built with **FastAPI** (Backend) and **Vue 3** (Frontend), it features a beautiful UI, automatic background metadata scraping, and requires **NO database** setup.

### ✨ Features
- **Zero Configuration**: No MySQL/Redis required. Just point it to your music folder.
- **Modern UI**: Built with Tailwind CSS. Features glassmorphism design, vinyl rotation animations, and responsive layout.
- **Background Scraping**: Automatically fetches lyrics and cover art from `lrc.cx` in the background without blocking the UI.
- **Local Priority**: Prioritizes embedded ID3 tags and local lyrics files (`.lrc`).
- **Playback Controls**: Supports Loop (List/Single), Shuffle, and Media Session API.
- **Mobile Friendly**: Works perfectly on mobile browsers as a web app.

### 🚀 Quick Start (Docker)

You can easily run this player using Docker.

#### 1. Clone the repository
Download the source code to your NAS or server.

#### 2. Run with Docker
Replace `/volume1/music` `/volume1/blazeplayer/app` with your actual music & app folder path.

```bash
docker run -d \
  --name nas-music \
  --restart unless-stopped \
  -p 8000:8000 \
  -v /volume1/music:/music \
  -v /volume1/blazeplayer/app:/app \
  python:3.9-slim \
  /bin/bash /app/start.sh
```
### 🛠 Tech Stack
- Backend: Python FastAPI, Uvicorn
- Frontend: Vue.js 3, Tailwind CSS
- Audio Processing: Mutagen
- Networking: Requests
### 📡 API Usage
- Stream: GET /api/stream?path=...
- Cover Art: GET /api/cover?path=...
- Metadata: GET /api/songs

## Update Log - November 30, 2025:
- Added sort buttons for the song library, allowing sorting by song title, artist name, and album name. Repeatedly clicking the same button toggles between ascending and descending order.
- Added A-Z quick selection functionality.
- Added hotkey support.
- The song list on the left now automatically scrolls to and highlights the currently playing song.
- Fixed a bug where FLAC files would not automatically switch to the next track during playback.


---

<a name="-中文说明"></a>
## 🇨🇳 中文说明

一款专为 NAS 设计的轻量级、高颜值网页音乐播放器。使用 FastAPI 和 Vue 3 开发。它拥有现代化的界面设计，支持后台自动刮削元数据，且无需复杂的数据库配置，开箱即用。

###✨ 主要功能
- 零配置: 不需要安装 MySQL 或 Redis，直接读取文件目录即可播放。
- 高颜值界面: 使用 Tailwind CSS 打造的磨砂玻璃质感 UI，带有黑胶唱片旋转动画。
- 后台刮削: 播放器会在后台静默调用 lrc.cx API 获取缺失的歌词和封面，完全不卡顿前端界面。
- 本地优先: 优先读取音乐文件内嵌的封面和 Tag 信息，以及同目录下的 .lrc 歌词文件。
- 播放控制: 支持列表循环、单曲循环、随机播放、音量控制。
- 移动端适配: 完美支持手机浏览器访问。

### 🚀 安装方法 (Docker)
推荐使用 Docker 进行部署，无需配置 Python 环境。
#### 1. 下载代码
将本项目代码下载到你的 NAS 或服务器文件夹中。
#### 2. 运行命令
进入代码所在目录，执行以下命令（请将 `/volume1/music` `/volume1/blazeplayer/app` 替换为你实际的音乐和代码文件夹路径）：

```bash
docker run -d \
  --name nas-music \
  --restart unless-stopped \
  -p 8000:8000 \
  -v /volume1/music:/music \
  -v /volume1/blazeplayer/app:/app \
  python:3.9-slim \
  /bin/bash /app/start.sh
```
注意：首次启动时，程序会自动在代码目录下的 cache 文件夹中生成 lyrics 和 covers 目录，用于存储刮削的数据。
### 🛠 技术栈
- 后端: Python FastAPI
- 前端: Vue.js 3 (CDN引入), Tailwind CSS
- 音频处理: Mutagen
- 网络请求: Requests
### 🤝 致谢
- 歌词与封面 API 由 Lrc.cx 提供支持。
- 图标库使用 RemixIcon。

## 2025.11.30 升级内容：
- 增加歌曲目录排序按钮，可以根据歌名、歌手名及专辑名排序。多次点击同一按钮支持正序和倒序。
- 增加A-Z快速选择功能。
- 增加热键功能。
- 左侧歌曲列表会自动跳转到当前正在播放的歌曲。
- 修复播放FLAC歌曲时不能自动切换歌曲的BUG。





