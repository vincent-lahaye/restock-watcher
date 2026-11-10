"""Configuration du watcher — tout vient de l'environnement (injecté par le
compose ou un fichier .env). Aucun secret en dur.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Variable d'environnement requise manquante : {name}")
    return val


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    # --- Cible ---
    target_url: str
    product_label: str  # nom lisible dans les notifs

    # --- Proxy résidentiel (Scrapling/curl_cffi) ---
    proxy_auth: str | None       # user:pass[_country-xx] IPRoyal, ou None = pas de proxy
    proxy_endpoint: str          # ex geo.iproyal.com:12321
    impersonate: str             # profil TLS curl_cffi (chrome, chrome124, ...)
    require_proxy: bool          # refuse de démarrer sans proxy (fail-loud)

    # --- LLM de qualification ---
    llm_provider: str            # "openai_compatible" (Kimi/OpenRouter) | "anthropic"
    llm_base_url: str | None     # base_url OpenAI-compatible (ex https://api.moonshot.ai/v1)
    llm_api_key: str | None
    llm_model: str               # ex kimi-k2.6 | moonshotai/kimi-k2.6 | claude-haiku-4-5

    # --- ntfy ---
    ntfy_server: str             # ex https://ntfy.sh
    ntfy_topic: str
    ntfy_token: str | None       # bearer optionnel (topics protégés)

    # --- Cadence (Europe/Paris) ---
    timezone: str
    windows: list[tuple[str, str]]  # créneaux serrés "HH:MM"-"HH:MM"
    poll_window_seconds: int        # période dans un créneau
    poll_idle_seconds: int          # période filet hors créneau
    jitter_seconds: int             # +/- aléatoire ajouté à chaque sleep

    # --- Robustesse ---
    fetch_timeout: int
    fetch_retries: int
    fail_alert_threshold: int    # nb d'échecs consécutifs avant alerte ops
    state_path: str

    @property
    def proxy_url(self) -> str | None:
        if not self.proxy_auth:
            return None
        return f"http://{self.proxy_auth}@{self.proxy_endpoint}"


def _parse_windows(raw: str) -> list[tuple[str, str]]:
    """"08:55-09:45,14:55-15:45" -> [("08:55","09:45"), ("14:55","15:45")]."""
    windows: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        start, _, end = chunk.partition("-")
        windows.append((start.strip(), end.strip()))
    return windows


def load_config() -> Config:
    provider = _env("LLM_PROVIDER", "openai_compatible")
    cfg = Config(
        target_url=_env("TARGET_URL", required=True),
        product_label=_env("PRODUCT_LABEL", "produit surveillé"),
        proxy_auth=_env("IP_ROYAL_AUTH"),
        proxy_endpoint=_env("PROXY_ENDPOINT", "geo.iproyal.com:12321"),
        impersonate=_env("IMPERSONATE", "chrome"),
        require_proxy=_env_bool("REQUIRE_PROXY", True),
        llm_provider=provider,
        llm_base_url=_env("LLM_BASE_URL", "https://api.moonshot.ai/v1"),
        llm_api_key=_env("LLM_API_KEY"),
        llm_model=_env("LLM_MODEL", "kimi-k2.6"),
        ntfy_server=_env("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
        ntfy_topic=_env("NTFY_TOPIC", required=True),
        ntfy_token=_env("NTFY_TOKEN"),
        timezone=_env("TZ", "Europe/Paris"),
        windows=_parse_windows(_env("POLL_WINDOWS", "08:55-09:45,14:55-15:45")),
        poll_window_seconds=_env_int("POLL_WINDOW_SECONDS", 120),
        poll_idle_seconds=_env_int("POLL_IDLE_SECONDS", 1800),
        jitter_seconds=_env_int("JITTER_SECONDS", 30),
        fetch_timeout=_env_int("FETCH_TIMEOUT", 45),
        fetch_retries=_env_int("FETCH_RETRIES", 2),
        fail_alert_threshold=_env_int("FAIL_ALERT_THRESHOLD", 4),
        state_path=_env("STATE_PATH", "/data/state.json"),
    )
    if cfg.require_proxy and not cfg.proxy_auth:
        raise RuntimeError(
            "IP_ROYAL_AUTH manquant/vide alors que REQUIRE_PROXY=true : refus de "
            "démarrer sans proxy résidentiel (sinon scraping depuis l'IP publique du "
            "serveur, déanonymisé et probablement bloqué par le WAF). Vérifier la variable "
            "IP_ROYAL_AUTH (ou mettre REQUIRE_PROXY=false)."
        )
    return cfg
