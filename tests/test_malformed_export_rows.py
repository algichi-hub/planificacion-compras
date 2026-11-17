"""Regression tests for the four verified malformed ERP export rows.

Synthetic examples mirror their column displacement; no ERP data in Git.
"""
import csv

import pytest

from src.normalize import repair_known_export_anomalies,repair_extra_fields,iter_source
from src.reconcile import parse_sc,parse_incident


@pytest.mark.parametrize("sc_no,quantity",[
    ("750551","5,0000"),("750683","15,0000"),("750708","20,0000")
])
def test_extra_blank_column_before_qr(sc_no,quantity):
    fields=[""]*52
    fields[0]="210"
    fields[6]=sc_no
    fields[7]="10"
    fields[8]="ARTICLE"
    fields[11]=quantity
    fields[12]="24/03/25"
    fields[13]="18/04/25"
    fields[16]="802244"
    fields[17]="1"
    fields[19]=quantity
    fields[47]="00.000.100.00"
    fields[48]="22505300"
    fields[49]="1050,0000"
    fields[50]=""
    fields[51]="0"
    malformed=fields[:47]+[""]+fields[47:]
    repaired=repair_known_export_anomalies(malformed,52,"SC_FAS.csv")
    assert repaired==fields
    parsed=parse_sc({str(i):v for i,v in enumerate(repaired)})
    assert parsed["sc_no"]==sc_no
    assert repaired[47]=="00.000.100.00"
    assert repaired[48]=="22505300"


def test_incident_multiple_unquoted_text_delimiters_and_trailing_blanks():
    fields=[""]*28
    fields[0]="4428"
    fields[1]="209522"
    fields[2]="730301"
    fields[3]="1"
    fields[5]="9999990020"
    fields[11]="20/03/23"
    fields[12]="VARIOS; LEER NOTA TEXT"
    fields[13]="15000"
    fields[14]="15000"
    fields[17]="13/07/26"
    fields[18]="user"
    fields[19]="Sí"
    fields[20]="Falta Documentación"
    fields[27]="Nota A;Nota B;Nota C;Nota D"
    malformed=fields[:12]+["VARIOS"," LEER NOTA TEXT"]+fields[13:27]+[
        "Nota A","Nota B","Nota C","Nota D","",""
    ]
    assert len(malformed)==34
    repaired=repair_known_export_anomalies(malformed,28,"INC_FAS.csv")
    assert repaired==fields
    parsed=parse_incident({str(i):v for i,v in enumerate(repaired)})
    assert parsed["po_no"]=="730301"
    assert parsed["resolved"]=="Sí"
    assert parsed["category"]=="Falta Documentación"


def test_refuse_unsafe_sc_repair_if_extra_field_is_not_blank():
    fields=[""]*53
    fields[47]="NONEMPTY"
    fields[48]="00.000.100.00"
    fields[52]="0"
    assert repair_known_export_anomalies(fields,52,"SC_FAS.csv") is None


def test_refuse_incident_repair_if_last_fields_are_not_empty():
    fields=[""]*34
    fields[-1]="important"
    assert repair_known_export_anomalies(fields,28,"INC_FAS.csv") is None


def test_refuse_incident_repair_if_resolved_status_shifted_unknown():
    fields=[""]*34
    fields[2]="730301"
    fields[3]="1"
    fields[5]="ARTICLE"
    fields[11]="20/03/23"
    fields[14]="15000"
    fields[15]="15000"
    fields[18]="13/07/26"
    fields[20]="UNKNOWN"
    assert repair_known_export_anomalies(fields,28,"INC_FAS.csv") is None


def test_iter_source_reports_repair_and_preserves_field_indexes(tmp_path):
    path=tmp_path/"SC_FAS.csv"
    header=[f"C{i}" for i in range(52)]
    fields=[""]*52
    fields[0]="210";fields[6]="750551";fields[7]="10"
    fields[11]="5,0000";fields[12]="24/03/25";fields[13]="18/04/25"
    fields[19]="5,0000";fields[47]="00.000.100.00"
    fields[48]="22505300";fields[49]="1050,0000";fields[51]="0"
    with path.open("w",encoding="cp1252",newline="") as stream:
        writer=csv.writer(stream,delimiter="|")
        writer.writerow(header)
        writer.writerow(fields[:47]+[""]+fields[47:])
    rows=list(iter_source(path,"|"))
    assert len(rows)==1
    _,record,error=rows[0]
    assert error is None
    assert record["C47__47"]=="00.000.100.00"
    assert "__repair_info__" in record


def test_existing_description_field_delimiter_repair_regression():
    fields=[""]*53
    fields[9]="LLAVE DE VASO"
    fields[10]=" RESTO"
    fields[12]="10,0000"
    fields[13]="23/02/24"
    assert repair_known_export_anomalies(fields,52,"SC_FAS.csv") is None
    result=repair_extra_fields(fields,52,"|","SC_FAS.csv")
    assert result is not None
    assert result[9]=="LLAVE DE VASO| RESTO"



def test_sc_literal_unbalanced_quotes_do_not_consume_next_line(tmp_path):
    """Regression for concurrent SC_FAS quote-handling change c7493be0."""
    path=tmp_path/"SC_FAS.csv"
    path.write_text(
        "COMPANIA|DESCRIPCION|POSICION\n"
        '210|"literal sin cierre|10\n'
        "210|Segunda linea normal|20\n",
        encoding="cp1252",
    )
    rows=list(iter_source(path,"|"))
    assert len(rows)==2
    assert [ln for ln,_,_ in rows]==[2,3]
    assert all(error is None for _,_,error in rows)
    assert rows[0][1]["DESCRIPCION__1"]=='"literal sin cierre'
    assert rows[1][1]["POSICION__2"]=="20"


def test_non_sc_csv_retains_standard_quoted_field_parsing(tmp_path):
    """INC source quotes must still protect the semicolon in text fields."""
    path=tmp_path/"INC_FAS.csv"
    path.write_text(
        "A;B;C\n"
        'x;"dos;terminos";y\n',
        encoding="cp1252",
    )
    rows=list(iter_source(path,";"))
    assert len(rows)==1
    assert rows[0][2] is None
    assert rows[0][1]["B__1"]=="dos;terminos"
