"""비교 표 행 그리기. config/items.yaml 의 type 마다 함수 하나."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core import config as C
from core.engine import available
from core.factors import llm_sentence
from core.loader import area_table
from core.ui import bars, cell, empty, esc, isnum, label, num, row, tag


@dataclass
class Ctx:
    slots: list
    vals: dict          # {cid: {metric: value}}
    base: dict          # 서울 보통 (+ _iqr, _n)
    industry: str       # 화면에 쓰는 업종 이름 (중분류, 전체면 대분류)
    is_total: bool
    major: str
    major_counts: pd.Series
    factors: list
    factor_note: str
    hl: dict            # {cid: Highlight}


def _cells(ctx: Ctx, fn) -> list[str]:
    out = []
    for cid in ctx.slots:
        if cid is None:
            out.append(empty("–"))
        elif not ctx.vals.get(cid):
            out.append(empty(f"'{ctx.industry}' 데이터가 아직 없어요" if ctx.is_total else f"최근 {ctx.industry} 가게가 없어요"))
        else:
            out.append(fn(cid, ctx.vals[cid]))
    return out


def _best(ctx: Ctx, metric: str):
    xs = {c: v.get(metric) for c, v in ctx.vals.items() if v and isnum(v.get(metric))}
    return max(xs, key=xs.get) if len(xs) >= 2 else None


def _wip(spec: dict, ctx: "Ctx") -> None:
    """지표 컬럼이 데이터에 없을 때: 라벨에 '데이터 확보 시', 칸은 빈 칸."""
    row(label(_lab(spec, ctx), spec.get("sub", ""), wip=True), [empty("데이터 확보 시 채워져요") for _ in ctx.slots])


def _lab(spec, ctx):
    return spec["label"].replace("{업종}", ctx.industry)


# ------------------------------------------------------------------ type 별
def r_highlight(spec, ctx: Ctx):
    T = C.S("highlight_T", 5)

    def fn(cid, v):
        h = ctx.hl.get(cid)
        if not ctx.factors:
            return cell(f'<div class="sk-llm">{esc(ctx.factor_note)}</div>', hl=True)
        if not any(f.usable for f in ctx.factors):
            return cell('<div class="sk-llm">관계를 확인할 수 있는 요인이 없어 요약을 만들지 않았어요</div>', hl=True)
        if h is None or h.mode == "nodata":
            return empty(f"최근 {ctx.industry} 가게가 없어요")
        if h.mode == "insufficient":
            return cell('<div class="sk-llm">비교할 가게가 적어 요약을 만들지 않았어요</div>', hl=True)
        if h.mode == "single":
            rows = "".join(
                f'<div class="sk-judge"><span>{esc(f.short)} <b>{f.fmt(x)}</b></span>'
                f'{tag(j, {"유리": "good", "아쉬움": "bad"}.get(j, "mid"))}</div>' for f, x, j in h.judgments)
            return cell(f'<div class="sk-cap" style="margin-bottom:6px">서울 보통과 비교한 진단이에요</div>{rows}'
                        f'<div class="sk-hlsent"><span class="sk-llm">{esc(C.S("llm_placeholder"))}</span></div>', hl=True)
        who = "다른 두 곳보다" if h.n_others == 2 else "다른 곳보다"
        b = (f'<div class="sk-pill good">▲ 가장 유리 · {esc(h.best[0].short)} {h.best[0].fmt(h.best[1])}</div>' if h.best
             else f'<div class="sk-pill none">▲ {who} 뚜렷하게 앞서는 점 없음</div>')
        w = (f'<div class="sk-pill bad">▼ 가장 불리 · {esc(h.worst[0].short)} {h.worst[0].fmt(h.worst[1])}</div>' if h.worst
             else f'<div class="sk-pill none">▼ {who} 뚜렷하게 뒤처지는 점 없음</div>')
        return cell(f'{b}<br>{w}<div class="sk-hlsent"><span class="sk-llm">{esc(llm_sentence(h))}</span></div>', hl=True)

    single = any(h.mode == "single" for h in ctx.hl.values())
    sub = "서울 보통 대비<br>유리 · 보통 · 아쉬움" if single else spec.get("sub", "")
    row(label(spec["label"], sub, hl=True), _cells(ctx, fn))


def r_value_bar(spec, ctx: Ctx):
    m = spec["metric"]
    if not available(m):
        return _wip(spec, ctx)
    sc, unit = spec.get("scale", 1), spec.get("unit", "")
    vmax = max([v.get(m) or 0 for v in ctx.vals.values() if v] + [ctx.base.get(m) or 0])
    top = _best(ctx, m)
    base = ctx.base.get(m)

    def vs_base(x):
        """서울 보통(같은 업종 상권 중앙값) 대비 ±% — items.yaml 의 show_vs_base: true 일 때"""
        if not spec.get("show_vs_base") or not isnum(x) or not isnum(base) or not base:
            return ""
        p = (x / base - 1) * 100
        return f'<div class="sk-sub"><b class="{"sk-pos" if p >= 0 else "sk-neg"}">{p:+.0f}%</b> 서울 보통 대비</div>'

    row(label(_lab(spec, ctx), spec.get("sub", "")), _cells(ctx, lambda c, v: cell(
        f'<div class="sk-big">{num(v.get(m), sc)}<small>{esc(unit)}</small>'
        f'{tag(spec["best_tag"]) if spec.get("best_tag") and c == top else ""}</div>'
        + vs_base(v.get(m))
        + bars(v.get(m), base, vmax, f'서울 보통 {num(base, sc)}{esc(unit.split()[0] if unit else "")}'))))


def r_store_counts(spec, ctx: Ctx):
    """대분류 n곳 / 중분류 n곳 (최근 달). '전체'면 대분류만."""
    def fn(c):
        mj = ctx.major_counts.get(c)
        mj_html = f'<span class="sk-big">{num(mj, d=0)}<small>곳</small></span><div class="sk-sub">{esc(ctx.major)}</div>'
        if ctx.is_total:
            return cell(mj_html)
        mi = (ctx.vals.get(c) or {}).get("stores_latest", 0)
        return cell(f'<div style="display:flex;gap:28px"><div>{mj_html}</div>'
                    f'<div><span class="sk-big">{num(mi, d=0)}<small>곳</small></span><div class="sk-sub">{esc(ctx.industry)}</div></div></div>')
    row(label(_lab(spec, ctx), spec.get("sub", "")), [empty("–") if c is None else fn(c) for c in ctx.slots])


def r_density_bar(spec, ctx: Ctx):
    """동종업계 밀집도: 대분류 · 중분류 가게 수 ÷ 상권 넓이(격자 수 × 격자 넓이). '전체'면 대분류만."""
    if not available(spec["metric"]):
        return _wip(spec, ctx)
    a = area_table()
    if "_grid_count" not in a:
        return _wip(spec, ctx)
    km2 = a["_grid_count"] * float(C.S("grid_area_km2", 0.0625))
    mj = ctx.major_counts
    mj_den = (mj / km2.reindex(mj.index)).dropna()
    mj_base = mj_den.reindex(mj[mj >= int(C.S("baseline_min_stores", 3))].index).median()
    mi_base = ctx.base.get("density")
    sel = [c for c in ctx.slots if c is not None]
    if ctx.is_total:
        xs = {c: mj_den.get(c) for c in sel if isnum(mj_den.get(c))}
        top = max(xs, key=xs.get) if len(xs) >= 2 else None
    else:
        top = _best(ctx, "density")
    best_tag = spec.get("best_tag")

    def block(val, base, name, is_top):
        t = tag(best_tag) if best_tag and is_top else ""
        return (f'<div><span class="sk-big">{num(val, d=0)}<small>곳/㎢</small></span>{t}'
                f'<div class="sk-sub">{esc(name)} · 서울 보통 <b>{num(base, d=0)}</b></div></div>')

    def fn(c):
        b_mj = block(mj_den.get(c), mj_base, ctx.major, ctx.is_total and c == top)
        if ctx.is_total:
            return cell(b_mj)
        mi = (ctx.vals.get(c) or {}).get("density")
        b_mi = block(mi, mi_base, ctx.industry, c == top)
        return cell(f'<div style="display:flex;gap:28px;flex-wrap:wrap">{b_mj}{b_mi}</div>')
    row(label(_lab(spec, ctx), spec.get("sub", "")), [empty("–") if c is None else fn(c) for c in ctx.slots])


def r_pct_judge(spec, ctx: Ctx):
    m = spec["metric"]
    if not available(m):
        return _wip(spec, ctx)
    g = float(C.S("judge_gap_pp", 2))

    def fn(c, v):
        x, b = v.get(m), ctx.base.get(m)
        if not isnum(x):
            return empty("–")
        t = ""
        if isnum(b):
            t = tag("유리", "good") if x - b >= g else tag("아쉬움", "bad") if x - b <= -g else tag("보통", "mid")
        return cell(f'<div class="sk-big">{x:.0f}<small>%</small>{t}</div><div class="sk-sub">서울 보통 <b>{num(b, d=0)}%</b></div>')
    row(label(_lab(spec, ctx), spec.get("sub", "")), _cells(ctx, fn))


def r_hours(spec, ctx: Ctx):
    bands = spec["bands"]
    if not all(available(b["metric"]) for b in bands):
        return _wip(spec, ctx)
    wk = spec.get("weekend")

    def fn(c, v):
        vs = [v.get(b["metric"]) for b in bands]
        ok = [x for x in vs if isnum(x)]
        if not ok:
            return empty("–")
        vmax = max(ok)
        pk = max(range(len(bands)), key=lambda i: vs[i] if isnum(vs[i]) else -1)
        strip = "".join(
            f'<div title="{esc(b["name"])} {num(x, d=0)}%" style="background:rgba(45,42,132,{0.1 + 0.85 * ((x or 0) / vmax):.2f})"></div>'
            for b, x in zip(bands, vs))
        labs = "".join(f'<span>{esc(b["name"])}</span>' for b in bands)
        w = v.get(wk) if wk else None
        wtxt = (f'<div class="sk-sub">주말 매출 <b>{w:.0f}%</b> · 평일 <b>{100 - w:.0f}%</b></div>' if isnum(w) else "")
        return cell(f'<div class="sk-big" style="font-size:18px">{esc(bands[pk]["name"])} {esc(bands[pk]["range"])}'
                    f' <small>{vs[pk]:.0f}%</small></div><div class="sk-strip">{strip}</div>'
                    f'<div class="sk-strip-lab">{labs}</div>{wtxt}')
    row(label(_lab(spec, ctx), spec.get("sub", "")), _cells(ctx, fn))


def r_customer_heatmap(spec, ctx: Ctx):
    grid = spec["rows"]
    if not all(available(m) for ms in grid.values() for m in ms):
        return _wip(spec, ctx)
    k = int(spec.get("top_k", 3))
    show_rank = bool(spec.get("show_rank", False))

    def fn(c, v):
        cells = [(g, a, v.get(m)) for g, ms in grid.items() for a, m in zip(spec["cols"], ms)]
        ok = [x for _, _, x in cells if isnum(x)]
        if not ok:
            return empty("–")
        rank = {(g, a): i + 1 for i, (g, a, _) in enumerate(sorted([t for t in cells if isnum(t[2])], key=lambda t: -t[2])[:k])}
        vmax = max(ok)
        head = "".join(f"<th>{esc(a)}</th>" for a in spec["cols"])
        body = ""
        for g, ms in grid.items():
            tds = ""
            for a, m in zip(spec["cols"], ms):
                x = v.get(m)
                if not isnum(x):
                    tds += '<td style="background:#F3F3F7">–</td>'
                    continue
                t = x / vmax
                rk = rank.get((g, a)) if show_rank else None
                tds += (f'<td class="{"top" if rk else ""}" style="background:rgba(45,42,132,{0.08 + 0.8 * t:.2f});'
                        f'color:{"#fff" if t > .55 else "#1D1D2B"}">{f"<sup>{rk}</sup> " if rk else ""}{x:.0f}%</td>')
            body += f"<tr><th>{esc(g)}</th>{tds}</tr>"
        first = min(rank, key=rank.get)
        return cell(f'<div class="sk-big" style="font-size:18px">{esc(first[0])} {esc(first[1])}</div>'
                    f'<table class="sk-heat"><tr><th></th>{head}</tr>{body}</table>')
    row(label(_lab(spec, ctx), spec.get("sub", "")), _cells(ctx, fn))


def r_money_area(spec, ctx: Ctx):
    m = spec["metric"]
    if not available(m):
        return _wip(spec, ctx)
    sc, unit = spec.get("scale", 1), spec.get("unit", "")
    a = area_table()
    col = C.metrics()[m]["col"]

    def fn(c, v):
        x = v.get(m)
        gu = a.loc[c, "_gu"] if c in a.index else ""
        gu_avg = a.loc[a["_gu"] == gu, col].mean() if gu else None
        return cell(f'<div class="sk-big">{num(x, sc)}<small>{esc(unit)}</small></div>'
                    f'<div class="sk-sub">{esc(gu)} 평균 <b>{num(gu_avg, sc)}만</b> · 서울 보통 <b>{num(ctx.base.get(m), sc)}만</b></div>')
    row(label(_lab(spec, ctx), spec.get("sub", "")), _cells(ctx, fn))


def r_tags(spec, ctx: Ctx):
    m = spec["metric"]
    if not available(m):
        return _wip(spec, ctx)
    k = int(spec.get("max", 3))

    def fn(c, v):
        raw = v.get(m)
        if not isinstance(raw, str) or not raw.strip():
            return empty("–")
        tags = [t.strip() for t in raw.replace(",", "|").split("|") if t.strip()][:k]
        return cell("".join(f'<span class="sk-hash">{esc(t if t.startswith("#") else "#" + t)}</span>' for t in tags))
    row(label(_lab(spec, ctx), spec.get("sub", "")), _cells(ctx, fn))


RENDER = {
    "highlight": r_highlight, "value_bar": r_value_bar, "store_counts": r_store_counts,
    "density_bar": r_density_bar, "pct_judge": r_pct_judge, "hours": r_hours,
    "customer_heatmap": r_customer_heatmap, "money_area": r_money_area, "tags": r_tags,
}
