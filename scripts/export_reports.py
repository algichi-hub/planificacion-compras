"""Generate reproducible Excel/CSV planning reports from a validated snapshot."""
import argparse
import os
from pathlib import Path
import pandas as pd
import psycopg

QUERIES={
 "cobertura_sc":"""SELECT company,sc_no,sc_pos,article,description,project,centre,requested_qty,
 ordered_qty,received_qty,approved_qty,coverage_state,coverage_pct
 FROM planning.v_sc_coverage WHERE snapshot_id=%s ORDER BY sc_no,sc_pos""",
 "detalle_recepciones":"""SELECT l.company,l.sc_no,l.sc_pos,l.po_no,l.po_pos,
 r.receipt_no,r.article,r.receipt_date,r.delivered_qty,r.approved_qty,r.erp_status,l.allocation_status
 FROM core.sc_po_links l LEFT JOIN core.receipts r
 ON r.snapshot_id=l.snapshot_id AND r.po_no=l.po_no AND r.po_pos=l.po_pos
 WHERE l.snapshot_id=%s ORDER BY l.sc_no,l.sc_pos,l.po_no,r.receipt_no""",
 "incidencias":"""SELECT record_no,sequence_no,po_no,po_pos,article,category,resolved,detail
 FROM core.incidents WHERE snapshot_id=%s ORDER BY record_no""",
 "calidad":"""SELECT source_name,line_number,severity,issue_code,details
 FROM audit.import_issues WHERE snapshot_id=%s ORDER BY id""",
}
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshot",required=True,type=int)
    ap.add_argument("--out",default="informes")
    args=ap.parse_args()
    if not os.environ.get("DATABASE_URL"):
        ap.error("Set DATABASE_URL first")
    out=Path(args.out)/f"snapshot_{args.snapshot}"
    out.mkdir(parents=True,exist_ok=True)
    datasets={}
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        with db.cursor() as cur:
            cur.execute("SELECT state FROM audit.snapshots WHERE id=%s",(args.snapshot,))
            state=cur.fetchone()
            if not state or state[0] not in ("validated","active"):
                ap.error("Snapshot does not exist or is not validated")
            for name,sql in QUERIES.items():
                cur.execute(sql,(args.snapshot,))
                datasets[name]=pd.DataFrame(cur.fetchall(),columns=[c.name for c in cur.description])
    for name,df in datasets.items():
        df.to_csv(out/f"{name}.csv",sep=";",decimal=",",encoding="utf-8-sig",index=False)
    with pd.ExcelWriter(out/"planificacion_compras.xlsx",engine="openpyxl") as writer:
        for name,df in datasets.items():
            sheet=name[:31]
            df.to_excel(writer,sheet_name=sheet,index=False)
            ws=writer.sheets[sheet]
            ws.freeze_panes="A2"
            if ws.max_row>1 and ws.max_column>0:
                ws.auto_filter.ref=ws.dimensions
            for col in ws.columns:
                letter=col[0].column_letter
                ws.column_dimensions[letter].width=min(48,max(12,max(len(str(c.value or "")) for c in list(col)[:100])+2))
    print("Reports created:",out.resolve())
if __name__=="__main__":
    main()
