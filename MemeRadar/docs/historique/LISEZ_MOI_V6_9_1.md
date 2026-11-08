# MemeRadar v6.9.1 — correctif des découvertes (30 octobre 2026)

## Pourquoi ce correctif

L’archive de données inspectée (2 198 tokens entre le 29 et le 30 octobre) était exécutée avec le moteur **v6.7**, pas v6.9. Les tokens Pump.fun et Meteora DBC sans liquidité DEX étaient donc presque systématiquement exclus du statut « À étudier ». Dans cette base : 1 724 pumpfun + 240 meteoradbc sans `liquidity_usd`, 1 730 classés `risque`, 444 `surveillance`, 19 `incomplet` et 5 `a_etudier`. Ce sont des **états historiques**, pas les prédictions de v6.9.1.

## Changements par rapport à la v6.9

- Conserve le modèle expérimental des bonding curves, le suivi prospectif V3, les alertes de sécurité et J7 de v6.9.
- Corrige le cas où l’algorithme ne reconnaissait comme « déjà connus » que les 1 000 coins les plus récemment rafraîchis : désormais toutes les adresses `mint` de SQLite sont consultées, sans charger les 2 198 fichiers JSON.
- Ajoute `engine_version: v6.9.1` et `known_total` dans `/api/data` pour identifier le **vrai moteur actif**.
- Affiche la version du moteur dans les diagnostics de sélection.
- Aucune modification des seuils financiers par rapport à v6.9 ; aucune transaction automatique.

## Installation Windows

1. Arrêter **toutes** les anciennes instances de MemeRadar (`Ctrl+C`) et sauvegarder le dossier actuel.
2. Extraire le ZIP dans un **nouveau dossier** (ne pas réutiliser le vieux `radar/engine.py`).
3. Copier `radar.db` et, si désiré, `wallets.txt` depuis ton ancienne installation. Aucune clé privée ou jeton dans les fichiers.
4. Lancer `START_J7.ps1` ou `START_MEMERADAR.bat`.
5. Faire `Ctrl + F5`. Dans les diagnostics ou `/api/data`, vérifier `engine_version: "v6.9.1"`.

Les anciens scores v6.7 **ne sont pas réécrits** : un coin peut rester archivé avec l'ancien classement jusqu'à sa réanalyse. Les nouvelles détections seront identifiées `analysis_version: "v6.9.1"`.

## Interprétation des résultats

Ce patch enlève un goulot d’étranglement de découverte, mais ne garantit ni beaucoup d’alertes « À étudier » ni la détection d’un pump. L’absence de liquidité DEX sur une courbe ne prouve pas sa sécurité ni sa possibilité de revente. Les indicateurs de volume et de transactions peuvent être manipulés.

Les scans restent limités en fréquence et en nombre de contrats analysés. Les requêtes RPC des wallets peuvent encore ralentir le scan principal. Les tests restent hors ligne : API réelles et performance prédictive non garanties.

**Pour l’audit suivant :** conserver `radar.db`, relever dans `/api/data` `status.engine_version`, `status.scanned`, `status.pairs_found`, `status.new_candidates`, puis observer pendant plusieurs heures.
