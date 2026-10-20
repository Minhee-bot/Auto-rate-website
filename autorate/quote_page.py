"""새 견적 화면.

- 왼쪽: 조건 입력 (고객, 견적일, POL, POD, 컨테이너, 수량, 마진%, 선사, 메모)
- 오른쪽: 안내 문구(맨 위 고정) → 요약 카드 → 항목 표 → 출력 버튼
- 좁은 화면에서는 위아래로 쌓인다 (Streamlit 컬럼 기본 동작).
"""

from __future__ import annotations

import datetime as dt
import html
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st

from autorate import calculator as calc
from autorate import margin_import as mi
from autorate import places
from autorate import pdf_quote
from autorate import quote_checks as qc
from autorate import quotes
from autorate.ui import show_table

NEW_CUSTOMER = "직접 입력"
# 수준별 색: 진행 불가(빨강) / 확인 후 진행(주황) / 참고(파랑)
LEVEL_COLOR = {"block": ("#b8402a", "#ebebeb"), "warn": ("#f2c230", "#ebebeb"), "info": ("#000000", "#ebebeb")}
PDF_HELP = "PDF 출력은 4단계에서 연결돼요."
SAVE_HELP = "견적 저장은 4단계에서 연결돼요."


def usd(value) -> str:
    return f"USD {int(value):,}"


def pct(value) -> str:
    return f"{value:.2f}%"


def _notice(level: str, text: str) -> None:
    color, bg = LEVEL_COLOR[level]
    st.markdown(
        f'<div style="border:1px solid #000000;border-left:4px solid {color};background:{bg};color:#000000;'
        f'padding:10px 14px;border-radius:0;margin:0 0 8px 0;font-weight:300">{html.escape(text)}</div>',
        unsafe_allow_html=True,
    )


def _set_container(value: str) -> None:
    st.session_state["q_container"] = value


def _actions(actions, data_page, key_prefix: str) -> None:
    """안내 문구의 다음 행동. 버튼이 되는 것만 버튼으로, 나머지는 작은 안내로."""
    buttons = [(label, act) for label, act in actions if act == qc.UPLOAD or act.startswith("container:")]
    hints = [label for label, act in actions if act not in (qc.UPLOAD,) and not act.startswith("container:")]
    if buttons:
        cols = st.columns(len(buttons))
        for i, (label, act) in enumerate(buttons):
            if act == qc.UPLOAD:
                cols[i].page_link(data_page, label=label)
            else:
                cols[i].button(
                    label, key=f"{key_prefix}_{i}", on_click=_set_container, args=(act.split(":", 1)[1],)
                )
    for hint in hints:
        st.caption(hint)


def _show_issues(issues, data_page, key_prefix: str) -> None:
    for n, issue in enumerate(issues):
        _notice(issue.level, issue.message)
        _actions(issue.actions, data_page, f"{key_prefix}_{n}")


def _customer_input(conn) -> str:
    names = sorted({m["customer_name"] for m in mi.load_margins(conn)})
    choice = st.selectbox("고객 *", names + [NEW_CUSTOMER], key="q_customer")
    if choice == NEW_CUSTOMER:
        return st.text_input("고객명 입력 *", key="q_customer_text").strip()
    return choice


def _cards(items) -> None:
    cells = []
    for label, value, internal in items:
        bg = "#c8c8c8" if internal else "#ebebeb"
        tag = '<div style="color:#4a4a4a;font-family:Libertinus Mono,Gowun Batang,monospace;font-size:11px">내부 전용</div>' if internal else ""
        cells.append(
            f'<div style="border:1px solid #000000;background:{bg};border-radius:0;padding:12px 14px">'
            f'<div style="color:#4a4a4a;font-size:12px">{label}</div>'
            f'<div style="font-size:20px;font-weight:300;color:#000000">{html.escape(value)}</div>{tag}</div>'
        )
    st.markdown(
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px">'
        + "".join(cells) + "</div>",
        unsafe_allow_html=True,
    )


