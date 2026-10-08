@echo off

echo Stopping AI News Assistant (port 8000)...
set "FOUND_PID="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do set "FOUND_PID=%%a"
if defined FOUND_PID (
  taskkill /F /PID %FOUND_PID% >nul 2>&1
  echo Stopped PID %FOUND_PID%.
) else (
  echo No running service found.
)
timeout /t 1 /nobreak >nul