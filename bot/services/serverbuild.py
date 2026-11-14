"""Construction automatique d'un serveur complet (commande `/build`).

Le module ne dépend d'aucune vue : il reçoit un serveur (`discord.Guild`) et
crée les catégories, les salons, les permissions et les messages d'accueil.
Il est volontairement **idempotent** : un salon qui porte déjà le bon nom est
réutilisé au lieu d'être dupliqué, ce qui permet de relancer `/build` après
avoir ajouté ou supprimé des modules.

Les noms suivent le thème du bot : `-➠˗ˏˋ🎐┆𝑃𝑖𝑛𝑔𝑠ˎˊ˗`.
"""

from __future__ import annotations

import asyncio
import logging
import re
import string
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import discord

from ..constants import (
    COLOR,
    COLOR_ANNOUNCE,
    COLOR_GIVEAWAY,
    COLOR_INFO,
    EMOJI,
    FOOTER,
    TEMPVOICE_DEFAULT_LIMIT,
    TEMPVOICE_HUB_NAME,
    TEMPVOICE_NAME_TEMPLATE,
)
from ..helpers import embed

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Polices « fantaisie »
# --------------------------------------------------------------------------- #
# Discord n'a pas de mise en forme des salons : on utilise donc les glyphes
# Unicode « mathematical italic » (𝑃𝑖𝑛𝑔𝑠). Les chiffres, eux, n'existent pas en
# italique : ils basculent sur la variante « bold italic ».
PREFIX = "-➠"
ACCENT_START = "˗ˏˋ"
ACCENT_END = "ˎˊ˗"
NAME_MAX_LENGTH = 100
# Version de la structure générée (permet de savoir qu'un /build a déjà eu lieu).
BUILD_VERSION = 1
# Pause (secondes) entre deux créations de salons : ménage les limites Discord.
BUILD_DELAY = 0.35


def _build_fancy_map() -> dict[str, str]:
    """Table de correspondance a-z / A-Z / 0-9 vers les caractères stylisés.

    Lettres en italique, chiffres en gras-italique (l'italique seul n'existe pas
    pour les chiffres Unicode).
    """
    mapping: dict[str, str] = {}
    for letter in string.ascii_uppercase:
        try:
            mapping[letter] = unicodedata.lookup(f"MATHEMATICAL ITALIC CAPITAL {letter}")
        except KeyError:  # pragma: no cover - tous les glyphes existent
            mapping[letter] = letter
    for letter in string.ascii_lowercase:
        name = f"MATHEMATICAL ITALIC SMALL {letter.upper()}"
        try:
            mapping[letter] = unicodedata.lookup(name)
        except KeyError:
            # Unicode nomme deux glyphes autrement (« h » manquant, « h » en
            # planche ?), on retombe sur la variante « sans-serif italic ».
            try:
                mapping[letter] = unicodedata.lookup(f"MATHEMATICAL SANS-SERIF ITALIC SMALL {letter.upper()}")
            except KeyError:  # pragma: no cover
                mapping[letter] = letter
    for digit, word in zip("0123456789", "ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE", strict=False):
        try:
            mapping[digit] = unicodedata.lookup(f"MATHEMATICAL BOLD DIGIT {word}")
        except KeyError:  # pragma: no cover
            mapping[digit] = digit
    return mapping


FANCY_MAP = _build_fancy_map()


def fancy(text: str) -> str:
    """Convertit un texte ASCII en « mathematical italic »."""
    return "".join(FANCY_MAP.get(char, char) for char in text)


