# MemeRadar v6.6 — cotations périmées et redémarrage des services

## Problème corrigé en priorité

Dans la v6.5, `last_scan` donnait l'heure du **cycle global**, sans signifier que les centaines de coins enregistrés avaient été revérifiés. Un token vieux de 16 heures pouvait conserver son ancien score « À étudier » et sa liquidité du jour précédent.

Depuis la v6.6 :

- L'interface considère les **dernières données du coin** (champ `last_seen`), pas la date du dernier cycle global.
- **Plus de 5 minutes sans nouvelle cotation DEX : « PÉRIMÉ »**, indépendamment de la valeur du score précédent. Les archives sont masquées par défaut.
- L'historique des cours et les vieux scores restent conservés dans SQLite. Pour les examiner, décoche « Masquer les coins périmés » ou utilise « Tout afficher ». Les anciennes cotations sont explicitement signalées.
- Si un pool est introuvable pendant un cycle, l'ancien cours n'est **jamais** utilisé pour fabriquer un nouveau scan récent.
- Le moteur donne désormais priorité à certains tokens récents dont la dernière analyse vieillit, tout en conservant au moins dix places sur quatorze pour les nouvelles découvertes lorsqu'il y en a suffisamment.
- La fiche affiche la **paire et le DEX utilisés par DexScreener**. Si Axiom présente une autre paire du même token, les chiffres peuvent différer.

**Limite :** le moteur peut examiner au maximum 14 tokens par cycle (par défaut). Beaucoup de tokens enregistrés seront donc archivés après 5 minutes : cela vaut mieux que les présenter comme des opportunités actuelles. L'actualisation toutes les 5 secondes concerne l'écran ; elle n'actualise pas toutes les cotations. Les données des API peuvent aussi avoir leurs propres délais.

## Bouton « Redémarrer les services »

Dans le haut du tableau de bord, le bouton demande confirmation, puis déclenche :

1. Arrêt de la boucle de scanner et du serveur HTTP local.
2. Fermeture de la connexion J7 et de la vérification X optionnelle.
3. Arrêt complet du processus Python (`exit 75`).
4. Redémarrage d'un **nouveau** processus par `START_J7.ps1` ou `START_MEMERADAR.bat`. Le nouveau processus reprend la même base et les mêmes fichiers.

**Important :** lance MemeRadar avec l'un de ces scripts Windows pour que le bouton puisse le redémarrer. Si tu l'exécutes directement avec `python main.py`, le bouton arrête Python, mais il faudra le relancer manuellement. Le jeton J7 reste uniquement dans la session PowerShell du lanceur et n'est pas enregistré sur disque ; il est réutilisé lors d'un redémarrage demandé par le bouton. Fermer la fenêtre arrête les services.

## Installation depuis v6.5

1. Arrête l'ancienne version (fenêtre PowerShell : `Ctrl+C`).
2. Décompresse `MemeRadar_v6_6_Cotations_Actualisation.zip` dans un **nouveau dossier**.
3. Copie ton ancien fichier `radar.db` et `wallets.txt` dans ce dossier (ne copie aucune clé privée).
4. Lance `START_J7.ps1` pour utiliser J7, ou `START_MEMERADAR.bat` sans J7.
5. Dans Chrome : `Ctrl+F5` pour vider le cache des scripts.
6. Surveille les indicateurs « récents / enregistrés » et « archives périmées » dans le diagnostic des candidats.

## Tests et précautions

85 tests automatisés ont été validés, notamment : données historiques marquées périmées, récupération de nouveaux cours, absence de faux rafraîchissements, protection de l'endpoint de redémarrage, et absence de double commande de redémarrage.

L'interface a été vérifiée avec des **données factices** dans Chromium. Les appels API de marché en direct, la synchronisation avec Axiom et une session J7 authentifiée **n'ont pas été validés** dans ce test. Aucune stratégie n'est garantie rentable. Le bot reste en lecture seule, sans ordre ni wallet privé.
