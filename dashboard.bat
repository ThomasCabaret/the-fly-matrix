@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  The Fly Matrix - tableau de bord global
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dashboard.ps1" -NoPause
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Tableau de bord genere et ouvert.
) else (
  echo [ECHEC] Generation interrompue avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
