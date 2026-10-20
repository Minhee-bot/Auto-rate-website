"""지명 변환표: 한글/약칭 → 영어 정식 지명.

- 저장된 pricing 원본 값은 바꾸지 않는다. 화면 표시와 조회 시에만 변환한다.
- 한글로 들어온 값('부산')도 같은 지명(Busan)으로 조회되도록 원본 형태 목록(raw_forms)을 만든다.
- 변환표에 없는 지명은 원본 그대로 두고, 업로드 검수에서 '영어 지명 미등록'으로 알린다.
"""

from __future__ import annotations

# 영어 정식 지명 -> 입력으로 인정할 다른 표기들 (정식 지명 자신은 자동 포함)
PLACE_ALIASES: dict[str, list[str]] = {
    "Busan": ["부산"],
    "Los Angeles": ["LA", "로스앤젤레스"],
    "Rotterdam": ["로테르담"],
    "Hamburg": ["함부르크"],
    "Singapore": ["싱가포르"],
    "Sydney": ["시드니"],
}

_LOOKUP: dict[str, str] = {}
for _en, _aliases in PLACE_ALIASES.items():
    for _name in [_en, *_aliases]:
        _LOOKUP[_name.casefold()] = _en


def canonical(name: str | None) -> str | None:
    """입력 지명을 영어 정식 지명으로. 변환표에 없으면 None."""
    if not name:
        return None
    return _LOOKUP.get(name.strip().casefold())


def display(name: str) -> str:
    """화면 표시용. 변환표에 없으면 원본 그대로."""
    return canonical(name) or name


def raw_forms(name: str) -> list[str]:
    """DB에 들어 있을 수 있는 모든 표기. SQL의 IN 조건에 쓴다."""
    en = canonical(name)
    if en is None:
        return [name]
    return [en, *PLACE_ALIASES[en]]


def is_registered(name: str) -> bool:
    return canonical(name) is not None
