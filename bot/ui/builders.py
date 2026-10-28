"""Construction des embeds "vitrine" du bot (menu et commandes utilitaires)."""

from __future__ import annotations

import platform
import resource
from typing import TYPE_CHECKING

import discord

from .. import __version__
from ..constants import (
    COLOR,
    COLOR_GIVEAWAY,
    COLOR_INFO,
    COLOR_MUTED,
    DEFAULT_RULES,
    EMOJI,
    FOOTER,
)
from ..helpers import (
    accent_color,
    animated_progress,
    embed,
    full_timestamp,
    humanize_duration,
    timestamp,
    truncate,
    utcnow,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

VERIFICATION_LABELS = {
    discord.VerificationLevel.none: "Aucune",
    discord.VerificationLevel.low: "Faible",
    discord.VerificationLevel.medium: "Moyenne",
    discord.VerificationLevel.high: "Élevée",
    discord.VerificationLevel.highest: "Maximale",
}


# --------------------------------------------------------------------------- #
# Membre
# --------------------------------------------------------------------------- #
def profile_embed(member: discord.Member | discord.User, *, detailed: bool = False) -> discord.Embed:
    user = member
    emb = embed(
        title=f"{EMOJI['wave']} {user.display_name}",
        description=discord.utils.escape_markdown(str(user)),
        color=getattr(getattr(member, "color", None), "value", COLOR) or COLOR,
        thumbnail=user.display_avatar.url,
    )
    if isinstance(member, discord.Member):
        roles = [role for role in reversed(member.roles) if role != member.guild.default_role]
        top_role = member.top_role.mention if member.top_role != member.guild.default_role else "Aucun"
        emb.add_field(name="Identifiant", value=f"`{user.id}`", inline=True)
        emb.add_field(name="Surnom", value=member.nick or "—", inline=True)
        emb.add_field(name="Rôle principal", value=top_role, inline=True)
        emb.add_field(name="Compte créé", value=timestamp(user.created_at), inline=True)
        if member.joined_at:
            emb.add_field(name="A rejoint", value=timestamp(member.joined_at), inline=True)
        emb.add_field(
            name=f"Rôles ({len(roles)})",
            value=truncate(" ".join(role.mention for role in roles[:12]), 1000) or "Aucun",
            inline=False,
        )
        if detailed:
            emb.add_field(
                name="Permissions clés",
                value=truncate(
                    ", ".join(
                        label
                        for label, flag in (
                            ("Administrateur", "administrator"),
                            ("Gérer le serveur", "manage_guild"),
                            ("Gérer les messages", "manage_messages"),
                            ("Gérer les rôles", "manage_roles"),
                            ("Expulser", "kick_members"),
                            ("Bannir", "ban_members"),
                        )
                        if getattr(member.guild_permissions, flag)
                    )
                    or "Aucune permission notable",
                    900,
                ),
                inline=False,
            )
    else:
        emb.add_field(name="Identifiant", value=f"`{user.id}`", inline=True)
        emb.add_field(name="Compte créé", value=timestamp(user.created_at), inline=True)

    emb.set_footer(text=FOOTER, icon_url=getattr(user, "display_avatar", None) and user.display_avatar.url)
    return emb


# --------------------------------------------------------------------------- #
# Serveur
# --------------------------------------------------------------------------- #
def server_embed(guild: discord.Guild, *, detailed: bool = False) -> discord.Embed:
    humans = sum(1 for member in guild.members if not member.bot)
    bots = guild.member_count - humans if guild.member_count else 0
    owner = guild.owner.mention if guild.owner else f"<@{guild.owner_id}>"

    emb = embed(
        title=f"{EMOJI['leaf']} {guild.name}",
        description=guild.description or "Aucune description définie.",
        color=COLOR,
        thumbnail=guild.icon.url if guild.icon else None,
    )
    emb.add_field(name="Propriétaire", value=owner, inline=True)
    emb.add_field(name="Identifiant", value=f"`{guild.id}`", inline=True)
    emb.add_field(name="Créé le", value=full_timestamp(guild.created_at), inline=True)
    emb.add_field(
        name="Membres",
        value=f"{guild.member_count or '?'} au total\n{humans} humains · {max(0, bots)} bots",
        inline=True,
    )
    emb.add_field(
        name="Salons",
        value=f"{len(guild.text_channels)} textuels\n{len(guild.voice_channels)} vocaux",
        inline=True,
    )
    emb.add_field(name="Rôles", value=str(len(guild.roles)), inline=True)
    boost_count = guild.premium_subscription_count or 0
    emb.add_field(
        name="Boosts",
        value=f"Niveau {guild.premium_tier} · {boost_count} boost{'s' if boost_count > 1 else ''}",
        inline=True,
    )
    emb.add_field(
        name="Vérification",
        value=VERIFICATION_LABELS.get(guild.verification_level, "Inconnue"),
        inline=True,
    )
    if detailed:
        emb.add_field(
            name="Fonctionnalités",
            value=truncate(", ".join(feature.replace("_", " ").title() for feature in guild.features) or "Aucune", 900),
            inline=False,
        )
        if guild.rules_channel:
            emb.add_field(name="Salon des règles", value=guild.rules_channel.mention, inline=True)
        if guild.afk_channel:
            emb.add_field(name="Salon AFK", value=guild.afk_channel.mention, inline=True)
        if guild.banner:
            emb.set_image(url=guild.banner.url)

    emb.set_footer(text=FOOTER, icon_url=guild.icon.url if guild.icon else None)
    return emb


def roles_embed(guild: discord.Guild) -> discord.Embed:
    roles = [role for role in guild.roles if role != guild.default_role]
    roles.sort(key=lambda role: role.position, reverse=True)

    lines = []
    for role in roles[:25]:
        count = len(role.members)
        line = f"{role.mention} — `{role.id}` · {count} membre{'s' if count > 1 else ''}"
        if role.hoist:
            line += " · épinglé"
        lines.append(line)

    emb = embed(
        title=f"{EMOJI['crown']} Rôles de {guild.name}",
        description="\n".join(lines) or "Aucun rôle personnalisé.",
        color=COLOR_INFO,
        thumbnail=guild.icon.url if guild.icon else None,
    )
    if len(roles) > 25:
        emb.set_footer(text=f"{FOOTER} • {len(roles) - 25} rôles supplémentaires masqués")
    else:
        emb.set_footer(text=FOOTER)
    return emb


# --------------------------------------------------------------------------- #
# Règlement / giveaways
# --------------------------------------------------------------------------- #
def rules_embed(bot: "VesparaBot", guild: discord.Guild) -> discord.Embed:
    rules = bot.db.guild(guild.id).get("rules") or DEFAULT_RULES
    emb = embed(
        title=f"{EMOJI['book']} Règlement de {bot.settings.brand}",
        description=rules,
        color=COLOR,
        thumbnail=guild.icon.url if guild.icon else None,
    )
    emb.set_footer(text=f"{FOOTER} • En restant sur le serveur, tu acceptes ce règlement.")
    return emb


def giveaways_embed(bot: "VesparaBot", guild: discord.Guild) -> discord.Embed:
    now = utcnow().timestamp()
    active = bot.db.guild_giveaways(guild.id)
    if not active:
        return embed(
            title=f"{EMOJI['gift']} Giveaways",
            description="Aucun giveaway en cours pour le moment.\nReviens vite, ça arrive ! 👀",
            color=COLOR_GIVEAWAY,
        )

    lines = []
    for gw in active[:10]:
        jump = f"https://discord.com/channels/{guild.id}/{gw.get('channel_id')}/{gw.get('message_id')}"
        entries = len(gw.get("entries", []))
        start = float(gw.get("started_at") or now)
        end = float(gw.get("ends_at") or now)
        ratio = (now - start) / (end - start) if end > start else 1.0
        lines.append(
            f"{EMOJI['party']} **[{truncate(gw['prize'], 60)}]({jump})**\n"
            f"　　{animated_progress(1 - ratio, 10)} {entries} participant"
            f"{'s' if entries > 1 else ''}\n"
            f"　　{EMOJI['clock']} se termine {timestamp(gw.get('ends_at'))}"
        )

    return embed(
        title=f"{EMOJI['gift']} Giveaways en cours",
        description="\n\n".join(lines),
        color=COLOR_GIVEAWAY,
        accent="givaway",
        icon=EMOJI["sparkles"],
    )


def voice_info_embed(bot: "VesparaBot", guild: discord.Guild) -> discord.Embed:
    """Explique comment obtenir un vocal personnel (bouton du menu)."""
    settings = bot.db.guild(guild.id)
    hub_id = settings.get("voice_hub_id")
    hub = guild.get_channel(int(hub_id)) if hub_id else None
    rooms = bot.db.guild_voice_rooms(guild.id)

    if hub is None:
        return embed(
            title=f"{EMOJI['mic']} Vocaux temporaires",
            description=(
                "Les vocaux personnels ne sont pas encore activés sur ce serveur.\n"
                "Un membre du staff peut les installer avec `/vocal installer`."
            ),
            color=COLOR_MUTED,
        )

    emb = embed(
        title=f"{EMOJI['mic']} Ton vocal, en un clic",
        description=(
            f"Rejoins le salon **{hub.name}** ({hub.mention}) et je te crée "
            "instantanément un vocal personnel.\n\n"
            "**Dans le salon créé**, un panneau apparaît dans le chat pour :\n"
            "• renommer le vocal ;\n"
            "• limiter le nombre de places ;\n"
            "• le verrouiller ou le rendre privé ;\n"
            "• expulser ou autoriser des membres ;\n"
            "• transférer la propriété ou supprimer le salon.\n\n"
            "Le salon est supprimé automatiquement dès qu'il est vide. 🍃"
        ),
        color=COLOR,
        thumbnail=guild.icon.url if guild.icon else None,
    )
    emb.add_field(name="Salon générateur", value=hub.mention, inline=True)
    emb.add_field(name="Vocaux ouverts", value=str(len(rooms)), inline=True)
    emb.set_footer(text=FOOTER)
    return emb


# --------------------------------------------------------------------------- #
# Bot / menu
# --------------------------------------------------------------------------- #
def bot_info_embed(bot: "VesparaBot") -> discord.Embed:
    uptime = bot.uptime
    stats = bot.db.stats()
    try:
        memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Mo (Linux)
    except Exception:  # pragma: no cover
        memory = 0.0

    latency = getattr(bot, "latency_ms", 0)
    health = (
        f"{EMOJI['success']} excellente"
        if 0 < latency < 120
        else (f"{EMOJI['warning']} correcte" if latency < 300 else f"{EMOJI['error']} dégradée")
        if latency
        else f"{EMOJI['clock']} connexion en cours"
    )
    emb = embed(
        title=f"{EMOJI['bot']} {bot.settings.brand}",
        description=(
            f"### *{bot.settings.tagline}*\n"
            f"Giveaways, annonces, réponses automatiques, vocaux temporaires, "
            f"économie et casino — tout en un.\n\u200b"
        ),
        color=COLOR,
        accent="violet",
        thumbnail=bot.user.display_avatar.url if bot.user else None,
        icon=EMOJI["bot"],
    )
    emb.add_field(name="Version", value=f"`{__version__}`", inline=True)
    emb.add_field(name="Latence", value=f"`{latency} ms` · {health}", inline=True)
    emb.add_field(name="En ligne depuis", value=humanize_duration(uptime), inline=True)
    emb.add_field(name="Serveurs", value=f"**{len(bot.guilds)}**", inline=True)
    emb.add_field(
        name="Commandes",
        value=f"**{getattr(bot, 'command_count', None) or len(bot.tree.get_commands())}**",
        inline=True,
    )
    emb.add_field(name="Mémoire", value=f"{memory:.0f} Mo", inline=True)
    emb.add_field(
        name=f"{EMOJI['gift']} Giveaways",
        value=f"{stats['active_giveaways']} en cours",
        inline=True,
    )
    emb.add_field(
        name=f"{EMOJI['mic']} Vocaux",
        value=f"{stats.get('voice_rooms', 0)} ouvert(s)",
        inline=True,
    )
    emb.add_field(
        name=f"{EMOJI['users']} Comptes éco",
        value=f"{stats.get('accounts', 0)}",
        inline=True,
    )
    emb.add_field(
        name="Stack",
        value=f"Python {platform.python_version()} · discord.py {discord.__version__}",
        inline=False,
    )
    emb.set_footer(text=f"{FOOTER} • {guild_footer(bot)}")
    return emb


def guild_footer(bot: "VesparaBot") -> str:
    count = len(bot.guilds)
    return f"{count} serveur{'s' if count > 1 else ''}"


def menu_embed(bot: "VesparaBot", guild: discord.Guild) -> discord.Embed:
    """Panneau d'accueil : carte de visite animée du serveur."""
    settings = bot.settings
    stats = bot.db.stats()
    emb = embed(
        title=f"{EMOJI['leaf']} {settings.brand}",
        description=(
            f"### Bienvenue sur **{settings.brand}**\n"
            f"*{settings.tagline}* 🍃\n\n"
            "Clique sur un bouton ci-dessous pour explorer le serveur en un clin d'œil."
        ),
        color=accent_color("violet"),
        thumbnail=guild.icon.url if guild.icon else None,
        accent="violet",
        icon=EMOJI["sparkles"],
    )
    emb.add_field(
        name=f"{EMOJI['tools']} Découverte",
        value=(
            "`/menu` · ce panneau\n"
            "`/rules` · le règlement\n"
            "`/userinfo` · fiche d'un membre\n"
            "`/serverinfo` · infos du serveur\n"
            "`/roleinfo` · détails d'un rôle"
        ),
        inline=True,
    )
    emb.add_field(
        name=f"{EMOJI['gift']} Animation",
        value=(
            "`/giveaways` · giveaways en cours\n"
            "`/boule` · boule magique 🎱\n"
            "`/casino accueil` · jeux de coins\n"
            "`/eco daily` · récompense du jour"
        ),
        inline=True,
    )
    emb.add_field(
        name=f"{EMOJI['mic']} Ton espace",
        value=(
            "Rejoins le salon **vocaux** pour obtenir ton vocal personnel,\n"
            "puis gère-le directement depuis le panneau du salon créé."
        ),
        inline=False,
    )
    emb.add_field(
        name=f"{EMOJI['chart']} Le serveur en chiffres",
        value=(
            f"{EMOJI['users']} **{guild.member_count or '?'}** membres · "
            f"{EMOJI['gift']} **{stats['active_giveaways']}** giveaway(s) · "
            f"{EMOJI['mic']} **{stats.get('voice_rooms', 0)}** vocal(aux)"
        ),
        inline=False,
    )
    emb.set_footer(
        text=f"{FOOTER} • {guild.member_count or '?'} membres",
        icon_url=guild.icon.url if guild.icon else None,
    )
    return emb
