@echo off
chcp 65001 >nul
title 飞行营地飞行程序分析工具

echo ============================================
echo    飞行营地飞行程序分析工具 v1.0.0
echo    Flight Circuit Analyzer
echo ============================================
echo.

cd /d "%~dp0"

REM --- Check Python ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo        下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [OK] Python %%v

REM --- Check Node.js ---
node --version >nul 2>&1
if errorlevel 1 (
    echo [警告] 未找到 Node.js，将跳过前端构建（使用已有构建产物或纯 API 模式）
    set NO_NODE=1
) else (
    for /f %%v in ('node --version 2^>^&1') do echo [OK] Node.js %%v
    set NO_NODE=0
)

REM --- Setup Python virtual environment ---
echo.
echo [1/4] 准备 Python 虚拟环境...

REM Check if existing venv is valid (may be broken when copied from another machine)
set VENV_OK=0
if exist "backend\venv\Scripts\python.exe" (
    call backend\venv\Scripts\python.exe --version >nul 2>&1
    if not errorlevel 1 set VENV_OK=1
)

if "%VENV_OK%"=="0" (
    if exist "backend\venv\" (
        echo        检测到无效的虚拟环境（可能来自其他电脑），正在重建...
        rmdir /s /q "backend\venv"
    )
    echo        创建 Python 虚拟环境...
    python -m venv backend\venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
)
call backend\venv\Scripts\activate.bat
echo       虚拟环境就绪

REM --- Install Python dependencies ---
echo [2/4] 安装 Python 依赖...
pip install -r backend\requirements.txt -q 2>nul
if errorlevel 1 (
    echo [错误] Python 依赖安装失败，尝试使用国内镜像...
    pip install -r backend\requirements.txt -q -i https://pypi.tuna.tsinghua.edu.cn/simple 2>nul
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
)
echo       依赖安装完成

REM --- Build frontend ---
if "%NO_NODE%"=="1" (
    if not exist "frontend\dist\index.html" (
        echo [3/4] 未安装 Node.js 且无前端构建产物，将以纯 API 模式运行
    ) else (
        echo [3/4] 使用已有前端构建产物
    )
) else (
    echo [3/4] 安装并构建前端...
    cd frontend

    REM Check if node_modules is valid
    set NPM_OK=0
    if exist "node_modules\.package-lock.json" (
        node -e "require('./node_modules/vite')" >nul 2>&1
        if not errorlevel 1 set NPM_OK=1
    )

    if "%NPM_OK%"=="0" (
        if exist "node_modules\" (
            echo        检测到无效的 node_modules，正在重建...
            rmdir /s /q "node_modules"
        )
        echo        安装前端依赖（首次可能需要几分钟）...
        call npm install 2>nul
        if errorlevel 1 (
            echo [警告] npm install 失败，尝试使用国内镜像...
            call npm install --registry=https://registry.npmmirror.com 2>nul
            if errorlevel 1 (
                echo [警告] 前端依赖安装失败，将以纯 API 模式运行
                cd ..
                goto :start_server
            )
        )
    )

    echo        构建前端...
    call npm run build 2>nul
    cd ..
    if exist "frontend\dist\index.html" (
        echo       前端构建完成
    ) else (
        echo [警告] 前端构建失败，将以纯 API 模式运行
    )
)

REM --- Start server ---
:start_server
echo [4/4] 启动服务器...
echo.
echo ============================================
echo   服务器启动中...
echo   前端页面: http://localhost:8000
echo   API 文档: http://localhost:8000/docs
echo   按 Ctrl+C 停止服务器
echo ============================================
echo.

REM Open browser after a short delay
start /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

echo.
echo 服务器已停止
pause
