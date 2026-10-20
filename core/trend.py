"""상권 상세: 한 상권 × 업종의 1년 트렌드.

비교 방식은 데이터 기간에 따라 자동으로 정해진다 (config/settings.yaml → trend).
  - 데이터가 yoy_min_months 이상: 최근 n개월 vs 전년 동기(같은 달 1년 전)
  - 그보다 짧음(지금 샘플 12개월): 최근 n개월 vs 최근 1년
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config as C
from .engine import industry_rows, months


@dataclass
class Periods:
    recent: list[int]
    base: list[int]
    chart: list[int]
    mode: str          # yoy | year
    recent_label: str
    base_label: str


def _minus_year(ym: int) -> int:
    return ym - 100


def periods() -> Periods:
    t = C.S("trend", {}) or {}
    ms = months()
    r = int(t.get("recent_months", 3))
    recent = ms[-r:]
    chart = ms[-int(t.get("chart_months", 12)):]
    yoy = [_minus_year(m) for m in recent]
    if len(ms) >= int(t.get("yoy_min_months", 15)) and all(m in ms for m in yoy):
        return Periods(recent, yoy, chart, "yoy", f"최근 {r}개월", "전년 동기")
    year = ms[-12:]
    return Periods(recent, year, chart, "year", f"최근 {r}개월", "최근 1년" if len(year) >= 12 else f"최근 {len(year)}개월")


def _share_metrics() -> list[str]:
    """비율(가중 평균) 지표 이름들."""
    return [n for n, s in C.metrics().items() if s.get("agg") == "wavg"]


def _agg(rows: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """매출·점포 수 합계 + 비율 지표 가중 평균. by=None 이면 한 줄."""
    key = by or "_all"
    rows = rows.assign(_all=0)
    g = rows.groupby(key)
    sales, stores = C.metric_col("sales"), C.metric_col("stores")
    out = pd.DataFrame({"sales": g[sales].sum(), "stores": g[stores].sum(), "n_months": g["_month"].nunique()})
    for name in _share_metrics():
        spec = C.metrics()[name]
        c, w = C.metric_col(spec["col"]), C.metric_col(spec["weight"])
        if c not in rows or w not in rows:
            continue
        ok = rows[c].notna()
        num = (rows[c].where(ok, 0) * rows[w].where(ok, 0)).groupby(rows[key]).sum()
        den = rows[w].where(ok, 0).groupby(rows[key]).sum()
        out[name] = num / den.replace(0, np.nan)
    out["sps"] = out["sales"] / out["stores"].replace(0, np.nan)
    return out


def cluster_rows(major: str, middle: str, cid: int) -> pd.DataFrame:
    r = industry_rows(major, middle)
    return r[r["_cluster"] == cid]


def monthly(major: str, middle: str, cid: int) -> pd.DataFrame:
    """월별 매출·점포 수 + 첫 달 = 100 지수 (그래프 기간)."""
    p = periods()
    rows = cluster_rows(major, middle, cid)
    rows = rows[rows["_month"].isin(p.chart)]
    if rows.empty:
        return pd.DataFrame()
    m = _agg(rows, "_month").reindex(p.chart)
    first = m.dropna(subset=["sales"]).iloc[0]
    m["sales_idx"] = m["sales"] / first["sales"] * 100
    m["stores_idx"] = m["stores"] / first["stores"] * 100
    return m


def compare(major: str, middle: str, cid: int) -> dict | None:
    """최근 vs 기준 기간. 매출·점포 수는 월평균, 비율은 기간 가중 평균."""
    p = periods()
    rows = cluster_rows(major, middle, cid)
    rec, base = rows[rows["_month"].isin(p.recent)], rows[rows["_month"].isin(p.base)]
    if rec.empty or base.empty:
        return None
    a, b = _agg(rec).iloc[0], _agg(base).iloc[0]

    def per_month(x):
        return x["sales"] / x["n_months"], x["stores"] / x["n_months"]
    rs, rst = per_month(a)
    bs, bst = per_month(b)
    out = {"recent": a.to_dict(), "base": b.to_dict(),
           "sales": (rs, bs), "stores": (rst, bst), "sps": (a["sps"], b["sps"])}
    out["chg"] = {k: (v[0] / v[1] - 1) * 100 if v[1] else np.nan for k, v in
                  (("sales", out["sales"]), ("stores", out["stores"]), ("sps", out["sps"]))}
    return out


def biggest_share_change(cmp: dict, mapping: dict[str, str]) -> list[tuple[str, float, float, float]]:
    """[(이름, 기준 비중, 최근 비중, 변화 %p)] 변화 큰 순."""
    res = []
    for name, metric in mapping.items():
        a, b = cmp["recent"].get(metric), cmp["base"].get(metric)
        if a is None or b is None or pd.isna(a) or pd.isna(b):
            continue
        res.append((name, b, a, a - b))
    return sorted(res, key=lambda x: -x[3])


def segment_sales_change(cmp: dict, metric: str) -> float | None:
    """그 고객층 매출액(월평균 매출 × 비중)의 변화율 %."""
    a, b = cmp["recent"].get(metric), cmp["base"].get(metric)
    if a is None or b is None or pd.isna(a) or pd.isna(b) or not b:
        return None
    ra = cmp["sales"][0] * a / 100
    rb = cmp["sales"][1] * b / 100
    return (ra / rb - 1) * 100 if rb else None


def llm_payload(industry: str, district: str, p: Periods, cmp: dict, who, when, weekend, factor) -> dict:
    """LLM 연결 시 입력 (상세 페이지 헤드라인 · 준비 방향 문장용)."""
    return {
        "industry": industry, "district": district,
        "compare": f"{p.recent_label} vs {p.base_label}",
        "growth": {k: None if pd.isna(v) else round(v, 1) for k, v in cmp["chg"].items()},
        "who": who, "when": when, "weekend": weekend, "top_factor": factor,
        "rules": "~이에요/~일 수 있어요로 끝, 인과·보장 표현 금지, 숫자는 근거로만",
    }
