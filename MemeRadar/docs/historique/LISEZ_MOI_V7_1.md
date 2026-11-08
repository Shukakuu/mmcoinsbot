# MemeRadar v7.1 — Radar J7, narratives et interface sombre

## Objectif
Détecter des événements sociaux et des lancements Solana **avant** qu'ils soient déjà trop vieux pour être étudiés, sans prétendre prédire la hausse ni la sécurité d'un memecoin. **Lecture seule** : aucune clé privée, aucun achat, aucune vente ni copie automatique de positions. La v7.1 ne constitue pas un système de trading validé. À utiliser en observation, particulièrement après des pertes.

## Installation sur Windows 11
1. **Arrêter** l'ancien bot, puis sauvegarder son dossier et `radar.db`.
2. Décompresser le ZIP dans un **nouveau dossier**, sans l'écraser par-dessus l'ancien.
3. Avec le ZIP **avec historique**, une copie de `radar.db` (6 984 tokens de l'archive fournie) est déjà incluse. Pour conserver les observations faites **après** cet export, remplacer cette copie par ton `radar.db` le plus récent, après l'avoir sauvegardé. Avec le ZIP **code seul**, copier ton `radar.db` à la racine du nouveau dossier `MemeRadar` ; sinon une base vierge sera créée.
4. Dans PowerShell à la racine du dossier :

   ```powershell
   py -3 -m pip install -r requirements-j7.txt
   ```

5. Lancer `START_J7.ps1` (si Windows demande une confirmation PowerShell, autoriser le script que tu viens de vérifier). Saisir le jeton J7 au prompt ; ne jamais le publier.
6. Ouvrir `http://127.0.0.1:8765` ; vérifier **Moteur v7.1**. Le bouton de relance redémarre le processus uniquement avec le lanceur.
7. Pour observer les comptes effectivement suivis par J7 : `py -3 tools/j7_watchlist.py`. Le script n'ajoute aucun compte de manière automatique ; toute proposition d'ajout gratuit demande confirmation.

## Architecture et priorités de la v7.1
- **J7/X** : reçoit les tweets, reposts et enrichissements tardifs. Repère les contrats **exacts** et des hypothèses de mots/memes (« DOOMSDAY », « GTA VI », « LEONIDA », etc.). Ce repérage est notre propre logique explicable, **pas l'algorithme de surlignage propriétaire de J7** ; les mots ne prouvent aucune affiliation officielle.
- **J7 hors X** : examine les événements sociaux et les cartes structurées de nouvelles paires (`pumppairs`, `ponspairs`, `stonkpairs`) quand elles existent dans le flux effectivement reçu. Les mentions de YouTube/TikTok ne deviennent jamais automatiquement des contrats.
- **Mots en veille** : garde les narratives et les origines des événements dans SQLite, pour rapprocher également les tokens créés **après** le tweet. Les clones restent plusieurs candidats séparés, pas des tokens approuvés.
- **Voie rapide** : les événements J7 contenant un mint et les nouveaux lancements connus passent dans un petit processus de vérification indépendant. Tant que le marché ou RugCheck ne sont pas disponibles, le token peut apparaître **Incomplet, non vérifié**, avec score 0. La vérification normale continue ensuite ; aucun contrôle de sécurité n'est contourné.
- **Recherche** : revoit les coins existants correspondant aux phrases, sans limiter la base historique aux derniers 5 000 tokens.
- **Anti-rug existant** : conserve RugCheck, état de la bonding curve, suivi prospective et filtres de l'ancien scanner ; les narratives **ne font jamais grimper** artificiellement le score ou l'éligibilité. Il reste des risques non détectés (clusters de premiers acheteurs, ventes coordonnées, sorties impossibles).
- **Interface** : sombre et compacte, mots en veille, filtres avancés repliés, statut de fraîcheur des coins, lien **Axiom** basé sur le mint sur chaque ligne et dans le détail, copie du contrat.

## Sources et coût
- J7 : abonnement/session que tu possèdes déjà ; la couverture des comptes de célébrités dépend de tes comptes réellement surveillés.
- DexScreener, GeckoTerminal, RugCheck, sources de tendances : intégrations existantes, soumises aux quotas et délais.
- **PumpPortal : FACULTATIF**. Sans `PUMPPORTAL_API_KEY`, le flux n'est pas lancé et aucun supplément n'est nécessaire. Si tu as déjà **une clé obtenue auprès du service**, tu peux définir `PUMPPORTAL_API_KEY` dans ton environnement avant le démarrage. Cette intégration ne s'abonne qu'aux créations/migrations annoncées gratuites ; **aucun flux facturé de transactions, aucun appel d'achat ni connexion de wallet**. Vérifie les conditions du fournisseur avant d'activer. Le jeton reste local, n'est pas écrit dans SQLite et n'est pas inclus dans les archives.

## Diagnostic et limites
- Le bandeau **Mots en veille** affiche les mots remarqués par le moteur, **pas des tickets d'achat** ni des prévisions de rentabilité.
- L'étiquette **Incomplet** signifie données absentes, **jamais** « sûr » ; en particulier les nouveaux mints sans cotation peuvent être invendables ou manipulés.
- Les événements d'un gros compte peuvent être des blagues, reposts, citations, ou concerner des tokens sans relation avec lui. L'historique doit permettre d'estimer leur valeur réelle.
- La voie rapide n'efface pas l'attente d'un fournisseur pour obtenir une cotation ; sans flux de trades non facturé, elle **ne garantit pas** une réaction avant les snipers.
- Les calculs de score/market-cap non calibrés ne prouvent pas un gain net après slippage, frais, latence et impossibilité éventuelle de vente.
- Cette mise à jour améliore la collecte et le tri des événements, **mais n'est pas une preuve que le taux de rugs a diminué**. Il faut des essais en lecture seule avec résultats à +5/+20/+60 min et vérification des changements de pools.

## Tests et démarrage démo
```powershell
py -3 -m unittest discover -s tests -q
py -3 main.py --demo --no-browser --port 8766
```
Puis ouvrir `http://127.0.0.1:8766` pour tester l'interface avec des tokens fictifs.

En cas de problème : conserver `radar.db`, lister les diagnostics du programme et la version affichée, puis comparer les mêmes tokens à la dernière version.
