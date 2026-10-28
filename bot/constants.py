"""Constantes partagées par tout le bot."""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------- #
# Identité de la marque
# --------------------------------------------------------------------------- #
BRAND: Final = "Vespara"
TAGLINE: Final = "Le serveur chill"
FOOTER: Final = f"{BRAND} • {TAGLINE}"

# --------------------------------------------------------------------------- #
# Couleurs (thème violet / nuit de Vespara)
# --------------------------------------------------------------------------- #
COLOR: Final = 0x8B5CF6  # violet principal
COLOR_SUCCESS: Final = 0x3BA55D
COLOR_ERROR: Final = 0xED4245
COLOR_WARNING: Final = 0xFAA61A
COLOR_INFO: Final = 0x5865F2
COLOR_MUTED: Final = 0x6B7280
COLOR_GIVEAWAY: Final = 0xA78BFA
COLOR_ANNOUNCE: Final = 0x7C3AED
COLOR_ECONOMY: Final = 0xFBBF24  # or / coins
COLOR_CASINO: Final = 0x10B981  # vert tapis de jeu
COLOR_LEVEL: Final = 0x22D3EE  # cyan des niveaux
COLOR_LEGENDARY: Final = 0xF97316  # orange des gros gains

# Palette utilisée par défaut pour les annonces
ANNOUNCE_COLORS: Final[dict[str, int]] = {
    "violet": COLOR,
    "bleu": 0x3B82F6,
    "vert": 0x22C55E,
    "or": 0xF59E0B,
    "rouge": 0xEF4444,
    "rose": 0xEC4899,
    "cyan": 0x06B6D4,
    "gris": 0x6B7280,
}

# --------------------------------------------------------------------------- #
# Emojis (unicode uniquement, aucune dépendance à un serveur d'emojis)
# --------------------------------------------------------------------------- #
EMOJI: Final[dict[str, str]] = {
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "info": "ℹ️",
    "gift": "🎁",
    "party": "🎉",
    "megaphone": "📢",
    "bot": "🤖",
    "gear": "🛠️",
    "leaf": "🍃",
    "sparkles": "✨",
    "clock": "⏳",
    "users": "👥",
    "crown": "👑",
    "wave": "👋",
    "shield": "🛡️",
    "book": "📖",
    "chart": "📊",
    "pin": "📌",
    "door": "🚪",
    "dice": "🎲",
    "menu": "🎛️",
    "tools": "🧰",
    "reply": "💬",
    "mic": "🎧",
    "lock": "🔒",
    "unlock": "🔓",
    "trash": "🗑️",
    "pencil": "✏️",
    "eye": "👁️",
    "eye_off": "🙈",
    "handshake": "🤝",
    "refresh": "🔄",
    "no_entry": "🚫",
    "speaker": "🔊",
}

# --------------------------------------------------------------------------- #
# Permissions proposées pour masquer les commandes staff
# --------------------------------------------------------------------------- #
# Discord ne permet pas de lier la *visibilité* d'une commande à un rôle via
# l'API du bot : seule `default_member_permissions` est disponible. On utilise
# donc une permission que le rôle staff possède forcément, configurable via
# la variable d'environnement STAFF_PERMISSION.
STAFF_PERMISSIONS: Final[dict[str, str]] = {
    "manage_guild": "Gérer le serveur",
    "manage_messages": "Gérer les messages",
    "manage_roles": "Gérer les rôles",
    "manage_channels": "Gérer les salons",
    "manage_threads": "Gérer les fils",
    "manage_events": "Gérer les événements",
    "moderate_members": "Exclure temporairement des membres",
    "kick_members": "Expulser des membres",
    "ban_members": "Bannir des membres",
    "administrator": "Administrateur",
}
DEFAULT_STAFF_PERMISSION: Final = "manage_guild"

# --------------------------------------------------------------------------- #
# Règlement par défaut
# --------------------------------------------------------------------------- #
DEFAULT_RULES: Final = (
    "**1 · Respect avant tout**\n"
    "Aucune insulte, discrimination, harcèlement ou provocation. On reste cool, "
    "même en cas de désaccord.\n\n"
    "**2 · Un salon, un sujet**\n"
    "Poste tes messages dans le salon adapté et évite le spam, le flood et les "
    "mentions massives inutiles.\n\n"
    "**3 · Pas de publicité non sollicitée**\n"
    "Invitations, liens de serveurs et autopromotion sont interdits sans "
    "l'accord de l'équipe.\n\n"
    "**4 · Contenus interdits**\n"
    "Pas de NSFW, de contenu choquant, de piratage ni de fichiers malveillants.\n\n"
    "**5 · Écoute l'équipe**\n"
    "Les décisions du staff sont à respecter. Pour contester un avertissement, "
    "ouvre un ticket en message privé auprès d'un membre de l'équipe.\n\n"
    "**6 · Bonne humeur obligatoire**\n"
    "Vespara est un serveur chill : détends-toi, discute, participe aux "
    "giveaways et profite. 🍃"
)

