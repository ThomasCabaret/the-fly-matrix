@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - FH-07a NEUTRAL NEURAL REGIME GATE
echo  Technical only / no body outcome / no named behavior
echo ============================================================
echo.
echo [INFO] Running the preregistered pairwise neural screen.
echo [INFO] Results remain an unranked engineering ensemble.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.front_leg_neutral_neural_regime
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] FH-07a finished. See calibration\runner\front-leg-neutral-neural-regime-v0.yaml
) else (
  echo [ERROR] FH-07a failed with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%

