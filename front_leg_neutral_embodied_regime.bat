@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - FH-07b NEUTRAL EMBODIED REGIME GATE
echo  Technical only / frozen mechanics / no named behavior
echo ============================================================
echo.
echo [INFO] Running 32 preregistered physical composites.
echo [INFO] Each admitted composite executes live, replay, open and closed branches.
echo [INFO] This usually takes several minutes; every blocked row remains reported.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.front_leg_neutral_embodied_regime
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] FH-07b finished. See calibration\runner\front-leg-neutral-embodied-regime-v0.yaml
) else (
  echo [ERROR] FH-07b failed with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
