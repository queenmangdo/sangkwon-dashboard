"""상권 매출 요인 대시보드 — 실행: streamlit run app.py"""
import streamlit as st

from core import config as C
from core import state
from core.loader import factor_table
from core.ui import inject_css

st.set_page_config(page_title="상권 매출 요인", page_icon="📍", layout="wide")
state.init()
inject_css()
ss = st.session_state

pages = {
    "compare": st.Page("views/compare.py", title="상권 비교", url_path="compare", default=True),
    "detail": st.Page("views/detail.py", title="상권 상세", url_path="detail"),
}
ss._pages = pages
pg = st.navigation(list(pages.values()), position="hidden")

# ------------------------------------------------------------------ 상단 바: 대분류 / 중분류 (요인 표에서 목록을 읽음)
ft = factor_table()
total = C.S("total_label", "전체")
majors = list(dict.fromkeys(ft["major"])) if not ft.empty else [C.S("default_major")]
if ss.major not in majors:
    ss.major = majors[0]
mids = [total] + [x for x in dict.fromkeys(ft.loc[ft["major"] == ss.major, "middle"]) if x != total] if not ft.empty else [total]
if ss.middle not in mids:
    ss.middle = C.S("default_middle") if C.S("default_middle") in mids else mids[0]

t, l1, s1, l2, s2 = st.columns([5.2, .55, 1.4, .55, 1.4], vertical_alignment="center")
t.html('<span class="sk-title">상권 매출 요인</span>')
l1.html('<div class="sk-inline-label">대분류</div>')
new_major = s1.selectbox("대분류", majors, index=majors.index(ss.major), label_visibility="collapsed")
l2.html('<div class="sk-inline-label">중분류</div>')
new_mid = s2.selectbox("중분류", mids, index=mids.index(ss.middle), label_visibility="collapsed")
if new_major != ss.major:
    if C.area_set(new_major) != C.area_set(ss.major):   # 상권 경계가 다른 대분류 → 고른 상권 비움
        state.clear_all()
    ss.major, ss.middle = new_major, total
    st.rerun()
if new_mid != ss.middle:
    ss.middle = new_mid
state.sync_url()

# ------------------------------------------------------------------ 탭
cur = "detail" if pg.url_path == "detail" else "compare"
n_sel = len(state.selected())
c1, c2, _ = st.columns([1.2, 1.1, 8], gap="small")
if c1.button(f"상권 비교 · {n_sel}곳", key="tab_compare", type="primary" if cur == "compare" else "tertiary", use_container_width=True):
    st.switch_page(pages["compare"])
if c2.button("상권 상세", key="tab_detail", type="primary" if cur == "detail" else "tertiary", use_container_width=True):
    st.switch_page(pages["detail"])
st.html('<div style="border-top:1px solid #E3E3EE;margin:-8px 0 6px"></div>')

pg.run()

# ------------------------------------------------------------------ 진단: 주소 끝에 ?debug=1 을 붙이면 LLM 연결 상태를 보여줌
if st.query_params.get("debug") == "1":
    from core import llm
    with st.expander("LLM 연결 진단", expanded=True):
        st.json(llm.diagnose(test=st.button("테스트 호출")))
