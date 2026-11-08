# MemeRadar v6.8 — Signaux précoces, vérification du risque et mesures prospectives

**Usage : scanner en lecture seule pour recherches personnelles. Aucun ordre, clé privée, portefeuille de trading ni promesse de performance.** Les signaux « À étudier » ne sont **pas** des conseils d'achat.

## Le changement essentiel

Les versions précédentes pouvaient rejeter de jeunes tokens à cause d'une concentration brute de détenteurs incluant des réserves de liquidité ou une bonding curve. En v6.8 :

- RugCheck `topHolders` est conservé en **Top 10 brut**, à titre informatif. Pour le **Top 10 hors réserves identifiées**, le code exclut seulement les adresses reconnues à partir de `markets[].liquidityA/liquidityB` et `knownAccounts` (types de pool, AMM, locker, curve, vault). Il ne devine aucune adresse manquante.
- Si les informations ne permettent pas de calculer 10 portefeuilles privés, le score corrigé est **inconnu**. Il n'y a **plus de blocage mécanique** « Top 10 > 55 % ».
- Les alertes RugCheck liées aux détenteurs ne sont plus comptées deux fois comme un risque bloquant. Les risques graves RugCheck de nature différente peuvent encore bloquer. La vérification du Top 10 ne garantit pas l'indépendance des wallets et reste une mesure du pourcentage de l'offre totale, PAS de l'offre en circulation.
- L'écart de prix >5 % entre DexScreener et GeckoTerminal devient un **avertissement de cotation** (latence, volatilité, ou mauvais pool), et non une accusation de fraude. La vérification sur le **même pool** reste requise pour attribuer les points de concordance.
- Restent bloquants : autorité mint active, autorité freeze active, rug explicitement identifié, faible liquidité DEX (<5 000 $), mouvements extrêmes, risques graves vérifiés non assimilables à une simple concentration.

## Pré-impulsion : deux niveaux distincts

**Pression initiale** : un premier relevé sur 5 min, prix entre −3 % et +4 %, volume ≥1 500 $, liquidité ≥12 000 $, au moins 24 opérations et 65 % de transactions à l'achat. Le signal préliminaire peut faire passer en « À étudier » (score ≥45, couverture ≥70 %, contrôles de base présents et absence de risque bloquant). C'est une piste à examiner, pas une confirmation ni une prédiction de hausse.

**Pression confirmée** : deux fenêtres de 5 minutes prises sur la même paire, espacées de 5 à 12 min, avec prix relativement stable. Les fenêtres ne se chevauchent plus. Toujours aucune preuve d'acheteurs indépendants : DexScreener fournit ici des *nombres de transactions*, pas des identités de wallets ni des volumes d'achat nets. Une confirmation plus rapide nécessiterait des transactions on-chain individuelles, horodatées.

Les anciens signaux (départ précoce, momentum, rebond) sont conservés, ainsi que J7 et la classification des risques. Le nombre de coins « À étudier » peut augmenter : ne pas confondre visibilité accrue et précision prédictive prouvée.

## Mesures prospectives v2 (nouveau)

Une table de journal **distincte** conserve chaque type de signal au moment de sa première apparition : adresse du token, pool retenu, **heure de la décision**, **prix de référence, score, âge de la paire, liquidité et latence de la cotation**. Les anciennes métriques de v6 et v6.7 sont conservées en base pour historique, mais **ne sont pas mélangées** à ce journal.

La surveillance essaie de récupérer une cotation **sur la même paire** aux horizons **+5, +10, +20 et +60 minutes**. Une observation réelle est admissible de 90 s avant à 300 s après le rendez-vous prévu. L'heure exacte est conservée : cela évite d'inventer une valeur qui n'a jamais été relevée.

- **Observé** : variation depuis le prix disponible au moment de l'alerte (non nette des frais de trading).
- **Sans liquidité, explicitement constaté** : résultat de sortie pessimiste de −100 %. Ce n'est pas une preuve universelle que le token vaut zéro.
- **Introuvable, API indisponible ou autre pool** : *manquant / non coté*. On n'invente ni bénéfice, ni rug avéré ; les statistiques présentent un scénario pessimiste (manquants à −100 %) et une sensibilité neutre (manquants à 0 %), en plus du rendement médian des seules observations.
- **Témoin descriptif** : une partie des tokens étudiés sans alerte lors du premier contrôle est enregistrée comme `control`. Les groupes sont séparés par âge de paire et tranche de liquidité dans le rapport. Ce n'est **pas** une expérience randomisée ni un appariement causal.