def render(conn, today: dt.date, data_page) -> None:
    st.markdown("### 새 견적")
    left, right = st.columns([1, 1.3], gap="large")
    with right:
        alerts = st.container()  # 안내 문구 고정 위치 (결과 영역 맨 위)

    with left, st.container(border=True):
        st.markdown("**조건 입력**")
        customer = _customer_input(conn)
        issue_date = st.date_input("견적일 *", value=today, key="q_issue")

        pols = qc.route_pols(conn)
        if not pols:
            with alerts:
                _notice("info", "저장된 요율이 없어요. 자료 관리에서 pricing 파일을 먼저 업로드해 주세요.")
                _actions([("요율 업로드하기", qc.UPLOAD)], data_page, "empty")
            return
        pol = st.selectbox("POL *", pols, key="q_pol")
        pod_raw = st.selectbox(
            "POD *",
            qc.route_pods(conn, pol),
            key="q_pod",
            accept_new_options=True,
            placeholder="도착지를 고르거나 입력하세요",
        )
        pod = places.display(pod_raw) if pod_raw else ""
        containers = qc.route_containers(conn, pol, pod) if pod else []
        container = None
        if containers:
            container = st.selectbox("컨테이너 *", containers, key="q_container")
        qty = int(st.number_input("수량 *", min_value=1, value=1, step=1, key="q_qty"))

        # ── 마진 (7장 7·9번) ──
        table_margin = mi.find_margin(conn, customer, issue_date) if customer else None
        margin_text = st.text_input(
            "마진 (%) *",
            value="" if table_margin is None else str(table_margin),
            key=f"q_margin_{customer}_{issue_date.isoformat()}",
            help="Freight(OF, BAF)에만 적용돼요.",
        )
        reason = ""
        if table_margin is not None and margin_text.strip() and margin_text.strip() != str(table_margin):
            reason = st.text_input("마진 수정 사유 *", key="q_margin_reason").strip()
        save_margin = False
        if customer and table_margin is None:
            save_margin = st.radio(
                "이 마진을 어떻게 할까요?", ["이번만 적용", "마진표에 저장"], horizontal=True, key="q_save_mode"
            ) == "마진표에 저장"
        memo_slot = st.container()

    # ── 입력 검증: 진행 불가 안내 (빨강) ──
    with alerts:
        if not pod:
            _notice("info", "도착지(POD)를 고르면 요율을 찾아볼게요.")
            return
        if container is None:
            _show_issues(
                qc.diagnose_empty(conn, calc.QuoteRequest(pol, pod, "", qty, issue_date, Decimal(0))),
                data_page, "nocontainer",
            )
            return
        if not customer:
            _notice("info", "고객을 선택하거나 고객명을 입력해 주세요.")
            return
        try:
            margin = Decimal(margin_text.replace("%", "").strip())
        except InvalidOperation:
            _notice("block", f"{customer} 마진%를 입력해야 계산할 수 있어요. 마진표에 없는 고객이면 마진%를 직접 입력해 주세요.")
            return
        if table_margin is None:
            sims = qc.similar_customers(conn, customer)
            if sims:
                _notice("info", f"비슷한 고객이 마진표에 있어요: {', '.join(sims)}. 같은 고객이면 목록에서 골라 주세요. 자동으로 연결하지는 않아요.")
            if save_margin:
                st.button(
                    "마진표에 저장",
                    key="q_save_margin_btn",
                    on_click=mi.add_manual_margin,
                    args=(conn, customer, margin, issue_date, "견적 화면 직접 입력"),
                )
        elif margin != table_margin and not reason:
            _notice("block", f"마진율을 마진표({table_margin}%)와 다르게 입력했어요. 수정 사유를 입력하면 계산할 수 있어요.")
            return

    # ── 요율 조회 (4장) ──
    req = calc.QuoteRequest(pol, pod, container, qty, issue_date, margin)
    candidates = calc.quote_carriers(conn, req)
    if not candidates:
        with alerts:
            _show_issues(qc.diagnose_empty(conn, req), data_page, "noquote")
        return

    usable = [q for q in candidates if q.blocked_reason is None]
    with alerts:
        for q in candidates:
            if q.blocked_reason:
                _show_issues(qc.quote_warnings(q, req), data_page, f"blk_{q.carrier}")
    if not usable:
        return

    with left, st.container(border=True):
        st.markdown("**선사 선택** (Total Cost 낮은 순, 기본 최저가)")
        labels = [
            f"{q.carrier} · Total Cost {usd(q.total_cost)} · 유효 ~{q.valid_until.strftime('%m/%d')}"
            for q in usable
        ]
        picked = st.radio("선사", labels, index=0, key="q_carrier", label_visibility="collapsed")
        q = usable[labels.index(picked)]
        memo_slot.text_area("메모 (내부용 PDF에만 표시)", key="q_memo", height=70)

    issues = qc.quote_warnings(q, req)
    warns = [i for i in issues if i.level == "warn"]
    with alerts:
        _show_issues([i for i in issues if i.level != "block"], data_page, "result")
        if warns:
            st.checkbox("내용을 확인했어요 (확인해야 PDF를 만들 수 있어요)", key="q_confirm")

    with right:
        with st.container(border=True):
            st.markdown("**요약**")
            _cards([
                ("Sales", usd(q.total_sales), False),
                ("Cost", usd(q.total_cost), True),
                ("Profit", usd(q.profit), True),
                ("마진율", pct(q.margin_rate) if q.margin_rate is not None else "-", True),
                ("견적 유효기간", q.valid_until.isoformat() + (" (단축)" if q.shortened else ""), False),
            ])

        with st.container(border=True):
            st.markdown("**항목별 금액**")
            frame = pd.DataFrame(
                [
                    {
                        "항목": l.charge,
                        "구분": l.charge_type,
                        "단위": l.unit,
                        "수량": l.qty,
                        "Sales 단가": int(l.unit_sales),
                        "Sales 금액": int(l.amt_sales),
                        "Cost 단가 (내부)": int(l.unit_cost),
                        "Cost 금액 (내부)": int(l.amt_cost),
                        "Profit (내부)": int(l.profit),
                    }
                    for l in q.lines
                ]
            )
            num_cols = [c for c in frame.columns if c not in ("항목", "구분", "단위")]
            internal = ["Cost 단가 (내부)", "Cost 금액 (내부)", "Profit (내부)"]
            styled = (
                frame.style.format({c: "{:,}" for c in num_cols})
                .set_properties(subset=num_cols, **{"text-align": "right"})
                .set_properties(subset=internal, **{"background-color": "#c8c8c8"})
            )
            show_table(styled, width="stretch", hide_index=True)
            if q.missing_charges:
                st.caption(f"요율이 없는 항목: {', '.join(q.missing_charges)}")

        with st.container(border=True):
            st.markdown("**출력**")
            memo_text = st.session_state.get("q_memo", "")
            sig = (customer, pol, pod, container, qty, issue_date.isoformat(), str(margin), q.carrier, memo_text, reason)
            saved = st.session_state.get("q_saved")
            already = saved is not None and saved["sig"] == sig

            c1, c2, c3 = st.columns(3)
            if c1.button(
                "견적 저장",
                type="primary",
                disabled=already,
                help="이 조건은 이미 저장했어요. 조건을 바꾸면 다시 저장할 수 있어요." if already else None,
                width="stretch",
            ):
                quote_no = quotes.save_quote(conn, req, q, customer, memo_text, reason)
                st.session_state["q_saved"] = {"sig": sig, "no": quote_no}
                st.rerun()  # 다시 그려서 저장 버튼이 바로 비활성이 되게 한다 (중복 저장 방지)

            if already:
                st.success(f"견적번호 {saved['no']}로 저장했어요.")
            else:
                st.caption("저장하면 견적번호가 붙고, 그 다음 PDF를 만들 수 있어요.")

            confirmed = not warns or st.session_state.get("q_confirm", False)
            if not already:
                pdf_help = "PDF는 먼저 견적을 저장한 뒤에 만들 수 있어요."
            elif not confirmed:
                pdf_help = "경고 내용을 확인 체크해야 PDF를 만들 수 있어요."
            else:
                pdf_help = None
            pdf_ready = already and confirmed
            quote_doc = quotes.load_quote(conn, saved["no"]) if already else None
            c2.download_button(
                "내부용 PDF",
                data=pdf_quote.to_pdf(pdf_quote.internal_html(quote_doc)) if pdf_ready else b"",
                file_name=f"{saved['no'] if already else 'quote'}_내부용.pdf",
                mime="application/pdf",
                disabled=not pdf_ready,
                help=pdf_help,
                width="stretch",
                key="dl_internal",
            )
            c3.download_button(
                "고객용 PDF",
                data=pdf_quote.to_pdf(pdf_quote.customer_html(quote_doc)) if pdf_ready else b"",
                file_name=f"{saved['no'] if already else 'quote'}_고객용.pdf",
                mime="application/pdf",
                disabled=not pdf_ready,
                help=pdf_help,
                width="stretch",
                key="dl_customer",
            )
