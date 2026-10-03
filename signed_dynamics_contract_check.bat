@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo The Fly Matrix - signed MaleCNS model contract validation
echo STRUCTURAL TEST VALUES ONLY / NOT CALIBRATION
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv\Scripts\python.exe
  echo Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] The 166,700 canonical neurons and 25,582,938 runtime edges will be checked.
echo [INFO] Every edge must retain one explicit transmitter-class parameter path.
echo [INFO] Probe values are non-physiological and no parameter set will be fitted.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.calibration_runner --job calibration\runner\signed-dynamics-contract-validation-v0.yaml
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Signed model structure passed exhaustive validation.
) else (
  echo [FAILED] Signed model contract validation failed with code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
