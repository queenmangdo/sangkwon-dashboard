"""SNS 관심 트렌드 — area.csv 의 sns_keyword_details(JSON) / sns_hashtags 를 화면용으로 정리.

데이터는 prep/build_sns.py 가 채운다.
  sns_hashtags         "#안국화덕피자|#안국한옥카페|…"   (비교 표 '기타 › SNS 트렌드 #' 행)
  sns_keyword_details  [{"keyword": "안국 화덕피자", "hashtag": "안국화덕피자", "category": "음식",
                         "mentions": 13, "status": "상승", "growth_pct": 12.3}, …]
                       status / growth_pct 는 네이버 DataLab 결과가 있을 때만 들어 있음
"""
from __future__ import annotations

import json
from html import escape

# 대분류(앱 상단 선택) → 먼저 보여줄 SNS 키워드 업종
MAJOR_FIRST = {
    "음식점": ["음식", "카페·디저트", "주점"],
    "카페": ["카페·디저트"],
    "주점": ["주점"],
    "오락": ["오락"],
    "소매": ["소매·쇼핑"],
    "서비스": ["서비스"],
}

STATUS_CLASS = {"상승": "up", "상승지속": "up", "유지": "flat", "보합": "flat", "하락": "down", "둔화": "down"}


def parse_details(raw) -> list[dict]:
    if not isinstance(raw, str) or not raw.strip() or raw.strip() == "[]":
        return []
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [x for x in items if isinstance(x, dict) and (x.get("keyword") or x.get("hashtag"))]


def parse_tags(raw) -> list[str]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    return [t.strip() for t in raw.replace(",", "|").split("|") if t.strip()]


def ordered(items: list[dict], major: str) -> list[dict]:
    """고른 대분류와 맞는 업종 키워드를 앞으로, 그 안에서는 언급 많은 순."""
    first = MAJOR_FIRST.get(major, [])
    return sorted(items, key=lambda x: (x.get("category") not in first, -(x.get("mentions") or 0)))


def cards_html(items: list[dict], major: str, limit: int = 8) -> str:
    out = []
    first = MAJOR_FIRST.get(major, [])
    for x in ordered(items, major)[:limit]:
        kw = x.get("keyword") or x.get("hashtag")
        cat = x.get("category") or "기타"
        mine = " mine" if cat in first else ""
        meta = []
        if x.get("mentions"):
            meta.append(f"인스타 게시물 {int(x['mentions'])}개")
        status = x.get("status")
        trend = ""
        if status == "자료부족":
            meta.append("검색 추이 부족")
        elif status:
            cls = STATUS_CLASS.get(str(status), "flat")
            g = x.get("growth_pct")
            if isinstance(g, (int, float)):
                label = f"검색 {float(g):+.0f}%"
            else:
                label = {"up": "검색 늘어남", "down": "검색 줄어듦"}.get(cls, "검색 비슷함")
            trend = f'<span class="tr {cls}">{escape(label)}</span>'
            if x.get("slowing"):
                meta.append("최근 1주 주춤")
        else:
            meta.append("검색량 집계 전")
        out.append(
            f'<div class="sk-kwc{mine}"><div class="top"><span class="cat">{escape(cat)}</span>{trend}</div>'
            f'<div class="kw">{escape(str(kw))}</div><div class="meta">'
            + "".join(f"<span>{escape(m)}</span>" for m in meta) + "</div></div>"
        )
    return '<div class="sk-kwgrid">' + "".join(out) + "</div>"
