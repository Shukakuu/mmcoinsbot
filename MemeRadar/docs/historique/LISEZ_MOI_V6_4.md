# MemeRadar v6.4 — scanner rétabli et vérification X optionnelle

## Changements

- Tous les correctifs v6.3 conservés : pages supplémentaires de découverte Gecko, budget de priorité aux nouveaux memecoins, diagnostic de liste vide, suivi J7 avec CA exact.
- J7 continue à détecter les contrats via les posts, métadonnées et liens. Un post J7 non certifié peut proposer un **contrat à examiner**, mais ne donne **aucun bonus d’attention**.
- Une mention n’augmente la **priorité d’investigation** que si l’auteur a un badge `verified: true` **confirmé par l’API officielle X**, et a au moins 50 000 abonnés. Les profils très récents ou à cadence de publications extrême sont signalés et exclus du bonus. Deux auteurs différents sont nécessaires au motif "J7 multi-comptes".
- La consultation des profils X est optionnelle et peut être payante. Aucun accès X n’est inclus. Sans jeton X, les comptes J7 sont marqués "badge non vérifié" et les mentions continuent d’alimenter la découverte, mais pas le bonus. Aucun contournement X ni scraping de comptes.
- **Un badge X n’est pas une preuve d’identité**, ni un audit de vrais abonnés : nous ne prétendons pas mesurer le pourcentage de bots. Pour cela, il faudrait une API autorisée d’échantillonnage des abonnés et une analyse statistique, avec ses propres erreurs possibles.

## Démarrage Windows

1. Fermer l’ancienne version avec Ctrl+C et sauvegarder `radar.db`, `wallets.txt`.
2. Extraire v6.4 dans un nouveau dossier. Copier `radar.db` et `wallets.txt` depuis l’ancien dossier **après arrêt de l’ancien bot**. Sans `radar.db`, l’historique repart de zéro et le nombre de coins affichés baisse.
3. Démarrer `START_J7.ps1` comme avant. La surveillance DEX fonctionne sans J7.
4. Si tu as un accès développeur **officiel** à l’API X, dans PowerShell avant le lancement : `$env:X_BEARER_TOKEN = 'TON_JETON_X'`. Puis lance `./START_J7.ps1`. Ne colle jamais de jeton dans les fichiers du projet ou dans une capture. La clé reste dans la session du terminal.
5. `Ctrl+F5` dans le navigateur, puis contrôler `/api/data` (filtrage et découverte) et `/api/social-status` (J7 et vérification X).

Le filtre reste score >40 par défaut, risques masqués, avec bouton de diagnostic si tout est caché. Les scores sont expérimentaux ; ce ne sont pas des pourcentages de hausse. Les tests sont hors ligne et ne valident pas la connexion X ou J7 réelle. Aucune transaction n’est possible.
