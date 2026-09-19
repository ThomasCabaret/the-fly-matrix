@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  The Fly Matrix - audit MaleCNS, FlyBody et neuPrint
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_analysis.ps1" -NoPause
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Audit termine.
) else (
  echo [ECHEC] Inventaire interrompu avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
