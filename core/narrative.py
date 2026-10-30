"""화면 문장 만들기: 슬롯별 입력(payload)·상황(state)을 정해 LLM 에 보낸다. 지침 문구는 config/llm_prompts.yaml.

각 *_req 함수는 (system, payload) 를 돌려주고, 문장을 쓸 수 없는 상황이면 None 을 돌려준다.
문장은 core.llm.ask_many 로 받고, None 이면 화면에서 자리 표시 문구로 되돌린다.
"""
from __future__ import annotations

import re

import pandas as pd

from . import config as C
from .ui import esc


def _num(v, d=1):
    return None if v is None or pd.isna(v) else round(float(v), d)


def _system(slot: str, state: str) -> str:
    P = C.llm_prompts()
    s = P[slot]
    ex = "\n".join(f"- {e}" for e in s.get("examples", []))
    return (f"{P['common'].strip()}\n\n{s['task'].strip()}\n\n이번 상황({state}): {s['states'][state].strip()}"
            + (f"\n\n문장 예시 (말투·길이만 참고하고 내용은 베끼지 마):\n{ex}" if ex else ""))


def html(text: str) -> str:
    """응답 문장 → 안전한 HTML (**굵게** 만 허용)."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(text.replace("\n", " ")))


# ------------------------------------------------------------------ 상권 비교 · 하이라이트
def highlight_req(h) -> tuple[str, dict] | None:
    """h: core.factors.Highlight"""
    if not h.payload:
        return None
    if h.mode == "compare":
        state = "both" if h.best and h.worst else "best_only" if h.best else "worst_only" if h.worst else None
        return (_system("highlight_compare", state), h.payload) if state else None
    if h.mode == "single":
        p = h.payload
        state = "both" if p["good"] and p["bad"] else "good_only" if p["good"] else "bad_only" if p["bad"] else "all_mid"
        return _system("highlight_single", state), p
    return None


# ------------------------------------------------------------------ 상권 상세
def growth_req(industry: str, compare_label: str, chg: dict, small_sample: bool) -> tuple[str, dict] | None:
    g = {k: _num(chg.get(k)) for k in ("sales", "stores", "sps")}
    if all(v is None for v in g.values()):
        return None
    state = "small_sample" if small_sample else "partial" if any(v is None for v in g.values()) else "normal"
    return _system("growth_headline", state), {"industry": industry, "compare": compare_label, "growth": g}


def when_req(industry: str, compare_label: str, top, largest, weekend) -> tuple[str, dict] | None:
    """top: (이름, 기준, 최근, 변화%p) 또는 None / largest: 같은 형식(가장 큰 시간대) / weekend: (기준, 최근) 또는 None"""
    wk = {"before": _num(weekend[0], 0), "after": _num(weekend[1], 0), "change_pp": _num(weekend[1] - weekend[0], 0)} if weekend else None
    if top:
        nm, b, a, d = top
        return _system("action_when", "changed"), {
            "industry": industry, "compare": compare_label,
            "band": {"name": nm, "before": _num(b, 0), "after": _num(a, 0), "change_pp": _num(d, 0)}, "weekend": wk}
    if largest:
        return _system("action_when", "similar"), {
            "industry": industry, "compare": compare_label,
            "largest_band": {"name": largest[0], "share": _num(largest[2], 0)}, "weekend": wk}
    return None


def who_req(industry: str, compare_label: str, top, largest, sales_change) -> tuple[str, dict] | None:
    sc = _num(sales_change, 0)
    if top:
        nm, b, a, d = top
        state = "changed" if sc is None else "changed_sales_up" if sc >= 0 else "changed_sales_down"
        return _system("action_who", state), {
            "industry": industry, "compare": compare_label,
            "segment": {"name": nm, "before": _num(b, 0), "after": _num(a, 0), "change_pp": _num(d, 0)},
            "sales_change_pct": sc}
    if largest:
        return _system("action_who", "similar"), {
            "industry": industry, "compare": compare_label,
            "largest_segment": {"name": largest[0], "share": _num(largest[2], 0)}}
    return None


def competition_req(industry: str, compare_label: str, chg: dict, factor_name, before, after) -> tuple[str, dict] | None:
    stores, sps = _num(chg.get("stores")), _num(chg.get("sps"))
    if stores is None and sps is None:
        return None
    tf = {"name": factor_name, "before": _num(before, 0), "after": _num(after, 0)} if factor_name else None
    return _system("action_competition", "with_factor" if tf else "no_factor"), {
        "industry": industry, "compare": compare_label,
        "stores_change_pct": stores, "sps_change_pct": sps, "top_factor": tf}
