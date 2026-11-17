# Comandos de snapshots semanales

## Actualizar código y dependencias

```powershell
git pull origin develop
python -m pip install -r requirements.txt
python -m pytest -q
```

## Importar con progreso en consola

```powershell
python scripts/import_snapshot.py --date 2026-11-06 --input entrada
```

Ahora se muestran las fases de importación y tres indicadores `tqdm`, uno por fuente. El progreso mide líneas leídas y remitidas a `COPY` de PostgreSQL; **100 % de la barra no significa que Neon haya terminado el commit**. A continuación se visualizan las fases de conciliación y confirmación de la transacción. El tiempo de espera de Neon y el commit final no permiten porcentajes exactos. Use `--no-progress` para desactivar la barra si se registra la salida en un log.

## Consultar y eliminar snapshots

```powershell
python scripts/manage_snapshots.py --list
python scripts/manage_snapshots.py --delete 1
```

`--delete 1` es únicamente una **simulación**: presenta las tablas afectadas y los recuentos, sin escribir ni borrar.

Después de revisar el resultado, para eliminar realmente un snapshot **no activo**:

```powershell
python scripts/manage_snapshots.py --delete 1 --confirm 1
```

Esta operación es irreversible a través de la aplicación; realizar respaldo si el contenido es importante. Elimina en una sola transacción los datos dependientes del snapshot en `core`, `raw`, `audit.source_files` y `audit.import_issues`. Guarda fecha, hashes y recuentos en `audit.snapshot_deletions`. Si alguna operación falla, la transacción revierte todos los borrados. Por seguridad, los snapshots activos no pueden eliminarse, aunque se proporcione la confirmación.

**No se ha eliminado ningún snapshot en Neon durante esta implementación.**

El campo `snapshot_date` es único: borrar un snapshot permite posteriormente reutilizar su fecha de corte, pero solo después de una operación explícita y auditada.

## Importación parcial por fecha de aprobación SC

```powershell
python scripts/import_snapshot.py --date 2026-11-06 --from 2025-01-20 --input entrada
```

`--from` aplica un corte **inclusivo** sobre `FECHA APROBACIÓN` del fichero `SC_FAS.csv`, **no** sobre creación SC, fecha de pedido ni fecha de recepción. La fecha se pasa como ISO `YYYY-MM-DD`.

Se selecciona toda la solicitud (compañía + número SC) si cualquiera de sus registros tiene aprobación igual o posterior al corte; se mantienen todas sus posiciones y sus enlaces PO. Se importan únicamente recepciones e incidencias cuya pareja pedido/posición aparezca vinculada a las SC seleccionadas. Se incluyen las recepciones independientemente de su fecha; sin filtro se conserva la importación habitual completa.

Si alguna SC seleccionada presenta fechas de aprobación distintas, se conserva entera y se registra `SC_APPROVAL_DATE_CONFLICT`. Si faltan fechas o son ilegibles, el filtrado se aborta para evitar excluir registros sin conocimiento. Las filas estructuralmente malformadas se registran por la vía normal.

`audit.snapshots.sc_approved_from` registra el corte; es `NULL` si no hubo filtro. Los hashes de origen son de los CSV completos. Los contadores de progreso reportan total, incluidos, excluidos y malformados. Las cifras agregadas del tablero son **solo del universo de SC seleccionadas** y no equivalen al total del ERP.

Si una posición PO coincide con solicitudes externas al universo seleccionado, la pertenencia de sus recepciones debe revisarse en la auditoría, porque el CSV de recepciones no contiene la compañía.

## Rendimiento de la conciliación y auditoría P2

La fase [3/4] confirma el snapshot sin consultar la costosa vista `planning.v_sc_coverage`. La auditoría de cobertura se realiza **después** y en un proceso independiente:

```powershell
python scripts/audit_snapshot.py --snapshot 2 --timeout 30
```

El timeout es por consulta, en segundos. Si la vista excede el plazo, la auditoría responde `AUDIT INCOMPLETE` y la importación anterior permanece confirmada y sin activar; no se debe aceptar P2 hasta resolver la consulta.
