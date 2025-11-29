#!/bin/bash

# 1. 进入工作目录
cd /app

# 2. 设置国内镜像源（为了下载速度更快，防止卡住）
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 安装依赖库
# 注意：Docker容器重启后，原本装好的包可能会消失（取决于容器类型），
# 所以每次启动时运行一次安装命令是最保险的。pip会自动跳过已安装的包，不会浪费时间。
echo "正在检查并安装依赖库..."
pip install fastapi uvicorn mutagen requests pypinyin

# 4. 启动播放器
echo "正在启动播放器..."
# --host 0.0.0.0 允许外网访问
# --reload 代码修改后自动重启（方便开发）
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
