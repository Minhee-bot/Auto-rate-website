import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from autorate.calculator import QuoteRequest, quote_carriers
from autorate.db import connect
from autorate.margin_import import add_manual_margin, parse_margin, save_margins
from autorate.pricing_import import build_plan, parse_pricing, save_plan
from autorate.quote_checks import (
    diagnose_empty,
    quote_warnings,
    route_containers,
    route_pods,
    similar_customers,
)

ROOT = Path(__file__).resolve().parent.parent
REAL_PRICING = ROOT / "01_pricing_2026-10.xlsx"
REAL_MARGIN = ROOT / "02_customer_margin.xlsx"
TODAY = dt.date(2026, 10, 20)


@pytest.fixture
def loaded(tmp_path):
    conn = connect(tmp_path / "t.db")
    save_plan(conn, build_plan(parse_pricing(REAL_PRICING), conn), "01.xlsx", "t")
    rows, _ = parse_margin(REAL_MARGIN)
    save_margins(conn, rows)
    return conn


def req(pod="Los Angeles", container="40HC", qty=1, issue=TODAY, margin="8"):
    return QuoteRequest("부산", pod, container, qty, issue, Decimal(margin))


def messages(issues):
    return [i.message for i in issues]


# ── 7장 1·2·3번: 요율 없음 / 컨테이너 없음 / 만료 ─────────
def test_case1_route_without_pricing_is_blocked(loaded):
    r = req(pod="Sydney")
    assert quote_carriers(loaded, r) == []
    issues = diagnose_empty(loaded, r)
    assert issues[0].level == "block"
    assert "등록된 요율이 없어" in issues[0].message
    assert "Sydney" in issues[0].message


def test_case2_container_missing_lists_available_containers(loaded):
    # Rotterdam은 40HC만 있음 (기획서 예: Rotterdam 40GP)
    r = req(pod="Rotterdam", container="40GP")
    assert quote_carriers(loaded, r) == []
    assert "40HC" in diagnose_empty(loaded, r)[0].message


def test_case3_expired_only_shows_last_expiry(loaded):
    r = req(pod="Singapore", container="20GP")
    assert quote_carriers(loaded, r) == []
    assert "Singapore 20GP 요율이 2026-09-30에 만료됐어요" in diagnose_empty(loaded, r)[0].message


def test_available_quote_has_no_empty_diagnosis(loaded):
    r = req()
    assert quote_carriers(loaded, r)
    assert diagnose_empty(loaded, r) == []


def test_route_helpers(loaded):
    assert "Los Angeles" in route_pods(loaded, "부산")
    assert route_containers(loaded, "부산", "Rotterdam") == ["40HC"]


# ── 7장 4번: 일부 항목만 유효 ─────────────────────────
def test_partial_charges_warn_and_list_missing(loaded):
    loaded.execute(
        "INSERT INTO pricing VALUES ('RX9','테스트선사','부산','Los Angeles','40HC','Ocean Freight',"
        "'Freight','Per Container','USD','500','2026-10-01','2026-10-31',NULL,NULL,NULL)"
    )
    q = next(x for x in quote_carriers(loaded, req()) if x.carrier == "테스트선사")
    issues = quote_warnings(q, req())
    warn = [i for i in issues if i.level == "warn"]
    assert any("BAF" in i.message for i in warn)


# ── 7장 5번: 기간 중복 차단 ───────────────────────────
def test_duplicate_period_is_blocking_issue(loaded):
    loaded.execute(
        "INSERT INTO pricing VALUES ('RX3','코리아라인(KRL)','부산','Los Angeles','40HC','THC','Local',"
        "'Per Container','USD','999','2026-10-15','2026-10-25',NULL,NULL,NULL)"
    )
    q = quote_carriers(loaded, req())[0]
    issues = quote_warnings(q, req())
    assert issues[0].level == "block"


# ── 7장 6번: 임박 (단축 알림) ─────────────────────────
def test_shortened_validity_is_info(loaded):
    issues = quote_warnings(quote_carriers(loaded, req())[0], req())
    info = [i for i in issues if i.level == "info"]
    assert any("2026-10-31" in i.message for i in info)


# ── 7장 10번: 마진 0% 이하 / Profit 음수 ──────────────
def test_zero_margin_warns(loaded):
    r = req(margin="0")
    issues = quote_warnings(quote_carriers(loaded, r)[0], r)
    assert any(i.level == "warn" and "0% 이하" in i.message for i in issues)


def test_negative_profit_warns(loaded):
    r = req(margin="-20")
    q = quote_carriers(loaded, r)[0]
    assert q.profit < 0
    issues = quote_warnings(q, r)
    assert any(i.level == "warn" and "Profit이 마이너스" in i.message for i in issues)


def test_normal_quote_has_no_warning(loaded):
    r = req()
    issues = quote_warnings(quote_carriers(loaded, r)[0], r)
    assert [i for i in issues if i.level == "warn"] == []


# ── 7장 7·8번: 미등록 고객 / 표기 차이 ─────────────────
def test_similar_customer_name_is_suggested_not_matched(loaded):
    assert similar_customers(loaded, "정우정밀(주)") == ["정우정밀"]
    assert similar_customers(loaded, "㈜ 정우 정밀") == ["정우정밀"]


def test_exact_name_has_no_suggestion(loaded):
    assert similar_customers(loaded, "정우정밀") == []


def test_unregistered_customer_has_no_table_margin(loaded):
    from autorate.margin_import import find_margin

    assert find_margin(loaded, "대원산업", TODAY) is None
    add_manual_margin(loaded, "대원산업", Decimal("7"), TODAY, "가상값")
    assert find_margin(loaded, "대원산업", TODAY) == Decimal(7)
