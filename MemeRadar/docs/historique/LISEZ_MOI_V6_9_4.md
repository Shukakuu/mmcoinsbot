# MemeRadar v6.9.4 — Veille précoce et contexte des narratives

**But** : montrer plus tôt les premières traces de demande, sans prétendre qu'un
memecoin est sûr, et rechercher les correspondances avec les thèmes détectés
par J7 et Google Trends. **Lecture seule : zéro transaction, aucune clé privée.**

## Installation sans perdre les données

1. Arrêter l'ancienne instance avec la console ou le bouton de redémarrage.
2. Décompresser le ZIP dans **un nouveau dossier** (ne pas superposer les
   fichiers pendant que le bot tourne).
3. Copier le fichier `radar.db` de l'ancien dossier vers le **nouveau dossier
   `MemeRadar/`**. Facultatif : sauvegarder puis copier `wallets.txt` si modifié.
4. Lancer `START_J7.ps1` comme avant. Le flux J7 ne fonctionne que si votre
   session `J7_FEED_TOKEN` est configurée et couvre les comptes désirés.
5. Vérifier que la barre de diagnostic indique **Moteur v6.9.4** et observer
   l'étiquette **VEILLE PRÉCOCE · NON VÉRIFIÉ** sur les jeunes courbes actives.

## Modifications concrètes

- **Première passe non bloquante** : quand DexScreener expose déjà prix + quelques
  transactions/volume sur 5 min, un token récent peut s'afficher avant les
  appels plus lents à Gecko et RugCheck. Score/couverture restent incomplets ;
  **« Surveillance » ne signifie pas « à acheter »**.
- Les tokens récents qui montrent des débuts d'activité, mais manquent de
  vérifications, ne sont plus **tous** cachés sous `incomplet` ; les nouveaux
  contrôles continuent et toute alerte connue l'emporte.
- Les premiers signaux restent visibles même si l'utilisateur a choisi un
  **score minimal ou une couverture minimale** dans l'interface, **mais pas**
  s'il a choisi de cacher les risques connus ou les cotations périmées.
- Les contrôles `a_etudier` et `eligible` **ne sont pas assouplis**.
- Retour à une nouvelle observation possible après environ 20 s (sous réserve
  du budget disponible et de la durée réelle d'un cycle).
- **Thèmes J7** : un tweet récent reçu **sans adresse** mais issu d'un compte
  d'au moins 100 000 abonnés déclarés par J7 peut déclencher la nouvelle
  vérification d'un token *déjà connu*, **uniquement** si son nom complet
  (distinctif) apparaît dans le texte. Ce n'est pas un soutien du compte au CA.
- **Tendances publiques** : un thread indépendant consulte les titres des RSS
  Google Trends **FR et US toutes les 10 minutes**, les archive avec dates et
  peut replanifier l'analyse de tokens déjà connus dont le nom correspond.
  Disponibilité du flux dépend de Google et de la connexion ; les erreurs ne
  doivent pas stopper le scanner.
- Dans les fiches de coins apparaissent les mentions J7 / tendances correspondantes
  **avec avertissement d'association thématique non vérifiée**. Aucun bonus
  de score ou de sécurité ne découle des mots-clés.
- **Recherche prospective** : signal `veille_precoce` enregistré à l'instant
  de première présentation, même si RugCheck n'a pas répondu, afin de mesurer
  ensuite la proportion de gros décrochages. Pas de sélection a posteriori.

## Limites importantes

- Il **n'y a pas de recherche X exhaustive** : seulement les publications
  **réellement reçues** par J7. Si le compte d'Elon Musk ou d'autres comptes
  n'apparaît pas dans le flux J7, le bot ne peut pas inventer ses tweets.
- Une correspondance entre le *nom d'un token* et une actualité **n'est pas
  une association vérifiée de contrat**. Les clones restent un problème ;
  lorsqu'une actualité correspond à trop de mints identiques déjà connus,
  les déclenchements automatiques par thème sont ignorés.
- Google Trends est une source de contexte, **pas** une source de signaux en
  secondes. On ne peut prédire les contenus d'un tweet inédit.
- La veille précoce exige encore un prix et une activité disponibles chez le
  fournisseur : un contrat J7 non encore coté est mis en file d'attente,
  pas affiché comme « marché tradable ». Le RPC websocket natif et l'analyse
  précise des acheteurs indépendants ne sont **pas encore développés**.
- Les seuils observatoires de cette version (`>=4` achats, `>=80 $` volume m5,
  <=30 min, prix 5 min entre -15 % et +25 %, majorité acheteuse >=55 %) sont
  des **heuristiques expérimentales non calibrées**. Ils ne garantissent ni la
  qualité de la demande ni une sortie possible.
- Suivre le **nombre de rugs après alerte** et les résultats nets après une
  entrée retardée ; les graphiques de prix ne sont pas des bénéfices réels.

## Tests locaux

Depuis le dossier `MemeRadar` :

```powershell
py -3 -m unittest discover -s tests -q
py -3 tools/audit_local.py --db radar.db --hours 2
```

Ce ZIP n'inclut **ni `radar.db`, ni clé ou jeton d'authentification**.
