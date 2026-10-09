@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo The Fly Matrix - motor spike-force source parser
echo ============================================================
echo This ports the recovered published MATLAB table transforms.
echo It writes ignored normalized tables plus a tracked compact status.
echo It promotes NO calibration value and selects NO MaleCNS class.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)
echo [RUN] Parsing 194 declared trials from three hash-verified archives...
".venv\Scripts\python.exe" -m the_fly_matrix.motor_spike_force_parser
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" echo [ERROR] Parser failed with exit code %EXIT_CODE%.
:finish
echo.
echo Press any key to close this window.
pause >nul
exit /b %EXIT_CODE%

