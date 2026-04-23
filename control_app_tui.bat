@echo off
setlocal
cd /d "%~dp0"
py -3 ".\scripts\app_control_tui.py"
endlocal
