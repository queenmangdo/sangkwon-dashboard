"""페이지 간 공유 상태 (session_state ↔ URL).  예: ?major=음식점&middle=한식&c=12,301,-&d=12"""
from __future__ import annotations

import streamlit as st

from . import config as C


def init() -> None:
    ss = st.session_state
    if "slots" in ss:
        return
    qp = st.query_params
    n = int(C.S("max_slots", 3))
    slots: list[int | None] = [None] * n
    for i, tok in enumerate(qp.get("c", "").split(",")[:n]):
        if tok.strip().isdigit():
            slots[i] = int(tok)
    ss.slots = slots
    ss.major = qp.get("major") or C.S("default_major")
    ss.middle = qp.get("middle") or C.S("default_middle")
    d = qp.get("d", "")
    ss.detail = int(d) if d.isdigit() else next((c for c in slots if c is not None), None)


def sync_url() -> None:
    ss = st.session_state
    st.query_params.update({
        "major": ss.major, "middle": ss.middle,
        "c": ",".join("-" if s is None else str(s) for s in ss.slots),
        "d": "" if ss.detail is None else str(ss.detail),
    })


def selected() -> list[tuple[int, int]]:
    return [(i, c) for i, c in enumerate(st.session_state.slots) if c is not None]


def set_slot(i: int, cid: int) -> None:
    st.session_state.slots[i] = cid
    if st.session_state.detail is None:
        st.session_state.detail = cid
    sync_url()


def clear_slot(i: int) -> None:
    ss = st.session_state
    cid, ss.slots[i] = ss.slots[i], None
    if ss.detail == cid:
        ss.detail = next((c for _, c in selected()), None)
    sync_url()


def letter(i: int) -> str:
    return "ABCDEFGH"[i]
