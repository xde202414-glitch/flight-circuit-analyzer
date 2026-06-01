@echo off
chcp 65001 >nul
title 打包发布

cd /d "%~dp0"

set OUTPUT=flight-circuit-analyzer-v1.0.0.zip

echo ============================================
echo    打包发布版本
echo ============================================
echo.

echo [1/3] 清理开发文件...

REM 删除不应分发的文件夹
for %%F in (
    "backend\venv"
    "backend\.venv"
    "backend\__pycache__"
    "backend\.pytest_cache"
    "backend\app\__pycache__"
    "backend\app\api\__pycache__"
    "backend\app\core\__pycache__"
    "backend\app\models\__pycache__"
    "backend\tests\__pycache__"
    "frontend\node_modules"
    "frontend\dist"
    ".git"
    ".claude"
) do (
    if exist %%F (
        echo        删除 %%F
        rmdir /s /q %%F 2>nul
    )
)

REM 删除日志文件
del /q *.log 2>nul
del /q *.err.log 2>nul

echo [2/3] 打包文件...

REM 使用 PowerShell 压缩（Windows 10+ 自带）
powershell -Command "Compress-Archive -Path '.\backend', '.\frontend', '.\启动.bat', '.\README.md' -DestinationPath '%OUTPUT%' -Force"

echo [3/3] 完成！
echo.
echo ============================================
echo   打包完成: %OUTPUT%
echo   文件大小:
powershell -Command "(Get-Item '%OUTPUT%').Length / 1KB"
echo ============================================
echo.
echo 将此 ZIP 发给别人，对方解压后双击 启动.bat 即可运行。
echo 对方需要预装 Python 3.10+ 和 Node.js
echo.
pause
