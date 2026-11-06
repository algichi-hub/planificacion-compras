"""P3: forensic, read-only PO over-delivery audit against ALL original CSV rows.

Never modify receipt or approval quantities. Only unresolved PO positions receive
a comment in the UTF-8-BOM, semicolon-delimited Excel report.
"""
import argparse
import csv
import os
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.normalize import iter_source, indexed, decimal_es
from src.reconcile import parse_receipt, parse_incident


def classify_position(ordered, delivered, approved, records, full_match=True,
                      other_owners=False, transfer_context=False):
    """Classification deliberately does NOT invent ERP movement semantics."""
    if not full_match:
        return "FUENTE_INCONSISTENTE", "Los movimientos no coinciden con el CSV completo; revisar origen y filtro."
    if other_owners:
        return "PEDIDO_COMPARTIDO", "La posicion PO pertenece a otras SC del universo completo; revisar asignacion."
    if ordered is None:
        return "CANTIDAD_PEDIDA_INDETERMINADA", "No se puede determinar cantidad pedida."
    if approved > ordered:
        return "APROBADO_EXCEDE_PEDIDO", "Aprobado supera cantidad pedida; requiere revision."
    if ordered == 0 and delivered > 0 and approved == 0 and transfer_context:
        return "TRANSFERIDA_NOMINAL_CONFORME", ""
    if ordered == 0 and delivered > 0:
        return "PEDIDO_CERO_CON_ENTREGA", "Pedido real 0 con entrega positiva; no se ha confirmado conciliacion nominal y transferencia."
    if approved < ordered and delivered > ordered:
        return "APROBACION_INCOMPLETA_CON_SOBREENTREGA", "Entregado supera pedido y aprobado aun no cubre pedido; revisar movimientos."
    if approved == ordered and delivered > ordered:
        # The gross quantity is greater but approval coverage is coherent;
        # an unapproved gross movement is NOT necessarily a duplicate.
        return "COBERTURA_APROBADA_CONFORME", ""
    if delivered > ordered:
        return "SOBREENTREGA_SIN_CONCILIAR", "Entregas mayores que pedido sin conciliacion concluyente."
    return "SIN_EXCESO", ""


def receipt_signature(receipt):
    return (receipt["po_no"], receipt["po_pos"], receipt["receipt_no"],
            receipt["article"], receipt["receipt_date"],
            receipt["delivered"], receipt["approved"], receipt["status"])


def inspect_universe(root, keys):
    """Read every original CSV, not merely records imported by --from."""
    root=Path(root)
    sc_owners=defaultdict(set)
    sc_context=defaultdict(set)
    full_receipts=defaultdict(Counter)
    incidents=defaultdict(int)
    scanned={}
    for filename,separator in (("SC_FAS.csv","|"),("INC_FAS.csv",";"),
                                ("Recepciones_Sevilla.csv",";")):
        if not (root/filename).is_file():
            raise FileNotFoundError(root/filename)
        n=malformed=0
        for line,record,error in iter_source(root/filename,separator):
            n+=1
            if error:
                malformed+=1
                continue
            if filename=="SC_FAS.csv":
                key=(indexed(record,16),indexed(record,17))
                if key in keys:
                    sc_owners[key].add((indexed(record,0),indexed(record,6),indexed(record,7)))
                    sc_context[key].add((decimal_es(indexed(record,18)),
                                         decimal_es(indexed(record,11)),
                                         indexed(record,5)))
            elif filename=="Recepciones_Sevilla.csv":
                key=(indexed(record,0),indexed(record,1))
                if key in keys:
                    receipt=parse_receipt(record)
                    full_receipts[key][receipt_signature(receipt)]+=1
            else:
                key=(indexed(record,2),indexed(record,3))
                if key in keys:
                    parse_incident(record)  # preserve validation path
                    incidents[key]+=1
        scanned[filename]=(n,malformed)
        if malformed:
            raise ValueError(
                f"{filename}: {malformed} malformed records in full input; "
                "P3 source completeness cannot be guaranteed"
            )
    return sc_owners,sc_context,full_receipts,incidents,scanned


