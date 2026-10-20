"""SQLite 스키마 (기획서 6장: pricing, customer_margin, quote, quote_line).

금액은 부동소수점 오차를 피하려고 TEXT로 저장하고, 코드에서는 Decimal로 읽는다.
날짜는 ISO 문자열(YYYY-MM-DD)로 저장한다.
"""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "autorate.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS pricing (
    rate_id      TEXT PRIMARY KEY,
    carrier      TEXT NOT NULL,
    pol          TEXT NOT NULL,
    pod          TEXT NOT NULL,
    container    TEXT NOT NULL,
    charge       TEXT NOT NULL,
    charge_type  TEXT NOT NULL CHECK (charge_type IN ('Freight', 'Local')),
    unit         TEXT NOT NULL,
    currency     TEXT NOT NULL CHECK (currency = 'USD'),
    cost         TEXT NOT NULL,
    valid_from   TEXT NOT NULL,
    valid_to     TEXT NOT NULL CHECK (valid_to >= valid_from),
    remark       TEXT,
    source_file  TEXT,
    uploaded_at  TEXT,
    UNIQUE (carrier, pol, pod, container, charge, valid_from)
);
CREATE INDEX IF NOT EXISTS idx_pricing_lookup
    ON pricing (pol, pod, container, charge);

CREATE TABLE IF NOT EXISTS customer_margin (
    customer_id    TEXT PRIMARY KEY,
    customer_name  TEXT NOT NULL,
    margin_pct     TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    source         TEXT NOT NULL CHECK (source IN ('upload', 'manual')),
    remark         TEXT,
    UNIQUE (customer_name, effective_from)
);

CREATE TABLE IF NOT EXISTS quote (
    quote_no      TEXT PRIMARY KEY,
    issue_date    TEXT NOT NULL,
    valid_until   TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    carrier       TEXT,
    pol           TEXT NOT NULL,
    pod           TEXT NOT NULL,
    container     TEXT NOT NULL,
    qty           INTEGER NOT NULL CHECK (qty >= 1),
    margin_pct    TEXT NOT NULL,
    total_sales   TEXT,
    total_cost    TEXT,
    profit        TEXT,
    source_type   TEXT NOT NULL CHECK (source_type IN ('new', 'copy', 'imported_docx')),
    copied_from   TEXT,
    price_mode    TEXT CHECK (price_mode IN ('recalc', 'keep')),
    status        TEXT NOT NULL CHECK (status IN ('draft', 'issued')),
    memo          TEXT,
    margin_reason TEXT,
    saved_at      TEXT
);

CREATE TABLE IF NOT EXISTS quote_line (
    quote_no    TEXT NOT NULL REFERENCES quote (quote_no),
    line_no     INTEGER NOT NULL,
    charge      TEXT NOT NULL,
    charge_type TEXT NOT NULL,
    unit        TEXT NOT NULL,
    qty         INTEGER NOT NULL,
    unit_cost   TEXT,
    unit_sales  TEXT,
    amt_cost    TEXT,
    amt_sales   TEXT,
    profit      TEXT,
    rate_id     TEXT,
    PRIMARY KEY (quote_no, line_no)
);
"""


# 이전 단계에서 만든 DB에 없는 열을 추가한다 (데이터는 그대로 둔다)
ADDED_QUOTE_COLUMNS = {"memo": "TEXT", "margin_reason": "TEXT", "saved_at": "TEXT"}


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """DB 연결을 만들고 스키마가 없으면 생성한다."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(quote)")}
    for column, column_type in ADDED_QUOTE_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE quote ADD COLUMN {column} {column_type}")
    conn.commit()
    return conn
