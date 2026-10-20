"""Auto - Rate 운임 계산기.

실행: python -m streamlit run app.py
메뉴: 자료 관리 / 새 견적 / 복사 견적 / 견적 이력 (사이드바에 고정)
"""

import datetime as dt
import html
from decimal import Decimal, InvalidOperation
from io import BytesIO

import pandas as pd
import streamlit as st

from autorate import margin_import as mi
from autorate import pricing_import as pi
from autorate import quote_page, quotes
from autorate.ui import show_table
from autorate.db import connect

APP_NAME = "Auto - Rate"
st.set_page_config(page_title=APP_NAME, layout="wide")

# 디자인 시스템(Editorial Index): 회색 바탕, 1px 선, 라임은 대표 칸만, 둥근 모서리·그림자·볼드 없음
THEME_CSS = """
<style>
:root {
  --surface: #ebebeb;
  --surface-accent: #eeffd0;
  --ink: #000000;
  --ink-muted: #4a4a4a;
  --ink-on-accent: #000000;
  --line: #000000;
  --error: #b8402a;
  --warning: #f2c230;
  --success: #2f6f6a;
  --on-success: #ebebeb;
  --on-error: #ebebeb;
  --focus-ring: #000000;
  --media-placeholder: #c8c8c8;
}
@import url("https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@300;400&family=Gowun+Dodum&family=Gowun+Batang&family=Libertinus+Mono&display=swap");

html, body, .stApp, .stApp p, .stApp label, .stApp li, .stApp input, .stApp textarea, .stApp button {
  font-family: "Hanken Grotesk", "Gowun Dodum", system-ui, sans-serif;
  font-weight: 300;
}
.stApp { background: var(--surface); color: var(--ink); }
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { font-weight: 300; color: var(--ink); letter-spacing: -0.01em; }
/* 강조는 밑줄만 (볼드 금지) */
.stApp strong, .stApp b { font-weight: 300; text-decoration: underline; text-underline-offset: 3px; }
.stApp a { color: var(--ink); text-decoration: underline; text-underline-offset: 3px; }
header[data-testid="stHeader"] { background: var(--surface); }

[data-testid="stSidebar"] { background: var(--surface); border-right: 1px solid var(--line); }
/* 캡션·보조 설명은 산세리프 (README: 세리프 모노는 태그 전용) */
[data-testid="stCaptionContainer"] { font-family: "Hanken Grotesk", "Gowun Dodum", system-ui, sans-serif; font-weight: 300; color: var(--ink-muted); }

[data-testid^="stBaseButton"] {
  border: 1px solid var(--line) !important;
  border-radius: 0 !important;
  background: transparent !important;
  color: var(--ink) !important;
  box-shadow: none !important;
  font-weight: 400 !important;
}
[data-testid^="stBaseButton"]:disabled { opacity: 0.4; }

[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {
  border-radius: 0 !important;
  border-color: var(--line) !important;
  background: transparent !important;
}
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea { background: transparent !important; }
/* 모든 테두리는 검정 실선: 기본값이 반투명 회색이거나 바탕색과 같은 곳도 전부 덮어쓴다 */
[data-testid="stVerticalBlock"], [data-testid="stSidebarNavSeparator"], [data-testid="stDataFrameResizable"], [data-testid="stDataFrame"] {
  border-color: var(--line) !important;
}
[data-testid="stDateInputField"] { border: 1px solid var(--line) !important; border-radius: 0 !important; }
/* 입력칸 실선: Streamlit 입력 래퍼 div에 1px 실선 (래퍼 기본 테두리는 배경색과 같아서 안 보임) */
[data-testid="stTextInput"] div:has(> input),
[data-testid="stNumberInput"] div:has(> input),
[data-testid="stDateInput"] div:has(> input),
[data-testid="stSelectbox"] div:has(> input),
[data-testid="stTextArea"] div:has(> textarea) {
  border: 1px solid var(--line) !important;
  border-radius: 0 !important;
  background: transparent !important;
}

[data-testid="stVerticalBlockBorderWrapper"] > div { border-radius: 0 !important; border-color: var(--line) !important; }
[data-testid="stMetric"] { border: 1px solid var(--line); padding: 12px 14px; }
[data-testid="stMetricLabel"] { color: var(--ink-muted); }
[data-testid="stAlert"] { border-radius: 0 !important; border: 1px solid var(--line) !important; background: transparent !important; }
/* 알림 상자: 기본은 회색 바탕 + 검정 글자(파랑 금지). 상태색은 디자인 시스템의 Notice 색 */
[data-testid="stAlertContainer"] { background: var(--surface) !important; border: 1px solid var(--line) !important; border-radius: 0 !important; }
[data-testid="stAlertContainer"] p, [data-testid="stAlertContainer"] svg { color: var(--ink) !important; fill: var(--ink) !important; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) { background: var(--warning) !important; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) { background: var(--error) !important; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) p,
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) svg { color: var(--on-error) !important; fill: var(--on-error) !important; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) { background: var(--success) !important; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) p,
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) svg { color: var(--on-success) !important; fill: var(--on-success) !important; }
[data-testid="stExpander"] { border: 1px solid var(--line) !important; border-radius: 0 !important; background: transparent; }
/* 표 테두리는 안쪽 stDataFrameResizable 하나만 (바깥 래퍼에도 두면 선이 두 겹으로 겹쳐 보임) */
[data-testid="stDataFrame"] { border: none; border-radius: 0; }
/* 정적 표(show_table): 헤더 행 라임, 칸 사이 1px 검정 선, 상자 가로 스크롤 */
[data-testid="stTable"] { border: 1px solid var(--line); overflow-x: auto; }
[data-testid="stTable"] table { border-collapse: collapse; width: 100%; font-weight: 300; color: var(--ink); }
[data-testid="stTable"] th { background: var(--surface-accent) !important; font-weight: 400; text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
[data-testid="stTable"] td { padding: 7px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
[data-testid="stTable"] tr:last-child td { border-bottom: none; }
[data-testid="stTable"] th *, [data-testid="stTable"] td * { white-space: nowrap !important; }
/* 스타일이 입혀진 표(Styler)는 테스트 ID가 stTableStyledTable이라 접두어로 한 번 더 잡는다 */
[data-testid^="stTable"] table { border-collapse: collapse; width: 100%; font-weight: 300; color: var(--ink); }
[data-testid^="stTable"] th, [data-testid^="stTable"] th * { color: var(--ink-on-accent) !important; }
[data-testid^="stTable"] th { background: var(--surface-accent) !important; font-weight: 400; text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
[data-testid^="stTable"] td { padding: 7px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
[data-testid^="stTable"] tr:last-child td { border-bottom: none; }
[data-testid^="stTable"] th + th, [data-testid^="stTable"] td + td { border-left: 1px solid var(--line); }
[data-testid="stTable"] th + th, [data-testid="stTable"] td + td { border-left: 1px solid var(--line); }
[data-testid="stDataFrameResizable"] { border-radius: 0 !important; }

[data-baseweb="tab-list"] { border-bottom: 1px solid var(--line); gap: 0; }
[data-baseweb="tab"] { border-radius: 0 !important; font-weight: 300; color: var(--ink-muted) !important; }
[data-baseweb="tab"][aria-selected="true"] { color: var(--ink) !important; }
[data-baseweb="tab-highlight"] { background: var(--ink) !important; }
[data-baseweb="tab-border"] { display: none; }

:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }

/* 견적 이력 표: 헤더 행은 라임, 칸 사이 1px 검정 선 */
.hl-table-wrap { overflow-x: auto; border: 1px solid var(--line); }
.hl-table { border-collapse: collapse; width: 100%; font-size: 13px; font-weight: 300; color: var(--ink); }
.hl-table th { background: var(--surface-accent); font-weight: 400; text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.hl-table td { padding: 7px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.hl-table tr:last-child td { border-bottom: none; }
.hl-table th + th, .hl-table td + td { border-left: 1px solid var(--line); }

.hl-brand {
  background: var(--surface-accent);
  border: 1px solid var(--line);
  padding: 14px 16px;
  margin-bottom: 12px;
  font-size: 22px;
  font-weight: 300;
  color: var(--ink-on-accent);
  letter-spacing: -0.01em;
}
</style>
"""
st.markdown(THEME_CSS, unsafe_allow_html=True)
conn = connect()
today = dt.date.today()


