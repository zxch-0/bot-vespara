"""Casino : blackjack, machine à sous, roulette et dés (`/casino …`)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..constants import (
    CASINO_DICE_PAYOUTS,
    CASINO_ROULETTE_PAYOUTS,
    EMOJI,
)
from ..helpers import embed, error, gradient_color, reply_ephemeral, warning
from ..services.casino import (
    BlackjackSession,
    casino_games,
    dice_table,
    normalize_dice_bet,
    normalize_roulette_bet,
    roll_dice,
    roulette_table,
    spin_roulette,
    spin_slots,
)
from ..services.economy import (
    EconomyError,
    EconomyManager,
    InsufficientFunds,
)
from ..ui.casino import (
    BlackjackView,
    CasinoView,
    animate_slots,
    blackjack_embed,
    casino_home_embed,
    dice_embed,
    roulette_embed,
    slots_embed,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)


class Casino(commands.Cog):
    """Jeux d'argent : coins gagnés et perdus, sans argent réel."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self.casino = CasinoGroup(self)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.casino.name)

    @property
    def manager(self) -> EconomyManager:
        economy = getattr(self.bot, "economy", None)
        if economy is None:  # pragma: no cover - le cog économie doit être chargé
            raise RuntimeError("Le module d'économie n'est pas chargé.")
        return economy

    # ------------------------------------------------------------------ #
    # Garde-fou : salon du casino (facultatif)
    # ------------------------------------------------------------------ #
    def allowed_here(self, interaction: discord.Interaction) -> bool:
        """Le casino peut être restreint à un salon via `/eco-admin parametres`."""
        guild = interaction.guild
        if guild is None:
            return False
        channel_id = self.bot.db.guild(guild.id).get("casino_channel_id")
        if not channel_id:
            return True
        return getattr(interaction, "channel_id", None) == int(channel_id)

    def _guard(self) -> discord.Embed:
        return error(
            "Le casino est uniquement accessible dans le salon dédié. "
            "Le staff peut le changer avec `/eco-admin parametres`.",
            title="Mauvais salon",
        )

    # ------------------------------------------------------------------ #
    # Jeux (mutualisés entre les commandes)
    # ------------------------------------------------------------------ #
    async def play_slots(self, interaction: discord.Interaction, mise: int) -> None:
        guild_id, user_id = interaction.guild.id, interaction.user.id  # type: ignore[union-attr]
        try:
            self.manager.bet(guild_id, user_id, int(mise), game="slots")
        except EconomyError as exc:
            await reply_ephemeral(interaction, error(str(exc), title="Mise refusée"))
            return

        await interaction.response.send_message(
            embed=slots_embed(("🎰", "🎰", "🎰"), int(mise), spinning=True), ephemeral=True
        )
        message = await interaction.original_response()
        await animate_slots(message, int(mise))

        result = spin_slots(int(mise))
        if result.payout:
            self.manager.payout(guild_id, user_id, result.payout, bet=result.bet)
        else:
            self.manager.count_game(guild_id, user_id)

        with contextlib.suppress(discord.HTTPException):
            await message.edit(
                embed=slots_embed(
                    result.reels,
                    result.bet,
                    payout=result.payout,
                    label=result.label,
                    balance=self.manager.balance(guild_id, user_id),
                )
            )

    async def play_roulette(self, interaction: discord.Interaction, mise: int, pari: str) -> None:
        try:
            bet_kind, number = normalize_roulette_bet(pari)
        except ValueError as exc:
            await reply_ephemeral(
                interaction,
                error(f"{exc}\n\n**Paris disponibles**\n{roulette_table()}", title="Pari invalide"),
            )
            return
        if bet_kind == "nombre" and (number is None or not 0 <= number <= 36):
            await reply_ephemeral(interaction, error("Le numéro doit être entre 0 et 36."))
            return

        guild_id, user_id = interaction.guild.id, interaction.user.id  # type: ignore[union-attr]
        try:
            self.manager.bet(guild_id, user_id, int(mise), game="roulette")
        except EconomyError as exc:
            await reply_ephemeral(interaction, error(str(exc), title="Mise refusée"))
            return

        await interaction.response.send_message(
            embed=embed(
                title=f"{EMOJI['dice']} Roulette",
                description="🎡 *La bille tourne…*",
                color=gradient_color("menthe", 0.2),
            ),
            ephemeral=True,
        )
        message = await interaction.original_response()
        await asyncio.sleep(1.1)

        result = spin_roulette(int(mise), bet_kind, number)
        if result.payout:
            self.manager.payout(guild_id, user_id, result.payout, bet=result.stake)
        else:
            self.manager.count_game(guild_id, user_id)

        with contextlib.suppress(discord.HTTPException):
            await message.edit(
                embed=roulette_embed(result, balance=self.manager.balance(guild_id, user_id))
            )

    async def play_dice(self, interaction: discord.Interaction, mise: int, pari: str) -> None:
        try:
            bet_kind = normalize_dice_bet(pari)
        except ValueError as exc:
            await reply_ephemeral(
                interaction,
                error(f"{exc}\n\n**Paris disponibles**\n{dice_table()}", title="Pari invalide"),
            )
            return

        guild_id, user_id = interaction.guild.id, interaction.user.id  # type: ignore[union-attr]
        try:
            self.manager.bet(guild_id, user_id, int(mise), game="dés")
        except EconomyError as exc:
            await reply_ephemeral(interaction, error(str(exc), title="Mise refusée"))
            return

        await interaction.response.send_message(
            embed=embed(
                title=f"{EMOJI['dice']} Dés",
                description="🎲 *Les dés roulent…*",
                color=gradient_color("menthe", 0.2),
            ),
            ephemeral=True,
        )
        message = await interaction.original_response()
        await asyncio.sleep(0.9)

        result = roll_dice(int(mise), bet_kind)
        if result.payout:
            self.manager.payout(guild_id, user_id, result.payout, bet=result.stake)
        else:
            self.manager.count_game(guild_id, user_id)

        with contextlib.suppress(discord.HTTPException):
            await message.edit(
                embed=dice_embed(result, balance=self.manager.balance(guild_id, user_id))
            )


