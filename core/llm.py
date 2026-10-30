"""LLM 호출 (OpenAI 호환 chat completions). 키·모델·주소는 코드에 두지 않는다.

- 키: core/secrets.py 의 OPENUB_API
- 모델·주소: config/settings.yaml → llm
실패하면 None 을 돌려주니, 부르는 쪽은 자리 표시 문구로 되돌리면 된다.
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import requests

from . import config as C
from . import secrets

_cache: dict[str, str] = {}      # 성공한 응답만 (실패는 다음에 다시 시도). 같은 입력은 앱이 켜져 있는 동안 재사용
_CACHE_MAX = 2000


def enabled() -> bool:
    return bool(secrets.llm_key() and C.S("llm", {}).get("model"))


def _call(system: str, user: str) -> str | None:
    cfg = C.S("llm", {})
    k = hashlib.sha1(f'{cfg["model"]}\n{system}\n{user}'.encode()).hexdigest()
    if k in _cache:
        return _cache[k]
    effort = cfg.get("reasoning_effort")
    try:
        r = requests.post(
            f"{cfg.get('base_url', 'https://api.openai.com/v1').rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {secrets.llm_key()}"},
            json={"model": cfg["model"],
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                  **({"reasoning_effort": effort} if effort else {})},
            timeout=cfg.get("timeout", 20),
        )
        r.raise_for_status()
        text = (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return None
    if not text:
        return None
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[k] = text
    return text


def ask(system: str, payload: dict) -> str | None:
    """system 지침 + JSON 입력 → 응답 문장. 키·모델이 없거나 실패하면 None."""
    if not enabled():
        return None
    return _call(system, json.dumps(payload, ensure_ascii=False, sort_keys=True))


def ask_many(reqs: list[tuple[str, dict] | None]) -> list[str | None]:
    """여러 요청을 동시에 보내 순서대로 돌려줌. None 요청은 건너뜀."""
    if not enabled() or not any(reqs):
        return [None] * len(reqs)
    with ThreadPoolExecutor(max_workers=min(len(reqs), 6)) as ex:
        futs = [ex.submit(ask, *r) if r else None for r in reqs]
        return [f.result() if f else None for f in futs]
