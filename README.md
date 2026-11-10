# restock-watcher

Surveille la disponibilité d'un produit **WooCommerce** et envoie une alerte
**ntfy** quand son état change. Un LLM qualifie le changement pour éviter les
fausses alertes. Conçu pour tourner en conteneur Docker.

## Comment ça marche

1. **Fetch furtif** : `curl_cffi` (impersonation TLS Chrome), à travers un proxy
   résidentiel. Pas de navigateur headless.
2. **Signature déterministe** à chaque passage : JSON-LD `availability`, classe du
   bloc produit (`instock`/`outofstock`), `p.stock`, bouton « Ajouter au panier »,
   prix. Si le hash ne bouge pas, rien ne se passe.
3. **Qualification LLM**, seulement quand la signature change : le modèle classe
   l'état (`in_stock`, `out_of_stock`, `preorder`…) et juge si le changement compte.
   Le passage de non achetable à achetable déclenche une alerte immédiate, sans
   attendre le LLM.
4. **Alerte ntfy** avec priorité, tag et lien vers la page produit.

Après plusieurs échecs consécutifs de récupération ou d'analyse, une alerte
technique part, pour ne pas tomber en panne en silence.

## Configuration

Copier `.env.example` en `.env` et le remplir. Toutes les clés sont décrites dans
`restock_watcher/config.py`.

Le LLM ne dépend d'aucun fournisseur : `LLM_PROVIDER=anthropic`,
`LLM_MODEL=claude-haiku-4-5` et une clé Anthropic suffisent pour passer sur Claude.

## Lancer

```bash
cp .env.example .env   # puis remplir
cp docker-compose.example.yml docker-compose.yml
docker compose up -d --build
```

En local, un seul cycle :

```bash
uv run --with-requirements requirements.txt --env-file .env python -m restock_watcher --once
```

## Tests

```bash
uv run --with selectolax python3 tests/test_detect.py
uv run --with-requirements requirements.txt python3 tests/test_schedule.py
```

## Licence

MIT
