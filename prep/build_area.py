"""격자 파일(gpkg) → 상권 단위 표 + 경계 + 이름(동 · 대표 도로).

클러스터가 바뀌면 이 스크립트만 다시 돌리면 된다. 도로·행정동 데이터는 처음 한 번 받아 data/ 에 저장해 두고 재사용.

실행 (geopandas, requests 필요 — 앱 실행에는 불필요):
    python prep/build_area.py --gpkg data/cluster_seoul_t9_202607.gpkg

입력
    --gpkg   격자 × 상권 번호 파일. 필요한 컬럼: cluster(--cluster-col), geometry
    --adm    행정동 경계 geojson (없으면 자동으로 받음: github.com/vuski/admdongkor)
    --roads  도로 geojson (없으면 OpenStreetMap 에서 서울 도로를 자동으로 받음). --no-roads 면 도로 없이 동 이름만

출력 (data/)
    area.csv              cluster, name, gu, dong, road, grid_count, area_km2, lat, lon, rent_per_m2, sns_hashtags
    area_shapes.geojson   상권 경계 (WGS84)

대분류마다 다른 상권 경계 (settings.yaml → area_sets)
    격자 모양은 --gpkg 그대로 쓰고, 상권 번호만 다른 클러스터링 결과(grid_id, cluster CSV)로 바꿔 만든다.
    python prep/build_area.py --cluster-csv ../data_rent/cluster_retail_t9_202607.csv --suffix _retail \
        --rent ../data_rent/cluster_rent_retail_2026q2.csv --copy-from data/area.csv
    --suffix     출력 이름 뒤에 붙임 → data/area_retail.csv, data/area_shapes_retail.geojson
    --rent       상권별 임대료 CSV (rent_1f, 천 원/㎡) → rent_per_m2 (원/㎡)
    --copy-from  기존 경계의 area.csv. SNS 키워드 칸을 격자가 가장 많이 겹치는 기존 상권에서 가져옴
                 (기존 상권 번호 = --gpkg 의 cluster 칸)

이름 규칙
    1. 동 1개(상권이 가장 많이 걸친 행정동) · 대표 도로 1개   예) 안암동 · 고려대로
    2. 대표 도로 = 경계 안을 지나는 이름 있는 도로 중 대로 > 로 > 길 순, 같은 급이면 경계 안 길이가 긴 도로
    3. 같은 구 안에서 이름이 겹치면 다음 순위 도로로 바꿔 구분 (다 써도 겹치면 두 번째 동을 덧붙임)
    4. 이름 있는 도로가 없으면 동 1~2개
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

APP = Path(__file__).resolve().parents[1]
DATA = APP / "data"
FUTURE_COLS = ["rent_per_m2", "sns_hashtags"]
COPY_COLS = ["sns_hashtags_main", "sns_hashtags_detail", "sns_hashtags", "sns_keyword_details"]   # 동네 단위 값 (--copy-from)
ADM_URL = "https://raw.githubusercontent.com/vuski/admdongkor/master/ver20230701/HangJeongDong_ver20230701.geojson"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
SEOUL_BBOX = (37.41, 126.76, 37.72, 127.19)       # 남, 서, 북, 동
ROAD_CLASSES = "trunk|primary|secondary|tertiary|unclassified|residential|living_street"
MIN_ROAD_M = 60                                    # 경계 안 길이가 이보다 짧은 도로는 대표 도로 후보에서 제외
TIER = [("대로", 0), ("로", 1), ("길", 2)]         # 이름 끝 글자로 도로 급 판단 (대로를 로보다 먼저 검사)


# ------------------------------------------------------------------ 외부 데이터 받기 (처음 한 번)
def fetch_adm(path: Path) -> Path | None:
    if path.exists():
        return path
    try:
        import requests
        print("행정동 경계 받는 중…")
        r = requests.get(ADM_URL, timeout=120)
        r.raise_for_status()
        path.write_bytes(r.content)
        return path
    except Exception as e:  # noqa: BLE001
        print(f"  행정동 경계를 받지 못했어요 ({e}). 이름이 '상권 #번호'로 나와요.")
        return None


def fetch_roads(path: Path) -> Path | None:
    """OpenStreetMap(Overpass API)에서 서울 범위의 이름 있는 도로를 받아 geojson 으로 저장.

    서버 부담을 줄이려고 서울을 4칸으로 나눠 차례로 받는다. 칸마다 서버를 바꿔가며 다시 시도하고,
    '요청이 많다(429)'·'바쁘다(504)'면 잠깐 기다렸다 다시 시도한다.
    """
    if path.exists():
        return path
    import time
    import requests
    headers = {"User-Agent": "sangkwon-report/1.0 (Seoul commercial area dashboard; contact: local user)",
               "Accept": "application/json"}
    s, w, n, e = SEOUL_BBOX
    mid_lat, mid_lon = (s + n) / 2, (w + e) / 2
    tiles = [(s, w, mid_lat, mid_lon), (s, mid_lon, mid_lat, e), (mid_lat, w, n, mid_lon), (mid_lat, mid_lon, n, e)]
    ways: dict[int, dict] = {}
    tile_dir = path.parent / "roads_tiles"          # 칸별로 저장 → 중간에 실패해도 다시 실행하면 남은 칸만 받음
    tile_dir.mkdir(exist_ok=True)
    print("서울 도로 데이터 받는 중… (4칸으로 나눠 받아요, 몇 분 걸릴 수 있어요)")
    for ti, (ts, tw, tn, te) in enumerate(tiles, 1):
        tf = tile_dir / f"tile_{ti}.json"
        if tf.exists():
            for el in json.loads(tf.read_text(encoding="utf-8")):
                ways[el["id"]] = el
            print(f"  {ti}/4칸: 저장해 둔 파일 사용 (지금까지 도로 {len(ways):,}개)")
            continue
        q = (f'[out:json][timeout:180];way["highway"~"^({ROAD_CLASSES})$"]["name"]({ts},{tw},{tn},{te});'
             f'out tags geom qt;')
        ok = False
        for attempt in range(6):
            url = OVERPASS[attempt % len(OVERPASS)]
            try:
                r = requests.post(url, data={"data": q}, headers=headers, timeout=240)
                if r.status_code in (429, 504):
                    wait = 20 * (attempt + 1)
                    print(f"  {ti}/4칸: {url.split('/')[2]} 가 바빠요({r.status_code}). {wait}초 뒤 다시 시도")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                got = [el for el in r.json().get("elements", []) if el.get("geometry") and el.get("tags")]
                tf.write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
                for el in got:
                    ways[el["id"]] = el
                print(f"  {ti}/4칸 완료 (지금까지 도로 {len(ways):,}개)")
                ok = True
                break
            except Exception as ex:  # noqa: BLE001
                print(f"  {ti}/4칸: {url.split('/')[2]} 실패 ({ex})")
                time.sleep(5)
        if not ok:
            print("  도로 데이터를 다 받지 못했어요. 이번엔 동 이름만으로 만들어요.\n"
                  "  받은 칸은 저장해 뒀으니, 몇 분 뒤 같은 명령을 다시 실행하면 남은 칸만 받아요.")
            return None
        time.sleep(3)
    feats = []
    for el in ways.values():
        tags = el["tags"]
        name = tags.get("name:ko") or tags.get("name")
        if not name:
            continue
        feats.append({"type": "Feature", "properties": {"name": name, "highway": tags.get("highway", "")},
                      "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in el["geometry"]]}})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
    print(f"  도로 {len(feats):,}개 저장 → {path.relative_to(APP)}")
    return path


# ------------------------------------------------------------------ 이름 계산
def road_tier(name: str) -> int | None:
    base = re.sub(r"\s+", "", str(name))
    for suf, t in TIER:
        if base.endswith(suf):
            return t
    return None


def road_candidates(shapes: gpd.GeoDataFrame, roads_path: Path) -> dict[int, list[tuple[str, float]]]:
    """상권별 대표 도로 후보 (대로 > 로 > 길, 같은 급이면 경계 안 길이 순)."""
    roads = gpd.read_file(roads_path)
    roads = roads[roads["name"].notna()].copy()
    roads["tier"] = roads["name"].map(road_tier)
    roads = roads[roads["tier"].notna()].to_crs(shapes.crs).explode(index_parts=False)
    poly = shapes.reset_index()[["cluster", "geometry"]]
    pairs = gpd.sjoin(roads[["name", "tier", "geometry"]], poly, predicate="intersects", how="inner")
    if pairs.empty:
        return {}
    shp = poly.set_index("cluster").geometry
    other = gpd.GeoSeries(shp.reindex(pairs["cluster"]).values, index=pairs.index, crs=shapes.crs)
    pairs["len"] = pairs.geometry.intersection(other).length
    agg = pairs.groupby(["cluster", "name"]).agg(tier=("tier", "min"), len=("len", "sum")).reset_index()
    agg = agg[agg["len"] >= MIN_ROAD_M].sort_values(["cluster", "tier", "len"], ascending=[True, True, False])
    return {c: list(zip(g["name"], g["len"])) for c, g in agg.groupby("cluster")}


def make_names(out: pd.DataFrame, cands: dict[int, list[tuple[str, float]]]) -> pd.DataFrame:
    out["road"] = ""
    pick = {c: 0 for c in out.index}
    for c in out.index:
        if cands.get(c):
            out.at[c, "road"] = cands[c][0][0]
    for _ in range(10):  # 같은 구에서 이름이 겹치면 다음 도로로
        lab = out["gu"].fillna("") + "|" + out["dong1"] + "|" + out["road"]
        dup = lab[lab.duplicated(keep=False) & (out["road"] != "")]
        if dup.empty:
            break
        changed = False
        for _, grp in dup.groupby(dup):
            # 그 도로가 가장 길게 지나는 상권은 그대로, 나머지만 다음 후보로
            members = sorted(grp.index, key=lambda c: -cands[c][pick[c]][1])
            for c in members[1:]:
                if pick[c] + 1 < len(cands.get(c, [])):
                    pick[c] += 1
                    out.at[c, "road"] = cands[c][pick[c]][0]
                    changed = True
        if not changed:
            break
    out["name"] = [f"{d1} · {r}" if r else (dn or "") for d1, r, dn in zip(out["dong1"], out["road"], out["dong"])]
    lab = out["gu"].fillna("") + "|" + out["name"]
    still = lab.duplicated(keep=False) & (out["road"] != "") & (out["dong2"] != "")
    out.loc[still, "name"] = out.loc[still, "name"] + " · " + out.loc[still, "dong2"]
    return out


def copy_from_base(g: gpd.GeoDataFrame, base: pd.DataFrame, cluster_col: str, path: Path) -> pd.DataFrame:
    """기존 경계의 상권 단위 값(COPY_COLS)을 격자가 가장 많이 겹치는 기존 상권에서 가져옴. index = 새 상권 번호"""
    pair = g[["grid_id", cluster_col]].merge(base, on="grid_id").dropna()
    n = pair.groupby([cluster_col, "_base"]).size().rename("n").reset_index()
    top = n.sort_values("n", ascending=False).drop_duplicates(cluster_col).set_index(cluster_col)["_base"].astype(int)
    src = pd.read_csv(path, encoding="utf-8-sig").set_index("cluster")
    cols = [c for c in COPY_COLS if c in src]
    return src.reindex(top.to_numpy())[cols].set_axis(top.index)


# ------------------------------------------------------------------ 메인
def main(gpkg: Path, adm: Path | None, roads: Path | None, cluster_col: str = "cluster",
         cluster_csv: Path | None = None, suffix: str = "", rent: Path | None = None, copy_from: Path | None = None) -> None:
    g = gpd.read_file(gpkg)
    base = None
    if cluster_csv is not None:     # 격자 모양은 gpkg 그대로, 상권 번호만 다른 클러스터링 결과로
        base = g[["grid_id", cluster_col]].rename(columns={cluster_col: "_base"})
        c = pd.read_csv(cluster_csv, encoding="utf-8-sig")[["grid_id", "cluster"]].rename(columns={"cluster": cluster_col})
        g = g.drop(columns=[cluster_col]).merge(c, on="grid_id", how="left")
    g = g[g[cluster_col].notna()].copy()
    g[cluster_col] = g[cluster_col].astype(int)
    cell_km2 = g.geometry.iloc[0].area / 1e6

    shapes = g[[cluster_col, "geometry"]].dissolve(cluster_col)
    shapes.index.name = "cluster"
    out = pd.DataFrame(index=shapes.index)
    out["grid_count"] = g.groupby(cluster_col).size()
    out["area_km2"] = (out["grid_count"] * cell_km2).round(4)
    pts = shapes.representative_point().to_crs(4326)
    out["lat"], out["lon"] = pts.y.round(6), pts.x.round(6)

    out["gu"], out["dong"], out["dong1"], out["dong2"] = "", "", "", ""
    if adm is not None and adm.exists():
        a = gpd.read_file(adm)
        a = a[a["sidonm"] == "서울특별시"].to_crs(shapes.crs)[["sggnm", "adm_nm", "geometry"]]
        a["dong_nm"] = a["adm_nm"].str.split().str[-1]
        inter = gpd.overlay(shapes.reset_index(), a, how="intersection", keep_geom_type=True)
        inter["a"] = inter.area
        top = inter.sort_values(["cluster", "a"], ascending=[True, False]).groupby("cluster").head(2)
        out["gu"] = top.groupby("cluster")["sggnm"].first()
        out["dong1"] = top.groupby("cluster")["dong_nm"].first()
        out["dong2"] = top.groupby("cluster")["dong_nm"].agg(lambda s: s.iloc[1] if len(s) > 1 and s.iloc[1] != s.iloc[0] else "")
        out["dong"] = top.groupby("cluster")["dong_nm"].agg(lambda s: " · ".join(dict.fromkeys(s)))
    out[["gu", "dong", "dong1", "dong2"]] = out[["gu", "dong", "dong1", "dong2"]].fillna("")

    cands = road_candidates(shapes, roads) if roads is not None and roads.exists() else {}
    out = make_names(out, cands)
    out["name"] = out["name"].where(out["name"] != "", "상권 #" + out.index.astype(str))
    for c in FUTURE_COLS:
        out[c] = pd.NA
    cols = ["cluster", "name", "gu", "dong", "road", "grid_count", "area_km2", "lat", "lon", *FUTURE_COLS]
    if rent is not None:
        r = pd.read_csv(rent, encoding="utf-8-sig").set_index("cluster")["rent_1f"]   # 천 원/㎡
        out["rent_per_m2"] = (out.index.map(r).astype(float) * 1000).round(0)
    if copy_from is not None and base is not None:
        cp = copy_from_base(g, base, cluster_col, copy_from)
        for c in cp.columns:
            out[c] = cp[c].reindex(out.index)
        cols += [c for c in cp.columns if c not in cols]

    DATA.mkdir(exist_ok=True)
    f_csv, f_geo = f"area{suffix}.csv", f"area_shapes{suffix}.geojson"
    out.reset_index()[cols].to_csv(DATA / f_csv, index=False, encoding="utf-8-sig")
    s = shapes.to_crs(4326).reset_index()
    s["geometry"] = s.geometry.simplify(0.00005)
    s.to_file(DATA / f_geo, driver="GeoJSON", COORDINATE_PRECISION=6)

    lab = out["gu"] + " " + out["name"]
    print(f"상권 {len(out)}곳 저장 → data/{f_csv}, data/{f_geo}")
    print(f"  도로 이름 붙은 상권 {(out['road'] != '').sum()}곳 · 같은 이름 남은 상권 {lab.duplicated(keep=False).sum()}곳")
    if rent is not None:
        print(f"  임대료 있는 상권 {out['rent_per_m2'].notna().sum()}곳")
    if "sns_hashtags" in cols:
        print(f"  SNS 키워드 있는 상권 {out['sns_hashtags'].notna().sum()}곳")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpkg", type=Path, default=DATA / "cluster_seoul_t9_202607.gpkg")
    ap.add_argument("--adm", type=Path, default=DATA / "admdong_seoul.geojson")
    ap.add_argument("--roads", type=Path, default=DATA / "roads_seoul.geojson")
    ap.add_argument("--no-roads", action="store_true")
    ap.add_argument("--cluster-col", default="cluster")
    ap.add_argument("--cluster-csv", type=Path, help="상권 번호만 바꿀 클러스터링 결과 (grid_id, cluster)")
    ap.add_argument("--suffix", default="", help="출력 이름 뒤에 붙임 (예: _retail)")
    ap.add_argument("--rent", type=Path, help="상권별 임대료 CSV (cluster, rent_1f)")
    ap.add_argument("--copy-from", type=Path, help="SNS 키워드를 가져올 기존 경계의 area.csv")
    a = ap.parse_args()
    if not a.gpkg.exists():
        sys.exit(f"격자 파일이 없어요: {a.gpkg}")
    DATA.mkdir(exist_ok=True)
    adm = fetch_adm(a.adm)
    roads = None if a.no_roads else fetch_roads(a.roads)
    main(a.gpkg, adm, roads, a.cluster_col, a.cluster_csv, a.suffix, a.rent, a.copy_from)
