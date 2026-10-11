@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Front-Leg Chain Envelope

echo ============================================================
echo THE FLY MATRIX - FRONT-LEG SENSOR-CNS-MOTOR CHAIN
echo FACTORIZED UNCERTAINTY / NO BEHAVIOR / NO PROMOTION
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Freezing the 36 FeCO and 10 tibia-flexor endpoints.
echo [INFO] Accounting every endpoint distance and every path up to two CNS hops.
echo [INFO] Propagating FeCO, motor-class, route, kernel and gain uncertainty.
echo [LIMIT] This command chooses no neural model, parameter, route or body motion.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.front_leg_chain
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Factorized local-chain envelope compiled without selection.
  echo [RESULT] calibration\runner\front-leg-sensor-cns-motor-chain-v0.yaml
) else (
  echo [FAILED] A frozen input, topology, accounting or exposure invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
