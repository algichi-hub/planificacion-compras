# P3 — Auditoría de sobreentregas (snapshot 6)

## Alcance y metodología

La auditoría no modifica ninguna cantidad, snapshot ni tabla de Neon. Consulta las posiciones del snapshot y **recorre íntegros** los tres CSV originales: `SC_FAS.csv`, `INC_FAS.csv` y `Recepciones_Sevilla.csv`, aunque el snapshot se haya importado con `--from`. Rechaza el análisis si un fichero contiene filas estructuralmente malformadas, sin descartar inadvertidamente una posible relación.

Para cada PO/posición con `SUM(entregado) > pedido_real`, compara contra los CSV completos:
- Todas las SC propietarias de esa posición (incluidas las excluidas por `--from`).
- La identidad y cantidades de **todos** los movimientos de recepción (`po_no,po_pos,receipt_no,article,date,delivered,approved,status`).
- Las incidencias del pedido/posición.
- `CANTIDAD PEDIDO` (cantidad nominal), `PEDIDA REAL` (cantidad real) y `SOLICITADA REAL`, sin sustituir ni fusionar estos campos.

## Hallazgos SQL sobre el snapshot 6 (sin modificación de datos)

43 posiciones aparentaban sobreentrega (467 unidades de diferencia bruta respecto a `PEDIDA REAL`). Se contrastó con el histórico completo del snapshot 1: **las 43 tienen el mismo número de movimientos de recepción** en ambos snapshots; no se observan SC externas ni incidencias vinculadas en ese conjunto.

- **30 posiciones**: la suma de cantidades aprobadas cubre exactamente `PEDIDA REAL`; los movimientos de entrega incluyen cantidades no aprobadas (por ejemplo, pedido 761214/3: pedida 42, entregada 84, aprobada 42). No hay evidencia suficiente para declarar duplicación física o borrar movimientos.
- **10 posiciones**: `PEDIDA REAL=0`, `SOLICITADA REAL=0`, `ESTADO COMPRAS=Transferida` y `CANTIDAD PEDIDO` nominal coincide exactamente con la cantidad entregada; aprobado=0. No es correcto concluir que nunca se pidió material. Se conserva este estado distinto en la auditoría.
- **3 posiciones**: exceso de entregas y aprobación que no cubre el pedido: `761596/1` (pedido 12, entregado 34, aprobado 4), `761695/29` (11,18,9) y `761258/1` (4,5,0). Estas requieren revisión del ERP. No se corrigen automáticamente.

Los estados textuales del ERP pueden contradecir las cantidades (`Todo aprobado` con aprobado 0 y `Libre` con aprobación plena). Por ello, se usan cantidades y evidencias originales para conciliar, no el estado textual como sustituto de aprobación.

## Implementación

```powershell
git pull origin develop
python -m pytest -q
python scripts/audit_p3.py --snapshot 6 --input entrada --output auditoria_p3_6.csv
```

El comando muestra el total de posiciones evaluadas y su clasificación. El CSV se genera **solo para las posiciones sin conciliación concluyente**; en el snapshot 6 se esperan 3 comentarios si los ficheros locales son los originales. En la salida CSV se emplean `;`, UTF-8 con BOM, encabezados y números con coma decimal, sin separador de miles. Si el informe ya existe, el script no lo sobrescribe.

No se modifica el importador ni el snapshot 6. El CSV P3 es un **reporte diagnóstico local**. Si se modifican los archivos de entrada, la auditoría debe repetirse y contrastar hashes. Las cifras esperadas no equivalen a una ejecución real del script sobre los archivos del usuario hasta que este lo ejecute en Windows.

## Límite de interpretación

La conciliación numérica de `aprobado` o `CANTIDAD PEDIDO` **no demuestra que una recepción haya sido físicamente duplicada o anulada**. Para resolver físicamente ese extremo harían falta movimientos de devolución/anulación o evidencia documental adicional. No sumar cantidades de distintos artículos como una magnitud homogénea de stock.

## Interpretación operativa acordada (P3)

**Cancelación:** `PEDIDA REAL = 0` identifica un pedido cancelado, aunque la SC permanezca en estado `Transferida`. Si el ERP conserva una cantidad nominal y recepciones históricas con aprobación cero, el auditor etiqueta `PEDIDO_CANCELADO_CON_HISTORICO` sin inventar sobreentrega activa ni añadir un comentario de excepción. Si aún aparecen aprobaciones positivas, genera comentario `P3-CANCELACION` para revisión.

**Regularización potencial:** el exceso bruto entregado puede reflejar movimientos históricos de regularización. Cuando `APROBADA = PEDIDA REAL` y el universo de fuentes coincide, se conserva `COBERTURA_APROBADA_CONFORME`, sin afirmar que haya un duplicado físico y sin emitir comentario excepcional.

**Conciliación pendiente:** si `ENTREGADA > PEDIDA REAL > APROBADA`, el comentario interno generado usa el código `P3-REGULARIZACION_PENDIENTE`, cuantifica el exceso bruto entregado y la aprobación pendiente, y pide contrastar partes de recepción, rechazos, devoluciones y aceptaciones en el ERP. Esto cubre los tres pedidos 761596/1, 761695/29 y 761258/1 y otros casos equivalentes en futuras auditorías.

El comentario interno está en la columna `COMENTARIO INTERNO` del CSV diagnóstico, **no se inserta ni se persiste en Neon**. Esto evita contaminar cantidades y estados históricos con hipótesis. El CSV se conserva como evidencia de auditoría y puede integrarse posteriormente en un modelo persistente de incidencias con identificador, estado y revisión humana.
