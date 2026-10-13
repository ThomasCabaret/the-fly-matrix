@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  The Fly Matrix - feedback identifiability gate
echo  65 active rows x 4 branches; no fit, ranking or behavior
echo ============================================================
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_feedback_identifiability
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] Feedback identifiability gate passed.
) else (
  echo [FAILED] Gate exited with code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
