@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo The Fly Matrix - autonomous calibration runner check
echo RUNNER VALIDATION / NOT CALIBRATION
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv\Scripts\python.exe
  echo Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Immutable job: calibration\runner\peripheral-compiler-validation-v0.yaml
echo [INFO] Six trials will be exhaustively accounted under runs\calibration\runner\
echo [INFO] No scientific parameter value will be fitted or persisted.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.calibration_runner
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Runner validation passed with exhaustive trial accounting.
) else (
  echo [FAILED] Runner validation failed with code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
