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
| 🎛️ **Menu** | Panneau à boutons : profil, infos serveur, rôles, giveaways, règlement, infos bot | Tout le monde |
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
https://discord.com/api/oauth2/authorize?client_id=TON_CLIENT_ID&permissions=274878426176&scope=bot%20applications.commands
```

Les permissions demandées couvrent l'envoi de messages, les embeds, l'historique,
la gestion des messages et les mentions. Ajuste-les si tu préfères.

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
   Serveurs : 1 · Commandes : 31
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

50 tests couvrent l'analyse des durées, les modes de l'auto-responder, la base
JSON, la page de statut, la structure des commandes (visibilité staff incluse)
et le cycle de vie complet d'un giveaway (création, participation, tirage,
relance, suppression) avec des objets Discord simulés.

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
│   └── settings.py      # /config ... et /staffrole
├── services/giveaways.py  # logique des giveaways (tirages, refresh, reroll)
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
| `/ping` · `/botinfo` | Latence et état du bot |

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
| `/staffrole [rôle]` | Définit le rôle staff (admin) |

---

## 🩺 Dépannage

| Symptôme | Piste |
| --- | --- |
| Les commandes n'apparaissent pas | Vérifie `GUILD_ID`, l'invitation avec le scope `applications.commands`, puis relance le client Discord (Ctrl+R) |
| « Accès refusé » alors que je suis staff | Le rôle staff est mal configuré : `/config voir`, puis `/staffrole` |
| Les commandes staff sont invisibles pour le staff | Le rôle n'a pas la permission de visibilité → voir [Visibilité](#-visibilité-des-commandes-staff) |
| L'auto-responder ne réagit pas | Active **Message Content Intent** dans le portail développeur |
| `PrivilegedIntentsRequired` au démarrage | Active les intents privilégiés (message content + members) |
| Le bot perd ses données | Offre gratuite Render : voir [Persistance](#-persistance-des-données) |
| Le bot est en veille | Offre gratuite Render : `SELF_PING=true` aide à le garder éveillé, sans garantie (Render peut aussi redémarrer une instance gratuite à tout moment) |
| `Invalid token` | Token régénéré ou mal copié → mets à jour `DISCORD_TOKEN` |

---

## 📄 Licence

MIT — voir [LICENSE](LICENSE).
