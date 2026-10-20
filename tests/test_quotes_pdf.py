import datetime as dt
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from autorate import pdf_quote, quotes
from autorate.calculator import QuoteRequest, quote_carriers
from autorate.db import connect
from autorate.margin_import import parse_margin, save_margins
from autorate.pricing_import import build_plan, parse_pricing, save_plan

ROOT = Path(__file__).resolve().parent.parent
REAL_PRICING = ROOT / "01_pricing_2026-10.xlsx"
REAL_MARGIN = ROOT / "02_customer_margin.xlsx"
ISSUE = dt.date(2026, 10, 20)


@pytest.fixture
def loaded(tmp_path):
    conn = connect(tmp_path / "t.db")
    save_plan(conn, build_plan(parse_pricing(REAL_PRICING), conn), "01_pricing_2026-10.xlsx", "t")
    rows, _ = parse_margin(REAL_MARGIN)
    save_margins(conn, rows)
    return conn


def jungwoo_quote(conn, issue=ISSUE):
    req = QuoteRequest("Busan", "Los Angeles", "40HC", 2, issue, Decimal(8))
    q = quote_carriers(conn, req)[0]
    return req, q


def pdf_text(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ── 견적번호 (4-5) ────────────────────────────────────
def test_quote_numbers_increase_within_month(loaded):
    req, q = jungwoo_quote(loaded)
    first = quotes.save_quote(loaded, req, q, "정우정밀", "", "")
    second = quotes.save_quote(loaded, req, q, "정우정밀", "", "")
    assert first == "Q-2610-001"
    assert second == "Q-2610-002"


def test_quote_number_restarts_next_month(loaded):
    req, q = jungwoo_quote(loaded)
    quotes.save_quote(loaded, req, q, "정우정밀", "", "")
    # 10월 번호가 있어도 11월은 001부터 (확인 필요 항목의 기본값)
    assert quotes.next_quote_no(loaded, dt.date(2026, 11, 2)) == "Q-2611-001"


def test_saved_quote_keeps_lines_and_source(loaded):
    req, q = jungwoo_quote(loaded)
    no = quotes.save_quote(loaded, req, q, "정우정밀", "메모 테스트", "")
    saved = quotes.load_quote(loaded, no)
    assert saved["total_sales"] == "8720"
    assert saved["total_cost"] == "8100"
    assert len(saved["lines"]) == 5
    assert saved["sources"][0]["file"] == "01_pricing_2026-10.xlsx"
    assert saved["memo"] == "메모 테스트"


# ── 내부용 / 고객용 PDF (3장, 9장 출력) ──────────────────
def test_internal_html_contains_cost_and_margin(loaded):
    req, q = jungwoo_quote(loaded)
    no = quotes.save_quote(loaded, req, q, "정우정밀", "", "")
    html = pdf_quote.internal_html(quotes.load_quote(loaded, no))
    assert "8,100" in html
    assert "7.11" in html
    assert "KRL" in html or "코리아라인" in html


def test_customer_html_has_no_cost_profit_margin_or_carrier(loaded):
    req, q = jungwoo_quote(loaded)
    no = quotes.save_quote(loaded, req, q, "정우정밀", "내부 메모", "사유")
    html = pdf_quote.customer_html(quotes.load_quote(loaded, no))
    for hidden in ["Cost", "Profit", "3,450", "3450", "420", "7.11", "코리아라인", "KRL", "내부 메모", "사유"]:
        assert hidden not in html, hidden
    assert "8,720" in html


def test_customer_pdf_text_does_not_contain_cost(loaded):
    req, q = jungwoo_quote(loaded)
    no = quotes.save_quote(loaded, req, q, "정우정밀", "", "")
    doc = quotes.load_quote(loaded, no)
    text = pdf_text(pdf_quote.to_pdf(pdf_quote.customer_html(doc)))
    assert "8,720" in text
    assert "견적번호" in text  # 한글 글꼴이 실제로 들어갔는지 확인
    for hidden in ["Cost", "Profit", "3,450", "8,100", "620", "마진", "KRL", "코리아라인"]:
        assert hidden not in text, hidden
    assert "Los Angeles" in text  # 지명은 영어로 표시


def test_internal_pdf_text_has_cost_and_source(loaded):
    req, q = jungwoo_quote(loaded)
    no = quotes.save_quote(loaded, req, q, "정우정밀", "", "")
    text = pdf_text(pdf_quote.to_pdf(pdf_quote.internal_html(quotes.load_quote(loaded, no))))
    assert "8,100" in text
    assert "01_pricing_2026-10.xlsx" in text
