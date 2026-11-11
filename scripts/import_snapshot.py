"""Manual weekly CSV import with atomic operational SC classification."""
import argparse
import hashlib
import os
import sys
import time
from datetime import date
from collections import defaultdict
from pathlib import Path

import psycopg
from tqdm import tqdm

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.normalize import iter_source,decimal_es,date_es,is_real_po,indexed
from src.reconcile import parse_sc,parse_receipt,parse_incident,summarize_sc,summarize_po
from scripts.build_sc_workflow import classify
from src.pr_approval_import import import_approval_dates
from scripts.prepare_input_zip import prepare_inputs, InputArchiveError
from src.import_history import log_event

SOURCES={"SC_FAS.csv":"|","INC_FAS.csv":";","Recepciones_Sevilla.csv":";"}
IMPORTER_REVISION="p2_receipt_decimal_dot_v1"

def ensure_current_importer(revision):
    if revision != IMPORTER_REVISION:
        raise ValueError("Snapshot uses an outdated importer revision; reimport original CSV files")

def count_data_lines(path):
    """Count physical lines, excluding the header, for progress display."""
    with open(path, "rb") as fh:
        number=sum(block.count(b"\n") for block in iter(lambda: fh.read(1024*1024), b""))
    with open(path, "rb") as fh:
        fh.seek(0,2)
        if fh.tell():
            fh.seek(-1,2)
            if fh.read(1)!=b"\n":
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

def parse_cutoff(value):
    if value is None:
        return None
    try:
        parsed=date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("--from must be a valid YYYY-MM-DD date") from exc
    if parsed.isoformat()!=value:
        raise ValueError("--from must use YYYY-MM-DD")
    return parsed

def approved_sc_selection(path, cutoff):
    """Select whole (company,SC) groups by any approval date >= cutoff.

    A date conflict never causes partial SC import: retain whole SC and
    report it. Malformed or missing approval dates fail closed.
    """
    dates=defaultdict(set)
    for ln,record,error in iter_source(path,SOURCES["SC_FAS.csv"]):
        if error:
            continue  # remains reported during the regular CSV pass
        key=(indexed(record,0),indexed(record,6))
        if not all(key):
            raise ValueError(f"SC line {ln}: missing company or SC number")
        raw=indexed(record,12)
        try:
            approved=date_es(raw)
        except ValueError as exc:
            raise ValueError(f"SC line {ln}: invalid FECHA APROBACIÓN: {raw!r}") from exc
        if approved is None:
            raise ValueError(f"SC line {ln}: missing FECHA APROBACIÓN; cannot filter safely")
        dates[key].add(approved)
    selected={key for key,values in dates.items() if max(values)>=cutoff}
    conflicts={key:values for key,values in dates.items() if len(values)>1 and key in selected}
    return selected,conflicts

def in_approval_scope(source, record, selected_sc_keys, selected_po_keys):
    """Keep whole selected SC and only matching PO-position dependent rows."""
    if selected_sc_keys is None:
        return True
    if source=="SC_FAS.csv":
        return (indexed(record,0),indexed(record,6)) in selected_sc_keys
    if source=="Recepciones_Sevilla.csv":
        return (indexed(record,0),indexed(record,1)) in selected_po_keys
    if source=="INC_FAS.csv":
        return (indexed(record,2),indexed(record,3)) in selected_po_keys
    raise ValueError(f"Unknown import source: {source}")

def finalize_import(db, cur, snapshot_id):
    """Publish a validated snapshot only with a complete derived SC classification.

    Called inside run_import's transaction: failures roll back source and derived rows.
    """
    cur.execute("SELECT count(*) FROM core.sc_lines WHERE snapshot_id=%s", (snapshot_id,))
    expected=cur.fetchone()[0]
    if expected <= 0:
        raise ValueError("Cannot validate a snapshot without SC positions")
    cur.execute("UPDATE audit.snapshots SET state='validated' WHERE id=%s", (snapshot_id,))
    counts=classify(db, snapshot_id, commit=True)
    if sum(counts.values()) != expected:
        raise ValueError("SC classification cardinality mismatch")
    return expected


