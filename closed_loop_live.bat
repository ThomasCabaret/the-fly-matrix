@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  The Fly Matrix - live real MaleCNS closed loop
echo  REAL MALECNS / UNCALIBRATED
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_embodied_malecns.ps1" -Mode live -Duration 0 -NoPause %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Live closed-loop session ended.
) else (
  echo [FAIL] Live closed-loop session failed with code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
