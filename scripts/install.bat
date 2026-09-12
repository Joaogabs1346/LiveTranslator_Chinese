@echo off
setlocal
cd /d "%~dp0\.."
echo === LiveScreen Translator - install ===
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version || (echo Python 3.10+ not found. Install from https://www.python.org/downloads/windows/ and tick "Add to PATH". & pause & exit /b 1)
if not exist .venv (
  echo Creating virtual environment...
  %PY% -m venv .venv || (echo venv failed & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip wheel
echo Installing dependencies (PaddleOCR is large, this can take several minutes)...
pip install -r requirements.txt || (echo Dependency install failed & pause & exit /b 1)
echo.
echo Done. Run scripts\run.bat to start the app (first run downloads OCR models ~20 MB).
echo Make sure Ollama is installed and running: https://ollama.com  then  ollama pull qwen3:8b
pause
