@echo off
setlocal enabledelayedexpansion
set "SYS=%SystemRoot%\System32"

echo Stopping AI News Assistant (port 8000)...
set "FOUND_PID="
for /f "tokens=5" %%a in ('%SYS%\netstat.exe -ano ^| %SYS%\findstr.exe /C:":8000 " ^| %SYS%\findstr.exe /C:"LISTENING"') do set "FOUND_PID=%%a"
if defined FOUND_PID (
  "%SYS%\taskkill.exe" /F /PID !FOUND_PID! >nul 2>&1
  if errorlevel 1 (
    echo Failed to stop PID !FOUND_PID! - run this as administrator.
  ) else (
    echo Stopped PID !FOUND_PID!.
  )
) else (
  echo No running service found.
)
"%SYS%\PING.EXE" -n 2 127.0.0.1 >nul
echo.
pause