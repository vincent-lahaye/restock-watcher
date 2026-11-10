"""Cadence adaptative : dense pendant les créneaux de réappro (Europe/Paris),
filet léger le reste du temps, avec jitter pour ne pas taper pile à la minute.
Fonctions pures (on injecte `now`) -> testables.
"""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import Config


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _in_window(now: datetime, start: str, end: str) -> bool:
    s, e, t = _hhmm(start), _hhmm(end), now.time()
    if s <= e:
        return s <= t <= e
    return t >= s or t <= e  # créneau à cheval sur minuit (ex 23:55-00:30)


def in_any_window(now: datetime, windows: list[tuple[str, str]]) -> bool:
    return any(_in_window(now, s, e) for s, e in windows)


def seconds_to_next_window(now: datetime, windows: list[tuple[str, str]]) -> int:
    """Secondes avant le prochain *début* de créneau (aujourd'hui ou demain)."""
    if not windows:
        return 10**9  # pas de créneau -> "jamais" (le filet prendra le relais)
    candidates: list[datetime] = []
    for start, _end in windows:
        st = _hhmm(start)
        today = now.replace(hour=st.hour, minute=st.minute, second=0, microsecond=0)
        candidates.append(today if today > now else today + timedelta(days=1))
    nxt = min(candidates)
    return int((nxt - now).total_seconds())


def next_sleep(cfg: Config, now: datetime | None = None) -> int:
    tz = ZoneInfo(cfg.timezone)
    now = now or datetime.now(tz)

    if not cfg.windows:
        base = cfg.poll_idle_seconds  # aucun créneau -> filet uniquement
    elif in_any_window(now, cfg.windows):
        base = cfg.poll_window_seconds
    else:
        # dormir jusqu'au prochain créneau, plafonné par le filet (réappro hors créneau)
        base = min(cfg.poll_idle_seconds, seconds_to_next_window(now, cfg.windows))

    jitter = random.randint(-cfg.jitter_seconds, cfg.jitter_seconds) if cfg.jitter_seconds else 0
    return max(30, base + jitter)
