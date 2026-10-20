"""설정 파일 읽기 (config/*.yaml, variables.csv). 코드에는 데이터 값·컬럼 이름을 두지 않는다."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

APP = Path(__file__).resolve().parents[1]
CONF = APP / "config"


def _yaml(name: str) -> dict:
    with open(CONF / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def settings() -> dict:
    return _yaml("settings.yaml")


@lru_cache
def columns() -> dict:
    return _yaml("columns.yaml")


@lru_cache
def metrics() -> dict:
    return _yaml("metrics.yaml")


@lru_cache
def items() -> dict:
    return _yaml("items.yaml")


@lru_cache
def detail() -> dict:
    return _yaml("detail.yaml")


@lru_cache
def variables() -> pd.DataFrame:
    v = pd.read_csv(CONF / "variables.csv", encoding="utf-8-sig", dtype=str).fillna("")
    return v.set_index("var")


def path(key: str) -> Path:
    return (APP / settings()["data"][key]).resolve()


def S(key: str, default=None):
    return settings().get(key, default)


def role(table: str, name: str) -> str | None:
    """역할 이름 → 실제 컬럼 이름 (없으면 None)."""
    return columns().get(table, {}).get(name)


def metric_col(name: str) -> str:
    """metrics.yaml 의 num/den/weight/col 값 → 상권 지표 테이블의 실제 컬럼 이름."""
    return columns().get("metrics_table", {}).get(name) or name
