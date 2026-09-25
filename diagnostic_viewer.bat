@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  The Fly Matrix - viewer physique diagnostique
echo  NOT MALECNS - NOT CALIBRATION
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_diagnostic_viewer.ps1" -NoPause %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Viewer diagnostique termine.
) else (
  echo [ECHEC] Viewer diagnostique interrompu avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
