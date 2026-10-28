"""Pagination de plusieurs embeds dans un même message."""

from __future__ import annotations

import discord

from ..helpers import error


class Paginator(discord.ui.View):
    """Affiche une liste d'embeds avec des boutons de navigation."""

    def __init__(
        self,
        pages: list[discord.Embed],
        *,
        author_id: int,
        timeout: float = 180.0,
        show_close: bool = True,
    ) -> None:
        super().__init__(timeout=timeout)
        if not pages:
            raise ValueError("Aucune page à afficher.")
        self.pages = pages
        self.author_id = author_id
        self.index = 0

        self.first_button = discord.ui.Button(emoji="⏮️", style=discord.ButtonStyle.secondary)
        self.prev_button = discord.ui.Button(emoji="◀️", style=discord.ButtonStyle.secondary)
        self.page_button = discord.ui.Button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
        self.next_button = discord.ui.Button(emoji="▶️", style=discord.ButtonStyle.secondary)
        self.last_button = discord.ui.Button(emoji="⏭️", style=discord.ButtonStyle.secondary)
        self.close_button = discord.ui.Button(emoji="🗑️", style=discord.ButtonStyle.danger)

        self.first_button.callback = self._go_first  # type: ignore[method-assign]
        self.prev_button.callback = self._go_prev  # type: ignore[method-assign]
        self.next_button.callback = self._go_next  # type: ignore[method-assign]
        self.last_button.callback = self._go_last  # type: ignore[method-assign]
        self.close_button.callback = self._close  # type: ignore[method-assign]

        for item in (self.first_button, self.prev_button, self.page_button, self.next_button, self.last_button):
            self.add_item(item)
        if show_close:
            self.add_item(self.close_button)

        self._refresh()

    # ------------------------------------------------------------------ #
    @property
    def page(self) -> discord.Embed:
        return self.pages[self.index]

    def _refresh(self) -> None:
        single = len(self.pages) <= 1
        self.page_button.label = f"{self.index + 1}/{len(self.pages)}"
        self.first_button.disabled = single or self.index == 0
        self.prev_button.disabled = single or self.index == 0
        self.next_button.disabled = single or self.index >= len(self.pages) - 1
        self.last_button.disabled = single or self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=error("Utilise ta propre commande pour naviguer dans cette liste."), ephemeral=True
            )
            return False
        return True

    async def _navigate(self, interaction: discord.Interaction, index: int) -> None:
        self.index = index
        self._refresh()
        await interaction.response.edit_message(embed=self.page, view=self)

    async def _go_first(self, interaction: discord.Interaction) -> None:
        await self._navigate(interaction, 0)

    async def _go_prev(self, interaction: discord.Interaction) -> None:
        await self._navigate(interaction, max(0, self.index - 1))

    async def _go_next(self, interaction: discord.Interaction) -> None:
        await self._navigate(interaction, min(len(self.pages) - 1, self.index + 1))

    async def _go_last(self, interaction: discord.Interaction) -> None:
        await self._navigate(interaction, len(self.pages) - 1)

    async def _close(self, interaction: discord.Interaction) -> None:
        self.stop()
        try:
            await interaction.message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            await interaction.response.defer()
