"""Rendus et vues des commandes rigolotes (jauges, ship, duel, PFC, sondages)."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import discord

from ..constants import (
    COLOR_INFO,
    COLOR_LEGENDARY,
    COLOR_MUTED,
    COLOR_SUCCESS,
    COLOR_WARNING,
    EMOJI,
    FOOTER,
    SPARKLES,
)
from ..helpers import animated_progress, embed, error, gradient_color, percent_bar, truncate
from ..services.fun import (
    ACTIONS,
    COIN_EMOJIS,
    RPS_EMOJIS,
    RPS_LABELS,
    BattleResult,
    Gauge,
    action_line,
    bot_rps_choice,
    resolve_rps,
)

if TYPE_CHECKING:  # pragma: no cover
    pass


# --------------------------------------------------------------------------- #
# /dire — le bot parle
# --------------------------------------------------------------------------- #
async def send_say(
    channel: Any,
    text: str,
    *,
    as_embed: bool = False,
    accent: str = "violet",
    pin: bool = False,
) -> Any:
    """Envoie (ou fait dire) un message public dans un salon."""
    kwargs: dict[str, Any] = {}
    if as_embed:
        kwargs["embed"] = embed(
            description=text,
            color=gradient_color(accent, 0.25),
            accent=accent,
            icon="📣",
        )
    else:
        kwargs["content"] = text

    message = await channel.send(
        allowed_mentions=discord.AllowedMentions.none(), **kwargs
    )
    if pin:
        with contextlib.suppress(discord.HTTPException):
            await message.pin(reason="/dire : épinglage demandé")
    return message


def say_preview_embed(text: str, channel: Any) -> discord.Embed:
    """Aperçu privé avant l'envoi public."""
    return embed(
        title="📣 Aperçu du message",
        description=truncate(text, 3800),
        color=gradient_color("violet", 0.2),
        accent="violet",
        icon="👁️",
    ).add_field(name="Salon", value=getattr(channel, "mention", "—"), inline=True)


# --------------------------------------------------------------------------- #
# Jauges (/iq, /sus, /simp, /aura, /chaos)
# --------------------------------------------------------------------------- #
def gauge_embed(gauge_result: Gauge, member: Any) -> discord.Embed:
    """Carte animée d'une jauge rigolote."""
    name = getattr(member, "display_name", str(member))
    color = (
        gradient_color("menthe", 0.2)
        if gauge_result.ratio >= 0.66
        else (gradient_color("or", 0.5) if gauge_result.ratio >= 0.33 else COLOR_MUTED)
    )
    emb = embed(
        title=f"{gauge_result.emoji} {gauge_result.title} — {name}",
        description=(
            f"## {gauge_result.label}\n"
            f"{percent_bar(gauge_result.ratio, 16)}\n\n"
            f"### {gauge_result.verdict}\n"
            f"*{gauge_result.comment}*"
        ),
        color=color,
        thumbnail=getattr(getattr(member, "display_avatar", None), "url", None),
        icon=SPARKLES[0],
    )
    emb.set_footer(text=f"{FOOTER} • Résultat certifié par le comité très sérieux du bot")
    return emb


# --------------------------------------------------------------------------- #
# /ship
# --------------------------------------------------------------------------- #
def ship_embed(result: dict[str, Any]) -> discord.Embed:
    a, b = result["a"], result["b"]
    score = int(result["score"])
    ratio = score / 100
    heart = "💞" if ratio >= 0.7 else ("💓" if ratio >= 0.4 else "💔")
    emb = embed(
        title=f"{heart} {result['name']}",
        description=(
            f"## {score} % de compatibilité\n"
            f"{percent_bar(ratio, 18)}\n\n"
            f"### {result['verdict']}\n"
            f"*{result['comment']}*"
        ),
        color=gradient_color("rose", 1 - ratio),
        accent="rose",
        thumbnail=getattr(getattr(a, "display_avatar", None), "url", None),
        image=getattr(getattr(b, "display_avatar", None), "url", None),
        icon="💘",
    )
    return emb


