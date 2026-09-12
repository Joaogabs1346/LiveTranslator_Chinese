@echo off
cd /d "%~dp0\.."
call .venv\Scripts\activate.bat
pip install -q pytest
python -m pytest -q
pause
