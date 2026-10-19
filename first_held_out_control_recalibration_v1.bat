@echo off
setlocal
cd /d "%~dp0"
echo [The Fly Matrix] FH-09 outcome-blind topology-control recalibration
echo [IMPORTANT] This runs FH-05 through FH-07 on four rewired graphs.
echo [IMPORTANT] It does not execute or inspect the held-out reflex protocol.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv. Run setup.bat first.
  goto :end
)
".venv\Scripts\python.exe" -m the_fly_matrix.first_held_out_control_recalibration
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] All four rewired control calibrations were accounted.
) else (
  echo [ERROR] Control recalibration stopped with exit code %EXIT_CODE%.
  echo Partial diagnostics were retained under runs\calibration\first-held-out-control-recalibration-v1.
)
:end
echo.
pause
exit /b %EXIT_CODE%
