"""업종별 5가지 요인 카드 + 매출 요인 하이라이트 (docs/SPEC.md 2·3절)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from . import config as C
from .engine import available
from .loader import factor_table

UNCLEAR = ("뚜렷하지", "불안정")


def _num(x):
    try:
        x = float(x)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


@dataclass
class Factor:
    var: str
    metric: str
    rank: int
    name: str
    short: str
    unit: str
    definition: str
    shape: str            # increasing | decreasing | optimum | binary | unknown
    threshold: float | None
    optimum: float | None
    effect: float | None  # 방향 크기 (%)
    share: float | None
    reliability: str
    binary_action: str = ""
    high_text: str = ""
    low_text: str = ""

    @property
    def usable(self) -> bool:
        if self.effect is None or not available(self.metric):
            return False
        return self.shape in ("increasing", "decreasing", "binary") or (self.shape == "optimum" and self.optimum is not None)

    @property
    def confirmed(self) -> bool:
        return self.shape in ("increasing", "decreasing", "binary") or (self.shape == "optimum" and self.optimum is not None)

    def fmt(self, v) -> str:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "–"
        return f"{v:,.0f}{self.unit}"

    @property
    def relation(self) -> str:
        if not self.confirmed:
            return "관계 확인 불가"
        if self.shape == "increasing":
            return (f"{self.fmt(self.threshold)}보다 높아질수록 매출이 높아지는 편이에요" if self.threshold is not None
                    else "높을수록 매출이 높은 편이에요")
        if self.shape == "decreasing":
            return "높을수록 매출이 낮은 편이에요"
        if self.shape == "optimum":
            return f"{self.fmt(self.optimum)} 근처일 때 매출이 가장 높고, 그보다 많거나 적으면 낮아져요"
        return f"{self.binary_action or '해당'}하는 가게가 안 하는 가게보다 매출이 높은 편이에요"

    @property
    def curve(self) -> str:
        return {"increasing": "up", "binary": "up", "decreasing": "down", "optimum": "hill"}.get(self.shape, "none") \
            if self.confirmed else "none"

    def score(self, v: float | None, base: float | None, iqr: float | None) -> float | None:
        """매출 % 환산 효과 (서울 보통 = 0). effect × (v − 기준) ÷ iqr. 최적점형은 최적값과의 거리."""
        if v is None or base is None or not iqr or self.effect is None:
            return None
        if any(isinstance(x, float) and math.isnan(x) for x in (v, base, iqr)):
            return None
        if self.shape == "optimum":
            return abs(self.effect) * (abs(base - self.optimum) - abs(v - self.optimum)) / iqr
        return self.effect * (v - base) / iqr


def _shape(row, vrow) -> str:
    d = str(row.get("direction") or "")
    if any(u in d for u in UNCLEAR):
        return "unknown"
    s = str(row.get("shape") or "").strip() if pd.notna(row.get("shape")) else ""
    if not s and vrow is not None:
        s = vrow.get("shape", "").strip()
    if not s:
        s = "increasing" if "↑" in d else "decreasing" if "↓" in d else "unknown"
    return s


def factors_for(major: str, middle: str, n: int = 5) -> tuple[list[Factor], str]:
    """(요인 목록, 안내 문구). 안내: '' | 대분류 기준 | 신뢰도 경고 | 데이터 없음."""
    t = factor_table()
    if t.empty:
        return [], "요인 결과 파일이 없어요."
    total = C.S("total_label", "전체")
    rows = t[(t["major"] == major) & (t["middle"] == middle)]
    note = ""
    if rows.empty:
        return [], "이 업종의 요인 결과가 아직 없어요."
    if str(rows["reliability"].iloc[0]).startswith("낮") and middle != total:
        up = t[(t["major"] == major) & (t["middle"] == total)]
        if len(up):
            rows, note = up, "대분류 기준이에요"
        else:
            note = "이 업종은 분석에 쓴 가게 수가 적어 결과를 조심해서 봐야 해요."
    rows = rows.sort_values("rank").head(n)
    V = C.variables()
    out = []
    for _, r in rows.iterrows():
        var = str(r["var"])
        v = V.loc[var].to_dict() if var in V.index else None
        get = (lambda k, d="": (v.get(k) or d) if v else d)
        out.append(Factor(
            var=var, metric=get("metric", var), rank=int(r["rank"]),
            name=get("name", str(r["name"])), short=get("short_name", str(r["name"])), unit=get("unit", "%"),
            definition=(str(r["definition"]) if pd.notna(r["definition"]) else get("definition", "")),
            shape=_shape(r, v),
            threshold=_num(r["threshold"]) if _num(r["threshold"]) is not None else _num(get("threshold")),
            optimum=_num(r["optimum"]) if _num(r["optimum"]) is not None else _num(get("optimum")),
            effect=_num(r["effect"]), share=_num(r["share"]), reliability=str(r["reliability"]),
            binary_action=get("binary_action"), high_text=get("high_text"), low_text=get("low_text"),
        ))
    return out, note


# ------------------------------------------------------------------ 하이라이트
@dataclass
class Highlight:
    mode: str                         # compare | single | insufficient | nodata
    best: tuple | None = None         # (Factor, 값, gap)
    worst: tuple | None = None
    judgments: list = field(default_factory=list)   # single: [(Factor, 값, 유리/보통/아쉬움)]
    n_others: int = 0
    payload: dict | None = None


def highlights(factors: list[Factor], values: dict[int, dict], stores: dict[int, float], base: dict,
               industry: str, names: dict[int, str]) -> dict[int, Highlight]:
    T = float(C.S("highlight_T", 5))
    min_n = int(C.S("sample_min_stores", 3))
    use = [f for f in factors if f.usable]
    iqr = base.get("_iqr", {})
    res: dict[int, Highlight] = {}
    valid = []
    for cid, v in values.items():
        if not v:
            res[cid] = Highlight("nodata")
        elif stores.get(cid, 0) < min_n:
            res[cid] = Highlight("insufficient")
        else:
            valid.append(cid)
    eff = {c: {f.var: f.score(values[c].get(f.metric), base.get(f.metric), iqr.get(f.metric)) for f in use} for c in valid}

    if len(valid) == 1:
        c = valid[0]
        js = []
        for f in use:
            e = eff[c][f.var]
            if e is None:
                continue
            js.append((f, values[c].get(f.metric), "유리" if e >= T else "아쉬움" if e <= -T else "보통"))
        res[c] = Highlight("single", judgments=js)
        return res

    for c in valid:
        others = [o for o in valid if o != c]
        gaps = []
        for f in use:
            mine = eff[c][f.var]
            ref = [eff[o][f.var] for o in others if eff[o][f.var] is not None]
            if mine is None or not ref:
                continue
            gaps.append((f, values[c].get(f.metric), mine - sum(ref) / len(ref)))
        best = max(gaps, key=lambda x: (x[2], -x[0].rank), default=None)
        worst = min(gaps, key=lambda x: (x[2], x[0].rank), default=None)
        best = best if best and best[2] >= T else None
        worst = worst if worst and worst[2] <= -T else None
        h = Highlight("compare", best=best, worst=worst, n_others=len(others))
        h.payload = llm_payload(industry, names.get(c, str(c)), best, worst, values[c], others, values)
        res[c] = h
    return res


def llm_payload(industry, district, best, worst, mine, others, values) -> dict:
    """명세의 LLM 입력 형식. API 연결 시 그대로 사용."""
    def part(t):
        if not t:
            return None
        f, v, _ = t
        ref = [values[o].get(f.metric) for o in others if values[o].get(f.metric) is not None]
        higher = v is not None and ref and v > sum(ref) / len(ref)
        return {"factor": f.name, "value": f.fmt(v), "direction": "higher_than_others" if higher else "lower_than_others",
                "meaning": f.high_text if higher else f.low_text}
    return {"industry": industry, "district": district, "best": part(best), "worst": part(worst),
            "rules": "한 문장, 60자 이내, '~한 사장님께 맞아요'로 끝, 수치 반복 금지, 핵심 키워드 1개를 **굵게**, 인과·보장 표현 금지"}


def llm_sentence(h: Highlight) -> str:
    """LLM 연결 전 자리 표시: {best.factor} {best.value} · {worst.factor} {worst.value} — LLM 한줄 해석 연결 예정"""
    ph = C.S("llm_placeholder", "LLM 한줄 해석 연결 예정")
    parts = []
    for t in (h.best, h.worst):
        if t:
            f, v, _ = t
            parts.append(f"{f.short} {f.fmt(v)}")
    return f"{' · '.join(parts) or '뚜렷한 차이 없음'} — {ph}"
