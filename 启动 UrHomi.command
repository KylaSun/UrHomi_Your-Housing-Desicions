#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
echo "UrHomi 工作台：http://127.0.0.1:8765"
echo "请保持此窗口运行。若提示端口占用，已有服务可能正在运行。"
exec python3 apps/server/server.py
