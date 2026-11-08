# MemeRadar v7.2 — J7 au centre

**Lecture seule.** Aucune clé privée, aucun achat, aucune vente. Un surlignage J7 n'est ni une approbation, ni une preuve de sécurité, ni une prévision de hausse. Il n'augmente jamais le score.

## Ce qui change
1. **Registre des surlignages J7** (`j7_highlights`) : chaque fois que J7 relie une publication ou une carte de lancement à un contrat, le bot enregistre l'auteur, la plateforme, le type de lien, la **latence** (publication → réception chez nous), le nom/ticker si J7 les fournit.
   Types de liens : `token_meta` (le surlignage du panneau J7), `post_ca` (contrat dans un post X), `external_ca` (contrat dans un post Truth Social / Instagram / TikTok / Binance Square…), `launch_card:<pumppairs|ponspairs|stonkpairs>`.
2. **Contrats hors X** : avant la v7.2, un contrat écrit dans un post non-X était ignoré. Il devient maintenant un candidat (même extracteur strict que pour X).
3. **Panneau « Surlignages J7 »** en haut de l'interface : âge, type de lien, auteur, token, statut radar, latence, délai de la 1re cotation, variations à +1 / +5 / +20 min.
4. **Mesure des sources** (volet « Quelles sources J7 valent le coup ? ») : par plateforme/auteur et par type de lien : nombre, latence médiane, part cotée, variation médiane. En dessous de 10 mesures, l'interface affiche « non concluant ».
5. **Télémétrie des formats J7** : le bot garde les **noms des champs** réellement reçus (jamais les valeurs), par type d'événement. Cela permettra de savoir enfin ce que contiennent `tokenMeta`, `grok`, `isContractLaunch`, `coinPairs`, `playSound`, au lieu de deviner.
6. **Origine J7 sur chaque coin** : badge dans la liste et section « Origine J7 » dans la fiche. La voie rapide reprend le nom/ticker donné par J7 quand le marché ne connaît pas encore le token.
7. Correctif : le premier scan wallet pouvait ne pas démarrer sur une machine fraîchement allumée (horloge monotone < 30 s). Le test d'intégration instable correspondant passe désormais.

## Installation (comme la v7.1)
1. Arrêter l'ancienne version, sauvegarder `radar.db`.
2. Décompresser dans un **nouveau dossier**, copier ton `radar.db` à la racine de `MemeRadar` (ce ZIP ne contient pas de base). Les nouvelles tables sont créées automatiquement.
3. `py -3 -m pip install -r requirements-j7.txt`, puis `START_J7.ps1` (jeton J7 demandé, jamais enregistré).
4. Vérifier **Moteur v7.2** et le panneau « Surlignages J7 ».

## Ce qui n'a PAS pu être vérifié
- **Aucune connexion J7 réelle n'a été testée** (pas de jeton ni de réseau dans l'environnement de développement). Le comportement est vérifié avec des événements simulés, à partir des champs vus dans ton ancien journal.
- Le **sens exact** de `isContractLaunch`, `grok`, `playSound` et le contenu de `tokenMeta` sont inconnus. Le bot les enregistre comme drapeaux/clés sans en tirer de conclusion. Après une session, la ligne « Champs réellement envoyés par J7 » du volet de mesure les montre.
- Les variations sont mesurées **depuis la première cotation obtenue** (DexScreener), pas depuis l'instant du tweet. Ce ne sont pas des prix d'exécution : slippage, frais et impossibilité de vendre ne sont pas simulés. Une cotation manquante est « manquante », jamais −100 %.
- **Il n'y a pas encore de groupe témoin** : même avec beaucoup de données, ces chiffres ne prouvent pas qu'un surlignage J7 apporte un avantage. Ils servent à éliminer les sources qui n'apportent rien.

## Limites structurelles (inchangées)
La cotation vient encore de DexScreener/GeckoTerminal par interrogation HTTP : un token neuf peut rester « Incomplet » plusieurs dizaines de secondes à quelques minutes. Pour réellement gagner du temps, il faudra un flux de créations en direct (PumpPortal ou abonnement de logs Solana). Le surlignage J7 réduit la latence **de découverte**, pas celle de la cotation.

## Tests
```powershell
py -3 -m unittest discover -s tests -q
```
185 tests (165 existants + 20 nouveaux dans `tests/test_v72.py`).