def slugify(text: str) -> str:
    """`Règles & infos` → `Regles-infos` (ASCII, sans espace)."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-")


def format_channel_name(label: str, emoji: str = "", *, max_length: int = NAME_MAX_LENGTH) -> str:
    """Nom de salon complet : `-➠˗ˏˋ🎐┆𝑃𝑖𝑛𝑔𝑠ˎˊ˗`."""
    slug = slugify(label) or "salon"
    icon = f"{emoji}" if emoji else ""
    name = f"{PREFIX}{ACCENT_START}{icon}┆{fancy(slug)}{ACCENT_END}"
    if len(name) <= max_length:
        return name
    # On tronque le texte stylisé, jamais les décorations.
    room = max_length - len(PREFIX) - len(ACCENT_START) - len(icon) - 1 - len(ACCENT_END)
    return f"{PREFIX}{ACCENT_START}{icon}┆{fancy(slug)[: max(1, room)]}{ACCENT_END}"


def format_category_name(label: str, emoji: str = "", *, max_length: int = NAME_MAX_LENGTH) -> str:
    """Nom de catégorie : `˗ˏˋ🎐┆𝑀𝒶 𝒞𝒶𝓉𝑒́𝑔𝑜𝓇𝒾𝑒ˎˊ˗`."""
    slug = slugify(label) or "categorie"
    name = f"{ACCENT_START}{emoji}┆{fancy(slug)}{ACCENT_END}"
    if len(name) <= max_length:
        return name
    room = max_length - len(ACCENT_START) - len(emoji) - 1 - len(ACCENT_END)
    return f"{ACCENT_START}{emoji}┆{fancy(slug)[: max(1, room)]}{ACCENT_END}"


# --------------------------------------------------------------------------- #
# Règlement par défaut proposé par /build
# --------------------------------------------------------------------------- #
SIMPLE_RULES = (
    f"{EMOJI['wave']} **Bienvenue !** En restant ici, tu acceptes les règles ci-dessous.\n\n"
    f"{EMOJI['handshake']} **1 · Respecte tout le monde**\n"
    "Pas d'insulte, de harcèlement, de discrimination ni de provocation.\n\n"
    f"{EMOJI['reply']} **2 · Un salon, un sujet**\n"
    "Poste dans le salon adapté, sans spam ni mention massive inutile.\n\n"
    f"{EMOJI['no_entry']} **3 · Zéro publicité**\n"
    "Pas de liens de serveurs ni d'autopromotion sans l'accord du staff.\n\n"
    f"{EMOJI['shield']} **4 · Contenus interdits**\n"
    "Pas de NSFW, de contenu choquant, de piratage ou de fichier malveillant.\n\n"
    f"{EMOJI['crown']} **5 · Écoute le staff**\n"
    "Ses décisions se respectent. Un souci ? Ouvre un ticket auprès de l'équipe.\n\n"
    f"{EMOJI['leaf']} **6 · Bonne humeur**\n"
    "On est là pour chill : discute, participe aux giveaways et profite."
)


# --------------------------------------------------------------------------- #
# Description du plan à construire
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ChannelSpec:
    """Un salon à créer (ou à réutiliser)."""

    key: str
    label: str
    emoji: str
    kind: str = "text"  # text | voice
    topic: str | None = None
    access: str = "public"  # public | read_only | staff
    intro: str | None = None  # clé du message d'accueil à publier


@dataclass(frozen=True)
class CategorySpec:
    """Une catégorie et ses salons."""

    key: str
    label: str
    emoji: str
    channels: tuple[ChannelSpec, ...]
    access: str = "public"


@dataclass
class BuildOptions:
    """Options de `/build`."""

    regles: bool = True
    logs: bool = True
    vocal: bool = True
    economie: bool = True
    texte_regles: str | None = None


@dataclass
class BuildResult:
    """Résultat détaillé d'une construction."""

    created: list[dict[str, str]] = field(default_factory=list)
    reused: list[dict[str, str]] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    channels: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def created_count(self) -> int:
        return len(self.created)

    @property
    def reused_count(self) -> int:
        return len(self.reused)

    @property
    def failed_count(self) -> int:
        return len(self.failed)


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #
def build_plan(options: BuildOptions | None = None) -> list[CategorySpec]:
    """Liste des catégories / salons à créer selon les options."""
    options = options or BuildOptions()
    plan: list[CategorySpec] = []

    info_channels: list[ChannelSpec] = []
    if options.regles:
        info_channels.append(
            ChannelSpec(
                key="regles",
                label="Regles",
                emoji="📜",
                topic="Le règlement du serveur — à lire avant de discuter.",
                access="read_only",
                intro="regles",
            )
        )
    info_channels.extend(
        [
            ChannelSpec(
                key="annonces",
                label="Annonces",
                emoji="📢",
                topic="Annonces officielles du serveur.",
                access="read_only",
                intro="annonces",
            ),
            ChannelSpec(
                key="giveaways",
                label="Giveaways",
                emoji="🎁",
                topic="Concours et cadeaux du serveur.",
                access="read_only",
                intro="giveaways",
            ),
            ChannelSpec(
                key="partenariats",
                label="Partenariats",
                emoji="🤝",
                topic="Nos partenaires et leurs serveurs.",
                access="read_only",
                intro="partenariats",
            ),
        ]
    )
    plan.append(
        CategorySpec(
            key="information",
            label="Informations",
            emoji="📌",
            channels=tuple(info_channels),
        )
    )

    community_channels = [
        ChannelSpec(
            key="general",
            label="General",
            emoji="💬",
            topic="Le salon principal : discute de tout et de rien.",
            intro="general",
        ),
        ChannelSpec(
            key="pings",
            label="Pings",
            emoji="🎐",
            topic="Choisis ici les rôles qui te correspondent.",
            access="read_only",
            intro="pings",
        ),
        ChannelSpec(
            key="medias",
            label="Medias",
            emoji="📸",
            topic="Tes meilleures photos, clips et créations.",
            intro="medias",
        ),
        ChannelSpec(
            key="commandes",
            label="Commandes-bot",
            emoji="🤖",
            topic="Salon réservé aux commandes du bot.",
            intro="commandes",
        ),
    ]
    if options.economie:
        community_channels.extend(
            [
                ChannelSpec(
                    key="niveaux",
                    label="Niveaux",
                    emoji="📊",
                    topic="Annonces de niveaux et paliers débloqués.",
                    access="read_only",
                    intro="niveaux",
                ),
                ChannelSpec(
                    key="casino",
                    label="Casino",
                    emoji="🎰",
                    topic="Mets tes coins en jeu : blackjack, slots, roulette, dés.",
                    intro="casino",
                ),
            ]
        )
    plan.append(
        CategorySpec(
            key="communaute",
            label="Communaute",
            emoji="💬",
            channels=tuple(community_channels),
        )
    )

    voice_channels: list[ChannelSpec] = [
        ChannelSpec(key="vocal-general", label="Vocal general", emoji="🔊", kind="voice"),
        ChannelSpec(key="vocal-gaming", label="Gaming", emoji="🎮", kind="voice"),
    ]
    if options.vocal:
        voice_channels.append(
            ChannelSpec(
                key="vocal-hub",
                label=TEMPVOICE_HUB_NAME,
                emoji="➕",
                kind="voice",
                intro="vocal-hub",
            )
        )
    plan.append(
        CategorySpec(
            key="vocaux",
            label="Vocaux",
            emoji="🎧",
            channels=tuple(voice_channels),
        )
    )

    staff_channels: list[ChannelSpec] = [
        ChannelSpec(
            key="staff",
            label="Staff",
            emoji="🛡️",
            topic="Espace de discussion de l'équipe.",
            access="staff",
            intro="staff",
        )
    ]
    if options.logs:
        staff_channels.extend(
            [
                ChannelSpec(
                    key="logs-messages",
                    label="Logs-messages",
                    emoji="📝",
                    topic="Messages modifiés et supprimés.",
                    access="staff",
                    intro="logs",
                ),
                ChannelSpec(
                    key="logs-membres",
                    label="Logs-membres",
                    emoji="🚪",
                    topic="Arrivées, départs et pseudonymes.",
                    access="staff",
                    intro="logs",
                ),
                ChannelSpec(
                    key="logs-sanctions",
                    label="Logs-sanctions",
                    emoji="🔨",
                    topic="Avertissements, exclusions et bannissements.",
                    access="staff",
                    intro="logs",
                ),
                ChannelSpec(
                    key="logs-vocaux",
                    label="Logs-vocaux",
                    emoji="🎙️",
                    topic="Connexions et changements de salon vocal.",
                    access="staff",
                    intro="logs",
                ),
                ChannelSpec(
                    key="logs-bot",
                    label="Logs-bot",
                    emoji="⚙️",
                    topic="Commandes staff et événements techniques.",
                    access="staff",
                    intro="logs",
                ),
            ]
        )
    plan.append(
        CategorySpec(
            key="staff",
            label="Staff",
            emoji="🛡️",
            channels=tuple(staff_channels),
            access="staff",
        )
    )
    return plan


