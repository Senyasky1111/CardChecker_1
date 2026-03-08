@echo off
REM ============================================================
REM Daily Price Update for CardChecker
REM
REM This script updates prices from all sources:
REM   1. PokeTrace API (EUR + USD, graded, eBay)
REM   2. Pokemon-API.com (country-specific: DE/FR/ES/IT)
REM   3. CardMarket CSV (if fresh file exists)
REM
REM Usage:
REM   update_prices.bat              - run full update
REM   update_prices.bat --dry-run    - preview without changes
REM   update_prices.bat --poketrace-only
REM   update_prices.bat --pokemon-api-only
REM   update_prices.bat --csv-only
REM
REM Schedule via Windows Task Scheduler:
REM   Action: Start a Program
REM   Program: C:\Users\amotrychenko\Desktop\CardRecognition\update_prices.bat
REM   Start in: C:\Users\amotrychenko\Desktop\CardRecognition
REM ============================================================

cd /d "%~dp0"

echo ============================================================
echo CardChecker Daily Price Update
echo %date% %time%
echo ============================================================

REM Log output when running scheduled
if "%1"=="--scheduled" (
    .\venv\Scripts\python.exe scripts\update_prices_daily.py >> logs\daily_update.log 2>&1
) else (
    .\venv\Scripts\python.exe scripts\update_prices_daily.py %*
)

echo.
echo ============================================================
echo Update complete at %time%
echo ============================================================

REM Keep window open if run manually (not via Task Scheduler)
if "%1"=="" pause
if "%1"=="--dry-run" pause
