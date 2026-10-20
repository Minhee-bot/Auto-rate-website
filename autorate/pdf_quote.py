"""견적 PDF: 내부용 / 고객용 (기획서 3장 출력 항목, 4-2 표시 규칙).

고객용은 Cost·Profit·마진 값을 '가려서' 만드는 것이 아니라, 처음부터 그 값을 넘기지 않는다
(customer_view에 해당 키가 없다). 그래서 PDF 텍스트에도 원가가 남지 않는다.
"""

from __future__ import annotations

import html
from io import BytesIO
from pathlib import Path

from xhtml2pdf import pisa
from xhtml2pdf.config.resources import ResourceAccessPolicy

COMPANY_NAME = "에스제이포워딩(주)"  # 확인 필요 항목 기본값 (기존 견적서 발신사)
CUSTOMER_FOOTER = "※ 본 견적은 유효기간 내 선적 건에 한하며, 선사 사정에 따라 변경될 수 있습니다."
FONT_PATH = Path("C:/Windows/Fonts/malgun.ttf")  # Windows 기본 한글 글꼴 (맑은 고딕)
# 글꼴 폴더만 읽기 허용 (문서 폴더 밖의 파일은 기본적으로 읽지 못함)
FONT_POLICY = ResourceAccessPolicy(extra_roots=(FONT_PATH.parent,))


def _money(value) -> str:
    return f"{int(float(value)):,}"


def customer_view(quote: dict) -> dict:
    """고객용에 들어갈 값만 골라 담는다. 선사명, Cost, Profit, 마진은 넣지 않는다."""
    return {
        "quote_no": quote["quote_no"],
        "issue_date": quote["issue_date"],
        "valid_until": quote["valid_until"],
        "customer_name": quote["customer_name"],
        "pol": quote["pol"],
        "pod": quote["pod"],
        "container": quote["container"],
        "qty": quote["qty"],
        "lines": [
            {
                "charge": l["charge"],
                "unit": l["unit"],
                "qty": l["qty"],
                "unit_sales": l["unit_sales"],
                "amt_sales": l["amt_sales"],
            }
            for l in quote["lines"]
        ],
        "total_sales": quote["total_sales"],
    }


def internal_view(quote: dict) -> dict:
    """내부용: 원가·마진·출처까지 모두 담는다."""
    total_sales = int(float(quote["total_sales"]))
    total_cost = int(float(quote["total_cost"]))
    profit = total_sales - total_cost
    return {
        **customer_view(quote),
        "carrier": quote["carrier"],
        "margin_pct": quote["margin_pct"],
        "margin_reason": quote.get("margin_reason"),
        "memo": quote.get("memo"),
        "sources": quote.get("sources", []),
        "lines": quote["lines"],
        "total_cost": total_cost,
        "profit": profit,
        "margin_rate": f"{profit / total_sales * 100:.2f}" if total_sales else "-",
    }


_STYLE = f"""
@font-face {{ font-family: Malgun; src: url('{FONT_PATH.as_posix()}'); }}
body {{ font-family: Malgun; font-size: 10pt; color: #111827; }}
h1 {{ font-size: 18pt; margin: 0 0 6pt 0; }}
.meta td {{ padding: 2pt 6pt; font-size: 9.5pt; }}
table.items {{ width: 100%; border-collapse: collapse; margin-top: 8pt; }}
table.items th {{ background: #e5e7eb; padding: 4pt; font-size: 9pt; }}
table.items td {{ padding: 4pt; border-bottom: 1px solid #e5e7eb; font-size: 9pt; }}
td.num {{ text-align: right; }}
td.internal {{ background: #f3f4f6; }}
tr.total td {{ font-weight: bold; border-top: 1.5px solid #111827; }}
.note {{ font-size: 8.5pt; color: #374151; margin-top: 10pt; }}
.box {{ border: 1px solid #d1d5db; padding: 6pt; margin-top: 8pt; font-size: 9pt; }}
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _header(v: dict, title: str) -> str:
    return f"""
