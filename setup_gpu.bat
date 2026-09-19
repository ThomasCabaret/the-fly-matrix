@echo off
setlocal
title The Fly Matrix - GPU Setup

echo ============================================================
echo  The Fly Matrix - installation et test du GPU
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_gpu.ps1" -NoPause %*
set "SCRIPT_EXIT=%ERRORLEVEL%"

echo.
if "%SCRIPT_EXIT%"=="0" (
  echo [OK] Installation et test GPU termines avec succes.
) else (
  echo [ERREUR] Installation ou test GPU termine avec le code %SCRIPT_EXIT%.
)
echo.
pause
exit /b %SCRIPT_EXIT%

