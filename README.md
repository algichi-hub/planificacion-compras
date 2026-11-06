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

## Estado de tramitación de las líneas SC (snapshot #7 y sucesivos)

La clasificación utiliza los datos ya importados sin alterar los CSV ni las tablas históricas.
Se guarda opcionalmente en una tabla derivada indexada para evitar recalcular las
conciliaciones completas durante cada interacción de Streamlit.

```powershell
git pull origin develop
python -m pytest -q
python scripts/apply_migrations.py
python scripts/build_sc_workflow.py --snapshot 7
# Comparar la distribución y, solo después de revisarla:
python scripts/build_sc_workflow.py --snapshot 7 --commit
```

La simulación por defecto es **solo lectura**; `--commit` actualiza exclusivamente
`planning.sc_workflow_status` (idempotente, sin activar snapshots).
La migración 007 añade la tabla derivada; no cambia tablas de origen.
El frontend continúa con la vista anterior hasta que exista el resumen para el snapshot seleccionado.

Orden de estados: **SC anulada** si `requested_qty=0` (excluida de «Pendiente pedido»);
«Pendiente conciliación» si cantidades/vínculos son inválidos; «Pendiente pedido» sin PO
aprobado; «Completado» con cantidad aprobada total; «Parcialmente aprobadas» con
aprobación parcial; «REAC (provisional)» si hay recepción y referencia al REAC, sin
probar su vigencia; «Pendiente aprobación» si hay recepción sin aprobaciones;
«Recibido con incidencia (provisional)» si una incidencia abierta sugiere
llegada física sin recepción; «Material sin recibir» cuando no existen eventos
posteriores ni incidencias abiertas. Los REAC e incidencias históricas se conservan
aunque las unidades estén aprobadas. Las dos clasificaciones provisionales no
equivalen a validación de llegada física o vigencia del REAC.

**Verificación de snapshot #7** (ejecución SQL read-only, 27.960 líneas):
Completado 19.524; Material sin recibir 3.315; Pendiente pedido 2.740;
SC anulada 1.840; Parcialmente aprobadas 278; Pendiente aprobación 244;
Pendiente conciliación 16; Recibido con incidencia (provisional) 3.
Las 1.840 anuladas tienen cero pedidos positivos vinculados.
