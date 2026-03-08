@echo off
REM ============================================================
REM Setup Windows Task Scheduler for daily price updates
REM
REM Creates a scheduled task "CardChecker_PriceUpdate" that runs
REM update_prices.bat daily at 6:00 AM (local time).
REM
REM Run as Administrator!
REM ============================================================

echo Setting up CardChecker Daily Price Update task...
echo.

REM Delete existing task if any
schtasks /delete /tn "CardChecker_PriceUpdate" /f >nul 2>&1

REM Create new task: daily at 6:00 AM
schtasks /create ^
  /tn "CardChecker_PriceUpdate" ^
  /tr "\"%~dp0update_prices.bat\" --scheduled" ^
  /sc daily ^
  /st 06:00 ^
  /rl HIGHEST ^
  /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo SUCCESS: Task "CardChecker_PriceUpdate" created!
    echo   Schedule: Daily at 6:00 AM
    echo   Action: %~dp0update_prices.bat
    echo.
    echo To modify: Open Task Scheduler ^> CardChecker_PriceUpdate
    echo To run now: schtasks /run /tn "CardChecker_PriceUpdate"
    echo To delete: schtasks /delete /tn "CardChecker_PriceUpdate" /f
) else (
    echo.
    echo FAILED: Could not create task.
    echo Make sure you're running as Administrator.
)

echo.
pause
