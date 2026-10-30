"""상권 상세 — 한 상권의 1년 트렌드 (문구·구성: config/detail.yaml)."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from core import config as C
from core import llm as llm_api
from core import narrative, state
from core.engine import compute, fmt_ym, is_total
from core.factors import factors_for
from core.geo import info
from core.loader import area_table
from core.trend import biggest_share_change, compare, monthly, periods, segment_sales_change
from core.sns import cards_html as sns_cards, parse_details, parse_tags
from core.ui import INDIGO, esc, isnum

ss = st.session_state
D = C.detail()
PH = C.S("llm_placeholder", "LLM 한줄 해석 연결 예정")
sel = state.selected()
major, middle = ss.major, ss.middle
industry = major if is_total(middle) else middle

if not sel:
    st.info("먼저 '상권 비교'에서 상권을 1곳 이상 골라주세요.")
    if st.button("상권 비교로 가기", type="primary"):
        st.switch_page(ss._pages["compare"])
    st.stop()


# ------------------------------------------------------------------ 도움 함수
def eul(word: str) -> str:
    """을/를"""
    ch = (word or " ")[-1]
    if "가" <= ch <= "힣":
        return "을" if (ord(ch) - 0xAC00) % 28 else "를"
    return "를"


def fill(t: str, **kw) -> str:
    base = {"업종": industry, "을를": eul(industry), "최근": P.recent_label, "기준": P.base_label}
    base.update(kw)
    for k, v in base.items():
        t = t.replace("{" + k + "}", str(v))
    return t


def pct(v, d=1, sign=True) -> str:
    return "–" if not isnum(v) else (f"{v:+.{d}f}%" if sign else f"{v:.{d}f}%")


def llm(vars_text: str = "", text: str | None = None) -> str:
    """LLM 문장이 있으면 그대로, 없으면 자리 표시 — 어떤 값으로 문장을 만들지 함께 보여줌."""
    if text:
        return narrative.html(text)
    v = f"{esc(vars_text)} — " if vars_text else ""
    return f'<span class="sk-llm-tag">LLM</span><span class="sk-llm">{v}{esc(PH)}</span>'


def sec(no: str, title: str, anchor: str, sub: str = "") -> None:
    s = f'<div class="sk-dsub">{esc(sub)}</div>' if sub else ""
    st.html(f'<div class="sk-dsec" id="{anchor}"><span class="no">{esc(no)}</span>{esc(title)}</div>{s}')


# ------------------------------------------------------------------ 상권 고르기 + 머리말
ids = [c for _, c in sel]
if ss.detail not in ids:
    ss.detail = ids[0]
letter = {c: state.letter(i) for i, c in sel}
cid = ss.detail
P = periods()
r = info(cid)
name = r.get("_name", f"상권 #{cid}")

top_l, top_r = st.columns([3, 2], vertical_alignment="bottom")
with top_l:
    st.html(f'<div class="sk-crumb">상권 비교 / 상권 {letter[cid]}</div>'
            f'<div class="sk-dtitle">{esc(fill(D["title"], 상권=name))}</div>'
            f'<div class="sk-cap">{esc(r.get("_gu", ""))} · {esc(D["subtitle"])}</div>')
with top_r:
    pick = st.segmented_control("상권", ids, default=cid, label_visibility="collapsed", key="detail_pick",
                                format_func=lambda c: f"상권 {letter[c]} · {info(c).get('_name')}")
    if pick is not None and pick != ss.detail:
        ss.detail = pick
        state.sync_url()
        st.rerun()
    st.html(f'<div class="sk-cap" style="text-align:right">분석 기간 {fmt_ym(P.chart[0])}~{fmt_ym(P.chart[-1])} · '
            f'{esc(P.recent_label)} vs {esc(P.base_label)}</div>')

cmp = compare(major, middle, cid)
mon = monthly(major, middle, cid)
m_all = compute(major, middle)
n_latest = int(m_all["stores_latest"].get(cid, 0)) if not m_all.empty else 0
if cmp is None or mon.empty:
    st.info(f"이 상권에는 '{industry}' 데이터가 아직 없어요. 위에서 업종을 바꿔보세요.")
    st.stop()
if n_latest < int(C.S("sample_min_stores", 3)):
    st.html(f'<div class="sk-warn">{esc(fill(D["small_sample"], n=n_latest))}</div>')

# ------------------------------------------------------------------ 01 성장 트렌드
G = D["growth"]
sec(G["num"], G["title"], "sec-01")
chg = cmp["chg"]
headline = llm_api.ask(*req) if (req := narrative.growth_req(
    industry, f"{P.recent_label} vs {P.base_label}", chg, n_latest < int(C.S("sample_min_stores", 3)))) else None
st.html(f'<div class="sk-headline">{llm(f"총매출 {pct(chg["sales"])} · 점포 수 {pct(chg["stores"])} · 점포당 {pct(chg["sps"])}", headline)}</div>')
cards = ""
for k in G["kpis"]:
    v = chg.get(k["key"])
    cls = "pos" if isnum(v) and v >= 0 else "neg"
    cards += (f'<div class="sk-kpi"><div class="t">{esc(fill(k["label"]))}</div>'
              f'<div class="v {cls}">{pct(v)}</div><div class="s">{esc(fill(G["kpi_sub"]))}</div></div>')
st.html(f'<div class="sk-kpis">{cards}</div>')

chart = pd.DataFrame({"월": [fmt_ym(m) for m in mon.index],
                      "매출": mon["sales_idx"].round(0), "점포 수": mon["stores_idx"].round(0)})
long = chart.melt("월", var_name="구분", value_name="지수")
color = alt.Color("구분:N", scale=alt.Scale(domain=["매출", "점포 수"], range=[INDIGO, "#8C89D9"]),
                  legend=alt.Legend(orient="top", title=None))
base = alt.Chart(long).encode(x=alt.X("월:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
                              y=alt.Y("지수:Q", title=None, scale=alt.Scale(zero=False)), color=color)
ch = (base.mark_line(strokeWidth=2.5) + base.mark_circle(size=55)
      + base.mark_text(dy=-11, fontSize=11).encode(text="지수:Q")).properties(height=260)
with st.container(border=True, key="growth_chart"):
    st.html(f'<div class="sk-ctitle">{esc(G["chart_title"])}<span>{esc(G["chart_note"])}</span></div>')
    st.altair_chart(ch, use_container_width=True)

# ------------------------------------------------------------------ 02 소비 트렌드
S = D["consumption"]
sec(S["num"], S["title"], "sec-02")
minpp = float(S.get("min_change_pp", 1))


def top_change(mapping: dict) -> tuple | None:
    """비중이 가장 많이 늘어난 항목 (min_change_pp 미만이면 없음)."""
    ranked = biggest_share_change(cmp, mapping)
    return ranked[0] if ranked and ranked[0][3] >= minpp else None


def largest_now(mapping: dict) -> tuple | None:
    """최근 기간에 비중이 가장 큰 항목 (이름, 기준, 최근, 변화)."""
    ranked = biggest_share_change(cmp, mapping)
    return max(ranked, key=lambda x: x[2]) if ranked else None


def share_card(cfg: dict, top: tuple | None, key: str, extra: str = "", mapping: dict | None = None) -> str:
    if top is None:
        title = cfg["title_none"]
        big = largest_now(mapping or {})
        body = (f'<div class="sk-cap" style="margin-top:6px">{esc(fill(cfg["value_label"]))} · 가장 큰 항목</div>'
                f'<div class="sk-trend"><span class="a">{esc(big[0])} {big[2]:.0f}%</span>'
                f'<span class="d" style="background:var(--neutral-bg);color:var(--neutral)">{big[3]:+.0f}%p</span></div>'
                if big else "")
    else:
        nm, b, a, d = top
        title = fill(cfg["title"], **{key: nm})
        vmax = max(a, b, 1)
        body = (f'<div class="sk-cap" style="margin-top:6px">{esc(fill(cfg["value_label"]))} · {esc(nm)}</div>'
                f'<div class="sk-trend"><span class="b">{b:.0f}%</span><span class="ar">→</span>'
                f'<span class="a">{a:.0f}%</span><span class="d">{d:+.0f}%p</span></div>'
                f'<div class="sk-tbar"><span>{esc(P.base_label)}</span><i style="width:{b / vmax * 70:.0f}%;background:var(--bar-base)"></i><em>{b:.0f}%</em></div>'
                f'<div class="sk-tbar"><span>{esc(P.recent_label)}</span><i style="width:{a / vmax * 70:.0f}%;background:var(--indigo)"></i><em>{a:.0f}%</em></div>')
    html = (f'<div class="sk-dcard"><div class="eb">{esc(cfg["eyebrow"])}</div>'
            f'<div class="tt">{esc(title)}</div>{body}{extra}</div>')
    return html


W = S["who"]
who_top = top_change(W["segments"])
who_note = ""
if who_top:
    sc = segment_sales_change(cmp, W["segments"][who_top[0]])
    if isnum(sc):
        note = fill(W["note_up"] if sc >= 0 else W["note_down"], segment=who_top[0])
        who_note = f'<div class="sk-dnote">{esc(note)} (매출액 {sc:+.0f}%)</div>'
who_html = share_card(W, who_top, "segment", who_note, W["segments"])

N = S["when"]
wk_metric = N.get("weekend")
wa, wb = cmp["recent"].get(wk_metric), cmp["base"].get(wk_metric)
wk_html = ""
if isnum(wa) and isnum(wb):
    wk_html = (f'<div class="sk-dnote"><b>{esc(N["weekend_label"])}</b> {wb:.0f}% → {wa:.0f}% '
               f'<span class="d{" neg" if wa - wb < 0 else ""}">{wa - wb:+.0f}%p</span></div>')
when_top = top_change(N["bands"])
when_html = share_card(N, when_top, "band", wk_html, N["bands"])
st.html(f'<div class="sk-dgrid2">{who_html}{when_html}</div>')

# ------------------------------------------------------------------ 03 관심 트렌드 (SNS 키워드 + 검색 추이)
I = D["interest"]
sec(I["num"], I["title"], "sec-03", I.get("sub", ""))
a = area_table()
det_col = I.get("details", "sns_keyword_details")
details = parse_details(a.loc[cid, det_col]) if (det_col in a and cid in a.index) else []
raw = a.loc[cid, I["metric"]] if (I["metric"] in a and cid in a.index) else None
seeds = a.loc[cid, I["seeds"]] if (I.get("seeds") in a and cid in a.index) else None
if details:
    # 키워드 카드: 업종 · 키워드 · 인스타 언급 수 · (DataLab 있으면) 검색 추이
    st.html(sns_cards(details, major, int(I.get("max", 8))))
    src = I.get("source", "")
    if isinstance(seeds, str) and seeds.strip():
        src = fill(src, 지역=seeds.replace("|", " "))
    if src:
        st.html(f'<div class="sk-dnote">{esc(src)}</div>')
elif parse_tags(raw):
    st.html('<div class="sk-kw">' + "".join(f'<span>↗ {esc(t)}</span>' for t in parse_tags(raw)) + "</div>")
else:
    st.html(f'<div class="sk-dempty">{esc(I["empty"])}</div>')

# ------------------------------------------------------------------ 04 준비 방향
A = D["actions"]
sec(A["num"], A["title"], "sec-04", A.get("sub", ""))
factors, _ = factors_for(major, middle)
top_f = next((f for f in factors if f.usable), None)

evid: dict[str, tuple[list[str], list[str]]] = {}
if not when_top and (bn := largest_now(N["bands"])):
    evid["when"] = ([f"시간대별 매출 구성은 {P.base_label}과 비슷한 편이고, 가장 큰 시간대는 {bn[0]} {bn[2]:.0f}%예요."]
                    + ([f"주말 매출 비중은 {wb:.0f}% → {wa:.0f}%예요."] if isnum(wa) and isnum(wb) else []),
                    [f"{bn[0]} {bn[2]:.0f}%"] + ([f"주말 비중 {wa - wb:+.0f}%p"] if isnum(wa) and isnum(wb) else []))
if not who_top and (sg := largest_now(W["segments"])):
    evid["who"] = ([f"고객층 구성은 {P.base_label}과 비슷한 편이고, 가장 큰 고객층은 {sg[0]} {sg[2]:.0f}%예요."],
                   [f"{sg[0]} {sg[2]:.0f}%"])
if when_top:
    nm, b, a_, d = when_top
    lines = [f"{nm} 매출 비중이 {b:.0f}% → {a_:.0f}%로 {d:+.0f}%p 바뀌었어요."]
    chips = [f"{nm} 비중 {d:+.0f}%p"]
    if isnum(wa) and isnum(wb):
        lines.append(f"주말 매출 비중은 {wb:.0f}% → {wa:.0f}%예요.")
        chips.append(f"주말 비중 {wa - wb:+.0f}%p")
    evid["when"] = (lines, chips)
if who_top:
    nm, b, a_, d = who_top
    lines = [f"{nm} 고객 비중이 {b:.0f}% → {a_:.0f}%로 {d:+.0f}%p 바뀌었어요."]
    chips = [f"{nm} {d:+.0f}%p"]
    sc = segment_sales_change(cmp, W["segments"][nm])
    if isnum(sc):
        lines.append(f"이 고객층 매출액은 {sc:+.0f}%예요.")
        chips.append(f"{nm} 매출액 {sc:+.0f}%")
    evid["who"] = (lines, chips)
lines = [f"점포 수는 {P.base_label} 대비 {pct(chg['stores'])}, 점포당 평균 매출은 {pct(chg['sps'])}예요."]
chips = [f"점포 수 {pct(chg['stores'])}", f"점포당 매출 {pct(chg['sps'])}"]
if top_f:
    fa, fb = cmp["recent"].get(top_f.metric), cmp["base"].get(top_f.metric)
    if isnum(fa) and isnum(fb):
        lines.append(f"{industry} 주요 매출요인 1순위는 {top_f.name}이고, 이 상권은 {fb:.0f}% → {fa:.0f}%예요.")
    chips.append(f"주요 요인 · {top_f.short}")
evid["competition"] = (lines, chips)

cmp_label = f"{P.recent_label} vs {P.base_label}"
fa = fb = None
if top_f:
    fa, fb = cmp["recent"].get(top_f.metric), cmp["base"].get(top_f.metric)
    fa, fb = (fa, fb) if isnum(fa) and isnum(fb) else (None, None)
reqs = {
    "when": narrative.when_req(industry, cmp_label, when_top, largest_now(N["bands"]), (wb, wa) if isnum(wa) and isnum(wb) else None),
    "who": narrative.who_req(industry, cmp_label, who_top, largest_now(W["segments"]),
                             segment_sales_change(cmp, W["segments"][who_top[0]]) if who_top else None),
    "competition": narrative.competition_req(industry, cmp_label, chg, top_f.name if top_f and fa is not None else None, fb, fa),
}
shown = [it for it in A["items"] if it["key"] in evid]
titles = dict(zip((it["key"] for it in shown), llm_api.ask_many([reqs.get(it["key"]) for it in shown])))  # 카드 제목을 한 번에 받아 둠

rows = ""
for i, it in enumerate(shown, 1):
    lines, chips = evid[it["key"]]
    rows += (f'<div class="sk-act"><span class="n">{i:02d}</span>'
             f'<div class="body"><div class="tt">{llm(" · ".join(chips), titles.get(it["key"]))}</div>'
             f'<div class="ev"><span>분석 근거</span><div>{"<br>".join(esc(x) for x in lines)}</div></div></div>'
             f'<div class="chips">{"".join(f"<em>{esc(c)}</em>" for c in chips)}</div>'
             f'<a class="more" href="#{it["link"]}">근거 보기 ›</a></div>')
st.html(f'<div class="sk-acts">{rows}</div>')
