@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - TRANSMITTER / SIGN PRIOR COMPILER
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo This deterministic pass validates source hashes, classifies every
echo canonical neuron, accounts for every runtime edge, and writes derived
echo caches under data\derived\calibration. It does not fit dynamics.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.calibration_evidence
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Evidence compilation completed successfully.
) else (
  echo [FAILED] Evidence compilation did not satisfy its contract.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
