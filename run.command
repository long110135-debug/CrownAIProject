#!/bin/bash
# 皇冠AI赛事研判系统 - 一键运行
# 双击此文件即可运行每日分析

cd "$(dirname "$0")"

echo "=================================="
echo "  皇冠AI赛事研判系统 启动中..."
echo "=================================="
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到python3，请先安装Python"
    read -p "按回车退出..."
    exit 1
fi

# 检查依赖
python3 -c "import playwright" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "安装依赖: playwright..."
    pip3 install playwright --quiet
    python3 -m playwright install chromium --quiet
fi

python3 -c "import requests" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "安装依赖: requests..."
    pip3 install requests --quiet
fi

# 运行主程序
python3 main.py

echo ""
echo "=================================="
echo "  运行完毕"
echo "=================================="
read -p "按回车退出..."