def _row_style(row):
    status = row["상태"]
    if status == "오류":
        return ["background-color: #fde2e1"] * len(row)
    if status == "만료":
        return ["color: #9ca3af"] * len(row)
    return [""] * len(row)


def _pricing_frame(rows):
    return pd.DataFrame(
        [
            {
                "행": r.row_no,
                "선사": r.carrier,
                "POL": r.pol,
                "POD": r.pod,
                "컨테이너": r.container,
                "항목": r.charge,
                "구분": r.charge_type,
                "단위": r.unit,
                "Cost": float(r.cost) if r.cost is not None else None,
                "유효시작": r.valid_from,
                "유효종료": r.valid_to,
                "상태": pi.status_of(r, today),
                "오류 내용": ", ".join(r.errors),
            }
            for r in rows
        ]
    )


# ── 자료 관리 ───────────────────────────────────────────
def page_data():
    st.markdown("### 자료 관리")
    tab_pricing, tab_margin = st.tabs(["Pricing 요율", "고객 마진표"])

    with tab_pricing:
        st.subheader("pricing 엑셀 업로드")
        upload = st.file_uploader("pricing 파일 (.xlsx)", type=["xlsx"], key="pricing_file")

        if upload is not None:
            parsed = pi.parse_pricing(BytesIO(upload.getvalue()))
            if parsed.file_errors:
                for err in parsed.file_errors:
                    st.error(err)
            else:
                plan = pi.build_plan(parsed, conn)
                rows = plan.rows
                invalid = plan.invalid_rows
                statuses = [pi.status_of(r, today) for r in rows]

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("전체 행", len(rows))
                c2.metric("정상", statuses.count("정상") + statuses.count("예정"))
                c3.metric("만료 (회색)", statuses.count("만료"))
                c4.metric("오류 (빨강)", len(invalid))

                show_table(
                    _pricing_frame(rows).style.apply(_row_style, axis=1),
                    width="stretch",
                    hide_index=True,
                )

                unregistered = pi.unregistered_places(rows)
                if unregistered:
                    names = ", ".join(f"{n}행 '{name}'" for n, name in unregistered[:10])
                    st.info(
                        f"영어 지명 미등록 {len(unregistered)}건: {names}. "
                        "지명 변환표에 없어서 원래 표기 그대로 보여요. 저장은 할 수 있어요."
                    )
                if invalid:
                    st.warning(
                        f"오류가 있는 {len(invalid)}행은 빼고 저장할 수 있어요. "
                        "엑셀에서 고쳐서 다시 올리면 모두 저장돼요."
                    )
                if plan.changed:
                    with st.expander(f"변경된 요율 미리보기 ({len(plan.changed)}건)"):
                        show_table(
                            pd.DataFrame(
                                [
                                    {
                                        "행": r.row_no,
                                        "선사": r.carrier,
                                        "POL → POD": f"{r.pol} → {r.pod}",
                                        "컨테이너": r.container,
                                        "항목": r.charge,
                                        "이전 Cost": float(old["cost"]),
                                        "새 Cost": float(r.cost),
                                        "이전 유효종료": old["valid_to"],
                                        "새 유효종료": r.valid_to,
                                    }
                                    for r, old in plan.changed
                                ]
                            ),
                            width="stretch",
                            hide_index=True,
                        )

                skip = st.checkbox(
                    "오류 행은 빼고 정상 행만 저장할게요",
                    value=False,
                    disabled=not invalid,
                    key="skip_invalid",
                )
                can_save = not invalid or skip
                if st.button(
                    "저장 (기존 자료에 병합)",
                    type="primary",
                    disabled=not can_save,
                    help=None if can_save else "오류 행을 빼고 저장하려면 위 체크박스를 켜 주세요.",
                ):
                    uploaded_at = dt.datetime.now().isoformat(timespec="seconds")
                    result = pi.save_plan(
                        conn, plan, source_file=upload.name, uploaded_at=uploaded_at, skip_invalid=skip
                    )
                    st.success(
                        f"저장 완료: 신규 {result['inserted']}건 · 변경 {result['updated']}건 · "
                        f"동일 {result['unchanged']}건 · 제외 {result['skipped_invalid']}건"
                    )

        st.divider()
        st.subheader("저장된 요율")
        stored = pi.load_stored(conn)
        if not stored:
            st.info("아직 저장된 요율이 없어요. 위에서 pricing 파일을 올려 주세요.")
        else:
            only_valid = st.checkbox(f"유효한 요율만 (기준일 {today.isoformat()})", value=False)
            frame = pd.DataFrame(stored)
            if only_valid:
                frame = frame[
                    (frame["valid_from"] <= today.isoformat()) & (frame["valid_to"] >= today.isoformat())
                ]
            st.caption(f"{len(frame)}건 표시 / 전체 {len(stored)}건")
            show_table(
                frame[["rate_id", "carrier", "pol", "pod", "container", "charge", "unit",
                       "cost", "valid_from", "valid_to", "source_file", "uploaded_at"]],
                width="stretch",
                hide_index=True,
            )

    with tab_margin:
        st.subheader("고객 마진표 업로드")
        m_upload = st.file_uploader("마진표 파일 (.xlsx)", type=["xlsx"], key="margin_file")
        if m_upload is not None:
            m_rows, m_errors = mi.parse_margin(BytesIO(m_upload.getvalue()))
            if m_errors:
                for err in m_errors:
                    st.error(err)
            else:
                show_table(
                    pd.DataFrame(
                        [
                            {
                                "행": r.row_no,
                                "고객명": r.customer_name,
                                "마진(%)": float(r.margin_pct) if r.margin_pct is not None else None,
                                "적용시작일": r.effective_from,
                                "비고": r.remark,
                                "오류 내용": ", ".join(r.errors),
                            }
                            for r in m_rows
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )
                m_invalid = [r for r in m_rows if not r.is_valid]
                if m_invalid:
                    st.warning(f"오류가 있는 {len(m_invalid)}행은 빼고 저장돼요.")
                if st.button("마진표 저장", type="primary", key="save_margin"):
                    result = mi.save_margins(conn, m_rows)
                    st.success(f"저장 완료: 신규 {result['inserted']}건 · 갱신 {result['updated']}건")

        st.divider()
        st.subheader("직접 입력 (마진표에 없는 고객)")
        with st.form("manual_margin"):
            name = st.text_input("고객명 *")
            pct_text = st.text_input("마진 (%) *", placeholder="예: 7")
            eff = st.date_input("적용시작일 *", value=today)
            remark = st.text_input("비고 (선택)")
            submitted = st.form_submit_button("마진표에 저장")
        if submitted:
            try:
                pct = Decimal(pct_text.replace("%", "").strip())
            except InvalidOperation:
                st.error("마진%는 숫자로 입력해 주세요.")
            else:
                if not name.strip():
                    st.error("고객명을 입력해 주세요.")
                else:
                    mi.add_manual_margin(conn, name, pct, eff, remark)
                    st.success(f"{name.strip()} 마진 {pct}% 저장 완료")

        margins = mi.load_margins(conn)
        st.subheader("저장된 마진표")
        if margins:
            show_table(pd.DataFrame(margins), width="stretch", hide_index=True)
        else:
            st.info("저장된 마진표가 없어요.")


# ── 새 견적 / 복사 견적 / 견적 이력 ──────────────────────
def page_quote():
    quote_page.render(conn, today, data_page)


def page_copy():
    st.markdown("### 복사 견적")
    st.info("복사 견적은 아직 준비 중이에요. 5단계에서 이어서 만들어요.")
    st.button("복사 견적 시작", disabled=True, help="복사 견적은 5단계에서 연결돼요.")


def _html_table(frame: pd.DataFrame) -> str:
    """헤더 행 색을 바꿀 수 있도록 st.dataframe 대신 HTML 표로 그린다 (줄바꿈 없이 한 줄로)."""
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in frame.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row) + "</tr>"
        for row in frame.itertuples(index=False)
    )
    return (
        f'<div class="hl-table-wrap"><table class="hl-table">'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def page_history():
    st.markdown("### 견적 이력")
    saved = quotes.list_quotes(conn)
    if not saved:
        st.info("아직 저장한 견적이 없어요. 새 견적에서 저장해 보세요.")
        return
    st.markdown(_html_table(
        pd.DataFrame(
            [
                {
                    "견적번호": q["quote_no"],
                    "발행일": q["issue_date"],
                    "유효기간": q["valid_until"],
                    "고객": q["customer_name"],
                    "구간": f"{q['pol']} → {q['pod']}",
                    "컨테이너": f"{q['container']} × {q['qty']}",
                    "Sales (USD)": int(float(q["total_sales"])),
                    "Cost (USD, 내부)": int(float(q["total_cost"])),
                    "Profit (USD, 내부)": int(float(q["profit"])),
                    "저장 시각": q["saved_at"],
                }
                for q in saved
            ]
        )
    ), unsafe_allow_html=True)


# ── 사이드바 메뉴 (항상 보이게 고정) ─────────────────────
data_page = st.Page(page_data, title="자료 관리", url_path="data")
quote_pg = st.Page(page_quote, title="새 견적", url_path="quote", default=True)
copy_pg = st.Page(page_copy, title="복사 견적", url_path="copy")
history_pg = st.Page(page_history, title="견적 이력", url_path="history")

nav = st.navigation([data_page, quote_pg, copy_pg, history_pg])
st.sidebar.markdown(f'<div class="hl-brand">{APP_NAME}</div>', unsafe_allow_html=True)
nav.run()
