@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Instala las dependencias antes de continuar.
  exit /b 1
)
if "%COMPRAS_ZIP_PASSWORD%"=="" (
  echo Falta COMPRAS_ZIP_PASSWORD en el entorno de la tarea programada.
  exit /b 3
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
echo Snapshot validado por el importador. Revisar audit.import_issues.
endlocal
