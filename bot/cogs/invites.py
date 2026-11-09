"""Invitations du serveur : lien, statistiques et classement des inviters (`/invites`)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..helpers import error, reply_ephemeral
from ..ui.invites import (
    count_by_inviter,
    invite_link_embed,
    leaderboard_embeds,
    pick_invite,
    ranked,
    stats_embed,
    usable,
)
from ..ui.paginator import Paginator

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)

# Nombre maximum de membres affichés au classement.
MAX_CLASSIFIED = 100


# --------------------------------------------------------------------------- #
# Groupe /invites (tout le monde)
# --------------------------------------------------------------------------- #
@app_commands.guild_only()
class InvitesGroup(app_commands.Group, name="invites", description="Lien d'invitation, statistiques et classement"):
    def __init__(self, cog: "Invites") -> None:
        super().__init__()
        self.cog = cog

    # ------------------------------------------------------------------ #
    async def fetch_invites(self, interaction: discord.Interaction) -> list[Any] | None:
        """Invitations du serveur, ou `None` après un message d'erreur.

        La liste des invitations d'un serveur exige la permission
        **Gérer le serveur** : c'est Discord qui la restreint, pas le bot.
        """
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return None
        try:
            return await interaction.guild.invites()
        except discord.Forbidden:
            await reply_ephemeral(
                interaction,
                error(
                    "Je n'ai pas la permission **Gérer le serveur**, indispensable pour "
                    "lister les invitations du serveur.\n"
                    "Accorde-la à mon rôle puis réessaie.",
                    title="Invitations indisponibles",
                ),
            )
            return None
        except discord.HTTPException as exc:
            log.warning("Invitations du serveur %s indisponibles : %s", interaction.guild.id, exc)
            await reply_ephemeral(
                interaction,
                error("Impossible de récupérer les invitations du serveur. Réessaie plus tard."),
                title="Invitations indisponibles",
            )
            return None

    async def _send_pages(self, interaction: discord.Interaction, pages: list[discord.Embed]) -> None:
        view = Paginator(pages, author_id=interaction.user.id)
        if interaction.response.is_done():
            await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="lien", description="Afficher le lien d'invitation du serveur")
    async def lien(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        invites = await self.fetch_invites(interaction)
        if invites is None:
            return

        invite = pick_invite(invites)
        if invite is None:
            await reply_ephemeral(
                interaction,
                error(
                    "Aucune invitation active n'existe sur ce serveur.\n"
                    "Clique sur le **nom du serveur** (en haut du salon) → "
                    "**Inviter des amis** pour en créer une.",
                    title="Aucun lien trouvé",
                ),
            )
            return
        await reply_ephemeral(interaction, invite_link_embed(interaction.guild, invite))

    @app_commands.command(name="classement", description="Top des membres qui ont le plus invité")
    async def classement(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        invites = await self.fetch_invites(interaction)
        if invites is None:
            return

        counts = count_by_inviter(invites)
        entries = ranked(interaction.guild, counts)[:MAX_CLASSIFIED]
        pages = leaderboard_embeds(interaction.guild, entries, total_invites=sum(counts.values()))
        await self._send_pages(interaction, pages)

    @app_commands.command(name="stats", description="Tes invitations (ou celles d'un membre)")
    @app_commands.describe(membre="Membre à consulter (défaut : toi)")
    async def stats(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        invites = await self.fetch_invites(interaction)
        if invites is None:
            return

        target = membre or interaction.user
        counts = count_by_inviter(invites)
        entries = ranked(interaction.guild, counts)
        count = counts.get(target.id, 0)
        rank = next(
            (index + 1 for index, (member, _) in enumerate(entries) if member.id == target.id), None
        )
        invite_url = next(
            (
                str(invite.url)
                for invite in invites
                if usable(invite)
                and invite.inviter is not None
                and invite.inviter.id == target.id
            ),
            None,
        )
        await reply_ephemeral(
            interaction,
            stats_embed(
                interaction.guild,
                target,
                count=count,
                rank=rank,
                ranked_count=len(entries),
                invite_url=invite_url,
            ),
        )


# --------------------------------------------------------------------------- #
# Cog
# --------------------------------------------------------------------------- #
class Invites(commands.Cog):
    """Lien d'invitation, statistiques et classement des inviters."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self.group = InvitesGroup(self)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command("invites")


async def setup(bot: "VesparaBot") -> None:
    cog = Invites(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.group, override=True)


__all__ = ["Invites", "MAX_CLASSIFIED"]
