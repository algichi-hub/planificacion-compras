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

def iter_source(path, delimiter, encoding="cp1252"):
    """Yield (physical_line, fields, error). Never silently discard a malformed row."""
    with Path(path).open("r",encoding=encoding,newline="") as fh:
        reader=csv.reader(fh,delimiter=delimiter)
        header=next(reader)
        header=[clean(x) for x in header]
        if header and not header[-1]:
            header=header[:-1]
        for rec in reader:
            if rec and not rec[-1] and len(rec)==len(header)+1:
                rec=rec[:-1]
            if len(rec)!=len(header):
                yield reader.line_num,None,f"expected {len(header)} fields, got {len(rec)}"
            else:
                yield reader.line_num,dict(zip([f"{h}__{i}" for i,h in enumerate(header)],rec)),None

def indexed(row,i):
    return clean(list(row.values())[i])

def article(value):
    return clean(value)

def is_real_po(value):
    v=clean(value)
    return bool(v and v not in ("0","000000"))
