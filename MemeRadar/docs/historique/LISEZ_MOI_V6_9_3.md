# MemeRadar v6.9.3 — Correctifs vérifiables et audit de la collecte

**Origine :** audit du dossier `MemeRadar(1).zip` reçu le 30 octobre 2026. Cette mise à jour **ne prétend pas améliorer la rentabilité**. Elle corrige le suivi RPC et, surtout, rend les blocages mesurables pendant la prochaine session.

## Constat établi sur la base fournie

- **2 930 tokens** cumulés, sur plusieurs sessions et versions. Sur ces tokens, **2 652/2 930 (90,5 %)** n'ont pas de valeur `liquidity.usd` dans leur dernière observation : cela concerne surtout les marchés sur courbe, pas nécessairement une absence de réserves.
- Dernière version **v6.9.1** : 824 dernières fiches, les autres provenant de v6.7 (2 022) et v6 (84). Le correctif RPC v6.9.2 n'était pas dans l'archive.
- Fenêtre prospective v3 : du **30 octobre 2026 à 07:29:05 UTC à 08:51:30 UTC** : 1 h 22 de battements de cœur enregistrés, **60 événements**, 173 observations par horizon. Les données plus anciennes ne constituent pas une session continue de 24 h.
- 3 985 posts X/J7 cumulés, 4 associations post/contrat exact cumulées ; 549 posts reçus dans la fenêtre de deux heures précédant la dernière observation ; 0 post **publié par** `elonmusk` dans cette fenêtre (mentionner `@elonmusk` dans un autre post ne compte pas).
- 8 événements de hausses de solde de token liés à un wallet. Il n'est pas démontré que ce sont des achats. Le wallet sniper `69d6eA...` n'était pas suivi.
- Recherche v3, événement `a_etudier` : à +5 min, 15/21 variations positives ; à +60 min, 2/7 positives et 3/7 à -30 % ou pire. Ces échantillons sont incomplets et peuvent inclure plusieurs événements pour le même token. Les variations sont des **cotations**, sans frais, slippage ni validation de revente.
- Derniers états : 2 141 `risque`, 428 `surveillance`, 351 `incomplet`, 10 `a_etudier`. Ce ne sont pas les nombres d'alertes de la dernière session.
- Les pré-impulsions confirmées sont rares (1 événement confirmé v3). Quatre événements de courbe précoce sont enregistrés. La version ancienne n'a pas de mesures de durée par étape ; impossible d'attribuer précisément sa lenteur à Gecko, RPC ou RugCheck.

## Modifications de la v6.9.3

1. `getTransaction` accepte `maxSupportedTransactionVersion: 1` (le v6.9.1 demandait 0, provoquant le RPC `-32015` sur des transactions v1).
2. `wallets.txt` remplace l'adresse finissant par `pump`, probablement un mint, par **`69d6eAnot869mAuaDZqyF8qqDmXKQZqfhmDCyfQDapFp`**, à étudier. Sa rentabilité et son indépendance ne sont **pas confirmées**. Les autres wallets publics ont été conservés. Le suivi détecte des **augmentations de solde**, pas des achats prouvés.
3. Nouvelle table `scan_cycles` dans SQLite. Pour chaque cycle, conserve son succès, sa durée, les nouveaux candidats, le nombre choisi, les paires trouvées et les durées des étapes (`discovery`, `wallets`, `candidate_selection`, `dex_quotes`, `gecko_quotes`, `token_analysis`). Le rapport `/api/data` contient aussi `status.scan_stages_s` et `status.fresh_scanned`.
4. Les nouveaux événements prospectifs v3 conservent désormais une **copie des preuves au moment du signal** : prix/volume, liquidité, achats/ventes m5 et résumé de sécurité RugCheck. La mise à jour ultérieure du cache ne peut plus effacer ces renseignements historiques.
5. Le diagnostic de `/api/social` expose `watched_authors_received_2h` : nombre de publications **effectivement reçues** pour les comptes indiqués dans `MEMERADAR_SOCIAL_WATCH` (par défaut `elonmusk,RockstarGames`). Cela **n'abonne pas automatiquement J7** à ces comptes : un zéro signifie « non reçu », pas « ce compte n'a pas publié ».
6. Les messages non-X `external_message` de J7 sont désormais journalisés **sous forme de structure uniquement** (`external_shape` dans `j7_events`, sans texte sensible, token ni contrat inventé). On pourra comprendre la forme réelle des webhooks, avant d'essayer de résoudre de nouveaux lancements.
7. Script `tools/audit_local.py` : diagnostic **hors ligne, en lecture seule**, sans compte ni clé API. Permet de comparer les prochaines sessions à la précédente.
8. Aucun seuil de score, algorithme de classement, type d'alerte ni interface n'a été modifié ; aucune fonction d'achat, vente, signature ou import de clé privée.

