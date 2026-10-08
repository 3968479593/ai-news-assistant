@echo off
cd /d "%~dp0"

echo ============================================
echo    AI News Assistant - One-click Start
echo ============================================

echo [1/3] Checking port 8000...
set "FOUND_PID="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do set "FOUND_PID=%%a"
if defined FOUND_PID (
  echo      Old process PID %FOUND_PID% found, stopping...
  taskkill /F /PID %FOUND_PID% >nul 2>&1
  timeout /t 2 /nobreak >nul
  echo      Stopped.
) else (
  echo      Port 8000 is free.
)

echo [2/3] Starting backend (logs: backend\data\server8000.*.log)...
powershell -NoProfile -Command "Start-Process -FilePath 'py' -ArgumentList '-3.11','-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory '%~dp0backend' -RedirectStandardOutput '%~dp0backend\data\server8000.out.log' -RedirectStandardError '%~dp0backend\data\server8000.err.log' -WindowStyle Hidden"

echo [3/3] Waiting for service ready (model loading ~30-40s)...
set "READY="
for /l %%i in (1,1,24) do (
  timeout /t 2 /nobreak >nul
  powershell -NoProfile -Command "try { $r = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 2; if ($r.status -eq 'ok') { exit 0 } } catch { exit 1 }"
  if errorlevel 1 (
    echo      waiting... %%i/24
  ) else (
    set "READY=1"
    goto ready
  )
)
:ready
if not defined READY (
  echo      Not ready in 48s, refresh the page later if blank.
) else (
  echo      Service ready!
)

echo.
echo Opening http://127.0.0.1:8000
start "" http://127.0.0.1:8000
echo.
echo Tips:
echo   - Page blank after frontend change? Press Ctrl+F5
echo   - Stop: stop.bat    ^|    Refresh news: refresh.bat
echo.