@echo off
setlocal
title The Fly Matrix - MaleCNS data

echo ============================================================
echo  The Fly Matrix - telechargement et controle des donnees
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\download_data.ps1" -NoPause %*
set "SCRIPT_EXIT=%ERRORLEVEL%"

echo.
if "%SCRIPT_EXIT%"=="0" (
  echo [OK] Operation terminee avec succes.
) else (
  echo [ERREUR] Operation terminee avec le code %SCRIPT_EXIT%.
)
echo.
pause
exit /b %SCRIPT_EXIT%

