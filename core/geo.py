"""상권 위치: 경계·이름·검색·좌표 → 상권."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import streamlit as st

from .loader import area_shapes, area_table


def info(cid: int) -> dict:
    a = area_table()
    return a.loc[cid].to_dict() if (not a.empty and cid in a.index) else {"_label": f"상권 #{cid}", "_name": f"상권 #{cid}", "_gu": ""}


@st.cache_data
def shape_index() -> dict[int, dict]:
    gj = area_shapes() or {"features": []}
    return {int(f["properties"]["cluster"]): f for f in gj["features"]}


def shape(cid: int) -> dict | None:
    return shape_index().get(cid)


def _inside(geom: dict, x: float, y: float) -> bool:
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        ring, inside, j = poly[0], False, len(poly[0]) - 1
        for i in range(len(ring)):
            (xi, yi), (xj, yj) = ring[i], ring[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi:
                inside = not inside
            j = i
        if inside:
            return True
    return False


def locate(lat: float, lon: float, allowed: set[int] | None = None) -> int | None:
    """좌표가 들어 있는 상권 → 없으면 중심이 가장 가까운 상권."""
    for cid, f in shape_index().items():
        if (allowed is None or cid in allowed) and _inside(f["geometry"], lon, lat):
            return cid
    a = area_table().dropna(subset=["_lat", "_lon"])
    if allowed is not None:
        a = a[a.index.isin(allowed)]
    if a.empty:
        return None
    d = (a["_lat"] - lat) ** 2 + ((a["_lon"] - lon) * np.cos(np.radians(lat))) ** 2
    return int(d.idxmin())


def search(q: str, allowed: set[int] | None = None, limit: int = 8) -> pd.DataFrame:
    """구·동 이름·상권 번호로 찾기. 없으면 (KAKAO_REST_API_KEY 가 있을 때) 주소 → 좌표 → 상권."""
    a = area_table()
    if allowed is not None:
        a = a[a.index.isin(allowed)]
    q = q.strip().lstrip("#")
    if not q or a.empty:
        return a.head(0)
    if q.isdigit() and int(q) in a.index:
        return a.loc[[int(q)]]
    hit = a[a["_label"].str.contains(q, regex=False)].head(limit)
    if len(hit):
        return hit
    pt = geocode(q)
    if pt:
        cid = locate(*pt, allowed)
        return a.loc[[cid]] if cid is not None else a.head(0)
    return a.head(0)


def geocode(q: str) -> tuple[float, float] | None:
    key = os.environ.get("KAKAO_REST_API_KEY")
    if not key:
        return None
    try:
        import requests
        r = requests.get("https://dapi.kakao.com/v2/local/search/address.json",
                         headers={"Authorization": f"KakaoAK {key}"}, params={"query": q}, timeout=5)
        docs = r.json().get("documents", [])
        return (float(docs[0]["y"]), float(docs[0]["x"])) if docs else None
    except Exception:
        return None
