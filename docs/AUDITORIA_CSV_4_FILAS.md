# Auditoría de cuatro registros malformados del snapshot 5

## Evidencia y causa raíz (archivos ERP originales)

El snapshot 5 se importó con filtro de aprobación SC >= 2026-01-20. Su importador anterior registró cuatro `MALFORMED_ROW`. Las líneas indicadas se contrastaron con los CSV originales (lectura `csv.reader`, separadores `|` y `;`, decodificación CP1252).

| Archivo y línea física | Clave ERP | Defecto identificado | Reparación |
|---|---|---|---|
| SC_FAS.csv:50791 | SC 750551 / posición 10 | 53 columnas frente a 52, una celda vacía espuria en posición 47, antes de QR | Quitar solo la celda vacía si fechas, cantidades, QR y referencia final se validan |
| SC_FAS.csv:52636 | SC 750683 / posición 10 | Igual al anterior | Igual |
| SC_FAS.csv:52788 | SC 750708 / posición 530 | Igual al anterior | Igual |
| INC_FAS.csv:4408 | PO 730301 / posición 1 | 34 columnas frente a 28 útiles: un `;` dentro de descripción, varios `;` dentro de observaciones y dos campos vacíos terminales | Concatenar la descripción y las observaciones conservando separadores; descartar únicamente las dos celdas terminales vacías |

La anomalía de incidencias además desplazaba la columna `Resuelto`, por lo que el reparador anterior fallaba su validación. La nueva rama comprueba fechas, cantidades, identificadores y estado `Resuelto` tras restaurar las posiciones de columna. Si no se cumplen los anclajes, la fila sigue siendo inválida, sin forzar interpretaciones.

## Comprobaciones realizadas

- Las cuatro filas concretas del fichero real se recuperaron con las reglas propuestas.
- Explorados los archivos originales: la rama estricta específica recupera exactamente las tres filas SC y una fila INC; no se identificaron otras coincidencias de estos dos patrones.
- GitHub Actions: pruebas unitarias y regresión superadas, incluidas pruebas de rechazo de desplazamientos inseguros y regresión del reparador previo de descripciones.
- **No se ha reimportado ni modificado el snapshot 5**, que conserva los cuatro errores en su histórico.

## Efecto del filtro parcial

Las tres SC son aprobaciones del 2025, anteriores al corte 2026-01-20. La posición PO 730301/1 de la incidencia no aparece entre los pedidos seleccionados en snapshot 5. Por tanto, las cuatro filas están fuera del universo de conciliación del snapshot filtrado, aunque se contabilizaron como errores estructurales de los archivos de entrada.

Al repetir el mismo corte con el importador actualizado y los mismos archivos de origen, el resultado esperado es cero `MALFORMED_ROW` de estas cuatro filas; permanecerán las advertencias `DELIMITER_REPAIRED` y `SC_APPROVAL_DATE_CONFLICT` del subconjunto seleccionado. No afirmar esta cifra como resultado de una nueva importación hasta contrastarla en Neon.
