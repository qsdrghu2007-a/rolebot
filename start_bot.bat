@echo off
chcp 65001 >nul
echo ========================================
echo   Telegram Chatbot Launcher
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.8+
    pause
    exit /b 1
)

echo Checking dependencies...
python -c "import telegram, requests, yaml, tenacity, colorama" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Missing packages. Run: pip install -r requirements.txt
    pause
)

if not exist "config.yaml" (
    echo [INFO] config.yaml not found. Launching setup...
    python setup.py
    if errorlevel 1 (
        pause
        exit /b 1
    )
)

echo Starting bot...
python main.py
pause
