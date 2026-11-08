> **Nouveau : v6.7 — pression acheteuse avant mouvement.** Voir [LISEZ_MOI_V6_7.md](LISEZ_MOI_V6_7.md). Un token avec des achats soutenus et un prix relativement stable peut devenir « À étudier » après deux relevés concordants, sans attendre une hausse. Signal de recherche non prédictif.

> **Nouveau : v6.6 — fiabilité des cotations.** Voir [LISEZ_MOI_V6_6.md](LISEZ_MOI_V6_6.md). Les tokens non revérifiés depuis plus de 5 minutes sont archivés, leur ancien score ne constitue pas un signal actuel. Un bouton peut redémarrer les services quand MemeRadar est lancé par un script Windows.

# Correctif v6.3 — détection des coins + intégration J7

**Commencer par [LISEZ_MOI_V6_3.md](LISEZ_MOI_V6_3.md)** pour les changements, le diagnostic des listes vides et la migration de `radar.db`.

# Correctif v6.2 — veille sociale J7 rétablie

Voir [LISEZ_MOI_V6_2.md](LISEZ_MOI_V6_2.md) pour la nouvelle section sociale, les diagnostics et la migration depuis v6.1.

# MemeRadar v6.1

Commencez par **LISEZ_MOI_V6_1.md** : installation, corrections, limites et tests. Les indications de ce guide priment sur les notes v5 ci-dessous.

# MemeRadar — scanner de memecoins Solana (sans trading)

**MemeRadar recherche des tokens, analyse leurs premières métriques, identifie des configurations de marché explicables et affiche tout sur une interface locale.** Il ne contient **aucune fonction d'achat, de vente, de signature de transaction, de connexion à un wallet, ni d'importation de clé privée**.

Il est construit à partir des **principes** présents dans tes trois projets :

| Projet original | Ce qui a été repris | Ce qui n'a pas été repris |
|---|---|---|
| `real_bot` (Robinhood Chain / EVM) | Idées de détection très précoce, accélération et reprise après correction | Wallets EVM, seuils de market cap en ETH, code de trading, clés privées et performances revendiquées |
| `MemeBot-Scanner-Audit-2026` | Sources DexScreener/GeckoTerminal, logique de sécurité et contrôles RugCheck sur les pools | Blocages systématiques qui excluent tous les tokens récents, anciennes bases de données |
| `memebot(4)` | Observations de plusieurs wallets, journal SQLite, distinction score / preuves | Score pouvant afficher 100/100 sans preuves, vrai trading Jupiter, présentation d'un solde augmenté comme achat certifié |

**Important : le code du premier bot visait une autre blockchain. MemeRadar cible uniquement Solana. Il adapte des hypothèses, il ne combine pas les transactions des trois blockchains.**


## NOUVEAU — v5 : veille sur X en direct avec J7Tracker

**Objectif :** capter les publications des comptes suivis par J7 dès leur réception, afficher les mentions de memecoins et faire analyser en priorité les adresses de contrats Solana explicites. C'est une **veille sociale**, pas une stratégie garantissant des gains.

**Ce qui fonctionne sans J7 :** DexScreener, GeckoTerminal, RugCheck, suivi de wallets publics, scans automatiques 20 s, filtre score > 40 et exclusion `RISQUE`. La zone « Veille X / J7Tracker » indique alors « J7 désactivé », plutôt que de simuler des tweets en direct.

**Connexion au flux officiel J7 :** J7 documente un Socket.IO v4 sur `https://nyc.j7tracker.io`. Il faut une session J7 autorisée sous forme de **jeton d'accès JWT**. Le projet **ne contourne pas l'authentification, ne scrape pas les pages de J7, et n'utilise ni cookies récupérés clandestinement ni clés privées**. L'accès réel dépend de ton compte et des conditions de J7. Les comptes personnalisés peuvent avoir des quotas spécifiques ; les comptes du flux commun restent disponibles selon les droits de ta session.

### Activer sur Windows (PowerShell)

1. Ouvre un terminal PowerShell dans le dossier `MemeRadar` et installe la dépendance optionnelle :

   ```powershell
   py -3 -m pip install "python-socketio[client]"
   ```

