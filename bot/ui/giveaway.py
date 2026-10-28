"""Vues persistantes attachées aux messages de giveaway."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from ..constants import EMOJI
from ..helpers import embed, error, reply_ephemeral, success
from .common import ConfirmView

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

CUSTOM_ID_PREFIX = "vespara:gw"


class GiveawayView(discord.ui.View):
    """Boutons Participer / Quitter / Participants d'un giveaway.

    La vue est persistante : elle est ré-enregistrée au démarrage pour que les
    boutons des messages déjà envoyés continuent de fonctionner.
    """

    def __init__(self, bot: "VesparaBot", giveaway_id: str, *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.giveaway_id = str(giveaway_id)

        self.join_button = discord.ui.Button(
            label="Participer",
            emoji=EMOJI["party"],
            style=discord.ButtonStyle.success,
            custom_id=f"{CUSTOM_ID_PREFIX}:join:{self.giveaway_id}",
            disabled=disabled,
        )
        self.leave_button = discord.ui.Button(
            label="Quitter",
            emoji=EMOJI["door"],
            style=discord.ButtonStyle.secondary,
            custom_id=f"{CUSTOM_ID_PREFIX}:leave:{self.giveaway_id}",
            disabled=disabled,
        )
        self.participants_button = discord.ui.Button(
            label="Participants",
            emoji=EMOJI["users"],
            style=discord.ButtonStyle.secondary,
            custom_id=f"{CUSTOM_ID_PREFIX}:list:{self.giveaway_id}",
            disabled=disabled,
        )

        self.join_button.callback = self._join  # type: ignore[method-assign]
        self.leave_button.callback = self._leave  # type: ignore[method-assign]
        self.participants_button.callback = self._participants  # type: ignore[method-assign]

        for item in (self.join_button, self.leave_button, self.participants_button):
            self.add_item(item)

    # ------------------------------------------------------------------ #
    def _manager(self):
        manager = getattr(self.bot, "giveaway_manager", None)
        if manager is None:
            raise RuntimeError("Le module giveaways n'est pas chargé.")
        return manager

    async def _join(self, interaction: discord.Interaction) -> None:
        await self._manager().join(interaction, self.giveaway_id)

    async def _leave(self, interaction: discord.Interaction) -> None:
        await self._manager().leave(interaction, self.giveaway_id)

    async def _participants(self, interaction: discord.Interaction) -> None:
        await self._manager().show_participants(interaction, self.giveaway_id)


class RerollView(discord.ui.View):
    """Bouton de relance affiché avec l'annonce des gagnants (staff uniquement)."""

    def __init__(self, bot: "VesparaBot", giveaway_id: str) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.giveaway_id = str(giveaway_id)

        self.reroll_button = discord.ui.Button(
            label="Relancer le tirage",
            emoji=EMOJI["dice"],
            style=discord.ButtonStyle.secondary,
            custom_id=f"{CUSTOM_ID_PREFIX}:reroll:{self.giveaway_id}",
        )
        self.reroll_button.callback = self._reroll  # type: ignore[method-assign]
        self.add_item(self.reroll_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        from ..checks import is_admin_member, resolve_staff_role_id

        member = interaction.user
        if not isinstance(member, discord.Member) or interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur le serveur."))
            return False

        allowed = await is_admin_member(interaction)
        if not allowed:
            role_id = resolve_staff_role_id(self.bot, interaction.guild)
            allowed = bool(role_id) and any(role.id == role_id for role in member.roles)
        if not allowed:
            await reply_ephemeral(
                interaction, error("Seul le staff peut relancer le tirage d'un giveaway.")
            )
            return False
        return True

    async def _reroll(self, interaction: discord.Interaction) -> None:
        manager = getattr(self.bot, "giveaway_manager", None)
        if manager is None:
            await reply_ephemeral(interaction, error("Module giveaways indisponible."))
            return

        gw = manager.get(self.giveaway_id)
        if gw is None:
            await reply_ephemeral(interaction, error("Ce giveaway n'existe plus dans la base."))
            return
        if not gw.get("ended"):
            await reply_ephemeral(interaction, error("Ce giveaway n'est pas encore terminé."))
            return

        confirm = ConfirmView(author_id=interaction.user.id, confirm_label="Relancer", danger=False)
        accepted = await confirm.prompt(
            interaction,
            embed(
                title="Relancer le tirage ?",
                description=(
                    f"De nouveaux gagnants seront tirés pour **{gw['prize']}** "
                    "parmi les participants."
                ),
            ),
        )
        if not accepted:
            return
        count = int(gw.get("winners_count", 1))
        winners = await manager.reroll(gw, count, actor=interaction.user)
        if winners:
            await interaction.followup.send(
                embed=success(f"Nouveau tirage effectué : {' '.join(f'<@{uid}>' for uid in winners)}"),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                embed=error("Impossible de relancer : aucun autre participant disponible."),
                ephemeral=True,
            )
