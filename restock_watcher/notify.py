"""Envoi de notifications ntfy (endpoint JSON, UTF-8 propre pour titres accentués
et emojis). Réutilise curl_cffi pour ne pas ajouter de dépendance.

Retries + log en cas d'échec : une alerte de réappro non délivrée est un échec
critique (l'appelant s'appuie sur le booléen retourné pour NE PAS avancer l'état).
"""

from __future__ import annotations

import logging
import time

from curl_cffi import requests

from .config import Config

log = logging.getLogger("restock-watcher.notify")

# niveaux logiques -> priorité ntfy (1=min .. 5=urgent)
_PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}


def notify(
    cfg: Config,
    *,
    title: str,
    message: str,
    priority: str = "default",
    tags: list[str] | None = None,
    click: str | None = None,
    retries: int = 3,
) -> bool:
    """Publie sur ntfy. Retourne True seulement si délivré (2xx). Retente sur
    échec réseau/5xx ; logge en erreur si tout échoue."""
    payload: dict = {
        "topic": cfg.ntfy_topic,
        "title": title,
        "message": message,
        "priority": _PRIORITY.get(priority, 3),
    }
    if tags:
        payload["tags"] = tags
    if click:
        payload["click"] = click

    headers = {}
    if cfg.ntfy_token:
        headers["Authorization"] = f"Bearer {cfg.ntfy_token}"

    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(cfg.ntfy_server + "/", json=payload, headers=headers, timeout=15)
            if r.status_code < 300:
                return True
            last_error = f"HTTP {r.status_code}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(2 * (attempt + 1))

    log.error(
        "Envoi ntfy ÉCHOUÉ après %d tentatives (%s) — titre=%r", retries + 1, last_error, title
    )
    return False
