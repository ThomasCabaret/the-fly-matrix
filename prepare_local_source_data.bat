@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - FRONT-LEG LOCAL SOURCE DATA
echo LOCAL CALIBRATION DATA / NO BEHAVIOR / NO TOPOLOGY CHANGE
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Acquiring the complete 2 MB FeCO processed-calcium/source subset.
echo [INFO] Dryad file bytes require DRYAD_BEARER_TOKEN in .env or the environment.
echo [INFO] Acquiring only the small motor README/anatomy metadata.
echo [INFO] The 860 MB motor pilot is NOT downloaded by default.
echo [INFO] To include it, run this script from a console with argument --include-large-motor-pilot.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.local_source_data %*
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Selected source files were accounted for and available tables inspected.
  echo [NEXT] Calcium remains an observation proxy; it does not identify native spikes.
) else if "%EXIT_CODE%"=="2" (
  echo [BLOCKED] Source metadata/code were processed, but Dryad bytes need DRYAD_BEARER_TOKEN.
  echo [NEXT] Add that token locally to .env, then relaunch this script.
) else (
  echo [FAILED] Acquisition, checksum verification, or schema inspection failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
