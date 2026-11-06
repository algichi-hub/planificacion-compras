from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

import pytest

from scripts.audit_p3 import (classify_position,receipt_signature,analyse_rows,
                              inspect_universe,write_report)


def test_p3_coverage_complete_keeps_comment_empty():
    status,comment=classify_position(Decimal("42"),Decimal("84"),Decimal("42"),[])
    assert status=="COBERTURA_APROBADA_CONFORME"
    assert comment==""


@pytest.mark.parametrize("ordered,delivered,approved,status",[
    ("0","100","0","PEDIDO_CERO_CON_ENTREGA"),
    ("12","34","4","APROBACION_INCOMPLETA_CON_SOBREENTREGA"),
    ("11","18","9","APROBACION_INCOMPLETA_CON_SOBREENTREGA"),
    ("4","5","0","APROBACION_INCOMPLETA_CON_SOBREENTREGA"),
])
def test_p3_unresolved_has_comment(ordered,delivered,approved,status):
    actual,comment=classify_position(Decimal(ordered),Decimal(delivered),Decimal(approved),[])
    assert actual==status
    assert len(comment)>10


def test_p3_full_input_mismatch_is_not_silently_ignored():
    status,comment=classify_position(Decimal("10"),Decimal("10"),Decimal("10"),[],
                                     full_match=False)
    assert status=="FUENTE_INCONSISTENTE"
    assert comment


def test_p3_foreign_sc_owner_requires_comment():
    status,comment=classify_position(Decimal("5"),Decimal("8"),Decimal("5"),[],
                                     other_owners=True)
    assert status=="PEDIDO_COMPARTIDO"
    assert comment


def test_p3_full_input_matches_receipt_and_sc_scope():
    p=dict(po_no="761214",po_pos="3",company="210",sc_no="761000",sc_pos="10",
           article="A",ordered=Decimal("42"))
    r=dict(po_no="761214",po_pos="3",receipt_no="764133",article="A",
           receipt_date=date(2026,8,17),delivered=Decimal("42"),approved=Decimal("0"),
           status="Todo aprobado")
    r2=dict(r,receipt_no="768275",delivered=Decimal("42"),approved=Decimal("42"))
    key=("761214","3")
    owners={key:{("210","761000","10")}}
    full={key:Counter([receipt_signature(r),receipt_signature(r2)])}
    result=analyse_rows([p],[r,r2],owners,full,{})[0]
    assert result["comment"]==""
    assert result["delivered"]==Decimal("84")
    assert result["approved"]==Decimal("42")
    full[key][receipt_signature(r2)]+=1
    result=analyse_rows([p],[r,r2],owners,full,{})[0]
    assert result["status"]=="FUENTE_INCONSISTENTE"


def test_excel_csv_only_unresolved_and_format(tmp_path):
    base=dict(po_no="761214",po_pos="3",sc_no="765000",sc_pos="10",article="A",
              ordered=Decimal("42.50"),delivered=Decimal("84.50"),approved=Decimal("42.50"),
              receipt_count=2,incidents=0,status="COBERTURA_APROBADA_CONFORME",comment="")
    problem=dict(base,po_pos="4",status="PEDIDO_CERO_CON_ENTREGA",
                 ordered=Decimal("0"),comment="Verificar ERP")
    target=tmp_path/"report.csv"
    write_report(target,[base,problem])
    raw=target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    text=raw.decode("utf-8-sig")
    assert "761214;4;" in text
    assert "761214;3;" not in text
    assert "84,50" in text
    assert len(text.splitlines())==2
    with pytest.raises(FileExistsError):
        write_report(target,[problem])


def test_full_universe_reads_all_three_csv_files(tmp_path):
    sc=[""]*52;sc[0]="210";sc[6]="761000";sc[7]="10";sc[16]="761214";sc[17]="3"
    rec=[""]*28;rec[0]="761214";rec[1]="3";rec[10]="A";rec[14]="17/08/26"
    rec[19]="764133";rec[20]="42";rec[21]="0";rec[26]="Todo aprobado"
    inc=[""]*28;inc[0]="1";inc[1]="3";inc[2]="761214";inc[3]="3"
    import csv
    for file,sep,data in [("SC_FAS.csv","|",sc),
                          ("Recepciones_Sevilla.csv",";",rec),("INC_FAS.csv",";",inc)]:
        with (tmp_path/file).open("w",encoding="cp1252",newline="") as fh:
            writer=csv.writer(fh,delimiter=sep)
            writer.writerow([f"C{i}" for i in range(len(data))])
            writer.writerow(data)
    owners,context,full,incidents,scanned=inspect_universe(tmp_path,{("761214","3")})
    assert owners[("761214","3")]=={("210","761000","10")}
    assert sum(full[("761214","3")].values())==1
    assert incidents[("761214","3")]==1
    assert set(scanned)=={"SC_FAS.csv","Recepciones_Sevilla.csv","INC_FAS.csv"}

def test_transferred_real_zero_reconciles_against_nominal_from_full_csv():
    status,comment=classify_position(Decimal("0"),Decimal("100"),Decimal("0"),[],
                                     transfer_context=True)
    assert status=="TRANSFERIDA_NOMINAL_CONFORME"
    assert comment==""


def test_nominal_match_without_transferred_context_is_unresolved():
    status,comment=classify_position(Decimal("0"),Decimal("100"),Decimal("0"),[],
                                     transfer_context=False)
    assert status=="PEDIDO_CERO_CON_ENTREGA"
    assert comment


def test_context_must_match_exactly_not_merely_nominal():
    p=dict(po_no="760964",po_pos="1",company="210",sc_no="760544",sc_pos="40",
           article="A",ordered=Decimal("0"))
    r=dict(po_no="760964",po_pos="1",receipt_no="758793",article="A",
           receipt_date=date(2026,5,21),delivered=Decimal("100"),
           approved=Decimal("0"),status="Todo aprobado")
    key=("760964","1")
    owners={key:{("210","760544","40")}}
    signatures={key:Counter([receipt_signature(r)])}
    correct={key:{(Decimal("100"),Decimal("0"),"Transferida")}}
    result=analyse_rows([p],[r],owners,signatures,{},correct)[0]
    assert result["comment"]==""
    wrong={key:{(Decimal("100"),Decimal("0"),"Libre")}}
    result=analyse_rows([p],[r],owners,signatures,{},wrong)[0]
    assert result["status"]=="PEDIDO_CERO_CON_ENTREGA"
