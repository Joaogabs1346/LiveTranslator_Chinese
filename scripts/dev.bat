@echo off
REM Development: installs dev deps, runs tests, then launches the app with console output.
cd /d "%~dp0\.."
if not exist .venv (call scripts\install.bat)
call .venv\Scripts\activate.bat
pip install -r requirements-dev.txt
python -m pytest -q || (echo Tests failed & pause & exit /b 1)
python run.py
