"""상권 선택 팝업 (검색 / 지도에서 상권 경계 클릭) + 지도 칸의 작은 지도."""
from __future__ import annotations

import folium
import streamlit as st
from streamlit_folium import st_folium

from core import config as C
from core import state
from core.engine import compute
from core.geo import info, locate, search, shape
from core.loader import area_shapes, area_table, metrics_table
from core.ui import INDIGO, esc

ORANGE = "#F2A900"
SEOUL = (37.5665, 126.9780)
# 지도 바탕을 리포트처럼 밝은 회색으로
GRAY_TILES = ("<style>.leaflet-tile-pane{filter:grayscale(1) brightness(1.06) contrast(.88);}"
              ".leaflet-interactive:focus{outline:none;}</style>")


def selectable(major: str | None = None) -> set[int]:
    """고를 수 있는 상권 = 그 대분류 지표가 있는 상권 (대분류마다 상권 경계·번호가 다를 수 있음)"""
    df = metrics_table()
    return set(df.loc[df["_major"] == (major or st.session_state.major), "_cluster"].unique())


@st.cache_data
def _shapes_for(major: str, middle: str) -> dict | None:
    gj = area_shapes(major)
    if not gj:
        return None
    m = compute(major, middle)
    n = m["stores_latest"].to_dict() if not m.empty else {}
    ok = selectable(major)
    a = area_table(major)
    feats = []
    for f in gj["features"]:
        cid = int(f["properties"]["cluster"])
        if cid not in ok:
            continue
        lab = a.loc[cid, "_label"] if cid in a.index else f"상권 #{cid}"
        p = {"cluster": cid, "n": int(n.get(cid, 0)), "tip": f"{lab} · {middle} {int(n.get(cid, 0))}곳"}
        feats.append({**f, "properties": p})
    return {"type": "FeatureCollection", "features": feats}


@st.dialog("상권 선택", width="large")
def picker(slot: int) -> None:
    ss = st.session_state
    taken = {c for i, c in state.selected() if i != slot}
    if ss.get("pk_slot") != slot:
        ss.pk_slot, ss.pk_cand, ss.pk_click, ss.pk_shape, ss.pk_radio = slot, ss.slots[slot], None, None, None

    st.markdown(f"**상권 {state.letter(slot)}** 에 넣을 상권을 검색하거나, 지도에서 상권(경계)을 눌러 골라주세요. "
                f"색이 진할수록 {ss.middle} 가게가 많아요.")
    q = st.text_input("찾기", placeholder="구 · 동 · 도로 이름 (예: 안암동, 마포구, 고려대로)", label_visibility="collapsed")
    if q != ss.get("pk_q"):          # 새로 검색하면 이전에 고른 후보는 비우고 결과 위치로 이동
        ss.pk_q, ss.pk_cand, ss.pk_radio = q, (ss.pk_cand if not q else None), None
    res_ids: list[int] = []
    if q:
        res = search(q, selectable())
        if res.empty:
            st.info("찾는 상권이 없어요. 지도에서 골라주세요.")
        else:
            res_ids = [int(c) for c in res.index]
            m = compute(ss.major, ss.middle)
            labs = {c: f"{lab} · {ss.middle} {int(m['stores_latest'].get(c, 0)) if not m.empty else 0}곳"
                    for c, lab in zip(res.index, res["_label"])}
            pick = st.radio("검색 결과", list(labs), format_func=labs.get, horizontal=True, index=None,
                            label_visibility="collapsed", key=f"pk_radio_{q}")
            if pick is not None and pick != ss.get("pk_radio"):   # 검색 결과를 새로 골랐을 때만 반영
                ss.pk_radio = pick
                ss.pk_cand = int(pick)

    cand = ss.pk_cand
    r = info(cand) if cand is not None else {}
    center = (r.get("_lat"), r.get("_lon")) if r.get("_lat") else SEOUL
    fmap = folium.Map(location=center, zoom_start=14 if cand is not None else 11, tiles="OpenStreetMap")
    fmap.get_root().header.add_child(folium.Element(GRAY_TILES))
    gj = _shapes_for(ss.major, ss.middle)
    if gj:
        vmax = max([f["properties"]["n"] for f in gj["features"]] + [1])

        def style(f):
            p = f["properties"]
            if p["cluster"] in taken:
                return dict(color="#9A9AAE", weight=1, fillColor="#9A9AAE", fillOpacity=.35)
            return dict(color=INDIGO, weight=.6, fillColor=INDIGO, fillOpacity=.05 + .55 * min(1, (p["n"] / vmax) ** .5))
        folium.GeoJson(gj, style_function=style, highlight_function=lambda f: dict(weight=2.5, color=ORANGE),
                       tooltip=folium.GeoJsonTooltip(fields=["tip"], labels=False)).add_to(fmap)
        if res_ids:                  # 검색 결과: 주황 점선 경계 + 결과가 다 보이게 지도 맞춤
            rf = [f for c in res_ids if (f := shape(c))]
            rg = folium.GeoJson({"type": "FeatureCollection", "features": rf}, interactive=False,
                                style_function=lambda f: dict(color=ORANGE, weight=2.5, dashArray="5,4", fillOpacity=0))
            rg.add_to(fmap)
            if cand is None or cand in res_ids:
                fmap.fit_bounds(rg.get_bounds(), padding=(30, 30))
        if cand is not None and (sf := shape(cand)):
            folium.GeoJson(sf, style_function=lambda f: dict(color=ORANGE, weight=3, fillColor=ORANGE, fillOpacity=.25),
                           interactive=False).add_to(fmap)
    out = st_folium(fmap, height=440, use_container_width=True, key=f"pk_map_{slot}_{C.area_set(ss.major)}",
                    returned_objects=["last_clicked", "last_active_drawing"]) or {}
    sc, ck = out.get("last_active_drawing"), out.get("last_clicked")
    new = None
    if sc and sc != ss.pk_shape:
        ss.pk_shape, ss.pk_click = sc, ck
        new = int(sc["properties"]["cluster"])
    elif ck and ck != ss.pk_click:
        ss.pk_click = ck
        new = locate(ck["lat"], ck["lng"], selectable())
    if new is not None and new != ss.pk_cand:
        ss.pk_cand = new
        st.rerun(scope="fragment")

    cand = ss.pk_cand
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    if cand is None:
        c1.caption("아직 고른 상권이 없어요.")
    else:
        m = compute(ss.major, ss.middle)
        n = int(m["stores_latest"].get(cand, 0)) if not m.empty else 0
        c1.markdown(f"**{info(cand).get('_label')}** · {ss.middle} {n}곳")
    dup = cand in taken
    if c2.button("이 상권 선택", type="primary", disabled=cand is None or dup, use_container_width=True):
        state.set_slot(slot, cand)
        for k in ("pk_slot", "pk_cand", "pk_click", "pk_shape", "pk_radio", "pk_q"):
            ss.pop(k, None)
        st.rerun()
    if dup:
        st.caption("이미 다른 칸에 고른 상권이에요.")


