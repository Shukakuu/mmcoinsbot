# MemeRadar v6.9 — Bonding curves et mesure prospective v3

## Pourquoi cette version

Dans la base précédente, la plupart des nouvelles paires Pump.fun / Meteora DBC avaient un `liquidity.usd` absent dans les données DexScreener. Il ne faut pas interpréter `null` comme zéro : un marché sur courbe est tradable avant la création de la réserve AMM classique. L'ancien score exigeait néanmoins une liquidité DEX ≥10 000 USD pour devenir « À étudier », ce qui excluait mécaniquement ces lancements.

## Ce qui change

- Deux modèles **dans un seul tableau** : `amm` pour les pools DEX dotés de liquidité et `curve_experimentale` pour les marchés sur courbe **probables** (identification par `dexId`/URL et absence de liquidité DEX). Cette classification est une hypothèse : l'état de la curve **n'est pas confirmé on-chain**.
- Le modèle sur courbe calcule sa propre note expérimentale à partir de la capitalisation indicative, du volume 5 min, du nombre de transactions, du pourcentage d'achats et d'un momentum limité. Il ne remplace **pas** la liquidité manquante par un chiffre fictif. Les seuils sont heuristiques, non calibrés.
- Un signal « Courbe : pression avant hausse » peut placer un token **« À étudier »** avant un pump, sans nécessiter 10 000 USD de liquidité DEX, MAIS uniquement si les autorités mint/freeze sont vérifiées comme désactivées, un rapport RugCheck existe et qu'aucune alerte grave bloquante n'a été détectée. Un premier signal 5 min n'est pas une confirmation de deux observations indépendantes.
- Ce statut est une **invitation à examiner manuellement**, jamais une validation d'achat. L'indicateur interne `eligible` reste `false` lorsque les réserves de courbe ne sont pas vérifiées.
- S'il y a plus de 40 nouveaux candidats, une présélection par lots de 30 adresses DexScreener peut examiner jusqu'à 60 contrats puis prioriser les marchés récents et actifs dans les 14 analyses coûteuses habituelles. Les limites de requêtes des autres fournisseurs et les pauses 429 restent appliquées.
- Les filtres d'interface démarrent avec **score >40**, risques et cotations périmées masqués. Ils restent configurables. La version utilise une nouvelle clé locale pour éviter de conserver un ancien filtre « >55 » trop restrictif.
- Un petit volet **Résultats des alertes** affiche les résultats prospectifs V3 à la demande, sans ralentir chaque scan.

## Recherche V3 (séparée de V2)

- Chaque alerte commence à son prix et son heure précis, et reste attachée au **mint** plutôt qu'à la paire initiale ; une nouvelle paire lors d'une migration pourra fournir le prix de suivi (avec mention de migration).
- Horizons +5, +10, +20, +60 minutes : tolérance **symétrique ±85 s**, sans chevauchement entre horizons. Le relevé valide le plus proche de la cible est privilégié.
- Un **heartbeat** stocke les moments où le programme fonctionne. Une observation non disponible à l'échéance pendant un arrêt est comptée « hors ligne », pas -100 %. Une observation sans cotation pendant le fonctionnement est « non cotée » : elle n'est pas assimilée à une perte de 100 % ni un gain de 0 %.
- Le groupe témoin exclut les tokens présentant des risques identifiés et exige les autorités désactivées et le rapport RugCheck présent. Le rapport sépare les régimes (courbe/pool), âges et classes de taille. Ce n'est **pas** un appariement statistique causal complet.
- Les vieux résultats de `research_events_v2` sont conservés, mais ne sont **jamais mélangés** aux nouveaux résultats V3. Pour voir la V3 : `/api/research` ou « Résultats des alertes ».
- Un intervalle de Wilson à 95 % est calculable pour le taux de résultats positifs *observés* ; il ne couvre pas les cotations manquantes ni le risque de slippage.

## Ce que cette version ne fait PAS encore

- Lire directement les réserves et la progression de graduation sur Pump.fun ou Meteora DBC.
- Identifier les acheteurs uniques et les transactions de wash trading sur chaque curve.
- Garantir la possibilité ou le prix d'une sortie. Le prix et la capitalisation DexScreener sont indicatifs et peuvent être retardés.
- Découvrir tous les lancements à la seconde : DexScreener et GeckoTerminal sont des agrégateurs, pas un abonnement direct à chaque événement Solana.
- Prouver qu'une alerte précédait un pump historique sans historique horodaté complet du même contrat.
- Valider la stratégie sur les marchés en direct ; les tests exécutés ici utilisent des données simulées.

## Installer sous Windows

1. Fermer l'ancien bot (`Ctrl+C`). Sauvegarder **tout** le dossier, en particulier `radar.db` et `wallets.txt`.
2. Extraire la nouvelle archive dans un nouveau dossier, par exemple `MemeRadar_v6_9`.
3. Copier `radar.db` et `wallets.txt` depuis l'ancien dossier vers le nouveau.
4. Lancer `START_J7.ps1` avec une session J7 valide, ou `START_MEMERADAR.bat` sans J7.
5. Recharger l'interface avec `Ctrl+F5`, puis observer les rubans « COURBE · EXPÉRIMENTAL ».
6. Laisser tourner longtemps pour les mesures V3 ; arrêter le bot fait apparaître des échéances « hors ligne » et réduit le nombre de mesures utilisables.

Le bot ne détient jamais de clé privée et n'émet aucune transaction.

## Commandes de vérification

```powershell
py -3 -m unittest discover -s tests -v
py -3 main.py --demo
```

Interface `http://127.0.0.1:8765` ; rapport V3 `http://127.0.0.1:8765/api/research` ; suivi J7 `http://127.0.0.1:8765/api/social-status`.

## Tests / limites de validation

La V6.9 introduit dix+ tests de régression sur la classification de courbes, les risques bloquants, la migration, les échéances non recouvrantes, les arrêts et le groupe témoin. **Aucune API authentifiée ni aucun flux réel J7** n'a été utilisé pendant ces tests ; les quotas et la stabilité doivent être vérifiés sur la machine de l'utilisateur.

## Sources techniques consultées

- https://pump.fun/docs/bonding-curve
- https://github.com/MeteoraAg/docs/blob/main/developer-guides/dbc/index.mdx
- https://docs.dexscreener.com/api/reference
- https://solana.com/docs/rpc/websocket/logssubscribe