2. Récupère **ton propre jeton d'accès à J7**, via ton compte et les moyens officiellement mis à disposition par J7. **Ce n'est pas** la clé chiffrée du wallet proposée dans le menu Deploy / API keys (elle sert au trading et n'a rien à faire ici). Si tu ne disposes pas d'un jeton de flux accessible, il faut contacter J7 ; sans ce jeton, la veille en direct n'est pas activable.

3. Tu peux lancer **`START_J7.ps1`** depuis PowerShell (si ta politique locale autorise les scripts), qui demande le jeton avec une saisie masquée et ne l’enregistre pas. Sinon, démarre manuellement en saisissant le jeton pour la **session en cours uniquement** :

   ```powershell
   $env:J7_FEED_TOKEN = Read-Host "Jeton d'accès J7"
   py -3 main.py --interval 20
   ```

   Attention : `Read-Host` affiche ce que tu tapes ; sur un PC partagé, utilise `Read-Host -AsSecureString` et un mécanisme de secrets adapté. Ne colle jamais ce jeton dans `wallets.txt`, le README, les captures, Git ou un formulaire externe. Ne conserve pas de secrets dans les fichiers du projet.

4. Vérifie dans l'interface l'état **« LIVE · X/J7 »**. S'il affiche une erreur de session, le jeton est incorrect/expiré ou ton compte n'a pas accès au feed. Referme et rouvre le processus avec un nouveau jeton autorisé.

### Ce que le module analyse

- Les événements `tweet`, `tweet_update`, `initialTweets` et `tweet_deleted` du flux **en lecture seule**. Il fusionne les mises à jour d'un même tweet pour éviter les doublons et ne déclenche pas de nouvelle alerte à partir du backlog lors de la connexion.
- L'auteur, le nombre d'abonnés communiqué par J7, la date et le lien vers le vrai tweet. **« Gros compte » signifie 50 000 abonnés ou plus** par défaut. Cela ne prouve ni l'authenticité, ni l'indépendance, ni une recommandation d'achat.
- Les adresses de contrats Solana présentes explicitement dans le tweet ou signalées par J7. Elles sont vérifiées comme **adresses base58 de 32 octets**. Un ticker comme `$CHAD` seul reste *non attribué* : plusieurs coins peuvent utiliser le même ticker.
- Les mentions croisées : **au moins deux auteurs différents de plus de 50 000 abonnés, mentionnant la même adresse explicite pendant les 10 dernières minutes**. Ce n'est pas une validation de ces auteurs ni une mesure de probabilité de pump.
- Les nouveaux contrats sociaux sont proposés au scanner DEX comme candidats prioritaires, sans points bonus dans le score de qualité. Si aucune paire n'est indexée, le tweet reste visible, mais **aucun prix ni note n'est inventé**.

**Latence :** les posts sont reçus dès que J7 les transmet, puis l'interface locale rafraîchit le panneau X toutes les **2 secondes**. Il peut s'écouler davantage de temps entre le tweet publié et son arrivée chez J7. Les données DEX et RugCheck, elles, suivent leurs propres délais d'indexation, analyses et limitations d'API. Ce n'est donc pas une garantie de réception immédiate à la seconde de publication.

**Important :** les tweets peuvent être sponsorisés, les gros comptes compromis, les tickers usurpés et les pumps manipulés. Les chiffres d'abonnés ne mesurent pas la fiabilité. Le filtre `RISQUE` continue d'être prioritaire ; **un tweet ne rend jamais un token sûr**.

Documentation officielle consultée :
- [J7 — Flux live Socket.IO](https://docs.j7tracker.io/docs/feed)
- [J7 — Événements et mise à jour des tweets](https://docs.j7tracker.io/docs/feed-events)
- [J7 — Limites et sessions](https://docs.j7tracker.io/docs/errors)

**Tests :** le parseur, l'association par adresse, la déduplication, l'absence de déclenchement du backlog et la conservation des risques sont vérifiés hors ligne ; **connexion J7 authentifiée non testée faute de session fournie**. Aucune performance prédictive démontrée.

---

## Correction GeckoTerminal HTTP 429 — version v4

- La surveillance DexScreener et le rafraîchissement local (5 s) restent actifs ; scans espacés de **20 secondes après la fin** d'un cycle.
- Les endpoints GeckoTerminal `new_pools` et `trending_pools` sont mis en cache respectivement **75 s** et **180 s** : le radar ne redemande pas les mêmes listes toutes les 20 s. Ces listes peuvent donc avoir ce retard supplémentaire.
- Les appels Gecko sont espacés d'au moins **9 secondes** entre départs d'appels, avec un ordre de grandeur maximal de **6 à 7 requêtes/minute** pour *ce processus* seulement. Une limite partagée par adresse IP peut encore déclencher un refus.
- Sur un **HTTP 429**, Gecko est mis en pause pendant **120 s au minimum**, puis plus longtemps si les refus se répètent, ou selon l'en-tête `Retry-After`. Les autres sources continuent de fonctionner.
- **Les prix Gecko ne sont pas mis en cache** : si la confirmation indépendante est indisponible, elle apparaît *inconnue* dans le score, plutôt qu'être présentée faussement comme un prix confirmé. Les notes peuvent temporairement baisser en période de blocage.
- Si les refus se poursuivent, essaie `py -3 main.py --interval 45 --limit 8`. Évite de faire tourner plusieurs copies du scanner sur la même connexion.

## Filtrage des memecoins (v3)

L'interface n'affiche **par défaut que les coins dont le score est strictement supérieur à 40/100**, **à l'exclusion des coins classés `RISQUE`**. Ces deux filtres sont ajustables en haut du flux. Le seuil est une **note heuristique**, pas une chance de réussite de 40 %.

- **Note minimale :** curseur de 0 (« tous ») à 90. À 40, un score de 40,0 est masqué, 40,1 est visible.
- **Masquer les tokens à risque :** activé par défaut ; concerne le statut d'alerte produit par MemeRadar, quel que soit le score. Un token non classé `RISQUE` n'est pas nécessairement sûr.
- **Exiger un signal détecté :** optionnel, limite les résultats aux tokens pour lesquels l'algorithme a enregistré un signal particulier (départ précoce, impulsion, rebond…).
- **Preuves disponibles :** optionnel, exige une couverture minimale de 50 %, 70 % ou 90 %. Ce n'est pas une probabilité de gain.
- **Tout afficher :** désactive les filtres de qualité et restaure le flux complet. Les préférences restent conservées dans le navigateur, sur ce PC.

Les filtres sont **uniquement visuels** : MemeRadar continue de scanner et conserver les tokens masqués. Les quatre compteurs du haut reflètent toujours le répertoire global ; l'indicateur « X tokens affichés sur Y » reflète les filtres actifs. Le fichier CSV conserve tous les tokens de la liste transmise par le serveur, y compris ceux masqués dans l'interface. Pour revoir un coin à risque, décoche « Masquer les tokens à risque ».


## 1. Installation sur Windows 11 — la méthode facile

1. Décompresse `MemeRadar.zip` dans un dossier, par exemple `C:\MemeRadar`.
2. Installe Python **3.11 ou plus récent** si nécessaire. Vérifie dans CMD avec :

   ```bat
   py -3 --version
   ```

3. Double-clique sur **`START_MEMERADAR.bat`**. Une console apparaît et ton navigateur devrait ouvrir :

   **http://127.0.0.1:8765**

4. Laisse la **fenêtre CMD ouverte** : le programme continue ses scans pendant qu'elle reste ouverte. Pour arrêter : **Ctrl+C** dans cette fenêtre, ou ferme-la.

**Le scanner de marché ne nécessite toujours aucun `pip install`.** Pour activer le flux J7 (optionnel), il faut installer `python-socketio[client]` et disposer de son propre jeton de session J7 valide. Sans cela, le radar DEX continue normalement.

Pour essayer l'interface avant de demander les vraies données, double-clique `START_DEMO.bat`. Le mode démo affiche **six tokens entièrement fictifs** et ne contacte aucun service de marché.

### Démarrage manuel depuis CMD

```bat
cd /d C:\MemeRadar
py -3 main.py
```

Autres commandes :

```bat
py -3 main.py --demo
py -3 main.py --interval 20 --limit 14
py -3 main.py --once
py -3 main.py --port 8787 --no-browser
py -3 main.py --rpc https://TON_RPC_SOLANA_PUBLIQUE
```

- `--interval 20` : **20 secondes après la fin de chaque cycle** (minimum 20 secondes). Valeur par défaut : **20 s**. Ce n’est pas un flux instantané : un cycle peut durer plus longtemps et les sources doivent d’abord référencer les tokens. Une limite de cadence par API s’applique également pour protéger les quotas publics.
- `--limit 20` : jusqu'à **20 tokens inspectés en profondeur par cycle**, parmi les nouveaux détectés et ceux déjà suivis. Intervalle permis : 1 à 25 ; défaut 14.
- `--once` : effectue **un seul cycle** de collecte, imprime un bilan et se termine, sans interface.
- `--demo` : affiche seulement des **exemples inventés**.
- `--port` : change le port du site local ; `--no-browser` évite l'ouverture automatique du navigateur.
- `--rpc` : URL d'un RPC Solana que tu contrôles, **facultatif** pour suivre des adresses publiques. Sans wallet configuré, le RPC n'est pas sollicité.

### Mode rapide : intervalle, limites et rafraîchissement

- **Scan automatique :** démarrage immédiat puis attente de **20 secondes après la fin** de chaque cycle. La fréquence effective dépend aussi de la durée des requêtes (par exemple, 15 s de collecte + 20 s d'attente = un départ toutes les 35 s).
- **Interface :** actualisation des résultats locaux toutes les **5 secondes**, sans déclencher de nouvelle collecte de marché à chaque affichage.
- **Quotas publics vérifiés en octobre 2026 :** DexScreener profils/boosts : **60 appels/min**, DexScreener données de paires/tokens : **300 appels/min**, GeckoTerminal public : **30 appels/min** annoncé (mais plafond effectif parfois inférieur / partagé). Le code applique un cache de découverte, un espacement de 9 s entre appels Gecko et une pause automatique après **HTTP 429** ; les quotas des fournisseurs peuvent évoluer.
- **Ordre de grandeur par cycle avec 14 tokens :** 2 appels découverte DexScreener + 2 appels découverte GeckoTerminal + 1 appel groupé DexScreener + jusqu'à 2 appels groupés GeckoTerminal, plus RugCheck (cache 15 min) et éventuellement du RPC public pour suivre les wallets. Les reprises sur erreur et les serveurs lents allongent le cycle.
- **En cas de ralentissement ou de refus 429 :** relance avec `py -3 main.py --interval 45 --limit 8`.

### Nouveau : panneau de mise à jour en direct

En haut du tableau de bord, le **panneau « Surveillance automatique »** permet de savoir ce que fait réellement le programme :

- **« Analyse en cours… »** : indicateur rotatif et étape courante (découverte, wallets, cotations, vérification des tokens). Quand des tokens sont traités, leur nombre apparaît (`3/14`, par exemple). La barre indique la progression des étapes, **pas une précision chronométrique ni une garantie sur le délai restant**.
- **« Scanner en veille active »** : le cycle est fini ; la barre et le compteur indiquent combien de secondes restent avant le prochain. Le délai de **20 secondes commence après la fin de la collecte**, pas au début.
- **« Dernier scan »** : heure et temps écoulé ; **« Interface actualisée »** : date de la dernière réponse locale. L'interface lit le statut du programme toutes les 5 secondes, avec un décompte actualisé toutes les secondes.
- **« Scanner maintenant »** : déclenche un nouveau cycle dès que le programme est disponible. Si un scan est déjà en cours ou demandé, il n'en lance **pas un deuxième en parallèle**.
- **En cas d'erreur** : avertissement visible et prochaine tentative automatique selon l'intervalle habituel. Le bouton ne contourne pas les quotas des fournisseurs.

Le panneau affiche un avis à la fin d'un cycle, même si celui-ci a été trop rapide pour que l'interface voie l'animation. Le **mode démo** n'exécute aucun scan ni actualisation de marché et désactive le bouton de scan.

### Mise à jour depuis une ancienne version (sans perdre tes données)

1. Arrête l'ancien MemeRadar avec **Ctrl+C**.
2. Conserve une copie de **`radar.db`** (historique SQLite, s'il existe) et **`wallets.txt`** (adresses publiques que tu as ajoutées).
3. Décompresse la nouvelle version dans un **nouveau dossier**, puis replace ces deux fichiers dans celui-ci avant le lancement. Ne remplace pas ta base ou tes wallets avec ceux de l'archive.
4. Relance `START_MEMERADAR.bat` et actualise ton navigateur avec **Ctrl+F5** pour charger le nouveau JavaScript et CSS.

Cette mise à jour concerne le **suivi visuel et le déclenchement des scans**. Elle ne change pas les filtres de sélection ou le mode observation (aucun achat automatique).

## 2. Ce que l'interface montre

Dans **Flux des candidats**, chaque ligne indique : nom, symbole, prix, liquidité, volume, variation récente, âge de la **paire DEX**, évolution mesurée depuis le premier prix relevé et score de recherche.

Cliquer sur un token ouvre :

- ses **signaux observés** et la méthode exacte qui les a déclenchés ;
- les points positifs, les **risques** et les **données qui manquent** ;
- le détail des composantes du score ;
- ses prix réellement relevés (ce n'est pas un graphique historique reconstitué) ;
- les sources et événements de wallets publics, lorsqu'ils sont configurés ;
- un lien vers DexScreener pour **faire tes propres vérifications**, sans jamais exécuter d'achat.

Fonctions pratiques : recherche par adresse ou ticker, filtre **Avec signaux**, tri par score ou récence, favoris dans le navigateur, export CSV.

Les favoris sont stockés **uniquement dans le navigateur** sur ce PC. La collecte et les prix sont conservés dans `radar.db` (SQLite).

## 3. Comment le bot trouve les tokens

**Découverte :** `new_pools` et `trending_pools` de GeckoTerminal ; derniers profils et boosts DexScreener, clairement identifiés comme données de promotion et **jamais considérés comme preuves de qualité**. Les gros tokens évidents (SOL/USDC/USDT) sont exclus de la découverte.

**Validation :** DexScreener fournit les prix, transactions, volumes, âge et liquidité des paires SOL/USDC/USDT ; GeckoTerminal est interrogé sur **l'adresse de la même paire**, pour comparer les prix sans confondre deux marchés du même token. RugCheck fournit, si possible, les autorités mint/freeze, la concentration et ses indicateurs de risque.

**Signaux :**

1. **Départ précoce** : paire d'au plus 20 minutes, liquidité d'au moins 5 000 $, au moins 20 transactions sur une heure, achats ≥ 60 % des transactions et hausse comprise entre +2 et +25 % sur 5 minutes.
2. **Impulsion acheteuse** : paire d'au plus 3 heures, liquidité ≥ 10 000 $, volume 1h ≥ 15 000 $, au moins 50 transactions, achats ≥ 65 % et hausse de +3 à +25 % sur 5 minutes.
3. **Reprise après correction** : après **au moins 10 minutes de relevés locaux**, le prix a reculé de 15 % après un sommet observé, puis a rebondi d'au moins 5 % sans retrouver ce sommet. **Ce n'est pas un plus-haut historique du token**.
4. **Mouvement de wallets publics** : si tu configures des adresses, le programme repère certains changements de **solde de token** enregistrés par RPC. Une augmentation n'est **pas forcément un achat**. Deux adresses ne prouvent ni deux investisseurs indépendants ni une « smart money » réellement profitable.

Les seuils sont **heuristiques et exploratoires**, inspirés des règles de tes projets. Ce ne sont pas des seuils optimisés sur un grand historique indépendant.

## 4. Le score est-il une probabilité de pump ? Non.

Le **score 0–100** est une grille de recherche, pas une probabilité de gain ni une prévision du cours :

| Bloc | Points max | Mesures |
|---|---:|---|
| Marché / momentum | 55 | Liquidité (14), volume/liquidité (10), transactions (7), proportion d'achats (10), variation 5 min (9), jeunesse de la paire (5) |
| Sécurité | 25 | Autorités mint/freeze (10), concentration (10), score de risque RugCheck (5) |
| Découverte | 10 | Nouvelles paires / tendances et observation légère de wallets publics ; **zéro point pour le boost seul** |
| Vérification indépendante | 10 | Même paire/prix confirmé par Gecko (8), acheteurs distincts disponibles (2) |

Si une donnée manque, **elle donne zéro point** au score et réduit la couverture des preuves. Une donnée de sécurité inconnue n'est **pas** considérée comme rassurante.

Les statuts sont :

- **À étudier** : aucun risque bloquant identifié, couverture ≥ 70 %, score ≥ 65/100 et liquidité ≥ 10 000 $. **Cela ne signifie pas « acheter ».**
- **Surveillance** : des contrôles sont présents mais le score ou le marché ne satisfait pas les critères précédents.
- **Incomplet** : couverture de preuves inférieure à 70 %.
- **Risque** : au moins un signe d'alerte identifié ; ce statut prime toujours sur le score.

Exemples de blocages de risque : liquidité inférieure à 5 000 $, autorité de mint ou de gel active, concentration très élevée, drapeau RugCheck ou chute/pump extrême sur cinq minutes. Les données absentes restent clairement signalées.

## 5. Faut-il ajouter des wallets ?

**Ce n'est pas nécessaire pour commencer.** MemeRadar utilise les flux publics de découverte, même avec `wallets.txt` vide. Si tu disposes de **véritables adresses PUBLIQUES Solana** que tu souhaites suivre :

1. Ouvre `wallets.txt` dans Bloc-notes ou VS Code.
2. Ajoute **une adresse Solana publique par ligne**, sans guillemets ; au maximum cinq seront suivies.
3. Redémarre MemeRadar. Les nouvelles augmentations de solde détectées peuvent apparaître dans la fiche d'un token.

**N'ajoute jamais ta seed phrase, tes clés privées ou une clé de connexion dans ce fichier.** Les wallets `0x…` du `real_bot` Robinhood Chain ne sont pas des wallets Solana et ne sont pas suivis ici. Le RPC Solana public peut limiter les requêtes. Aucune identité de « smart wallet » n'est prévalidée et le moteur ne prouve pas qu'une transaction est un swap : ce sont des observations.

## 6. Combien de temps laisser tourner le bot ?

- **5–15 minutes :** vérifie surtout que l'interface démarre et que les API répondent. Il peut n'y avoir **aucune alerte**, ce qui est normal.
- **1–3 heures :** plusieurs scans permettent de commencer à voir la variation des tokens, notamment les signaux de « reprise après correction » s'ils se produisent.
- **1–2 semaines :** période raisonnable pour **collecter des observations préliminaires** de qualité et repérer les limites des sources. Ce n'est **pas suffisant, à lui seul, pour prouver la rentabilité**.
- **Plusieurs semaines avec beaucoup de signaux :** nécessaire pour comparer les alertes, leurs variations après détection et les tokens non retenus dans un futur backtest prospectif. Les sources sont publiques, leurs quotas peuvent changer et la disponibilité est variable.

Tu peux laisser le PC tourner tant que tu veux, mais le bot **ne travaille pas une fois le script arrêté**. Les prix restent enregistrés localement. Par défaut, les snapshots détaillés sont conservés pendant **trois jours** et un relevé au maximum par token et par seconde ; le prix initial de référence est conservé. Arrêter le programme crée des trous dans l'observation ; **aucun cours intermédiaire n'est inventé**.

## 7. Structure du dossier

```text
MemeRadar/
├── START_MEMERADAR.bat      Démarrage direct Windows
├── START_DEMO.bat           Mode présentation (données fictives)
├── main.py                  Serveur web local + API + export CSV
├── radar/
│   ├── engine.py            Orchestration, priorité des nouveaux tokens
│   ├── providers.py         Connecteurs API et suivi de wallets publics
│   ├── source_scanner.py    Fonctions d'analyse issues du scanner original
│   ├── scoring.py           Score 0-100 et contrôles de risques
│   ├── patterns.py          Setups « précoce / momentum / correction / wallets »
│   └── store.py             Stockage SQLite
├── web/
│   ├── index.html           Interface graphique
│   ├── style.css
│   └── app.js
├── tests/
│   └── test_memeradar.py    Tests hors ligne / API simulées
├── wallets.txt              Adresses publiques facultatives
└── README.md                Ce guide
```

Pour lancer les tests sans connexion aux API :

```bat
cd /d C:\MemeRadar
py -3 -m unittest discover -s tests -v
```

## 8. Dépannage

**Page blanche / navigateur non ouvert :** copie manuellement `http://127.0.0.1:8765` dans ton navigateur. Vérifie que la fenêtre du bot est ouverte et que le port 8765 est libre. Si occupé, utilise `py -3 main.py --port 8787`.

**Aucun token :** les découvertes récentes peuvent être peu nombreuses, les sources peuvent être temporairement indisponibles, ou le scanner n'a pas encore fini un cycle. Regarde « Sources / diagnostics » sous le tableau. Un classement vide n'est **pas** une erreur en soi. Essaye `--once` pour afficher un diagnostic en console.

**Erreur 429 / RPC :** les limites des API publiques ne sont pas garanties. Augmente `--interval` à 45–120, réduis `--limit`, ou désactive le suivi des wallets publics en commentant les lignes de `wallets.txt`.

**Fenêtre qui se ferme :** lance `py -3 main.py` depuis une fenêtre CMD déjà ouverte pour lire le message d'erreur. Python 3.11+ est nécessaire.

**Programme devenu lent :** les API sont interrogées séquentiellement et peuvent avoir une latence élevée. Réduis `--limit` et surveille les messages de diagnostic. L'interface se rafraîchit toutes les **5 secondes** depuis le serveur local (sans interroger les API publiques à chaque rafraîchissement). Le prochain scan démarre **20 secondes après la fin du cycle précédent**, et non toutes les 5 secondes.

## 9. Limites importantes et sécurité

- **Ce prototype n'a pas été validé en temps réel contre les API dans cet environnement.** Les endpoints ont été confrontés à leurs documentations, mais le fonctionnement effectif dépend du réseau et des quotas. Les tests automatisés utilisent des réponses fictives.
- L'outil découvre des **paires indexées par les services**, pas nécessairement un token dans les toutes premières secondes de sa création sur une bonding curve. Il peut manquer complètement certains x10 très précoces.
- Les taux de transactions et achats peuvent être simulés par des robots ; les portefeuilles peuvent être liés. **Aucun score ne garantit l'absence de rug pull ou de manipulation de prix**.
- Il n'y a **aucun backtest prospectif** ou comparaison prouvant que les tokens les mieux classés surperforment d'autres tokens. Il n'y a pas de promesse de revenu.
- Le score est fondé sur le **marché observé** et des signaux publics : ni une analyse exhaustive du contrat, ni une garantie de possibilité de revente, ni la mesure d'un retour net de frais.
- L'interface est accessible **uniquement en local** sur `127.0.0.1`, sans tunnel ou exposition réseau. N'expose pas le serveur à Internet.
- **Ne copie aucun fichier de configuration ou fichier utilisateur du RAR `real_bot`** : il contient des données sensibles. MemeRadar n'en a pas besoin.

**Sources et documentations officielles :**

- https://docs.dexscreener.com/api/reference
- https://api.geckoterminal.com/docs/index.html
- https://api.rugcheck.xyz/swagger/index.html (disponibilité dépendante du fournisseur)
- https://solana.com/docs/rpc/http/getsignaturesforaddress
- https://solana.com/docs/rpc/http/gettransaction

**Utilise l'outil comme aide à l'analyse, et fais toujours tes propres vérifications avant tout investissement manuel.**


## Correctifs v6.4

Voir `LISEZ_MOI_V6_4.md` pour la migration, la vérification facultative des badges X, le diagnostic de découverte et les limites de l’analyse des abonnés.


## Mise à jour v6.5

Les changements du scanner et de la sélection J7 sont décrits dans `LISEZ_MOI_V6_5.md`.
