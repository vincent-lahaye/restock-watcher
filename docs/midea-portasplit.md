# Guide pour LLM : surveiller le Midea PortaSplit H24

[Retour au README](../README.md)

Ce guide permet à un assistant de reproduire la configuration historique du
watcher Midea chez Optimea, puis de l'exécuter en continu sur un serveur Docker.
Il surveille la disponibilité et envoie une notification ; il ne passe pas de
commande. Lire les fichiers du dépôt avant d'exécuter les commandes et adapter
les chemins à la machine cible.

## 1. Faits connus et limites

La configuration et le README du projet d'origine, versionnés le **24 juillet
2026**, indiquaient :

- Cible : `https://www.optimea.fr/product/climatiseur-split-mobile-midea/`.
- Réapprovisionnements décrits comme **quasi quotidiens**, autour de **9 h à
  9 h 30 le matin**, et aussi de **15 h à 15 h 30**, en **Europe/Paris**.
- Surveillance renforcée de **08:55 à 09:45** et de **14:55 à 15:45** : pause de
  120 secondes entre cycles, avec une variation aléatoire de ±30 secondes.
  Hors créneaux, pause de 1 800 secondes avec la même variation, raccourcie à
  l'approche du prochain créneau. Le temps de traitement s'ajoute aux pauses.
- Lecture via un proxy résidentiel **IPRoyal** et `curl_cffi` avec profil Chrome ;
  cette combinaison avait permis de lire la page derrière son WAF.
- Qualification par **Kimi k2.6 via Moonshot**, notifications **ntfy**, exécution
  Docker sur un NAS avec état persistant.

Ces éléments ont été retrouvés dans les archives du projet le **11 novembre
2026** : il ne s'agit pas d'une nouvelle observation du stock à cette date.
Les horaires sont un retour d'expérience historique, sans garantie du vendeur
ni statistiques permettant de mesurer leur fréquence. Ne pas affirmer que le
produit est actuellement en rupture ou disponible, ni promettre un réassort.
Avant le déploiement, vérifier que l'URL désigne toujours le **Midea PortaSplit**
recherché et que les signaux WooCommerce restent lisibles. Si la page a changé,
signaler le problème plutôt que substituer silencieusement un autre produit.

La cadence s'applique tous les jours, week-end compris. Conserver le filet H24 :
un réassort peut arriver hors créneau. Un stock épuisé entre deux lectures peut
échapper au watcher.

## 2. Choisir la machine et réunir les accès

Utiliser un hôte Linux toujours allumé avec Docker Engine et le plugin Compose :
un NAS compatible Docker/Compose reproduit le principe historique ; un VPS
Linux permet le même déploiement sans dépendre du réseau domestique. Un petit
serveur déjà disponible convient aussi. Aucun navigateur ni GPU n'est requis.

Éviter un hébergement qui met les processus en veille, impose une durée maximale
aux tâches ou efface le disque à chaque redéploiement. Il faut un processus
permanent, un répertoire persistant et des connexions sortantes vers le proxy,
Moonshot et ntfy. Le watcher n'expose aucun port entrant.

L'assistant doit identifier l'hôte choisi et obtenir les accès nécessaires sans
créer de service payant à l'insu de son utilisateur. Préparer :

- les identifiants du proxy résidentiel IPRoyal (`user:password`) ;
- une clé API Moonshot et l'accès au modèle configuré ;
- un topic ntfy long et aléatoire, auquel le téléphone est abonné, avec les
  notifications autorisées ; un jeton si le serveur/topic l'exige.

Ne jamais réutiliser ni publier les secrets de l'installation d'origine.
Sur le serveur public ntfy, traiter le nom du topic comme un secret. Utiliser
un gestionnaire de secrets ou saisir les valeurs sur l'hôte, sans les recopier
dans une conversation, un commit ou un compte rendu.

## 3. Installer et configurer

