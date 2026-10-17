@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo The Fly Matrix - FH-05 coupled-identifiability design
echo ============================================================
echo.
echo This compiles structural and owner-factor coverage only.
echo It selects no parameter, population assignment, or behavior.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.front_leg_coupled_identifiability
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] FH-05 design compiled and validated.
) else (
  echo [FAILED] FH-05 design stopped with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
