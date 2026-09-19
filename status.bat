@echo off
setlocal
title The Fly Matrix - Status

echo ============================================================
echo  The Fly Matrix - etat du projet
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\status.ps1" -NoPause %*
set "SCRIPT_EXIT=%ERRORLEVEL%"

echo.
if "%SCRIPT_EXIT%"=="0" (
  echo [OK] Controle termine.
) else (
  echo [ERREUR] Controle termine avec le code %SCRIPT_EXIT%.
)
echo.
pause
exit /b %SCRIPT_EXIT%

