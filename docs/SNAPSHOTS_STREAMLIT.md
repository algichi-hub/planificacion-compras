# Administración de snapshots desde Streamlit

La pestaña **Snapshots** utiliza la identidad Google existente (`st.login("google")`) y la lista de correos verificados `BULK_ADMIN_EMAILS`. No se ejecutan consultas de inventario mientras la pestaña no está abierta.

## Configuración del despliegue

En los secretos de Streamlit Cloud:

- `[auth]`: configuración de autenticación Google existente (no modificar).
- `BULK_ADMIN_EMAILS`: correos autorizados, separados por coma (existente).
- `DATABASE_URL`: conexión de lectura ya utilizada por el dashboard.
- `SNAPSHOT_ADMIN_DATABASE_URL`: **nueva** conexión PostgreSQL de escritura, guardada **solo** en los secretos del servidor. Debe permitir SELECT y DELETE sobre las tablas de cada snapshot e INSERT en `audit.snapshot_deletions`. Preferir un rol dedicado de mínimos privilegios, no el propietario de Neon. No copiar secretos al repositorio ni mostrarlos en la UI.

Hasta configurar `SNAPSHOT_ADMIN_DATABASE_URL`, el administrador puede consultar el inventario y seleccionar snapshots, pero **no simular ni ejecutar** su eliminación: ambas operaciones requieren comprobar todas las tablas (incluida `raw.source_rows`) con el rol de gestión. La simulación usa ese rol en una transacción explícitamente de **solo lectura**. Nunca se amplían los permisos de `DATABASE_URL` del dashboard. El acceso a esta conexión se valida después de comprobar el usuario Google verificado y autorizado.

## Operación

1. Abrir **Snapshots**. La tabla muestra ID, fecha del snapshot, fecha mínima de aprobación SC, estado, fecha de importación, estadísticas, número de CSV y auditoría.
2. Marcar uno o varios snapshots en la columna **Eliminar**. El vigente puede seleccionarse siempre que quede algún otro validado.
3. Pulsar **Simular eliminación**. Se consultan las dependencias de claves foráneas, las filas afectadas y el nuevo vigente. Es de solo lectura.
4. Revisar el detalle de tablas por snapshot y las fechas de cobertura.
5. Pulsar **Eliminar seleccionados**, escribir `ELIMINAR` y confirmar. Se abre una **única** transacción para todos los seleccionados, se serializan los borrados del servicio, se verifica que el plan sigue siendo idéntico y se elimina con auditoría.
6. La app invalida solo las cachés de inventario y selección, conserva la sesión y determina automáticamente el nuevo vigente según `snapshot_date DESC, id DESC`.

No existe columna `active` ni reasignación con UPDATE. El vigente es el último snapshot validado disponible. No se puede borrar el último validado.

La auditoría permanente guarda `deleted_by` con el correo Google autorizado; las eliminaciones antiguas por CLI seguirán mostrando el rol PostgreSQL. La tabla histórica no depende de la fila del snapshot eliminado.

## Rendimiento y seguridad

- Inventario: **una consulta** solo al entrar en la pestaña, `st.cache_data(ttl=600)` y botón de actualización explícito.
- Detalle de CSV, estados y advertencias: solo al expandir **Detalle de importación**, no en el flujo normal.
- Simulación: consultas adicionales por snapshot únicamente al pulsar el botón.
- Confirmación: reconteo bajo bloqueo y comparación SHA-256 del plan, contra operaciones concurrentes o datos obsoletos.
- Sin polling, sin cambios en datos de importación salvo eliminación autorizada y confirmada.
- Si se produce cualquier error en un DELETE o en su auditoría, PostgreSQL revierte **todo el lote**.

## Validación

CI ejecuta las pruebas de autorización, protección del último validado, dependencia de claves foráneas, invalidez de planes caducados y regresión existente. No se prueban eliminaciones en Neon productivo: es necesaria la prueba funcional de la interfaz desplegada con cuenta ADMIN y un snapshot descartable antes de considerar el flujo de escritura validado en producción.
