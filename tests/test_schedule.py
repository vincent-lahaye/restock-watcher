"""Tests du scheduler (fonctions pures, now injecté)."""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from restock_watcher.config import Config  # noqa: E402
from restock_watcher.schedule import in_any_window, next_sleep  # noqa: E402

TZ = ZoneInfo("Europe/Paris")


def _cfg(windows, idle=1800, win=120):
    return Config(
        target_url="x", product_label="p", proxy_auth="a", proxy_endpoint="e",
        impersonate="chrome", require_proxy=False, llm_provider="openai_compatible",
        llm_base_url=None, llm_api_key=None, llm_model="m", ntfy_server="https://ntfy.sh",
        ntfy_topic="t", ntfy_token=None, timezone="Europe/Paris", windows=windows,
        poll_window_seconds=win, poll_idle_seconds=idle, jitter_seconds=0,
        fetch_timeout=45, fetch_retries=2, fail_alert_threshold=4, state_path="/tmp/s",
    )


def test_midnight_window():
    w = [("23:55", "00:30")]
    assert in_any_window(datetime(2026, 7, 24, 23, 56, tzinfo=TZ), w)
    assert in_any_window(datetime(2026, 7, 25, 0, 10, tzinfo=TZ), w)
    assert not in_any_window(datetime(2026, 7, 24, 12, 0, tzinfo=TZ), w)


def test_empty_windows_no_crash():
    c = _cfg([])
    # ne doit PAS lever (min([]) ) et retomber sur le filet
    assert next_sleep(c, datetime(2026, 7, 24, 12, 0, tzinfo=TZ)) == 1800


def test_in_window_dense():
    c = _cfg([("08:55", "09:45")])
    assert next_sleep(c, datetime(2026, 7, 24, 9, 10, tzinfo=TZ)) == 120


def test_out_window_capped_to_next_start():
    c = _cfg([("08:55", "09:45")])
    # à 08:50 -> prochain créneau dans 300 s (< filet 1800) -> dort 300 s
    assert next_sleep(c, datetime(2026, 7, 24, 8, 50, tzinfo=TZ)) == 300


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
