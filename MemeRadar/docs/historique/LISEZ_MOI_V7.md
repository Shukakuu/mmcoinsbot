# MemeRadar v7.0 — Arc GTA VI + J7 + lien Axiom

## IMPORTANT
- **Lecture seule** : aucune connexion à un wallet privé, aucun achat/vente.
- Aucun filtre ou score ne garantit une hausse : la découverte d'une narrative est une **hypothèse** et ne remplace jamais la vérification anti-rug.
- **N'utilise pas de fonds réels pour valider cette version.** Examine d'abord plusieurs sessions et le bilan prospectif, surtout après tes pertes récentes.
- Cette version dérive de v6.9.4 (la version reçue en ZIP était v6.9.3). Elle **n'embarque pas ton radar.db** pour éviter d'écraser l'historique.

## Installation Windows
1. Arrêter l'ancien bot et copier ton `radar.db` dans un emplacement de sauvegarde.
2. Extraire ce ZIP dans un dossier **neuf**.
3. Copier `radar.db` **à la racine du dossier MemeRadar** (et ton `wallets.txt` personnalisé si besoin).
4. Installer si nécessaire `py -3 -m pip install -r requirements-j7.txt`.
5. Lancer `START_J7.ps1`, saisir ton **propre** jeton J7 dans la console, puis ouvrir `http://127.0.0.1:8765`.
6. Vérifier le statut **Moteur v7.0** et le panneau **Diagnostics J7**. Le panneau indique quels comptes prioritaires sont réellement couverts par **ton abonnement**, et ceux absents ou disponibles gratuitement.

## Ce qui change
- **Arc GTA VI** : mise en relation prudente de GTA 6/VI, Vice City et Leonida (et Jason/Lucia seulement lorsqu'un post Rockstar mentionne clairement GTA VI). Contrats identifiés par leur mint ; une ressemblance de thème ne constitue **jamais** une approbation officielle.
- **Sources de contexte** : flux J7 déjà connecté, Google Trends FR/US et titres RSS RockstarINTEL (site indépendant, pas l'éditeur Rockstar). Une panne RSS n'arrête pas le scan. Les titres RSS sont vérifiés sur publication récente.
- **Gros comptes J7** : audit via `GET https://core.j7tracker.io/api/watched-accounts`, seulement sur la session du propriétaire. La liste `elonmusk`, `RockstarGames`, `RockstarSupport`, `blknoiz06`, `MustStopMurad`, `cz_binance`, `theunipcs` est une liste de *couverture souhaitée*, **pas une liste garantie**. Lancer `py -3 tools/j7_watchlist.py` pour voir la couverture ; le script propose, uniquement sur confirmation `AJOUTER`, d'ajouter les comptes déjà disponibles gratuitement dans le pool. Il n'utilise **jamais** de créneau payant et ne crée pas de compte personnalisé. Les comptes absents devront être gérés dans J7. Le bot en lui-même reste en lecture seule.
- **Interface** : nouveau lien « Ouvrir sur Axiom » dans la fiche token, construit avec le **mint** et non l'adresse du pool ; pas de connexion ni d'ordre automatique.
- **Sans changement arbitraire des seuils** : le score de sécurité, les contrôles RugCheck et les inconnues sont préservés. La narrative sert à prioriser une investigation, pas à autoriser un achat.

## Limites réelles
- Le scanner dépend encore de découvertes DEX et des quotas de ses API. Il ne garantit pas une alerte avant le premier pump et ne suit pas les prix en streaming Solana pur.
- L'actualité (même GTA VI) n'est pas une indication fiable qu'un token va monter ; beaucoup de clones servent à attirer des acheteurs avant un dump.
- `rockstarintel.com/feed/` est une source tierce de presse. Les actualités officielles se vérifient sur `https://www.rockstargames.com/VI` ou le Newswire.
- La base de recherche ne permet pas à elle seule de certifier une stratégie profitable ni de calculer une exécution réellement possible.

## Couverture J7 : étape conseillée dès l'installation
Ouvrir un autre terminal dans `MemeRadar`, exécuter `py -3 tools/j7_watchlist.py`, saisir ton jeton J7 de manière masquée. Choisir `AJOUTER` seulement pour les comptes présents dans le pool gratuit. Relancer ensuite le bot pour réactualiser le diagnostic de couverture. Cette opération est facultative, explicite et indépendante de la logique de trading.

## Vérifier
`py -3 -m unittest discover -s tests -q`

Site externe Axiom : `https://axiom.trade/meme/<MINT>` (ne pas confondre avec des domaines similaires).
