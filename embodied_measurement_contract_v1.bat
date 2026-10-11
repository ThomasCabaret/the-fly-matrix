@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Embodied Measurement Contract v1

echo ============================================================
echo THE FLY MATRIX - EMBODIED MEASUREMENT CONTRACT V1
echo PAIRED PASSIVE FIXTURE / NO STABILITY / NO BEHAVIOR
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Repeating one passive flat-ground baseline twice.
echo [INFO] Running one matched generic root-velocity perturbation.
echo [INFO] Measuring COM, joint limits, physical jerk, masks and recovery.
echo [LIMIT] No threshold, parameter, action or visual result is selected.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.embodied_measurement_contract
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] The short-horizon technical measurement contract passed.
  echo [RESULT] calibration\runner\embodied-measurement-contract-v1.yaml
) else (
  echo [FAILED] A model, measurement, pairing or leakage invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
