"""Récupération de la page via curl_cffi (impersonation TLS Chrome) à travers le
proxy résidentiel IPRoyal. Suffit en général à passer les WAF courants
(HTTP 200) sans navigateur headless.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from curl_cffi import requests

from .config import Config


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    html: str | None
    status: int | None
    error: str | None = None


def fetch(cfg: Config) -> FetchResult:
    proxies = None
    if cfg.proxy_url:
        proxies = {"http": cfg.proxy_url, "https": cfg.proxy_url}

    last_error: str | None = None
    for attempt in range(cfg.fetch_retries + 1):
        try:
            r = requests.get(
                cfg.target_url,
                impersonate=cfg.impersonate,
                proxies=proxies,
                timeout=cfg.fetch_timeout,
                allow_redirects=True,
            )
            if r.status_code == 200 and r.text:
                return FetchResult(ok=True, html=r.text, status=200)
            last_error = f"HTTP {r.status_code}"
        except Exception as exc:  # curl_cffi lève des exceptions réseau variées
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < cfg.fetch_retries:
            time.sleep(2 * (attempt + 1))
    return FetchResult(ok=False, html=None, status=None, error=last_error)
