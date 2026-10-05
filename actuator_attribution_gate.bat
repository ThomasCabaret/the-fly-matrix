@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Actuator Causal Attribution Gate

echo ============================================================
echo  The Fly Matrix - attribution causale des actionneurs
echo  DIAGNOSTIC ONLY / ZERO OPTIMIZATION / NO BEHAVIOR
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_actuator_attribution_gate.ps1" -NoPause %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Resultat compact: calibration\runner\actuator-causal-attribution-v1.yaml
) else (
  echo [ECHEC] Attribution interrompue avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
