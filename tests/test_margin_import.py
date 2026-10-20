import datetime as dt
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import openpyxl

from autorate.db import connect
from autorate.margin_import import (
    add_manual_margin,
    load_margins,
    normalize_name,
    parse_margin,
    save_margins,
)

ROOT = Path(__file__).resolve().parent.parent
REAL_MARGIN = ROOT / "02_customer_margin.xlsx"


def make_margin_xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["고객명", "마진(%)", "적용시작일", "비고"])
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_real_margin_file_has_four_customers(tmp_path):
    rows, errors = parse_margin(REAL_MARGIN)
    assert errors == []
    assert len(rows) == 4
    assert all(r.is_valid for r in rows)
    conn = connect(tmp_path / "t.db")
    save_margins(conn, rows)
    assert len(load_margins(conn)) == 4


def test_saving_same_margin_twice_does_not_duplicate(tmp_path):
    conn = connect(tmp_path / "t.db")
    rows, _ = parse_margin(REAL_MARGIN)
    save_margins(conn, rows)
    result = save_margins(conn, rows)
    assert result["inserted"] == 0 and result["updated"] == 4
    assert len(load_margins(conn)) == 4


def test_invalid_margin_value_is_row_error():
    rows, errors = parse_margin(make_margin_xlsx([["정우정밀", "여덟", dt.date(2026, 1, 1), None]]))
    assert errors == []
    assert not rows[0].is_valid


def test_manual_margin_is_saved_with_manual_source(tmp_path):
    conn = connect(tmp_path / "t.db")
    add_manual_margin(conn, "대원산업", Decimal("7"), dt.date(2026, 10, 20), "가상값")
    saved = load_margins(conn)
    assert saved[0]["customer_name"] == "대원산업"
    assert saved[0]["source"] == "manual"
    assert saved[0]["customer_id"].startswith("C")


def test_normalize_name_removes_spaces_and_company_marks():
    assert normalize_name("(주) 정우정밀") == "정우정밀"
    assert normalize_name("㈜정우 정밀") == "정우정밀"
