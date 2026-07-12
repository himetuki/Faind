@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Faind Build

echo.
echo  ==========================================
echo          Faind Build Script
echo  ==========================================
echo.

:: [1/3] Check PyInstaller
echo  [1/3] Checking PyInstaller...
pip show pyinstaller >nul 2>&1
if !errorlevel! neq 0 (
    echo        Installing PyInstaller...
    pip install pyinstaller -q
    if !errorlevel! neq 0 (
        echo        [FAIL] Cannot install PyInstaller. Check network or install manually.
        pause
        exit /b 1
    )
)
echo        [OK] Ready

:: [2/3] Clean old builds
echo  [2/3] Cleaning old builds...
if exist "build" (rmdir /s /q "build" 2>nul)
if exist "dist"  (rmdir /s /q "dist"  2>nul)
echo        [OK] Done

:: [3/3] Build with PowerShell progress display
echo  [3/3] Building...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
set BUILD_RESULT=%errorlevel%

:: Result
echo.
if %BUILD_RESULT% equ 0 (
    for %%A in ("dist\Faind.exe") do (
        set /a "SIZE=%%~zA"
        set /a "SIZE_MB=!SIZE! / 1048576"
        set /a "SIZE_REM=!SIZE! %% 1048576 * 100 / 1048576"
    )
    echo  ==========================================
    echo         BUILD SUCCESSFUL!
    echo  ------------------------------------------
    echo    Output: dist\Faind.exe
    if defined SIZE_MB (
        echo    Size: !SIZE_MB!.!SIZE_REM! MB
    )
    echo  ==========================================
) else (
    echo  ==========================================
    echo          BUILD FAILED!
    echo  ==========================================
    echo   Exit code: %BUILD_RESULT%
    echo   Check error messages above.
)

echo.
pause
exit /b %BUILD_RESULT%