def count_channels(plan: list[CategorySpec]) -> int:
    """Nombre total de salons du plan (hors catégories)."""
    return sum(len(category.channels) for category in plan)


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
def _bot_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        embed_links=True,
        attach_files=True,
        read_message_history=True,
        manage_messages=True,
    )


def channel_overwrites(
    guild: Any,
    spec: ChannelSpec,
    *,
    staff_role: Any | None = None,
    actor: Any | None = None,
) -> dict[Any, discord.PermissionOverwrite]:
    """Permissions à appliquer à un salon selon son niveau d'accès."""
    overwrites: dict[Any, discord.PermissionOverwrite] = {}
    default_role = getattr(guild, "default_role", None)
    me = getattr(guild, "me", None)

    if spec.access == "public":
        return overwrites

    if spec.access == "read_only":
        if default_role is not None:
            overwrites[default_role] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                add_reactions=True,
                create_public_threads=False,
            )
        if staff_role is not None:
            # Le staff publie les annonces et les giveaways dans ces salons.
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
            )
    elif spec.access == "staff":
        if default_role is not None:
            overwrites[default_role] = discord.PermissionOverwrite(view_channel=False)
        if staff_role is not None:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            )
        elif actor is not None:
            # Aucun rôle staff configuré : on garde au moins l'auteur du /build.
            overwrites[actor] = discord.PermissionOverwrite(view_channel=True)

    if me is not None:
        overwrites[me] = _bot_overwrite()
    return overwrites


