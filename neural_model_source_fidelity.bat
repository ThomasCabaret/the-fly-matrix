@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Source-aligned LIF v1

echo ============================================================
echo  The Fly Matrix - correction de fidelite LIF v1
echo  SOURCE-ALIGNED / UNCALIBRATED / NO BEHAVIOR
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_neural_model_source_fidelity.ps1" -NoPause %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Resultat compact: calibration\runner\neural-model-class-source-fidelity-v1.yaml
) else (
  echo [ECHEC] Gate interrompu avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
