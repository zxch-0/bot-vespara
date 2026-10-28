"""Vues et rendus animés du casino (blackjack, machine à sous, roulette, dés)."""

from __future__ import annotations

import asyncio
import contextlib
import random
from typing import TYPE_CHECKING, Any

import discord

from ..constants import (
    CASINO_BLACKJACK_NATURAL,
    CASINO_BLACKJACK_PAYOUT,
    CASINO_SLOTS_PAYOUTS,
    COLOR_CASINO,
    COLOR_LEGENDARY,
    COLOR_WARNING,
    EMOJI,
    SLOT_SYMBOLS,
    SPARKLES,
)
from ..helpers import embed, error, gradient_color
from ..services.casino import (
    BlackjackSession,
    casino_games,
    hand_value,
    render_hand,
)
from ..services.economy import EconomyManager, format_coins

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot


# --------------------------------------------------------------------------- #
# Embeds
# --------------------------------------------------------------------------- #
def casino_home_embed(bot: "VesparaBot", guild: discord.Guild | None, balance: int) -> discord.Embed:
    """Accueil du casino avec le catalogue des jeux."""
    emb = embed(
        title=f"{EMOJI['dice']} Casino Vespara",
        description=(
            f"{SPARKLES[0]} Bienvenue à la table ! Ton solde : **{format_coins(balance)}**\n"
            "Choisis un jeu ci-dessous, mise raisonnablement et tente la chance. 🍀\n\u200b"
        ),
        color=gradient_color("menthe", 0.15),
        accent="menthe",
        icon=EMOJI["dice"],
    )
    for game in casino_games().values():
        emb.add_field(name=game["name"], value=f"{game['description']}\n`{game['command']}`", inline=False)
    emb.add_field(
        name="💡 Bon à savoir",
        value=(
            "• Les mises vont de 10 à 50 000 coins.\n"
            "• Gains, pertes et parties sont suivis dans `/eco profil`.\n"
            "• Les parties de blackjack ne durent que le temps du message."
        ),
        inline=False,
    )
    emb.set_footer(text=f"Vespara • Casino • {getattr(bot.settings, 'tagline', 'Le serveur chill')}")
    return emb


def blackjack_embed(
    session: BlackjackSession,
    *,
    member: Any,
    balance: int,
    title_icon: str = "🃏",
) -> discord.Embed:
    """Table de blackjack : mains, mise et résultat éventuel."""
    if session.finished:
        color = {
            "blackjack": COLOR_LEGENDARY,
            "player": COLOR_CASINO,
            "push": COLOR_WARNING,
            "dealer": 0x64748B,
            "bust": 0xEF4444,
            "surrender": 0x94A3B8,
        }.get(session.outcome, COLOR_CASINO)
    else:
        color = gradient_color("menthe", 0.35)

    emb = embed(
        title=f"{title_icon} Blackjack — mise {format_coins(session.bet)}",
        description=f"{session.player_view()}\n\u200b",
        color=color,
        accent=None if session.finished else "menthe",
    )
    if session.finished:
        net = session.net
        sign = "+" if net >= 0 else "−"
        emb.add_field(name="Résultat", value=session.summary, inline=False)
        emb.add_field(
            name="💰 Gain",
            value=(
                f"**{sign}{format_coins(abs(net))}**\n"
                f"Solde : {format_coins(balance)}"
            ),
            inline=True,
        )
        emb.add_field(name="Mise", value=format_coins(session.bet), inline=True)
    else:
        emb.add_field(
            name="Que fais-tu ?",
            value="**Tirer** une carte · **Rester** · **Doubler** · **Abandonner**",
            inline=False,
        )
        emb.add_field(name="Solde", value=format_coins(balance), inline=True)
        emb.add_field(name="Mise", value=format_coins(session.bet), inline=True)
    emb.set_footer(
        text=f"Vespara • Blackjack • blackjack naturel ×{CASINO_BLACKJACK_NATURAL:g} · victoire ×{CASINO_BLACKJACK_PAYOUT:g}"
    )
    return emb


