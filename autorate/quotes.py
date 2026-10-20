"""견적 저장과 조회 (기획서 6-3, 6-4, 4-5).

- 견적번호: Q-YYMM-NNN, 발행월 기준 일련번호 (월이 바뀌면 001부터, 확인 필요 항목의 기본값)
- 저장 시 마진%, 메모, 마진 수정 사유, 항목별 rate_id를 함께 남긴다.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

from autorate import places
from autorate.calculator import CarrierQuote, QuoteRequest


def next_quote_no(conn: sqlite3.Connection, issue_date: dt.date) -> str:
    prefix = f"Q-{issue_date:%y%m}-"
    rows = conn.execute("SELECT quote_no FROM quote WHERE quote_no LIKE ?", (prefix + "%",)).fetchall()
    seqs = [int(r[0][len(prefix):]) for r in rows if r[0][len(prefix):].isdigit()]
    return f"{prefix}{(max(seqs) if seqs else 0) + 1:03d}"


def save_quote(
    conn: sqlite3.Connection,
    req: QuoteRequest,
    q: CarrierQuote,
    customer: str,
    memo: str,
    margin_reason: str,
) -> str:
    """견적 헤더와 항목을 저장하고 견적번호를 돌려준다."""
    saved_at = dt.datetime.now().isoformat(timespec="seconds")
    with conn:
        quote_no = next_quote_no(conn, req.issue_date)
        conn.execute(
            "INSERT INTO quote (quote_no, issue_date, valid_until, customer_name, carrier, pol, pod, "
            "container, qty, margin_pct, total_sales, total_cost, profit, source_type, copied_from, "
            "price_mode, status, memo, margin_reason, saved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', NULL, NULL, 'issued', ?, ?, ?)",
            (
                quote_no, req.issue_date.isoformat(), q.valid_until.isoformat(), customer, q.carrier,
                places.display(req.pol), places.display(req.pod), req.container, req.qty,
                str(req.margin_pct), str(q.total_sales), str(q.total_cost), str(q.profit),
                memo or None, margin_reason or None, saved_at,
            ),
        )
        for n, line in enumerate(q.lines, start=1):
            conn.execute(
                "INSERT INTO quote_line (quote_no, line_no, charge, charge_type, unit, qty, unit_cost, "
                "unit_sales, amt_cost, amt_sales, profit, rate_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    quote_no, n, line.charge, line.charge_type, line.unit, line.qty,
                    str(line.unit_cost), str(line.unit_sales), str(line.amt_cost),
                    str(line.amt_sales), str(line.profit), line.rate_id,
                ),
            )
    return quote_no


def load_quote(conn: sqlite3.Connection, quote_no: str) -> dict | None:
    """PDF와 이력 화면에 쓰는 견적 한 건. 항목의 출처 pricing 정보도 함께 붙인다."""
    head = conn.execute("SELECT * FROM quote WHERE quote_no = ?", (quote_no,)).fetchone()
    if head is None:
        return None
    lines = [dict(r) for r in conn.execute(
        "SELECT * FROM quote_line WHERE quote_no = ? ORDER BY line_no", (quote_no,)
    )]
    sources = {}
    for line in lines:
        src = conn.execute(
            "SELECT source_file, valid_from, valid_to FROM pricing WHERE rate_id = ?", (line["rate_id"],)
        ).fetchone()
        if src is not None:
            sources[(src["source_file"], src["valid_from"], src["valid_to"])] = True
    quote = dict(head)
    quote["lines"] = lines
    quote["sources"] = [
        {"file": f, "valid_from": a, "valid_to": b} for (f, a, b) in sources
    ]
    return quote


def list_quotes(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM quote ORDER BY saved_at DESC, quote_no DESC")]
