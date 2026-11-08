# MemeRadar v8.1 — correctifs, suivi et interface accélérée

Version du 7 novembre 2026, basée sur la v8.0 code seul et votre configuration de 353 wallets. Application locale, lecture seule : aucune transaction, aucun achat automatique, aucune clé privée. Les scores restent des classements heuristiques, pas des probabilités de hausse.

## Mise à jour Windows

1. Arrêter complètement l'ancien bot. Sauvegarder son dossier et surtout sa base `radar.db`.
2. Extraire cette archive dans **un nouveau dossier**, sans fusionner les anciens modules.
3. Copier votre `radar.db` le plus récent à côté de `main.py`, après arrêt de l'ancien bot. S'il reste des fichiers `radar.db-wal` et `radar.db-shm`, conserver une copie de l'ensemble avant toute manipulation : une copie isolée de la base pendant qu'elle tourne peut perdre des observations.
4. Le nouveau `wallets.txt` contient les 5 adresses actives de votre export : **EustazZ, Tuults, Chris, Commeoit, tr77ck**. Les 353 adresses sont conservées dans `wallets_registry.json` et `wallets_all.txt`. Si votre configuration locale a changé depuis l'export, conserver également votre ancien fichier pour comparaison.
5. Ouvrir un terminal dans le dossier contenant `main.py`, puis installer :

```powershell
py -3 -m pip install -r requirements-j7.txt
```

6. Lancer `START_V8.bat` pour J7, ou exécuter :

```powershell
powershell -NoProfile -File .\START_J7.ps1
```

Le jeton J7 est demandé avec saisie masquée. Utiliser votre jeton de session J7, jamais une clé privée de wallet. Sans J7, utiliser `START_MEMERADAR.bat`.

7. Ouvrir **http://127.0.0.1:8765**. La version affichée est V8.1. Le lancement direct est aussi possible :

```powershell
py -3 main.py --no-browser
```

Le bouton « Relancer les services » fonctionne avec les lanceurs fournis : ils relancent Python après son arrêt. Avec `python main.py` lancé directement, le bouton arrête le processus avec le code 75 ; il faut le relancer manuellement.

## Historique et migration

Cette archive ne contient **pas de radar.db** et n'invente aucun historique. Sans base copiée, le programme crée une base vide.

Le schéma passe de 8 à 9. Les tables historiques restent présentes. Une correction retire les anciens montants `initial_buy_sol` du registre des lancements : la v8 y stockait `initialBuy`, dont l'unité n'était pas validée comme SOL. Les nouveaux montants ne sont renseignés que si le champ explicite `solAmount` est fourni. Une sauvegarde reste nécessaire pour revenir à la v8, qui refuse un schéma plus récent.

## Ce qui change

- **Affichage rapide :** suppression de 900 lectures inutilisées pour 300 tokens, index sur la date des coins, lectures SQLite sans verrou d'écriture et regroupement des risques de lancement dans une seule requête.
- **Réseau :** découvertes Dex/Gecko en parallèle ; jusqu'à 3 contrôles RugCheck en vol pendant la vérification Gecko. Les espacements globaux et pauses HTTP 429 restent actifs. Pas de rafales illimitées.
- **Tokens pas encore cotés :** jusqu'à 12 tentatives bornées dans la voie rapide, par lots de 30, avec délais croissants de 5 à 60 secondes. Les contrôles déjà obtenus, notamment les risques, ne sont pas écrasés. La file persistante historique continue aussi ses tentatives.
- **Calculs :** variations exactes des soldes en unités entières ; transferts entre comptes d'un même wallet neutralisés ; transactions échouées ignorées. Une transaction non disponible ne fait plus avancer le curseur.
- **Classement :** pas de bonus numérique pour une simple augmentation de solde. L'absence de preuve sur les autorités mint/freeze ne permet plus d'obtenir le statut « À étudier » dans le score AMM. Normalisation corrigée du score de priorité des courbes (maximum de composantes marché 82, pas 50).
- **Mesures :** attente jusqu'à la fin de la tolérance avant de déclarer une cotation J7 manquante. Suivi J7 ajouté à 10 min, 3 h et 6 h ; suivi des lancements prolongé au-delà de 6 h. Témoins servis selon l'échéance pour limiter leur privation de cotations. Cohorte figée à la première réception, sans réétiquetage après coup.
- **Interface :** filtre score ≥ 40 par défaut, choix de l'horizon, redémarrage, gestion du refus d'un refresh concurrent, absence de requêtes périodiques superposées pour un même endpoint.
- **Auteurs :** historique local des mentions contractuelles directes, ID stable quand reçu, pseudo, abonnés, badge déclaré par J7 et variations observées. Reposts, réponses et backlog exclus des statistiques d'attribution. Aucun classement de rentabilité ajouté.
- **Vamps :** rapprochement de contrats distincts avec même nom normalisé **et** même ticker. Le même mint n'est jamais compté deux fois. Indication « copie possible », sans prétendre identifier le token original ou prouver un déplacement d'acheteurs/liquidité.
- **Wallets :** le registre est maintenant lu et visible avec les noms des 5 adresses effectivement interrogées. Les 348 autres restent en inventaire, pas en surveillance temps réel.

