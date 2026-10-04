@echo off
setlocal
if not exist "%~dp0engine\config\dirs.json" exit /b 1
if not exist "%~dp0engine\VCMI_launcher.exe" exit /b 1
set "VCMI_FRIEND_PROFILE=%~dp0profile"
if not exist "%VCMI_FRIEND_PROFILE%" mkdir "%VCMI_FRIEND_PROFILE%"
if not exist "%VCMI_FRIEND_PROFILE%" exit /b 1
cd /d "%~dp0engine" || exit /b 1
"VCMI_launcher.exe"
endlocal
