@echo off

echo Triggering one news refresh...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/news/refresh' -Method Post -TimeoutSec 120 -UseBasicParsing; Write-Host ('Refresh triggered: ' + $r.Content.Substring(0, [Math]::Min(200, $r.Content.Length))) } catch { Write-Host ('Failed: ' + $_.Exception.Message + ' (is service running? run start.bat first)') }"
pause