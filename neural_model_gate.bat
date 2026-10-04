@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Neural Model Fidelity Gate

echo ============================================================
echo  The Fly Matrix - gate de fidelite du modele neural
echo  UNCALIBRATED / NO BEHAVIOR CLAIM
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_neural_model_gate.ps1" -NoPause %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Resultat compact: calibration\runner\neural-model-class-lif-feasibility-v0.yaml
) else (
  echo [ECHEC] Gate interrompu avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
