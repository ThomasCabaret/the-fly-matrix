@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  The Fly Matrix - topologie cyclique MaleCNS
echo  Analyse structurelle - aucune calibration
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_cycle_topology.ps1" -NoPause %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Analyse terminee.
) else (
  echo [ECHEC] Analyse interrompue avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
