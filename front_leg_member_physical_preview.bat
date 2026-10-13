@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - THREE LOCAL-MEMBER PHYSICAL PREVIEWS
echo ============================================================
echo Complete FlyBody physics; local front-leg chain only.
echo This is NOT a whole-MaleCNS run and NOT a behavior claim.
echo.
call .venv\Scripts\python.exe -m the_fly_matrix.front_leg_member_physical_preview
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Three controller-independent trajectories generated.
  echo Run front_leg_member_preview_replay.bat to inspect them.
) else (
  echo [FAILED] Preview generation stopped with code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
