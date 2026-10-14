@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - BASAL SOURCE BRIDGE MECHANICS
echo ============================================================
echo This executes all three preregistered input shapes through
echo both diagnostic population-assignment extremes.
echo Fixture values are NOT physiological and cannot be promoted.
echo No named behavior is exposed or selected.
echo.
call .venv\Scripts\python.exe -m the_fly_matrix.basal_source_bridges
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Source bridge mechanics passed for all 6,041 terminals.
  echo           Basal values and population assignments remain unresolved.
) else (
  echo [FAILED] Source bridge mechanics stopped with code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