## Lire l'interface

« Tous les scores / non cotés » affiche aussi les candidats dont le score est inconnu. Le filtre ≥ 40 les masque dans le tableau ; les créations reliées restent visibles séparément. Une ligne « Risque » peut avoir un score élevé : le score n'annule jamais le risque.

« Tokens cotés » compte les tokens ayant eu une cotation ; cela ne prouve pas qu'elle est actuelle. Vérifier l'âge de la dernière cotation dans la fiche. Un token ancien devient « Historique ». Les badges J7 ne sont pas des certifications indépendantes d'identité, et la proportion de bots dans les abonnés reste inconnue.

Le volet « Auteurs, copies possibles et wallets » est descriptif. Il examine au plus 1 000 posts sur 7 jours et 5 000 lancements sur 24 h. Les correspondances affichées sont bornées ; ce n'est pas un inventaire complet de toutes les copies Solana. Les statistiques auteur portent seulement sur le premier lien direct suivi pour un mint : elles ne représentent pas toutes les publications d'un auteur.

## Formules et horizons

Variation observée : `(prix_sortie / prix_référence - 1) × 100`. Exemple : 10 → 11 donne +10 %, 10 → 2 donne −80 %. La médiane est calculée uniquement sur les variations observées ; les absences sont comptées séparément, jamais remplacées par un profit ou par −100 %.

Deux mesures distinctes sont conservées :

| Mesure | Référence | Horizons |
|---|---|---|
| Comparaison lancements J7 / témoins | Première cotation entre réception +30 s et +160 s | 5, 10, 20 min, 1, 3, 6 h depuis réception |
| Historique J7 par première mention | Première cotation effectivement reçue, recherchée pendant 10 min | 1, 5, 10, 20 min, 1, 3, 6 h après cette cotation |

La comparaison prend la première cotation à partir de l'horizon, dans une tolérance de 130 s. Le tracker J7 utilise une tolérance de 90 s. Ce sont des observations de prix, **pas des gains nets** : frais, slippage, taxe éventuelle et possibilité de vendre ne sont pas simulés. Un arrêt du bot ou une saturation laisse des mesures absentes. L'heure de réception du lancement n'est pas une heure de création on-chain vérifiée.

## Combien de temps laisser tourner ?

- Quelques minutes : vérifier connexion J7, flux Solana, réception de publications et nouveaux lancements.
- Au moins 6 h 15 après un nouveau signal : permettre les observations jusqu'à 6 h, si les cotations arrivent et que le bot reste allumé. Ce délai ne garantit pas un échantillon suffisant.
- Une session de 24–48 h : recueillir un premier journal utile des erreurs et délais. Une durée seule ne prouve aucun avantage ; vérifier nombre de mesures et taux d'absence.

Pour une analyse ultérieure, arrêter le bot et transmettre sa base actualisée. Ne pas transmettre le jeton J7. Les tableaux ne prouvent ni causalité J7 ni rentabilité d'une stratégie.

## Coût et limites des sources

Les abonnements PumpPortal demandés restent uniquement `subscribeNewToken` et `subscribeMigration`. Aucun flux de trades facturé n'est demandé. La connexion sans clé est tentée ; en cas de refus du fournisseur, le diagnostic l'indique. Une clé peut être fournie via `PUMPPORTAL_API_KEY`, sans que le programme n'achète de service.

Cielo n'est pas intégré. Le RPC public ne permet pas de promettre une surveillance complète et instantanée des 353 wallets. Le moniteur lit au maximum 5 signatures par passage et peut manquer une activité plus dense ; une hausse de solde peut être un transfert ou un airdrop. Il ne calcule pas un PnL réalisé et ne prouve pas les achats/ventes.

Les scores restent heuristiques. La détection des vamps par images, liens sociaux communs, flux nets ou migrations de détenteurs n'est pas implémentée. Les performances sociales ne modifient pas automatiquement la priorité ou le score : il faudrait une évaluation prospective avant de l'autoriser.

## Validation et dépannage

```powershell
py -3 -m unittest discover -s tests -q
py -3 main.py --demo --no-browser
```

En mode démo, les tokens sont fictifs et les services externes ne sont pas contactés. Si le port est occupé, arrêter l'autre instance ou choisir `--port 8766`.

Le rapport détaillé est dans `AUDIT_V8_1.md`. Le benchmark reproductible :

```powershell
py -3 tools\benchmark_view.py .
```

Mesure locale sur 300 coins et 18 000 relevés, médiane de 5 appels à `Radar.view()` : v8.0 **289,53 ms**, v8.1 **3,86 ms** ; JSON environ 899 ko → 86 ko. Cela mesure l'assemblage du tableau de bord, pas l'affichage complet du navigateur, ni la rapidité des fournisseurs ni la performance financière.

Documentation des protocoles vérifiée le 7 novembre 2026 :
- https://docs.dexscreener.com/api/reference
- https://docs.j7tracker.io/docs/feed
- https://pumpportal.fun/data-api/real-time/
