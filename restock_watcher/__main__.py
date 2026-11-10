"""Boucle principale du watcher.

Cycle : fetch -> extraction signature -> diff vs état persistant.
- signature inchangée  -> rien (pas d'appel LLM).
- signature changée / 1er run -> qualification LLM -> alerte ntfy si dispo pertinente.
- page illisible / fetch KO -> backoff + alerte ops après N échecs consécutifs.

Usage : `python -m restock_watcher` (boucle) ou `--once` (un cycle, debug).
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Config, load_config
from .detect import Extraction, extract
from .fetch import fetch
from .notify import notify
from .qualify import Verdict, deterministic_verdict, qualify
from .schedule import next_sleep
from .state import load_state, save_state

log = logging.getLogger("restock-watcher")


def _now_iso(cfg: Config) -> str:
    return datetime.now(ZoneInfo(cfg.timezone)).isoformat(timespec="seconds")


def _handle_unreadable(cfg: Config, state: dict, reason: str) -> None:
    fails = state.get("consecutive_failures", 0) + 1
    state["consecutive_failures"] = fails
    state["updated_at"] = _now_iso(cfg)
    log.warning("Page illisible (%s) — échec consécutif #%d", reason, fails)
    # alerte ops au seuil, puis re-tentée tous les `threshold` échecs (si le 1er
    # envoi ntfy échoue, on ré-essaie ; évite aussi le spam à chaque poll)
    if fails % cfg.fail_alert_threshold == 0:
        notify(
            cfg,
            title=f"⚠️ Watcher {cfg.product_label} : lecture impossible",
            message=(
                f"{fails} échecs consécutifs. Dernière raison : {reason}. "
                "Le proxy, le WAF ou la page ont peut-être changé — à vérifier."
            ),
            priority="high",
            tags=["warning"],
            click=cfg.target_url,
        )


def _notify_available(cfg: Config, verdict: Verdict) -> bool:
    """Alerte 'produit dispo' — la SEULE notification que le watcher envoie.
    Jamais d'alerte sur indispo, cosmétique, ou retour en rupture."""
    return notify(
        cfg,
        title=f"✅ {cfg.product_label} DISPO",
        message=f"{verdict.resume}\nÀ commander maintenant.",
        priority="urgent",
        tags=["shopping_cart"],
        click=cfg.target_url,
    )


def _qualify_or_fallback(cfg: Config, ex: Extraction, sig, previous: dict | None) -> Verdict:
    """Qualifie via le LLM ; si le LLM est HS, verdict déterministe (on n'avale
    jamais une alerte à cause d'une panne LLM)."""
    try:
        return qualify(cfg, ex.summary_text, previous)
    except Exception as exc:
        log.warning("Qualification LLM en échec (%s) — fallback déterministe.", exc)
        return deterministic_verdict(sig, previous)


def run_once(cfg: Config, state: dict) -> None:
    fr = fetch(cfg)
    if not fr.ok:
        _handle_unreadable(cfg, state, f"fetch: {fr.error}")
        return

    ex = extract(fr.html)
    if not ex.ok or ex.signature is None:
        _handle_unreadable(cfg, state, "page lue mais 0 signal de dispo")
        return

    # page lisible -> on repart de zéro côté échecs
    if state.get("consecutive_failures"):
        log.info("Lecture rétablie après %d échec(s).", state["consecutive_failures"])
        state["consecutive_failures"] = 0

    sig = ex.signature
    digest = sig.digest()
    first_run = "last_digest" not in state

    if not first_run and digest == state.get("last_digest"):
        state["updated_at"] = _now_iso(cfg)
        log.info("Aucun changement (%s).", sig.short())
        return

    # changement (ou 1er run)
    previous = None
    if not first_run:
        previous = {
            "dispo": state.get("last_dispo"),
            "achetable": state.get("last_buyable"),
            "prix": state.get("last_prix"),
            "resume": state.get("last_resume"),
        }

    # Règle d'alerte : on n'alerte QUE quand le produit est/devient ACHETABLE.
    # Jamais sur indispo, retour en rupture, ou changement cosmétique.
    buyable = sig.buyable()
    was_buyable = bool(state.get("last_buyable", False))
    became_buyable = not first_run and buyable and not was_buyable

    delivered = True  # True si aucune alerte à envoyer OU si elle est bien passée
    if became_buyable:
        # transition claire non-achetable -> achetable : alerte INSTANTANÉE sur le
        # signal déterministe (fiable, validé sur le vrai DOM), sans attendre le LLM.
        verdict = deterministic_verdict(sig, previous)
        log.info("DEVENU ACHETABLE -> alerte : %s", sig.short())
        delivered = _notify_available(cfg, verdict)
    else:
        # cas non-trivial : on qualifie via le LLM (joli message + rattrapage d'un
        # état commandable ambigu que le déterministe raterait). On alerte SEULEMENT
        # si c'est achetable ; sinon silence total.
        verdict = _qualify_or_fallback(cfg, ex, sig, previous)
        alert = (first_run and buyable) or (
            not first_run and verdict.achetable and not was_buyable
        )
        if alert:
            log.info("ACHETABLE -> alerte : %s", verdict.resume)
            delivered = _notify_available(cfg, verdict)
        else:
            log.info("Pas d'alerte (indispo / déjà signalé / cosmétique) : %s", sig.short())

    if not delivered:
        # notification non délivrée : NE PAS avancer l'état (last_digest reste
        # périmé) -> l'alerte est re-tentée au prochain poll. On ne perd jamais une
        # dispo à cause d'un blip ntfy.
        log.error("Notification NON délivrée — état non avancé, re-tentative au prochain poll.")
        state["updated_at"] = _now_iso(cfg)
        return

    state.update(
        {
            "last_digest": digest,
            "last_dispo": verdict.dispo,
            "last_resume": verdict.resume,
            "last_prix": sig.price,
            # 'orderable' par le signal déterministe OU le jugement LLM -> évite de
            # ré-alerter en boucle sur un état commandable ambigu.
            "last_buyable": buyable or verdict.achetable,
            "updated_at": _now_iso(cfg),
        }
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    cfg = load_config()
    once = "--once" in sys.argv[1:]

    # NB : on ne logge PAS le topic ntfy — sur ntfy.sh public le topic EST le secret.
    log.info(
        "restock-watcher démarre | cible=%s | modèle=%s (%s) | ntfy=%s | once=%s",
        cfg.target_url, cfg.llm_model, cfg.llm_provider, cfg.ntfy_server, once,
    )

    while True:
        state = load_state(cfg.state_path)
        try:
            run_once(cfg, state)
        except Exception:
            log.exception("Cycle en erreur inattendue")
        save_state(cfg.state_path, state)

        if once:
            return 0
        sleep_s = next_sleep(cfg)
        log.info("Prochain poll dans %d s.", sleep_s)
        try:
            time.sleep(sleep_s)
        except KeyboardInterrupt:
            log.info("Arrêt demandé.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
