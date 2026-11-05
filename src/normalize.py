"""Input normalization: identifiers remain strings and numbers remain Decimal."""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

SC_HEADERS = ["COMPAÑÍA","PROYECTO","CENTRO","DIRPROY","ESTADO SC","ESTADO COMPRAS","SOLICITUD","POSICIÓN","ARTÍCULO","DESCRIPCIÓN","SOLICITADA INICIAL","SOLICITADA REAL","FECHA APROBACIÓN","FECHA ENTREGA SOLICITUD","REAC","ARTÍCULO REAC","PEDIDO","POSICIÓN","CANTIDAD PEDIDO","PEDIDA REAL","PRECIO €","IMPORTE","MONEDA","PROVEEDOR","NOMBRE","FECHA RECEPCIÓN","FECHA PLANIFICADA","FECHA PLANIFICADA ACTUAL","CANTIDAD APROBADA","IMP APROBADO","PARTE RECEPCIÓN","REVISIÓN SOLICITUD COMPRAS","REVISIÓN ORDEN COMPRAS","REVISIÓN ACTUAL","VEHÍCULO","PDG136","ARTÍCULO HOMOLOGADO POR PROVEEDOR","PROYECTO NO ENTREGABLE","REQUISITOS ADICIONALES","INSPECCIÓN SSL","INSPECCIÓN","FECHA APROBACIÓN DEL PEDIDO","CANTIDAD RETRO-ORDEN","CANTIDAD RECIBIDA","IMP RECIBIDO","COMPRADOR","CONTRATO GDSBS","QR","Nº FACTURA","IMPORTE FACTURADO","GdM","CÓDIGO REFERENCIA"]

def clean(value):
    return (value or "").strip()

def decimal_es(value):
    v = clean(value).replace(" ","").replace("\u00a0","")
    if not v:
        return None
    try:
        return Decimal(v.replace(".","").replace(",","."))
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal: {value!r}") from exc

def date_es(value):
    v = clean(value)
    if not v:
        return None
    for fmt in ("%d/%m/%y","%d/%m/%Y"):
        try:
            return datetime.strptime(v,fmt).date()
        except ValueError:
            pass
    raise ValueError(f"invalid date: {v!r}")

def repair_extra_fields(fields, expected, separator, source_name):
    """Attempt a bounded recovery of delimiters in a known free-text field.

    Returns None when fixed-position numeric/date/status anchors are inconsistent.
    INC_FAS notes repair is heuristic and must be reported in the audit log.
    """
    if len(fields) <= expected:
        return None
    description_index={"SC_FAS.csv":9,"INC_FAS.csv":27,
                       "Recepciones_Sevilla.csv":27}.get(source_name)
    if description_index is None:
        return None
    surplus=len(fields)-expected
    candidate=(fields[:description_index]
               +[separator.join(fields[description_index:description_index+surplus+1])]
               +fields[description_index+surplus+1:])
    if len(candidate)!=expected:
        return None
    try:
        if source_name=="SC_FAS.csv":
            decimal_es(candidate[11])
            date_es(candidate[12])
        elif source_name=="Recepciones_Sevilla.csv":
            decimal_es(candidate[20])
            decimal_es(candidate[21])
            if clean(candidate[26]) not in ("Todo aprobado","Libre","Conciliado"):
                return None
        elif source_name=="INC_FAS.csv":
            if clean(candidate[19]).lower() not in ("sí","si","no",""):
                return None
            date_es(candidate[11])
    except ValueError:
        return None
    return candidate

def iter_source(path, delimiter, encoding="cp1252"):
    """Yield (physical_line, fields, error), preserving documented repairs."""
    source_name=Path(path).name
    with Path(path).open("r",encoding=encoding,errors="replace",newline="") as fh:
        reader=csv.reader(fh,delimiter=delimiter)
        header=next(reader)
        header=[clean(x) for x in header]
        if header and not header[-1]:
            header=header[:-1]
        for rec in reader:
            if rec and not rec[-1] and len(rec)==len(header)+1:
                rec=rec[:-1]
            repair_note=None
            if len(rec)>len(header):
                original_count=len(rec)
                candidate=repair_extra_fields(rec,len(header),delimiter,source_name)
                if candidate is not None:
                    rec=candidate
                    repair_note=f"heuristic text-field repair: {original_count} to {len(header)} fields"
            if len(rec)!=len(header):
                yield reader.line_num,None,f"expected {len(header)} fields, got {len(rec)}"
            else:
                fields=dict(zip([f"{h}__{i}" for i,h in enumerate(header)],rec))
                if repair_note:
                    fields["__repair_info__"]=repair_note
                yield reader.line_num,fields,None

def indexed(row,i):
    return clean(list(row.values())[i])

def article(value):
    return clean(value)

def is_real_po(value):
    v=clean(value)
    return bool(v and v not in ("0","000000"))
