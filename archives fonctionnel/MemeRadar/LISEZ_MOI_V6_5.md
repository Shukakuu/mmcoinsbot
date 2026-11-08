# MemeRadar v6.5 — DEX rétabli, J7 réellement intégré au classement

**Lis ce fichier avant la mise à jour.** Les profils J7 possèdent déjà `author.verified`, `author.badge`, `author.verifiedType` et `author.parody`. La v6.1 ne les enregistrait pas. Cette version rétablit ces informations.

## Détection des coins

- Le classement d’affichage reste sur le **score du marché** (>40 et risques masqués par défaut), comme les anciennes versions v3/v4/v5. Le seuil précédent 50/100 peut être resté enregistré par ton navigateur : v6.5 repart à 40/100 dans une nouvelle préférence.
- Le scanner analyse 14 tokens par passage à 20 s après le précédent. Nouveaux pools prioritaires ; suivi tournant des anciens ; deuxième page des nouveaux pools Gecko avec protection HTTP 429. Les coins masqués restent en base.
- Si aucun coin n’apparaît, un diagnostic détaille le nombre sous la note, les alertes et les paires récupérées. Bouton pour voir uniquement les coins sans alerte de risque et desserrer le score, sans les présenter comme des achats.
- `radar.db` est essentiel à préserver : une base SQLite neuve explique parfois le passage de 50+ coins à 26 après une migration.

## J7 / X

- La priorité sociale est calculée uniquement sur les **adresses Solana exactes**, jamais sur un ticker ambigu.
- Une mention originale (pas une réponse ou retweet), datant de moins de 10 minutes, par un compte **≥50 000 abonnés** et marqué `verified: true` par J7 peut donner **3 points de priorité d’investigation**. Un compte marqué `parody: true` est exclu. Deux auteurs distincts augmentent le signal. Le market score et le statut de risque restent inchangés.
- Si une clé développeur officielle X est fournie via `X_BEARER_TOKEN`, la vérification par l’API X est exécutée en arrière-plan, avec cache et budget strict ; elle permet de confirmer le badge et accorde alors 6 points par auteur (au lieu de 3), ou retire le bonus si X ne confirme pas. L'interface affiche le statut de la preuve. Sans clé, les informations J7 restent utilisables en priorité *faiblement pondérée*, sans vérification indépendante.
- **Ne pas confondre badge X et authenticité des abonnés :** la coche bleue peut venir d’un abonnement Premium. Aucun de ces systèmes ne calcule réellement la proportion de bots dans les followers. Une estimation de cette proportion exigerait un échantillon via une API autorisée, des métriques et des contrôles statistiques. Le programme n'invente aucune proportion.
- Les tweets restent accessibles dans le panneau social replié. Aucun besoin de lire les tweets pour que la priorité J7 soit appliquée au moteur.

## Migration

1. `Ctrl+C` pour arrêter l’ancienne installation, puis sauvegarder `radar.db` et `wallets.txt`.
2. Extraire v6.5 dans un **nouveau** dossier, copier les deux fichiers dans ce dossier après arrêt.
3. Démarrer `START_J7.ps1` normalement. Une clé X est facultative : `$env:X_BEARER_TOKEN = '...'; ./START_J7.ps1` dans le même terminal (ne partage jamais ton jeton).
4. Ouvrir `http://127.0.0.1:8765` et faire `Ctrl+F5`.
5. Si 0 coin : observer le diagnostic de la liste, puis `http://127.0.0.1:8765/api/data`. Statistiques `stored`, `new_candidates`, `pairs_found` et `errors` indiquent si le problème est base/filtres ou découverte. `/api/social-status` confirme J7. Ne remplace pas ces diagnostics par une supposée probabilité de gain.

**Limites** : tests hors ligne, sans clé J7 ni API X authentifiées ; pas d’achat automatique ; scores non calibrés, ne prédisent pas les gains.
