@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem 系统命令一律用绝对路径，避免 PATH 被改坏后整个脚本失效。
rem 注意：for /f 的单引号里，命令不能以引号开头（cmd 会剥外层引号导致语法错误），
rem 而 C:\Windows\System32 不含空格，因此这里不加引号。
set "SYS=%SystemRoot%\System32"
set "PS=%SYS%\WindowsPowerShell\v1.0\powershell.exe"

echo ============================================
echo    AI News Assistant - One-click Start
echo ============================================

rem ---- 本项目自带 venv，本机没有 py launcher，因此直接用 venv 里的 python ----
set "PY=%~dp0backend\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python venv not found:
  echo         %PY%
  echo         Rebuild it with:
  echo             cd backend
  echo             python -m venv venv
  echo             venv\Scripts\pip install -r requirements.txt
  goto end
)

rem ---- Start-Process 的日志重定向要求目标目录已存在 ----
if not exist "%~dp0backend\data" mkdir "%~dp0backend\data"

echo [1/3] Checking port 8000...
set "FOUND_PID="
for /f "tokens=5" %%a in ('%SYS%\netstat.exe -ano ^| %SYS%\findstr.exe /C:":8000 " ^| %SYS%\findstr.exe /C:"LISTENING"') do set "FOUND_PID=%%a"
if defined FOUND_PID (
  echo      Old process PID !FOUND_PID! found, stopping...
  "%SYS%\taskkill.exe" /F /PID !FOUND_PID! >nul 2>&1
  "%SYS%\PING.EXE" -n 3 127.0.0.1 >nul
  echo      Stopped.
) else (
  echo      Port 8000 is free.
)

echo [2/3] Starting backend (logs: backend\data\server8000.*.log)...
"%PS%" -NoProfile -Command "Start-Process -FilePath '%PY%' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory '%~dp0backend' -RedirectStandardOutput '%~dp0backend\data\server8000.out.log' -RedirectStandardError '%~dp0backend\data\server8000.err.log' -WindowStyle Hidden"

echo [3/3] Waiting for service ready (model loading ~30-40s)...
set "READY="
for /l %%i in (1,1,24) do (
  "%SYS%\PING.EXE" -n 3 127.0.0.1 >nul
  "%PS%" -NoProfile -Command "try { $r = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 2; if ($r.status -eq 'ok') { exit 0 } else { exit 1 } } catch { exit 1 }"
  if errorlevel 1 (
    echo      waiting... %%i/24
  ) else (
    set "READY=1"
    goto ready
  )
)
:ready
if not defined READY (
  echo      Not ready in 48s. Check backend\data\server8000.err.log
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

:end
echo.
pause