def slots_embed(
    reels: tuple[str, ...],
    bet: int,
    *,
    payout: int = 0,
    spinning: bool = False,
    label: str = "",
    balance: int | None = None,
) -> discord.Embed:
    """Machine à sous : rouleaux, gain et animation."""
    won = payout > 0
    if spinning:
        color = COLOR_CASINO
        desc = "```\n" + " ┃ ".join(reels) + "\n```\n*Les rouleaux tournent…*"
    else:
        color = COLOR_LEGENDARY if payout >= bet * 6 else (COLOR_CASINO if won else 0x64748B)
        desc = "```\n" + " ┃ ".join(reels) + "\n```\n" + (label or "")
        if balance is not None:
            net = payout - bet
            desc += f"\n\n**{'Gain' if net >= 0 else 'Perte'} : {'+' if net >= 0 else '−'}{format_coins(abs(net))}**"
            desc += f"\nSolde : {format_coins(balance)}"

    emb = embed(
        title=f"{EMOJI['gift']} Machine à sous — mise {format_coins(bet)}",
        description=desc,
        color=color,
        accent="menthe" if won else None,
    )
    emb.add_field(
        name="Multiplicateurs",
        value=(
            f"3 identiques : ×{CASINO_SLOTS_PAYOUTS[3]:g}\n"
            "3 × 7️⃣ : ×24\n"
            f"2 identiques : ×{CASINO_SLOTS_PAYOUTS[2]:g}"
        ),
        inline=True,
    )
    emb.add_field(name="Symboles", value=" ".join(SLOT_SYMBOLS), inline=True)
    emb.set_footer(text="Vespara • Machine à sous")
    return emb


def roulette_embed(result: Any, *, balance: int) -> discord.Embed:
    emb = embed(
        title=f"{EMOJI['dice']} Roulette — mise {format_coins(result.stake)}",
        description=(
            f"🎡 La bille s'arrête sur… {result.display}\n\n"
            f"**Pari** : {result.bet if result.bet != 'nombre' else f'numéro {result.bet_number}'}\n"
            f"{result.label}"
        ),
        color=COLOR_LEGENDARY if result.won else 0x64748B,
        accent="menthe" if result.won else None,
    )
    net = result.net
    emb.add_field(
        name="Résultat",
        value=f"{'+' if net >= 0 else '−'}{format_coins(abs(net))}\nSolde : {format_coins(balance)}",
        inline=True,
    )
    emb.add_field(name="Multiplicateur", value=f"×{result.multiplier:g}", inline=True)
    emb.set_footer(text="Vespara • Roulette européenne")
    return emb


def dice_embed(result: Any, *, balance: int) -> discord.Embed:
    emb = embed(
        title=f"{EMOJI['dice']} Dés — mise {format_coins(result.stake)}",
        description=f"{result.display}\n\n{result.label}",
        color=COLOR_LEGENDARY if result.won else 0x64748B,
        accent="menthe" if result.won else None,
    )
    net = result.net
    emb.add_field(
        name="Résultat",
        value=f"{'+' if net >= 0 else '−'}{format_coins(abs(net))}\nSolde : {format_coins(balance)}",
        inline=True,
    )
    emb.add_field(name="Multiplicateur", value=f"×{result.multiplier:g}", inline=True)
    emb.set_footer(text="Vespara • Jeu de dés")
    return emb


# --------------------------------------------------------------------------- #
# Animation des rouleaux
# --------------------------------------------------------------------------- #
async def animate_slots(message: discord.Message, bet: int, frames: int = 4, delay: float = 0.55) -> None:
    """Fait défiler les rouleaux avant de révéler le résultat."""
    rng = random.Random()
    for _ in range(frames):
        fake = tuple(rng.choice(SLOT_SYMBOLS) for _ in range(3))
        with contextlib.suppress(discord.HTTPException):
            await message.edit(embed=slots_embed(fake, bet, spinning=True))
        await asyncio.sleep(delay)


