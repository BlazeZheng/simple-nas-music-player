#!/bin/bash

# 1. 进入工作目录
cd /app

# 2. 设置国内镜像源（为了下载速度更快，防止卡住）
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 安装依赖库
# 注意：Docker容器重启后，原本装好的包可能会消失（取决于容器类型），
# 所以每次启动时运行一次安装命令是最保险的。pip会自动跳过已安装的包，不会浪费时间。
echo "正在检查并安装依赖库..."
pip install -r requirements.txt

# 4. 启动播放器
echo "正在启动播放器..."
# 通过环境变量 HOST/PORT/RELOAD 控制，默认 0.0.0.0:8000 无热重载
UVICORN_HOST=${HOST:-0.0.0.0}
UVICORN_PORT=${PORT:-8000}
UVICORN_ARGS="--host $UVICORN_HOST --port $UVICORN_PORT"
if [ "${RELOAD:-0}" = "1" ]; then
    UVICORN_ARGS="$UVICORN_ARGS --reload"
fi
uvicorn main:app $UVICORN_ARGS