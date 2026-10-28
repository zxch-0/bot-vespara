"""Vues génériques réutilisables."""

from __future__ import annotations

import discord

from ..helpers import error


class ConfirmView(discord.ui.View):
    """Petit bouton Confirmer / Annuler, utilisable via `await view.prompt(...)`."""

    def __init__(
        self,
        *,
        author_id: int,
        confirm_label: str = "Confirmer",
        cancel_label: str = "Annuler",
        confirm_emoji: str = "✅",
        cancel_emoji: str = "✖️",
        danger: bool = True,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None

        self.confirm_button = discord.ui.Button(
            label=confirm_label,
            emoji=confirm_emoji,
            style=discord.ButtonStyle.danger if danger else discord.ButtonStyle.success,
        )
        self.cancel_button = discord.ui.Button(
            label=cancel_label, emoji=cancel_emoji, style=discord.ButtonStyle.secondary
        )
        self.confirm_button.callback = self._on_confirm  # type: ignore[method-assign]
        self.cancel_button.callback = self._on_cancel  # type: ignore[method-assign]
        self.add_item(self.confirm_button)
        self.add_item(self.cancel_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=error("Cette confirmation ne t'appartient pas."), ephemeral=True
            )
            return False
        return True

    async def _on_confirm(self, interaction: discord.Interaction) -> None:
        self.value = True
        self._disable()
        await interaction.response.edit_message(view=self)
        self.stop()

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        self.value = False
        self._disable()
        await interaction.response.edit_message(view=self)
        self.stop()

    def _disable(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    async def on_timeout(self) -> None:
        self.value = None

    # ------------------------------------------------------------------ #
    async def prompt(self, interaction: discord.Interaction, embed: discord.Embed) -> bool | None:
        """Envoie la confirmation en éphémère et attend la réponse."""
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=self, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
        await self.wait()
        return self.value
