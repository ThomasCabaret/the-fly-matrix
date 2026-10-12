@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - DECLARED ENVELOPE NEURAL SENTINEL
echo  240 neural tuples; no fit, no physics, no behavior
echo ============================================================
echo.
echo Executing every declared FeCO routing, sign and numeric profile.
echo Checking the incoming-L1 transform and isolated axis oracles.
echo No neural magnitude is used to rank or select a candidate.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_declared_neural_sentinel
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] The declared neural execution contract passed.
) else (
  echo [FAILED] Neural sentinel stopped with exit code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
