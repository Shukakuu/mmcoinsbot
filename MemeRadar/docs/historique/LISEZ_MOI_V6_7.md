# MemeRadar v6.7 — Détection de pression avant mouvement

## Objectif

Le scanner v6.6 pouvait attendre la hausse de prix pour attribuer les points de momentum nécessaires au statut « À étudier ». La v6.7 ajoute une voie expérimentale **qui ne dépend pas d'une hausse** : elle repère des achats relativement soutenus lorsque le cours reste stable. Aucun investissement automatique, aucune clé privée.

## Deux niveaux de vérification

- **Pression acheteuse à confirmer** : premier relevé recevable, le coin demeure en « Surveillance » et est prioritaire pour une seconde vérification.
- **Pression acheteuse avant mouvement** : deux relevés réels sur la *même paire* séparés de 45 secondes à 8 minutes, prix variant de 6 % au maximum entre les deux, et présence continue des indicateurs ci-dessous. Si les vérifications de sécurité passent et que le score existant atteint 50/100, le token peut passer en « À étudier » **sans devoir déjà monter**.

**Conditions de recherche** (expérimentales, à valider sur plusieurs centaines d'alertes) : liquidité ≥ 12 000 $, volume sur 5 minutes ≥ 1 500 $ et ≥ 1,5 % de la liquidité, au moins 24 transactions sur 5 minutes dont 16 achats et 65 % d'achats, montant moyen de transaction ≥ 10 $, prix sur 5 minutes entre -3 % et +4 %, variation 1 h ≥ -25 %. Les contrôles RugCheck, mint et freeze restent obligatoires, le ratio de détenteurs Top 10 doit être ≤ 55 %, la note RugCheck sous 75 et la couverture des preuves ≥ 90 %.

La part d'achats est comptée en **nombre de transactions**, pas en dollars : l'indicateur peut être manipulé, les acheteurs uniques ne sont pas certifiés. Les fenêtres glissantes de 5 minutes se recouvrent ; deux relevés ne constituent pas deux preuves indépendantes. Un token noté « À étudier » n'est pas une promesse de hausse, et peut perdre toute sa valeur.

## Ce qui est conservé

- Score d'origine inchangé ; l'exception concerne uniquement le passage en « À étudier » après confirmation de la pression avant mouvement.
- Scan principal et moteur J7 inchangés, risque/âge de prix (périmé après 5 minutes), redémarrage des services, filtres, favoris et historique.
- Nouveau stockage SQLite `market_snapshots` (créé automatiquement), ne remplace ni ne supprime l'historique antérieur.
- Un coin avec un signal précoce est prioritaire lors des cycles suivants. Cela ne garantit pas que tous les coins sont rafraîchis : la capacité de scan reste limitée par les API.

## Mise à jour Windows

1. Fermer le bot actuel (`Ctrl+C`) et faire une copie de `radar.db` et de `wallets.txt`.
2. Extraire cette archive dans un **nouveau dossier**.
3. Copier les deux fichiers sauvegardés dans ce nouveau dossier (au même niveau que `main.py`). Ne pas copier de jeton X ou J7 dans les fichiers.
4. Lancer `START_J7.ps1` ou `START_MEMERADAR.bat`.
5. Faire `Ctrl+F5` dans le navigateur.

Le suivi de pré-impulsion commence à réunir **ses propres nouveaux relevés** au lancement de la v6.7 ; les anciens cours collectés par v6.6 n'indiquent pas les statistiques d'achats 5 minutes nécessaires à une reconstitution rétrospective fiable.

## Validation effectuée

Tests hors ligne sur les cas : deux observations cohérentes à +0,2 %, première observation seule, exclusion d'une hausse déjà commencée, changement de paire, délai trop court/long, volume trop faible, risque de contrat, statistiques 5 min absentes, persistance SQLite et intégration scanner. Non validé en direct sur plusieurs semaines ; les seuils ne sont pas calibrés pour prédire des rendements.

## Pour une vraie détection plus avancée

Ajouter plus tard un flux on-chain/WebSocket pour suivre achats, **acheteurs distincts**, montants d'achats/ventes en dollars, gros porteurs et transactions coordonnées. Ne pas confondre les transactions et les wallets différents. Comparer prospectivement les alertes avec un groupe de tokens non alertés : taux de x2, drawdown, temps au sommet, liquidité et prix réellement exécutables.
