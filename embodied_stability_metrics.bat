@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Embodied Stability Metric Contract

echo ============================================================
echo  The Fly Matrix - metriques de stabilite incarnee
echo  DIAGNOSTIC ONLY / ZERO OPTIMIZATION / NO BEHAVIOR
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_embodied_stability_metrics.ps1" -NoPause %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Resultat compact: calibration\runner\embodied-stability-metric-contract-v0.yaml
) else (
  echo [ECHEC] Mesure interrompue avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
