"""Commandes de gestion des giveaways (staff uniquement)."""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..checks import is_staff
from ..constants import (
    COLOR_GIVEAWAY,
    EMOJI,
    MAX_GIVEAWAY_DURATION,
    MIN_GIVEAWAY_DURATION,
)
from ..helpers import (
    embed,
    error,
    humanize_duration,
    info,
    parse_duration,
    reply_ephemeral,
    success,
    timestamp,
    truncate,
    warning,
)
from ..services.giveaways import GiveawayManager
from ..ui.common import ConfirmView

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Autocomplétion
# --------------------------------------------------------------------------- #
def _guild_giveaways(interaction: discord.Interaction, *, ended: bool | None = None) -> list[dict]:
    if interaction.guild is None:
        return []
    db = interaction.client.db  # type: ignore[attr-defined]
    items = [
        gw
        for gw in db.giveaways().values()
        if gw.get("guild_id") == interaction.guild.id and (ended is None or bool(gw.get("ended")) == ended)
    ]
    return sorted(items, key=lambda gw: gw.get("created_at", 0), reverse=True)


def _format_choice(gw: dict) -> str:
    state = "terminé" if gw.get("ended") else f"{len(gw.get('entries', []))} part."
    return truncate(f"#{gw['id']} · {gw['prize']} · {state}", 100)


async def active_giveaway_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current = current.lower()
    return [
        app_commands.Choice(name=_format_choice(gw), value=str(gw["id"]))
        for gw in _guild_giveaways(interaction, ended=False)[:25]
        if current in _format_choice(gw).lower() or current in str(gw["id"])
    ]


async def ended_giveaway_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current = current.lower()
    return [
        app_commands.Choice(name=_format_choice(gw), value=str(gw["id"]))
        for gw in _guild_giveaways(interaction, ended=True)[:25]
        if current in _format_choice(gw).lower() or current in str(gw["id"])
    ]


async def any_giveaway_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current = current.lower()
    return [
        app_commands.Choice(name=_format_choice(gw), value=str(gw["id"]))
        for gw in _guild_giveaways(interaction)[:25]
        if current in _format_choice(gw).lower() or current in str(gw["id"])
    ]