# --------------------------------------------------------------------------- #
# Messages d'accueil
# --------------------------------------------------------------------------- #
def _intro_embed(bot: "VesparaBot", key: str) -> discord.Embed | None:
    brand = getattr(getattr(bot, "settings", None), "brand", "Vespara")
    if key == "regles":
        return None  # construit séparément (besoin du règlement enregistré)
    if key == "annonces":
        return embed(
            title=f"{EMOJI['megaphone']} Annonces",
            description=(
                "Retrouve ici **toutes les annonces officielles** du serveur : "
                "nouveautés, événements et informations importantes.\n\n"
                "Ce salon est en lecture seule — le staff y publie, tu n'as qu'à lire. 👀"
            ),
            color=COLOR_ANNOUNCE,
        )
    if key == "giveaways":
        return embed(
            title=f"{EMOJI['gift']} Giveaways",
            description=(
                "Les concours du serveur arrivent dans ce salon.\n\n"
                "Clique sur **Participer** sous un giveaway pour tenter ta chance, "
                "puis guette le tirage automatique. 🍀"
            ),
            color=COLOR_GIVEAWAY,
        )
    if key == "partenariats":
        return embed(
            title=f"{EMOJI['handshake']} Partenariats",
            description=(
                f"Nos serveurs partenaires sont présentés ici.\n\n"
                f"Tu veux apparaître dans cette liste ? Contacte l'équipe de {brand}."
            ),
            color=COLOR_INFO,
        )
    if key == "general":
        return embed(
            title=f"{EMOJI['wave']} Bienvenue sur {brand}",
            description=(
                f"Content de te voir ! Présente-toi, discute et n'hésite pas à passer "
                f"dans les autres salons.\n\n"
                f"{EMOJI['book']} Pense à lire le règlement avant de commencer."
            ),
            color=COLOR,
        )
    if key == "pings":
        return embed(
            title=f"{EMOJI['pin']} Rôles de notification",
            description=(
                "Réagis aux messages du staff pour recevoir (ou non) les pings :\n\n"
                f"{EMOJI['megaphone']} **Annonces** — nouveautés importantes\n"
                f"{EMOJI['gift']} **Giveaways** — tirages au sort\n"
                f"{EMOJI['party']} **Événements** — soirées et animations\n\n"
                "*Les réactions de ce salon sont gérées par le staff.*"
            ),
            color=COLOR,
        )
    if key == "medias":
        return embed(
            title=f"{EMOJI['sparkles']} Médias",
            description=(
                "Partage ici tes captures, clips et créations.\n\n"
                "Merci de respecter les droits d'auteur et de garder les contenus "
                "adaptés à tout public. 🎨"
            ),
            color=COLOR,
        )
    if key == "commandes":
        return embed(
            title=f"{EMOJI['bot']} Commandes du bot",
            description=(
                "Ce salon est fait pour utiliser les commandes — pas pour discuter. 🤖\n\n"
                "**Pour découvrir le bot**\n"
                "• `/menu` — le panneau principal\n"
                "• `/eco daily` — ta récompense journalière\n"
                "• `/casino accueil` — les jeux du casino\n"
                "• `/boule` — pose une question à la boule magique\n"
                "• `/invites lien` — le lien du serveur\n"
                "• `/rules` — relire le règlement\n\n"
                "*Les commandes de gestion (staff) restent invisibles pour les membres.*"
            ),
            color=COLOR,
        )
    if key == "niveaux":
        return embed(
            title=f"{EMOJI['chart']} Niveaux",
            description=(
                "Chaque message te rapporte de l'XP, et chaque palier débloque des "
                "récompenses (coins, rôles…). Les montées de niveau s'affichent ici.\n\n"
                "Consulte ta progression avec `/eco niveau`."
            ),
            color=COLOR,
        )
    if key == "casino":
        return embed(
            title=f"{EMOJI['dice']} Casino",
            description=(
                "Bienvenue à la table ! 🎲\n\n"
                "• `/casino blackjack` — affronte le croupier\n"
                "• `/casino slots` — la machine à sous\n"
                "• `/casino roulette` — rouge, noir ou un numéro\n"
                "• `/casino des` — le jeu de dés\n\n"
                "Joue responsable : les coins se gagnent avec `/eco daily` et `/eco work`."
            ),
            color=COLOR_GIVEAWAY,
        )
    if key == "staff":
        return embed(
            title=f"{EMOJI['shield']} Espace staff",
            description=(
                f"Ce salon n'est visible que par l'équipe de {brand}.\n\n"
                "**À faire après un `/build`**\n"
                "• `/staffrole` — déclarer le rôle staff\n"
                "• `/config salon-annonces` — vérifier le salon des annonces\n"
                "• `/vocal installer` — (re)générer les vocaux temporaires\n"
                "• `/eco-admin article-ajouter` — remplir la boutique\n"
                "• `/config reglement` — personnaliser le règlement"
            ),
            color=COLOR,
        )
    if key == "logs":
        return embed(
            title=f"{EMOJI['eye']} Salon de logs",
            description=(
                "Les événements du serveur seront consignés ici.\n\n"
                "*Le bot n'y écrit que les actions qu'il voit passer (commandes staff, "
                "giveaways, vocaux temporaires…). Pour les logs Discord complets "
                "(messages supprimés, sanctions), active **Journal d'audit** côté "
                "Paramètres du serveur → Journal d'audit.*"
            ),
            color=COLOR,
        )
    return None


