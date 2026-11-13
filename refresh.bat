@echo off
set "SYS=%SystemRoot%\System32"
set "PS=%SYS%\WindowsPowerShell\v1.0\powershell.exe"

echo Triggering one news refresh...
"%PS%" -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/news/refresh' -Method Post -TimeoutSec 120 -UseBasicParsing -ErrorAction Stop; $c = [string]$r.Content; if ($c.Length -gt 200) { $c = $c.Substring(0,200) + '...' }; Write-Host ('Refresh triggered: ' + $c) } catch { Write-Host ('Failed: ' + $_.Exception.Message); Write-Host 'Is the service running? Run start.bat first.' }"
pause