# Commande racine des modules réservés au staff (visibilité restreinte)
STAFF_COMMAND_ROOTS: Final[dict[str, str]] = {
    "giveaway": "Gestion des giveaways",
    "annonce": "Publication d'annonces",
    "autoresponder": "Réponses automatiques",
    "config": "Configuration du serveur",
    "vocal": "Salons vocaux temporaires",
    "eco-admin": "Administration de l'économie",
}

# --------------------------------------------------------------------------- #
# Divers
# --------------------------------------------------------------------------- #
AUTORESPONDER_MODES: Final[dict[str, str]] = {
    "contains": "Contient",
    "startswith": "Commence par",
    "endswith": "Se termine par",
    "exact": "Exactement",
    "regex": "Expression régulière",
}
# --------------------------------------------------------------------------- #
# Boule magique 🎱
# --------------------------------------------------------------------------- #
MAGIC8BALL_ANSWERS: Final[dict[str, tuple[str, ...]]] = {
    "oui": (
        "Oui, sans hésiter.",
        "C'est certain.",
        "Absolument !",
        "Compte là-dessus.",
        "Oui, la boule le sent bien.",
        "Les astres sont d'accord : oui.",
        "Évidemment que oui.",
        "Oui, et n'en doute plus.",
        "Tout porte à croire que oui.",
        "Oui ! Fonce.",
    ),
    "peut_etre": (
        "Je sais pas trop…",
        "Peut-être bien.",
        "Impossible de le dire maintenant.",
        "La boule hésite encore.",
        "Redemande-moi plus tard.",
        "Ça se joue à pile ou face.",
        "Hmm… les signaux sont flous.",
        "Pas impossible, mais pas gagné.",
        "Difficile à dire, vraiment.",
        "La boule a besoin d'un café avant de répondre.",
    ),
    "non": (
        "Non.",
        "Certainement pas.",
        "N'y compte pas trop.",
        "La boule dit non, désolé.",
        "Mes sources disent non.",
        "Très improbable.",
        "Non, et ne reviens pas me demander.",
        "C'est mort.",
        "Aucune chance, à mon avis.",
        "Non… enfin, je crois.",
    ),
}

# Libellé de la tonalité, affiché dans le pied de l'embed
MAGIC8BALL_TONES: Final[dict[str, str]] = {
    "oui": "positive",
    "peut_etre": "mitigée",
    "non": "négative",
}

# Emoji affiché devant la réponse
MAGIC8BALL_EMOJIS: Final[dict[str, str]] = {
    "oui": "🟢",
    "peut_etre": "🟡",
    "non": "🔴",
}

MAGIC8BALL_COLORS: Final[dict[str, int]] = {
    "oui": COLOR_SUCCESS,
    "peut_etre": COLOR_WARNING,
    "non": COLOR_ERROR,
}

MAGIC8BALL_EMOJI: Final = "🎱"
MAGIC8BALL_MIN_LENGTH: Final = 3
MAGIC8BALL_MAX_LENGTH: Final = 200
MAGIC8BALL_COOLDOWN: Final = 4.0  # secondes entre deux questions

MAX_AUTORESPONSES: Final = 50
MAX_GIVEAWAY_DURATION: Final = 60 * 60 * 24 * 90  # 90 jours
MIN_GIVEAWAY_DURATION: Final = 10  # secondes

# --------------------------------------------------------------------------- #
# Salons vocaux temporaires (« crée ton vocal »)
# --------------------------------------------------------------------------- #
# Nom du salon générateur créé par /vocal installer.
TEMPVOICE_HUB_NAME: Final = "➕ Créer ton vocal"
# Modèle de nom des salons créés. Variables : {user}, {username}, {count}
TEMPVOICE_NAME_TEMPLATE: Final = "Vocal de {user}"
TEMPVOICE_NAME_MAX_LENGTH: Final = 100
# Limite de places par défaut (0 = illimitée)
TEMPVOICE_DEFAULT_LIMIT: Final = 0
TEMPVOICE_MAX_LIMIT: Final = 99
# Nombre maximum de salons temporaires simultanés par serveur
TEMPVOICE_MAX_ROOMS: Final = 50
# Nombre maximum de salons inspectés au démarrage pour le rattachement auto
TEMPVOICE_RECOVERY_MAX_CHANNELS: Final = 30
# Délai (secondes) avant suppression d'un salon devenu vide : évite de
# détruire un salon lors d'un simple déplacement entre deux vocaux.
TEMPVOICE_DELETE_GRACE: Final = 5.0
# Texte d'information publié dans le chat du salon générateur.
TEMPVOICE_HUB_MESSAGE: Final = (
    "**Rejoins ce salon vocal pour obtenir ton propre vocal !**\n\n"
    "• Ton salon est créé automatiquement et tu en deviens le **propriétaire**.\n"
    "• Un **panneau de gestion** apparaît dans le chat texte du salon : "
    "renommer, verrouiller, limiter les places, expulser des membres, "
    "transférer la propriété, supprimer…\n"
    "• Le salon est **supprimé tout seul** dès qu'il est vide."
)

