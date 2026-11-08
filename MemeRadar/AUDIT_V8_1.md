# Audit v8.1 — 7 novembre 2026

## Portée réelle

Base : `MemeRadar_v8_0_J7_TempsReel_CodeSeul.zip` et `MemeRadar_Configuration_353_Wallets.zip`. Revue des parcours actifs de découverte, scoring, cotation rapide, journaux SQLite, J7, wallets, calculs et interface. Compilation de tous les modules Python et tests de régression. Les anciens documents et anciens frontends sont conservés dans `docs/` comme archives, pas comme documentation de la version actuelle.

Il ne s'agit pas d'une certification exhaustive de chaque ligne historique, ni d'une validation en conditions de marché. Aucune session J7 réelle, aucun suivi financier ni test Windows réel n'a été effectué ici. Le navigateur de test n'a pas pu démarrer dans cet environnement ; la vérification visuelle interactive reste non réalisée. La syntaxe JavaScript et les routes HTTP locales sont contrôlées séparément.

## Corrections et preuves

| Problème | Correction / vérification |
|---|---|
| Solde converti en float, unité décimale plafonnée à 18 | Différence sur entiers bruts par mint ; test +1 au-delà de la précision float, transfert interne et transaction échouée |
| Transaction RPC absente consommée par le curseur | Conservation du curseur, nouvelle tentative au prochain passage |
| Cotation rapide unique | File de tentatives bornée, délais croissants, récupération d'un token pas encore indexé, risque conservé |
| File d'événements pleine bloquant une nouvelle soumission | Retrait de l'anti-doublon si l'insertion échoue |
| Quote provisoire gardant le nom « ? » | Nom/ticker synchronisés depuis les métadonnées DEX dans JSON et colonnes SQLite |
| Bonus score pour hausse de solde | Bonus retiré ; annotation descriptive conservée |
| Promotion avec autorités inconnues | Autorités explicitement révoquées requises pour le statut « À étudier » AMM |
| Horodatage au début du scan ou de la requête | Cotation horodatée à réception, fraîcheur affichée depuis le relevé |
| Priorité courbe divisée par 50 malgré un maximum 82 | Dénominateur corrigé pour cette branche |
| `initialBuy` présenté comme SOL | Champ non utilisé comme SOL ; migration nettoyant les anciennes valeurs ambiguës |
| Échec transitoire J7 déclaré définitivement manquant | Attente jusqu'à fin de la tolérance ; test récupération à +80 s |
| Mesures longues impossibles | Collecte prolongée après 6 h ; horizons ajoutés ; sélection des échéances dues |
| Témoins repoussés indéfiniment par les signaux | Échéance prioritaire dans la file de cotations |
| Cohorte modifiée après première observation | Affectation figée à réception, test anti-réétiquetage |
| 900 requêtes inutilisées à chaque vue de 300 coins | Retrait des champs non consommés par le frontend v8 ; ~74,9× sur le microbenchmark d'assemblage local |
| Lectures SQLite prenant des verrous d'écriture | Connexions `query_only` pour méthodes de lecture identifiées, index coins, jointure des risques |
| Providers séquentiels | Deux découvertes concurrentes, maximum 3 RugCheck en vol ; pacer global maintenu |
| Valeurs non finies / booléennes | Gardes numériques pour les champs concernés ; soldes RPC illisibles laissés inconnus |
| Rafraîchissement annonçant un succès HTTP 409 | Message d'erreur affiché ; polling séquentiel par endpoint |

## Ajouts limités aux preuves disponibles

`radar/intelligence.py` : regroupement de clones potentiels nom + ticker, déduplication par mint, ordre de première réception sans affirmation d'origine ; registre wallet et sélection active ; auteurs indexés par ID quand disponible, statistiques locales limitées aux premières mentions contractuelles directes suivies. Aucune preuve d'identité réelle, de coordination, de bots ou de rentabilité n'est fabriquée.

## Validation reproductible

- Suite de la base v8.0 : 199 tests réussis avant modification.
- Suite v8.1 : **223 tests réussis**. Tests historiques conservés, attentes mises à jour uniquement pour version, migration, unité et attente de fin de tolérance ; nouveaux tests ciblés dans `tests/test_v81.py` et `tests/test_http_v81.py`.
- `python -m compileall -q .` et `node --check web/v8.js`.
- Les résultats d'exécution sont joints dans `docs/validation_tests.txt`.
- Benchmark reproductible dans `tools/benchmark_view.py` : même jeu synthétique 300 coins / 18 000 prix, base temporaire, 5 appels ; aucune requête externe. Médiane 289,53 → 3,86 ms. Les champs historiques retirés de `/api/data` restent stockés, mais un consommateur tiers de cet ancien JSON devra s'adapter.

## Points qui restent ouverts

- Promesse « alerte <30 s » non démontrée ; dépend des flux, indexeurs, réseau, saturation et quotas. Les nouvelles tentatives évitent un abandon prématuré mais ne rendent pas un prix disponible avant sa publication.
- Pas de validation live J7/PumpPortal/RugCheck ni d'installation Windows dans cet environnement. Les APIs ont été consultées dans leur documentation officielle.
- Scores heuristiques, courbe probable déduite du DEX, concentration privée dépendante de l'identification des réserves par le fournisseur.
- Pas de PnL net, de frais/slippage simulés ni d'identification des wallets liés. Limite de 5 signatures par wallet et par passage.
- Vamps : pas d'analyse d'images, de flux de détenteurs ni de preuve de drainage de liquidité. Les rapprochements sont bornés aux lancements récents observés.
- Auteurs : statistiques descriptives de première mention, pas historique exhaustif des pumps ni prédiction hors échantillon ; les taux de données absentes restent essentiels.
- Les tables de recherche historiques v1/v2/v3 conservent leurs conventions, notamment les scénarios de sensibilité v2. Elles ne doivent pas être mélangées aux résultats de comparaison des lancements.
- Files, échantillons et fenêtres bornés : en forte charge, des données peuvent manquer. Les observations manquantes ne sont pas des rendements nuls.
