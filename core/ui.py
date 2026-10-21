"""화면 조각. 스타일 값은 design/theme.css 에만 둔다."""
from __future__ import annotations

import base64
import html as _h
import math
import numbers

import streamlit as st

from .config import APP

INDIGO = "#2D2A84"


def inject_css() -> None:
    st.html(f"<style>{(APP / 'design' / 'theme.css').read_text(encoding='utf-8')}</style>")


def esc(s) -> str:
    return _h.escape("" if s is None else str(s))


def isnum(v) -> bool:
    return isinstance(v, numbers.Real) and not isinstance(v, bool) and not math.isnan(float(v))


def num(v, scale: float = 1, d: int | None = None) -> str:
    if not isnum(v):
        return "–"
    x = v / scale
    if d is None:
        d = 1 if abs(x) < 100 and scale != 1 else 0
    return f"{x:,.{d}f}"


# ------------------------------------------------------------------ 격자
def section(title: str) -> None:
    st.html(f'<div class="sk-section">{esc(title)}</div>')


def label(title: str, sub: str = "", hl: bool = False, wip: bool = False) -> str:
    key = '<span class="tag-key">핵심 요약</span>' if hl else ""
    w = '<span class="tag-wip">데이터 확보 시</span>' if wip else ""
    return f'<div class="sk-label{" hl" if hl else ""}">{key}<b>{esc(title)}</b><span>{sub}</span>{w}</div>'


def row(label_html: str, cells: list[str]) -> None:
    st.html(f'<div class="sk-grid">{label_html}{"".join(cells)}</div>')


def cell(inner: str, hl: bool = False) -> str:
    return f'<div class="sk-cell{" hl" if hl else ""}">{inner}</div>'


def empty(text: str = "–") -> str:
    return f'<div class="sk-cell empty">{esc(text)}</div>'


def tag(text: str, kind: str = "top") -> str:
    return f'<span class="sk-tag {kind}">{esc(text)}</span>'


def bars(mine, base, vmax, base_text: str) -> str:
    vmax = vmax or 1
    w1 = max(2, min(100, mine / vmax * 100)) if isnum(mine) else 0
    w2 = max(2, min(100, base / vmax * 100)) if isnum(base) else 0
    return (f'<div class="sk-bar"><i style="width:{w1 * .6:.0f}%;background:var(--indigo)"></i>이 상권</div>'
            f'<div class="sk-bar"><i style="width:{w2 * .6:.0f}%;background:var(--bar-base)"></i>{base_text}</div>')


# ------------------------------------------------------------------ 요인 카드
def curve_img(kind: str) -> str:
    paths = {"up": "M4 30 C 30 27, 55 18, 88 6", "down": "M4 6 C 30 10, 55 21, 88 30", "hill": "M4 30 C 25 2, 65 2, 88 30"}
    if kind not in paths:
        return '<div style="height:36px"></div>'
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="92" height="36" viewBox="0 0 92 36">'
           f'<line x1="4" y1="33" x2="88" y2="33" stroke="#D5D5E0"/>'
           f'<path d="{paths[kind]}" fill="none" stroke="{INDIGO}" stroke-width="2"/></svg>')
    return f'<img alt="" src="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}"/>'


def band_html(f) -> str:
    """좋은 구간 띠: 눈금 위에 매출이 가장 높은 구간을 칠함. 0/1 변수는 '안 함 / 함' 두 칸. 띠 값이 없으면 곡선 아이콘"""
    if f.confirmed and f.shape == "binary":
        return ('<div class="sk-band bin"><div class="cells"><span>안 함</span><span class="on">함</span></div>'
                '<div class="ax"><span>매출이 더 높은 쪽</span></div></div>')
    if not f.band:
        return curve_img(f.curve)
    a, z, lo, hi = f.band
    pos = lambda v: max(0.0, min(100.0, (v - a) / (z - a) * 100))
    left, right = pos(lo), pos(hi)
    mid = min(max((left + right) / 2, 18), 82)          # 글자가 카드 밖으로 안 나가게
    return (f'<div class="sk-band"><div class="lab" style="left:{mid:.0f}%">{esc(f.band_label)}</div>'
            f'<div class="track"><i style="left:{left:.0f}%;width:{max(right - left, 3):.0f}%"></i></div>'
            f'<div class="ax"><span>{esc(f.fmt(a))}</span><span>{esc(f.fmt(z))}</span></div></div>')


def factor_box(major: str, middle: str, factors, note: str) -> None:
    head = (f'<h3>선택하신 <span class="sk-chip">{esc(major)}</span><span class="sk-chip">{esc(middle)}</span>'
            f' 업종은 아래 {len(factors) or 5}가지 항목을 눈여겨보는 게 좋아요!</h3>'
            f'<div class="sk-cap">서울 {esc(middle)} 가게들의 매출을 분석해, 매출과 관계가 큰 순서대로 골랐어요. '
            f'업종을 바꾸면 {len(factors) or 5}가지 항목도 바뀌어요.</div>')
    if not factors:
        st.html(f'<div class="sk-fbox">{head}<div class="sk-empty-box">{esc(note)}</div></div>')
        return
    cards = []
    for f in factors:
        rel = f'<div>{esc(f.relation)}</div>' if f.confirmed else '<div class="na">관계 확인 불가</div>'
        cards.append(f'<div class="sk-fcard"><span class="n">{f.rank}</span><div class="t">{esc(f.name)}</div>'
                     f'{band_html(f)}<div class="k">어떤 값이에요</div><div>{esc(f.definition)}</div>'
                     f'<div class="k">매출과의 관계</div>{rel}</div>')
    warn = f'<div class="sk-warn">{esc(note)}</div>' if note else ""
    st.html(f'<div class="sk-fbox">{head}<div class="sk-fgrid" style="grid-template-columns:repeat({len(cards)},1fr)">'
            f'{"".join(cards)}</div>{warn}<div class="sk-fnote">모델이 찾은 관계예요. 모델은 틀릴 수 있어요.</div></div>')
