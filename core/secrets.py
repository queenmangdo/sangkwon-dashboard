"""API 키 읽기. 로컬(.env)과 배포(환경변수·Streamlit secrets) 어느 쪽이든 같은 이름으로 읽는다.

우선순위: 실제 환경변수(GitHub Actions·Codespaces·서버) > .env(로컬) > st.secrets(Streamlit Cloud)
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

APP = Path(__file__).resolve().parents[1]

LLM_KEY = "OPENUB_API"


@lru_cache
def _dotenv() -> dict[str, str]:
    f = APP / ".env"
    out: dict[str, str] = {}
    if not f.is_file():
        return out
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    return out


def get(name: str, default: str | None = None) -> str | None:
    """키 이름으로 값 찾기. 어디에도 없으면 default."""
    v = os.environ.get(name) or _dotenv().get(name)
    if v:
        return v
    try:
        import streamlit as st
        v = st.secrets.get(name)  # secrets 파일이 없으면 예외 → 아래에서 무시
        if v:
            return str(v)
    except Exception:
        pass
    return default


def source(name: str) -> str | None:
    """키가 어디서 읽혔는지 (진단용): 환경변수 | .env | st.secrets | None. 값은 돌려주지 않는다."""
    if os.environ.get(name):
        return "환경변수"
    if _dotenv().get(name):
        return ".env"
    try:
        import streamlit as st
        if st.secrets.get(name):
            return "st.secrets"
    except Exception:
        pass
    return None


def llm_key() -> str | None:
    return get(LLM_KEY)
