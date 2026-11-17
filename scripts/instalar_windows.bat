@echo off
cd /d "%~dp0.."
py -3 -m venv .venv
if errorlevel 1 exit /b 1
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
echo Configure DATABASE_URL en el entorno, nunca en Git.
