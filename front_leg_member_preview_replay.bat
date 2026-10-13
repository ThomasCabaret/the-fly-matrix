@echo off
setlocal
cd /d "%~dp0"
set "SHORT_ID=%~1"
if not "%SHORT_ID%"=="" goto :resolve
echo Choose the exact member to present:
echo   1. declared_tuple_129
echo   2. declared_tuple_141
echo   3. declared_tuple_238
echo.
set /p "CHOICE=Choice [1-3]: "
if "%CHOICE%"=="1" set "SHORT_ID=129"
if "%CHOICE%"=="2" set "SHORT_ID=141"
if "%CHOICE%"=="3" set "SHORT_ID=238"
:resolve
if "%SHORT_ID%"=="129" set "MEMBER=declared_tuple_129"
if "%SHORT_ID%"=="141" set "MEMBER=declared_tuple_141"
if "%SHORT_ID%"=="238" set "MEMBER=declared_tuple_238"
if not defined MEMBER (
  echo [ERROR] Usage: front_leg_member_preview_replay.bat [129^|141^|238]
  echo.
  pause
  exit /b 2
)
set "TRAJECTORY=runs\calibration\front-leg-member-physical-preview-v0\%MEMBER%\physical-trajectory.npz"
if not exist "%TRAJECTORY%" (
  echo [ERROR] Missing %TRAJECTORY%
  echo Run front_leg_member_physical_preview.bat first.
  echo.
  pause
  exit /b 3
)
echo ============================================================
echo  LOCAL FRONT-LEG MEMBER PREVIEW: %MEMBER%
echo ============================================================
echo Complete FlyBody physics; local front-leg chain only.
echo NOT whole MaleCNS. NOT basal. NOT a behavior claim.
echo Controls: mouse = camera, Space = pause, R = restart.
echo.
call .venv\Scripts\python.exe -m the_fly_matrix.physical_trajectory "%TRAJECTORY%" --speed 0.1
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Replay ended with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
