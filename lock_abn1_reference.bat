@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Lock aBN1 reference
echo ============================================================
echo  aBN1 JO-CE / JO-F protocol lock - NO FITTING
echo ============================================================
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\lock_abn1_reference.ps1" -NoPause %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Resultat: calibration\runner\antennal-abn1-reference-lock-v1.yaml
) else (
  echo [ECHEC] Audit interrompu avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
