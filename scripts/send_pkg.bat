@echo off
rem Send Feishu pieces from a detached window (see AGENTS.md section 6.1).
rem nohup is not enough, setsid does not exist on Git Bash; cmd start is the only
rem reliable way. Foreground runs get killed by the tool timeout (broke at 8/13).
rem ASCII ONLY in this file: cmd.exe reads .bat in the system code page (GBK),
rem non-ASCII would swallow line breaks and run REM text as commands.
rem Usage: cmd /c start "" scripts\send_pkg.bat <pkg>
cd /d "%~dp0.."
py -3.10 "%~dp0send_pkg.py" %1 %2 %3 > "%TEMP%\send_%1.log" 2>&1
echo DONE_RC=%ERRORLEVEL% >> "%TEMP%\send_%1.log"
