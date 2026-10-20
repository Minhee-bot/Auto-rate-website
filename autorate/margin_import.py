"""고객 마진표 업로드와 직접 입력.

기획서 6-2(customer_margin), 7장 7·8번(미등록 고객, 고객명 표기 차이) 기준.
고객명 자동 매칭은 하지 않고, 비교용 정규화 값만 제공한다.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import BinaryIO

import openpyxl

HEADERS = {"customer_name": "고객명", "margin_pct": "마진(%)", "effective_from": "적용시작일", "remark": "비고"}


@dataclass
class MarginRow:
    row_no: int
    customer_name: str = ""
    margin_pct: Decimal | None = None
    effective_from: dt.date | None = None
    remark: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def normalize_name(name: str) -> str:
    """비교용 고객명: 공백, (주), ㈜ 제거 (기획서 7장 8번). 저장값은 바꾸지 않는다."""
    text = re.sub(r"\(주\)|㈜", "", name or "")
    return re.sub(r"\s+", "", text)


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _parse_decimal(value) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.replace(",", "").replace("%", "").strip())
        except InvalidOperation:
            return None
    return None


def _parse_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def parse_margin(source: BinaryIO | str) -> tuple[list[MarginRow], list[str]]:
    """마진표 첫 번째 시트를 읽는다. 반환: (행 목록, 파일 오류 목록)."""
    try:
        wb = openpyxl.load_workbook(source, data_only=True, read_only=True)
    except Exception as exc:
        return [], [f"엑셀 파일을 열 수 없습니다: {exc}"]

    all_rows = list(wb.worksheets[0].iter_rows(values_only=True))
    if not all_rows:
        return [], ["마진표가 비어 있습니다."]

    header = [_text(h) for h in all_rows[0]]
    missing = [h for h in HEADERS.values() if h not in header and h != "비고"]
    if missing:
        return [], [f"필수 컬럼이 없습니다: {', '.join(missing)}"]

    idx = {name: header.index(h) for name, h in HEADERS.items() if h in header}

    def cell(values, name):
        i = idx.get(name)
        return values[i] if i is not None and i < len(values) else None

    rows = []
    for row_no, values in enumerate(all_rows[1:], start=2):
        if all(v is None or _text(v) == "" for v in values):
            continue
        row = MarginRow(
            row_no=row_no,
            customer_name=_text(cell(values, "customer_name")),
            margin_pct=_parse_decimal(cell(values, "margin_pct")),
            effective_from=_parse_date(cell(values, "effective_from")),
            remark=_text(cell(values, "remark")),
        )
        if not row.customer_name:
            row.errors.append("고객명 비어 있음")
        if row.margin_pct is None:
            row.errors.append("마진(%) 숫자가 아님")
        if row.effective_from is None:
            row.errors.append("적용시작일 날짜 오류")
        rows.append(row)
    return rows, []


def save_margins(conn: sqlite3.Connection, rows: list[MarginRow]) -> dict:
    """정상 행을 저장한다. 같은 고객명+적용시작일이면 마진%와 비고를 갱신한다."""
    valid = [r for r in rows if r.is_valid]
    inserted = updated = 0
    with conn:
        for row in valid:
            if _upsert(conn, row.customer_name, row.margin_pct, row.effective_from, "upload", row.remark):
                inserted += 1
            else:
                updated += 1
    return {"inserted": inserted, "updated": updated, "skipped_invalid": len(rows) - len(valid)}


def add_manual_margin(
    conn: sqlite3.Connection,
    customer_name: str,
    margin_pct: Decimal,
    effective_from: dt.date,
    remark: str = "",
) -> None:
    """화면에서 직접 입력한 마진을 마진표에 저장한다 (source = manual)."""
    with conn:
        _upsert(conn, customer_name.strip(), margin_pct, effective_from, "manual", remark)


def _upsert(conn, name, pct, effective_from, source, remark) -> bool:
    """신규 추가면 True, 기존 행 갱신이면 False."""
    existing = conn.execute(
        "SELECT customer_id FROM customer_margin WHERE customer_name = ? AND effective_from = ?",
        (name, effective_from.isoformat()),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE customer_margin SET margin_pct = ?, source = ?, remark = ? WHERE customer_id = ?",
            (str(pct), source, remark or None, existing["customer_id"]),
        )
        return False

    next_no = conn.execute(
        "SELECT COUNT(*) + 1 FROM customer_margin"
    ).fetchone()[0]
    # 번호 충돌 방지: 이미 있으면 가장 큰 번호 다음으로
    while conn.execute(
        "SELECT 1 FROM customer_margin WHERE customer_id = ?", (f"C{next_no:03d}",)
    ).fetchone():
        next_no += 1
    conn.execute(
        "INSERT INTO customer_margin (customer_id, customer_name, margin_pct, effective_from, source, remark) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (f"C{next_no:03d}", name, str(pct), effective_from.isoformat(), source, remark or None),
    )
    return True


def find_margin(conn: sqlite3.Connection, customer_name: str, as_of: dt.date) -> Decimal | None:
    """견적일 기준 적용 마진%. 같은 고객의 견적일 이전 최신 행을 쓴다 (6-2). 없으면 None."""
    row = conn.execute(
        "SELECT margin_pct FROM customer_margin "
        "WHERE customer_name = ? AND effective_from <= ? "
        "ORDER BY effective_from DESC LIMIT 1",
        (customer_name, as_of.isoformat()),
    ).fetchone()
    return Decimal(row["margin_pct"]) if row else None


def load_margins(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM customer_margin ORDER BY customer_name, effective_from"
    ).fetchall()
    return [dict(r) for r in rows]
