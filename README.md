code

Markdown

\# Simple NAS Music Player (光辉永恒播放器)



\[English](#english) | \[中文](#chinese)



<a name="english"></a>

\## 🇬🇧 English



A lightweight, modern, and aesthetically pleasing web-based music player designed for NAS (Network Attached Storage). Built with \*\*FastAPI\*\* and \*\*Vue 3\*\*, it features a beautiful UI, automatic background metadata scraping, and requires no database setup.



\### Features

\- \*\*Zero Configuration\*\*: No database required. Just point it to your music folder.

\- \*\*Modern UI\*\*: Built with Vue 3 + Tailwind CSS. Features glassmorphism design, vinyl rotation animations, and responsive layout.

\- \*\*Background Scraping\*\*: Automatically fetches lyrics and cover art from `lrc.cx` in the background without blocking the UI.

\- \*\*Local Priority\*\*: Prioritizes embedded ID3 tags and local lyrics files.

\- \*\*Playback Controls\*\*: Supports Loop (List/Single), Shuffle, and Keyboard controls.

\- \*\*Mobile Friendly\*\*: Works perfectly on mobile browsers.



\### Installation (Docker)



You can easily run this player using Docker.



\#### 1. Directory Structure

Ensure you have a music directory on your host (e.g., `/volume1/music`).



\#### 2. Run with Docker CLI

```bash

docker run -d \\

&nbsp; --name nas-player \\

&nbsp; --restart unless-stopped \\

&nbsp; -p 8000:8000 \\

&nbsp; -v /path/to/your/music:/music \\

&nbsp; -v ./cache:/app/cache \\

&nbsp; ghplayer/simple-nas-player

Note: The metadata (lyrics/covers) will be saved in the mapped /app/cache directory.

API Usage

Cover Art API: GET /api/cover?path=...

Stream API: GET /api/stream?path=...

Credits

Lyrics and Cover Art API provided by Lrc.cx.

Frontend Icons by RemixIcon.

<a name="chinese"></a>

🇨🇳 中文说明

一款专为 NAS 设计的轻量级、高颜值网页音乐播放器。使用 FastAPI (后端) 和 Vue 3 (前端) 开发。它拥有现代化的界面设计，支持后台自动刮削元数据，且无需复杂的数据库配置，开箱即用。

主要功能

零配置: 不需要安装 MySQL 或 Redis，读取文件目录即可播放。

高颜值界面: 使用 Tailwind CSS 打造的磨砂玻璃质感 UI，带有黑胶唱片旋转动画。

后台刮削: 后台静默调用 lrc.cx API 获取歌词和封面，不卡顿前端界面。

本地优先: 优先读取音乐文件内嵌的封面和 Tag 信息，以及同名 .lrc 文件。

播放控制: 支持列表循环、单曲循环、随机播放。

移动端适配: 完美支持手机浏览器访问。

安装方法 (Docker)

推荐使用 Docker 进行部署。

1\. 准备目录

确保你有一个存放音乐的文件夹（例如群晖的 /volume1/music）。

2\. 运行命令

你可以直接构建镜像或者使用 Python 容器挂载运行：

code

Bash

docker run -d \\

&nbsp; --name nas-player \\

&nbsp; --restart unless-stopped \\

&nbsp; -p 8000:8000 \\

&nbsp; -v /你的音乐目录:/music \\

&nbsp; -v /你的缓存目录/cache:/app/cache \\

&nbsp; python:3.9-slim \\

&nbsp; /bin/bash -c "pip install fastapi uvicorn mutagen requests aiofiles python-multipart \&\& uvicorn main:app --host 0.0.0.0 --port 8000"

注意：程序会自动在挂载的 cache 目录下生成 lyrics 和 covers 文件夹用于存储刮削的数据。

技术栈

Backend: Python FastAPI

Frontend: Vue.js 3 (CDN), Tailwind CSS

Audio Decoding: Mutagen

致谢

歌词与封面 API 由 Lrc.cx 提供支持。

图标库使用 RemixIcon。

code

Code

---

