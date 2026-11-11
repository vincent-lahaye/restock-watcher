# restock-watcher

Surveille la disponibilité d'un produit **WooCommerce** et envoie une alerte
**ntfy** quand son état change. Un LLM qualifie le changement pour éviter les
fausses alertes. Conçu pour tourner en conteneur Docker.

Pour reproduire la surveillance du **Midea PortaSplit chez Optimea** et la faire
tourner H24 : [guide de déploiement destiné aux LLMs](docs/midea-portasplit.md).

## Prompt prêt à l'emploi pour lancer la surveillance du Midea PortaSplit

Copiez ce prompt dans votre assistant :

```text
Lis ce guide et les fichiers du dépôt auxquels il renvoie :
https://github.com/vincent-lahaye/restock-watcher/blob/main/docs/midea-portasplit.md

Accompagne-moi jusqu'à ce que la surveillance du Midea PortaSplit chez Optimea
soit réellement active H24 et que je reçoive les alertes sur mon téléphone.
Commence par identifier avec moi l'hébergement disponible et les accès nécessaires,
puis guide-moi dans la configuration et le déploiement. Exécute les étapes que
tes outils te permettent de réaliser ; pour les autres, donne-moi des instructions
précises et attends mon retour pour vérifier le résultat. Ne t'arrête pas à un
plan ou à la création des fichiers : poursuis jusqu'à la validation du service.

Reprends la configuration et les créneaux historiques du guide, en précisant que
les horaires de réassort sont des observations passées, pas une garantie actuelle.
Ne me demande pas de coller mes secrets dans la conversation et demande mon accord
avant de souscrire un service payant.

Vérifie une lecture réussie de la page produit, la réception d'une notification
de test sur mon téléphone, le fonctionnement en continu, la persistance de l'état
après redémarrage et le démarrage automatique du service. Ne déclare pas la
surveillance opérationnelle sans ces vérifications. Si une étape est bloquée,
explique ce qui manque et aide-moi à la débloquer. Termine avec les commandes
pour consulter les logs, arrêter et relancer la surveillance.
```

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
