"""데이터 읽기. 역할 컬럼은 내부 이름(_cluster, _month, _major, _middle …)으로 바꿔 두고,
나머지 컬럼은 원래 이름 그대로 둔다 → metrics.yaml 이 원래 컬럼 이름으로 참조."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from . import config as C


def _read(p: Path, **kw) -> pd.DataFrame:
    suf = p.suffix.lower()
    if suf == ".parquet":
        return pd.read_parquet(p)
    if suf in (".xlsx", ".xls"):
        return pd.read_excel(p)
    return pd.read_csv(p, encoding="utf-8-sig", **kw)


def _header(p: Path) -> list[str]:
    if p.suffix.lower() == ".csv":
        return list(pd.read_csv(p, encoding="utf-8-sig", nrows=0).columns)
    return list(_read(p).columns)


@st.cache_data(show_spinner="상권 지표 불러오는 중…")
def metrics_table() -> pd.DataFrame:
    p = C.path("metrics_table")
    cols = _header(p)
    m = C.columns()["metrics_table"]
    need = {v for v in m.values() if v}
    for spec in C.metrics().values():
        for k in ("num", "den", "weight", "col"):
            if spec.get(k) and spec.get("agg") != "area":
                need.add(C.metric_col(spec[k]))
    use = [c for c in cols if c in need]
    df = _read(p, usecols=use) if p.suffix.lower() == ".csv" else _read(p)[use]
    ren = {m["cluster"]: "_cluster", m["month"]: "_month", m["middle"]: "_middle"}
    if m.get("major") and m["major"] in df:
        ren[m["major"]] = "_major"
    df = df.rename(columns=ren)
    if "_major" not in df:
        df["_major"] = C.S("default_major")
    df["_month"] = pd.to_numeric(df["_month"].astype(str).str.replace("-", "").str[:6], errors="coerce").astype(int)
    for c in ("_major", "_middle"):
        df[c] = df[c].astype(str)
    return df


def has_metric_columns(name: str) -> bool:
    """지표 계산에 필요한 컬럼이 데이터에 있고 비어 있지 않은지."""
    spec = C.metrics().get(name)
    if not spec:
        return False
    if spec["agg"] == "area":
        a = area_table()
        return spec["col"] in a and a[spec["col"]].notna().any()
    df = metrics_table()
    keys = [spec.get(k) for k in ("num", "den", "weight", "col") if spec.get(k)]
    cols = [C.metric_col(k) for k in keys]
    return all(c in df for c in cols) and all(df[c].notna().any() for c in cols)


@st.cache_data
def factor_table() -> pd.DataFrame:
    p = C.path("factor_table")
    if not p.exists():
        return pd.DataFrame()
    df = _read(p)
    m = C.columns()["factor_table"]
    out = pd.DataFrame(index=df.index)
    for k, c in m.items():
        out[k] = df[c] if c and c in df else pd.NA
    out["major"], out["middle"] = out["major"].astype(str), out["middle"].astype(str)
    out["rank"] = pd.to_numeric(out["rank"], errors="coerce")
    for k in ("share", "effect", "threshold", "optimum"):
        out[k] = pd.to_numeric(out[k], errors="coerce")
    return out


@st.cache_data
def area_table() -> pd.DataFrame:
    p = C.path("area_table")
    if not p.exists():
        return pd.DataFrame()
    df = _read(p)
    m = C.columns()["area_table"]
    df = df.rename(columns={v: "_" + k for k, v in m.items() if v and v in df})
    for k in ("name", "gu"):
        if "_" + k not in df:
            df["_" + k] = ""
        df["_" + k] = df["_" + k].fillna("").astype(str)
    df["_name"] = df["_name"].where(df["_name"] != "", "상권 #" + df["_cluster"].astype(str))
    df["_label"] = (df["_gu"] + " " + df["_name"]).str.strip()
    return df.set_index("_cluster", drop=False)


@st.cache_data
def area_shapes() -> dict | None:
    p = C.path("area_shapes")
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
