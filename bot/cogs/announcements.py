"""Publication d'annonces (staff uniquement), avec aperçu avant envoi."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import is_staff, resolve_staff_role
from ..constants import ANNOUNCE_COLORS, COLOR_ANNOUNCE
from ..helpers import error, reply_ephemeral
from ..ui.announcement import AnnouncementModal

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)

MENTION_CHOICES = [
    app_commands.Choice(name="Aucune mention", value="none"),
    app_commands.Choice(name="@everyone", value="everyone"),
    app_commands.Choice(name="@here", value="here"),
    app_commands.Choice(name="Rôle staff", value="staff"),
]

COLOR_CHOICES = [
    app_commands.Choice(name=name.capitalize(), value=name) for name in ANNOUNCE_COLORS
]


def _valid_image_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class Announcements(commands.Cog):
    """Annonces publiques avec aperçu, mention optionnelle et couleur."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot

    # ------------------------------------------------------------------ #
    def _mention_text(
        self, interaction: discord.Interaction, choice: str | None
    ) -> str | None:
        choice = (choice or "none").lower()
        if choice == "everyone":
            return "@everyone"
        if choice == "here":
            return "@here"
        if choice == "staff" and interaction.guild is not None:
            role = resolve_staff_role(self.bot, interaction.guild)
            return role.mention if role else None
        return None

    @app_commands.command(name="annonce", description="Publier une annonce sur le serveur")
    @app_commands.describe(
        salon="Salon où publier (défaut : salon actuel ou salon d'annonces configuré)",
        mention="Mention à ajouter au message",
        couleur="Couleur de l'embed",
        image="URL d'une image à afficher",
    )
    @app_commands.choices(mention=MENTION_CHOICES, couleur=COLOR_CHOICES)
    @app_commands.guild_only()
    @is_staff()
    async def annonce(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel | None = None,
        mention: app_commands.Choice[str] | None = None,
        couleur: app_commands.Choice[str] | None = None,
        image: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande disponible uniquement sur un serveur."))
            return

        settings = self.bot.db.guild(interaction.guild.id)
        configured = settings.get("announce_channel_id")
        channel = salon
        if channel is None and configured:
            channel = interaction.guild.get_channel(int(configured))  # type: ignore[assignment]
        if channel is None:
            channel = interaction.channel  # type: ignore[assignment]

        if not isinstance(channel, discord.TextChannel):
            await reply_ephemeral(interaction, error("Choisis un salon textuel valide."))
            return

        permissions = channel.permissions_for(interaction.guild.me)
        if not permissions.send_messages or not permissions.embed_links:
            await reply_ephemeral(
                interaction,
                error(
                    f"Il me manque les permissions « Envoyer des messages » et "
                    f"« Intégrer des liens » dans {channel.mention}."
                ),
            )
            return

        if image and not _valid_image_url(image):
            await reply_ephemeral(
                interaction, error("Le lien de l'image doit commencer par `http://` ou `https://`.")
            )
            return

        color = ANNOUNCE_COLORS.get(couleur.value, COLOR_ANNOUNCE) if couleur else COLOR_ANNOUNCE
        mention_text = self._mention_text(interaction, mention.value if mention else None)

        modal = AnnouncementModal(
            self.bot,
            channel=channel,
            mention_text=mention_text,
            color=color,
            image_url=image,
        )
        await interaction.response.send_modal(modal)


async def setup(bot: "VesparaBot") -> None:
    await bot.add_cog(Announcements(bot))
