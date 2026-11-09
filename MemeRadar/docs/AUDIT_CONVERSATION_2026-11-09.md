# Audit de « Revoir la logique du bot » — 9 novembre 2026

## Conclusion

La première livraison locale V2 n'était pas une réalisation complète de toutes les recommandations de la conversation. Plusieurs fonctions existaient, mais regroupées dans `strategies.py` et `world_watch.py`, avec des branchements incomplets. La présence de fichiers modifiés et 250 tests réussis ne suffisaient pas à démontrer la conformité de toute la refonte.

Cette passe a vérifié les huit modules nommés dans l'architecture et leurs interactions avec les fichiers existants. Les corrections décrites ci-dessous sont enregistrées dans `D:\dev\Project\mmcoins\MemeRadar`. Aucun envoi GitHub effectué par cette passe.

## Sources de l'audit et limite d'accès

Conversation identifiée : « Revoir la logique du bot », identifiant `6af0cff0-5588-83ed-b06b-feead6c89abc`. Lecture directe des messages disponibles, puis pagination des derniers échanges. Le code complet visible du collecteur proposé a été comparé au collecteur local, et les conseils précédemment lus dans ce chat ont été pris en compte.

L'outil de lecture tronque les messages longs à 20 000 caractères et ne restitue actuellement que les cinq derniers échanges de cette conversation. Les lectures du 8 novembre contenaient également deux échanges plus anciens, mais leurs grands messages étaient eux aussi tronqués. Une ouverture de la conversation web a été tentée : le navigateur n'est pas connecté et n'affiche pas le contenu. Il n'est donc pas possible d'affirmer une comparaison mot à mot de la fin des deux grands extraits, ni de garantir qu'aucun autre fichier n'existe dans une partie non accessible. Aucun fichier joint n'est retourné par l'outil pour les échanges disponibles.

Il faut distinguer les noms de modules annoncés dans un tableau d'architecture du code effectivement transmis : l'extrait accessible fournit surtout `world_intel.py`, les indications de raccordement de `main.py`/`engine.py` et des tests du collecteur. Les trois fichiers de stratégie et le filtre de sécurité sont des composants annoncés ; aucun corps complet de ces fichiers n'a été récupéré dans cette lecture. Ils ont été implémentés localement à partir des critères déjà retenus, sans prétendre recopier un contenu inaccessible.

## Les huit modules de l'architecture

| Fichier prévu | Avant cet audit | Vérification et résultat local |
|---|---|---|
| `radar/world_intel.py` | Absent sous ce nom ; service partiel dans `world_watch.py` | Créé et utilisé par `main.py`. Service `WorldIntel`, API `/api/world`, `context_for_token`, dates RSS/ISO et Atom, lecture J7 toutes les 30 s, RSS toutes les 300 s avec quatre téléchargements au maximum en parallèle. |
| `radar/narrative_graph.py` | Présent, graphe lexical | Vérifié et corrigé : les rubriques d'un même média comptent comme une seule voix. Noms nouveaux et cooccurrences conservés. Ce n'est pas un moteur sémantique à embeddings. |
| `radar/event_calendar.py` | Présent, dates ISO uniquement | Vérifié : dates explicites avec contexte de lancement/sortie, fenêtre d'un an, statut non confirmé. Les alias `date_hint`/`future_date` sont exposés par `world_intel.py`. Agenda officiel et autres formats de dates non implémentés. |
| `radar/security_gate.py` | Logique dans `strategies.py` | Extrait dans un module réel et raccordé au moteur. Ajout du rejet des pourcentages incohérents comme données inconnues ; alerte fournisseur sévère sans détail non résolu bloquante. Un contrôle non vérifié empêche toute éligibilité et retire le statut à étudier ; les statuts de découverte surveillance/incomplet restent conservés. |
| `radar/strategy_fast.py` | Branche d'une boucle commune | Module autonome exécuté par le moteur : âge, liquidité, fraîcheur, momentum 5 min et nombre d'achats/ventes. L'indépendance des acheteurs et une vente réalisable ne sont pas établies. |
| `radar/strategy_trend.py` | Branche d'une boucle commune | Module autonome exécuté par le moteur : contrôles horaires et événement de moins de six heures. La détection des transferts de capitaux entre narratifs reste absente. |
| `radar/strategy_growth.py` | Branche d'une boucle commune | Module autonome exécuté par le moteur : persistance narrative, diversité des sources, historique de liquidité/prix/top10. Tri et déduplication des relevés horaires ajoutés. La qualité humaine de la communauté et les volumes organiques ne sont pas certifiés. |
| `radar/decision_engine.py` | Pas de moteur central ; stratégie calculée dans l'API, ancien critère d'éligibilité dans le scanner | Créé et réellement utilisé par `engine.py`, `world_watch.py` et les imports de compatibilité. Même décision dans l'analyse, le tableau et l'API V2. Le score historique ne peut ni contourner un refus ni, seul, empêcher une observation répondant à FAST/TREND/GROWTH. |

