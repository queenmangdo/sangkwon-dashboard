"""지표 계산: metrics.yaml 정의대로 상권 × 업종 값을 만든다."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from . import config as C
from .loader import area_table, has_metric_columns, metrics_table


def months() -> list[int]:
    return sorted(metrics_table()["_month"].unique())


def window() -> list[int]:
    return months()[-int(C.S("period_months", 12)):]


def latest() -> int:
    return months()[-1]


def fmt_ym(ym: int) -> str:
    s = str(ym)
    return f"{s[2:4]}.{s[4:6]}"


def is_total(middle: str) -> bool:
    return middle == C.S("total_label", "전체")


def industry_rows(major: str, middle: str) -> pd.DataFrame:
    """고른 업종의 행. '전체'는 데이터의 '전체' 행 → 없으면 total_fallback 에 따라 비우거나 합친다."""
    df = metrics_table()
    df = df[df["_major"] == major]
    total = C.S("total_label", "전체")
    if is_total(middle):
        t = df[df["_middle"] == total]
        if len(t) or C.S("total_fallback", "none") != "aggregate":
            return t
        return df[df["_middle"] != total]
    return df[df["_middle"] == middle]


def available(name: str) -> bool:
    return has_metric_columns(name)


@st.cache_data(show_spinner="상권 값 계산 중…")
def compute(major: str, middle: str) -> pd.DataFrame:
    """index = 상권 ID, columns = 지표 이름 + stores_latest, density."""
    rows = industry_rows(major, middle)
    if rows.empty:
        return pd.DataFrame()
    win = rows[rows["_month"].isin(window())]
    last = rows[rows["_month"] == latest()]
    g = win.groupby("_cluster")
    out = pd.DataFrame(index=sorted(rows["_cluster"].unique()))
    area = area_table()
    for name, spec in C.metrics().items():
        if not available(name):
            continue
        agg = spec["agg"]
        if agg == "ratio":
            n, d = C.metric_col(spec["num"]), C.metric_col(spec["den"])
            v = g[n].sum() / g[d].sum().replace(0, np.nan)
        elif agg == "wavg":
            c, w = C.metric_col(spec["col"]), C.metric_col(spec["weight"])
            ok = win[c].notna()
            num = (win[c].where(ok, 0) * win[w].where(ok, 0)).groupby(win["_cluster"]).sum()
            den = win[w].where(ok, 0).groupby(win["_cluster"]).sum()
            v = num / den.replace(0, np.nan)
        elif agg == "sum_latest":
            v = last.groupby("_cluster")[C.metric_col(spec["col"])].sum()
        elif agg == "area":
            v = area[spec["col"]] if spec["col"] in area else pd.Series(dtype=float)
        else:
            continue
        if spec.get("transform") == "exp_pct":
            v = (np.exp(v) - 1) * 100
        out[name] = v.reindex(out.index)
    out["stores_latest"] = out.get("stores_latest", pd.Series(0, index=out.index)).fillna(0)
    if "_grid_count" in area:
        km2 = area["_grid_count"].reindex(out.index) * float(C.S("grid_area_km2", 0.0625))
        out["density"] = out["stores_latest"] / km2
    return out


@st.cache_data
def major_counts(major: str) -> pd.Series:
    """대분류 가게 수 (최근 달). '전체' 행이 있으면 그 값, 없으면 중분류 합."""
    df = metrics_table()
    df = df[(df["_major"] == major) & (df["_month"] == latest())]
    total = C.S("total_label", "전체")
    t = df[df["_middle"] == total]
    use = t if len(t) else df[df["_middle"] != total]
    return use.groupby("_cluster")[C.metric_col("stores")].sum()


@st.cache_data
def baseline(major: str, middle: str) -> dict:
    """서울 보통 = 같은 업종 가게가 최근 달 n곳 이상인 상권들의 중앙값. iqr = p75 − p25."""
    m = compute(major, middle)
    if m.empty:
        return {"_n": 0, "_iqr": {}}
    pool = m[m["stores_latest"] >= int(C.S("baseline_min_stores", 3))]
    num = pool.select_dtypes("number")
    out = num.median().to_dict()
    out["_iqr"] = (num.quantile(.75) - num.quantile(.25)).to_dict()
    out["_n"] = int(len(pool))
    out["_pool"] = pool.index.tolist()
    return out


def values_for(major: str, middle: str, cids: list[int]) -> dict[int, dict]:
    m = compute(major, middle)
    return {c: (m.loc[c].to_dict() if (not m.empty and c in m.index) else {}) for c in cids}