def mini_map(cid: int, stores: int | None, industry: str, height: int = 190) -> None:
    """지도 칸: 밝은 회색 지도 + 점선 경계 + 왼쪽 위 이름표."""
    r = info(cid)
    sf = shape(cid)
    if not sf:
        st.caption("위치 정보 없음")
        return
    fmap = folium.Map(location=(r.get("_lat"), r.get("_lon")), zoom_start=15, tiles="OpenStreetMap",
                      zoom_control=False, scrollWheelZoom=False, dragging=False, attributionControl=False)
    g = folium.GeoJson(sf, style_function=lambda f: dict(color=INDIGO, weight=2, dashArray="5,5",
                                                          fillColor="#C9C8E8", fillOpacity=.45))
    g.add_to(fmap)
    fmap.fit_bounds(g.get_bounds(), padding=(28, 28))
    area = r.get("area_km2")
    meta = " · ".join(x for x in [r.get("_gu", ""), f"넓이 {area:.2f}km²" if isinstance(area, float) else "",
                                   f"{industry} {stores}곳" if stores is not None else ""] if x)
    tag = (f'<div style="position:absolute;left:10px;top:10px;z-index:999;background:#fff;border-radius:4px;'
           f'padding:5px 9px;box-shadow:0 1px 4px rgba(0,0,0,.15);font-family:Pretendard,sans-serif">'
           f'<div style="font-weight:800;font-size:13px;color:#1D1D2B">{esc(r.get("_name"))}</div>'
           f'<div style="font-size:11px;color:#7A7A8C">{esc(meta)}</div></div>')
    fmap.get_root().html.add_child(folium.Element(tag))
    fmap.get_root().header.add_child(folium.Element(GRAY_TILES + "<style>html,body{margin:0}</style>"))
    html = fmap.get_root().render()
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        import streamlit.components.v1 as components
        components.html(html, height=height)
