# MemeRadar v6.1 — interface simplifiée, compatibilité v5

## Installation

1. Fermez l'ancien bot avec Ctrl+C. Gardez une sauvegarde complète de son dossier.
2. Extrayez le nouveau ZIP dans un dossier séparé.
3. Copiez votre radar.db et wallets.txt depuis l'ancien dossier après son arrêt. Ne copiez pas une base en cours d'utilisation. Si des fichiers radar.db-wal et radar.db-shm restent présents, gardez-les avec la base dans votre sauvegarde.
4. Lancez START_J7.ps1. Le jeton est saisi de façon masquée pour cette session seulement. Le lanceur est encodé pour Windows PowerShell et reste ouvert en cas d'erreur.
5. Ouvrez http://127.0.0.1:8765 et faites Ctrl+F5. Si la liste reste vide, cliquez « Tout afficher » pour réinitialiser les anciens filtres mémorisés dans votre navigateur.

L'archive contient le programme et les tests, pas une copie de votre base ou un jeton J7. La base v5 est compatible, de même que la base v6. Les nouvelles tables sont ajoutées sans effacer l'historique.

## Corrections

- Suppression du panneau « Mentions des gros comptes » et de ses cartes de tweets. J7 continue à analyser en arrière-plan. Une seule ligne indique sa connexion ou son erreur ; les mentions pertinentes restent dans la fiche de chaque coin.
- Suppression du grand journal de statistiques et des simulations de la page. Le journal initial et les observations continuent en arrière-plan.
- Retour au filtrage v5 : score > 40 et risques masqués par défaut. Le nouveau filtre v6 exigeant eligible=true et une observation de moins de trois minutes a été retiré. Il masquait tous les anciens enregistrements avant leur réanalyse. La date du relevé reste visible ; une ancienne observation n'est pas présentée comme un prix actuel garanti.
- Les erreurs Gecko 429 sont regroupées dans une petite ligne « Gecko : pause … s ». La pause respecte toujours le mécanisme existant de temporisation. Aucun nouveau prix Gecko n'est inventé et une ancienne confirmation n'est pas recyclée comme actuelle. Les points de confirmation restent indisponibles lorsque la source ne répond pas. DexScreener et l'analyse continuent.
- Transactions SQLite réservées avant toute lecture/modification et accès sérialisés : protection contre les conflits entre le flux J7, le scanner et le suivi des résultats. Une erreur de mise à jour J7 est effacée à la réception réussie suivante. Une erreur OperationalError d'une autre cause reste possible ; les tests ne prouvent pas rétrospectivement la cause exacte de chaque erreur sur votre PC.
- Le port HTTP est réservé avant de démarrer les scanners, afin qu'une seconde instance ne démarre pas un autre travail de fond quand le port est occupé.

## Calculs conservés

Le score technique historique reste utilisé par le curseur et affiché dans sa colonne. La priorité expérimentale v6 sert au tri « Priorité » après le statut : 70 × score marché / 50 + min(30, 5 × auteurs sur 5 min + 5 × augmentation positive par rapport aux 5 min précédentes). L'âge n'entre pas dans cette priorité. Les impulsions peuvent être détectées sur les anciens tokens.

Les événements J7 avec adresse exacte alimentent une file persistante. Les contrats sans paire exploitable restent hors de la liste. Le badge J7 indique la provenance ; il ne garantit pas une hausse. Les tweets contenant seulement un ticker ne sont pas associés à un contrat supposé.

Les sorties restent manuelles. Aucune clé de wallet, aucun ordre d'achat ou de vente. Ce correctif vise l'affichage et la stabilité ; il ne démontre pas une rentabilité ni une capacité prédictive nouvelle.

## Résultats et limites

54 tests hors ligne passent, incluant 80 écritures concurrentes de publications avec calculs du journal via quatre instances de Store, un scan avec Gecko en pause 429, les données v5 sans eligible, et le suivi v6.

La logique de rendu a aussi été exécutée avec une copie de votre base : 300 dernières lignes accessibles, 8 visibles avec les filtres par défaut au moment du test. Aucun seuil n'a été artificiellement abaissé pour obtenir ce résultat. Le tableau conserve la limite historique des 300 derniers coins.

Syntaxe Python et JavaScript vérifiée. Mise en page non validée dans un navigateur réel dans cet environnement ; le rendu a été testé avec un DOM simulé. Connexion J7 authentifiée et appels de marché non testés en continu ici.

Un 429 peut encore survenir malgré la temporisation : le programme ne peut pas lever la limite du fournisseur. Les coins ne disparaissent plus à cause du filtre v6, mais un score sous votre seuil ou un statut à risque peut toujours masquer une ligne. « Tout afficher » permet de consulter ces analyses sans les considérer comme des recommandations.

Les données insuffisantes, le sentiment des publications, l'indépendance réelle des comptes, les promotions coordonnées et les coûts d'exécution restent des limites. Le suivi conserve la première analyse v6 d'un contrat et des prix échantillonnés ; il ne reconstitue pas les périodes durant lesquelles le bot était fermé.
