# MemeRadar v6.2 — restauration de la veille sociale J7

## Pourquoi tu recevais des tweets sans voir de coins J7

La v6.1 n'affichait plus le panneau de tweets : son `web/social.js` ne chargeait que `/api/social-status`. Pourtant, le flux J7 était authentifié et recevait des publications. Dans l'export fourni, les **70 dernières publications enregistrées n'ont aucune adresse Solana**, et la majorité portent sur l'actualité générale. Ce n'est pas une preuve d'échec de la connexion : J7 propose aussi des comptes non liés aux memecoins.

## Ce qui a changé

- **Panneau « Veille sociale » restauré** dans le tableau de bord, avec vue « Crypto / memecoins », vue « Avec contrat CA » et vue « Tout le flux », plus un réglage pour afficher les réponses et reposts. Le panneau lit `/api/social` toutes les **2 secondes** ; les tweets reçus n'ont pas besoin d'avoir une adresse Solana pour être affichés.
- **Compteurs de diagnostic** : nombre de tweets reçus, stockés, tweets ayant un CA confirmé, associations tweet/contrat et tweets jugés pertinents parmi les derniers messages. `new_mints` dénombre les nouvelles associations de mints détectées par les tweets ; ce compteur ne mesure pas la rentabilité et il est normal qu'il reste à zéro si les publications sont hors sujet.
- **Extraction enrichie** depuis `text`, les cartes `card`, `article`, les blocs texte de `components`, l'URL préférée de trading et les champs directs J7 `contractAddress` / `extraContractAddresses` lorsqu'ils correspondent à Solana. Une adresse doit être valide en base58 et représenter 32 octets.
- **`token_meta` relié à son tweet d'origine** lorsqu'un identifiant de post existe, même s'il arrive après le tweet. Quand `token_meta` arrive avant le tweet, l'association est conservée en mémoire jusqu'à 3 minutes (puis abandonnée s'il n'arrive pas). Plusieurs contrats pour un même post ne sont plus éliminés par le dédoublonnage.
- Aucune supposition à partir d'un simple `$TICKER` ; les contenus cités par d'autres auteurs ne sont pas interprétés comme des recommandations de l'auteur principal. Les métadonnées et les relations directes ne prouvent pas que l'auteur recommande ou achète le coin.
- Rien n'a été modifié dans les critères de sélection, les scores marché, les sécurités, les achats (aucun achat automatique) ni dans les délais GeckoTerminal. L'interface reste actualisée pendant le scan DEX.

## Installation Windows (sans perdre l'historique)

1. Ferme complètement la v6.1 avec **Ctrl+C**.
2. **Sauvegarde ton dossier v6.1**, notamment `radar.db`, `wallets.txt` et, s'ils sont présents, `radar.db-wal` et `radar.db-shm`. Ne copie pas une base SQLite en cours d'utilisation.
3. Décompresse ce ZIP dans un **nouveau dossier** et copie `radar.db` et `wallets.txt` depuis la sauvegarde (pas besoin de recopier les fichiers `-wal` si la fermeture propre les a fusionnés). **Ne partage pas ces fichiers s'ils contiennent des informations personnelles.**
4. Lance `START_J7.ps1` avec PowerShell et saisis ta session J7 sans la communiquer à qui que ce soit. Si PowerShell demande si tu approuves le script, vérifie le code avant de choisir une exécution ponctuelle.
5. Ouvre `http://127.0.0.1:8765`, puis appuie sur **Ctrl+F5** pour renouveler les fichiers JS/CSS mis en cache. Clique sur « Veille sociale J7 » dans la barre latérale pour accéder directement au flux.

## Vérifier rapidement

- Ouvre `http://127.0.0.1:8765/api/social-status` : `connected: true` et `upstream_connected: true` indiquent que le flux est actif.
- Ouvre `http://127.0.0.1:8765/api/social` : `posts` contient des tweets ; `diagnostics.linked_posts` compte les tweets liés à une adresse Solana dans la base.
- Si `posts` est rempli et `linked_posts` reste à 0, va sur l'onglet « Tout le flux » : la source envoie des publications, mais peut ne pas transmettre de contrats Solana pendant la fenêtre observée.
- Le bouton « Avec contrat CA » pourra rester vide pendant un moment : il ne signifie pas que la connexion est perdue.

## Limites réelles

Le flux est **quasi temps réel** en fonction de la source ; la latence du fournisseur et l'indexation ne sont pas garanties. Le filtrage « Crypto / memecoins » est un filtre lexical d'affichage, pas une analyse sémantique avancée. Les mentions sociales ne garantissent aucune hausse et peuvent résulter de publicité payante, de manipulation ou de sarcasme. Sans contrat Solana vérifié, MemeRadar n'associe pas un ticker à un token précis. Les 62 tests automatisés restent hors ligne ; une session J7 authentifiée et continue doit être vérifiée sur ton PC.