def analyse_rows(pos, receipts, universe_owners, universe_receipts, universe_incidents, universe_sc_context=None):
    """Pure decision kernel; issues contain comments only for failed reconciliation."""
    rows=[]
    universe_sc_context=universe_sc_context or {}
    all_keys={(p["po_no"],p["po_pos"]) for p in pos}
    by_key=defaultdict(list)
    for r in receipts:
        key=(r["po_no"],r["po_pos"])
        if key in all_keys:
            by_key[key].append(r)
    for p in pos:
        key=(p["po_no"],p["po_pos"])
        db_receipts=by_key[key]
        db_signatures=Counter(receipt_signature(r) for r in db_receipts)
        full_ok=(db_signatures == universe_receipts.get(key,Counter()))
        expected={(p["company"],p["sc_no"],p["sc_pos"])}
        actual_owners=universe_owners.get(key,set())
        foreign_owners=actual_owners-expected
        if not actual_owners or not expected.issubset(actual_owners):
            full_ok=False
        delivered=sum((r["delivered"] or Decimal(0) for r in db_receipts),Decimal(0))
        approved=sum((r["approved"] or Decimal(0) for r in db_receipts),Decimal(0))
        context=universe_sc_context.get(key,set())
        # This explains a zero REAL order when the original nominal ordered
        # quantity matches delivered and the ERP marks the PO as transferred.
        transfer_context=(len(context)==1 and
                          (delivered,Decimal(0),"Transferida") in context)
        status,comment=classify_position(p["ordered"],delivered,approved,db_receipts,
                                         full_ok,bool(foreign_owners),transfer_context)
        rows.append(dict(po_no=p["po_no"],po_pos=p["po_pos"],
                         sc_no=p["sc_no"],sc_pos=p["sc_pos"],article=p["article"],
                         ordered=p["ordered"],delivered=delivered,approved=approved,
                         receipt_count=len(db_receipts),incidents=universe_incidents.get(key,0),
                         status=status,comment=comment))
    return rows


def csv_number(value):
    if value is None:
        return ""
    return format(value,"f").replace(".",",")


def write_report(path, rows):
    """Only unresolved rows; Excel ES: semicolon, BOM, comma decimals."""
    path=Path(path)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing audit: {path}")
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as fh:
        writer=csv.writer(fh,delimiter=";",quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["PEDIDO","POSICIÓN PO","SC","POSICIÓN SC","ARTÍCULO",
                         "PEDIDO CANTIDAD","ENTREGADO","APROBADO",
                         "RECEPCIONES","INCIDENCIAS","CÓDIGO","COMENTARIO"])
        for x in rows:
            if not x["comment"]:
                continue
            writer.writerow([x["po_no"],x["po_pos"],x["sc_no"],x["sc_pos"],x["article"],
                             csv_number(x["ordered"]),csv_number(x["delivered"]),
                             csv_number(x["approved"]),x["receipt_count"],
                             x["incidents"],x["status"],x["comment"]])


def audit(snapshot_id,root,output):
    if snapshot_id<=0:
        raise ValueError("Positive snapshot ID required")
    url=os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("Set DATABASE_URL outside the repository")
    with psycopg.connect(url) as db:
        with db.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SELECT state FROM audit.snapshots WHERE id=%s",(snapshot_id,))
            if cur.fetchone() is None:
                raise ValueError("Snapshot not found")
            # 43 expected on snapshot 6: one row per PO position with unambiguous SC.
            cur.execute("""
                WITH r AS (
                    SELECT po_no,po_pos,sum(delivered_qty) delivered
                    FROM core.receipts WHERE snapshot_id=%s GROUP BY 1,2
                ) SELECT p.po_no,p.po_pos,p.company,l.sc_no,l.sc_pos,p.article,p.ordered_qty
                FROM core.po_lines p
                JOIN r ON r.po_no=p.po_no AND r.po_pos=p.po_pos
                JOIN core.sc_po_links l ON l.snapshot_id=p.snapshot_id
                   AND l.company=p.company AND l.po_no=p.po_no AND l.po_pos=p.po_pos
                WHERE p.snapshot_id=%s AND r.delivered>p.ordered_qty
                ORDER BY p.po_no,p.po_pos
            """,(snapshot_id,snapshot_id))
            positions=[dict(zip(["po_no","po_pos","company","sc_no","sc_pos",
                                 "article","ordered"],record)) for record in cur.fetchall()]
            cur.execute("""
                SELECT po_no,po_pos,receipt_no,article,receipt_date,delivered_qty,
                       approved_qty,erp_status
                FROM core.receipts WHERE snapshot_id=%s
            """,(snapshot_id,))
            receipts=[dict(zip(["po_no","po_pos","receipt_no","article","receipt_date",
                                 "delivered","approved","status"],record))
                      for record in cur.fetchall()]
    keys={(p["po_no"],p["po_pos"]) for p in positions}
    if len(keys)!=len(positions):
        raise ValueError("PO position mapped to multiple SC; cannot produce one-to-one audit")
    print(f"Auditing {len(keys)} over-delivered PO positions against ALL input files...",flush=True)
    owners,context,full_receipts,incidents,scanned=inspect_universe(root,keys)
    results=analyse_rows(positions,receipts,owners,full_receipts,incidents,context)
    write_report(output,results)
    counts=Counter(x["status"] for x in results)
    print("CSV universe inspected:",scanned)
    print("Status:",dict(counts))
    print(f"Unresolved positions with comment: {sum(bool(x['comment']) for x in results)}")
    print(f"Report: {output}")
    return results


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot",type=int,required=True)
    ap.add_argument("--input",default="entrada")
    ap.add_argument("--output",default="auditoria_p3.csv")
    args=ap.parse_args()
    audit(args.snapshot,args.input,args.output)

if __name__=="__main__":
    main()
