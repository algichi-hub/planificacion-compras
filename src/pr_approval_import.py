"""Optional fourth CSV: only F_PEND_RETIRAR as PR approval date.

Core receipt quantities and original SC workflow always remain authoritative.
"""
import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HEADER = ('RECEPCIÓN','ORDEN','POSICIÓN','REAC','SECUENCIA','PROYECTO',
    'NOMBRE_PROVEEDOR','ARTICULO','DESCRIPCION','CANTIDAD','C_RECHAZADA',
    'F_ACTUAL','F_EXW','F_ENTRADA','F_RECEPCIÓN','H_RECEPCIÓN',
    'F_PEND_UTILIDAD','H_PEND_UTILIDAD','F_PEND_RETIRAR','H_PEND_RETIRAR',
    'F_RETIRADO','H_RETIRADO','ESTADO','UBICACIÓN','UBICACIÓN_FINAL',
    'INCIDENCIA','N_REGITRO','BULTOS','F_APROB_DOC','TEXTO')


def _date(value):
    value=value.strip()
    if not value:
        return None
    for fmt in ('%d/%m/%y','%d/%m/%Y'):
        try:
            return datetime.strptime(value,fmt).date()
        except ValueError:
            pass
    raise ValueError(f'invalid date {value!r}')


def parse_totales(path):
    """Yield (source_line, (PR,PO,position,approval,receipt_date), issue).

    Repair only the documented extra separator inside UBICACIÓN_FINAL.
    """
    with Path(path).open(encoding='cp1252',errors='replace',newline='') as handle:
        reader=csv.reader(handle,delimiter=';',quoting=csv.QUOTE_NONE)
        if tuple(x.strip().lstrip('\ufeff') for x in next(reader)) != HEADER:
            raise ValueError('Unexpected RecepcionesTotales.csv columns')
        for line,fields in enumerate(reader,2):
            repair=False
            if len(fields)==31:
                candidate=fields[:24]+[';'.join(fields[24:26])]+fields[26:]
                if (len(candidate)==30 and candidate[26].strip().isdigit()
                        and candidate[27].strip().isdigit()):
                    fields=candidate
                    repair=True
            if len(fields)!=30:
                yield line,None,('MALFORMED_ROW',f'Unexpected {len(fields)} columns')
                continue
            if any('\ufffd' in fields[i] for i in (0,1,2,14,18)):
                yield line,None,('INVALID_ENCODING','Replacement character in key/date')
                continue
            pr,po,pos=(fields[i].strip() for i in (0,1,2))
            if not all((pr,po,pos)) or not all(k.isdigit() for k in (pr,po,pos)):
                yield line,None,('INVALID_KEY',f'Invalid PR/PO/position: {pr}/{po}/{pos}')
                continue
            try:
                approval=_date(fields[18])
                received=_date(fields[14])
            except ValueError as exc:
                yield line,None,('INVALID_DATE',str(exc))
                continue
            yield line,(pr,po,pos,approval,received),(
                'DELIMITER_REPAIRED','Extra separator in UBICACIÓN_FINAL'
            ) if repair else None


def reconcile_totales(rows, principal, snapshot_day):
    """Join to the already imported core.receipts; never repeat SC selection.

    principal rows: (receipt_no, po_no, po_pos, receipt_date).
    Returns accepted PR approvals, conflicting PRs, counters and auditable issues.
    """
    primary=defaultdict(list)
    for pr,po,pos,received in principal:
        primary[str(pr)].append((str(po),str(pos),received))
    source=defaultdict(list)
    issues=[]
    counts=Counter()
    for line,item,issue in rows:
        counts['rows_total']+=1
        if issue:
            issues.append((line,'warning' if item else 'error',issue[0],issue[1]))
        if item is not None:
            counts['rows_parsed']+=1
            source[item[0]].append((line,item))
        else:
            counts['rows_invalid']+=1
    accepted=[]
    conflicts=[]
    for pr,primary_rows in primary.items():
        candidates=source.get(pr,[])
        if not candidates:
            counts['no_source_pr']+=1
            continue
        if len(candidates)!=1 or len(primary_rows)!=1:
            conflicts.append((pr,'AMBIGUOUS_PR'))
            counts['ambiguous_pr']+=1
            continue
        line,(_,po,pos,approval,totales_received)=candidates[0]
        expected_po,expected_pos,primary_received=primary_rows[0]
        if (po,pos)!=(expected_po,expected_pos):
            conflicts.append((pr,'PO_POSITION_MISMATCH'))
            issues.append((line,'error','PO_POSITION_MISMATCH',
                           f'PR {pr}: {po}/{pos} vs {expected_po}/{expected_pos}'))
            counts['key_conflict']+=1
            continue
        if totales_received and primary_received and totales_received!=primary_received:
            issues.append((line,'warning','RECEIPT_DATE_MISMATCH',
                           f'PR {pr}: different ERP receipt dates'))
            conflicts.append((pr,'RECEIPT_DATE_MISMATCH'))
            counts['receipt_date_mismatch']+=1
            continue
        if approval is None:
            counts['missing_approval_date']+=1
            continue
        if primary_received and approval<primary_received:
            conflicts.append((pr,'APPROVAL_BEFORE_RECEIPT'))
            issues.append((line,'error','APPROVAL_BEFORE_RECEIPT',
                           f'PR {pr}: approval precedes ERP receipt'))
            counts['impossible_date']+=1
            continue
        if approval>snapshot_day:
            counts['later_approval']+=1
        accepted.append((pr,po,pos,approval,line))
        counts['accepted']+=1
    counts['source_outside_scope']=len(set(source)-set(primary))
    counts['source_matched_pr']=len(set(source)&set(primary))
    return accepted,conflicts,counts,issues


