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
