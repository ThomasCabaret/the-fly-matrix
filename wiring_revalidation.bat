@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  The Fly Matrix - revalidation scientifique du cablage
echo  Regles reproductibles - aucune calibration
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_wiring_revalidation.ps1" -NoPause %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Revalidation terminee. Consultez le rapport HTML.
) else (
  echo [ECHEC] Revalidation interrompue avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
