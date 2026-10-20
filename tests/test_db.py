import sqlite3

import pytest

from autorate.db import connect


def _table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def test_creates_four_tables(tmp_path):
    conn = connect(tmp_path / "t.db")
    assert {"pricing", "customer_margin", "quote", "quote_line"} <= _table_names(conn)


def test_pricing_rejects_non_usd(tmp_path):
    conn = connect(tmp_path / "t.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO pricing VALUES ('R1','KRL','부산','LA','40HC','OF','Freight',"
            "'Per Container','KRW','3450','2026-10-01','2026-10-31',NULL,NULL,NULL)"
        )


def test_pricing_rejects_end_before_start(tmp_path):
    conn = connect(tmp_path / "t.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO pricing VALUES ('R1','KRL','부산','LA','40HC','OF','Freight',"
            "'Per Container','USD','3450','2026-10-31','2026-10-01',NULL,NULL,NULL)"
        )


def test_quote_line_requires_existing_quote(tmp_path):
    conn = connect(tmp_path / "t.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO quote_line (quote_no, line_no, charge, charge_type, unit, qty) "
            "VALUES ('Q-2610-999', 1, 'THC', 'Local', 'Per Container', 2)"
        )
