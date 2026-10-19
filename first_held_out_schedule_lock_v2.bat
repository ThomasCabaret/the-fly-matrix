@echo off
setlocal
cd /d "%~dp0"
echo [The Fly Matrix] FH-09 v2 outcome-blind schedule lock
echo [IMPORTANT] This compiles scenario metadata only. It does not run the held-out response.
echo [IMPORTANT] All 41 native recalibrated-control survivors must remain accounted.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv. Run setup.bat first.
  goto :end
)
".venv\Scripts\python.exe" -m the_fly_matrix.first_held_out_schedule_lock
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] V2 schedule locked with zero held-out outcomes.
) else (
  echo [ERROR] V2 schedule lock stopped with exit code %EXIT_CODE%.
)
:end
echo.
pause
exit /b %EXIT_CODE%
