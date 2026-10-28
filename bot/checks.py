"""Vérifications d'accès (rôle staff, administrateur, serveur uniquement)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

import discord
from discord import app_commands

from .constants import EMOJI

if TYPE_CHECKING:  # pragma: no cover
    from .main import VesparaBot

log = logging.getLogger(__name__)


class StaffOnly(app_commands.CheckFailure):
    """Le membre n'a pas le rôle staff configuré (ni admin)."""

    def __init__(self) -> None:
        super().__init__("Cette commande est réservée à l'équipe du serveur.")


class AdminOnly(app_commands.CheckFailure):
    """Le membre n'est pas administrateur."""

    def __init__(self) -> None:
        super().__init__("Cette commande est réservée aux administrateurs du serveur.")


# --------------------------------------------------------------------------- #
# Résolution du rôle staff
# --------------------------------------------------------------------------- #
def resolve_staff_role_id(bot: "VesparaBot", guild: discord.Guild | None) -> int | None:
    """Cherche le rôle staff : config du serveur d'abord, puis variable d'env."""
    if guild is not None and getattr(bot, "db", None) is not None:
        role_id = bot.db.guild(guild.id).get("staff_role_id")
        if role_id:
            return int(role_id)
    return bot.settings.staff_role_id


def resolve_staff_role(bot: "VesparaBot", guild: discord.Guild) -> discord.Role | None:
    role_id = resolve_staff_role_id(bot, guild)
    if role_id is None:
        return None
    return guild.get_role(role_id)


async def _is_bot_owner(bot: discord.Client, user: discord.abc.User) -> bool:
    try:
        return await bot.is_owner(user)
    except Exception:  # pragma: no cover - réseau
        return False


async def is_admin_member(interaction: discord.Interaction) -> bool:
    """True si l'auteur est administrateur du serveur ou propriétaire du bot."""
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    return await _is_bot_owner(interaction.client, member)


# --------------------------------------------------------------------------- #
# Décorateurs
# --------------------------------------------------------------------------- #
def is_staff() -> Callable[[app_commands.Command], app_commands.Command]:
    """Autorise uniquement le rôle staff (ou les admins / owner du bot)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise app_commands.NoPrivateMessage()
        member = interaction.user
        if not isinstance(member, discord.Member):
            raise StaffOnly()

        if await is_admin_member(interaction):
            return True

        bot: "VesparaBot" = interaction.client  # type: ignore[assignment]
        role_id = resolve_staff_role_id(bot, interaction.guild)
        if role_id is None:
            # Aucun rôle staff configuré : on laisse passer les modérateurs pour
            # qu'ils puissent effectuer la configuration initiale.
            if member.guild_permissions.manage_guild:
                return True
            raise StaffOnly()

        if any(role.id == role_id for role in member.roles):
            return True
        raise StaffOnly()

    return app_commands.check(predicate)


def is_server_admin() -> Callable[[app_commands.Command], app_commands.Command]:
    """Autorise uniquement les administrateurs (ou le propriétaire du bot)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise app_commands.NoPrivateMessage()
        if await is_admin_member(interaction):
            return True
        raise AdminOnly()

    return app_commands.check(predicate)


def staff_role_has_visibility_permission(bot: "VesparaBot", role: discord.Role) -> bool:
    """Le rôle possède-t-il la permission utilisée pour révéler les commandes staff ?"""
    permission = bot.settings.staff_permission
    if permission == "administrator":
        return role.permissions.administrator
    return bool(getattr(role.permissions, permission, False) or role.permissions.administrator)


async def command_visibility_notice(bot: "VesparaBot", guild: discord.Guild, *, detailed: bool = False) -> str:
    """Message d'aide expliquant la visibilité des commandes staff."""
    role = resolve_staff_role(bot, guild)
    permission = bot.settings.staff_permission_label

    if role is None:
        text = (
            f"{EMOJI['warning']} Aucun rôle staff n'est configuré : utilise "
            "`/staffrole` (administrateur) ou la variable d'environnement `STAFF_ROLE_ID`."
        )
        if detailed:
            text += (
                "\n\nTant qu'aucun rôle n'est défini, les commandes staff restent "
                "accessibles aux membres ayant la permission **Gérer le serveur**."
            )
        return text

    if not staff_role_has_visibility_permission(bot, role):
        text = (
            f"{EMOJI['warning']} Le rôle {role.mention} n'a pas la permission "
            f"**{permission}** : ses membres ne verront pas les commandes staff."
        )
        if detailed:
            text += (
                "\n\nDeux solutions :\n"
                f"• Accordé la permission **{permission}** au rôle {role.mention} ;\n"
                f"• Ou définis manuellement les permissions des commandes dans "
                f"**Paramètres du serveur → Intégrations → {bot.settings.brand}**."
            )
        return text

    text = (
        f"{EMOJI['success']} Rôle staff : {role.mention} — seuls ses membres voient et "
        f"utilisent les commandes staff (visibilité liée à **{permission}**)."
    )
    if detailed:
        text += (
            "\n\n*Discord ne permet pas à un bot de lier la visibilité d'une commande à "
            "un rôle précis. Les commandes sont donc masquées aux membres qui n'ont pas "
            "cette permission, et le bot vérifie en plus le rôle à chaque utilisation.*"
        )
    return text
