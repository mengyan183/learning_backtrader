@echo off
REM ==========================================================================
REM Shoutu (fear/greed index) daily fetch -- E2, Windows Task Scheduler.
REM
REM Called by the scheduled task; can also be run by double-click.
REM Log: logs\shoutu_daily.log (appended)
REM
REM Why this .cmd wrapper exists instead of pointing the task at python.exe:
REM   1 Task Scheduler does NOT set a working directory -- must cd explicitly,
REM     otherwise relative paths (Data/raw/...) resolve to the wrong place.
REM   2 Output must be redirected -- otherwise error messages vanish together
REM     with the console window and cannot be diagnosed afterwards.
REM   3 PYTHONUTF8=1 must be set explicitly -- the script prints Chinese;
REM     a GBK console raises UnicodeEncodeError.
REM
REM --------------------------------------------------------------------------
REM KEEP THIS FILE ASCII-ONLY. DO NOT ADD NON-ASCII CHARACTERS.
REM
REM cmd.exe reads .bat/.cmd using the SYSTEM CODE PAGE (GBK on this machine),
REM NOT UTF-8. Non-ASCII bytes in a REM line get mis-decoded; because GBK is a
REM double-byte encoding, a mis-aligned pair can swallow the line break, the
REM lines merge, and the merged text is then executed as a command:
REM     '...' is not recognized as an internal or external command
REM This actually happened on 2026-09-23. The Chinese rationale for this file
REM lives in docs/trading-discipline.md, section 14.5.
REM --------------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set PYTHONUTF8=1
set PYTHONPATH=.

if not exist logs mkdir logs

REM Timestamp via PowerShell (ISO 8601). Do NOT use %date%: in a Chinese
REM locale it carries local characters and is written as GBK, which shows up
REM as mojibake when the log is read back as UTF-8.
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format s"') do set STAMP=%%i

echo. >> logs\shoutu_daily.log
echo ===== start %STAMP% ===== >> logs\shoutu_daily.log

REM ---------------------------------------------------------------------------
REM PRIMARY: browser path (fetch_shoutu.py) -- the user's explicit choice.
REM
REM Order of value sources, cheapest first. This ordering is a COST decision,
REM not a correctness one:
REM
REM   1. The 11 category tables. One page load, zero per-symbol requests.
REM      Covers 6 of the 8 tracked symbols (CONL/GDXU/SOXL/TQQQ/UPRO/YINN).
REM   2. The per-stock fear/greed view ("gegu tankong"), US sub-tab. AXTX and
REM      CRCG live here and NOT in any category table -- verified: the 379-row
REM      market snapshot contains neither, and the leveraged-US tab
REM      (alphabetical) plus the stock / conventional tabs (curated 51 / 33
REM      name lists) were all checked.
REM      Reached by clicking the query button, i.e. one request per symbol --
REM      so only symbols NOT already found in step 1 are queried.
REM
REM Why not the API path as primary (reverted 2026-09-24):
REM   fetch_shoutu_api.py issues ONE REQUEST PER SYMBOL -- 8/day vs 1 page load.
REM   fetch_shoutu.py's header records why the API was rejected originally: a
REM   probe came back with status=2 "parameter validation failed, IP recorded"
REM   -- the endpoint logs unauthorized IPs. The token is now held
REM   legitimately, but the request volume is still 8x, against a partner
REM   endpoint, for no benefit. The user asked for the browser path.
REM ---------------------------------------------------------------------------
"C:\Users\260023\AppData\Local\Programs\Python\Python310\python.exe" scripts\fetch_shoutu.py >> logs\shoutu_daily.log 2>&1
set RC=%ERRORLEVEL%

REM ---------------------------------------------------------------------------
REM FALLBACK: API path, only if the browser path failed.
REM Used when the browser is unavailable (Chrome not running after wake, bsk
REM extension detached, page redesign). The token lives at Data\shoutu_token
REM (config.py:303) and the request is authorised, so this is safe to fall
REM back to -- it is just not the preferred route.
REM ---------------------------------------------------------------------------
REM NOTE: use goto, NOT an "if (...)" block. Inside a parenthesised block cmd.exe
REM expands %ERRORLEVEL% when it PARSES the block, not when it runs the line --
REM so "set RC=%ERRORLEVEL%" there would capture the pre-block value and the
REM fallback's exit code would be wrong (and look like success).
if "%RC%"=="0" goto :shoutu_done

echo [WARN] browser path failed (exit %RC%); falling back to API path >> logs\shoutu_daily.log
"C:\Users\260023\AppData\Local\Programs\Python\Python310\python.exe" scripts\fetch_shoutu_api.py >> logs\shoutu_daily.log 2>&1
set RC=%ERRORLEVEL%

:shoutu_done

REM ---------------------------------------------------------------------------
REM A2 (2026-09-28): shoutu HISTORY -- the production signal source.
REM fetch_shoutu.py above only records the 06:30 SNAPSHOT (Data/raw/shoutu_fng.csv,
REM 4-5 days per symbol, not a history source). A2 wires shoutu_history.csv into
REM the us_equity core, so it must be refreshed on a schedule.
REM Run AFTER the US close: 06:30 Beijing = 18:30 ET previous day (DST) -- closed.
REM Failure here does NOT change RC (the main path decides the task result),
REM but its own exit code is logged separately.
REM ---------------------------------------------------------------------------
"C:\Users\260023\AppData\Local\Programs\Python\Python310\python.exe" scripts\fetch_shoutu_history.py >> logs\shoutu_daily.log 2>&1
set RC2=%ERRORLEVEL%
echo ===== shoutu_history exit=%RC2% ===== >> logs\shoutu_daily.log

REM ---------------------------------------------------------------------------
REM MARKET DATA (2026-09-29, section 12.28 item 3): prices.csv had NO scheduled
REM task at all -- its only caller was scripts\bootstrap_data.py (one-time
REM rebuild). Result: the production signal date froze (measured 2026-09-29:
REM shoutu data was current, prices.csv was 4 days stale).
REM
REM Failure here does NOT change RC -- the main path decides the task result
REM (same convention as the history block above).
REM No hard timeout: 24 symbols x retries x throttle can run long (worst case
REM 10+ min). How to spot a hang: logs\shoutu_daily.log has "===== start" with
REM no matching "===== end".
REM NOTE: keep this file ASCII-only (see the header of this file).
REM NOTE: the % in the python -c line below is Python's format operator, NOT a
REM cmd variable -- do NOT add a matching % (cmd would expand %...%).
REM ---------------------------------------------------------------------------
"C:\Users\260023\AppData\Local\Programs\Python\Python310\python.exe" -c "from fg_system.data import fetch; df, a = fetch.update_prices(); print('prices.csv added %d rows' % sum(a.values()))" >> logs\shoutu_daily.log 2>&1
set RC3=%ERRORLEVEL%
echo ===== prices exit=%RC3% ===== >> logs\shoutu_daily.log
REM NOTE: single-line "if not" on purpose -- inside a ( ) block cmd.exe expands
REM %RC3% at PARSE time (see the warning at the top of this file).
if not "%RC3%"=="0" echo ===== prices FAILED rc=%RC3% (see traceback above) ===== >> logs\shoutu_daily.log

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format s"') do set STAMP2=%%i
echo ===== end %STAMP2% exit=%RC% ===== >> logs\shoutu_daily.log

endlocal
exit /b %RC%