def rules_intro_embed(bot: "VesparaBot", rules_text: str) -> discord.Embed:
    """Embed du salon règlement (repris par `/rules`)."""
    brand = getattr(getattr(bot, "settings", None), "brand", "Vespara")
    emb = embed(
        title=f"{EMOJI['book']} Règlement de {brand}",
        description=rules_text,
        color=COLOR,
    )
    emb.set_footer(text=f"{FOOTER} • En restant sur le serveur, tu acceptes ce règlement.")
    return emb


# --------------------------------------------------------------------------- #
# Recherche / création
# --------------------------------------------------------------------------- #
def _existing_by_name(channels: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for channel in channels or []:
        name = getattr(channel, "name", None)
        if isinstance(name, str):
            found.setdefault(name, channel)
    return found


async def _ensure_category(
    guild: Any,
    spec: CategorySpec,
    *,
    existing: dict[str, Any],
    result: BuildResult,
    reason: str,
    staff_role: Any | None,
    actor: Any | None,
) -> Any | None:
    name = format_category_name(spec.label, spec.emoji)
    category = existing.get(name)
    if category is not None:
        result.reused.append({"kind": "category", "name": name})
        return category

    overwrites: dict[Any, discord.PermissionOverwrite] = {}
    default_role = getattr(guild, "default_role", None)
    if spec.access == "staff" and default_role is not None:
        overwrites[default_role] = discord.PermissionOverwrite(view_channel=False)
        if staff_role is not None:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True)
        elif actor is not None:
            overwrites[actor] = discord.PermissionOverwrite(view_channel=True)

    try:
        category = await guild.create_category(name, overwrites=overwrites, reason=reason)
    except Exception as exc:  # noqa: BLE001 - on rapporte sans interrompre
        log.warning("Catégorie %s impossible : %s", name, exc)
        result.failed.append({"kind": "category", "name": name, "error": str(exc)})
        return None

    result.created.append({"kind": "category", "name": name})
    return category


