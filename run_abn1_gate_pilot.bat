@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  The Fly Matrix - aBN1 model-class pilot
echo  NON-DECISIONAL / NO FITTING / NO BEHAVIOR CLAIM
echo ============================================================
echo.
echo This run exercises the full MaleCNS graph for a bounded set of
echo frequencies, rate-ensemble sentinels and input bridges. It may
echo take several minutes and writes heavy output below runs\calibration.
echo.
call .venv\Scripts\python.exe -m the_fly_matrix.abn1_model_class --backend auto
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Pilot completed. No scientific model decision was made.
) else (
  echo [FAILED] Pilot stopped with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
