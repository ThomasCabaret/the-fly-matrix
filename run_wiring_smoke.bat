@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  The Fly Matrix - smoke test du cablage executable
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_wiring_smoke.ps1" -NoPause
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Smoke test du cablage termine.
) else (
  echo [ECHEC] Smoke test interrompu avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