async def _ensure_channel(
    guild: Any,
    spec: ChannelSpec,
    *,
    category: Any,
    existing: dict[str, Any],
    result: BuildResult,
    reason: str,
    staff_role: Any | None,
    actor: Any | None,
) -> tuple[Any | None, bool]:
    name = format_channel_name(spec.label, spec.emoji)
    channel = existing.get(name)
    if channel is not None:
        result.reused.append({"kind": spec.kind, "name": name})
        result.channels[spec.key] = channel
        return channel, False

    overwrites = channel_overwrites(guild, spec, staff_role=staff_role, actor=actor)
    try:
        if spec.kind == "voice":
            channel = await guild.create_voice_channel(
                name,
                category=category,
                overwrites=overwrites,
                reason=reason,
            )
        else:
            channel = await guild.create_text_channel(
                name,
                category=category,
                topic=spec.topic,
                overwrites=overwrites,
                reason=reason,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("Salon %s impossible : %s", name, exc)
        result.failed.append({"kind": spec.kind, "name": name, "error": str(exc)})
        return None, False

    result.created.append({"kind": spec.kind, "name": name})
    result.channels[spec.key] = channel
    # Discord limite la création de salons : on marque une petite pause pour
    # éviter de déclencher une longue série de 429.
    await asyncio.sleep(BUILD_DELAY)
    return channel, True


async def _publish_intro(
    bot: "VesparaBot",
    channel: Any,
    spec: ChannelSpec,
    rules_text: str,
) -> None:
    """Publie le message d'accueil d'un salon (best effort)."""
    if spec.intro is None:
        return
    if spec.intro == "regles":
        emb = rules_intro_embed(bot, rules_text)
    elif spec.intro == "vocal-hub":
        from .tempvoice import hub_embed

        emb = hub_embed(bot, channel)
    else:
        emb = _intro_embed(bot, spec.intro)
    if emb is None:
        return
    try:
        await channel.send(embed=emb)
    except Exception as exc:  # noqa: BLE001
        log.debug("Message d'accueil impossible dans %s : %s", getattr(channel, "name", "?"), exc)


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
async def build_server(
    bot: "VesparaBot",
    guild: Any,
    *,
    options: BuildOptions | None = None,
    actor: Any | None = None,
    reason: str = "Construction du serveur (/build)",
) -> BuildResult:
    """Crée (ou complète) le serveur décrit par :func:`build_plan`."""
    from ..checks import resolve_staff_role

    options = options or BuildOptions()
    result = BuildResult()
    plan = build_plan(options)

    me = getattr(guild, "me", None)
    permissions = getattr(me, "guild_permissions", None)
    if (
        me is not None
        and permissions is not None
        and not (permissions.manage_channels or permissions.administrator)
    ):
        result.error = (
            "Il me manque la permission **Gérer les salons** pour construire le serveur."
        )
        return result

    staff_role = resolve_staff_role(bot, guild)
    if staff_role is None:
        result.warnings.append(
            "Aucun rôle staff configuré : les salons privés sont visibles par les "
            "administrateurs uniquement. Définis-le avec `/staffrole`."
        )

    try:
        existing_categories = _existing_by_name(getattr(guild, "categories", []))
    except Exception:  # pragma: no cover - serveurs factices
        existing_categories = {}
    existing_text = _existing_by_name(getattr(guild, "text_channels", []))
    existing_voice = _existing_by_name(getattr(guild, "voice_channels", []))

    rules_text = (options.texte_regles or "").strip()
    if not rules_text:
        stored = bot.db.guild(guild.id).get("rules") if getattr(bot, "db", None) else None
        rules_text = str(stored).strip() if stored else SIMPLE_RULES

    for category_spec in plan:
        category = await _ensure_category(
            guild,
            category_spec,
            existing=existing_categories,
            result=result,
            reason=reason,
            staff_role=staff_role,
            actor=actor,
        )
        if category is None:
            continue

        for spec in category_spec.channels:
            pool = existing_voice if spec.kind == "voice" else existing_text
            channel, is_new = await _ensure_channel(
                guild,
                spec,
                category=category,
                existing=pool,
                result=result,
                reason=reason,
                staff_role=staff_role,
                actor=actor,
            )
            # Un salon réutilisé garde son contenu : on n'écrit que dans les nouveaux.
            if channel is not None and is_new:
                await _publish_intro(bot, channel, spec, rules_text)

    _apply_config(bot, guild, result, options, rules_text, actor)
    return result


def _apply_config(
    bot: "VesparaBot",
    guild: Any,
    result: BuildResult,
    options: BuildOptions,
    rules_text: str,
    actor: Any | None,
) -> None:
    """Enregistre les salons du build dans la configuration du serveur."""
    db = getattr(bot, "db", None)
    if db is None:  # pragma: no cover - bot factice
        return
    settings = db.guild(guild.id)

    for key, field_name in (
        ("annonces", "announce_channel_id"),
        ("niveaux", "levelup_channel_id"),
        ("casino", "casino_channel_id"),
    ):
        channel = result.channels.get(key)
        if channel is None:
            continue
        # On respecte une configuration déjà choisie par le staff.
        if settings.get(field_name):
            if int(settings[field_name]) != int(getattr(channel, "id", 0)):
                result.config[field_name] = "conservé"
            continue
        settings[field_name] = getattr(channel, "id", None)
        result.config[field_name] = getattr(channel, "mention", None)

    hub = result.channels.get("vocal-hub")
    if hub is not None and options.vocal:
        settings["voice_hub_id"] = getattr(hub, "id", None)
        settings["voice_hub_name"] = getattr(hub, "name", TEMPVOICE_HUB_NAME)
        category = getattr(hub, "category", None)
        settings["voice_category_id"] = getattr(category, "id", None)
        settings["voice_name_template"] = settings.get("voice_name_template") or TEMPVOICE_NAME_TEMPLATE
        settings["voice_limit"] = int(settings.get("voice_limit") or TEMPVOICE_DEFAULT_LIMIT)
        result.config["voice_hub_id"] = getattr(hub, "mention", None)

    if options.regles and not settings.get("rules"):
        settings["rules"] = rules_text
        result.config["rules"] = "règlement enregistré"

    settings["built_by"] = getattr(actor, "id", None)
    settings["build_version"] = BUILD_VERSION
    db.schedule_save(0.5)


# --------------------------------------------------------------------------- #
# Résumé / aperçu
# --------------------------------------------------------------------------- #
def plan_embed(plan: list[CategorySpec], *, brand: str = "Vespara") -> discord.Embed:
    """Aperçu lisible du plan (avant construction)."""
    emb = embed(
        title=f"{EMOJI['gear']} Aperçu de la construction",
        description=(
            f"Voici ce que `/build` va créer sur **{brand}** :\n"
            f"**{len(plan)} catégorie(s)** et **{count_channels(plan)} salon(s)**.\n\n"
            "*Les salons déjà présents ne seront pas dupliqués, ils seront réutilisés.*"
        ),
        color=COLOR,
    )
    for category in plan:
        lines = []
        for spec in category.channels:
            name = format_channel_name(spec.label, spec.emoji)
            icon = {"read_only": "🔒", "staff": "🛡️"}.get(spec.access, "👥")
            lines.append(f"{icon} {name}")
        emb.add_field(
            name=format_category_name(category.label, category.emoji),
            value="\n".join(lines)[:1024],
            inline=False,
        )
    emb.add_field(
        name="Légende",
        value="👥 tout le monde · 🔒 lecture seule · 🛡️ staff uniquement",
        inline=False,
    )
    emb.set_footer(text=f"{FOOTER} • Relance avec `apercu:False` pour construire")
    return emb


def result_embed(result: BuildResult, *, brand: str = "Vespara") -> discord.Embed:
    """Résumé d'une construction terminée."""
    if result.error:
        return embed(
            title=f"{EMOJI['error']} Construction impossible",
            description=result.error,
            color=0xED4245,
        )

    partial = result.failed_count > 0
    emb = embed(
        title=(
            f"{EMOJI['warning']} Serveur construit partiellement"
            if partial
            else f"{EMOJI['success']} Serveur construit"
        ),
        description=(
            f"**{brand}** est {'partiellement ' if partial else ''}prêt : "
            f"**{result.created_count}** élément(s) créé(s), "
            f"**{result.reused_count}** réutilisé(s)"
            + (f", **{result.failed_count}** échec(s)." if partial else ".")
            + (
                "\nVérifie mes permissions (**Gérer les salons**) puis relance `/build` "
                "pour compléter les éléments manquants."
                if partial
                else "\nTous les salons et permissions sont en place. 🎉"
            )
        ),
        color=0xFAA61A if partial else 0x3BA55D,
    )

    def _format(items: list[dict[str, str]], limit: int = 12) -> str:
        shown = [f"• {item['name']}" for item in items[:limit]]
        extra = len(items) - len(shown)
        if extra > 0:
            shown.append(f"*… et {extra} autre(s)*")
        return "\n".join(shown) or "—"

    if result.created:
        emb.add_field(name="Créés", value=_format(result.created)[:1024], inline=False)
    if result.reused:
        emb.add_field(name="Réutilisés", value=_format(result.reused)[:1024], inline=False)
    if result.failed:
        emb.add_field(name="Échecs", value=_format(result.failed)[:1024], inline=False)

    config = result.config
    if config:
        lines = []
        if config.get("announce_channel_id"):
            lines.append(f"• Annonces → {config['announce_channel_id']}")
        if config.get("levelup_channel_id"):
            lines.append(f"• Niveaux → {config['levelup_channel_id']}")
        if config.get("casino_channel_id"):
            lines.append(f"• Casino → {config['casino_channel_id']}")
        if config.get("voice_hub_id"):
            lines.append(f"• Générateur de vocaux → {config['voice_hub_id']}")
        if config.get("rules"):
            lines.append("• Règlement enregistré")
        if lines:
            emb.add_field(name="Configuration", value="\n".join(lines)[:1024], inline=False)

    if result.warnings:
        emb.add_field(
            name=f"{EMOJI['warning']} À savoir",
            value="\n".join(f"• {text}" for text in result.warnings)[:1024],
            inline=False,
        )

    emb.add_field(
        name="Et maintenant ?",
        value=(
            "• `/build apercu:True` — revoir le plan sans rien créer\n"
            "• `/build` — relancer pour compléter les salons manquants\n"
            "• `/staffrole` puis `/vocal installer` pour finaliser les vocaux"
        ),
        inline=False,
    )
    emb.set_footer(text=f"{FOOTER} • /build")
    return emb
