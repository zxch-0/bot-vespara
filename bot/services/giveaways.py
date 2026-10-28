"""Logique complète des giveaways (création, participation, tirage, relance)."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING, Any, Iterable

import discord

from ..constants import (
    COLOR_GIVEAWAY,
    COLOR_SUCCESS,
    EMOJI,
    MAX_GIVEAWAY_DURATION,
)
from ..helpers import (
    embed,
    error,
    humanize_duration,
    info,
    mention_list,
    progress_bar,
    reply_ephemeral,
    success,
    timestamp,
    truncate,
)
from ..ui.builders import giveaways_embed
from ..ui.giveaway import GiveawayView, RerollView
from ..ui.paginator import Paginator

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Embed
# --------------------------------------------------------------------------- #
def build_giveaway_embed(gw: dict[str, Any], *, icon_url: str | None = None) -> discord.Embed:
    """Construit l'embed d'un giveaway (en cours ou terminé)."""
    now = time.time()
    started = float(gw.get("started_at") or now)
    ends_at = float(gw.get("ends_at") or now)
    ended = bool(gw.get("ended"))
    entries: list[int] = [int(uid) for uid in gw.get("entries", [])]
    winners: list[int] = [int(uid) for uid in gw.get("winners", [])]

    title_prefix = "🎉" if ended else "🎁"
    parts: list[str] = []

    if gw.get("description"):
        parts.append(str(gw["description"]))

    if ended:
        if winners:
            parts.append(f"### 🏆 {'Gagnants' if len(winners) > 1 else 'Gagnant'}\n{mention_list(winners, 20)}")
        else:
            parts.append("### 😔 Aucun participant\nPersonne n'a tenté sa chance cette fois-ci.")
    else:
        total = max(1.0, ends_at - started)
        ratio = 1.0 if now >= ends_at else (now - started) / total
        parts.append(
            f"`{progress_bar(ratio)}` · **{humanize_duration(max(0, ends_at - now))}** restants"
        )

    emb = embed(
        title=f"{title_prefix} {truncate(str(gw.get('prize', 'Giveaway')), 240)}",
        description="\n\n".join(parts) or None,
        color=COLOR_SUCCESS if ended else COLOR_GIVEAWAY,
        thumbnail=icon_url,
    )

    winners_count = int(gw.get("winners_count", 1))
    if ended:
        emb.add_field(
            name="Terminé",
            value=timestamp(gw.get("ended_at") or ends_at),
            inline=True,
        )
        emb.add_field(name="Participants", value=str(len(entries)), inline=True)
        emb.add_field(name="Gagnants", value=str(len(winners)) if winners else "Aucun", inline=True)
    else:
        emb.add_field(name="Fin", value=f"{timestamp(ends_at)}\n<t:{int(ends_at)}:f>", inline=True)
        emb.add_field(
            name="Participants",
            value=f"**{len(entries)}**",
            inline=True,
        )
        emb.add_field(
            name="Gagnants",
            value=str(winners_count),
            inline=True,
        )

    required_role_id = gw.get("required_role_id")
    if required_role_id:
        emb.add_field(name="Condition", value=f"Rôle <@&{required_role_id}> requis", inline=False)

    host = gw.get("host_name") or "le staff"
    footer = f"Organisé par {host} • Vespara"
    if gw.get("rerolled_at"):
        footer += f" • relancé {timestamp(gw['rerolled_at'])}"
    emb.set_footer(text=truncate(footer, 2048))
    return emb


# --------------------------------------------------------------------------- #
# Manager
# --------------------------------------------------------------------------- #
class GiveawayManager:
    """Service centralisé, accessible via `bot.giveaway_manager`."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self._refresh_tasks: dict[str, asyncio.Task[None]] = {}
        self._message_cache: dict[str, discord.Message] = {}
        self._channel_cache: dict[int, discord.abc.Messageable] = {}
        self._ending: set[str] = set()

    # ------------------------------------------------------------------ #
    # Accès aux données
    # ------------------------------------------------------------------ #
    @property
    def db(self):
        return self.bot.db

    def get(self, giveaway_id: str) -> dict[str, Any] | None:
        return self.db.get_giveaway(giveaway_id)

    # ------------------------------------------------------------------ #
    # Création
    # ------------------------------------------------------------------ #
    async def create(
        self,
        *,
        guild: discord.Guild,
        channel: discord.TextChannel,
        host: discord.abc.User,
        prize: str,
        duration: int,
        description: str | None = None,
        winners_count: int = 1,
        required_role: discord.Role | None = None,
    ) -> dict[str, Any]:
        duration = max(10, min(int(duration), MAX_GIVEAWAY_DURATION))
        now = time.time()
        record: dict[str, Any] = {
            "id": self.db.next_id(),
            "guild_id": guild.id,
            "channel_id": channel.id,
            "message_id": None,
            "host_id": host.id,
            "host_name": host.display_name,
            "prize": prize.strip()[:256],
            "description": (description or "").strip()[:1000] or None,
            "started_at": now,
            "ends_at": now + duration,
            "winners_count": max(1, min(int(winners_count), 20)),
            "required_role_id": required_role.id if required_role else None,
            "entries": [],
            "winners": [],
            "ended": False,
            "ended_at": None,
            "created_at": now,
        }
        self.db.add_giveaway(record)

        emb = build_giveaway_embed(record, icon_url=guild.icon.url if guild.icon else None)
        try:
            message = await channel.send(embed=emb, view=GiveawayView(self.bot, record["id"]))
        except (discord.Forbidden, discord.HTTPException):
            # Évite de garder un giveaway fantôme sans message.
            self.db.giveaways().pop(str(record["id"]), None)
            self.db.schedule_save(0.5)
            raise
        record["message_id"] = message.id
        self._message_cache[record["id"]] = message
        self._channel_cache[channel.id] = channel
        self.db.schedule_save(0.5)

        log.info(
            "Giveaway #%s créé par %s (%s) dans #%s — fin %s",
            record["id"],
            host,
            prize,
            channel,
            timestamp(record["ends_at"]),
        )
        return record

    # ------------------------------------------------------------------ #
    # Messages
    # ------------------------------------------------------------------ #
    async def _get_channel(self, channel_id: int) -> discord.abc.Messageable | None:
        channel = self.bot.get_channel(channel_id) or self._channel_cache.get(channel_id)
        if channel is not None:
            self._channel_cache[channel_id] = channel
            return channel  # type: ignore[return-value]
        try:
            channel = await self.bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            log.warning("Salon %s introuvable : %s", channel_id, exc)
            return None
        self._channel_cache[channel_id] = channel  # type: ignore[assignment]
        return channel  # type: ignore[return-value]

    async def _get_message(self, gw: dict[str, Any]) -> discord.Message | None:
        cached = self._message_cache.get(str(gw["id"]))
        if cached is not None:
            return cached
        if not gw.get("message_id"):
            return None
        channel = await self._get_channel(int(gw["channel_id"]))
        if channel is None:
            return None
        try:
            message = await channel.fetch_message(int(gw["message_id"]))  # type: ignore[attr-defined]
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            log.debug("Message du giveaway #%s introuvable : %s", gw["id"], exc)
            return None
        self._message_cache[str(gw["id"])] = message
        return message

    def _icon_for(self, gw: dict[str, Any]) -> str | None:
        guild = self.bot.get_guild(int(gw.get("guild_id", 0)))
        return guild.icon.url if guild and guild.icon else None

    async def refresh(self, giveaway_id: str, *, disabled: bool = False) -> bool:
        """Réécrit l'embed du message de giveaway."""
        gw = self.get(giveaway_id)
        if gw is None:
            return False
        message = await self._get_message(gw)
        if message is None:
            return False

        emb = build_giveaway_embed(gw, icon_url=self._icon_for(gw))
        ended = bool(gw.get("ended")) or disabled
        view = GiveawayView(self.bot, str(gw["id"]), disabled=ended)
        try:
            await message.edit(embed=emb, view=view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            log.debug("Mise à jour du giveaway #%s impossible : %s", giveaway_id, exc)
            return False
        return True

    def schedule_refresh(self, giveaway_id: str, delay: float = 1.5) -> None:
        """Regroupe les mises à jour pour éviter le rate limit sur les gros giveaways."""
        existing = self._refresh_tasks.get(giveaway_id)
        if existing is not None and not existing.done():
            return

        async def worker() -> None:
            try:
                await asyncio.sleep(delay)
                await self.refresh(giveaway_id)
            except asyncio.CancelledError:  # pragma: no cover
                raise
            except Exception:  # pragma: no cover
                log.exception("Erreur pendant la mise à jour du giveaway #%s", giveaway_id)
            finally:
                self._refresh_tasks.pop(giveaway_id, None)

        try:
            self._refresh_tasks[giveaway_id] = asyncio.create_task(
                worker(), name=f"vespara-gw-refresh-{giveaway_id}"
            )
        except RuntimeError:  # pragma: no cover - pas de boucle
            pass

    # ------------------------------------------------------------------ #
    # Participation
    # ------------------------------------------------------------------ #
    async def join(self, interaction: discord.Interaction, giveaway_id: str) -> None:
        gw = self.get(giveaway_id)
        if gw is None:
            await reply_ephemeral(interaction, error("Ce giveaway n'existe plus."))
            return
        if gw.get("ended") or float(gw.get("ends_at", 0)) <= time.time():
            await reply_ephemeral(interaction, error("Ce giveaway est déjà terminé."))
            return
        if interaction.guild is None or interaction.guild.id != gw.get("guild_id"):
            await reply_ephemeral(interaction, error("Ce giveaway n'appartient pas à ce serveur."))
            return

        member = interaction.user
        required_role_id = gw.get("required_role_id")
        if (
            required_role_id
            and isinstance(member, discord.Member)
            and not any(role.id == int(required_role_id) for role in member.roles)
        ):
            await reply_ephemeral(
                interaction,
                error(f"Tu dois avoir le rôle <@&{required_role_id}> pour participer."),
            )
            return

        entries: list[int] = gw.setdefault("entries", [])
        if interaction.user.id in entries:
            await reply_ephemeral(
                interaction,
                info(f"Tu participes déjà à **{gw['prize']}**. Bonne chance ! 🍀"),
            )
            return

        entries.append(interaction.user.id)
        self.db.schedule_save(0.5)
        self.schedule_refresh(giveaway_id)
        await reply_ephemeral(
            interaction,
            success(
                f"Tu participes à **{gw['prize']}** !\n"
                f"Fin {timestamp(gw['ends_at'])} · {len(entries)} participant"
                f"{'s' if len(entries) > 1 else ''}.",
                title="Participation enregistrée",
            ),
        )

    async def leave(self, interaction: discord.Interaction, giveaway_id: str) -> None:
        gw = self.get(giveaway_id)
        if gw is None:
            await reply_ephemeral(interaction, error("Ce giveaway n'existe plus."))
            return
        entries: list[int] = gw.setdefault("entries", [])
        if interaction.user.id not in entries:
            await reply_ephemeral(interaction, info("Tu ne participes pas à ce giveaway."))
            return
        if gw.get("ended"):
            await reply_ephemeral(interaction, error("Ce giveaway est déjà terminé."))
            return

        entries.remove(interaction.user.id)
        self.db.schedule_save(0.5)
        self.schedule_refresh(giveaway_id)
        await reply_ephemeral(
            interaction,
            success(f"Tu ne participes plus à **{gw['prize']}**.", title="Participation annulée"),
        )

    async def show_participants(self, interaction: discord.Interaction, giveaway_id: str) -> None:
        gw = self.get(giveaway_id)
        if gw is None:
            await reply_ephemeral(interaction, error("Ce giveaway n'existe plus."))
            return

        entries: list[int] = [int(uid) for uid in gw.get("entries", [])]
        if not entries:
            await reply_ephemeral(
                interaction,
                info(f"Aucun participant pour **{gw['prize']}** pour l'instant."),
            )
            return

        per_page = 30
        pages: list[discord.Embed] = []
        for index in range(0, len(entries), per_page):
            chunk = entries[index : index + per_page]
            emb = embed(
                title=f"{EMOJI['users']} Participants — {truncate(str(gw['prize']), 180)}",
                description="\n".join(f"`{index + pos + 1:>3}.` <@{uid}>" for pos, uid in enumerate(chunk)),
                color=COLOR_GIVEAWAY,
            )
            pages.append(emb)

        view = Paginator(pages, author_id=interaction.user.id, show_close=False)
        await reply_ephemeral(interaction, pages[0], view=view)

    # ------------------------------------------------------------------ #
    # Fin et relance
    # ------------------------------------------------------------------ #
    @staticmethod
    def _pick_winners(gw: dict[str, Any], count: int, *, exclude: Iterable[int] = ()) -> list[int]:
        entries = list(dict.fromkeys(int(uid) for uid in gw.get("entries", [])))
        excluded = set(exclude)
        pool = [uid for uid in entries if uid not in excluded]
        if not pool:
            pool = entries
        if not pool:
            return []
        return random.sample(pool, min(max(1, count), len(pool)))

    async def end(self, gw: dict[str, Any], *, ended_by: discord.abc.User | None = None) -> list[int]:
        giveaway_id = str(gw["id"])
        if gw.get("ended") or giveaway_id in self._ending:
            return list(gw.get("winners", []))
        self._ending.add(giveaway_id)
        try:
            gw["ended"] = True
            gw["ended_at"] = time.time()
            count = int(gw.get("winners_count", 1))
            winners = self._pick_winners(gw, count)
            gw["winners"] = winners
            if ended_by is not None:
                gw["ended_by"] = ended_by.id
            self.db.schedule_save(0.5)
            await self.refresh(giveaway_id, disabled=True)
            await self.announce_winners(gw)
            log.info("Giveaway #%s terminé — gagnants : %s", giveaway_id, winners or "aucun")
            return winners
        finally:
            self._ending.discard(giveaway_id)

    async def announce_winners(self, gw: dict[str, Any]) -> None:
        channel = await self._get_channel(int(gw["channel_id"]))
        if channel is None:
            return

        winners: list[int] = [int(uid) for uid in gw.get("winners", [])]
        jump = f"https://discord.com/channels/{gw['guild_id']}/{gw['channel_id']}/{gw.get('message_id')}"
        if winners:
            mentions = " ".join(f"<@{uid}>" for uid in winners)
            content = (
                f"{EMOJI['party']} Félicitations {mentions} !\n"
                f"Vous remportez **{gw['prize']}** 🎁\n"
                f"<{jump}>"
            )
        else:
            content = (
                f"{EMOJI['warning']} Le giveaway **{gw['prize']}** est terminé sans participant.\n"
                f"<{jump}>"
            )

        try:
            await channel.send(
                content=content,
                allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=False),
                view=RerollView(self.bot, str(gw["id"])),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning("Annonce des gagnants du giveaway #%s impossible : %s", gw["id"], exc)

    async def reroll(
        self,
        gw: dict[str, Any],
        count: int,
        *,
        actor: discord.abc.User | None = None,
    ) -> list[int]:
        previous = [int(uid) for uid in gw.get("winners", [])]
        winners = self._pick_winners(gw, count, exclude=previous)
        if not winners:
            return []

        gw["winners"] = winners
        gw["rerolled_at"] = time.time()
        gw.setdefault("reroll_history", []).append(
            {
                "at": time.time(),
                "by": actor.id if actor else None,
                "winners": winners,
            }
        )
        self.db.schedule_save(0.5)
        await self.refresh(str(gw["id"]), disabled=True)

        channel = await self._get_channel(int(gw["channel_id"]))
        if channel is not None:
            mentions = " ".join(f"<@{uid}>" for uid in winners)
            try:
                await channel.send(
                    content=(
                        f"{EMOJI['dice']} Nouveau tirage pour **{gw['prize']}** : {mentions} ! 🎉"
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True),
                    view=RerollView(self.bot, str(gw["id"])),
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.warning("Annonce du reroll impossible : %s", exc)
        return winners

    async def delete(self, gw: dict[str, Any]) -> bool:
        """Supprime le message du giveaway et son enregistrement."""
        message = await self._get_message(gw)
        if message is not None:
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        removed = self.db.giveaways().pop(str(gw["id"]), None) is not None
        self._message_cache.pop(str(gw["id"]), None)
        self.db.schedule_save(0.5)
        return removed

    # ------------------------------------------------------------------ #
    # Maintenance
    # ------------------------------------------------------------------ #
    async def end_expired(self) -> int:
        """Termine tous les giveaways dont la date est dépassée."""
        ended = 0
        for gw in list(self.db.active_giveaways()):
            if float(gw.get("ends_at", 0)) <= time.time():
                try:
                    await self.end(gw)
                    ended += 1
                except Exception:  # pragma: no cover - un giveaway ne doit pas bloquer les autres
                    log.exception("Impossible de terminer le giveaway #%s", gw.get("id"))
        return ended

    async def restore_views(self) -> None:
        """Ré-enregistre les vues persistantes après un redémarrage."""
        restored = 0
        for gw in list(self.db.giveaways().values()):
            giveaway_id = str(gw["id"])
            if not gw.get("message_id"):
                continue
            self.bot.add_view(GiveawayView(self.bot, giveaway_id, disabled=bool(gw.get("ended"))))
            if gw.get("ended"):
                self.bot.add_view(RerollView(self.bot, giveaway_id))
            restored += 1
        if restored:
            log.info("%s vue(s) de giveaway restaurée(s).", restored)

    async def list_embed(self, guild: discord.Guild) -> discord.Embed:
        return giveaways_embed(self.bot, guild)

    async def close(self) -> None:
        for task in list(self._refresh_tasks.values()):
            if not task.done():
                task.cancel()
        self._refresh_tasks.clear()
