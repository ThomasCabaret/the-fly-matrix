@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Actuator Semantics Gate

echo ============================================================
echo  The Fly Matrix - audit semantique des actionneurs
echo  NO CALIBRATION / NO BEHAVIOR CLAIM
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_actuator_semantics_gate.ps1" -NoPause %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Resultat compact: calibration\runner\actuator-semantics-gate-v0.yaml
) else (
  echo [ECHEC] Audit interrompu avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