## Installation — conserver impérativement l'historique

1. **Arrêter complètement** le bot existant, ainsi que les fenêtres J7 ouvertes par les scripts.
2. **Sauvegarder** ton dossier actuel, surtout `radar.db` et les éventuels fichiers `radar.db-wal` / `radar.db-shm` si le programme avait été arrêté brutalement. Les copier ensemble avant de remplacer le code. Ne jamais fusionner deux bases SQLite différentes.
3. Décompresser le nouveau ZIP dans **un nouveau dossier**. **Ce ZIP ne contient pas de `radar.db`** : il ne faut pas lancer le bot sans d'abord y remettre ta base actuelle, sinon une nouvelle base vide sera créée.
4. Copier `radar.db` (et les éventuels fichiers journaux SQLite associés) depuis l'ancien dossier dans le nouveau dossier `MemeRadar` ; vérifier que l'ancien bot est arrêté avant la copie. Les anciens fichiers `wallets.txt` peuvent être comparés et fusionnés manuellement ; le nouveau fichier ajoute le wallet demandé.
5. Installer si nécessaire `py -3 -m pip install -r requirements-j7.txt` et lancer `START_J7.ps1` (avec ton propre jeton J7), ou `START_MEMERADAR.bat` sans J7.
6. Vérifier dans `http://127.0.0.1:8765/api/data` que `engine_version` affiche `v6.9.3`. Le journal des nouveaux cycles sera enregistré dans **la même base**.

### Diagnostic après la session

Dans PowerShell, depuis le dossier `MemeRadar`, après avoir arrêté le bot :

```powershell
py -3 tools/audit_local.py --db radar.db --hours 2
```

Consulter également `http://127.0.0.1:8765/api/social` pendant la session : `watched_authors_received_2h` indique quels comptes surveillés sont **effectivement** présents dans le flux reçu, pas ce à quoi l'abonnement J7 donne droit.

### Ce qui reste à construire et à tester

- Vérifier la latence réelle entre tweet → J7 → signal → cote et comparer l'identité de l'auteur, des contrats et du pool.
- Identifier les réserves on-chain avant migration, les gros acheteurs qui revendent et les clusters liés aux créateurs. **Aucun détecteur robuste de ces phénomènes n'est inclus dans ce correctif.**
- Un moteur « narrative » (GTA VI, Elon Musk, OpenAI, sujets viraux) a besoin de sources dont on mesure le **rappel réel**, d'une attribution explicite entre événement et mint, et d'une validation prospective ; on ne peut pas en déduire une probabilité fiable à partir des 4 contrats associés actuellement.
- Comparer aux témoins, avec une entrée manuelle retardée, les frais, le slippage, le fait de pouvoir vendre, ainsi que des règles de sortie fixées à l'avance. La recherche v3 actuelle ne mesure que des prix observés.
- Les 2h de prochaine collecte permettront surtout de diagnostiquer **où le bot passe son temps** et **combien de candidats sont réellement vérifiés**. Elles ne suffiront pas à prouver une stratégie prédictive.

**Tests hors réseau :** 129 tests unitaires passés lors de la préparation. Aucun test réel du flux J7 authentifié ou de la performance des signaux en direct n'a été fait dans cet environnement.
