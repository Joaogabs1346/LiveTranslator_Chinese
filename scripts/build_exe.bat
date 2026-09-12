@echo off
setlocal
cd /d "%~dp0\.."
if not exist .venv (echo Run scripts\install.bat first & pause & exit /b 1)
call .venv\Scripts\activate.bat
pip install -q pyinstaller
echo Building LiveScreenTranslator.exe (one-folder build; this takes a few minutes)...
rmdir /s /q build dist 2>nul
pyinstaller --noconfirm LiveScreenTranslator.spec || (echo Build failed & pause & exit /b 1)
echo.
echo ===========================================================
echo  EXE created at:  %cd%\dist\LiveScreenTranslator\LiveScreenTranslator.exe
echo  Copy the whole dist\LiveScreenTranslator folder to distribute.
echo ===========================================================
pause
