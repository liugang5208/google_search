@echo off
setlocal EnableDelayedExpansion

echo ================================================
echo  SEO Rank Checker - Windows Build Script
echo  Target: Python 3.8 / Win7 + Win10 + Win11
echo ================================================
echo.

:: Check Python 3.8
py -3.8 --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.8 not found.
    echo   Please install Python 3.8 from:
    echo   https://www.python.org/downloads/release/python-3810/
    echo   Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)
echo [OK] Python 3.8 found:
py -3.8 --version

:: Install dependencies under Python 3.8
echo.
echo [Step 1/3] Installing dependencies...
py -3.8 -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
py -3.8 -m pip install selenium webdriver-manager beautifulsoup4 requests pyinstaller undetected-chromedriver -q -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. Try running as Administrator.
    pause
    exit /b 1
)
echo [OK] Dependencies installed

:: Clean old build
echo.
echo [Step 2/3] Cleaning old build...
if exist "dist\SEO_Rank_Checker.exe" del /f /q "dist\SEO_Rank_Checker.exe"
if exist "build"                      rmdir /s /q "build"
if exist "SEO_Rank_Checker.spec"      del /f /q "SEO_Rank_Checker.spec"
echo [OK] Clean done

:: PyInstaller build (onefile)
echo.
echo [Step 3/3] Building single EXE (this may take 3-8 minutes)...

py -3.8 -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "SEO_Rank_Checker" ^
    --add-binary "chromedriver.exe;." ^
    --hidden-import selenium ^
    --hidden-import selenium.webdriver ^
    --hidden-import selenium.webdriver.chrome ^
    --hidden-import selenium.webdriver.chrome.service ^
    --hidden-import selenium.webdriver.chrome.options ^
    --hidden-import selenium.webdriver.support.ui ^
    --hidden-import selenium.webdriver.support.expected_conditions ^
    --hidden-import webdriver_manager ^
    --hidden-import webdriver_manager.chrome ^
    --hidden-import bs4 ^
    --hidden-import requests ^
    --hidden-import xml.etree.ElementTree ^
    --hidden-import tkinter ^
    --hidden-import tkinter.ttk ^
    --hidden-import tkinter.messagebox ^
    --hidden-import tkinter.filedialog ^
    --collect-all webdriver_manager ^
    --collect-all selenium ^
    --collect-all certifi ^
    seo_rank_checker.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check the error messages above.
    pause
    exit /b 1
)

echo.
echo ================================================
echo  Build complete!
echo  Output: dist\SEO_Rank_Checker.exe
echo ================================================
echo.
echo [Notes]
echo  - The EXE is a single file, no extra folders needed.
echo  - Target machine must have Google Chrome installed.
echo  - For Win7: install Microsoft Visual C++ 2015-2022 Redistributable
echo      https://aka.ms/vs/17/release/vc_redist.x64.exe
echo ================================================
echo.

set /p OPEN_DIR="Open output folder? (y/n): "
if /i "!OPEN_DIR!"=="y" explorer "dist"

pause
