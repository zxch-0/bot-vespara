"""Petites commandes utiles pour tous les membres."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..constants import COLOR, COLOR_INFO, EMOJI
from ..helpers import (
    embed,
    error,
    humanize_duration,
    reply_ephemeral,
    truncate,
)
from ..ui.builders import (
    bot_info_embed,
    giveaways_embed,
    profile_embed,
    rules_embed,
    server_embed,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)

PERMISSION_LABELS = {
    "administrator": "Administrateur",
    "manage_guild": "Gérer le serveur",
    "manage_roles": "Gérer les rôles",
    "manage_channels": "Gérer les salons",
    "manage_messages": "Gérer les messages",
    "kick_members": "Expulser des membres",
    "ban_members": "Bannir des membres",
    "moderate_members": "Exclure temporairement",
    "mention_everyone": "Mentionner @everyone",
    "manage_webhooks": "Gérer les webhooks",
    "manage_events": "Gérer les événements",
    "view_audit_log": "Voir les logs d'audit",
}

AVATAR_FORMATS = ("png", "jpg", "webp")


class Utilities(commands.Cog):
    """Commandes publiques affichées dans le menu."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot

    # ------------------------------------------------------------------ #
    # État du bot
    # ------------------------------------------------------------------ #
    @app_commands.command(name="ping", description="Afficher la latence du bot")
    async def ping(self, interaction: discord.Interaction) -> None:
        started = time.perf_counter()
        emb = embed(
            title=f"{EMOJI['chart']} Pong !",
            description="Calcul de la latence…",
            color=COLOR_INFO,
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)
        elapsed = (time.perf_counter() - started) * 1000

        final = embed(
            title=f"{EMOJI['chart']} Pong !",
            color=COLOR_INFO,
        )
        final.add_field(name="Websocket", value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)
        final.add_field(name="Aller-retour API", value=f"`{elapsed:.0f} ms`", inline=True)
        final.add_field(name="En ligne depuis", value=humanize_duration(self.bot.uptime), inline=True)
        await interaction.edit_original_response(embed=final)

    @app_commands.command(name="botinfo", description="Informations sur le bot Vespara")
    async def botinfo(self, interaction: discord.Interaction) -> None:
        await reply_ephemeral(interaction, bot_info_embed(self.bot))

    # ------------------------------------------------------------------ #
    # Membres
    # ------------------------------------------------------------------ #
    @app_commands.command(name="userinfo", description="Afficher la fiche d'un membre")
    @app_commands.describe(membre="Membre à consulter (défaut : toi)")
    @app_commands.guild_only()
    async def userinfo(
        self, interaction: discord.Interaction, membre: discord.Member | None = None
    ) -> None:
        target = membre or interaction.user
        if not isinstance(target, discord.Member):
            await reply_ephemeral(interaction, error("Membre introuvable sur ce serveur."))
            return
        await reply_ephemeral(interaction, profile_embed(target, detailed=True))

    @app_commands.command(name="avatar", description="Afficher l'avatar d'un membre")
    @app_commands.describe(membre="Membre concerné (défaut : toi)")
    async def avatar(
        self, interaction: discord.Interaction, membre: discord.User | None = None
    ) -> None:
        target = membre or interaction.user

        emb = embed(
            title=f"🖼️ Avatar de {target.display_name}",
            description=f"[Ouvrir en grand]({target.display_avatar.with_size(1024).url})",
            color=COLOR,
            image=target.display_avatar.with_size(1024).url,
        )

        view = discord.ui.View(timeout=180)
        for fmt in AVATAR_FORMATS:
            view.add_item(
                discord.ui.Button(
                    label=fmt.upper(),
                    style=discord.ButtonStyle.link,
                    url=target.display_avatar.with_format(fmt).with_size(1024).url,
                )
            )

        if isinstance(target, discord.Member):
            guild_avatar = target.guild_avatar
            if guild_avatar is not None:
                emb.add_field(
                    name="Avatar du serveur",
                    value=f"[Voir l'avatar de serveur]({guild_avatar.with_size(1024).url})",
                    inline=False,
                )
                view.add_item(
                    discord.ui.Button(
                        label="Avatar du serveur",
                        emoji="🏰",
                        style=discord.ButtonStyle.link,
                        url=guild_avatar.with_size(1024).url,
                    )
                )

        await interaction.response.send_message(embed=emb, view=view, ephemeral=True)

    @app_commands.command(name="banner", description="Afficher la bannière d'un membre")
    @app_commands.describe(membre="Membre concerné (défaut : toi)")
    async def banner(
        self, interaction: discord.Interaction, membre: discord.User | None = None
    ) -> None:
        target = membre or interaction.user
        banner = getattr(target, "banner", None)
        if banner is None:
            try:
                target = await self.bot.fetch_user(target.id)
                banner = target.banner
            except (discord.NotFound, discord.HTTPException):
                banner = None

        if banner is None:
            await reply_ephemeral(
                interaction, error(f"**{target.display_name}** n'a pas de bannière de profil.")
            )
            return

        emb = embed(
            title=f"🎨 Bannière de {target.display_name}",
            description=f"[Ouvrir en grand]({banner.with_size(1024).url})",
            color=COLOR,
            image=banner.with_size(1024).url,
        )
        view = discord.ui.View(timeout=180)
        for fmt in AVATAR_FORMATS:
            view.add_item(
                discord.ui.Button(
                    label=fmt.upper(),
                    style=discord.ButtonStyle.link,
                    url=banner.with_format(fmt).with_size(1024).url,
                )
            )
        await interaction.response.send_message(embed=emb, view=view, ephemeral=True)

    # ------------------------------------------------------------------ #
    # Serveur
    # ------------------------------------------------------------------ #
    @app_commands.command(name="serverinfo", description="Afficher les informations du serveur")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande disponible uniquement sur un serveur."))
            return
        await reply_ephemeral(interaction, server_embed(interaction.guild, detailed=True))

    @app_commands.command(name="roleinfo", description="Afficher les détails d'un rôle")
    @app_commands.describe(role="Rôle à consulter")
    @app_commands.guild_only()
    async def roleinfo(self, interaction: discord.Interaction, role: discord.Role) -> None:
        permissions = [
            label for flag, label in PERMISSION_LABELS.items() if getattr(role.permissions, flag, False)
        ]
        color_value = role.color.value if role.color.value else COLOR

        emb = embed(
            title=f"{EMOJI['shield']} {role.name}",
            description=role.mention,
            color=color_value,
        )
        emb.add_field(name="Identifiant", value=f"`{role.id}`", inline=True)
        emb.add_field(name="Couleur", value=f"`{str(role.color)}`", inline=True)
        emb.add_field(name="Position", value=f"#{role.position}", inline=True)
        emb.add_field(name="Membres", value=str(len(role.members)), inline=True)
        emb.add_field(name="Mentionnable", value="Oui" if role.mentionable else "Non", inline=True)
        emb.add_field(name="Affiché séparément", value="Oui" if role.hoist else "Non", inline=True)
        emb.add_field(
            name="Créé le", value=discord.utils.format_dt(role.created_at, "R"), inline=True
        )
        emb.add_field(name="Géré par une intégration", value="Oui" if role.managed else "Non", inline=True)
        emb.add_field(name="Permissions clés", value=truncate(", ".join(permissions) or "Aucune", 900), inline=False)
        await reply_ephemeral(interaction, emb)

    @app_commands.command(name="rules", description="Afficher le règlement du serveur")
    @app_commands.guild_only()
    async def rules(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande disponible uniquement sur un serveur."))
            return
        await reply_ephemeral(interaction, rules_embed(self.bot, interaction.guild))

    @app_commands.command(name="giveaways", description="Voir les giveaways en cours")
    @app_commands.guild_only()
    async def giveaways(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande disponible uniquement sur un serveur."))
            return
        await reply_ephemeral(interaction, giveaways_embed(self.bot, interaction.guild))


async def setup(bot: "VesparaBot") -> None:
    await bot.add_cog(Utilities(bot))
