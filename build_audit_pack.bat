@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  The Fly Matrix - construction du pack d'audit
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_audit_pack.ps1" -NoPause
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Le pack d'audit est pret dans audit-packs\
) else (
  echo [ECHEC] Construction interrompue avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