# --------------------------------------------------------------------------- #
# Thème graphique (esthétique « néon » partagée par tous les embeds)
# --------------------------------------------------------------------------- #
THEME_GRADIENTS: Final[dict[str, list[int]]] = {
    "violet": [0x8B5CF6, 0x6366F1, 0x4F46E5],
    "nuit": [0x0F172A, 0x312E81, 0x6D28D9],
    "menthe": [0x34D399, 0x059669, 0x0D9488],
    "or": [0xFDE68A, 0xF59E0B, 0xD97706],
    "feu": [0xF97316, 0xEF4444, 0xBE123C],
    "ocean": [0x22D3EE, 0x0EA5E9, 0x2563EB],
    "rose": [0xF472B6, 0xDB2777, 0x9D174D],
    "givaway": [0xA78BFA, 0x8B5CF6, 0x6D28D9],
}

# Barres de progression / animations textuelles
SPARKLES: Final = ("✨", "💫", "⭐", "🌟", "✦")
CONFETTI: Final = ("🎉", "🎊", "✨", "🎈", "🪅")
PROGRESS_FULL: Final = "▰"
PROGRESS_EMPTY: Final = "▱"
PROGRESS_HEAD: Final = "◆"

# Petites animations d'attente (frame -> texte)
LOADING_FRAMES: Final[tuple[str, ...]] = ("◐", "◓", "◑", "◒")
SLOT_SYMBOLS: Final[tuple[str, ...]] = ("🍒", "🍋", "🔔", "💎", "⭐", "7️⃣")

# --------------------------------------------------------------------------- #
# Économie, niveaux et casino
# --------------------------------------------------------------------------- #
CURRENCY_NAME: Final = "coins"
CURRENCY_EMOJI: Final = "🪙"
ECONOMY_START_BALANCE: Final = 100
ECONOMY_MAX_BET: Final = 50_000
ECONOMY_MIN_BET: Final = 10
ECONOMY_MAX_TRANSFER: Final = 100_000
ECONOMY_DAILY_BASE: Final = 150
ECONOMY_DAILY_STREAK_BONUS: Final = 50
ECONOMY_DAILY_STREAK_MAX: Final = 7
ECONOMY_WORK_MIN: Final = 40
ECONOMY_WORK_MAX: Final = 160
ECONOMY_WORK_COOLDOWN: Final = 3600  # 1 h
ECONOMY_DAILY_COOLDOWN: Final = 79200  # 22 h (marge pour ne pas rater un jour)
# XP gagné par message
ECONOMY_XP_MIN: Final = 12
ECONOMY_XP_MAX: Final = 26
ECONOMY_XP_COOLDOWN: Final = 45  # secondes entre deux gains d'XP
ECONOMY_XP_BASE: Final = 120  # XP requis pour le niveau 1 -> 2
ECONOMY_XP_EXPONENT: Final = 1.45
ECONOMY_MAX_LEVEL: Final = 500
ECONOMY_COINS_PER_LEVEL: Final = 25  # bonus de coins par niveau gagné
MAX_SHOP_ITEMS: Final = 40
MAX_LEVEL_REWARDS: Final = 30

# Gains du casino (multiplicateurs bruts, l'avantage maison reste léger)
CASINO_BLACKJACK_PAYOUT: Final = 2.0  # gain net = mise (paiement 1:1)
CASINO_BLACKJACK_NATURAL: Final = 2.5  # blackjack naturel
CASINO_SLOTS_PAYOUTS: Final[dict[int, float]] = {3: 12.0, 2: 2.2}
CASINO_ROULETTE_PAYOUTS: Final[dict[str, float]] = {
    "rouge": 2.0,
    "noir": 2.0,
    "pair": 2.0,
    "impair": 2.0,
    "bas": 2.0,
    "haut": 2.0,
    "vert": 14.0,
    "nombre": 36.0,
}
CASINO_DICE_PAYOUTS: Final[dict[str, float]] = {
    "pair": 2.0,
    "impair": 2.0,
    "sept": 6.0,
    "double": 8.0,
    "haut": 2.0,
    "bas": 2.0,
}

# Libellés français des paris
ROULETTE_LABELS: Final[dict[str, str]] = {
    "rouge": "🔴 Rouge",
    "noir": "⚫ Noir",
    "pair": "⚖️ Pair",
    "impair": "🎯 Impair",
    "bas": "📉 1-18",
    "haut": "📈 19-36",
    "vert": "🟢 Vert (0)",
    "nombre": "🔢 Un numéro",
}
DICE_LABELS: Final[dict[str, str]] = {
    "pair": "⚖️ Somme paire",
    "impair": "🎯 Somme impaire",
    "sept": "7️⃣ Exactement 7",
    "double": "👯 Double",
    "haut": "📈 9-12",
    "bas": "📉 2-6",
}

# Récompenses de série de /daily (index = jours consécutifs)
DAILY_STREAK_MULTIPLIERS: Final[tuple[float, ...]] = (1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.5)
