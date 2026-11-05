"""Conservative reconciliation: ambiguous source values are not invented."""
from collections import defaultdict
from .normalize import clean,decimal_es,date_es,indexed,is_real_po

def parse_sc(row):
    v=lambda i:indexed(row,i)
    return {
        "company":v(0),"sc_no":v(6),"sc_pos":v(7),"article":v(8),
        "description":v(9),"project":v(1),"centre":v(2),"director":v(3),
        "requested":decimal_es(v(11)),"required":date_es(v(13)),
        "po_no":v(16),"po_pos":v(17),"ordered":decimal_es(v(19)),
        "vendor":v(23),"planned":date_es(v(27)), "reac":v(14), "reac_article":v(15),
    }

def parse_receipt(row):
    v=lambda i:indexed(row,i)
    return {
        "po_no":v(0),"po_pos":v(1),"article":v(10),
        "receipt_no":v(19),"receipt_date":date_es(v(14)),
        "delivered":decimal_es(v(20)),"approved":decimal_es(v(21)),
        "status":v(26),
    }

def parse_incident(row):
    v=lambda i:indexed(row,i)
    return {"sequence":v(0),"record":v(1),"po_no":v(2),"po_pos":v(3),
            "article":v(5),"detail":v(12),"resolved":v(19),"category":v(20)}

def summarize_sc(records):
    """SC quantity is trustworthy only when all repeated values agree."""
    groups=defaultdict(list)
    for r in records:
        groups[(r["company"],r["sc_no"],r["sc_pos"])].append(r)
    for key,rows in groups.items():
        vals={r["requested"] for r in rows}
        qty=next(iter(vals)) if len(vals)==1 else None
        yield key,rows[0],qty,"verified" if len(vals)==1 and qty is not None else "ambiguous_requested_qty"

def summarize_po(records):
    groups=defaultdict(list)
    for r in records:
        if is_real_po(r["po_no"]):
            groups[(r["company"],r["po_no"],r["po_pos"])].append(r)
    for key,rows in groups.items():
        vals={r["ordered"] for r in rows}
        qty=next(iter(vals)) if len(vals)==1 else None
        yield key,rows[0],qty,"verified" if len(vals)==1 and qty is not None else "ambiguous_ordered_qty"
