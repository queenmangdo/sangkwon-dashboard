"""업종별 5가지 요인 카드(변수 묶음) + 매출 요인 하이라이트 (docs/SPEC.md 2·3절)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from . import config as C
from .engine import available
from .loader import factor_table, group_table

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
    axis_lo: float | None = None      # 좋은 구간 띠 — 눈금 시작·끝
    axis_hi: float | None = None
    band_lo: float | None = None      # 매출이 가장 높은 구간 시작·끝
    band_hi: float | None = None

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
    def band(self) -> tuple | None:
        """(눈금 시작, 눈금 끝, 구간 시작, 구간 끝). 연속 변수이고 값이 다 있을 때만"""
        v = (self.axis_lo, self.axis_hi, self.band_lo, self.band_hi)
        if not self.confirmed or self.shape == "binary" or any(x is None for x in v) or v[1] <= v[0]:
            return None
        return v

    @property
    def band_label(self) -> str:
        """'30~45%' · '45% 이상' · '13% 이하'. 구간이 눈금 전체면 ''"""
        if not self.band:
            return ""
        a, b, lo, hi = self.band
        if lo <= a and hi >= b:
            return ""
        if hi >= b:
            return f"{self.fmt(lo)} 이상"
        if lo <= a:
            return f"{self.fmt(hi)} 이하"
        return f"{self.fmt(lo)} 근처" if lo == hi else f"{lo:,.0f}~{self.fmt(hi)}"

    @property
    def relation(self) -> str:
        if not self.confirmed:
            return "관계 확인 불가"
        if self.band:
            return (f"{self.band_label}일 때 매출이 가장 높은 편이에요" if self.band_label
                    else "값에 따라 매출 차이가 크지 않은 편이에요")
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


@dataclass
class Group:
    """요인 카드 한 장 = 변수 묶음 하나"""
    key: str
    rank: int
    name: str
    definition: str
    relation: str          # 숫자 없이 말로 쓴 관계 문장
    rep: Factor | None     # 대표 변수 (요인 표에 없으면 None) — 하이라이트·상세 화면에 씀


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
    return [_factor(r, int(r["rank"])) for _, r in rows.iterrows()], note


def _factor(r, rank: int) -> Factor:
    """요인 표 한 행 → Factor. 이름·단위는 variables.csv"""
    V = C.variables()
    var = str(r["var"])
    v = V.loc[var].to_dict() if var in V.index else None
    get = (lambda k, d="": (v.get(k) or d) if v else d)
    return Factor(
        var=var, metric=get("metric", var), rank=rank,
        name=get("name", str(r["name"])), short=get("short_name", str(r["name"])), unit=get("unit", "%"),
        definition=(str(r["definition"]) if pd.notna(r["definition"]) else get("definition", "")),
        shape=_shape(r, v),
        threshold=_num(r["threshold"]) if _num(r["threshold"]) is not None else _num(get("threshold")),
        optimum=_num(r["optimum"]) if _num(r["optimum"]) is not None else _num(get("optimum")),
        effect=_num(r["effect"]), share=_num(r["share"]), reliability=str(r["reliability"]),
        binary_action=get("binary_action"), high_text=get("high_text"), low_text=get("low_text"),
        axis_lo=_num(r.get("axis_lo")), axis_hi=_num(r.get("axis_hi")),
        band_lo=_num(r.get("band_lo")), band_hi=_num(r.get("band_hi")),
    )


def groups_for(major: str, middle: str, n: int = 5) -> tuple[list[Group], str]:
    """(묶음 카드 목록, 안내 문구). 안내: '' | 대분류 기준 | 신뢰도 경고 | 데이터 없음."""
    t = group_table()
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
    ft = factor_table()
    used = rows["middle"].iloc[0]
    fv = ft[(ft["major"] == major) & (ft["middle"] == used)].set_index("var") if not ft.empty else pd.DataFrame()
    G = C.groups()
    out = []
    for _, r in rows.sort_values("rank").head(n).iterrows():
        key, rank = str(r["group"]), int(r["rank"])
        g = G.loc[key].to_dict() if key in G.index else {}
        rep = str(r["rep_var"]) if pd.notna(r["rep_var"]) else ""
        out.append(Group(key=key, rank=rank, name=g.get("name") or key, definition=g.get("definition", ""),
                         relation=str(r["relation"]) if pd.notna(r["relation"]) else "",
                         rep=_factor(fv.loc[rep].to_dict() | {"var": rep}, rank) if rep in fv.index else None))
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
        res[c] = Highlight("single", judgments=js, payload=_single_payload(industry, names.get(c, str(c)), js, base))
        return res

    # 한 요인은 그 요인에서 1등인 상권만 '유리', 꼴찌인 상권만 '불리'로 쓸 수 있다 (상권끼리 같은 요인으로 겹치지 않게)
    top: dict[str, int] = {}
    bottom: dict[str, int] = {}
    for f in use:
        sc = [(eff[c][f.var], -i, c) for i, c in enumerate(valid) if eff[c][f.var] is not None]
        if len(sc) >= 2:
            top[f.var] = max(sc)[2]
            bottom[f.var] = min(sc)[2]

    for c in valid:
        others = [o for o in valid if o != c]
        gaps = []
        for f in use:
            mine = eff[c][f.var]
            ref = [eff[o][f.var] for o in others if eff[o][f.var] is not None]
            if mine is None or not ref:
                continue
            gaps.append((f, values[c].get(f.metric), mine - sum(ref) / len(ref)))
        best = max((g for g in gaps if top.get(g[0].var) == c), key=lambda x: (x[2], -x[0].rank), default=None)
        worst = min((g for g in gaps if bottom.get(g[0].var) == c), key=lambda x: (x[2], x[0].rank), default=None)
        best = best if best and best[2] >= T else None
        worst = worst if worst and worst[2] <= -T else None
        h = Highlight("compare", best=best, worst=worst, n_others=len(others))
        h.payload = llm_payload(industry, names.get(c, str(c)), best, worst, values[c], others, values)
        res[c] = h
    return res


def _part(f: Factor, v, higher: bool) -> dict:
    return {"factor": f.name, "value": f.fmt(v), "direction": "higher_than_others" if higher else "lower_than_others",
            "meaning": f.high_text if higher else f.low_text, "shape": f.shape}


def llm_payload(industry, district, best, worst, mine, others, values) -> dict:
    """LLM 입력 (지침은 config/llm_prompts.yaml → highlight_compare)."""
    def part(t):
        if not t:
            return None
        f, v, _ = t
        ref = [values[o].get(f.metric) for o in others if values[o].get(f.metric) is not None]
        return _part(f, v, bool(v is not None and ref and v > sum(ref) / len(ref)))
    return {"industry": industry, "district": district, "best": part(best), "worst": part(worst)}


def _single_payload(industry, district, judgments, base) -> dict | None:
    """상권 1곳 진단용 LLM 입력: 유리 1개 + 아쉬움 1개 (요인 순위가 높은 것). 지침은 highlight_single."""
    def pick(label):
        for f, v, j in judgments:
            if j == label and v is not None:
                b = base.get(f.metric)
                higher = b is not None and v > b
                return {"factor": f.name, "value": f.fmt(v), "vs_seoul": "higher" if higher else "lower",
                        "meaning": f.high_text if higher else f.low_text, "shape": f.shape}
        return None
    if not judgments:
        return None
    return {"industry": industry, "district": district, "good": pick("유리"), "bad": pick("아쉬움")}


def llm_sentence(h: Highlight) -> str:
    """LLM 연결 전 자리 표시: {best.factor} {best.value} · {worst.factor} {worst.value} — LLM 한줄 해석 연결 예정"""
    ph = C.S("llm_placeholder", "LLM 한줄 해석 연결 예정")
    parts = []
    for t in (h.best, h.worst):
        if t:
            f, v, _ = t
            parts.append(f"{f.short} {f.fmt(v)}")
    return f"{' · '.join(parts) or '뚜렷한 차이 없음'} — {ph}"
