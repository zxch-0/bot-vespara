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
# Délai (secondes) avant suppression d'un salon devenu vide : évite de
# détruire un salon lors d'un simple déplacement entre deux vocaux.
TEMPVOICE_DELETE_GRACE: Final = 3.0
# Texte d'information publié dans le chat du salon générateur.
TEMPVOICE_HUB_MESSAGE: Final = (
    "**Rejoins ce salon vocal pour obtenir ton propre vocal !**\n\n"
    "• Ton salon est créé automatiquement et tu en deviens le **propriétaire**.\n"
    "• Un **panneau de gestion** apparaît dans le chat texte du salon : "
    "renommer, verrouiller, limiter les places, expulser des membres, "
    "transférer la propriété, supprimer…\n"
    "• Le salon est **supprimé tout seul** dès qu'il est vide."
)
