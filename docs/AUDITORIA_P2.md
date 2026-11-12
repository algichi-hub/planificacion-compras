# Auditoría P2 — aprobadas > solicitadas

Fecha de investigación: 2026-11-05. No se ha modificado ni activado el snapshot histórico #1.

## Causa raíz comprobada

`SC_FAS.csv` representa los decimales con coma. La fuente `Recepciones_Sevilla.csv` presenta cantidades enteras o con **punto decimal** (p. ej. `21335.986`). El parser anterior aplicaba `decimal_es()` a ambas fuentes, eliminando el punto y transformando `21335.986` en `21335986`.

En la fuente de recepciones hay 436 campos `CANT.ENTREGADA` y 430 campos `CANT.APROBADA` que contienen punto decimal. Los demás campos de cantidad analizados se representan como enteros. No se han observado comas en esos dos campos.

Ejemplo validado contra CSV original y Neon: PO `802418/11`, recepción `749488`. Cantidad real recibida y aprobada: `21335.986`; cantidad almacenada por el importador antiguo: `21335986`.

## Conciliación de las 399 líneas de P2

Análisis reproducido con los tres archivos originales, conciliación SC/PO y suma de recepciones por clave PO + posición.

| Escenario | Líneas con aprobadas > solicitadas |
| --- | ---: |
| Parser de recepción antiguo + criterio SC antiguo | 399 |
| Solo corregir decimal de recepción | 131 |
| Solo corregir desglose SC de P1 | 268 |
| Corregir decimal recepción + P1 | **0** |

Todos los 399 casos iniciales quedan explicados por las dos causas combinadas. Los 131 residuales tras corregir recepción derivan de la contabilización de una SC desglosada con varias posiciones de pedido, ya corregida en P1. Los 268 residuales tras corregir P1 derivan del parser de decimales.

La corrección se aplica en `src/normalize.py:decimal_receipt` y `src/reconcile.py:parse_receipt`. No se aplica a los importes ni cantidades de SC, que conservan `decimal_es`.

## Protecciones y regresión

- Se añade revisión del importador a `audit.snapshots.importer_revision` mediante migración 004.
- El snapshot #1 queda `legacy_pre_p2` y el código actual prohíbe activarlo. No se borra ni se recalcula en producción.
- Una importación nueva registra `p2_receipt_decimal_dot_v1` y puede producir un diagnóstico `APPROVED_EXCEEDS_REQUESTED` si encuentra un exceso real. No se capan ni falsean cantidades.
- Tests unitarios cubren decimales con punto, números enteros, negativos, valores inválidos, decimales españoles de SC y el caso ERP real citado.
- Ejecutar pruebas GitHub Actions y la primera carga nueva con los tres CSV antes de proclamar aceptación integral. Se necesita un snapshot de prueba nuevo; el snapshot #1 sigue reflejando los valores incorrectos.

## Advertencias

La verificación offline de P2 confirma ausencia de excesos por las reglas actuales en los casos analizables; **no valida** que cada recepción esté físicamente disponible ni resuelve problemas de alcance de los extractos, duplicaciones o casos pendientes de conciliación fuera de P2.

Para verificar desde PostgreSQL el snapshot nuevo:
```sql
SELECT count(*) FROM planning.v_sc_coverage
WHERE snapshot_id = :snapshot_id AND approved_qty > requested_qty;
SELECT issue_code,count(*) FROM audit.import_issues
WHERE snapshot_id = :snapshot_id GROUP BY issue_code ORDER BY count(*) DESC;
```
