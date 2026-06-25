@echo off
title Flight Procedure Analyzer v2.0

cd /d "%~dp0"

echo.
echo   ======================================
echo     Flight Procedure Analyzer v2.0
echo     Quick Start Mode
echo   ======================================
echo.

:: Kill existing server on port 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do (
    echo   Releasing port 8000 (PID: %%a)...
    taskkill /PID %%a /F >nul 2>&1
    timeout /t 1 /nobreak >nul
)

:: Activate venv
if exist "backend\venv\Scripts\activate.bat" (
    call backend\venv\Scripts\activate.bat >nul 2>&1
) else (
    echo   [ERROR] Virtual environment not found.
    echo   Please run setup.bat first.
    pause
    exit /b 1
)

:: Verify frontend exists
if not exist "frontend\dist\index.html" (
    echo   [WARN] Frontend not built. Run setup.bat first.
    echo.
    choice /c yn /m "Start in API-only mode?"
    if errorlevel 2 exit /b 0
)

echo   Starting server...
echo.
echo   Frontend:  http://localhost:8000
echo   API Docs:  http://localhost:8000/docs
echo   Press Ctrl+C to stop
echo   --------------------------------------

:: Open browser
start "" http://localhost:8000

:: Start server
cd /d "%~dp0backend"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level warning

echo.
echo   Server stopped.
pause
