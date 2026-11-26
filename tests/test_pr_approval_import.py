"""Regression tests: fourth PR file never replaces primary quantities."""
import csv
from datetime import date
from pathlib import Path

from src.pr_approval_import import HEADER, parse_totales, reconcile_totales


def _row(pr='769728',po='762087',pos='13',approval='09/11/26',received='05/11/26'):
    fields=['']*30
    fields[0],fields[1],fields[2]=pr,po,pos
    fields[14],fields[18]=received,approval
    fields[26],fields[27]='0','1'
    return fields


def _csv(tmp_path,rows):
    path=tmp_path/'RecepcionesTotales.csv'
    with path.open('w',encoding='cp1252',newline='') as fh:
        writer=csv.writer(fh,delimiter=';',quoting=csv.QUOTE_NONE)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


def test_real_schema_and_later_approval(tmp_path):
    rows=list(parse_totales(_csv(tmp_path,[_row()])))
    accepted,conflicts,stats,issues=reconcile_totales(
        rows,[('769728','762087','13',date(2026,11,5))],date(2026,11,8))
    assert accepted==[('769728','762087','13',date(2026,11,9),2)]
    assert not conflicts and stats['later_approval']==1
    assert not issues


def test_missing_date_does_not_change_approval(tmp_path):
    rows=list(parse_totales(_csv(tmp_path,[_row(approval='')])))
    accepted,conflicts,stats,_=reconcile_totales(
        rows,[('769728','762087','13',date(2026,11,5))],date(2026,11,8))
    assert not accepted and not conflicts and stats['missing_approval_date']==1


def test_wrong_po_is_untrusted(tmp_path):
    rows=list(parse_totales(_csv(tmp_path,[_row(po='123')])))
    a,c,_,_=reconcile_totales(
        rows,[('769728','762087','13',date(2026,11,5))],date(2026,11,8))
    assert not a and c==[('769728','PO_POSITION_MISMATCH')]


def test_approval_before_receipt(tmp_path):
    rows=list(parse_totales(_csv(tmp_path,[_row(approval='04/11/26')])))
    a,c,_,_=reconcile_totales(
        rows,[('769728','762087','13',date(2026,11,5))],date(2026,11,8))
    assert not a and c==[('769728','APPROVAL_BEFORE_RECEIPT')]


def test_date_mismatch_blocks_date(tmp_path):
    rows=list(parse_totales(_csv(tmp_path,[_row(received='04/11/26')])))
    a,c,_,_=reconcile_totales(
        rows,[('769728','762087','13',date(2026,11,5))],date(2026,11,8))
    assert not a and c==[('769728','RECEIPT_DATE_MISMATCH')]


def test_duplicate_pr_is_ambiguous(tmp_path):
    rows=list(parse_totales(_csv(tmp_path,[_row(),_row()])))
    a,c,_,_=reconcile_totales(
        rows,[('769728','762087','13',date(2026,11,5))],date(2026,11,8))
    assert not a and c==[('769728','AMBIGUOUS_PR')]


def test_partial_receipts_same_po_position(tmp_path):
    rows=list(parse_totales(_csv(tmp_path,[
        _row(pr='1',approval='06/11/26'),
        _row(pr='2',approval='07/11/26',received='06/11/26')
    ])))
    a,c,_,_=reconcile_totales(rows,[
        ('1','762087','13',date(2026,11,5)),
        ('2','762087','13',date(2026,11,6))],date(2026,11,8))
    assert len(a)==2 and not c


def test_out_of_scope_pr_is_not_attached(tmp_path):
    rows=list(parse_totales(_csv(tmp_path,[_row()])))
    a,c,stats,_=reconcile_totales(rows,[],date(2026,11,8))
    assert not a and not c and stats['source_outside_scope']==1


def test_reject_unexpected_header(tmp_path):
    path=tmp_path/'RecepcionesTotales.csv'
    path.write_text('wrong;header\n',encoding='cp1252')
    import pytest
    with pytest.raises(ValueError,match='columns'):
        list(parse_totales(path))


def test_localized_date_uses_day_month(tmp_path):
    rows=list(parse_totales(_csv(tmp_path,[_row(approval='12/11/2026')])))
    assert rows[0][1][3]==date(2026,11,12)
