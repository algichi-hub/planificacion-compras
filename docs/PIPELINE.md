# Operación semanal

1. Copiar **SC_FAS.csv**, **INC_FAS.csv**, **Recepciones_Sevilla.csv** a la carpeta local entrada. No incluir ZIP.
2. Definir variable de entorno DATABASE_URL hacia Neon de desarrollo o PostgreSQL Windows.
3. Ejecutar tests: `python -m pytest -q`.
4. Ejecutar importación: `python scripts/import_snapshot.py --date 2026-11-09 --input entrada`.
5. Revisar tabla `audit.source_files` y `audit.import_issues`, y la vista `planning.v_sc_coverage`.
6. Activar explícitamente lote validado: `python scripts/import_snapshot.py --activate ID`.
7. Generar informes: `python scripts/export_reports.py --snapshot ID --out informes`.
8. Arrancar Streamlit: `python -m streamlit run app.py`.

La primera versión conserva filas originales **válidas del SC_FAS** en `raw.source_rows`; los registros normalizados de recepción e incidencia están en `core`. Los registros malformados se cuentan y se registran en `audit.import_issues`. No afirmar que existe una importación de cero pérdidas hasta recuperar todas las filas defectuosas y comprobar las reglas de reconciliación.

## Cloud
Streamlit Community Cloud despliega el branch `develop`, con `app.py` como entrypoint y `DATABASE_URL` como secreto en Streamlit (no Git).
La carga de CSV grandes se realiza desde Python local y **no** desde la sesión web. Activar y validar antes de cambiar main.

## Migración futura local
Instalar PostgreSQL 18 en Windows, crear una base `compras` vacía y ejecutar en orden las migraciones SQL. Conectar por DATABASE_URL local, importar tres CSV y comprobar informes. No es necesario transferir los datos de simulación de Neon.

## Riesgos
- `SOLICITADA REAL` puede variar entre filas de la misma SC.
- RECEPCION puede repetirse; identificamos los movimientos por fila fuente y snapshot, no suponemos unicidad del número.
- El fichero de recepción no incluye compañía; se une por PO y posición y la atribución se considera ambigua cuando hay múltiples orígenes SC.
- Los CSV incluyen líneas con separadores internos; la importación inicial registra anomalías para corrección.
- Un aprobado documental no garantiza un stock utilizable.