## Comparaison du code de collecteur fourni

| Élément du code proposé | Résultat de vérification |
|---|---|
| `NEWS_FEEDS` généralistes | Sept flux locaux conservés : monde, technologie, économie, sciences, culture et actualité française. Guardian et France 24 remplacent ici les deux agrégateurs Google News proposés. Couverture mondiale bornée, pas « tout le web ». |
| `parse_date` RSS et ISO | Ajouté. Une date sans fuseau est rejetée plutôt que supposée UTC. |
| `parse_feed` RSS et Atom | RSS déjà présent ; Atom et lien `alternate` ajoutés. Limite de taille et refus des déclarations XML à entités conservés. |
| Date de publication manquante | Différence volontaire : article exclu des signaux récents. Le prototype le stockait avec l'heure de réception et un indicateur de date inconnue ; cette heure ne doit jamais être utilisée comme preuve de nouveauté. |
| Téléchargements parallèles | Ajoutés, limités à quatre. Une source en panne ne stoppe pas les autres. |
| J7 plus fréquent que le RSS | Corrigé : passage du collecteur toutes les 30 s, RSS toutes les cinq minutes ; le flux J7 direct reste événementiel. Budget de recherche DexScreener conservé à trois recherches par cinq minutes. |
| Mentions de contrat dans `post.mints` | Corrigé : les contrats valides fournis par les métadonnées J7 sont conservés même si le texte affiché ne contient pas l'adresse. |
| `context_for_token` | Ajouté, utilisé avec les mêmes règles de relation que le moteur : contrat exact ou hypothèse thématique, sans affiliation supposée. |
| `world_events`, `world_topics`, `world_token_links` | Les prototypes proposaient des schémas SQL différents de celui installé. Ils n'ont pas été copiés sur la base existante. RSS dans `world_events`, J7 dans `social_posts`, sujets et liens recalculés ; preuves sélectionnées enregistrées avec les décisions. Les trois tables exactes du prototype ne sont pas reproduites. |
| Conservation de 30 jours | Différence documentée : titres RSS conservés sept jours et relevés de stratégie 30 jours. Un agenda d'annonces persistantes jusqu'à la date de l'événement reste à développer. |
| `WorldIntel.report()` et `/api/world` | Ajoutés avec état du service, articles, sujets, dates à confirmer et liens aux tokens. L'API `/api/v2` existante est maintenue. |
| `run()` résistant aux erreurs | Conservé ; état d'erreur explicite et attente interruptible. |
| Tests proposés pour l'actualité hors GTA | Sujet inédit et entités en casse mixte testés. Le test d'article sans date du prototype n'est pas reproduit tel quel : la règle locale choisie est son exclusion des signaux. |
| Tests proposés pour dates futures | La logique locale valide une date explicite et son contexte ; elle n'invente pas de calendrier vérifié. |

## Autres fichiers et conseils vérifiés

