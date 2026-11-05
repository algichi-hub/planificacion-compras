# Planificación de Compras

Aplicación Streamlit + PostgreSQL 18 para **cobertura de SC por cantidades recibidas y aprobadas**. No gestiona ni certifica stock físico.

## Código y datos
- `app.py`: tablero Streamlit de solo lectura.
- `migrations/001_initial.sql`: esquemas `raw`, `core`, `planning`, `audit`.
- `src/`: parsers y reglas conservadoras para cantidades.
- `scripts/import_snapshot.py`: importador semanal manual.
- `scripts/export_reports.py`: informes Excel y CSV en formato español.
- `tests/`: pruebas básicas de normalización.
- `docs/PIPELINE.md`: instrucciones completas.
- `AGENTS.md`: reglas del proyecto.

## Instalación
```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = "postgresql://..."  # conexión guardada fuera de Git
python -m pytest -q
```
No publicar nunca credenciales en el repositorio.

## Entradas (descomprimidas)
Copiar a `entrada/`: `SC_FAS.csv`, `INC_FAS.csv` y **`Recepciones_Sevilla.csv`**.

## Primera importación
```powershell
python scripts/import_snapshot.py --date 2026-11-09 --input entrada
# Revisar las tablas audit y los indicadores antes de activar
python scripts/import_snapshot.py --activate 1
python scripts/export_reports.py --snapshot 1
python -m streamlit run app.py
```

Los scripts funcionan con Neon o PostgreSQL local; en Windows se instala PostgreSQL y se ejecuta la misma migración sobre una base vacía. La aplicación web requiere `DATABASE_URL` en los secretos de Streamlit.

## Limitaciones conocidas de V1
La conciliación conservadora marca como ambiguas las cantidades conflictivas de SC/PO y las recepciones con varios orígenes SC. Los CSV contienen separadores incrustados que provocan incidencias de estructura; hay que recuperarlos antes de declarar una carga completamente validada. REAC está conservado como referencia en SC raw; falta un enlace cuantitativo aprobado con cada recepción. No afirmar validación de despliegue, importación total o exactitud de cobertura hasta ejecutar pruebas con los CSV y revisar los resultados.
