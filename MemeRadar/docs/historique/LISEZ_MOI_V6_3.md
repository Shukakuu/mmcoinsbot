# MemeRadar v6.3 — détection des coins et J7 prioritaire

Cette version corrige les diagnostics de la liste vide et l'allocation de scan : un token découvert mais masqué n'est pas un problème réseau.

## Correctifs

- Le panneau des candidats explique maintenant le nombre de tokens exclus par risque et par score, ainsi que les nouveaux candidats et les paires réellement trouvées au dernier passage.
- Si aucun coin ne passe le filtre, un bouton propose de voir uniquement les candidats non marqués RISQUE, sans inventer de probabilité de gain.
- Le scanner interroge deux pages de nouveaux pools GeckoTerminal pour mieux couvrir les lancements. Les contrôles HTTP 429 et la cache restent actifs. Une page en échec ne bloque pas la récupération des autres sources.
- Le moteur réserve environ trois quarts des places libres aux nouveaux tokens, tout en continuant un suivi tournant des anciens candidats ; il vérifie aussi en priorité les contrats exacts reçus via J7.
- Une mention J7 ne renforce que la priorité de recherche lorsqu'elle est associée à une adresse de contrat Solana explicite. Le calcul social tient compte de plusieurs auteurs distincts avec au moins 50 000 abonnés, sans assimiler mention et achat. Les risques et le statut de sécurité restent indépendants.
- Le flux social et les fonctionnalités v6.2 sont conservés. Le flux J7 est maintenant replié sous la liste des coins, pour laisser la priorité visuelle au scanner ; aucun trade ni clé privée.

## Installation

1. Fermer l'ancienne version avec Ctrl+C ; sauvegarder `radar.db` et `wallets.txt` avant de remplacer les fichiers.
2. Extraire ce ZIP dans un nouveau dossier MemeRadar. **Copier l'ancien `radar.db` du dossier précédent dans ce nouveau dossier**, après arrêt, sinon l'interface redémarre avec une base vide : cela peut expliquer le passage de 50+ à 26 coins.
3. Copier `wallets.txt` si utilisé. Ne jamais copier un jeton J7 dans le projet ni partager la session.
4. Lancer `START_J7.ps1` (ou `START_MEMERADAR.bat` sans J7), puis Ctrl+F5 dans le navigateur.

## Vérifier un scan

- `http://127.0.0.1:8765/api/data` : `stats.stored` = total dans la base ; `status.new_candidates` = nouvelles adresses découvertes ; `status.pairs_found` = paires ayant un prix utilisable.
- Si la découverte est à zéro et GeckoTerminal est en pause HTTP 429, ce n'est pas un problème de filtrage : le bot attend la reprise des sources.
- `http://127.0.0.1:8765/api/social-status` : connexion J7 ; `new_mints=0` peut être normal si les tweets n'ont pas de contrat Solana.
- Si l'interface affiche 0/26 mais que `stats.total=26`, les coins existent en base ; regarder le compte des risques et le seuil, puis éventuellement `Voir les candidats sans alerte`.

**Pas de garantie** : API externes, prix et états de sécurité ne sont pas testés en flux réel ici. Les scores sont des critères heuristiques, pas des chances de hausse.