# --------------------------------------------------------------------------- #
# Groupe /giveaway
# --------------------------------------------------------------------------- #
@app_commands.guild_only()
class GiveawayGroup(app_commands.Group, name="giveaway", description="Organiser et gérer des giveaways"):
    """Toutes les commandes sont réservées au staff (voir visibilité)."""

    @app_commands.command(name="create", description="Lancer un nouveau giveaway")
    @app_commands.describe(
        prix="Ce que l'on fait gagner",
        duree="Durée : 30m, 1h30, 2 jours, 1 sem…",
        gagnants="Nombre de gagnants (1 à 20)",
        salon="Salon où publier le giveaway (défaut : salon actuel)",
        description="Texte complémentaire affiché dans l'embed",
        role="Rôle obligatoire pour participer",
    )
    @is_staff()
    async def create(
        self,
        interaction: discord.Interaction,
        prix: str,
        duree: str,
        gagnants: app_commands.Range[int, 1, 20] = 1,
        salon: discord.TextChannel | None = None,
        description: str | None = None,
        role: discord.Role | None = None,
    ) -> None:
        manager: GiveawayManager = interaction.client.giveaway_manager  # type: ignore[attr-defined]

        try:
            seconds = parse_duration(duree)
        except ValueError as exc:
            await reply_ephemeral(interaction, error(str(exc), title="Durée invalide"))
            return

        if seconds < MIN_GIVEAWAY_DURATION:
            await reply_ephemeral(
                interaction,
                error(
                    f"La durée minimale est de {MIN_GIVEAWAY_DURATION} secondes "
                    f"(reçu : {humanize_duration(seconds)})."
                ),
            )
            return
        if seconds > MAX_GIVEAWAY_DURATION:
            await reply_ephemeral(
                interaction,
                error(f"La durée maximale est de {humanize_duration(MAX_GIVEAWAY_DURATION)}."),
            )
            return

        channel = salon or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await reply_ephemeral(interaction, error("Choisis un salon textuel valide."))
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            gw = await manager.create(
                guild=interaction.guild,  # type: ignore[arg-type]
                channel=channel,
                host=interaction.user,
                prize=prix,
                duration=seconds,
                description=description,
                winners_count=gagnants,
                required_role=role,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error(
                    f"Je n'ai pas la permission d'écrire dans {channel.mention} "
                    "(il me faut « Envoyer des messages » et « Intégrer des liens »)."
                ),
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            log.exception("Création du giveaway impossible")
            await interaction.followup.send(
                embed=error(f"Discord a refusé la création du giveaway : `{exc}`"), ephemeral=True
            )
            return

        link = f"https://discord.com/channels/{gw['guild_id']}/{gw['channel_id']}/{gw['message_id']}"
        await interaction.followup.send(
            embed=success(
                f"Giveaway **{prix}** lancé dans {channel.mention} !\n"
                f"• Gagnants : **{gagnants}**\n"
                f"• Fin : {timestamp(gw['ends_at'])} ({humanize_duration(seconds)})\n"
                f"• [Voir le message]({link})",
                title="Giveaway créé",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="end", description="Terminer un giveaway maintenant et tirer les gagnants")
    @app_commands.describe(giveaway="Giveaway à terminer (défaut : le plus récent en cours)")
    @app_commands.autocomplete(giveaway=active_giveaway_autocomplete)
    @is_staff()
    async def end(self, interaction: discord.Interaction, giveaway: str | None = None) -> None:
        manager: GiveawayManager = interaction.client.giveaway_manager  # type: ignore[attr-defined]
        gw = _resolve_giveaway(interaction, giveaway, ended=False)
        if gw is None:
            await reply_ephemeral(
                interaction, error("Aucun giveaway en cours dans ce serveur."),
            )
            return
        if gw.get("ended"):
            await reply_ephemeral(interaction, error("Ce giveaway est déjà terminé."))
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        winners = await manager.end(gw, ended_by=interaction.user)
        if winners:
            text = (
                f"**{gw['prize']}** est terminé.\n"
                f"Gagnant{'s' if len(winners) > 1 else ''} : {' '.join(f'<@{uid}>' for uid in winners)}"
            )
        else:
            text = f"**{gw['prize']}** est terminé, mais il n'y avait aucun participant."
        await interaction.followup.send(
            embed=success(text, title="Giveaway terminé"), ephemeral=True
        )

    @app_commands.command(name="reroll", description="Relancer le tirage d'un giveaway terminé")
    @app_commands.describe(
        giveaway="Giveaway concerné (défaut : le dernier terminé)",
        gagnants="Nombre de nouveaux gagnants",
    )
    @app_commands.autocomplete(giveaway=ended_giveaway_autocomplete)
    @is_staff()
    async def reroll(
        self,
        interaction: discord.Interaction,
        giveaway: str | None = None,
        gagnants: app_commands.Range[int, 1, 20] | None = None,
    ) -> None:
        manager: GiveawayManager = interaction.client.giveaway_manager  # type: ignore[attr-defined]
        gw = _resolve_giveaway(interaction, giveaway, ended=True)
        if gw is None:
            await reply_ephemeral(interaction, error("Aucun giveaway terminé dans ce serveur."))
            return

        count = int(gagnants or gw.get("winners_count", 1))
        await interaction.response.defer(thinking=True, ephemeral=True)
        winners = await manager.reroll(gw, count, actor=interaction.user)
        if not winners:
            await interaction.followup.send(
                embed=error("Impossible de relancer : aucun participant disponible."), ephemeral=True
            )
            return
        await interaction.followup.send(
            embed=success(
                f"Nouveau tirage pour **{gw['prize']}** : {' '.join(f'<@{uid}>' for uid in winners)}",
                title="Tirage relancé",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="list", description="Afficher les giveaways en cours")
    @is_staff()
    async def list_(self, interaction: discord.Interaction) -> None:
        active = _guild_giveaways(interaction, ended=False)
        if not active:
            await reply_ephemeral(
                interaction,
                info("Aucun giveaway en cours. Lance-en un avec `/giveaway create` !"),
            )
            return

        lines = []
        for gw in active[:15]:
            link = f"https://discord.com/channels/{gw['guild_id']}/{gw['channel_id']}/{gw.get('message_id')}"
            lines.append(
                f"{EMOJI['gift']} **[{truncate(gw['prize'], 60)}]({link})** · `#{gw['id']}`\n"
                f"　　{len(gw.get('entries', []))} participant(s) · fin {timestamp(gw['ends_at'])}"
            )
        emb = embed(
            title=f"{EMOJI['gift']} Giveaways en cours ({len(active)})",
            description="\n\n".join(lines),
            color=COLOR_GIVEAWAY,
        )
        await reply_ephemeral(interaction, emb)

    @app_commands.command(name="delete", description="Supprimer un giveaway (message + données)")
    @app_commands.describe(giveaway="Giveaway à supprimer (défaut : le plus récent)")
    @app_commands.autocomplete(giveaway=any_giveaway_autocomplete)
    @is_staff()
    async def delete(self, interaction: discord.Interaction, giveaway: str | None = None) -> None:
        manager: GiveawayManager = interaction.client.giveaway_manager  # type: ignore[attr-defined]
        gw = _resolve_giveaway(interaction, giveaway, ended=None)
        if gw is None:
            await reply_ephemeral(interaction, error("Aucun giveaway trouvé dans ce serveur."))
            return

        confirm = ConfirmView(author_id=interaction.user.id, confirm_label="Supprimer")
        accepted = await confirm.prompt(
            interaction,
            warning(
                f"Supprimer définitivement le giveaway **{gw['prize']}** (`#{gw['id']}`) ?\n"
                "Le message sera retiré et les participations perdues.",
                title="Suppression",
            ),
        )
        if not accepted:
            return
        await manager.delete(gw)
        await interaction.followup.send(
            embed=success("Giveaway supprimé.", title="Suppression"), ephemeral=True
        )


def _resolve_giveaway(
    interaction: discord.Interaction, giveaway_id: str | None, *, ended: bool | None
) -> dict | None:
    """Retrouve un giveaway par identifiant, sinon le plus récent du serveur."""
    if interaction.guild is None:
        return None
    manager: GiveawayManager = interaction.client.giveaway_manager  # type: ignore[attr-defined]
    if giveaway_id:
        gw = manager.get(giveaway_id)
        if gw is None or gw.get("guild_id") != interaction.guild.id:
            return None
        return gw

    candidates = _guild_giveaways(interaction, ended=ended)
    return candidates[0] if candidates else None


# --------------------------------------------------------------------------- #
# Cog
# --------------------------------------------------------------------------- #
class Giveaways(commands.Cog):
    """Gestion des giveaways et de leur cycle de vie."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self.manager = GiveawayManager(bot)
        bot.giveaway_manager = self.manager
        self._last_prune = 0.0
        self.giveaway = GiveawayGroup()

    async def cog_load(self) -> None:
        await self.manager.restore_views()
        self.ending_loop.start()

    async def cog_unload(self) -> None:
        self.ending_loop.cancel()
        self.bot.tree.remove_command(self.giveaway.name)
        await self.manager.close()

    @tasks.loop(seconds=20)
    async def ending_loop(self) -> None:
        """Termine les giveaways arrivés à échéance et nettoie les vieux enregistrements."""
        if not self.bot.is_ready():
            return
        try:
            ended = await self.manager.end_expired()
            if ended:
                log.info("%s giveaway(s) terminé(s) automatiquement.", ended)
            if time.time() - self._last_prune > 3600:
                self._last_prune = time.time()
                removed = self.bot.db.prune_giveaways()
                if removed:
                    log.info("%s ancien(s) giveaway(s) purgé(s).", removed)
        except Exception:  # pragma: no cover - le loop doit survivre
            log.exception("Erreur dans la boucle des giveaways")

    @ending_loop.before_loop
    async def before_ending_loop(self) -> None:
        with contextlib.suppress(RuntimeError):
            await self.bot.wait_until_ready()


async def setup(bot: "VesparaBot") -> None:
    cog = Giveaways(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.giveaway, override=True)
