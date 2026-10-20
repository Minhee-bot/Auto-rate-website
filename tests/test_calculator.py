import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from autorate.calculator import QuoteRequest, quote_carriers, sales_unit_price
from autorate.db import connect
from autorate.margin_import import find_margin, parse_margin, save_margins
from autorate.pricing_import import build_plan, parse_pricing, save_plan

ROOT = Path(__file__).resolve().parent.parent
REAL_PRICING = ROOT / "01_pricing_2026-10.xlsx"
REAL_MARGIN = ROOT / "02_customer_margin.xlsx"
TODAY_QUOTE = dt.date(2026, 10, 20)


@pytest.fixture
def loaded(tmp_path):
    conn = connect(tmp_path / "t.db")
    save_plan(conn, build_plan(parse_pricing(REAL_PRICING), conn), "01.xlsx", "t")
    rows, _ = parse_margin(REAL_MARGIN)
    save_margins(conn, rows)
    return conn


def req(pod="Los Angeles", container="40HC", qty=2, issue=TODAY_QUOTE, margin="8"):
    return QuoteRequest("부산", pod, container, qty, issue, Decimal(margin))


# ── 반올림 (4-3) ───────────────────────────────────────
@pytest.mark.parametrize(
    "cost, margin, expected",
    [(10, 5, 10), (150, 5, 158), (420, 8, 454), (3450, 8, 3726), (3050, 12, 3416), (380, 12, 426)],
)
def test_sales_unit_price_bankers_rounding(cost, margin, expected):
    assert sales_unit_price(Decimal(cost), Decimal(margin)) == Decimal(expected)


# ── 정우정밀 예시 (4-6) ─────────────────────────────────
def test_jungwoo_example_totals(loaded):
    quotes = quote_carriers(loaded, req())
    assert len(quotes) == 1
    q = quotes[0]
    assert q.carrier.endswith("(KRL)")
    assert q.total_sales == Decimal(8720)
    assert q.total_cost == Decimal(8100)
    assert q.profit == Decimal(620)
    assert q.margin_rate == Decimal("7.11")


def test_jungwoo_example_lines(loaded):
    lines = {l.charge: l for l in quote_carriers(loaded, req())[0].lines}
    assert lines["Ocean Freight"].unit_sales == 3726
    assert lines["BAF"].unit_sales == 454
    assert lines["THC"].unit_sales == 150  # Local은 마진 없음
    assert lines["DOC Fee"].qty == 1  # Per B/L
    assert lines["Seal Fee"].amt_sales == 20


def test_validity_shortened_to_pricing_end(loaded):
    q = quote_carriers(loaded, req())[0]
    assert q.valid_until == dt.date(2026, 10, 31)
    assert q.shortened is True


# ── 태강전자 예시 (체크리스트) ───────────────────────────
def test_taekang_hamburg_example(loaded):
    q = quote_carriers(loaded, req(pod="Hamburg", container="40HC", qty=1, margin="12"))[0]
    assert q.total_sales == Decimal(4042)
    assert q.total_cost == Decimal(3630)
    lines = {l.charge: l for l in q.lines}
    assert lines["Ocean Freight"].amt_sales == 3416
    assert lines["BAF"].amt_sales == 426
    assert lines["THC"].amt_sales + lines["DOC Fee"].amt_sales + lines["Seal Fee"].amt_sales == 200


# ── 조회 조건 ──────────────────────────────────────────
def test_no_rate_for_unknown_route(loaded):
    assert quote_carriers(loaded, req(pod="Sydney")) == []


def test_expired_only_rate_is_not_used(loaded):
    # Singapore 20GP는 9월 요율만 있음 (10/20 기준 유효 없음)
    assert quote_carriers(loaded, req(pod="Singapore", container="20GP")) == []


def test_issue_date_uses_the_rate_valid_on_that_date(loaded):
    # 9/15 견적은 9월 요율을 쓰고, 유효기간은 9/15+14일(9/29)로 잡힌다
    q = quote_carriers(loaded, req(issue=dt.date(2026, 9, 15)))[0]
    assert all(l.valid_to == dt.date(2026, 9, 30) for l in q.lines)
    assert q.valid_until == dt.date(2026, 9, 29)
    assert q.shortened is False


def test_issue_date_with_no_valid_rate_returns_nothing(loaded):
    assert quote_carriers(loaded, req(issue=dt.date(2026, 11, 5))) == []


def test_issue_on_last_valid_day_is_used(loaded):
    q = quote_carriers(loaded, req(issue=dt.date(2026, 10, 31)))
    assert len(q) == 1
    assert q[0].valid_until == dt.date(2026, 10, 31)


def test_carrier_without_ocean_freight_is_excluded(loaded):
    loaded.execute(
        "INSERT INTO pricing VALUES ('RX1','테스트선사','부산','Los Angeles','40HC','THC','Local',"
        "'Per Container','USD','1','2026-10-01','2026-10-31',NULL,NULL,NULL)"
    )
    carriers = [q.carrier for q in quote_carriers(loaded, req())]
    assert "테스트선사" not in carriers


def test_carriers_sorted_by_total_cost_ascending(loaded):
    # 같은 구간에 더 싼 선사를 추가해 정렬을 확인
    loaded.execute(
        "INSERT INTO pricing VALUES ('RX2','저가선사','부산','Los Angeles','40HC','Ocean Freight',"
        "'Freight','Per Container','USD','1000','2026-10-01','2026-10-31',NULL,NULL,NULL)"
    )
    quotes = quote_carriers(loaded, req())
    costs = [q.total_cost for q in quotes]
    assert costs == sorted(costs)
    assert quotes[0].carrier == "저가선사"


def test_same_item_two_valid_rows_blocks_carrier(loaded):
    loaded.execute(
        "INSERT INTO pricing VALUES ('RX3','코리아라인(KRL)','부산','Los Angeles','40HC','THC','Local',"
        "'Per Container','USD','999','2026-10-15','2026-10-25',NULL,NULL,NULL)"
    )
    q = quote_carriers(loaded, req())[0]
    assert q.blocked_reason is not None


# ── 마진 조회 ──────────────────────────────────────────
def test_find_margin_uses_latest_effective_row(loaded):
    loaded.execute(
        "INSERT INTO customer_margin (customer_id, customer_name, margin_pct, effective_from, source) "
        "VALUES ('C999','정우정밀','9','2026-10-01','manual')"
    )
    assert find_margin(loaded, "정우정밀", dt.date(2026, 10, 20)) == Decimal(9)
    assert find_margin(loaded, "정우정밀", dt.date(2026, 5, 1)) == Decimal(8)


def test_find_margin_unknown_customer_is_none(loaded):
    assert find_margin(loaded, "대원산업", TODAY_QUOTE) is None


def test_find_margin_before_any_effective_date_is_none(loaded):
    assert find_margin(loaded, "정우정밀", dt.date(2025, 12, 31)) is None
