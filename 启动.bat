@echo off
setlocal enabledelayedexpansion
title Flight Procedure Analyzer v2.0

cd /d "%~dp0"

echo.
echo   ================================================
echo     Flight Procedure Analyzer v2.0
echo     Integrated: Runway / Helipad / Route Mgmt
echo                Data Import / Analysis / Takeoff
echo   ================================================
echo.

:: Step 1 - Check Python
echo   [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python not found. Install Python 3.10+
    echo           https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo         Python %%v [OK]

:: Step 2 - Setup venv
echo.
echo   [2/5] Setting up Python venv...
set "VENV_DIR=backend\venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

set "VENV_OK=0"
if exist "%VENV_PYTHON%" (
    call "%VENV_PYTHON%" --version >nul 2>&1
    if not errorlevel 1 set "VENV_OK=1"
)

if "!VENV_OK!"=="0" (
    if exist "%VENV_DIR%" (
        echo         Invalid venv detected, recreating...
        rmdir /s /q "%VENV_DIR%" >nul 2>&1
    )
    echo         Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo   [ERROR] Failed to create venv
        pause
        exit /b 1
    )
    echo         Venv created [OK]
) else (
    echo         Venv ready [OK]
)

call "%VENV_DIR%\Scripts\activate.bat" >nul 2>&1

:: Step 3 - Install dependencies
echo.
echo   [3/5] Checking Python dependencies...
python -c "import fastapi, shapely, pyproj" >nul 2>&1
if errorlevel 1 (
    echo         Installing dependencies...
    pip install -r backend\requirements.txt -q 2>nul
    if errorlevel 1 (
        echo         Trying mirror...
        pip install -r backend\requirements.txt -q -i https://pypi.tuna.tsinghua.edu.cn/simple 2>nul
        if errorlevel 1 (
            echo   [WARN] Dependency install failed, trying to continue...
        )
    )
)
echo         Dependencies ready [OK]

:: Step 4 - Check frontend build
echo.
echo   [4/5] Checking frontend build...

if exist "frontend\dist\index.html" (
    echo         Using existing build [OK]
) else (
    echo         Building frontend...
    node --version >nul 2>&1
    if errorlevel 1 (
        echo   [WARN] Node.js not found, cannot build frontend
        echo         Running in API-only mode
    ) else (
        cd frontend
        if not exist "node_modules\" (
            echo         Installing npm packages...
            call npm install --registry=https://registry.npmmirror.com >nul 2>&1
        )
        echo         Building...
        call npm run build >nul 2>&1
        cd ..
        if exist "frontend\dist\index.html" (
            echo         Build complete [OK]
        ) else (
            echo   [WARN] Build failed, running in API-only mode
        )
    )
)

:: Step 5 - Start server
echo.
echo   [5/5] Starting server...

:: Kill existing process on port 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do (
    echo         Port 8000 in use (PID: %%a), releasing...
    taskkill /PID %%a /F >nul 2>&1
    timeout /t 1 /nobreak >nul
)

echo.
echo   ================================================
echo     Starting server...
echo.
echo     Frontend:  http://localhost:8000
echo     API Docs:  http://localhost:8000/docs
echo.
echo     Press Ctrl+C to stop
echo   ================================================
echo.

:: Open browser
start "" http://localhost:8000

:: Start backend
cd /d "%~dp0backend"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level warning

echo.
echo   Server stopped.
pause
