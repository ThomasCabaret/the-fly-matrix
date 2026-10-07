@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - FECO CALCIUM OBSERVATION SOURCE CONTRACT
echo SOURCE FIDELITY / NOT NATIVE SPIKES / NO BEHAVIOR
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Verifying three source files pinned to an exact public commit.
echo [INFO] Reproducing the activation and GCaMP observation paths.
echo [INFO] Measuring, not hiding, the source's center/threshold discrepancies.
echo [INFO] This script fits no data and selects no graded/event representation.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.feco_observation
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] FeCO calcium observation source contract passed.
  echo [NEXT] Authenticated Dryad tables are still required for held-out fitting.
) else (
  echo [FAILED] A source hash, unit, causality, or governance invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
