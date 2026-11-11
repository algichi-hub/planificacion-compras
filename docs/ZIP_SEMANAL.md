# Importación semanal desde ZIP cifrado (Windows)

## Entrada única

Depositar exclusivamente **`entrada/planificacion-compras.zip`** como fuente externa.
Dentro deben existir exactamente cuatro archivos en la raíz del ZIP:

- `SC_FAS.csv`
- `INC_FAS.csv`
- `Recepciones_Sevilla.csv`
- `RecepcionesTotales.csv`

El ZIP debe estar protegido por contraseña (AES recomendado). No se aceptan
carpetas internas, archivos adicionales, CSV sin cifrar ni nombres alternativos.
Los CSV anteriores permanecerán en `entrada/` como copia de trabajo para el
importador; **no** es necesario copiarlos o sustituirlos manualmente.

## Preparación inicial

En el equipo que ejecuta el importador, instalar dependencias nuevas:

```powershell
cd C:\ruta\planificacion-compras
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Configurar dos variables de entorno **fuera del repositorio**, disponibles en
la misma cuenta de Windows que ejecutará la tarea semanal:

- `DATABASE_URL`: conexión Neon del importador, como hasta ahora.
- `COMPRAS_ZIP_PASSWORD`: contraseña fija del ZIP. No se pasa como argumento
  (evita aparecer en la línea de comandos), ni se almacena en Git o en el log.

Las variables persistentes de usuario de Windows pueden resultar accesibles a
otros procesos que se ejecuten bajo esa cuenta. Si el entorno requiere mayor
protección, utilizar un gestor de secretos o almacenamiento DPAPI asociado a
la cuenta y cargar los valores solo durante la ejecución. No incluir nunca la
contraseña en un BAT, PS1 ni archivo versionado.

## Comprobación sin escritura en Neon

```powershell
.\.venv\Scripts\python.exe scripts\prepare_input_zip.py --input entrada
```

El gestor usa SHA-256 para comparar el ZIP con la última extracción completa.
Si no ha cambiado y los cuatro CSV siguen íntegros, no escribe nada.
Si ha cambiado o falta/se ha alterado algún CSV, valida y extrae los cuatro
archivos en un directorio temporal dentro de `entrada`, y los reemplaza
solo cuando todas las comprobaciones previas han tenido éxito.

Guarda el manifiesto de hashes en
`entrada/.planificacion_compras_zip_state.json`, sin contraseña.
Si ocurre un fallo durante la sustitución, intenta restaurar todos los CSV
anteriores y no actualiza el manifiesto. Si hay un cierre abrupto del proceso,
la próxima ejecución detectará discrepancias con el manifiesto y reextraerá
el ZIP. El fichero de bloqueo `entrada/.planificacion_compras_import.lock`
evita dos ejecuciones simultáneas; tras un cierre abrupto, confirmar primero
que no queda ninguna importación activa antes de eliminarlo.

Los formatos de columnas y la conciliación completa continúan validándose
en `import_snapshot.py`. La extracción por sí sola **no** valida un snapshot.

## Ejecución semanal

El lanzador existente `scripts\snapshot_semanal_windows.bat` llama a
`scripts\import_snapshot.py`, que ejecuta automáticamente la preparación
**antes de conectarse a Neon**. La fecha del snapshot es la fecha local del PC.

Se puede programar sin instalar software adicional:

1. Abrir **Programador de tareas** de Windows.
2. Crear una tarea para el usuario que dispone de `.venv`, variables y acceso
   a `entrada`; habilitar **Ejecutar solo cuando el usuario haya iniciado sesión**
   si las políticas de la empresa impiden credenciales de tareas en segundo plano.
3. En **Desencadenadores**, elegir **Semanal** y establecer día/hora.
4. En **Acciones**, elegir **Iniciar un programa** y señalar la ruta absoluta a
   `scripts\snapshot_semanal_windows.bat`.
5. En **Configuración**, evitar iniciar una nueva instancia si ya se está ejecutando
   otra; comprobar el código de salida y `audit.import_issues`.

La tarea requiere acceso a Neon y a los archivos locales. Un ZIP no modificado
**no** impide crear el snapshot semanal: solo evita la extracción redundante.

## Seguridad y recuperación

- La importación **falla antes de escribir en Neon** si el ZIP es inválido,
  falta un CSV o no se puede descifrar.
- Los cuatro CSV se mantienen en claro en `entrada` después de extraerlos;
  proteger esa carpeta mediante permisos NTFS, dado que el cifrado aplica
  únicamente al ZIP, no a los CSV descomprimidos.
- Nunca compartir el fichero ZIP junto con su contraseña.
- Los hashes del manifiesto aseguran detección de cambios, no autenticación
  criptográfica del remitente: proteger también la carpeta donde se deposita
  el ZIP y verificar la procedencia del fichero.
- Para recuperar una extracción, conservar el ZIP correcto y ejecutar de nuevo
  el preflight; no eliminar manualmente snapshots validados.
