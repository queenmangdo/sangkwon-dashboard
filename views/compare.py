"""상권 비교 (메인)."""
from __future__ import annotations

import streamlit as st

from core import config as C
from core import state
from core.engine import baseline, compute, fmt_ym, is_total, latest, major_counts, values_for, window
from core.factors import factors_for, highlights
from core.geo import info
from core.ui import esc, factor_box, go, label, section
from views.picker import mini_map, picker
from views.rows import RENDER, Ctx

ss = st.session_state
major, middle = ss.major, ss.middle
total = is_total(middle)
industry = major if total else middle
slots = ss.slots
cids = [c for _, c in state.selected()]
win = window()
base = baseline(major, middle)
vals = values_for(major, middle, cids)
m = compute(major, middle)

# ------------------------------------------------------------------ 제목 + 요인 카드
st.html(f'<div class="sk-h2">고른 상권 — {esc(industry)}</div>')
factors, note = factors_for(major, middle)
factor_box(major, middle, factors, note)
if m.empty:
    st.info(f"'{industry}' 업종의 상권 데이터가 아직 없어요. 데이터에 해당 행이 추가되면 채워져요.")

# ------------------------------------------------------------------ 머리글 + 지도(선택) 행
heads = "".join(go(f'<div class="sk-head">상권 {state.letter(i)} ›</div>', state.detail_href(c)) if c is not None
                else f'<div class="sk-head off">상권 {state.letter(i)}</div>' for i, c in enumerate(slots))
st.html(f'<div class="sk-grid" style="margin-bottom:6px"><div class="sk-head">후보 상권</div>{heads}</div>')

H = 250
cols = st.columns([1.15] + [2] * len(slots), gap="small")
with cols[0]:
    st.html(label("상권 지도", "상권을 1~3곳 고르기").replace('class="sk-label"', f'class="sk-label" style="min-height:{H}px"'))
for i, cid in enumerate(slots):
    with cols[i + 1]:
        with st.container(border=True, height=H, key=f"slotbox_{i}"):
            if cid is None:
                st.html('<div style="height:62px"></div>')
                if st.button("＋ 상권을 선택해주세요!", key=f"add_{i}", use_container_width=True):
                    picker(i)
                st.caption("검색하거나 지도에서 상권을 눌러 골라요")
            else:
                n = int(m["stores_latest"].get(cid, 0)) if not m.empty else None
                mini_map(cid, n, industry, height=168)
                b1, b2 = st.columns(2, gap="small")
                if b1.button("변경", key=f"chg_{i}", use_container_width=True):
                    picker(i)
                if b2.button("삭제", key=f"del_{i}", use_container_width=True):
                    state.clear_slot(i)
                    st.rerun()

if not cids:
    st.caption("지도 칸에서 비교할 상권을 1곳 이상 골라주세요. 고르면 아래 항목이 채워져요.")

# ------------------------------------------------------------------ 비교 행 (config/items.yaml)
stores = {c: (vals[c].get("stores_latest", 0) if vals.get(c) else 0) for c in cids}
names = {c: info(c).get("_label", str(c)) for c in cids}
hl = highlights(factors, {c: vals[c] for c in cids}, stores, base, f"{major} > {industry}", names) if cids else {}
ctx = Ctx(slots=slots, vals=vals, base=base, industry=industry, is_total=total, major=major,
          major_counts=major_counts(major), factors=factors, factor_note=note, hl=hl)
for sec in C.items()["sections"]:
    section(sec["title"])
    for spec in sec["rows"]:
        RENDER[spec["type"]](spec, ctx)

T = C.S("highlight_T", 5)
foot = "".join(f"<li>{esc(t.replace('{T}', str(T)))}</li>" for t in C.items().get("footnotes", []))
st.html(f'<div class="sk-foot"><ul>{foot}</ul></div>')