# --------------------------------------------------------------------------- #
# Groupe /casino
# --------------------------------------------------------------------------- #
@app_commands.guild_only()
class CasinoGroup(app_commands.Group, name="casino", description="Jouer ses coins au casino"):
    def __init__(self, cog: Casino) -> None:
        super().__init__()
        self.cog = cog

    @property
    def manager(self) -> EconomyManager:
        return self.cog.manager

    # ------------------------------------------------------------------ #
    @app_commands.command(name="accueil", description="Découvrir les jeux du casino")
    async def accueil(self, interaction: discord.Interaction) -> None:
        if not self.cog.allowed_here(interaction):
            await reply_ephemeral(interaction, self.cog._guard())
            return
        balance = self.manager.balance(interaction.guild.id, interaction.user.id)  # type: ignore[union-attr]
        await interaction.response.send_message(
            embed=casino_home_embed(self.cog.bot, interaction.guild, balance),
            view=CasinoView(self.cog.bot, interaction.guild, interaction.user.id),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    @app_commands.command(name="blackjack", description="Jouer une main de blackjack contre le croupier")
    @app_commands.describe(mise="Coins misés (10 à 50 000)")
    async def blackjack(
        self,
        interaction: discord.Interaction,
        mise: app_commands.Range[int, 10, 50_000],
    ) -> None:
        if not self.cog.allowed_here(interaction):
            await reply_ephemeral(interaction, self.cog._guard())
            return
        guild = interaction.guild
        assert guild is not None  # garanti par @app_commands.guild_only()
        manager = self.manager

        try:
            manager.bet(guild.id, interaction.user.id, int(mise), game="blackjack")
        except InsufficientFunds as exc:
            await reply_ephemeral(interaction, error(str(exc), title="Solde insuffisant"))
            return
        except EconomyError as exc:
            await reply_ephemeral(interaction, error(str(exc)))
            return

        session = BlackjackSession.start(int(mise))
        if session.finished and session.payout:
            # Blackjack naturel : le gain est versé immédiatement.
            manager.payout(guild.id, interaction.user.id, session.payout, bet=session.bet)

        balance = manager.balance(guild.id, interaction.user.id)
        view = BlackjackView(self.cog.bot, manager, session, interaction.user, guild)
        await interaction.response.send_message(
            embed=blackjack_embed(session, member=interaction.user, balance=balance),
            view=view,
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    @app_commands.command(name="slots", description="Tourner la machine à sous")
    @app_commands.describe(mise="Coins misés (10 à 50 000)")
    async def slots(
        self,
        interaction: discord.Interaction,
        mise: app_commands.Range[int, 10, 50_000],
    ) -> None:
        if not self.cog.allowed_here(interaction):
            await reply_ephemeral(interaction, self.cog._guard())
            return
        await self.cog.play_slots(interaction, int(mise))

    # ------------------------------------------------------------------ #
    @app_commands.command(name="roulette", description="Miser sur un tour de roulette européenne")
    @app_commands.describe(
        mise="Coins misés (10 à 50 000)",
        pari="rouge, noir, pair, impair, bas, haut, vert ou un numéro (0-36)",
    )
    async def roulette(
        self,
        interaction: discord.Interaction,
        mise: app_commands.Range[int, 10, 50_000],
        pari: str,
    ) -> None:
        if not self.cog.allowed_here(interaction):
            await reply_ephemeral(interaction, self.cog._guard())
            return
        await self.cog.play_roulette(interaction, int(mise), pari)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="des", description="Miser sur un lancer de deux dés")
    @app_commands.describe(
        mise="Coins misés (10 à 50 000)",
        pari="pair, impair, sept, double, haut ou bas",
    )
    async def des(
        self,
        interaction: discord.Interaction,
        mise: app_commands.Range[int, 10, 50_000],
        pari: str,
    ) -> None:
        if not self.cog.allowed_here(interaction):
            await reply_ephemeral(interaction, self.cog._guard())
            return
        await self.cog.play_dice(interaction, int(mise), pari)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="jeux", description="Liste des jeux et de leurs gains")
    async def jeux(self, interaction: discord.Interaction) -> None:
        emb = embed(
            title=f"{EMOJI['dice']} Jeux du casino",
            description="Voici les jeux disponibles et les multiplicateurs de gain.",
            color=gradient_color("menthe", 0.3),
            accent="menthe",
        )
        for game in casino_games().values():
            emb.add_field(
                name=game["name"],
                value=f"{game['description']}\n`{game['command']}`",
                inline=False,
            )
        emb.add_field(
            name=f"🎡 Roulette ({len(CASINO_ROULETTE_PAYOUTS)} paris)",
            value=roulette_table(),
            inline=False,
        )
        emb.add_field(
            name=f"🎲 Dés ({len(CASINO_DICE_PAYOUTS)} paris)",
            value=dice_table(),
            inline=False,
        )
        emb.set_footer(text="Vespara • Casino • joue responsable 🍀")
        await reply_ephemeral(interaction, emb)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="mise-max", description="Miser tout ton solde sur un jeu")
    @app_commands.describe(jeu="Jeu choisi (par défaut : machine à sous)", pari="Pari (roulette/dés)")
    @app_commands.choices(
        jeu=[
            app_commands.Choice(name="🎰 Machine à sous", value="slots"),
            app_commands.Choice(name="🎡 Roulette", value="roulette"),
            app_commands.Choice(name="🎲 Dés", value="des"),
        ]
    )
    async def mise_max(
        self,
        interaction: discord.Interaction,
        jeu: app_commands.Choice[str] | None = None,
        pari: str | None = None,
    ) -> None:
        if not self.cog.allowed_here(interaction):
            await reply_ephemeral(interaction, self.cog._guard())
            return
        balance = self.manager.balance(interaction.guild.id, interaction.user.id)  # type: ignore[union-attr]
        if balance < 10:
            await reply_ephemeral(
                interaction,
                warning(
                    "Tu n'as pas assez de coins : récupère ta récompense avec `/eco daily`.",
                    title="Coffre vide",
                ),
            )
            return

        mise = min(balance, 50_000)
        choice = jeu.value if jeu else "slots"
        if choice == "roulette":
            await self.cog.play_roulette(interaction, mise, pari or "rouge")
        elif choice == "des":
            await self.cog.play_dice(interaction, mise, pari or "pair")
        else:
            await self.cog.play_slots(interaction, mise)

async def setup(bot: "VesparaBot") -> None:
    cog = Casino(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.casino, override=True)


__all__ = ["Casino", "CasinoGroup"]
