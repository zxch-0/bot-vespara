"""Menu communautaire : panneau de boutons pour les membres."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..helpers import error, reply_ephemeral
from ..ui.builders import menu_embed
from ..ui.menu import MenuView

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot


class CommunityMenu(commands.Cog):
    """Affiche le menu du serveur, en éphémère pour ne pas spammer les salons."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot

    @app_commands.command(name="menu", description="Afficher le menu du serveur Vespara")
    @app_commands.guild_only()
    async def menu(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Le menu est disponible uniquement sur un serveur."))
            return

        emb = menu_embed(self.bot, interaction.guild)
        await interaction.response.send_message(embed=emb, view=MenuView(self.bot), ephemeral=True)


async def setup(bot: "VesparaBot") -> None:
    await bot.add_cog(CommunityMenu(bot))
