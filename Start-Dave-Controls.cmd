@echo off
cd /d "%~dp0"
where pythonw.exe >nul 2>nul
if errorlevel 1 goto pylauncher
start "" pythonw.exe "%~dp0control_panel.py"
exit /b
:pylauncher
where pyw.exe >nul 2>nul
if errorlevel 1 goto missing
start "" pyw.exe -3 "%~dp0control_panel.py"
exit /b
:missing
echo Python with Tkinter is required. Run: python control_panel.py
pause
