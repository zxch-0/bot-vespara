"""Bouton « secouer à nouveau » de la boule magique."""

from __future__ import annotations

import asyncio
import time

import discord

from ..constants import MAGIC8BALL_EMOJI
from ..helpers import error, reply_ephemeral
from ..services.magic_ball import answer_embed, draw_answer, shake_embed

SHAKE_DELAY = 1.0
BUTTON_COOLDOWN = 1.5


class MagicBallView(discord.ui.View):
    """Permet de relancer la boule sans retaper la question."""

    def __init__(self, *, question: str, author_id: int, timeout: float = 180.0) -> None:
        super().__init__(timeout=timeout)
        self.question = question
        self.author_id = author_id
        self._last_press = 0.0

        self.shake_button = discord.ui.Button(
            label="Secouer à nouveau",
            emoji=MAGIC8BALL_EMOJI,
            style=discord.ButtonStyle.secondary,
        )
        self.shake_button.callback = self._shake_again  # type: ignore[method-assign]
        self.add_item(self.shake_button)

    # ------------------------------------------------------------------ #
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await reply_ephemeral(
                interaction,
                error("Cette boule n'est pas la tienne : pose ta propre question avec `/boule`."),
            )
            return False
        return True

    async def _shake_again(self, interaction: discord.Interaction) -> None:
        now = time.monotonic()
        if now - self._last_press < BUTTON_COOLDOWN:
            await reply_ephemeral(interaction, error("Doucement ! Laisse la boule se remettre."))
            return
        self._last_press = now

        try:
            await interaction.response.edit_message(embed=shake_embed(self.question), view=self)
        except discord.HTTPException:  # pragma: no cover - message supprimé
            return
        await asyncio.sleep(SHAKE_DELAY)

        answer = draw_answer()
        emb = answer_embed(self.question, answer, author=interaction.user)
        try:
            await interaction.edit_original_response(embed=emb, view=self)
        except discord.HTTPException:  # pragma: no cover - message supprimé
            pass
