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
