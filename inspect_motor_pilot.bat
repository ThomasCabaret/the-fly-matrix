@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - MOTOR SPIKE/FORCE PILOT INVENTORY
echo SAFE SCHEMA INSPECTION / NO FIT / NO BEHAVIOR / NO EXTRACTION
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Verifying one checksum-locked archive for each motor-unit class.
echo [INFO] Reading ZIP directories and at most 128 header bytes per member.
echo [INFO] No member is extracted and no parameter or body-class assignment is selected.
echo [INFO] If archives are absent, first run:
echo [INFO]   prepare_local_source_data.bat --include-large-motor-pilot
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.motor_pilot_inventory
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] All three archive schemas were safely inventoried.
  echo [NEXT] Version a variable-level parser and preregister the class-level kernel fit.
) else if "%EXIT_CODE%"=="2" (
  echo [BLOCKED] One or more exact motor archives are absent.
  echo [NEXT] Add DRYAD_BEARER_TOKEN locally and run the explicit 860 MB acquisition command above.
) else (
  echo [FAILED] A manifest, checksum, ZIP safety, or accounting invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
