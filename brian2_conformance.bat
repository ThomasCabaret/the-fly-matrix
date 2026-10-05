@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  The Fly Matrix - Brian2 scheduler conformance gate
echo ============================================================
echo.
if not exist ".\runs\reference-env\brian2-2.5.1\Scripts\python.exe" (
  echo [ERROR] The isolated reference environment is missing.
  echo         Run setup_brian2_reference.bat first.
  echo.
  pause
  exit /b 1
)
echo [RUN] Comparing the project comparator with Brian2 2.5.1...
".\.venv\Scripts\python.exe" -m the_fly_matrix.brian2_conformance
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Conformance report generated.
) else (
  echo [ERROR] Conformance gate failed with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
