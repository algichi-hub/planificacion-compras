# Directrices de desarrollo — Planificación de Compras

## Propósito
Para cada SC y posición calcular la cantidad solicitada, pedida, recibida y aprobada con trazabilidad SC → PO → recepción.
Las cantidades aprobadas documentalmente NO representan existencias disponibles.

## Datos
Tres CSV: SC_FAS.csv (pipe), INC_FAS.csv (punto y coma), Recepciones_Sevilla.csv (punto y coma). Codificación heredada cp1252, decimales españoles, fechas DD/MM/AA. La tercera fuente siempre se recibe descomprimida como CSV.

## Reglas no negociables
- No exponer datos, credenciales ni CSV en Git.
- Carga idempotente por fecha de corte y hashes; no modificar snapshots activados sin consentimiento.
- No atribuir una recepción a varias SC ni sumar cantidades con granularidad distinta.
- Ante claves o cantidades conflictivas, registrar pending_reconciliation en vez de inventar un estado.
- No confundir approved_qty con stock utilizable.
- Ejecución cloud en Neon PostgreSQL 18 y migración posible a PostgreSQL local vacío.
- SQL parametrizado; migraciones versionadas; acceso de lectura separado de importación.
- Frontend Streamlit claro, blanco, bordes gris claro, responsive y tablas exportables.
- Sin sondeo periódico; actualizaciones manuales una vez por semana.
- GitHub develop para trabajo; main solo tras validación de regresión.
- Diferenciar ejecución automatizada de validación real en Streamlit Cloud o Windows.

## Validación mínima
Parser, claves, duplicados, recepciones parciales, ajustes negativos, incidentes, concatenaciones erróneas por separadores, fechas, montos, estados ERP contradictorios y exportaciones de números.
