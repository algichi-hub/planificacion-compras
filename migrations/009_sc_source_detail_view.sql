-- Read-only, least-privilege SC source projection. No prices, amounts or invoices.
CREATE INDEX IF NOT EXISTS ix_sc_source_rows_lookup
ON raw.source_rows (
 snapshot_id,
 (fields->>'COMPAÑÍA__0'),
 (fields->>'SOLICITUD__6'),
 (fields->>'POSICIÓN__7')
)
WHERE source_name='SC_FAS.csv';

CREATE OR REPLACE VIEW planning.v_sc_source_detail AS
SELECT snapshot_id,source_line,
       fields->>'COMPAÑÍA__0' AS company,
       fields->>'SOLICITUD__6' AS sc_no,
       fields->>'POSICIÓN__7' AS sc_pos,
       jsonb_build_object(
         'FECHA APROBACIÓN__12',fields->>'FECHA APROBACIÓN__12',
         'FECHA ENTREGA SOLICITUD__13',fields->>'FECHA ENTREGA SOLICITUD__13',
         'PEDIDO__16',fields->>'PEDIDO__16',
         'POSICIÓN__17',fields->>'POSICIÓN__17',
         'NOMBRE__24',fields->>'NOMBRE__24',
         'COMPRADOR__45',fields->>'COMPRADOR__45',
         'ESTADO COMPRAS__5',fields->>'ESTADO COMPRAS__5',
         'FECHA APROBACIÓN DEL PEDIDO__41',fields->>'FECHA APROBACIÓN DEL PEDIDO__41',
         'FECHA PLANIFICADA__26',fields->>'FECHA PLANIFICADA__26'
       ) AS fields
FROM raw.source_rows
WHERE source_name='SC_FAS.csv';

GRANT SELECT ON planning.v_sc_source_detail TO compras_reader;
