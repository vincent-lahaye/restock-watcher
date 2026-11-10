"""Extraction d'une *signature de disponibilité* ciblée depuis une page produit
WooCommerce, et calcul de son empreinte (pour ne réveiller le LLM que sur un
vrai changement).

Principe : on ne se fie pas à un seul marqueur (fragile). On combine des signaux
robustes du bloc produit (JSON-LD schema.org, classe du wrapper, texte `p.stock`,
présence du bouton panier, prix) en une signature compacte. Son hash sert de
détecteur de changement déterministe, gratuit, à chaque poll. Le LLM ne qualifie
que quand ce hash bouge (voir qualify.py).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from selectolax.parser import HTMLParser

# Marqueurs schema.org d'availability, ordre = ne sert qu'à l'extraction du token.
_SCHEMA_AVAIL = re.compile(
    r"(InStock|OutOfStock|SoldOut|PreOrder|BackOrder|LimitedAvailability|"
    r"OnlineOnly|Discontinued|PreSale)",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")

# Sélecteur du bloc résumé produit WooCommerce (thème standard et variantes courantes).
_SUMMARY_SELECTORS = (".entry-summary", ".summary", "div.product.type-product")


_DIGITS = re.compile(r"\d+")

# marqueurs de page de blocage / challenge servie en HTTP 200 (WAF, Cloudflare…)
_BLOCK_MARKERS = (
    "just a moment",
    "un instant",
    "attention required",
    "checking your browser",
    "verify you are human",
    "verifying you are",
    "access denied",
    "forbidden",
    "cloudflare",
    "ddos-guard",
    "captcha",
    "request blocked",
)


def _norm(text: str | None) -> str | None:
    if text is None:
        return None
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    text = _WS.sub(" ", text).strip()
    return text or None


def _collapse_digits(text: str | None) -> str | None:
    """Neutralise les compteurs d'unités ('Plus que 3 en stock') pour que la
    signature ne change pas à chaque vente (un changement de compteur n'est pas un
    changement d'état de dispo)."""
    return _DIGITS.sub("N", text) if text else text


def _looks_blocked(tree: HTMLParser) -> bool:
    node = tree.css_first("title")
    txt = (_norm(node.text(deep=True, strip=True)) or "").lower() if node else ""
    return any(marker in txt for marker in _BLOCK_MARKERS)


@dataclass(frozen=True)
class Signature:
    """Signaux de dispo pertinents. `None` = signal absent de la page."""

    availability: str | None  # token schema.org normalisé (InStock/OutOfStock/...)
    wrapper_state: str | None  # "instock" | "outofstock" (classe du div produit)
    stock_class: str | None    # "in-stock" | "out-of-stock" (classe du p.stock)
    stock_text: str | None     # "En stock" | "Rupture de stock" | ...
    add_to_cart: bool          # bouton "Ajouter au panier" présent ET actif
    price: str | None          # prix normalisé, ex "999,00 €"

    def digest(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def buyable(self) -> bool:
        """Heuristique déterministe rapide (le verdict qualifié vient du LLM)."""
        if self.availability and self.availability.lower() in {
            "outofstock",
            "soldout",
            "discontinued",
        }:
            return False
        if self.wrapper_state == "outofstock":
            return False
        return self.add_to_cart

    def short(self) -> str:
        return (
            f"availability={self.availability} wrapper={self.wrapper_state} "
            f"stock={self.stock_text!r} panier={self.add_to_cart} prix={self.price!r}"
        )


@dataclass(frozen=True)
class Extraction:
    ok: bool                    # False = page illisible (0 signal) -> traiter en erreur
    signature: Signature | None
    title: str | None
    summary_text: str | None    # bloc compact passé au LLM en cas de changement


# ---------------------------------------------------------------------------
# JSON-LD (source machine la plus robuste : offers.availability + price)
# ---------------------------------------------------------------------------
def _iter_jsonld(tree: HTMLParser):
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text(deep=True, strip=False)
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except (ValueError, TypeError):
            continue


def _walk_products(obj):
    """Rend récursivement chaque dict représentant un Product schema.org."""
    if isinstance(obj, dict):
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and x.lower() == "product" for x in types):
            yield obj
        for value in obj.values():
            yield from _walk_products(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_products(item)


def _jsonld_availability_price(tree: HTMLParser) -> tuple[str | None, str | None]:
    for doc in _iter_jsonld(tree):
        for product in _walk_products(doc):
            offers = product.get("offers")
            candidates = offers if isinstance(offers, list) else [offers]
            for offer in candidates:
                if not isinstance(offer, dict):
                    continue
                avail = offer.get("availability")
                price = offer.get("price")
                token = None
                if isinstance(avail, str):
                    m = _SCHEMA_AVAIL.search(avail)
                    token = m.group(1) if m else avail.rsplit("/", 1)[-1]
                if token or price is not None:
                    return token, (str(price) if price is not None else None)
    return None, None


# ---------------------------------------------------------------------------
# Bloc résumé (thème)
# ---------------------------------------------------------------------------
def _summary_node(tree: HTMLParser):
    for sel in _SUMMARY_SELECTORS:
        node = tree.css_first(sel)
        if node is not None:
            return node
    return None


def _wrapper_state(tree: HTMLParser) -> str | None:
    node = tree.css_first("div.product.type-product") or tree.css_first(".product.type-product")
    if node is None:
        return None
    classes = (node.attributes.get("class") or "").split()
    if "outofstock" in classes:
        return "outofstock"
    if "instock" in classes:
        return "instock"
    return None


def _stock_p(scope) -> tuple[str | None, str | None]:
    node = scope.css_first("p.stock")
    if node is None:
        return None, None
    classes = (node.attributes.get("class") or "").split()
    cls = None
    if "out-of-stock" in classes:
        cls = "out-of-stock"
    elif "in-stock" in classes:
        cls = "in-stock"
    return cls, _collapse_digits(_norm(node.text(deep=True, strip=True)))


def _add_to_cart(scope) -> bool:
    btn = scope.css_first("form.cart button.single_add_to_cart_button") or scope.css_first(
        "button.single_add_to_cart_button"
    )
    if btn is None:
        return False
    return "disabled" not in btn.attributes


def _price(scope) -> str | None:
    # <bdi> = montant seul (sans le sous-span "dont X € d'éco-part.").
    node = (
        scope.css_first("p.price .woocommerce-Price-amount bdi")
        or scope.css_first("p.price .woocommerce-Price-amount")
        or scope.css_first("p.price")
    )
    if node is None:
        return None
    # strip=False : garder le nbsp séparateur "999,00 €" (_norm le normalise).
    return _norm(node.text(deep=True, strip=False))


def _title(tree: HTMLParser) -> str | None:
    node = tree.css_first("h1.product_title") or tree.css_first("h1") or tree.css_first("title")
    return _norm(node.text(deep=True, strip=True)) if node else None


def extract(html: str) -> Extraction:
    """Parse le HTML brut et retourne l'Extraction (signature + contexte LLM)."""
    tree = HTMLParser(html)

    # JSON-LD d'abord (a besoin des <script>), puis on nettoie style/script pour
    # que le texte visible passé au LLM ne soit pas pollué de CSS/JS inline.
    availability, jsonld_price = _jsonld_availability_price(tree)
    tree.strip_tags(["style", "script", "noscript", "template"])

    scope = _summary_node(tree) or tree.body or tree
    wrapper_state = _wrapper_state(tree)
    stock_class, stock_text = _stock_p(scope)
    add_to_cart = _add_to_cart(scope)
    price = _price(scope) or _norm(jsonld_price)
    title = _title(tree)

    sig = Signature(
        availability=availability,
        wrapper_state=wrapper_state,
        stock_class=stock_class,
        stock_text=stock_text,
        add_to_cart=add_to_cart,
        price=price,
    )

    # Lisible = un signal de dispo OU un vrai titre produit WooCommerce
    # (h1.product_title, pas le <title> générique), ET pas une page de
    # blocage/challenge servie en 200. Sinon on masquerait une réappro et on
    # remettrait à zéro le compteur d'échecs ops.
    any_signal = any(
        (availability, wrapper_state, stock_class, stock_text, add_to_cart, price)
    )
    has_product = bool(any_signal) or tree.css_first("h1.product_title") is not None
    ok = has_product and not _looks_blocked(tree)

    summary_text = _summary_text(title, sig, scope) if ok else None
    return Extraction(ok=ok, signature=sig if ok else None, title=title, summary_text=summary_text)


def _summary_text(title: str | None, sig: Signature, scope) -> str:
    """Bloc compact et propre pour le LLM (signaux structurés + texte visible du
    bloc résumé, tronqué). Volontairement court pour rester cheap."""
    visible = _norm(scope.text(deep=True, strip=True)) or ""
    if len(visible) > 1200:
        visible = visible[:1200] + " […]"
    return (
        f"Produit : {title or 'inconnu'}\n"
        f"Signaux extraits :\n"
        f"- schema.org availability : {sig.availability}\n"
        f"- classe wrapper : {sig.wrapper_state}\n"
        f"- p.stock : classe={sig.stock_class} texte={sig.stock_text!r}\n"
        f"- bouton 'Ajouter au panier' actif : {sig.add_to_cart}\n"
        f"- prix affiché : {sig.price}\n"
        f"Texte visible du bloc produit :\n{visible}"
    )
