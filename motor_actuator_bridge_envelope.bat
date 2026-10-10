@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Motor Actuator Bridge Envelope

echo ============================================================
echo THE FLY MATRIX - MOTOR FORCE TO DIRECT-MOTOR BRIDGE
echo CONDITIONAL ENGINEERING ENSEMBLE / NO BEHAVIOR / NO PROMOTION
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Freezing the accepted topology and direct-motor contract.
echo [INFO] Probing 22 front-leg candidate actuators in a tethered fixture.
echo [INFO] Deriving a detectable, sub-saturation conditional gain ensemble.
echo [LIMIT] This does not identify biological force-to-torque conversion.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.motor_actuator_bridge
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Conditional bridge ensemble generated; no reference selected.
  echo [RESULT] calibration\runner\motor-actuator-bridge-envelope-v0.yaml
) else (
  echo [FAILED] A topology, actuator, detectability or safety invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
