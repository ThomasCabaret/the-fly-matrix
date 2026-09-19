@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  The Fly Matrix - generation du tableau de bord
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dashboard.ps1" -NoPause -NoOpen
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Tableau de bord genere sans ouverture du navigateur.
) else (
  echo [ECHEC] Generation interrompue avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
