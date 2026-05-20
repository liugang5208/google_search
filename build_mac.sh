#!/bin/bash
# SEO 排名检测工具 - macOS 打包脚本
set -e

echo "================================================"
echo " SEO 排名检测工具 - macOS App 打包脚本"
echo "================================================"
echo ""

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3，请先安装"
    exit 1
fi
echo "[OK] $(python3 --version)"

# 安装依赖
echo ""
echo "[步骤 1/3] 安装依赖..."
python3 -m pip install --upgrade pip -q
python3 -m pip install selenium webdriver-manager beautifulsoup4 requests pyinstaller undetected-chromedriver -q
echo "[OK] 依赖安装完成"

# 清理
echo ""
echo "[步骤 2/3] 清理旧构建..."
rm -rf dist/SEO排名检测 build

# 打包
echo ""
echo "[步骤 3/3] 开始打包..."
pyinstaller \
    --noconfirm \
    --onedir \
    --windowed \
    --name "SEO排名检测" \
    --hidden-import selenium \
    --hidden-import webdriver_manager \
    --hidden-import webdriver_manager.chrome \
    --hidden-import bs4 \
    --hidden-import requests \
    --collect-all webdriver_manager \
    --collect-all selenium \
    --hidden-import undetected_chromedriver \
    --collect-all undetected_chromedriver \
    seo_rank_checker.py

echo ""
echo "================================================"
echo " 打包完成！"
echo " 输出: dist/SEO排名检测/"
echo "================================================"
