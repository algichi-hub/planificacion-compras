"""Manual weekly CSV import. No destructive replacement of active snapshots."""
import argparse
import hashlib
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import psycopg
from tqdm import tqdm

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.normalize import iter_source,decimal_es,date_es,is_real_po
from src.reconcile import parse_sc,parse_receipt,parse_incident,summarize_sc,summarize_po

SOURCES={"SC_FAS.csv":"|","INC_FAS.csv":";","Recepciones_Sevilla.csv":";"}
IMPORTER_REVISION="p2_receipt_decimal_dot_v1"

def ensure_current_importer(revision):
    if revision != IMPORTER_REVISION:
        raise ValueError("Snapshot uses an outdated importer revision; reimport original CSV files")

def count_data_lines(path):
    """Count physical lines, excluding the header, for progress display."""
    with open(path, "rb") as fh:
        number=sum(block.count(b"\\n") for block in iter(lambda: fh.read(1024*1024), b""))
    with open(path, "rb") as fh:
        fh.seek(0,2)
        if fh.tell():
            fh.seek(-1,2)
            if fh.read(1)!=b"\\n":
                number+=1
    return max(0,number-1)

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as fp:
        for block in iter(lambda:fp.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def copy_rows(cur,table,cols,records):
    sql=f"COPY {table} ({','.join(cols)}) FROM STDIN"
    with cur.copy(sql) as cp:
        for item in records:
            cp.write_row(item)

def run_import(args):
    root=Path(args.input)
    for name in SOURCES:
        if not (root/name).is_file():
            raise SystemExit(f"Required input missing: {root/name}")
    print("[1/4] Calculating file hashes...",flush=True)
    hashes={name:sha256(root/name) for name in SOURCES}
    sc_records=[]
    issue_rows=[]
    counts={}
    connstr=os.environ.get("DATABASE_URL")
    if not connstr:
        raise SystemExit("Set DATABASE_URL outside the repository")
    with psycopg.connect(connstr) as db:
        with db.transaction():
            with db.cursor() as cur:
                cur.execute("INSERT INTO audit.snapshots(snapshot_date,source_hashes,importer_revision) VALUES (%s,%s::jsonb,%s) RETURNING id",
                            (args.date,__import__("json").dumps(hashes),IMPORTER_REVISION))
                sid=cur.fetchone()[0]
                print("[2/4] Uploading CSV data...",flush=True)
                for source,separator in SOURCES.items():
                    total=valid=bad=0
                    pbar=tqdm(total=count_data_lines(root/source),desc=source[:22],unit="line",
                              disable=getattr(args,"no_progress",False),dynamic_ncols=True,mininterval=0.2)
                    path=root/source
                    def rows():
                        nonlocal total,valid,bad
                        last_line=1
                        for ln,record,error in iter_source(path,separator):
                            pbar.update(max(0,ln-last_line))
                            last_line=ln
                            total+=1
                            if error:
                                bad+=1
                                issue_rows.append((sid,source,ln,"error","MALFORMED_ROW",error))
                                continue
                            valid+=1
                            repair_note=record.pop("__repair_info__",None)
                            if repair_note:
                                issue_rows.append((sid,source,ln,"warning","DELIMITER_REPAIRED",repair_note))
                            if any("\ufffd" in str(value) for value in record.values()):
                                issue_rows.append((sid,source,ln,"warning","INVALID_ENCODING_BYTE",
                                                   "Undefined CP1252 byte replaced during decoding; inspect original file"))
                            yield ln,record
                    if source=="SC_FAS.csv":
                        def sc_raw():
                            for ln,rec in rows():
                                try:
                                    parsed=parse_sc(rec)
                                    sc_records.append(parsed)
                                except ValueError as exc:
                                    issue_rows.append((sid,source,ln,"error","INVALID_VALUE",str(exc)))
                                yield sid,source,ln,__import__("json").dumps(rec,ensure_ascii=False)
                        copy_rows(cur,"raw.source_rows",["snapshot_id","source_name","source_line","fields"],sc_raw())
                    elif source=="Recepciones_Sevilla.csv":
                        def receipt_records():
                            for ln,rec in rows():
                                try:
                                    r=parse_receipt(rec)
                                    if not all((r["po_no"],r["po_pos"],r["receipt_no"])):
                                        raise ValueError("missing receipt key")
                                    if r["approved"] is not None and r["delivered"] is not None and r["approved"]>r["delivered"] and r["delivered"]>=0:
                                        issue_rows.append((sid,source,ln,"warning","APPROVED_GT_DELIVERED","approved quantity exceeds delivered"))
                                    yield sid,ln,None,r["po_no"],r["po_pos"],r["receipt_no"],r["article"],r["receipt_date"],r["delivered"],r["approved"],r["status"]
                                except ValueError as exc:
                                    issue_rows.append((sid,source,ln,"error","INVALID_RECEIPT",str(exc)))
                        copy_rows(cur,"core.receipts",["snapshot_id","source_line","company","po_no","po_pos","receipt_no","article","receipt_date","delivered_qty","approved_qty","erp_status"],receipt_records())
                    else:
                        def incident_records():
                            for ln,rec in rows():
                                try:
                                    r=parse_incident(rec)
                                    yield sid,ln,r["record"],r["sequence"],r["po_no"],r["po_pos"],r["article"],r["category"],r["resolved"],r["detail"]
                                except ValueError as exc:
                                    issue_rows.append((sid,source,ln,"error","INVALID_INCIDENT",str(exc)))
                        copy_rows(cur,"core.incidents",["snapshot_id","source_line","record_no","sequence_no","po_no","po_pos","article","category","resolved","detail"],incident_records())
                    pbar.close()
                    tqdm.write(f"  {source}: {valid:,} parsed; {bad:,} malformed")
                    counts[source]={"total":total,"ok":valid,"invalid":bad}
                    cur.execute("INSERT INTO audit.source_files(snapshot_id,source_name,sha256,rows_total,rows_ok,rows_invalid) VALUES (%s,%s,%s,%s,%s,%s)",(sid,source,hashes[source],total,valid,bad))
                print("[3/4] Conciliating SC / PO and building database tables...",flush=True)
                sc_keys=list(summarize_sc(sc_records))
                copy_rows(cur,"core.sc_lines",["snapshot_id","company","sc_no","sc_pos","article","description","project","centre","project_director","requested_qty","qty_status","required_date"],
                    ((sid,k[0],k[1],k[2],sample["article"],sample["description"],sample["project"],sample["centre"],sample["director"],qty,status,sample["required"]) for k,sample,qty,status in sc_keys))
                po_keys=list(summarize_po(sc_records))
                copy_rows(cur,"core.po_lines",["snapshot_id","company","po_no","po_pos","article","vendor","ordered_qty","planned_date"],
                    ((sid,k[0],k[1],k[2],sample["article"],sample["vendor"],qty,sample["planned"]) for k,sample,qty,status in po_keys))
                po_status={k:status for k,sample,qty,status in po_keys}
                distinct_links={(r["company"],r["sc_no"],r["sc_pos"],r["po_no"],r["po_pos"])
                    for r in sc_records if is_real_po(r["po_no"])}
                po_owners=defaultdict(set)
                for comp,sc,scpos,po,popos in distinct_links:
                    po_owners[(po,popos)].add((comp,sc,scpos))
                copy_rows(cur,"core.sc_po_links",["snapshot_id","company","sc_no","sc_pos","po_no","po_pos","allocation_qty","allocation_status"],
                    ((sid,comp,sc,scpos,po,popos,None,
                      "verified" if len(po_owners[(po,popos)])==1 and po_status.get((comp,po,popos))=="verified" else "ambiguous")
                     for comp,sc,scpos,po,popos in sorted(distinct_links)))
                reac_keys={
                    (r["company"],r["sc_no"],r["sc_pos"],
                     r["po_no"] if is_real_po(r["po_no"]) else "",
                     r["po_pos"] if is_real_po(r["po_no"]) else "",
                     r["reac"],r["reac_article"])
                    for r in sc_records if r.get("reac") and r["reac"] not in ("0","000000")
                }
                copy_rows(cur,"core.reac_refs",
                    ["snapshot_id","company","sc_no","sc_pos","po_no","po_pos","reac_no","reac_article"],
                    ((sid,*r) for r in sorted(reac_keys)))
                for k,sample,qty,status in sc_keys:
                    if status!="verified":
                        issue_rows.append((sid,"SC_FAS.csv",None,"warning",status,f"SC {k}: conflicting or missing requested quantities"))
                for k,sample,qty,status in po_keys:
                    if status!="verified":
                        issue_rows.append((sid,"SC_FAS.csv",None,"warning",status,f"PO {k}: conflicting or missing ordered quantities"))
                cur.execute("""
                    SELECT company,sc_no,sc_pos,requested_qty,approved_qty
                    FROM planning.v_sc_coverage
                    WHERE snapshot_id=%s AND approved_qty>requested_qty
                """,(sid,))
                for comp,sc,pos,requested,approved in cur.fetchall():
                    issue_rows.append((
                        sid,"Recepciones_Sevilla.csv",None,"warning","APPROVED_EXCEEDS_REQUESTED",
                        f"SC {comp}/{sc}/{pos}: requested={requested}, approved={approved}"
                    ))
                copy_rows(cur,"audit.import_issues",["snapshot_id","source_name","line_number","severity","issue_code","details"],issue_rows)
                print("[4/4] Finalizing transaction...",flush=True)
                cur.execute("UPDATE audit.snapshots SET state='validated' WHERE id=%s",(sid,))
        print("Validated snapshot",sid,"date",args.date)
        print("Source counts:",counts)
        print("Quality issues:",len(issue_rows))
        print("NOT ACTIVE. Inspect audit.import_issues and coverage before --activate.")
    return sid

def activate(sid,allow_errors=False):
    connstr=os.environ.get("DATABASE_URL")
    if not connstr:
        raise SystemExit("Set DATABASE_URL")
    with psycopg.connect(connstr) as db:
        with db.transaction():
            with db.cursor() as cur:
                cur.execute("SELECT state,importer_revision FROM audit.snapshots WHERE id=%s FOR UPDATE",(sid,))
                row=cur.fetchone()
                if not row or row[0] not in ("validated","active"):
                    raise SystemExit("Snapshot must be validated")
                try:
                    ensure_current_importer(row[1])
                except ValueError as exc:
                    raise SystemExit(str(exc)) from exc
                cur.execute("SELECT count(*) FROM audit.import_issues WHERE snapshot_id=%s AND severity='error'",(sid,))
                errors=cur.fetchone()[0]
                if errors and not allow_errors:
                    raise SystemExit(f"{errors} import errors: inspect audit.import_issues. --allow-errors requires manual review")
                cur.execute("UPDATE audit.snapshots SET state='validated' WHERE state='active' AND id<>%s",(sid,))
                cur.execute("UPDATE audit.snapshots SET state='active',activated_at=now() WHERE id=%s",(sid,))
    print("Activated",sid)

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--date",help="Weekly snapshot date YYYY-MM-DD")
    ap.add_argument("--input",default="entrada")
    ap.add_argument("--activate",type=int,help="Explicitly activate an already validated snapshot")
    ap.add_argument("--allow-errors",action="store_true",help="Override after manual review")
    ap.add_argument("--no-progress",action="store_true",help="Disable progress bars")
    args=ap.parse_args()
    if args.activate is not None:
        activate(args.activate,args.allow_errors)
    elif args.date:
        run_import(args)
    else:
        ap.error("Provide --date or --activate")
