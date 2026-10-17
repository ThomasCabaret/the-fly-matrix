@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo The Fly Matrix - FH-05 coupled dynamic execution
echo ============================================================
echo.
echo Runs 81 owner-separated sentinels as paired stimulus/sham
echo comparisons under both basal source-native mirrors.
echo No value, assignment, behavior, or reference member is selected.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.front_leg_coupled_identifiability_execution
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] FH-05 finite technical execution ensemble retained.
) else (
  echo [FAILED] FH-05 execution stopped with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%