def run_import(args):
    root=Path(args.input)
    # Preflight is independent from Neon; abort before any snapshot write if
    # the encrypted ZIP is missing, incomplete or has the wrong password.
    try:
        changed=prepare_inputs(root)
    except InputArchiveError as exc:
        raise SystemExit(f"Input ZIP preflight failed: {exc}") from exc
    log_event(root, "SNAPSHOT_START", snapshot_date=args.date, zip_updated=changed)
    print("ZIP input: " + ("four CSVs updated" if changed else "unchanged; verified CSVs reused"),
          flush=True)
    for name in SOURCES:
        if not (root/name).is_file():
            raise SystemExit(f"Required input missing: {root/name}")
    print("[1/5] Calculating file hashes...",flush=True)
    hashes={name:sha256(root/name) for name in SOURCES}
    extra_path=root/"RecepcionesTotales.csv"
    if extra_path.is_file():
        hashes["RecepcionesTotales.csv"]=sha256(extra_path)
    cutoff=parse_cutoff(getattr(args,"from_date",None))
    selected_sc_keys,conflicts=(approved_sc_selection(root/"SC_FAS.csv",cutoff)
                               if cutoff is not None else (None,{}))
    if cutoff is not None:
        print(f"SC approval filter >= {cutoff}: {len(selected_sc_keys):,} SC selected; "
              f"{len(conflicts)} selected SC have conflicting approval dates",flush=True)
    sc_records=[]
    issue_rows=[]
    counts={}
    if cutoff is not None:
        for key,values in sorted(conflicts.items()):
            issue_rows.append((None,"SC_FAS.csv",None,"warning","SC_APPROVAL_DATE_CONFLICT",
                              f"SC {key}: approval dates {','.join(str(v) for v in sorted(values))}; selected as whole SC"))
    connstr=os.environ.get("DATABASE_URL")
    if not connstr:
        raise SystemExit("Set DATABASE_URL outside the repository")
    with psycopg.connect(connstr) as db:
        with db.transaction():
            with db.cursor() as cur:
                cur.execute("INSERT INTO audit.snapshots(snapshot_date,source_hashes,importer_revision,sc_approved_from) VALUES (%s,%s::jsonb,%s,%s) RETURNING id",
                            (args.date,__import__("json").dumps(hashes),IMPORTER_REVISION,cutoff))
                sid=cur.fetchone()[0]
                issue_rows=[(sid,*row[1:]) for row in issue_rows]
                selected_po_keys=set()
                print("[2/5] Uploading CSV data...",flush=True)
                for source,separator in SOURCES.items():
                    total=valid=bad=filtered=0
                    pbar=tqdm(total=count_data_lines(root/source),desc=source[:22],unit="line",
                              disable=getattr(args,"no_progress",False),dynamic_ncols=True,mininterval=0.2)
                    path=root/source
                    def rows():
                        nonlocal total,valid,bad,filtered
                        last_line=1
                        for ln,record,error in iter_source(path,separator):
                            pbar.update(max(0,ln-last_line))
                            last_line=ln
                            total+=1
                            if error:
                                bad+=1
                                issue_rows.append((sid,source,ln,"error","MALFORMED_ROW",error))
                                continue
                            if not in_approval_scope(source,record,selected_sc_keys,selected_po_keys):
                                filtered+=1
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
                                    if is_real_po(parsed["po_no"]):
                                        selected_po_keys.add((parsed["po_no"],parsed["po_pos"]))
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
                    tqdm.write(f"  {source}: {valid:,} selected; {filtered:,} excluded; {bad:,} malformed")
                    counts[source]={"total":total,"ok":valid,"filtered":filtered,"invalid":bad}
                    cur.execute("INSERT INTO audit.source_files(snapshot_id,source_name,sha256,rows_total,rows_ok,rows_invalid) VALUES (%s,%s,%s,%s,%s,%s)",(sid,source,hashes[source],total,valid,bad))
                print("[3/5] Conciliating SC / PO and building database tables...",flush=True)
                with tqdm(total=8,desc="SC/PO reconciliation (approx.)",unit="step",
                          disable=getattr(args,"no_progress",False),dynamic_ncols=True,leave=True) as progress:
                    progress.set_postfix_str("Grouping SC",refresh=True)
                    sc_keys=list(summarize_sc(sc_records))
                    progress.update(1)
                    progress.set_postfix_str("Writing SC to Neon",refresh=True)
                    copy_rows(cur,"core.sc_lines",["snapshot_id","company","sc_no","sc_pos","article","description","project","centre","project_director","requested_qty","qty_status","required_date"],
                        ((sid,k[0],k[1],k[2],sample["article"],sample["description"],sample["project"],sample["centre"],sample["director"],qty,status,sample["required"]) for k,sample,qty,status in sc_keys))
                    progress.update(1)
                    progress.set_postfix_str("Grouping PO",refresh=True)
                    po_keys=list(summarize_po(sc_records))
                    progress.update(1)
                    progress.set_postfix_str("Writing PO to Neon",refresh=True)
                    copy_rows(cur,"core.po_lines",["snapshot_id","company","po_no","po_pos","article","vendor","ordered_qty","planned_date","vendor_name","vendor_name_count"],
                        ((sid,k[0],k[1],k[2],sample["article"],sample["vendor"],qty,sample["planned"],
                          sample["vendor_name"],sample["vendor_name_count"]) for k,sample,qty,status in po_keys))
                    progress.update(1)
                    progress.set_postfix_str("Building SC/PO links",refresh=True)
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
                    progress.update(1)
                    progress.set_postfix_str("Writing REAC references",refresh=True)
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
                    progress.update(1)
                    progress.set_postfix_str("Checking data quality",refresh=True)
                    for k,sample,qty,status in sc_keys:
                        if status not in ("verified","verified_allocated_sum"):
                            issue_rows.append((sid,"SC_FAS.csv",None,"warning",status,f"SC {k}: conflicting or missing requested quantities"))
                    for k,sample,qty,status in po_keys:
                        if status!="verified":
                            issue_rows.append((sid,"SC_FAS.csv",None,"warning",status,f"PO {k}: conflicting or missing ordered quantities"))
                    progress.update(1)
                    progress.set_postfix_str("Saving import quality issues",refresh=True)
                    copy_rows(cur,"audit.import_issues",["snapshot_id","source_name","line_number","severity","issue_code","details"],issue_rows)
                    progress.update(1)
                    progress.set_postfix_str("Reconciliation complete",refresh=True)
                print("[4/5] Calculating SC workflow classification...",flush=True)
                classified_count=finalize_import(db,cur,sid)
                print(f"Classified {classified_count:,} SC positions.",flush=True)
                if extra_path.is_file():
                    print("Conciliating PR approval dates (fourth source)...",flush=True)
                    approval_counts=import_approval_dates(
                        cur,sid,extra_path,date.fromisoformat(args.date),
                        hashes["RecepcionesTotales.csv"])
                    print("Fourth-source PR reconciliation:",dict(approval_counts),flush=True)
                print("[5/5] Finalizing transaction...",flush=True)
        log_event(root, "SNAPSHOT_VALIDATED", snapshot_id=sid, snapshot_date=args.date,
                  source_count=len(hashes), positions=classified_count,
                  quality_issues=len(issue_rows))
        print("Validated snapshot",sid,"date",args.date)
        print("Source counts:",counts)
        print("Quality issues:",len(issue_rows))
        print("Snapshot validated with SC workflow computed. Latest validated snapshot is shown by default; inspect audit.import_issues before trusting results.")
    return sid

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--date",help="Weekly snapshot date YYYY-MM-DD")
    ap.add_argument("--input",default="entrada")
    ap.add_argument("--from",dest="from_date",metavar="YYYY-MM-DD",help="Include SC approved on or after date; keep all related PO/receipts/incidents")
    ap.add_argument("--no-progress",action="store_true",help="Disable progress bars")
    args=ap.parse_args()
    if args.date:
        try:
            run_import(args)
        except BaseException as exc:
            # Log a safe exception class, never a connection URL or secret.
            # SystemExit from ZIP preflight already has its specific ZIP log.
            if not isinstance(exc, KeyboardInterrupt):
                log_event(args.input, "SNAPSHOT_FAILED",
                          snapshot_date=args.date, error_type=type(exc).__name__)
            raise
    else:
        ap.error("Provide --date")
