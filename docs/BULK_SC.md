# Bulk SC: persistencia y acceso administrador

El nuevo panel `Bulk SC` sustituye a `REAC / Incidencias` y `Calidad de datos`.
Los grupos y las descripciones son independientes del snapshot y de los datos ERP.
Por defecto **no hay escrituras habilitadas**.

## Pasos de activación (pendientes de autorización operativa y configuración)

1. Aplicar `migrations/008_bulk_sc_groups.sql` con el procedimiento habitual de
   migraciones versionadas (`python scripts/apply_migrations.py`). **No ejecutado**.
2. Crear en Neon un rol PostgreSQL dedicado, sin herencia de privilegios sobre
   `core`, `raw` ni `audit`, mediante administración controlada.
   Conceder solo:
   ```sql
   GRANT USAGE ON SCHEMA planning TO bulk_sc_admin;
   GRANT SELECT, INSERT ON planning.bulk_sc_groups TO bulk_sc_admin;
   GRANT SELECT, INSERT, UPDATE, DELETE ON planning.bulk_sc_items TO bulk_sc_admin;
   GRANT USAGE, SELECT ON SEQUENCE planning.bulk_sc_groups_id_seq TO bulk_sc_admin;
   GRANT USAGE, SELECT ON SEQUENCE planning.bulk_sc_items_id_seq TO bulk_sc_admin;
   ```
   Verificar derechos efectivos y revocar cualquier privilegio heredado no deseado.
   La aplicación no ofrece eliminación de grupos: solo de sus referencias SC.
3. Registrar una aplicación OIDC (Google, Microsoft u otro proveedor).
   Configurar la URI de devolución:
   `https://planificacion-compras.streamlit.app/oauth2callback`.
4. Configurar los secretos de **Streamlit Cloud**, nunca el repositorio.
   Ejemplo con Google (reemplazar los marcadores por valores reales):
   ```toml
   DATABASE_URL = "postgresql://<lector>"
   BULK_ADMIN_DATABASE_URL = "postgresql://<bulk_sc_admin>"
   BULK_ADMIN_EMAILS = "admin@tu-dominio.com"
   [auth]
   redirect_uri = "https://planificacion-compras.streamlit.app/oauth2callback"
   cookie_secret = "<secreto-aleatorio-largo>"
   client_id = "<oidc-client-id>"
   client_secret = "<oidc-client-secret>"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```
   El administrador requiere correo verificado del proveedor OIDC.
   Solo los correos de `BULK_ADMIN_EMAILS` pueden escribir.
5. Comprobar con una cuenta invitada que puede consultar los grupos pero no
   crear, editar ni eliminar; comprobar el mismo flujo con el administrador.
   Verificar que el rol PostgreSQL no puede modificar tablas ERP.

## Operaciones y protección

- Las ediciones usan SQL parametrizado, operaciones restringidas y transacciones.
- Los números SC son cadenas de dígitos (preservan ceros iniciales).
- En el mismo grupo no se admite repetir una SC; volver a guardar actualiza
  su descripción contextual.
- El tablero solo consulta SC y estados desde las vistas derivadas del
  snapshot seleccionado. Las SC no encontradas siguen en la lista.
- Los grupos se guardan en Neon tras aplicar la migración; los cambios de
  snapshot no eliminan entradas.
- Un despliegue sin `[auth]` o sin `BULK_ADMIN_DATABASE_URL` solo muestra
  controles de lectura. No se habilita una contraseña pública por defecto.
- La consulta del grupo se realiza al pulsar «Consultar grupo»; las consultas
  de datos usan caché de 600 segundos. Una edición invalida la caché.

No se ha probado el inicio de sesión OIDC ni el rol PostgreSQL en producción.