| Fichier ou ensemble | Constat et action |
|---|---|
| `main.py` | Démarrage effectif de `WorldIntel`, route `/api/world`, maintien de `/api/v2`, mode démo sans service externe. |
| `radar/engine.py` | Ancien booléen d'éligibilité remplacé par `apply_decision`. Les événements et historiques sont fournis aux trois stratégies. Le rendu réévalue aussi les données périmées. |
| `radar/scoring.py` | Conservé comme diagnostic historique et source de signaux de marché. Le bonus de jeunesse n'entre pas dans les trois nouveaux critères. Certaines alertes y restent descriptives, mais le filtre central interdit qu'elles suffisent à qualifier le token. Ce fichier n'a pas été entièrement remplacé. |
| `radar/selection.py` | Relu : partage borné entre urgences, nouveaux tokens et anciens candidats. Les budgets et la priorité historique restent en place ; aucune refonte complète de l'ordonnanceur ou garantie de suivi de tous les tokens sur plusieurs jours n'est revendiquée. |
| `radar/fast_lane.py` | Relu : observation immédiate sans requête réseau, puis cotations différées ; les risques connus ne sont pas écrasés. Une qualification de sécurité complète des bonding curves n'est pas implémentée. |
| `radar/curve.py` | Rôle vérifié dans l'analyse : hypothèse de courbe et observation précoce. Ne certifie pas une LP ou la possibilité de vente. |
| `radar/onchain_risk.py` | Relu : supply, plus gros comptes et part du wallet de lancement. Les données remontent au filtre commun. Pas de détection exhaustive de wallets liés, snipers ou bundles. |
| `radar/source_scanner.py` | Contrôles de limites réseau et provenance RugCheck vérifiés. Le détail des risques et, maintenant, les niveaux sévères sans détails sont transmis au filtre central. |
| `radar/social.py` | Raccordement J7 vérifié : Socket.IO, authentification existante, `user_connected`, backlog et mises à jour. Aucun accès à un jeton privé pour valider la connexion réelle. |
| `radar/narratives.py` | Tendances d'origine maintenues en complément ; elles ne sont plus l'unique veille mondiale. |
| `radar/narrative_intelligence.py` | Extraction lexicale conservée en support. La compréhension sémantique générale reste une limite. |
| `radar/store.py` | Persistance conservée. Recherche des tokens déjà connus raccordée à la même extraction d'entités nouvelles que la veille. Aucun remplacement de base. |
| `radar/research_v3.py` | Ajout à chaque nouvelle observation pertinente des stratégies, du filtre, de la version de décision, de l'heure de contrôle et des preuves événementielles. Les résultats existants restent des variations observées, pas des gains nets. |
| `radar/providers.py` / suivi wallets | Limite de cinq wallets confirmée. Pas de promesse de surveillance en temps réel des 353 adresses. |
| `web/index.html` / `web/v2.js` | Les profils utilisent les résultats du moteur central. Filtre de score historique désactivé par défaut pour ne pas masquer un candidat V2 uniquement à cause de son ancien score. |
| Lanceurs | `START_V2.bat` et lanceur J7 existant gardent leur rôle. Redémarrer l'instance pour charger les nouveaux modules. |

## Ce qui reste réellement partiel

Les recommandations sur les embeddings/LLM, la diversité de communautés humaines, les flux de capitaux entre tokens, la sécurité propre à chaque bonding curve, les calendriers officiellement vérifiés, le calcul d'une sortie réalisable avec taxes/frais/slippage, les bundles/insiders et le backtest net des trois stratégies ne sont pas terminées. Le renommage et le découpage de fichiers ne les remplacent pas.

Les seuils actuels restent heuristiques. La mention « à examiner manuellement » n'est pas une recommandation d'achat ou une validation de rentabilité. Aucun achat, aucune signature de transaction et aucun accès aux clés privées pendant cet audit.

## Sauvegarde et validation

Sauvegarde préalable de cette passe : `D:\dev\Project\mmcoins\backups\MemeRadar_before_alignment_20261109_082405`. Code et copie SQLite cohérente, intégrité vérifiée. Base utilisateur non utilisée comme base de test.

Sur une copie contenant 9 347 tokens : préparation du tableau de 300 tokens avec décisions en environ 0,359 s ; construction complémentaire du rapport en environ 0,207 s. Mesure ponctuelle, pas un engagement de latence réseau.

Tests complets et résultats de cette passe : voir `validation-alignement.txt` fourni avec le rapport. Les nouveaux cas vérifient les modules effectivement exécutés, le refus malgré un score élevé, les cotations périmées, les pourcentages incohérents, les rubriques d'un même média, Atom, les métadonnées J7, les cadences séparées, `/api/world`, la cohérence tableau/API et la conservation des preuves dans l'historique.
