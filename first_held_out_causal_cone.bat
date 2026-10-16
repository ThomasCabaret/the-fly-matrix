@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - First Held-Out Causal Cone

echo ============================================================
echo THE FLY MATRIX - FIRST HELD-OUT CAUSAL CONE
echo SCOPE ACCOUNTING / NO VALUES / NO BEHAVIOR OUTCOME
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Verifying the FH-01 source/readiness decision.
echo [INFO] Freezing the existing 36 FeCO, 150 intermediate and 10 motor scope.
echo [INFO] Accounting native boundaries, exceptions and outside-cone neurons.
echo [LIMIT] This command observes no held-out response and selects no value or path.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.held_out_causal_cone
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] FH-02 causal scope compiled without outcome exposure.
  echo [RESULT] calibration\runner\first-held-out-causal-cone-v0.yaml
  echo [SCOPE]  calibration\scopes\first-held-out-proprioceptive-resistance-reflex-v0.yaml
) else (
  echo [FAILED] A frozen input, accounting, topology or exposure invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
