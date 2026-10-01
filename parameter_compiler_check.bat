@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo The Fly Matrix - peripheral parameter compiler validation
echo STRUCTURE TEST ONLY / NOT CALIBRATION
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv\Scripts\python.exe
  echo Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Candidate manifests will be hash-checked.
echo [INFO] Synthetic unit/simplex values are used in memory only.
echo [INFO] No fitted value or parameter set will be written.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.calibration_parameters
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Compiler contracts and deterministic expansion passed.
) else (
  echo [FAILED] Parameter compiler validation failed with code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
