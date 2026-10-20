"""견적 예외 처리 (기획서 7장 1~10번).

판정 기준(언제 막고, 언제 경고하고, 언제 알리는지)은 기존과 같다.
안내 문구는 '무슨 일 → 왜 → 지금 할 수 있는 것' 순서의 해요체이며,
다음 행동 버튼은 Issue.actions로 함께 넘긴다.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass, field

from autorate import places
from autorate.calculator import CarrierQuote, QuoteRequest
from autorate.margin_import import normalize_name

# 행동 키: "upload" 요율 업로드 화면, "container:XXX" 컨테이너 변경, "issue_date", "pod"(안내만)
UPLOAD = "upload"


@dataclass
class Issue:
    level: str  # "block"(빨강: 진행 불가) | "warn"(주황: 확인 후 진행) | "info"(파랑: 참고)
    message: str
    actions: list[tuple[str, str]] = field(default_factory=list)  # (버튼 이름, 행동 키)


def _pols_canonical(conn: sqlite3.Connection) -> list[str]:
    raws = [r[0] for r in conn.execute("SELECT DISTINCT pol FROM pricing")]
    return sorted({places.display(r) for r in raws})


def route_pols(conn: sqlite3.Connection) -> list[str]:
    return _pols_canonical(conn)


def route_pods(conn: sqlite3.Connection, pol: str) -> list[str]:
    raws = places.raw_forms(pol)
    rows = conn.execute(
        f"SELECT DISTINCT pod FROM pricing WHERE pol IN ({','.join('?' * len(raws))})", raws
    ).fetchall()
    return sorted({places.display(r[0]) for r in rows})


def route_containers(conn: sqlite3.Connection, pol: str, pod: str) -> list[str]:
    """구간에 실제 존재하는 컨테이너만 (7장 2번)."""
    pols = places.raw_forms(pol)
    pods = places.raw_forms(pod)
    rows = conn.execute(
        f"SELECT DISTINCT container FROM pricing WHERE pol IN ({','.join('?' * len(pols))}) "
        f"AND pod IN ({','.join('?' * len(pods))}) ORDER BY container",
        (*pols, *pods),
    ).fetchall()
    return [r[0] for r in rows]


def diagnose_empty(conn: sqlite3.Connection, req: QuoteRequest) -> list[Issue]:
    """견적 후보가 하나도 없을 때 이유를 설명한다 (7장 1·2·3번)."""
    pols = places.raw_forms(req.pol)
    pods = places.raw_forms(req.pod)
    route = conn.execute(
        f"SELECT * FROM pricing WHERE pol IN ({','.join('?' * len(pols))}) "
        f"AND pod IN ({','.join('?' * len(pods))})",
        (*pols, *pods),
    ).fetchall()
    pol, pod = places.display(req.pol), places.display(req.pod)
    if not route:
        return [
            Issue(
                "block",
                f"{pol} → {pod} 구간은 등록된 요율이 없어 견적을 만들 수 없어요. "
                "요율 파일을 업로드하거나 다른 도착지를 선택해 주세요.",
                [("요율 업로드하기", UPLOAD), ("다른 도착지 선택", "pod")],
            )
        ]

    same = [r for r in route if r["container"] == req.container]
    if not same:
        containers = sorted({r["container"] for r in route})
        return [
            Issue(
                "block",
                f"{pod}은 현재 {', '.join(containers)} 요율만 있어요. "
                f"{containers[0]}로 바꾸면 바로 계산할 수 있어요.",
                [(f"{c}로 변경", f"container:{c}") for c in containers[:2]],
            )
        ]

    iso = req.issue_date.isoformat()
    valid = [r for r in same if r["valid_from"] <= iso <= r["valid_to"]]
    if not valid:
        latest_end = max(dt.date.fromisoformat(r["valid_to"]) for r in same)
        earliest_start = min(dt.date.fromisoformat(r["valid_from"]) for r in same)
        if latest_end < req.issue_date:
            return [
                Issue(
                    "block",
                    f"{pod} {req.container} 요율이 {latest_end.isoformat()}에 만료됐어요. "
                    "새 요율을 업로드하면 견적을 만들 수 있어요.",
                    [("요율 업로드하기", UPLOAD)],
                )
            ]
        return [
            Issue(
                "block",
                f"견적일 {iso}에 맞는 {pod} {req.container} 요율이 없어요 "
                f"(저장된 기간 {earliest_start}~{latest_end}). 견적일을 바꾸거나 요율을 업로드해 주세요.",
                [("견적일 바꾸기", "issue_date"), ("요율 업로드하기", UPLOAD)],
            )
        ]

    if not any(r["charge"] == "Ocean Freight" for r in valid):
        return [
            Issue(
                "block",
                f"{pod} 구간에 해상운임(Ocean Freight) 요율이 없어 견적을 만들 수 없어요. "
                "운임 요율을 업로드해 주세요.",
                [("요율 업로드하기", UPLOAD)],
            )
        ]
    return []


def quote_warnings(q: CarrierQuote, req: QuoteRequest) -> list[Issue]:
    """선택된 선사 견적의 경고 (7장 4·6·10번)."""
    if q.blocked_reason:
        return [
            Issue(
                "block",
                f"{q.carrier}은 같은 항목의 유효 기간이 겹쳐 있어 계산할 수 없어요 "
                f"({q.blocked_reason.split(': ', 1)[-1]}). 요율 파일에서 기간을 정리해 주세요.",
                [("요율 업로드하기", UPLOAD)],
            )
        ]

    issues = []
    if q.missing_charges:
        issues.append(
            Issue(
                "warn",
                f"{', '.join(q.missing_charges)} 요율이 없어요. "
                "확인 후 진행을 체크하면 출력할 수 있어요.",
                [("요율 업로드하기", UPLOAD)],
            )
        )
    if q.shortened:
        issues.append(
            Issue("info", f"요율 종료일에 맞춰 견적 유효기간이 {q.valid_until.isoformat()}까지로 줄었어요.")
        )
    if req.margin_pct <= 0:
        issues.append(Issue("warn", "마진이 0% 이하예요. 내용을 확인하고 체크하면 PDF를 만들 수 있어요."))
    if q.profit < 0:
        issues.append(
            Issue("warn", "이 견적은 Profit이 마이너스예요. 내용을 확인하고 체크하면 PDF를 만들 수 있어요.")
        )
    return issues


def similar_customers(conn: sqlite3.Connection, name: str) -> list[str]:
    """마진표 고객 중 표기만 다른 후보 (7장 8번). 자동 매칭은 하지 않는다."""
    target = normalize_name(name)
    if not target:
        return []
    names = [r[0] for r in conn.execute("SELECT DISTINCT customer_name FROM customer_margin")]
    out = []
    for n in sorted(names):
        m = normalize_name(n)
        if n != name and m and (m == target or m in target or target in m):
            out.append(n)
    return out
