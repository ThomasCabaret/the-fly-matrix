@echo off
setlocal
title The Fly Matrix - Setup

echo ============================================================
echo  The Fly Matrix - creation de l'environnement Python
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" -NoPause %*
set "SCRIPT_EXIT=%ERRORLEVEL%"

echo.
if "%SCRIPT_EXIT%"=="0" (
  echo [OK] Setup termine avec succes.
) else (
  echo [ERREUR] Setup termine avec le code %SCRIPT_EXIT%.
)
echo.
pause
exit /b %SCRIPT_EXIT%

