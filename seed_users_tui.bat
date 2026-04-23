@echo off
setlocal
cd /d "%~dp0"
py -3 ".\scripts\seed_users_tui.py"
endlocal
