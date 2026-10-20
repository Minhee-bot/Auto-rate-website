import datetime as dt
from decimal import Decimal

from autorate import places
from autorate.calculator import QuoteRequest, quote_carriers
from autorate.db import connect
from autorate.pricing_import import PricingRow, unregistered_places
from autorate.quote_checks import route_pods, route_pols


def test_korean_and_english_names_map_to_same_place():
    assert places.canonical("부산") == "Busan"
    assert places.canonical("Busan") == "Busan"
    assert places.canonical("LA") == "Los Angeles"
    assert places.canonical(" 로테르담 ") == "Rotterdam"


def test_unknown_place_keeps_original_and_is_not_registered():
    assert places.display("Oakland") == "Oakland"
    assert not places.is_registered("오클랜드")


def test_pricing_stored_as_korean_is_found_by_english_name(tmp_path):
    conn = connect(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO pricing VALUES ('RK1','테스트선사','부산','Los Angeles','40HC','Ocean Freight',"
        "'Freight','Per Container','USD','100','2026-10-01','2026-10-31',NULL,NULL,NULL)"
    )
    # 저장값은 '부산' 그대로인데, 영어 지명으로 조회해도 찾는다
    q = quote_carriers(conn, QuoteRequest("Busan", "Los Angeles", "40HC", 1, dt.date(2026, 10, 20), Decimal(0)))
    assert len(q) == 1
    assert conn.execute("SELECT pol FROM pricing").fetchone()[0] == "부산"  # 원본 유지


def test_route_lists_show_english_names(tmp_path):
    conn = connect(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO pricing VALUES ('RK2','테스트선사','부산','로테르담','40HC','Ocean Freight',"
        "'Freight','Per Container','USD','100','2026-10-01','2026-10-31',NULL,NULL,NULL)"
    )
    assert route_pols(conn) == ["Busan"]
    assert route_pods(conn, "Busan") == ["Rotterdam"]


def test_unregistered_place_is_reported_on_upload():
    rows = [
        PricingRow(row_no=2, pol="부산", pod="Rotterdam"),
        PricingRow(row_no=3, pol="부산", pod="오클랜드"),
    ]
    assert unregistered_places(rows) == [(3, "오클랜드")]