def import_approval_dates(cur, snapshot_id, path, snapshot_day, source_hash):
    """Add dates and exceptional states *within* the caller's transaction."""
    cur.execute(
        'SELECT receipt_no,po_no,po_pos,receipt_date FROM core.receipts WHERE snapshot_id=%s',
        (snapshot_id,))
    accepted,conflicts,counts,issues=reconcile_totales(
        parse_totales(path),cur.fetchall(),snapshot_day)
    # The fourth file is optional for older imports but, when supplied, has
    # fully auditable key coverage; no inferred quantities or receipt updates.
    cur.executemany(
        'INSERT INTO core.pr_approval_dates '
        '(snapshot_id,pr_no,po_no,po_pos,approval_date,source_line) '
        'VALUES (%s,%s,%s,%s,%s,%s)',
        ((snapshot_id,*row) for row in accepted))
    cur.execute(
        'INSERT INTO audit.source_files '
        '(snapshot_id,source_name,sha256,rows_total,rows_ok,rows_invalid) '
        'VALUES (%s,%s,%s,%s,%s,%s)',
        (snapshot_id,'RecepcionesTotales.csv',source_hash,
         counts['rows_total'],counts['rows_parsed'],counts['rows_invalid']))
    # Failures affecting an existing PR are auditable and, when uniquely
    # associated with a verified SC line, receive one exceptional workflow state.
    for pr,reason in conflicts:
        issues.append((None,'warning','PENDING_VERIFICATION',
                       f'PR {pr}: {reason}'))
    cur.executemany(
        'INSERT INTO audit.import_issues '
        '(snapshot_id,source_name,line_number,severity,issue_code,details) '
        'VALUES (%s,%s,%s,%s,%s,%s)',
        ((snapshot_id,'RecepcionesTotales.csv',*item) for item in issues))
    if conflicts:
        cur.execute('CREATE TEMP TABLE tmp_pr_date_conflicts '
                    '(pr_no text PRIMARY KEY) ON COMMIT DROP')
        cur.executemany(
            'INSERT INTO tmp_pr_date_conflicts(pr_no) VALUES (%s) ON CONFLICT DO NOTHING',
            ((pr,) for pr,_ in conflicts))
        # Only one verified SC owner can be assigned a conflicting PR.
        # Do not overwrite SC annulled, or primary-source reconciliation errors.
        cur.execute("""
            WITH owners AS (
              SELECT r.receipt_no, l.company,l.sc_no,l.sc_pos,
                     count(*) OVER (PARTITION BY r.receipt_no) AS nowners
              FROM tmp_pr_date_conflicts c
              JOIN core.receipts r
                ON r.snapshot_id=%s AND r.receipt_no=c.pr_no
              JOIN core.sc_po_links l
                ON l.snapshot_id=r.snapshot_id
               AND l.po_no=r.po_no AND l.po_pos=r.po_pos
               AND l.allocation_status='verified'
            )
            UPDATE planning.sc_workflow_status w
               SET workflow_state='Pendiente verificación'
              FROM owners o
             WHERE o.nowners=1 AND w.snapshot_id=%s
               AND (w.company,w.sc_no,w.sc_pos)=(o.company,o.sc_no,o.sc_pos)
               AND w.workflow_state NOT IN ('SC anulada','Pendiente conciliación')
        """,(snapshot_id,snapshot_id))
        counts['verification_positions']=cur.rowcount
    return counts