Rapport JSON local : `http://127.0.0.1:8765/api/research` (en fonctionnement live). La fiche d'un coin affiche ses trois dernières alertes et les résultats par horizon. Le quota de sondage est limité par les fournisseurs : des données peuvent encore manquer lors d'un pic d'activité.

**Ne pas régler les seuils sur quelques succès spectaculaires.** Faire tourner une à deux semaines, idéalement collecter plusieurs centaines de signaux et témoins ; comparer ensuite une période d'apprentissage et une période ultérieure non utilisée pour les réglages, sans supprimer les pertes ni les coins indisponibles.

## Performance et hygiène

Les nettoyages d'historique SQLite ont été déplacés hors des écritures par token : un nettoyage horaire et un index sur le timestamp facilitent le fonctionnement prolongé. La base locale utilise toujours des connexions courtes transactionnelles pour privilégier l'intégrité, pas encore un pool de connexions optimisé. Les endpoints POST du serveur local vérifient le `Host`. Le redémarrage complet et J7 restent disponibles.

Une cotation âgée de plus de 60 secondes au moment de la décision déclenche un avertissement ; elle ne peut plus faire remonter directement le coin comme « À étudier » lors de ce scan.

## Installation Windows et conservation des données

1. Fermer l'ancienne instance avec `Ctrl+C`, sauvegarder `radar.db` et `wallets.txt`.
2. Extraire la v6.8 dans un **nouveau** dossier, puis y replacer ces deux fichiers (ne pas copier le jeton J7 dans un fichier).
3. Démarrer `START_J7.ps1` si vous utilisez J7, sinon `START_MEMERADAR.bat`.
4. Faire `Ctrl+F5` dans le navigateur. La page locale reste `http://127.0.0.1:8765`.
5. Vérifier le panneau de scan, les risques et les fiches de coins. L'API `/api/research` peut rester vide pendant le démarrage : il faut des **nouveaux événements prospectifs v6.8** et leurs échéances.

Si Windows affiche un avertissement concernant le script PowerShell, lire et vérifier le script avant de l'autoriser. Ne jamais saisir une phrase de récupération de wallet dans un script. `wallets.txt` accepte uniquement des adresses publiques.

## Idées suivantes, classées par valeur de recherche

1. **Flux de transactions Solana**, sur les coins déjà présélectionnés : acheteurs uniques, montants acheteurs/vendeurs en dollars, nombre de wallets qui augmentent leur position, ventes des premiers acheteurs ; indispensable pour réduire les faux signaux de volumes fabriqués.
2. **Suivi de la bonding curve avant migration** : réserve réelle, progression vers la graduation, flux entrant/sortant. Le même seuil de liquidité n'a pas le même sens sur curve et sur pool DEX.
3. **Comparaison de pairs assorties** : pour chaque alerte, chercher 1 à 3 tokens témoins de même âge, liquidité et activité, dans la même période, sans sélection à posteriori.
4. **Coût de sortie plausible** : courbe de slippage à 10, 50, 100 $ (pas une hypothèse de prix de vente égale au dernier graphique), avec quote réelle et évaluation des swaps interdits.
5. **J7 plus discriminant** : corréler uniquement une adresse Solana **exacte**, des auteurs indépendants et des timestamps avant mouvement ; ne jamais considérer badge bleu ou followers comme preuve de rentabilité ; mesurer les promotions suivies d'une vente brutale.
6. **Robustesse par régime** : analyser séparément jeunes courbes, pools fraîchement migrés et tokens établis, puis séparer les métriques par période sans toucher aux seuils de validation.

## Limites connues

- Sans flux on-chain, une accumulation peut être artificielle. Les 65 % d'achats sont un ratio de transactions, pas un volume net signé ni 65 % d'acheteurs uniques.
- Les données publiques et la disponibilité des API peuvent changer ; une paire peut disparaître sans qu'on sache si c'est un rug ou une panne de fournisseur.
- Aucun test en direct de plusieurs heures n'a été réalisé dans cette livraison. Les tests automatisés vérifient la mécanique, pas le taux de réussite ni la rentabilité de l'algorithme.
- Les constatations chiffrées de l'audit transmis par l'utilisateur (93/104, etc.) n'ont pas été reproduites : la base de données complète qui a servi à ces mesures n'est pas incluse.
