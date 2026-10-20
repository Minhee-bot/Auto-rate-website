import datetime as dt
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest

from autorate.db import connect
from autorate.pricing_import import build_plan, parse_pricing, save_plan, status_of

ROOT = Path(__file__).resolve().parent.parent
REAL_PRICING = ROOT / "01_pricing_2026-10.xlsx"
AS_OF = dt.date(2026, 10, 20)
HEADER = ["선사", "POL", "POD", "컨테이너", "항목", "구분", "단위", "통화", "Cost", "유효시작", "유효종료", "비고"]


def make_xlsx(rows, header=HEADER, sheet="pricing"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def line(charge="Ocean Freight", cost=3450, start=(10, 1), end=(10, 31), cntr="40HC",
         carrier="코리아라인(KRL)", currency="USD", ctype="Freight", unit="Per Container", pod="Los Angeles"):
    return [carrier, "부산", pod, cntr, charge, ctype, unit, currency, cost,
            dt.date(2026, *start), dt.date(2026, *end), None]


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "t.db")


def test_real_file_has_35_rows_and_no_errors():
    result = parse_pricing(REAL_PRICING)
    assert result.file_errors == []
    assert len(result.rows) == 35
    assert all(r.is_valid for r in result.rows)


def test_real_file_marks_ten_september_rows_expired():
    result = parse_pricing(REAL_PRICING)
    statuses = [status_of(r, AS_OF) for r in result.rows]
    assert statuses.count("만료") == 10
    assert statuses.count("정상") == 25


def test_missing_required_column_is_file_error():
    header = [h for h in HEADER if h != "Cost"]
    result = parse_pricing(make_xlsx([], header=header))
    assert result.rows == []
    assert any("Cost" in e for e in result.file_errors)


def test_missing_pricing_sheet_is_file_error():
    result = parse_pricing(make_xlsx([line()], sheet="Sheet1"))
    assert any("pricing" in e for e in result.file_errors)


def test_non_usd_row_is_error():
    result = parse_pricing(make_xlsx([line(currency="KRW")]))
    assert not result.rows[0].is_valid
    assert any("USD" in e for e in result.rows[0].errors)


def test_non_numeric_cost_is_error():
    result = parse_pricing(make_xlsx([line(cost="abc")]))
    assert any("Cost" in e for e in result.rows[0].errors)


def test_end_before_start_is_error():
    result = parse_pricing(make_xlsx([line(start=(10, 31), end=(10, 1))]))
    assert any("유효종료" in e for e in result.rows[0].errors)


def test_charge_type_mismatch_is_error():
    result = parse_pricing(make_xlsx([line(charge="THC", ctype="Freight", unit="Per Container")]))
    assert any("구분" in e for e in result.rows[0].errors)


def test_overlapping_periods_in_file_flag_both_rows():
    rows = [line(start=(10, 1), end=(10, 31)), line(start=(10, 15), end=(11, 15))]
    result = parse_pricing(make_xlsx(rows))
    assert all(not r.is_valid for r in result.rows)


def test_save_then_reupload_same_file_changes_nothing(conn):
    parsed = parse_pricing(REAL_PRICING)
    plan = build_plan(parsed, conn)
    assert len(plan.new_rows) == 35
    save_plan(conn, plan, "01_pricing_2026-10.xlsx", "2026-10-20T09:00:00")

    again = build_plan(parse_pricing(REAL_PRICING), conn)
    assert again.new_rows == [] and again.changed == []
    assert len(again.unchanged) == 35


def test_cost_change_is_detected_and_updated(conn):
    save_plan(conn, build_plan(parse_pricing(REAL_PRICING), conn), "a.xlsx", "t")

    changed_file = make_xlsx([line(cost=3500)])  # 같은 키(KRL, 40HC, OF, 10/1 시작)
    plan = build_plan(parse_pricing(changed_file), conn)
    assert len(plan.changed) == 1
    assert str(plan.changed[0][1]["cost"]) == "3450"

    save_plan(conn, plan, "b.xlsx", "t2")
    cost = conn.execute(
        "SELECT cost FROM pricing WHERE charge = 'Ocean Freight' AND container = '40HC' "
        "AND valid_from = '2026-10-01'"
    ).fetchone()[0]
    assert cost == "3500"


def test_overlap_with_stored_rate_is_blocked(conn):
    save_plan(conn, build_plan(parse_pricing(REAL_PRICING), conn), "a.xlsx", "t")
    # 저장된 10/1~10/31 OF와 다른 시작일로 겹치는 행
    overlapping = make_xlsx([line(start=(10, 15), end=(11, 15))])
    plan = build_plan(parse_pricing(overlapping), conn)
    assert len(plan.invalid_rows) == 1
    assert any("기간이 겹쳐요" in e for e in plan.invalid_rows[0].errors)


def test_save_with_invalid_rows_requires_skip_flag(conn):
    plan = build_plan(parse_pricing(make_xlsx([line(), line(currency="KRW", cntr="20GP")])), conn)
    with pytest.raises(ValueError):
        save_plan(conn, plan, "x.xlsx", "t")

    result = save_plan(conn, plan, "x.xlsx", "t", skip_invalid=True)
    assert result["inserted"] == 1
    assert result["skipped_invalid"] == 1
    assert conn.execute("SELECT COUNT(*) FROM pricing").fetchone()[0] == 1


def test_file_error_blocks_save(conn):
    plan = build_plan(parse_pricing(make_xlsx([], header=["선사"])), conn)
    with pytest.raises(ValueError):
        save_plan(conn, plan, "x.xlsx", "t", skip_invalid=True)
