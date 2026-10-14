@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - TYPED/HYBRID FULL-GRAPH RUNTIME SENTINEL
echo ============================================================
echo This executes two explicit diagnostic assignment extremes.
echo It promotes no population assignment, parameter or behavior.
echo.
call .venv\Scripts\python.exe -m the_fly_matrix.typed_hybrid_runtime
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Typed/hybrid runtime mechanics passed.
) else (
  echo [FAILED] Typed/hybrid runtime sentinel stopped with code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
