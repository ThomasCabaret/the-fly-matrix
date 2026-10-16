@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - SCOPED FECO SENSORY ENSEMBLE FREEZE
echo LOCAL INTERFACE / NO BEHAVIOR / NATIVE SCALE REMAINS OPEN
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Verifying the 36-neuron MaleCNS FeCO scope and source hashes.
echo [INFO] Reconstructing exact type aliases plus type-shared unknowns.
echo [INFO] Refitting six boundary-valid calcium observation shapes.
echo [INFO] Factorizing routing, source-path and event/graded uncertainty.
echo [INFO] No named behavior, body motion, or future held-out result is read.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.feco_sensory_freeze
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] The scoped routing and observation-shape ensemble is reproducible.
  echo [OPEN] Native neural units and amplitude still require a separate gate.
) else (
  echo [FAILED] A source hash, accounting, boundary, or factorization invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
