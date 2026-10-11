@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Front-Leg Uncertainty Propagation

echo ============================================================
echo THE FLY MATRIX - FRONT-LEG UNCERTAINTY PROPAGATION
echo PAIRWISE DIAGNOSTIC PANEL / NO SCIENTIFIC REDUCTION
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Preserving the complete 2^148 scientific assignment space.
echo [INFO] Building a deterministic balanced 50-profile sensitivity panel.
echo [INFO] Recording separate FeCO and motor interface decisions.
echo [LIMIT] No value, route, body response or behavior may select a candidate.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.front_leg_uncertainty_propagation
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] The bounded propagation policy and interface decisions passed.
  echo [RESULT] calibration\runner\front-leg-uncertainty-propagation-v0.yaml
) else (
  echo [FAILED] A frozen input, coverage or scientific-boundary invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
