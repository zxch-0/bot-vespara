# 🍃 Vespara — bot Discord

Bot Discord complet pour le serveur **Vespara** (ambiance chill), avec giveaways,
annonces, réponses automatiques configurables et un menu plein de petites
commandes utiles.

Il est **prêt à déployer sur [Render](https://render.com) via un Blueprint**
(`render.yaml`), et tourne aussi très bien en local.

---

## ✨ Fonctionnalités

| Module | Ce qu'il fait | Accès |
| --- | --- | --- |
| 🎁 **Giveaways** | Création avec durée libre (`1h30`, `2 jours`…), plusieurs gagnants, rôle requis, boutons **Participer / Quitter / Participants**, tirage automatique, relance, suppression | Staff |
| 📢 **Annonces** | Rédaction dans un modal, **aperçu privé** avant publication, titre/contenu markdown, couleur, image, mention `@everyone` / `@here` / rôle staff | Staff |
| 💬 **Auto-responder** | Déclencheurs `contient` / `commence par` / `finit par` / `exact` / `regex`, sensibilité à la casse, réponse texte ou embed, activation, cooldown, test en direct | Staff |
| 🎱 **Boule magique** | `/boule` (alias `/8ball`) : tu poses une question, la boule se secoue et répond — oui, peut-être ou non — avec 30 réponses, un bouton **Secouer à nouveau** et un cooldown anti-spam | Tout le monde |
| 🎧 **Vocaux temporaires** | Le staff installe un salon générateur accessible à tous ; le rejoindre crée instantanément un vocal personnel avec un **panneau de gestion dans le chat du salon** : renommer, verrouiller, masquer, limiter les places, expulser, autoriser, transférer, récupérer, supprimer. Salon supprimé automatiquement quand il est vide, et **rattachement automatique** des vocaux existants après un redémarrage | Staff (installation) · tout le monde (utilisation) |
| 🪙 **Économie** | Coins, `/eco daily` (série bonus ×7), `/eco work`, virements, classements, **niveaux XP** par message avec rôles automatiques | Tout le monde (admin : `/eco-admin`) |
| 🛒 **Boutique** | Articles configurables par les admins : rôles, coins, tickets ou récompenses libres, avec stock, limite par membre et niveau requis. Achat par menu déroulant ou `/boutique acheter` | Tout le monde (config : staff) |
| 🎰 **Casino** | Blackjack interactif (tirer/rester/doubler/abandonner), machine à sous animée, roulette européenne et jeu de dés — mises de 10 à 50 000 coins | Tout le monde |
| 🎛️ **Menu** | Panneau à boutons : profil, économie, giveaways, vocaux, casino, infos serveur, rôles, règlement, infos bot | Tout le monde |
| 🧰 **Utilitaires** | `/ping`, `/botinfo`, `/userinfo`, `/avatar`, `/banner`, `/serverinfo`, `/roleinfo`, `/rules`, `/giveaways` | Tout le monde |
| 🩺 **Web** | `/health` pour Render, page de statut publique autonome (aucun CDN) et `/api/status` en JSON | Public |

**Points techniques :** slash commands uniquement, embeds aux couleurs du serveur,
vues persistantes (les boutons des giveaways et du menu fonctionnent encore après
un redémarrage), sauvegarde JSON atomique, arrêt propre sur `SIGTERM`.

---

## 🚀 Déploiement sur Render (Blueprint)

### 1. Créer l'application Discord

1. Va sur <https://discord.com/developers/applications> → **New Application** →
   nomme-la **Vespara**.
2. Onglet **Bot** → **Reset Token** → copie le token (il ne sera plus affiché).
3. Toujours dans **Bot**, active ces *Privileged Gateway Intents* :
   - ✅ **Message Content Intent** (obligatoire pour l'auto-responder)
   - ✅ **Server Members Intent** (recommandé : rôles, infos membres)
4. Onglet **OAuth2 → General** : garde les scopes `bot` + `applications.commands`.

### 2. Inviter le bot

Remplace `TON_CLIENT_ID` (onglet *General Information*) dans ce lien :

```
https://discord.com/api/oauth2/authorize?client_id=TON_CLIENT_ID&permissions=274931904080&scope=bot%20applications.commands
```

Les permissions demandées couvrent l'envoi de messages, les embeds, l'historique,
la gestion des messages et des salons, le déplacement de membres (vocaux
temporaires) et les mentions. Ajuste-les si tu préfères.

### 3. Déployer

1. Pousse ce dépôt sur GitHub (ou utilise ton fork).
2. Sur Render : **New +** → **Blueprint** → sélectionne le dépôt → **Apply**.
3. Render lit `render.yaml` et demande les variables secrètes :
   - `DISCORD_TOKEN` → le token de l'étape 1 (**obligatoire**)
   - `GUILD_ID` → clic droit sur le serveur → *Copier l'identifiant* (fortement recommandé)
   - `STAFF_ROLE_ID` → clic droit sur le rôle staff → *Copier l'identifiant*
   - `LOG_CHANNEL_ID` → salon de journalisation des commandes staff (facultatif)
4. Clique sur **Deploy**. Les logs doivent finir par :
   ```
   Vespara v1.0.0 connecté en tant que Vespara#1234
   Serveurs : 1 · Commandes : 33
   ```
5. Invite le bot sur le serveur, va dans un salon et tape `/menu`.

> ⏱️ Les slash commands sont synchronisées sur le serveur `GUILD_ID` : elles
> apparaissent **immédiatement**. Sans `GUILD_ID`, elles sont globales et peuvent
> mettre jusqu'à 1 h à se propager.

> 🔒 Le token Discord est un secret : ne le mets **jamais** dans le dépôt
> (`.env` est ignoré par Git) et régénère-le immédiatement s'il a fuité.

---

## 🔐 Visibilité des commandes staff

Objectif : **seuls les membres du rôle staff voient les commandes de gestion**
(`/giveaway`, `/annonce`, `/autoresponder`, `/config`).

### Ce que fait le bot

- Les commandes staff sont enregistrées avec `default_member_permissions` : elles
  sont **masquées** pour tous les membres qui n'ont pas la permission configurée
  (`STAFF_PERMISSION`, `manage_guild` par défaut).
- Une vérification du **rôle exact** est faite à chaque utilisation : même un
  modérateur sans le rôle staff est refusé (sauf administrateurs et propriétaire
  du bot).
- `/staffrole` (administrateur) permet de définir le rôle staff directement dans
  Discord, et `/config voir` affiche un diagnostic de la visibilité.

### Ce que Discord impose (important)

Discord **ne permet pas** à un bot de lier la visibilité d'une commande à un
rôle précis : l'API n'expose que `default_member_permissions` (des
*permissions*), et la modification des permissions de commandes exige un token
OAuth2 d'utilisateur, pas le token du bot.

Deux solutions pour que le staff voie les commandes :

1. **Donner la permission de visibilité au rôle staff** (le plus simple) :
   dans *Paramètres du serveur → Rôles → rôle staff*, active
   **Gérer le serveur** (ou la permission choisie via `STAFF_PERMISSION`).
2. **Configurer à la main** : *Paramètres du serveur → Intégrations → Vespara →
   Permissions des commandes*, et ajoute le rôle staff sur `/giveaway`,
   `/annonce`, `/autoresponder` et `/config`.

Dans les deux cas, le bot reste protégé par la vérification du rôle côté code.

---

## 🎧 Vocaux temporaires (« crée ton vocal »)

Un membre du staff lance **une seule fois** :

```
/vocal installer [categorie] [nom] [limite]
```

Le bot crée alors un salon vocal **générateur** (par défaut **➕ Créer ton vocal**)
visible et accessible à **tout le monde**, puis publie un message d'explication
dans son chat.

### Ce qui se passe ensuite, côté membre

1. Un membre rejoint le salon générateur ;
2. le bot crée aussitôt **son** salon vocal (nom configurable), l'y déplace et lui
   donne les droits de gestion ;
3. un **panneau de gestion** est publié dans le chat texte du salon créé, avec :

| Bouton | Effet |
| --- | --- |
| ✏️ **Renommer** | Change le nom du vocal (modal) |
| 👥 **Places** | Limite le nombre de places (0 = illimité) |
| 🔒 **Verrouiller** / 🔓 **Déverrouiller** | Interdit / réautorise l'accès à tout le monde |
| 🙈 **Masquer** / 👁️ **Afficher** | Rend le salon invisible / visible dans la liste |
| 🚫 **Expulser** | Déconnecte un membre et lui bloque le salon |
| ✅ **Autoriser** | Autorise une personne précise (même salon verrouillé) |
| 🤝 **Transférer** | Donne la propriété du salon à un autre membre |
| 👑 **Récupérer** | Tout membre présent peut reprendre le salon si le propriétaire est parti |
| 🗑️ **Supprimer** | Ferme le salon (avec confirmation) |
| 🔄 **Actualiser** | Redemande le panneau s'il a été supprimé |

4. le salon est **supprimé automatiquement 5 secondes** après être devenu vide
   (compte à rebours animé affiché sur le panneau, annulé si quelqu'un revient) ;
   si le propriétaire part alors que d'autres membres restent, la propriété est
   **transférée**.

### Commandes staff

| Commande | Description |
| --- | --- |
| `/vocal installer [categorie] [nom] [limite] [remplacer]` | Crée (ou recrée) le salon générateur |
| `/vocal etat` | Configuration + liste des vocaux ouverts |
| `/vocal modele <modele>` | Nom des vocaux — variables `{user}`, `{username}`, `{count}` |
| `/vocal limite <places>` | Places par défaut des nouveaux vocaux |
| `/vocal rattacher` | Rattache les vocaux détachés (perte de base, redéploiement) |
| `/vocal nettoyer` | Rattache les vocaux détachés, répare les panneaux et les fiches orphelines |
| `/vocal desactiver [supprimer_salons]` | Retire complètement le système |

### 🔁 Résilience : les vocaux ne se détachent plus

Le bot **ne dépend pas uniquement de sa base** pour reconnaître un vocal
temporaire. Le panneau contient un marqueur (`vespara:temproom:<propriétaire>`)
et le salon conserve les permissions du propriétaire : après un redémarrage, un
redéploiement ou une perte du fichier de données (disque éphémère Render), le
bot **rattache automatiquement** les vocaux existants :

- au démarrage (`on_ready`), pour tous les serveurs ;
- à la volée, dès qu'un bouton du panneau est cliqué sur un salon détaché ;
- avec `/vocal rattacher` (rattachement immédiat, avec la liste des salons) ;
- avec `/vocal nettoyer` (rattachement + réparation des panneaux).

L'état complet est relu depuis Discord : propriétaire (panneau ou permissions),
places, verrouillage, visibilité, membres expulsés ou autorisés. Le salon
générateur lui-même est retrouvé **par son nom** si sa configuration a été
perdue. Les vocaux encore rattachés n'ont donc plus besoin d'être recréés.

> 🔑 **Permissions du bot nécessaires :** *Gérer les salons*, *Déplacer des
> membres* et *Envoyer des messages*. Le panneau et les boutons étant
> **persistants**, ils fonctionnent encore après un redémarrage du bot.

---

## 🪙 Économie, niveaux et boutique

Chaque membre possède un compte par serveur : **coins**, **XP / niveau**,
inventaire et statistiques de jeu.

### Gagner des coins

| Source | Détail |
| --- | --- |
| `/eco daily` | Récompense journalière : **150 coins** + 50 par jour de série (multiplicateur jusqu'à ×2,5 au bout de 7 jours) |
| `/eco work` | Petit boulot toutes les heures : **40 à 160 coins** |
| Discussion | XP à chaque message (**12 à 26 XP**, une fois toutes les 45 s) → coins bonus à chaque niveau |
| Casino | Blackjack, machine à sous, roulette et dés |
| Boutique | Certains articles donnent directement des coins |

### Niveaux

- Courbe d'XP : `120 × niveau^1,45` (niveau 1 → 2 : 120 XP, niveau 10 : ~2 700 XP).
- Chaque passage de niveau offre **25 × niveau** coins et peut débloquer un **rôle
  automatique** configuré par le staff.
- Les annonces de niveau sont animées (barre de progression, confettis) et peuvent
  être envoyées dans un salon dédié.

### Commandes publiques

| Commande | Description |
| --- | --- |
| `/eco profil [membre]` | Carte de profil complète (solde, niveau, rang, casino) |
| `/eco solde [membre]` | Solde en un coup d'œil |
| `/eco niveau [membre]` | Progression détaillée + prochaines récompenses |
| `/eco classement [par]` | Top 100 coins ou XP (paginé, podium 🥇🥈🥉) |
| `/eco daily` · `/eco work` | Récompenses périodiques |
| `/eco payer <membre> <montant>` | Virement (`1k`, `2.5k`, `1 000`…) |
| `/boutique voir` | Boutique interactive (menu déroulant + confirmation) |
| `/boutique acheter <article>` | Achat direct (autocomplétion) |
| `/boutique inventaire` | Tes achats |

### Commandes staff (`/eco-admin`)

| Commande | Description |
| --- | --- |
| `donner` / `retirer` | Créditer ou débiter un membre |
| `xp` | Ajouter de l'XP (déclenche niveaux et rôles) |
| `article-ajouter` | Ajouter un article : `type` (`role`, `coins`, `ticket`, `custom`), prix, rôle, stock, niveau requis, limite par membre |
| `article-modifier` / `article-supprimer` / `article-liste` | Gérer le catalogue |
| `recompense <niveau> <rôle>` | Attribuer automatiquement un rôle à un niveau (`retirer:True` pour supprimer) |
| `parametres` | XP par message on/off, multiplicateur, salon d'annonce, salon du casino |
| `reinitialiser <membre>` | Remettre un compte à zéro |
| `etat` | Statistiques globales (coins en circulation, podium, articles) |

> 🔒 `/eco-admin` est réservé au staff (même mécanisme de visibilité que les
> autres commandes de gestion).

---

## 🎰 Casino

| Jeu | Commande | Gains |
| --- | --- | --- |
| 🃏 **Blackjack** | `/casino blackjack <mise>` | ×2 en cas de victoire, **×2,5** sur blackjack naturel, égalité remboursée, abandon = moitié rendue |
| 🎰 **Machine à sous** | `/casino slots <mise>` | 3 identiques **×12** (trois 7️⃣ : ×24), 2 identiques ×2,2 |
| 🎡 **Roulette** | `/casino roulette <mise> <pari>` | rouge/noir, pair/impair, bas/haut ×2 · vert (0) ×14 · numéro exact ×36 |
| 🎲 **Dés** | `/casino des <mise> <pari>` | somme paire/impaire ×2 · 7 exact ×6 · double ×8 |

- `/casino accueil` : présentation avec boutons de raccourcis ;
- `/casino jeux` : tableau complet des paris et multiplicateurs ;
- `/casino mise-max [jeu]` : miser tout son solde d'un coup ;
- mises **10 → 50 000 coins**, parties **100 % éphémères** (personne d'autre ne voit
  tes cartes), boutons du blackjack avec timeout automatique ;
- animations : rouleaux qui défilent, bille qui tourne, dés qui roulent, cartes
  révélées, barres de progression animées.

---

## 🎨 Interface & animations

- **Thème à dégradés** (`violet`, `menthe`, `or`, `ocean`, `rose`, `feu`, `nuit`) :
  chaque embed choisit son ambiance via `embed(..., accent="menthe")`.
- **Barres de progression animées** (`animated_progress`, `percent_bar`) : XP,
  giveaways, compte à rebours des vocaux.
- **Sélecteurs et spinners** (`spinner`, `typing_dots`) : `/ping` mesure la latence
  en animant le calcul, les machines à sous font défiler les rouleaux.
- **Présence tournante** du bot toutes les 2 minutes.
- **Badges de niveau** (🌱 → 🌌) et podium de classement (🥇🥈🥉).
- Performance : seuils d'XP précalculés (`bisect`), conversions de niveau en
  O(log n), sauvegardes JSON regroupées, cache des embeds coûteux.

---

## ⚙️ Variables d'environnement

Toutes les variables sont optionnelles sauf `DISCORD_TOKEN` (voir `.env.example`).

| Variable | Défaut | Description |
| --- | --- | --- |
| `DISCORD_TOKEN` | — | **Obligatoire.** Token du bot |
| `GUILD_ID` | — | Serveur de test : synchronisation instantanée des commandes |
| `STAFF_ROLE_ID` | — | Rôle staff (peut aussi être défini avec `/staffrole`) |
| `LOG_CHANNEL_ID` | — | Salon de logs des commandes staff |
| `STAFF_PERMISSION` | `manage_guild` | Permission qui révèle les commandes staff (`manage_guild`, `manage_messages`, `manage_events`, `administrator`…) |
| `COMMAND_SCOPE` | `guild` | `guild` (instant sur `GUILD_ID`), `global`, ou `both` |
| `DATABASE_PATH` | `data/vespara.json` | Fichier de sauvegarde des données |
| `PORT` | `8080` | Port du serveur HTTP (Render l'injecte lui-même) |
| `SELF_PING` | `true` | Ping périodique du service Render pour éviter la veille |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `BOT_NAME` / `BOT_TAGLINE` | `Vespara` / `Le serveur chill` | Personnalisation des embeds |

---

## 💾 Persistance des données

Les données (giveaways, réponses automatiques, configuration par serveur) sont
stockées dans un fichier JSON (`DATABASE_PATH`).

> ℹ️ **Offre gratuite :** le service se met en veille après 15 min sans trafic
> (`SELF_PING=true` le garde éveillé), et le quota est de 750 h d'instance par
> mois et par espace de travail — un bot maintenu 24/7 en consomme ~730 h.

> ⚠️ **Offre gratuite Render : le disque est éphémère.**
> Les données sont perdues à chaque redéploiement ou redémarrage du service.
> Les **vocaux temporaires** sont eux-mêmes récupérés depuis Discord (voir
> [Résilience](#-résilience-les-vocaux-ne-se-détachent-plus)) : les salons
> existants sont automatiquement rattachés au bot.

Pour les conserver durablement :

1. Dans `render.yaml`, passe `plan: free` à `plan: starter` ;
2. Décommente le bloc `disk:` en bas du fichier (`mountPath: /var/data`) ;
3. Change `DATABASE_PATH` en `/var/data/vespara.json` ;
4. Redéploie le Blueprint.

---

## 💻 Développement local

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # puis renseigne DISCORD_TOKEN
python run.py
```

Le serveur de statut est disponible sur <http://localhost:8080>.
Sans `DISCORD_TOKEN`, le bot s'arrête avec un message explicite.

### Tests & lint

```bash
python -m unittest discover -s tests -t . -v
ruff check .            # pip install ruff
```

Astuce : ajoute ces deux commandes dans une GitHub Action pour lancer les
tests automatiquement à chaque push.

192 tests couvrent l'analyse des durées, les modes de l'auto-responder, la base
JSON, la page de statut, la structure des commandes (visibilité staff incluse),
le cycle de vie complet d'un giveaway (création, participation, tirage, relance,
suppression), la boule magique (tirage, embeds, bouton et cooldowns) et les
vocaux temporaires (création au join, permissions, panneau de gestion, expulsion,
transfert, récupération, suppression automatique, **rattachement des salons après
perte de la base**), l'**économie** (courbe d'XP, daily/work, virements, boutique,
classements, récompenses de niveau) et le **casino** (distributions, as, blackjack,
double, abandon, jackpots, couleurs et paris de la roulette, dés), avec des objets
Discord simulés.

Un script de fumée (`tests/test_smoke.py`) exécute **toutes les commandes** avec des
interactions simulées pour détecter les erreurs de rendu.

### Arborescence

```
bot/
├── main.py              # VesparaBot : démarrage, sync, erreurs, arrêt propre
├── config.py            # chargement des variables d'environnement
├── constants.py         # couleurs, emojis, textes par défaut
├── database.py          # base JSON atomique + helpers
├── helpers.py           # durées, embeds, formatage
├── checks.py            # rôle staff / admin
├── web.py               # serveur aiohttp (santé + page de statut)
├── cogs/
│   ├── giveaways.py     # /giveaway ...
│   ├── announcements.py # /annonce
│   ├── autoresponder.py # /autoresponder ...
│   ├── menu.py          # /menu
│   ├── utilities.py     # commandes publiques
│   ├── fun.py           # /boule et /8ball
│   ├── settings.py      # /config ... et /staffrole
│   ├── tempvoice.py     # /vocal ... (vocaux temporaires)
│   ├── economy.py       # /eco, /boutique et /eco-admin
│   └── casino.py        # /casino (blackjack, slots, roulette, dés)
├── services/
│   ├── giveaways.py     # logique des giveaways (tirages, refresh, reroll)
│   ├── magic_ball.py    # tirage et embeds de la boule magique
│   ├── tempvoice.py     # création/suppression et gestion des vocaux temporaires
│   ├── economy.py       # comptes, XP/niveaux, boutique, classements
│   └── casino.py        # blackjack, machine à sous, roulette, dés (logique pure)
└── ui/                    # vues, modals, pagination, embeds
```

---

## 📖 Commandes

### Tout le monde

| Commande | Description |
| --- | --- |
| `/menu` | Ouvre le menu du serveur (boutons) |
| `/rules` | Affiche le règlement |
| `/giveaways` | Liste les giveaways en cours |
| `/userinfo [membre]` | Fiche d'un membre |
| `/avatar [membre]` | Avatar (PNG / JPG / WEBP) |
| `/banner [membre]` | Bannière de profil |
| `/serverinfo` | Informations du serveur |
| `/roleinfo <rôle>` | Détails d'un rôle |
| `/boule <question>` · `/8ball` | Pose une question à la boule magique 🎱 |
| `/ping` · `/botinfo` | Latence (animée) et état du bot |
| `/eco profil` · `/eco solde` · `/eco niveau` · `/eco classement` · `/eco daily` · `/eco work` · `/eco payer` | Économie et niveaux |
| `/boutique voir` · `/boutique acheter` · `/boutique inventaire` | Boutique |
| `/casino accueil` · `/casino blackjack` · `/casino slots` · `/casino roulette` · `/casino des` · `/casino jeux` · `/casino mise-max` | Casino |

### Staff (`/giveaway`, `/annonce`, `/autoresponder`, `/config`)

| Commande | Description |
| --- | --- |
| `/giveaway create <prix> <durée> [gagnants] [salon] [description] [role]` | Lance un giveaway |
| `/giveaway end [giveaway]` | Termine et tire les gagnants |
| `/giveaway reroll [giveaway] [gagnants]` | Relance le tirage |
| `/giveaway list` | Giveaways en cours |
| `/giveaway delete [giveaway]` | Supprime un giveaway |
| `/annonce [salon] [mention] [couleur] [image]` | Rédige une annonce avec aperçu |
| `/autoresponder add [mode] [casse] [embed]` | Ajoute une réponse automatique |
| `/autoresponder remove/toggle/list/test/cooldown/reset` | Gestion des réponses |
| `/config voir` | Configuration + diagnostic de visibilité |
| `/config salon-annonces [salon]` | Salon par défaut des annonces |
| `/config reglement [reinitialiser]` | Édite le règlement |
| `/config menu [salon]` | Publie le panneau du menu |
| `/eco-admin donner/retirer/xp/article-*/recompense/parametres/reinitialiser/etat` | Économie, boutique et niveaux |
| `/vocal installer` · `etat` · `modele` · `limite` · `rattacher` · `nettoyer` · `desactiver` | Vocaux temporaires (voir [Vocaux temporaires](#-vocaux-temporaires-crée-ton-vocal)) |
| `/staffrole [rôle]` | Définit le rôle staff (admin) |

---

## 🎱 Boule magique

```
/boule question:"Est-ce que je vais gagner au giveaway ?"
```

1. La boule affiche d'abord **« La boule se secoue… »** (≈ 1 s de suspense) ;
2. puis la réponse s'affiche, colorée selon la tonalité :

| Tonalité | Couleur | Exemples de réponses |
| --- | --- | --- |
| 🟢 Oui | vert | « C'est certain. », « Absolument ! », « Fonce. » |
| 🟡 Peut-être | orange | « Je sais pas trop… », « Redemande-moi plus tard. » |
| 🔴 Non | rouge | « Non. », « Très improbable. », « C'est mort. » |

- **30 réponses** réparties équitablement entre les trois tonalités ;
- un bouton **Secouer à nouveau** permet de retenter sans retaper la question ;
- un cooldown de **4 s par membre** évite le spam (`/8ball` est un alias) ;
- la question est limitée à 200 caractères et affichée dans l'embed.

Les réponses se personnalisent dans `bot/constants.py` → `MAGIC8BALL_ANSWERS`.

---

## 🩺 Dépannage

| Symptôme | Piste |
| --- | --- |
| Les commandes n'apparaissent pas | Vérifie `GUILD_ID`, l'invitation avec le scope `applications.commands`, puis relance le client Discord (Ctrl+R) |
| « Accès refusé » alors que je suis staff | Le rôle staff est mal configuré : `/config voir`, puis `/staffrole` |
| Les commandes staff sont invisibles pour le staff | Le rôle n'a pas la permission de visibilité → voir [Visibilité](#-visibilité-des-commandes-staff) |
| L'auto-responder ne réagit pas | Active **Message Content Intent** dans le portail développeur |
| `PrivilegedIntentsRequired` au démarrage | Active les intents privilégiés (message content + members) |
| `/vocal` n'apparaît pas | Commande staff : voir [Visibilité](#-visibilité-des-commandes-staff). L'installation demande **Gérer les salons** |
| Les membres ne sont pas déplacés dans leur vocal | Donne au bot la permission **Déplacer des membres** |
| Les vocaux « se détachent » (0 vocal actif alors que des salons existent) | Lance `/vocal rattacher` : le bot relit les panneaux et rattache les salons. C'est automatique au démarrage et au clic sur un bouton. Sur Render gratuit, la base est éphémère → voir [Persistance](#-persistance-des-données) |
| Le panneau d'un vocal a été supprimé | Le propriétaire clique sur **Actualiser**, ou un staff lance `/vocal nettoyer` |
| Les membres ne gagnent pas d'XP | Vérifie `/eco-admin parametres` (XP par message activée, multiplicateur) |
| La boutique est vide | Ajoute un article : `/eco-admin article-ajouter` |
| `/eco-admin` n'apparaît pas | Commande staff : voir [Visibilité](#-visibilité-des-commandes-staff) |
| Le bot perd ses données | Offre gratuite Render : voir [Persistance](#-persistance-des-données) |
| Le bot est en veille | Offre gratuite Render : `SELF_PING=true` aide à le garder éveillé, sans garantie (Render peut aussi redémarrer une instance gratuite à tout moment) |
| `Invalid token` | Token régénéré ou mal copié → mets à jour `DISCORD_TOKEN` |

---

## 📄 Licence

MIT — voir [LICENSE](LICENSE).
