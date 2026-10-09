@echo off
REM ==========================================================================
REM Register / re-register the "Shoutu daily fetch" scheduled task (E2, plan B)
REM
REM Just double-click it. Normal user rights are enough -- NO admin required.
REM
REM Schedule: weekly, Tue-Sat, 06:30 Beijing time.
REM   Tue-Sat (not Mon-Fri): Tue 06:30 Beijing = Mon 18:30 ET, so it picks up
REM   the US Monday session; Sat 06:30 Beijing = Fri 18:30 ET, so it picks up
REM   the US Friday session. Covers US Mon-Fri with NO lag.
REM
REM 06:30 falls inside the intersection of the DST and standard-time safe
REM windows (05:00-08:00):
REM   DST       after-hours ends 04:00, overnight starts 08:00
REM   standard  after-hours ends 05:00, overnight starts 09:00
REM
REM See docs/trading-discipline.md section 14.5 for the full rationale.
REM
REM --------------------------------------------------------------------------
REM KEEP THIS FILE ASCII-ONLY. DO NOT ADD NON-ASCII CHARACTERS.
REM cmd.exe reads .bat/.cmd using the SYSTEM CODE PAGE (GBK), not UTF-8.
REM Mis-decoded non-ASCII bytes can swallow a line break and make the merged
REM line execute as a command. This actually happened on 2026-09-23.
REM --------------------------------------------------------------------------
setlocal
set TASKNAME=ShoutuDailyFetch
set CMDLINE="%~dp0shoutu_daily.cmd"

echo Registering scheduled task: %TASKNAME%
echo   command: %CMDLINE%
echo   schedule: weekly Tue-Sat 06:30
echo.

schtasks /create ^
  /tn "%TASKNAME%" ^
  /tr "%CMDLINE%" ^
  /sc weekly ^
  /d TUE,WED,THU,FRI,SAT ^
  /st 06:30 ^
  /f

if %ERRORLEVEL% neq 0 (
  echo.
  echo [FAILED] exit code %ERRORLEVEL%
  exit /b %ERRORLEVEL%
)

echo.
echo [OK] registered. Query it with:
schtasks /query /tn "%TASKNAME%" /v /fo LIST
endlocal