# --------------------------------------------------------------------------- #
# Vue du blackjack
# --------------------------------------------------------------------------- #
class BlackjackView(discord.ui.View):
    """Boutons Tirer / Rester / Doubler / Abandonner (éphémère, 3 min)."""

    def __init__(
        self,
        bot: "VesparaBot",
        manager: EconomyManager,
        session: BlackjackSession,
        member: Any,
        guild: discord.Guild,
        *,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.manager = manager
        self.session = session
        self.member = member
        self.guild = guild
        self.user_id = getattr(member, "id", 0)
        self._refresh()

    # ------------------------------------------------------------------ #
    def _refresh(self) -> None:
        finished = self.session.finished
        self.hit_button.disabled = finished
        self.stand_button.disabled = finished
        self.double_button.disabled = finished or not self.session.can_double()
        self.surrender_button.disabled = finished or not self.session.can_surrender()

    def embed_now(self) -> discord.Embed:
        balance = self.manager.balance(self.guild.id, self.user_id)
        return blackjack_embed(self.session, member=self.member, balance=balance)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=error("Cette table n'est pas la tienne : lance `/casino blackjack`."), ephemeral=True
            )
            return False
        return True

    # ------------------------------------------------------------------ #
    async def _settle(self, interaction: discord.Interaction, *, animate: bool = True) -> None:
        """Verse le gain, met à jour la vue et l'embed."""
        self._refresh()
        if self.session.payout:
            self.manager.payout(
                self.guild.id,
                self.user_id,
                self.session.payout,
                bet=self.session.bet,
            )
        else:
            self.manager.count_game(self.guild.id, self.user_id)

        if animate:
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.edit_message(
                    embed=blackjack_embed(
                        self.session,
                        member=self.member,
                        balance=self.manager.balance(self.guild.id, self.user_id),
                        title_icon="🎲",
                    ),
                    view=self,
                )
            return
        with contextlib.suppress(discord.HTTPException):
            await interaction.response.edit_message(embed=self.embed_now(), view=self)

    # ------------------------------------------------------------------ #
    @discord.ui.button(label="Tirer", emoji="🃏", style=discord.ButtonStyle.success)
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.session.hit()
        if self.session.finished:
            await self._settle(interaction)
            self.stop()
            return
        self._refresh()
        await interaction.response.edit_message(embed=self.embed_now(), view=self)

    @discord.ui.button(label="Rester", emoji="✋", style=discord.ButtonStyle.primary)
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.session.stand()
        await self._settle(interaction)
        self.stop()

    @discord.ui.button(label="Doubler", emoji="💰", style=discord.ButtonStyle.secondary)
    async def double_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        balance = self.manager.balance(self.guild.id, self.user_id)
        if balance < self.session.bet:
            await interaction.response.send_message(
                embed=error(
                    f"Doubler demande **{format_coins(self.session.bet)}** de plus "
                    f"(tu as {format_coins(balance)}).",
                    title="Solde insuffisant",
                ),
                ephemeral=True,
            )
            return
        self.manager.remove_coins(self.guild.id, self.user_id, self.session.bet, reason="double blackjack")
        self.session.double()
        await self._settle(interaction)
        self.stop()

    @discord.ui.button(label="Abandonner", emoji="🏳️", style=discord.ButtonStyle.danger)
    async def surrender_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.session.surrender():
            await interaction.response.send_message(
                embed=error("Trop tard pour abandonner."), ephemeral=True
            )
            return
        await self._settle(interaction)
        self.stop()

    async def on_timeout(self) -> None:
        """Au bout de 3 minutes sans action, la main est jouée automatiquement."""
        if self.session.finished:
            return
        self.session.stand()
        if self.session.payout:
            self.manager.payout(
                self.guild.id, self.user_id, self.session.payout, bet=self.session.bet
            )


# --------------------------------------------------------------------------- #
# Vue d'accueil du casino
# --------------------------------------------------------------------------- #
class CasinoView(discord.ui.View):
    """Boutons de raccourcis vers les jeux (éphémère)."""

    def __init__(self, bot: "VesparaBot", guild: discord.Guild, user_id: int) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild = guild
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=error("Relance `/casino` pour ouvrir ton propre menu."), ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Blackjack", emoji="🃏", style=discord.ButtonStyle.success)
    async def blackjack(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=embed(
                title="🃏 Blackjack",
                description="Lance la partie avec :\n`/casino blackjack mise:100`",
                color=COLOR_CASINO,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Machine à sous", emoji="🎰", style=discord.ButtonStyle.primary)
    async def slots(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=embed(
                title="🎰 Machine à sous",
                description="Lance les rouleaux avec :\n`/casino slots mise:100`",
                color=COLOR_CASINO,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Roulette", emoji="🎡", style=discord.ButtonStyle.secondary)
    async def roulette(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=embed(
                title="🎡 Roulette",
                description="Parie avec :\n`/casino roulette mise:100 pari:rouge`",
                color=COLOR_CASINO,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Dés", emoji="🎲", style=discord.ButtonStyle.secondary)
    async def dice(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=embed(
                title="🎲 Dés",
                description="Tente le coup avec :\n`/casino des mise:100 pari:sept`",
                color=COLOR_CASINO,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Mon profil", emoji="🪙", style=discord.ButtonStyle.secondary)
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from .economy import profile_embed

        manager: EconomyManager = self.bot.economy  # type: ignore[attr-defined]
        await interaction.response.send_message(
            embed=profile_embed(manager, self.guild, interaction.user), ephemeral=True
        )


__all__ = [
    "BlackjackView",
    "CasinoView",
    "animate_slots",
    "blackjack_embed",
    "casino_home_embed",
    "dice_embed",
    "hand_value",
    "render_hand",
    "roulette_embed",
    "slots_embed",
]
