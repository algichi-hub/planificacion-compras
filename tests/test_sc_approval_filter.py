from datetime import date
import pytest
from scripts import import_snapshot as importer

def rec(company,sc,approved):
    values=[""]*52
    values[0]=company
    values[6]=sc
    values[12]=approved
    return {f"k__{i}":v for i,v in enumerate(values)}

def test_from_approval_date_inclusive_and_whole_sc(monkeypatch):
    dataset=[
        (2,rec("210","1","19/01/25"),None),
        (3,rec("210","1","20/01/25"),None),
        (4,rec("210","2","19/01/25"),None),
        (5,rec("210","3","21/01/25"),None)]
    monkeypatch.setattr(importer,"iter_source",lambda *_:iter(dataset))
    selected,conflicts=importer.approved_sc_selection("unused",date(2025,1,20))
    assert selected=={("210","1"),("210","3")}
    assert ("210","1") in conflicts
    assert ("210","2") not in selected

def test_from_approval_date_rejects_missing_date(monkeypatch):
    monkeypatch.setattr(importer,"iter_source",lambda *_:iter([(2,rec("210","1",""),None)]))
    with pytest.raises(ValueError,match="missing FECHA APROBACIÓN"):
        importer.approved_sc_selection("unused",date(2025,1,20))

def test_from_approval_date_rejects_invalid_date(monkeypatch):
    monkeypatch.setattr(importer,"iter_source",lambda *_:iter([(2,rec("210","1","32/01/25"),None)]))
    with pytest.raises(ValueError,match="invalid FECHA APROBACIÓN"):
        importer.approved_sc_selection("unused",date(2025,1,20))

@pytest.mark.parametrize("value",["2025-01-20","2026-11-06"])
def test_cutoff_valid(value):
    assert importer.parse_cutoff(value).isoformat()==value

@pytest.mark.parametrize("value",["2025-02-30","20/01/2025","2025-1-20","bad"])
def test_cutoff_invalid(value):
    with pytest.raises(ValueError,match="--from"):
        importer.parse_cutoff(value)

def test_filter_scope_preserves_all_positions_for_selected_sc():
    chosen={("210","720001")}
    po={("800788","17"),("800788","18")}
    a=rec("210","720001","20/01/25")
    b=rec("210","720002","20/01/25")
    assert importer.in_approval_scope("SC_FAS.csv",a,chosen,po)
    assert not importer.in_approval_scope("SC_FAS.csv",b,chosen,po)
    receipt={f"k__{i}":v for i,v in enumerate(["800788","18"]+[""]*26)}
    assert importer.in_approval_scope("Recepciones_Sevilla.csv",receipt,chosen,po)
    receipt2={f"k__{i}":v for i,v in enumerate(["800789","18"]+[""]*26)}
    assert not importer.in_approval_scope("Recepciones_Sevilla.csv",receipt2,chosen,po)
    incident={f"k__{i}":v for i,v in enumerate(["","","800788","17"]+[""]*24)}
    assert importer.in_approval_scope("INC_FAS.csv",incident,chosen,po)
    incident2={f"k__{i}":v for i,v in enumerate(["","","800788","19"]+[""]*24)}
    assert not importer.in_approval_scope("INC_FAS.csv",incident2,chosen,po)

def test_no_cutoff_keeps_every_source():
    for src in importer.SOURCES:
        assert importer.in_approval_scope(src,{},None,set())
