@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - CAUSAL BODY-NEURAL-BODY SENTINEL
echo  16 fixed-stride tuples / 32 paired episodes / no fit or selection
echo ============================================================
echo.
echo Validating bilateral front-knee anatomical coordinates.
echo Running body -^> FeCO -^> typed local chain -^> motor -^> body.
echo Body motion cannot rank or select any candidate.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_declared_closed_loop_sentinel
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] The causal closed-loop execution sentinel passed.
) else (
  echo [FAILED] Closed-loop sentinel stopped with exit code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
