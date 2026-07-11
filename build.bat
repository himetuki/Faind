@echo off
chcp 65001 >nul
echo ========================================
echo   Faind 一键打包脚本
echo ========================================
echo.

:: 检查 PyInstaller
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [安装] 正在安装 PyInstaller...
    pip install pyinstaller
)

:: 清理旧构建
echo [清理] 删除旧的构建文件...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

:: 执行打包
echo [打包] 正在打包 Faind.exe（单文件模式）...
pyinstaller Faind.spec --noconfirm

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   打包成功！
    echo   输出文件: dist\Faind.exe
    echo ========================================
    echo.
    :: 显示文件大小
    for %%A in ("dist\Faind.exe") do echo 文件大小: %%~zA 字节
) else (
    echo.
    echo [错误] 打包失败，请检查错误信息
)

pause