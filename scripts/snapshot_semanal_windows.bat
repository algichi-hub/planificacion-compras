@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Instala las dependencias antes de continuar.
  exit /b 1
)
if "%DATABASE_URL%"=="" (
  echo Falta DATABASE_URL en el entorno. Nunca guardes credenciales en este BAT.
  exit /b 2
)
for /f %%D in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set SNAPSHOT_DATE=%%D
echo Fecha snapshot: %SNAPSHOT_DATE%
".venv\Scripts\python.exe" scripts\import_snapshot.py --date %SNAPSHOT_DATE% --input entrada
if errorlevel 1 (
  echo ERROR: no se ha preparado el snapshot.
  exit /b 1
)
echo Snapshot creado en estado validated. Revisar calidad antes de activar.
echo Para activarlo: python scripts\import_snapshot.py --activate ID
endlocal