# --------------------------------------------------------------------------- #
# /duel
# --------------------------------------------------------------------------- #
def battle_embed(result: BattleResult, *, step: int | None = None) -> discord.Embed:
    """Embed du duel : barres de vie et journal des derniers coups."""
    total = result.turns
    shown = result.events if step is None else result.events[:step]
    last = shown[-1].text if shown else "*Le duel commence…*"

    emb = embed(
        title=f"⚔️ {result.fighter_a} vs {result.fighter_b}",
        description=f"{animated_progress(0.5, 12)}\n\n{last}",
        color=COLOR_LEGENDARY if result.winner else COLOR_WARNING,
        accent="feu",
        icon="⚔️",
    )
    emb.add_field(
        name=f"🔵 {result.fighter_a}",
        value=f"{percent_bar(result.hp_a / 100, 10)}",
        inline=True,
    )
    emb.add_field(
        name=f"🔴 {result.fighter_b}",
        value=f"{percent_bar(result.hp_b / 100, 10)}",
        inline=True,
    )
    if result.winner:
        emb.add_field(
            name="🏆 Vainqueur",
            value=f"**{result.winner}** gagne le duel en **{total}** tour(s) !",
            inline=False,
        )
    else:
        emb.add_field(
            name="Tour",
            value=f"{len(shown)}/{total}" if step is not None else f"{total} tours",
            inline=False,
        )
    emb.set_footer(text=f"{FOOTER} • Combat simulé, aucune blessure réelle")
    return emb


async def _sleep(delay: float) -> None:
    """Unique point de pause des animations (patchable proprement dans les tests)."""
    await asyncio.sleep(delay)


