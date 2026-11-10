"""Qualification LLM de l'état de disponibilité — appelée UNIQUEMENT quand la
signature déterministe a changé (voir detect.py). Provider-agnostique :
- openai_compatible : Kimi (api.moonshot.ai/v1) ou OpenRouter
- anthropic : Claude Haiku (fallback)

Si le LLM est indisponible, `deterministic_verdict()` prend le relais : on ne
rate jamais une alerte de réappro à cause d'une panne LLM.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import Config
from .detect import Signature

VALID_DISPO = {"in_stock", "out_of_stock", "preorder", "backorder", "limited", "unknown"}

_DISPO_FR = {
    "in_stock": "En stock",
    "out_of_stock": "En rupture",
    "preorder": "En précommande",
    "backorder": "Sur commande",
    "limited": "Stock limité",
    "unknown": "État inconnu",
}

_SYSTEM = (
    "Tu es un classifieur de disponibilite produit e-commerce. On te donne les "
    "signaux extraits d'une page produit, et eventuellement l'etat qualifie "
    "precedent. Tu reponds UNIQUEMENT par un objet JSON valide, sans texte autour, "
    "avec exactement ces cles :\n"
    '- "dispo" : une valeur parmi in_stock, out_of_stock, preorder, backorder, limited, unknown\n'
    '- "achetable" : booleen (le produit peut etre commande maintenant)\n'
    '- "prix" : chaine ou null\n'
    '- "resume" : une phrase courte en francais decrivant l\'etat (pas de tiret cadratin)\n'
    '- "changement_significatif" : booleen, true SEULEMENT si l\'etat de disponibilite a '
    "change de facon pertinente par rapport a l'etat precedent fourni (ex: rupture->dispo, "
    "dispo->precommande). false si identique, purement cosmetique (promo, arrondi de prix), "
    "ou s'il n'y a pas d'etat precedent."
)

_JSON_RE = re.compile(r"\{.*\}", re.S)


@dataclass(frozen=True)
class Verdict:
    dispo: str
    achetable: bool
    prix: str | None
    resume: str
    changement_significatif: bool


def _build_user(summary_text: str, previous: dict | None) -> str:
    prev = json.dumps(previous, ensure_ascii=False) if previous else "aucun (premiere observation)"
    return (
        f"Etat precedent : {prev}\n\n"
        f"Signaux actuels de la page :\n{summary_text}\n\n"
        "Reponds uniquement par le JSON."
    )


def qualify(cfg: Config, summary_text: str, previous: dict | None) -> Verdict:
    user = _build_user(summary_text, previous)
    if cfg.llm_provider == "anthropic":
        raw = _call_anthropic(cfg, user)
    else:
        raw = _call_openai_compatible(cfg, user)
    return _parse(raw)


def _call_openai_compatible(cfg: Config, user: str) -> str:
    from openai import OpenAI

    client = OpenAI(base_url=cfg.llm_base_url, api_key=cfg.llm_api_key)
    resp = client.chat.completions.create(
        model=cfg.llm_model,
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        # pas de temperature : kimi-k2.6 (reasoning) impose 1 ; on laisse le défaut.
        # max_tokens généreux : les modèles reasoning consomment ~600-700 tokens de
        # raisonnement AVANT le JSON ; trop bas -> réponse tronquée, content vide.
        max_tokens=2000,
    )
    return resp.choices[0].message.content or ""


def _call_anthropic(cfg: Config, user: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=cfg.llm_api_key)
    msg = client.messages.create(
        model=cfg.llm_model,
        max_tokens=400,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def _parse(raw: str) -> Verdict:
    match = _JSON_RE.search(raw or "")
    data: dict = {}
    if match:
        try:
            data = json.loads(match.group(0))
        except ValueError:
            data = {}
    dispo = str(data.get("dispo", "unknown")).lower().strip()
    if dispo not in VALID_DISPO:
        dispo = "unknown"
    prix = data.get("prix")
    return Verdict(
        dispo=dispo,
        achetable=bool(data.get("achetable", False)),
        prix=str(prix) if prix else None,
        resume=(str(data.get("resume") or "").strip() or "Etat de disponibilite mis a jour."),
        changement_significatif=bool(data.get("changement_significatif", False)),
    )


def deterministic_verdict(sig: Signature, previous: dict | None) -> Verdict:
    """Fallback sans LLM : mappe les signaux vers un verdict, calcule le changement
    par rapport à l'état précédent. Garantit qu'une réappro déclenche l'alerte
    même si le LLM est HS."""
    avail = (sig.availability or "").lower()
    if "outofstock" in avail or "soldout" in avail or "discontinued" in avail or sig.wrapper_state == "outofstock":
        dispo = "out_of_stock"
    elif "preorder" in avail or "presale" in avail:
        dispo = "preorder"
    elif "backorder" in avail:
        dispo = "backorder"
    elif "instock" in avail or sig.wrapper_state == "instock":
        dispo = "in_stock"
    else:
        dispo = "unknown"

    prev_dispo = (previous or {}).get("dispo")
    changed = prev_dispo is not None and prev_dispo != dispo
    resume = f"{_DISPO_FR.get(dispo, dispo)} — {sig.price or 'prix n/a'}"
    return Verdict(
        dispo=dispo,
        achetable=sig.buyable(),
        prix=sig.price,
        resume=resume,
        changement_significatif=changed,
    )
