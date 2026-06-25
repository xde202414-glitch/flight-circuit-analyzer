@echo off
title Flight Circuit Analyzer - Dev Mode

set "ROOT=%~dp0"

echo ============================================
echo   Flight Circuit Analyzer v1.0.0
echo   One-Click Start (Frontend + Backend)
echo ============================================
echo.
echo   Working Dir: %ROOT%
echo.

REM === Check Backend ===
if not exist "%ROOT%backend\venv\Scripts\activate.bat" (
    echo [ERROR] Backend venv not found
    echo   %ROOT%backend\venv
    echo   Please create venv and install dependencies first
    goto :error
)

if not exist "%ROOT%backend\venv\Scripts\uvicorn.exe" (
    echo [ERROR] uvicorn not installed
    goto :error
)

REM === Check Frontend ===
if not exist "%ROOT%frontend\node_modules\.bin\vite.cmd" (
    echo [ERROR] Frontend dependencies not found
    echo   %ROOT%frontend\node_modules
    echo   Please run: cd /d "%ROOT%frontend" ^&^& npm install
    goto :error
)

REM === Start Backend ===
echo [1] Starting backend on port 8000...
start "Backend API - 8000" /D "%ROOT%backend" cmd /k call venv\Scripts\activate.bat ^&^& python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

REM === Start Frontend ===
echo [2] Starting frontend dev server on port 3000...
start "Frontend Dev - 3000" /D "%ROOT%frontend" cmd /k npm run dev

REM === Open Browser ===
echo [3] Waiting 5s then opening browser...
timeout /t 5 /nobreak >nul
start "" http://localhost:3000

echo.
echo ============================================
echo   Frontend : http://localhost:3000
echo   API Docs : http://localhost:8000/docs
echo   Close the two cmd windows to stop
echo ============================================
echo.

pause
exit /b 0

:error
echo.
echo ============================================
echo   STARTUP FAILED - Check environment!
echo ============================================
pause
exit /b 1
