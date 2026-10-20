"""견적 계산: 요율 조회, 선사별 묶기, 마진 적용, 합계, 유효기간 (기획서 4장).

- 조회 조건: POL·POD·컨테이너 일치, 유효시작 <= 견적일 <= 유효종료
- Sales 단가: Freight(OF, BAF)만 Cost × (1 + 마진%), 은행가 반올림 (정수)
- Local(THC, DOC, Seal)은 Cost 그대로
- 견적 유효기간: MIN(견적일 + 14일, 적용 행들의 유효종료 중 가장 빠른 날)
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

from autorate import places

QUOTE_VALID_DAYS = 14
CHARGE_ORDER = ["Ocean Freight", "BAF", "THC", "DOC Fee", "Seal Fee"]
PER_CONTAINER = "Per Container"


@dataclass
class QuoteRequest:
    pol: str
    pod: str
    container: str
    qty: int
    issue_date: dt.date
    margin_pct: Decimal


@dataclass
class LineResult:
    charge: str
    charge_type: str
    unit: str
    qty: int
    unit_cost: Decimal
    unit_sales: Decimal
    amt_cost: Decimal
    amt_sales: Decimal
    rate_id: str
    valid_to: dt.date

    @property
    def profit(self) -> Decimal:
        return self.amt_sales - self.amt_cost


@dataclass
class CarrierQuote:
    carrier: str
    lines: list[LineResult] = field(default_factory=list)
    missing_charges: list[str] = field(default_factory=list)
    valid_until: dt.date | None = None
    shortened: bool = False
    blocked_reason: str | None = None  # 같은 항목 기간 중복 등 계산 차단 사유

    @property
    def total_cost(self) -> Decimal:
        return sum((l.amt_cost for l in self.lines), Decimal(0))

    @property
    def total_sales(self) -> Decimal:
        return sum((l.amt_sales for l in self.lines), Decimal(0))

    @property
    def profit(self) -> Decimal:
        return self.total_sales - self.total_cost

    @property
    def margin_rate(self) -> Decimal | None:
        """마진율(매출 대비) = Profit ÷ Sales × 100, 소수점 2자리 표시용."""
        if not self.total_sales:
            return None
        return (self.profit / self.total_sales * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)


def sales_unit_price(cost: Decimal, margin_pct: Decimal) -> Decimal:
    """Freight 단가 판매가: Cost × (1 + 마진%)를 정수로 은행가 반올림 (4-3)."""
    return (cost * (1 + margin_pct / 100)).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)


def _build_carrier(carrier: str, charges: dict, req: QuoteRequest) -> CarrierQuote:
    issue = req.issue_date
    standard_end = issue + dt.timedelta(days=QUOTE_VALID_DAYS)

    conflicts = [c for c, rows in charges.items() if len(rows) > 1]
    if conflicts:
        return CarrierQuote(carrier, blocked_reason=f"같은 항목 기간 중복: {', '.join(conflicts)}")

    quote = CarrierQuote(carrier)
    quote.missing_charges = [c for c in CHARGE_ORDER if c not in charges]
    applied_ends = []

    for charge in CHARGE_ORDER:
        if charge not in charges:
            continue
        r = charges[charge][0]
        cost = Decimal(r["cost"])
        qty = req.qty if r["unit"] == PER_CONTAINER else 1
        if r["charge_type"] == "Freight":
            unit_sales = sales_unit_price(cost, req.margin_pct)
        else:
            unit_sales = cost  # Local은 마진 없이 Cost 그대로 청구
        valid_to = dt.date.fromisoformat(r["valid_to"])
        applied_ends.append(valid_to)
        quote.lines.append(
            LineResult(
                charge=charge,
                charge_type=r["charge_type"],
                unit=r["unit"],
                qty=qty,
                unit_cost=cost,
                unit_sales=unit_sales,
                amt_cost=cost * qty,
                amt_sales=unit_sales * qty,
                rate_id=r["rate_id"],
                valid_to=valid_to,
            )
        )

    quote.valid_until = min([standard_end, *applied_ends])
    quote.shortened = quote.valid_until < standard_end
    return quote


def quote_carriers(conn: sqlite3.Connection, req: QuoteRequest) -> list[CarrierQuote]:
    """견적일에 유효한 요율을 선사별로 묶어 Total Cost 오름차순으로 반환한다.

    Ocean Freight가 없는 선사는 제외한다 (4-1). 계산 차단 선사는 목록 맨 뒤에 둔다.
    """
    iso = req.issue_date.isoformat()
    pols = places.raw_forms(req.pol)
    pods = places.raw_forms(req.pod)
    rows = conn.execute(
        f"SELECT * FROM pricing WHERE pol IN ({','.join('?' * len(pols))}) "
        f"AND pod IN ({','.join('?' * len(pods))}) AND container = ? "
        "AND valid_from <= ? AND valid_to >= ?",
        (*pols, *pods, req.container, iso, iso),
    ).fetchall()

    by_carrier: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_carrier[r["carrier"]][r["charge"]].append(r)

    quotes = [
        _build_carrier(carrier, charges, req)
        for carrier, charges in by_carrier.items()
        if "Ocean Freight" in charges
    ]
    quotes.sort(key=lambda q: (q.blocked_reason is not None, q.total_cost))
    return quotes
