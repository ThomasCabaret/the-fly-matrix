@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Real MaleCNS Benchmark

echo ============================================================
echo  The Fly Matrix - vrai connectome MaleCNS
echo  BENCHMARK ONLY / UNCALIBRATED
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_connectome_benchmark.ps1" -NoPause %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Benchmark termine. Consultez runs\execution-benchmark\.
) else (
  echo [ECHEC] Benchmark interrompu avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
