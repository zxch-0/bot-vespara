"""Menu communautaire (panneau persistant) du serveur Vespara."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from ..constants import EMOJI
from ..helpers import reply_error
from .builders import (
    bot_info_embed,
    giveaways_embed,
    menu_embed,
    profile_embed,
    roles_embed,
    rules_embed,
    server_embed,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

CUSTOM_ID_PREFIX = "vespara:menu"


class MenuView(discord.ui.View):
    """Panneau de boutons accessible à tous les membres du serveur."""

    def __init__(self, bot: "VesparaBot") -> None:
        super().__init__(timeout=None)
        self.bot = bot

        definitions = (
            ("profile", "Mon profil", "👤", self.show_profile),
            ("server", "Le serveur", "🏰", self.show_server),
            ("roles", "Rôles", "🎭", self.show_roles),
            ("giveaways", "Giveaways", EMOJI["gift"], self.show_giveaways),
            ("rules", "Règlement", EMOJI["book"], self.show_rules),
            ("bot", "Le bot", EMOJI["bot"], self.show_bot),
        )
        for index, (key, label, emoji, callback) in enumerate(definitions):
            button = discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.primary if key == "profile" else discord.ButtonStyle.secondary,
                custom_id=f"{CUSTOM_ID_PREFIX}:{key}",
                row=0 if index < 5 else 1,
            )
            button.callback = callback  # type: ignore[method-assign]
            self.add_item(button)

    # ------------------------------------------------------------------ #
    async def _guild(self, interaction: discord.Interaction) -> discord.Guild | None:
        if interaction.guild is None:
            await reply_error(interaction, "Ce menu ne fonctionne que sur un serveur.")
            return None
        return interaction.guild

    async def show_profile(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=profile_embed(interaction.user), ephemeral=True
        )

    async def show_server(self, interaction: discord.Interaction) -> None:
        guild = await self._guild(interaction)
        if guild is None:
            return
        await interaction.response.send_message(embed=server_embed(guild), ephemeral=True)

    async def show_roles(self, interaction: discord.Interaction) -> None:
        guild = await self._guild(interaction)
        if guild is None:
            return
        await interaction.response.send_message(embed=roles_embed(guild), ephemeral=True)

    async def show_giveaways(self, interaction: discord.Interaction) -> None:
        guild = await self._guild(interaction)
        if guild is None:
            return
        await interaction.response.send_message(embed=giveaways_embed(self.bot, guild), ephemeral=True)

    async def show_rules(self, interaction: discord.Interaction) -> None:
        guild = await self._guild(interaction)
        if guild is None:
            return
        await interaction.response.send_message(embed=rules_embed(self.bot, guild), ephemeral=True)

    async def show_bot(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=bot_info_embed(self.bot), ephemeral=True)


def panel_embed(bot: "VesparaBot", guild: discord.Guild) -> discord.Embed:
    """Embed du panneau public publié avec /config menu."""
    return menu_embed(bot, guild)
