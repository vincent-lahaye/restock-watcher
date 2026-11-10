"""Tests du détecteur de signature contre des fixtures WooCommerce réalistes.

Lançable via `pytest` ou directement `python tests/test_detect.py`.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from restock_watcher.detect import extract  # noqa: E402

FIX = pathlib.Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_instock():
    ex = extract(_load("instock.html"))
    assert ex.ok
    sig = ex.signature
    assert sig.availability == "InStock"
    assert sig.wrapper_state == "instock"
    assert sig.stock_class == "in-stock"
    assert sig.stock_text == "En stock"
    assert sig.add_to_cart is True
    assert sig.buyable() is True
    # Prix propre : le montant seul, sans l'éco-part.
    assert sig.price == "999,00 €", sig.price
    assert "éco-part" not in (sig.price or "")


def test_outofstock():
    ex = extract(_load("outofstock.html"))
    assert ex.ok
    sig = ex.signature
    assert sig.availability == "OutOfStock"
    assert sig.wrapper_state == "outofstock"
    assert sig.stock_class == "out-of-stock"
    assert sig.stock_text == "Rupture de stock"
    assert sig.add_to_cart is False
    assert sig.buyable() is False


def test_preorder_is_buyable_but_distinct():
    ex = extract(_load("preorder.html"))
    assert ex.ok
    sig = ex.signature
    assert sig.availability == "PreOrder"  # extrait depuis un @graph
    assert sig.add_to_cart is True
    assert sig.buyable() is True  # heuristique : bouton présent -> le LLM qualifiera


def test_transition_changes_digest():
    a = extract(_load("instock.html")).signature.digest()
    b = extract(_load("outofstock.html")).signature.digest()
    assert a != b


def test_digest_is_stable():
    """Même page = même empreinte (pas de source volatile : nonce, timestamp)."""
    a = extract(_load("instock.html")).signature.digest()
    b = extract(_load("instock.html")).signature.digest()
    assert a == b


def test_empty_page_is_not_ok():
    ex = extract("<html><body></body></html>")
    assert ex.ok is False and ex.signature is None


def test_challenge_page_is_blocked():
    ex = extract(
        "<html><head><title>Just a moment...</title></head>"
        "<body><h1>Checking your browser before accessing</h1></body></html>"
    )
    assert ex.ok is False and ex.signature is None


def test_generic_title_only_is_not_ok():
    # <title>/<h1> génériques mais AUCUN markup produit -> pas lisible (sinon un
    # soft-404 / redirection boutique masquerait une réappro).
    ex = extract("<html><head><title>Boutique</title></head><body><h1>Bienvenue</h1></body></html>")
    assert ex.ok is False


def test_stock_counter_does_not_churn_digest():
    tmpl = (
        '<div class="product type-product instock purchasable">'
        '<div class="summary entry-summary"><h1 class="product_title">X</h1>'
        '<p class="price"><span class="woocommerce-Price-amount amount"><bdi>999,00&nbsp;€</bdi></span></p>'
        '<p class="stock in-stock">Plus que {n} en stock</p>'
        '<form class="cart"><button class="single_add_to_cart_button">Ajouter au panier</button></form>'
        "</div></div>"
    )
    d3 = extract(tmpl.format(n=3)).signature.digest()
    d2 = extract(tmpl.format(n=2)).signature.digest()
    assert d3 == d2, "le compteur d'unités ne doit pas changer la signature"


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