async def animate_battle(message: Any, result: BattleResult, *, delay: float = 0.7) -> None:
    """Fait défiler le journal du duel avant d'afficher le verdict."""
    total = len(result.events)
    step_size = max(1, total // 4)
    for step in range(step_size, total + 1, step_size):
        with contextlib.suppress(discord.HTTPException):
            await message.edit(embed=battle_embed(result, step=step))
        await _sleep(delay)
    with contextlib.suppress(discord.HTTPException):
        await message.edit(embed=battle_embed(result))


# --------------------------------------------------------------------------- #
# /pfc — pierre-feuille-ciseaux
# --------------------------------------------------------------------------- #
def rps_embed(
    *,
    player: Any,
    choice: str | None,
    bot_choice: str | None,
    outcome: str | None,
    opponent: Any | None = None,
) -> discord.Embed:
    """Tableau du pierre-feuille-ciseaux."""
    if choice is None or bot_choice is None:
        return embed(
            title="✂️ Pierre · Feuille · Ciseaux",
            description=(
                f"{getattr(player, 'mention', player)} choisit son coup…\n\n"
                f"🪨 Pierre · 📄 Feuille · ✂️ Ciseaux"
            ),
            color=COLOR_INFO,
            accent="ocean",
            icon="✂️",
        )

    emoji_player = RPS_EMOJIS[choice]
    emoji_bot = RPS_EMOJIS[bot_choice]
    rival = getattr(opponent, "display_name", None) or "Le bot"
    if outcome == "a":
        headline = f"🎉 **{getattr(player, 'display_name', player)} gagne !**"
        color = COLOR_SUCCESS
    elif outcome == "b":
        headline = f"😵 **{rival} gagne !**"
        color = COLOR_WARNING
    else:
        headline = "🤝 **Égalité !**"
        color = COLOR_MUTED

    emb = embed(
        title=f"✂️ {getattr(player, 'display_name', player)} vs {rival}",
        description=(
            f"### {RPS_LABELS[choice]} {emoji_player}  ⚡  {emoji_bot} {RPS_LABELS[bot_choice]}\n\n"
            f"{headline}"
        ),
        color=color,
        accent="ocean" if outcome == "draw" else None,
        icon="✂️",
    )
    return emb


class RpsView(discord.ui.View):
    """Boutons Pierre / Feuille / Ciseaux (un seul coup par membre)."""

    def __init__(self, author_id: int, opponent: Any, *, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.opponent = opponent
        self.played: dict[int, str] = {}
        self.result: str | None = None
        for key, emoji, label in (
            ("pierre", "🪨", "Pierre"),
            ("feuille", "📄", "Feuille"),
            ("ciseaux", "✂️", "Ciseaux"),
        ):
            self.add_item(self._make_button(key, emoji, label))

    def _make_button(self, key: str, emoji: str, label: str) -> discord.ui.Button:
        button = discord.ui.Button(
            label=label, emoji=emoji, style=discord.ButtonStyle.secondary, custom_id=f"vespara:rps:{key}"
        )
        button.callback = self._callback_factory(key)  # type: ignore[method-assign]
        return button

    def _callback_factory(self, key: str):
        async def callback(interaction: discord.Interaction) -> None:
            await self._play(interaction, key)

        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # En 1v1, les deux membres peuvent jouer ; en solo, seul l'auteur.
        allowed = {self.author_id}
        if self.opponent is not None:
            allowed.add(int(getattr(self.opponent, "id", 0)))
        if interaction.user.id not in allowed:
            await interaction.response.send_message(
                embed=error("Ce duel ne te concerne pas : lance `/pfc` pour jouer."), ephemeral=True
            )
            return False
        return True

    async def _play(self, interaction: discord.Interaction, choice: str) -> None:
        player = interaction.user
        if self.opponent is not None:
            self.played[player.id] = choice
            if len(self.played) < 2:
                await interaction.response.send_message(
                    embed=embed(
                        title="✂️ Coup enregistré",
                        description=(
                            f"{player.mention} a choisi son coup 🔒\n"
                            f"En attente de {getattr(self.opponent, 'mention', 'l’adversaire')}…"
                        ),
                        color=COLOR_INFO,
                    ),
                    ephemeral=True,
                )
                return

            a_choice = self.played.get(self.author_id)
            b_choice = self.played.get(int(getattr(self.opponent, "id", 0)))
            self.result = resolve_rps(a_choice, b_choice)
            emb = rps_embed(
                player=player,
                choice=b_choice,
                bot_choice=a_choice,
                outcome="b" if self.result == "a" else ("a" if self.result == "b" else "draw"),
                opponent=None,
            )
            for child in self.children:
                child.disabled = True  # type: ignore[attr-defined]
            await interaction.response.edit_message(embed=emb, view=self)
            self.stop()
            return

        bot_choice = bot_rps_choice()
        self.result = resolve_rps(choice, bot_choice)
        emb = rps_embed(
            player=player, choice=choice, bot_choice=bot_choice, outcome=self.result
        )
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(embed=emb, view=self)
        self.stop()


# --------------------------------------------------------------------------- #
# /sondage
# --------------------------------------------------------------------------- #
POLL_NUMBERS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")


def poll_embed(
    question: str, options: list[str], *, author: Any, multiple: bool = False
) -> discord.Embed:
    lines = [f"**{POLL_NUMBERS[index]}** {option}" for index, option in enumerate(options)]
    emb = embed(
        title="📊 Sondage",
        description=(
            f"### {question}\n\n" + "\n".join(lines) + "\n\n"
            f"*Réagis avec {'plusieurs' if multiple else 'un seul'} emoji pour voter.*"
        ),
        color=gradient_color("ocean", 0.35),
        accent="ocean",
        icon="📊",
    )
    emb.set_footer(
        text=f"{FOOTER} • Sondage de {getattr(author, 'display_name', author)}"
    )
    return emb


async def publish_poll(
    channel: Any,
    question: str,
    options: list[str],
    *,
    author: Any,
    multiple: bool = False,
) -> Any:
    """Publie le sondage et ajoute les réactions de vote."""
    message = await channel.send(embed=poll_embed(question, options, author=author, multiple=multiple))
    for emoji in POLL_NUMBERS[: len(options)]:
        with contextlib.suppress(discord.HTTPException):
            await message.add_reaction(emoji)
    return message


# --------------------------------------------------------------------------- #
# Divers : blague, citation, action, dés
# --------------------------------------------------------------------------- #
def joke_embed(text: str, *, author: Any = None) -> discord.Embed:
    return embed(
        title=f"{EMOJI['party']} Blague du jour",
        description=f"### {text}",
        color=gradient_color("or", 0.3),
        accent="or",
        icon="😂",
    )


def quote_embed(text: str, *, author_label: str, requester: Any = None) -> discord.Embed:
    emb = embed(
        title="❝ Citation ❞",
        description=f">>> {truncate(text, 3500)}\n\n— **{truncate(author_label, 120)}**",
        color=gradient_color("violet", 0.15),
        accent="violet",
        icon="🖋️",
    )
    if requester is not None:
        emb.set_footer(
            text=f"{FOOTER} • cité par {getattr(requester, 'display_name', requester)}"
        )
    return emb


def action_embed(key: str, actor: Any, target: Any) -> discord.Embed:
    spec = ACTIONS.get(key)
    if spec is None:  # pragma: no cover - clé validée en amont
        return embed(title="Action inconnue", color=COLOR_MUTED)
    emb = embed(
        title=f"{spec.emoji} {spec.label}",
        description=(
            f"{getattr(actor, 'mention', actor)} {spec.verb} {getattr(target, 'mention', target)} !\n\n"
            f"*{action_line(key)}*"
        ),
        color=spec.color,
    )
    return emb


def dice_embed(values: list[int], sides: int, *, roller: Any) -> discord.Embed:
    from ..services.fun import dice_display

    total = sum(values)
    emb = embed(
        title=f"🎲 Lancer de {len(values)}d{sides}",
        description=(
            f"### {dice_display(values, sides)}\n\n"
            f"Total : **{total}**"
        ),
        color=gradient_color("menthe", 0.3),
        accent="menthe",
        icon="🎲",
    )
    emb.set_footer(text=f"Vespara • lancé par {getattr(roller, 'display_name', roller)}")
    return emb


def coin_embed(result: str, *, flipper: Any) -> discord.Embed:
    emoji = COIN_EMOJIS.get(result, "🪙")
    emb = embed(
        title=f"{emoji} Pile ou face",
        description=f"## {result.capitalize()} !",
        color=gradient_color("or", 0.4),
        accent="or",
        icon="🪙",
    )
    emb.set_footer(text=f"Vespara • lancé par {getattr(flipper, 'display_name', flipper)}")
    return emb


def horoscope_embed(sign_label: str, text: str, member: Any) -> discord.Embed:
    return embed(
        title=f"🔮 {sign_label} — {getattr(member, 'display_name', member)}",
        description=f"### {text}",
        color=gradient_color("rose", 0.5),
        accent="rose",
        icon="🔮",
    )


def fun_menu_embed() -> discord.Embed:
    """Aide listant les commandes rigolotes (bouton du menu)."""
    emb = embed(
        title="🎉 Coin des bêtises",
        description=(
            "Des commandes **juste pour rire**, aucune conséquence (sauf pour ton ego).\n\u200b"
        ),
        color=gradient_color("rose", 0.2),
        accent="rose",
        icon="🎉",
    )
    emb.add_field(
        name="🎰 Jauges & hasard",
        value=(
            "`/iq` · `/sus` · `/simp` · `/aura` · `/chaos`\n"
            "`/ship` · `/blague` · `/horoscope`\n"
            "`/pileouface` · `/de`"
        ),
        inline=True,
    )
    emb.add_field(
        name="⚔️ Défis",
        value=(
            "`/duel` · combat épique\n"
            "`/pfc` · pierre-feuille-ciseaux\n"
            "`/boule` · boule magique 🎱"
        ),
        inline=True,
    )
    emb.add_field(
        name="🫶 Ambiance",
        value="`/calin` · `/baffe` · `/tapote`\n`/pique` · `/complimente`",
        inline=False,
    )
    emb.add_field(
        name="📣 Pour le staff",
        value=(
            "`/dire` (admin) · faire parler le bot\n"
            "`/sondage` · sondage à réactions\n"
            "`/citation` · citation mise en valeur"
        ),
        inline=False,
    )
    emb.set_footer(text=f"{FOOTER} • Tape / et laisse-toi guider")
    return emb


__all__ = [
    "POLL_NUMBERS",
    "RpsView",
    "action_embed",
    "animate_battle",
    "battle_embed",
    "coin_embed",
    "dice_embed",
    "fun_menu_embed",
    "gauge_embed",
    "horoscope_embed",
    "joke_embed",
    "poll_embed",
    "publish_poll",
    "quote_embed",
    "rps_embed",
    "say_preview_embed",
    "send_say",
    "ship_embed",
]
