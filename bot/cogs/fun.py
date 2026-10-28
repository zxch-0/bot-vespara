"""Boule magique 🎱 : commande publique avec bouton « secouer à nouveau »."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..constants import (
    MAGIC8BALL_COOLDOWN,
    MAGIC8BALL_MAX_LENGTH,
    MAGIC8BALL_MIN_LENGTH,
)
from ..services.magic_ball import answer_embed, draw_answer, shake_embed
from ..ui.ball import MagicBallView

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

SHAKE_DELAY = 1.1  # secondes de suspense avant la réponse


class Fun(commands.Cog):
    """Commandes fun du serveur."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot

    # ------------------------------------------------------------------ #
    async def _ask(self, interaction: discord.Interaction, question: str) -> None:
        """Affiche la boule qui se secoue puis révèle la réponse."""
        await interaction.response.defer(thinking=True)

        try:
            await interaction.edit_original_response(embed=shake_embed(question))
        except discord.HTTPException:
            pass
        await asyncio.sleep(SHAKE_DELAY)

        answer = draw_answer()
        emb = answer_embed(question, answer, author=interaction.user)
        view = MagicBallView(question=question, author_id=interaction.user.id)
        try:
            await interaction.edit_original_response(embed=emb, view=view)
        except discord.HTTPException:  # pragma: no cover - message supprimé
            await interaction.followup.send(embed=emb, view=view)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="boule", description="Poser une question à la boule magique 🎱")
    @app_commands.describe(question="La question que tu veux poser à la boule")
    @app_commands.checks.cooldown(1, MAGIC8BALL_COOLDOWN, key=lambda i: (i.guild_id, i.user.id))
    async def boule(
        self,
        interaction: discord.Interaction,
        question: app_commands.Range[str, MAGIC8BALL_MIN_LENGTH, MAGIC8BALL_MAX_LENGTH],
    ) -> None:
        await self._ask(interaction, question)

    @app_commands.command(name="8ball", description="Magic 8-ball : pose une question, la boule répond 🎱")
    @app_commands.describe(question="La question que tu veux poser à la boule")
    @app_commands.checks.cooldown(1, MAGIC8BALL_COOLDOWN, key=lambda i: (i.guild_id, i.user.id))
    async def eight_ball(
        self,
        interaction: discord.Interaction,
        question: app_commands.Range[str, MAGIC8BALL_MIN_LENGTH, MAGIC8BALL_MAX_LENGTH],
    ) -> None:
        await self._ask(interaction, question)


async def setup(bot: "VesparaBot") -> None:
    await bot.add_cog(Fun(bot))