<h1>{_esc(title)}</h1>
<table class="meta">
<tr><td>견적번호</td><td>{_esc(v['quote_no'])}</td><td>발행일</td><td>{_esc(v['issue_date'])}</td></tr>
<tr><td>유효기간</td><td>{_esc(v['valid_until'])}</td><td>통화</td><td>USD</td></tr>
<tr><td>수신</td><td>{_esc(v['customer_name'])}</td><td>발신</td><td>{_esc(COMPANY_NAME)}</td></tr>
<tr><td>구간</td><td>{_esc(v['pol'])} → {_esc(v['pod'])}</td><td>컨테이너</td><td>{_esc(v['container'])} × {_esc(v['qty'])}</td></tr>
</table>"""


def customer_html(quote: dict) -> str:
    v = customer_view(quote)
    rows = "".join(
        f"<tr><td>{_esc(l['charge'])}</td><td>{_esc(l['unit'])}</td><td class='num'>{_esc(l['qty'])}</td>"
        f"<td class='num'>{_money(l['unit_sales'])}</td><td class='num'>{_money(l['amt_sales'])}</td></tr>"
        for l in v["lines"]
    )
    return f"""<html><head><meta charset='utf-8'><style>{_STYLE}</style></head><body>
{_header(v, 'FREIGHT QUOTATION')}
<table class="items">
<tr><th>항목</th><th>단위</th><th>수량</th><th>단가 (USD)</th><th>금액 (USD)</th></tr>
{rows}
<tr class="total"><td colspan="4">TOTAL (USD)</td><td class="num">{_money(v['total_sales'])}</td></tr>
</table>
<div class="note">{_esc(CUSTOMER_FOOTER)}</div>
</body></html>"""


def internal_html(quote: dict) -> str:
    v = internal_view(quote)
    rows = "".join(
        f"<tr><td>{_esc(l['charge'])}</td><td>{_esc(l['charge_type'])}</td><td>{_esc(l['unit'])}</td>"
        f"<td class='num'>{_esc(l['qty'])}</td>"
        f"<td class='num'>{_money(l['unit_sales'])}</td><td class='num'>{_money(l['amt_sales'])}</td>"
        f"<td class='num internal'>{_money(l['unit_cost'])}</td>"
        f"<td class='num internal'>{_money(l['amt_cost'])}</td>"
        f"<td class='num internal'>{_money(l['profit'])}</td></tr>"
        for l in v["lines"]
    )
    sources = "<br/>".join(
        f"{_esc(s['file'])} / {_esc(s['valid_from'])} ~ {_esc(s['valid_to'])}" for s in v["sources"]
    ) or "-"
    reason = (
        f"<br/>마진 수정 사유: {_esc(v['margin_reason'])}" if v["margin_reason"] else ""
    )
    memo = f"<br/>메모: {_esc(v['memo'])}" if v["memo"] else ""
    return f"""<html><head><meta charset='utf-8'><style>{_STYLE}</style></head><body>
<h1>견적서 (내부용)</h1>
{_header(v, '내부용 - 외부 전달 금지')}
<table class="items">
<tr><th>항목</th><th>구분</th><th>단위</th><th>수량</th><th>Sales 단가</th><th>Sales 금액</th>
<th>Cost 단가</th><th>Cost 금액</th><th>Profit</th></tr>
{rows}
<tr class="total"><td colspan="5">TOTAL</td><td class="num">{_money(v['total_sales'])}</td>
<td></td><td class="num internal">{_money(v['total_cost'])}</td><td class="num internal">{_money(v['profit'])}</td></tr>
</table>
<div class="box">
선사: {_esc(v['carrier'])}<br/>
적용 마진: {_esc(v['margin_pct'])}% (Freight에만 적용) / 마진율(Profit ÷ Sales): {v['margin_rate']}%<br/>
pricing 출처: {sources}{reason}{memo}
</div>
<div class="note">{_esc(CUSTOMER_FOOTER)}</div>
</body></html>"""


def to_pdf(document: str) -> bytes:
    buf = BytesIO()
    result = pisa.CreatePDF(document, dest=buf, encoding="utf-8", resource_policy=FONT_POLICY)
    if result.err:
        raise RuntimeError("PDF 생성에 실패했어요. 다시 시도해 주세요.")
    return buf.getvalue()
