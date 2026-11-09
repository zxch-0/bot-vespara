"""Publication d'annonces : le bot parle simplement dans un salon (pas d'embed)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import is_staff, resolve_staff_role
from ..helpers import embed, error, reply_ephemeral
from ..ui.announcement import AnnouncementDraft, AnnouncementModal, AnnouncementPreview

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)

MENTION_CHOICES = [
    app_commands.Choice(name="Aucune mention", value="none"),
    app_commands.Choice(name="@everyone", value="everyone"),
    app_commands.Choice(name="@here", value="here"),
    app_commands.Choice(name="Rôle staff", value="staff"),
]


class Announcements(commands.Cog):
    """Annonces publiques : le bot envoie un message normal, comme si tu parlais à sa place."""

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

    @app_commands.command(name="annonce", description="Faire parler le bot dans un salon")
    @app_commands.describe(
        salon="Salon où envoyer le message (défaut : salon actuel ou salon d'annonces configuré)",
        mention="Mention à ajouter en tête du message",
        message="Contenu du message (si vide, un formulaire s'ouvre)",
    )
    @app_commands.choices(mention=MENTION_CHOICES)
    @app_commands.guild_only()
    @is_staff()
    async def annonce(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel | None = None,
        mention: app_commands.Choice[str] | None = None,
        message: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande disponible uniquement sur un serveur."))
            return

        settings = self.bot.db.guild(interaction.guild.id)
        configured = settings.get("announce_channel_id")
        channel = salon
        if channel is None and configured:
            ch = interaction.guild.get_channel(int(configured))
            if ch is not None:
                channel = ch  # type: ignore[assignment]
        if channel is None:
            channel = interaction.channel  # type: ignore[assignment]

        # Vérification souple : le salon doit pouvoir recevoir des messages
        if channel is None or not hasattr(channel, "send"):
            await reply_ephemeral(interaction, error("Choisis un salon textuel valide."))
            return

        # Vérification des permissions (ignorée en test si permissions_for n'existe pas)
        try:
            permissions = channel.permissions_for(interaction.guild.me)  # type: ignore[union-attr]
            if not permissions.send_messages:
                await reply_ephemeral(
                    interaction,
                    error(f"Il me manque la permission « Envoyer des messages » dans {channel.mention}."),
                )
                return
        except Exception:
            pass

        mention_text = self._mention_text(interaction, mention.value if mention else None)

        # Si un message est fourni directement → aperçu immédiat
        if message is not None:
            content = message.strip()
            if not content:
                await reply_ephemeral(interaction, error("Le message ne peut pas être vide."))
                return
            if len(content) > 2000 or (mention_text and len(content) + len(mention_text) + 1 > 2000):
                await reply_ephemeral(
                    interaction,
                    error(f"Le message est trop long ({len(content)} caractères, max 2000)."),
                )
                return

            draft = AnnouncementDraft(content=content)
            preview = AnnouncementPreview(
                self.bot,
                draft=draft,
                channel=channel,
                mention_text=mention_text,
                author_id=interaction.user.id,
            )
            preview_emb = embed(
                title=f"📢 Aperçu — salon {channel.mention}",
                description=content,
                color=0x8B5CF6,
            )
            if mention_text:
                preview_emb.add_field(name="Mention", value=mention_text, inline=False)
            preview_emb.set_footer(text="Ce message sera envoyé tel quel par le bot (sans embed).")

            await interaction.response.send_message(embed=preview_emb, view=preview, ephemeral=True)
            return

        # Sinon → on ouvre le formulaire
        modal = AnnouncementModal(
            self.bot,
            channel=channel,
            mention_text=mention_text,
        )
        await interaction.response.send_modal(modal)


async def setup(bot: "VesparaBot") -> None:
    await bot.add_cog(Announcements(bot))