Installer Docker selon la [documentation officielle](https://docs.docker.com/engine/install/)
adaptée au système, puis vérifier `docker version` et `docker compose version`.
Sur un NAS, utiliser son mécanisme de déploiement Compose et un dossier de
données persistant ; les commandes ci-dessous correspondent à un hôte avec SSH.

```bash
git clone https://github.com/vincent-lahaye/restock-watcher.git
cd restock-watcher
cp .env.example .env
chmod 600 .env
cp docker-compose.example.yml docker-compose.yml
mkdir -p data
```

Si le dépôt existe déjà, l'utiliser et préserver sa configuration. Remplir `.env`
avec les valeurs suivantes ; **remplacer les trois valeurs `REMPLACER_…`** :

```dotenv
TARGET_URL=https://www.optimea.fr/product/climatiseur-split-mobile-midea/
PRODUCT_LABEL=Midea PortaSplit (Optimea)

IP_ROYAL_AUTH=REMPLACER_UTILISATEUR:MOT_DE_PASSE
PROXY_ENDPOINT=geo.iproyal.com:12321
REQUIRE_PROXY=true
IMPERSONATE=chrome

LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.moonshot.ai/v1
LLM_API_KEY=REMPLACER_CLE_MOONSHOT
LLM_MODEL=kimi-k2.6

NTFY_SERVER=https://ntfy.sh
NTFY_TOPIC=REMPLACER_TOPIC_LONG_ALEATOIRE
NTFY_TOKEN=

TZ=Europe/Paris
POLL_WINDOWS=08:55-09:45,14:55-15:45
POLL_WINDOW_SECONDS=120
POLL_IDLE_SECONDS=1800
JITTER_SECONDS=30

FETCH_TIMEOUT=45
FETCH_RETRIES=2
FAIL_ALERT_THRESHOLD=4
STATE_PATH=/data/state.json
```

Il s'agit des choix historiques, pas d'une garantie de disponibilité actuelle
du modèle ou des services. Vérifier les accès et les crédits. Si Kimi n'est plus
accessible, configurer un fournisseur pris en charge dans
[`config.py`](../restock_watcher/config.py) et vérifier sa qualification.
Ne pas désactiver `REQUIRE_PROXY` pour contourner un identifiant manquant.
Pour les secrets contenant `$` ou `#`, respecter la syntaxe des fichiers
`.env` de Compose (notamment les valeurs entre apostrophes pour éviter
l'interpolation). Ne pas afficher la configuration résolue contenant les secrets.

Le Compose fourni monte `./data` dans `/data` et définit
`restart: unless-stopped`. Conserver ces deux propriétés. Sur NAS, remplacer
au besoin `./data` par un chemin absolu persistant propre à l'utilisateur.
Ne jamais placer les identifiants directement dans le fichier Compose.

## 4. Valider avant de laisser tourner

Exécuter depuis le répertoire du dépôt, avant de démarrer la boucle permanente :

```bash
docker compose config --quiet
docker compose build
docker compose run --rm restock-watcher --once
```

**Un code de sortie nul de `--once` ne prouve pas une lecture réussie** : la boucle
enregistre aussi les échecs et peut terminer normalement. Lire les logs et
vérifier `data/state.json` : un cycle lisible doit produire `last_digest`, un
`updated_at` récent et aucun échec consécutif restant. Comparer l'état détecté
à la page produit. Un premier cycle où le produit est achetable peut déjà
envoyer une alerte ; en rupture, l'absence d'alerte est normale.

Tester séparément le canal ntfy, même si le produit est indisponible :

```bash
docker compose run --rm --entrypoint python restock-watcher -c 'from restock_watcher.config import load_config; from restock_watcher.notify import notify; c=load_config(); ok=notify(c, title="Test watcher Midea", message="Test de notification uniquement : aucun stock confirme.", priority="urgent", click=c.target_url); raise SystemExit(0 if ok else 1)'
```

Confirmer la réception sur le téléphone : un succès HTTP ne prouve pas que le
téléphone affiche l'alerte. Vérifier aussi l'absence de message
`Qualification LLM en échec` lors du premier cycle. Le repli déterministe permet
de continuer si le LLM échoue, mais ne valide pas la configuration Moonshot.

Ne pas lancer de cycle manuel sur le même fichier d'état pendant que le service
tourne : arrêter d'abord le service, ou utiliser un état et un topic de test
distincts. Ne pas supprimer l'état pour tester : cela peut répéter une alerte.

## 5. Démarrer H24 et vérifier la persistance

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=100 restock-watcher
docker compose restart restock-watcher
docker compose logs --tail=50 restock-watcher
```

Vérifier que le conteneur reste démarré, qu'un cycle se termine, que
`Prochain poll dans … s.` apparaît et que l'état précédent reste présent après
redémarrage. `Up` seul ne prouve pas le bon fonctionnement du watcher.

Configurer le démarrage automatique de Docker avec le système. Sur une
distribution utilisant systemd : `sudo systemctl enable --now docker`.
Sur NAS, utiliser l'option équivalente de sa plateforme. La politique
`unless-stopped` redémarre le conteneur après incident ou redémarrage de Docker,
mais un conteneur arrêté volontairement reste arrêté : le relancer avec
`docker compose up -d`. Tester un redémarrage complet de l'hôte lors d'une fenêtre
adaptée, puis contrôler le service et le fichier d'état.

Le service continue une fois SSH déconnecté. Garder la machine et son réseau
actifs H24 ; désactiver la veille de l'hôte si nécessaire. Prévoir la rotation
des logs Docker et surveiller le disque, les crédits proxy/API et la fraîcheur
de `data/state.json`. Hors créneaux, une pause d'environ 30 minutes est normale.

Après quatre échecs consécutifs de lecture, le watcher tente une alerte technique,
puis recommence tous les quatre échecs. Ce seuil compte des cycles, pas des
minutes. Il ne peut pas signaler lui-même un hôte éteint, un processus arrêté ou
une panne totale du réseau/ntfy : pour une exploitation H24, prévoir une
surveillance externe de l'hôte et de la fraîcheur de l'état.

## 6. Exploitation et dépannage

| Symptôme | Vérifications |
| --- | --- |
| Refus de démarrer : proxy absent | Renseigner `IP_ROYAL_AUTH`, conserver `REQUIRE_PROXY=true`. |
| Page illisible, challenge ou erreurs HTTP | Vérifier proxy, crédits, URL et évolution du site ; ne pas augmenter aveuglément la fréquence. |
| Qualification LLM en échec | Vérifier clé, crédits, URL API et modèle ; le repli déterministe ne remplace pas cette validation. |
| Alerte non reçue | Tester ntfy, abonnement, autorisations du téléphone et jeton éventuel. |
| Erreur d'écriture de l'état | Vérifier montage `/data`, permissions et espace disque. |
| Silence alors que le service tourne | Lire les logs et l'état : aucun changement ou produit déjà signalé = silence normal. |

Une transition déterministe non achetable → achetable déclenche l'alerte sans
attendre le LLM. Le watcher ne renvoie pas une alerte à chaque cycle si le
produit reste disponible. Si l'envoi ntfy échoue, il n'avance pas l'état de
disponibilité et retente au cycle suivant.

Après modification de `.env`, appliquer la configuration avec
`docker compose up -d --force-recreate` ; un simple `restart` ne recharge pas
les variables. Pour mettre à jour le code, vérifier les modifications locales,
puis utiliser `git pull --ff-only` et `docker compose up -d --build`. Conserver
`.env` et `data/`. Pour arrêter : `docker compose stop` ; pour reprendre :
`docker compose up -d`.

## Compte rendu attendu du LLM

Rapporter l'hôte et le dossier de déploiement, l'URL surveillée, les créneaux
Europe/Paris, le résultat du cycle réel, la réception du test ntfy et la
persistance après redémarrage. Préciser ce qui reste à vérifier. Ne déclarer
l'installation opérationnelle qu'après ces contrôles, sans divulguer clés,
identifiants proxy ni topic ntfy.

## Références

- Provenance historique : README et Compose de l'installation d'origine,
  version du 24 juillet 2026, relus le 11 novembre 2026. Les chemins privés,
  noms de machines et secrets ne sont pas reproduits ici.
- Configuration publique : [exemple d'environnement](../.env.example),
  [Compose](../docker-compose.example.yml), [cadence](../restock_watcher/schedule.py)
  et [boucle de surveillance](../restock_watcher/__main__.py).
- Docker : [exécution ponctuelle avec Compose](https://docs.docker.com/reference/cli/docker/compose/run/),
  [politiques de redémarrage](https://docs.docker.com/engine/containers/start-containers-automatically/).
