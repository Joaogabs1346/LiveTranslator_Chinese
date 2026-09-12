@echo off
REM Runs the app elevated. Needed only if the game runs as administrator
REM (Windows blocks keyboard access from non-elevated apps while an elevated window has focus).
cd /d "%~dp0\.."
powershell -Command "Start-Process -Verb RunAs -FilePath '%cd%\.venv\Scripts\pythonw.exe' -ArgumentList '%cd%\run.py' -WorkingDirectory '%cd%'"
