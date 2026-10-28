"""Salons vocaux temporaires : création automatique et gestion par leur propriétaire.

Le principe
-----------
Un salon vocal « générateur » (le *hub*) est créé par le staff avec
`/vocal installer`. Il est visible et accessible à **tout le monde** : il suffit
de le rejoindre pour que le bot crée instantanément un vocal personnel, y
déplace le membre et publie un **panneau de gestion** dans le chat texte du
salon créé (renommer, verrouiller, limiter, expulser, transférer, supprimer…).

Le salon est supprimé automatiquement dès qu'il est vide.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from typing import TYPE_CHECKING, Any

import discord

from ..checks import resolve_staff_role_id
from ..constants import (
    COLOR,
    COLOR_MUTED,
    COLOR_SUCCESS,
    COLOR_WARNING,
    EMOJI,
    FOOTER,
    TEMPVOICE_DEFAULT_LIMIT,
    TEMPVOICE_DELETE_GRACE,
    TEMPVOICE_HUB_MESSAGE,
    TEMPVOICE_HUB_NAME,
    TEMPVOICE_MAX_LIMIT,
    TEMPVOICE_MAX_ROOMS,
    TEMPVOICE_NAME_MAX_LENGTH,
    TEMPVOICE_NAME_TEMPLATE,
    TEMPVOICE_RECOVERY_MAX_CHANNELS,
)
from ..helpers import progress_bar, truncate, utcnow

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot


log = logging.getLogger(__name__)

PANEL_TITLE = "Panneau de gestion"

# Marqueur machine lisible ajouté dans le pied du panneau : il permet au bot de
# retrouver (ou de retrouver le propriétaire d') un salon même si la base a été
# perdue (redéploiement, disque éphémère…).
PANEL_MARKER = "vespara:temproom"
PANEL_COMPONENT_PREFIX = "vespara:tv:"

_MARKER_RE = re.compile(r"vespara:temproom:(\d+)")
_MENTION_RE = re.compile(r"<@!?(\d+)>")


# --------------------------------------------------------------------------- #
# Utilitaires purs (testables sans Discord)
# --------------------------------------------------------------------------- #
def format_room_name(template: str | None, member: Any, count: int = 0) -> str:
    """Construit le nom du salon à partir du modèle configuré.

    Variables disponibles : ``{user}`` (pseudo affiché), ``{username}`` (nom du
    compte) et ``{count}`` (numéro du salon). Un modèle invalide retombe
    proprement sur « Vocal de pseudo ».
    """
    template = (template or TEMPVOICE_NAME_TEMPLATE).strip() or TEMPVOICE_NAME_TEMPLATE
    display = str(getattr(member, "display_name", None) or getattr(member, "name", "membre"))
    username = str(getattr(member, "name", display))
    # On neutralise les accolades saisies dans le pseudo pour éviter les erreurs
    # de formatage (`{0.__class__}` & co.).
    display = display.replace("{", "(").replace("}", ")")
    username = username.replace("{", "(").replace("}", ")")

    try:
        name = template.format(user=display, username=username, count=count)
    except (KeyError, IndexError, ValueError):
        name = f"Vocal de {display}"

    name = " ".join(name.split()).strip() or f"Vocal de {display}"
    return name[:TEMPVOICE_NAME_MAX_LENGTH]


def is_panel_message(message: Any) -> bool:
    """Ce message est-il un panneau de gestion de vocal temporaire ?"""
    for row in getattr(message, "components", None) or []:
        for child in getattr(row, "children", None) or []:
            custom_id = getattr(child, "custom_id", "") or ""
            if custom_id.startswith(PANEL_COMPONENT_PREFIX):
                return True
    return False


def parse_panel_owner(embeds: Any) -> int | None:
    """Retrouve l'identifiant du propriétaire depuis un panneau existant."""
    for emb in embeds or []:
        footer = getattr(getattr(emb, "footer", None), "text", None) or ""
        match = _MARKER_RE.search(footer)
        if match:
            return int(match.group(1))
        for field in getattr(emb, "fields", []) or []:
            if "Propriétaire" in (field.name or ""):
                mention = _MENTION_RE.search(field.value or "")
                if mention:
                    return int(mention.group(1))
    return None


def owner_from_overwrites(channel: Any) -> int | None:
    """Déduit le propriétaire : premier membre avec « Gérer le salon »."""
    for target, overwrite in (getattr(channel, "overwrites", None) or {}).items():
        if not hasattr(target, "bot"):  # rôle ou membre du bot : on ignore
            continue
        if getattr(target, "bot", False):
            continue
        if getattr(overwrite, "manage_channels", False):
            return int(target.id)
    return None


def record_from_channel(
    channel: Any, owner_id: int, *, panel_message_id: int | None = None
) -> dict[str, Any]:
    """Reconstruit la fiche d'un salon à partir de son état Discord réel."""
    guild = getattr(channel, "guild", None)
    default_role = getattr(guild, "default_role", None)
    bot_user = getattr(getattr(guild, "me", None), "id", None)

    locked = False
    hidden = False
    denied: list[int] = []
    allowed: list[int] = []

    for target, overwrite in (getattr(channel, "overwrites", None) or {}).items():
        if default_role is not None and target is default_role:
            locked = getattr(overwrite, "connect", None) is False
            hidden = getattr(overwrite, "view_channel", None) is False
            continue
        if not hasattr(target, "bot"):
            continue
        if getattr(target, "id", None) in {owner_id, bot_user}:
            continue
        if getattr(overwrite, "connect", None) is False:
            denied.append(int(target.id))
        elif getattr(overwrite, "connect", None) is True:
            allowed.append(int(target.id))

    return {
        "channel_id": int(getattr(channel, "id", 0)),
        "guild_id": int(getattr(guild, "id", 0)),
        "owner_id": int(owner_id),
        "panel_message_id": int(panel_message_id) if panel_message_id else None,
        "created_at": utcnow().timestamp(),
        "locked": locked,
        "hidden": hidden,
        "limit": int(getattr(channel, "user_limit", 0) or 0),
        "denied": sorted(set(denied)),
        "allowed": sorted(set(allowed)),
        "name": str(getattr(channel, "name", "") or ""),
        "recovered": True,
    }


def room_state_label(record: dict[str, Any]) -> str:
    """Résumé lisible de l'état d'un salon (`Public`, `Verrouillé`, `Privé`)."""
    if record.get("hidden"):
        return f"{EMOJI['eye_off']} Privé (invisible)"
    if record.get("locked"):
        return f"{EMOJI['lock']} Verrouillé"
    return f"{EMOJI['unlock']} Public"


def build_room_overwrites(guild: discord.Guild, record: dict[str, Any]) -> dict[Any, discord.PermissionOverwrite]:
    """Permissions du salon temporaire, recalculées à chaque changement d'état."""
    record = record or {}
    locked = bool(record.get("locked"))
    hidden = bool(record.get("hidden"))

    overwrites: dict[Any, discord.PermissionOverwrite] = {}

    default_role = getattr(guild, "default_role", None)
    if default_role is not None:
        overwrites[default_role] = discord.PermissionOverwrite(
            view_channel=not hidden,
            connect=not locked,
            speak=True,
            read_message_history=True,
            send_messages=True,
        )

    me = getattr(guild, "me", None)
    if me is not None:
        overwrites[me] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            send_messages=True,
            manage_channels=True,
            move_members=True,
            manage_messages=True,
            read_message_history=True,
        )

    owner = None
    get_member = getattr(guild, "get_member", None)
    if get_member is not None and record.get("owner_id"):
        owner = get_member(int(record["owner_id"]))
    if owner is not None:
        overwrites[owner] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            move_members=True,
            manage_messages=True,
            priority_speaker=True,
        )

    for user_id in record.get("denied", []) or []:
        member = get_member(int(user_id)) if get_member is not None else None
        if member is not None:
            overwrites[member] = discord.PermissionOverwrite(view_channel=True, connect=False)

    for user_id in record.get("allowed", []) or []:
        member = get_member(int(user_id)) if get_member is not None else None
        if member is not None:
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True, send_messages=True
            )

    return overwrites


def can_manage_room(bot: "VesparaBot", user: Any, guild: discord.Guild | None, record: dict[str, Any]) -> bool:
    """Le membre peut-il gérer ce salon (propriétaire, staff ou admin) ?"""
    if record.get("owner_id") and int(record["owner_id"]) == int(getattr(user, "id", 0)):
        return True

    permissions = getattr(user, "guild_permissions", None)
    if permissions is not None and (permissions.administrator or getattr(permissions, "manage_channels", False)):
        return True

    if guild is not None:
        role_id = resolve_staff_role_id(bot, guild)
        if role_id is not None and any(role.id == role_id for role in getattr(user, "roles", [])):
            return True
    return False


def owner_is_present(channel: Any, record: dict[str, Any]) -> bool:
    """Le propriétaire est-il encore connecté dans son salon ?"""
    owner_id = record.get("owner_id")
    if not owner_id:
        return False
    return any(int(member.id) == int(owner_id) for member in getattr(channel, "members", []))


def room_panel_embed(bot: "VesparaBot", channel: Any, record: dict[str, Any]) -> discord.Embed:
    """Embed du panneau affiché dans le chat texte du salon temporaire."""
    owner_id = int(record.get("owner_id") or 0)
    owner_text = f"<@{owner_id}>" if owner_id else "—"

    members = [member for member in getattr(channel, "members", []) if not member.bot]
    limit = int(record.get("limit") or 0)
    capacity = f"{len(members)}/{limit}" if limit else f"{len(members)}/∞"

    if members:
        names = ", ".join(truncate(member.display_name, 24) for member in members[:15])
        if len(members) > 15:
            names += f" … et {len(members) - 15} autre(s)"
    else:
        names = "*Personne pour le moment*"

    emb = discord.Embed(
        title=f"{EMOJI['mic']} {getattr(channel, 'name', 'Vocal temporaire')}",
        description=(
            f"Tu es dans ton **vocal personnel**, {owner_text}.\n"
            "Utilise les boutons ci-dessous pour le gérer — tout se passe ici, "
            "aucune commande à retenir.\n\u200b"
        ),
        color=state_color(record),
    )
    emb.add_field(name=f"{EMOJI['crown']} Propriétaire", value=owner_text, inline=True)
    emb.add_field(name="État", value=room_state_label(record), inline=True)
    emb.add_field(name=f"{EMOJI['users']} Places", value=capacity, inline=True)
    emb.add_field(name=f"{EMOJI['speaker']} Connectés", value=truncate(names, 1000), inline=False)
    emb.add_field(
        name=f"{EMOJI['tools']} Ce que tu peux faire",
        value=(
            "**Renommer** le salon · **Limiter** les places · **Verrouiller / Déverrouiller** "
            "l'accès\n"
            "**Masquer / Afficher** le salon · **Expulser** un membre · **Autoriser** "
            "quelqu'un\n"
            "**Transférer** la propriété · **Récupérer** le salon si le propriétaire est "
            "parti · **Supprimer** le salon"
        ),
        inline=False,
    )
    emb.set_footer(
        text=(
            f"{FOOTER} • {PANEL_MARKER}:{owner_id} • "
            f"Salon supprimé {int(TEMPVOICE_DELETE_GRACE)} s après être devenu vide"
        )
    )
    emb.timestamp = utcnow()
    return emb


def closing_embed(channel: Any, record: dict[str, Any], seconds: int) -> discord.Embed:
    """Panneau affiché pendant le compte à rebours avant suppression du salon."""
    emb = discord.Embed(
        title=f"{EMOJI['clock']} Salon vide — fermeture dans {seconds} s",
        description=(
            "Personne n'est connecté dans ce vocal.\n\n"
            f"{progress_bar(0.0, 12)}\n"
            "Rejoins-le vite pour annuler la suppression !"
        ),
        color=COLOR_WARNING,
    )
    emb.add_field(name="Propriétaire", value=f"<@{int(record.get('owner_id') or 0)}>", inline=True)
    emb.set_footer(text=f"{FOOTER} • Suppression automatique après {seconds} s")
    return emb


def hub_embed(bot: "VesparaBot", channel: Any) -> discord.Embed:
    """Message d'explication publié dans le chat du salon générateur."""
    emb = discord.Embed(
        title=f"{EMOJI['mic']} Crée ton propre salon vocal",
        description=TEMPVOICE_HUB_MESSAGE,
        color=COLOR,
    )
    emb.add_field(name="Salon générateur", value=getattr(channel, "mention", "—"), inline=True)
    emb.set_footer(text=f"{FOOTER} • Rejoins le salon pour commencer")
    return emb


# --------------------------------------------------------------------------- #
# Gestionnaire
# --------------------------------------------------------------------------- #
class TempVoiceManager:
    """Logique métier des salons vocaux temporaires."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self.db = bot.db
        self.deletion_grace = TEMPVOICE_DELETE_GRACE
        self._deletion_tasks: dict[int, asyncio.Task[None]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    def config(self, guild_id: int) -> dict[str, Any]:
        return self.db.guild(guild_id)

    def hub_id(self, guild_id: int) -> int | None:
        raw = self.config(guild_id).get("voice_hub_id")
        return int(raw) if raw else None

    def hub(self, guild: discord.Guild) -> Any | None:
        hub_id = self.hub_id(guild.id)
        if hub_id is None:
            return None
        channel = guild.get_channel(hub_id)
        if channel is None:
            return None
        return channel

    @staticmethod
    def _channel_id(channel: Any) -> int:
        """Accepte un salon Discord, un identifiant ou un objet compatible."""
        channel_id = getattr(channel, "id", None)
        return int(channel_id if channel_id is not None else channel)

    def room(self, channel: Any) -> dict[str, Any] | None:
        return self.db.voice_room(self._channel_id(channel))

    def is_managed(self, channel: Any) -> bool:
        return self.room(channel) is not None

    def _lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    # ------------------------------------------------------------------ #
    # Création / suppression
    # ------------------------------------------------------------------ #
    async def create_room(self, member: discord.Member, hub: Any) -> Any | None:
        """Crée le vocal personnel du membre et y déplace ce dernier."""
        guild = member.guild
        config = self.config(guild.id)
        rooms = self.db.guild_voice_rooms(guild.id)

        if len(rooms) >= TEMPVOICE_MAX_ROOMS:
            log.warning("Limite de %s salons temporaires atteinte sur %s", TEMPVOICE_MAX_ROOMS, guild.id)
            return None

        existing = self.db.voice_room_of(guild.id, member.id)
        if existing is not None:
            channel = guild.get_channel(int(existing["channel_id"]))
            if channel is not None:
                with contextlib.suppress(discord.HTTPException):
                    await member.move_to(channel, reason="Retour dans son salon personnel")
                await self.refresh_panel(channel, existing)
                return channel
            self.db.remove_voice_room(int(existing["channel_id"]))

        category_id = config.get("voice_category_id")
        category = guild.get_channel(int(category_id)) if category_id else getattr(hub, "category", None)
        if category is not None and not isinstance(category, discord.CategoryChannel):
            category = None

        record: dict[str, Any] = {
            "channel_id": 0,
            "guild_id": guild.id,
            "owner_id": member.id,
            "panel_message_id": None,
            "created_at": utcnow().timestamp(),
            "locked": False,
            "hidden": False,
            "limit": int(config.get("voice_limit") or TEMPVOICE_DEFAULT_LIMIT),
            "denied": [],
            "allowed": [],
            "name": "",
        }
        name = format_room_name(config.get("voice_name_template"), member, len(rooms) + 1)
        record["name"] = name

        async with self._lock(guild.id):
            try:
                channel = await guild.create_voice_channel(
                    name,
                    category=category,
                    user_limit=int(record["limit"]),
                    overwrites=build_room_overwrites(guild, record),
                    reason=f"Vocal temporaire de {member}",
                )
            except discord.HTTPException:
                log.exception("Création du salon temporaire impossible pour %s", member)
                return None

            record["channel_id"] = channel.id
            self.db.add_voice_room(record)
            # Sauvegarde immédiate : un redémarrage ne doit pas « détacher » le salon.
            await self.db.save()

        log.info("Salon temporaire créé : %s (%s) pour %s", channel.name, channel.id, member)

        with contextlib.suppress(discord.HTTPException):
            await member.move_to(channel, reason="Création du salon personnel")

        await self.send_panel(channel, record)
        return channel

    async def delete_room(self, channel: Any, *, reason: str = "Salon temporaire vide") -> None:
        """Supprime le salon (et sa fiche en base)."""
        record = self.room(channel)
        channel_id = self._channel_id(channel)
        self.db.remove_voice_room(int(channel_id))
        await self.db.save()
        task = self._deletion_tasks.pop(int(channel_id), None)
        if task is not None and not task.done():
            task.cancel()
        try:
            await channel.delete(reason=reason)
        except discord.NotFound:
            pass
        except discord.HTTPException:
            log.warning("Suppression du salon %s impossible", channel_id, exc_info=True)
        if record is not None:
            log.info("Salon temporaire supprimé : %s (%s)", record.get("name"), channel_id)

    def _schedule_delete(self, guild: discord.Guild, channel_id: int) -> None:
        """Supprime le salon après un court délai s'il est toujours vide."""
        existing = self._deletion_tasks.get(channel_id)
        if existing is not None and not existing.done():
            return

        async def _later() -> None:
            try:
                record = self.db.voice_room(channel_id)
                channel = guild.get_channel(channel_id)

                # Petit compte à rebours visuel sur le panneau (5 s par défaut).
                if channel is not None and record is not None:
                    with contextlib.suppress(discord.HTTPException, AttributeError):
                        message_id = record.get("panel_message_id")
                        if message_id:
                            await channel.get_partial_message(int(message_id)).edit(
                                embed=closing_embed(
                                    channel, record, max(1, int(round(self.deletion_grace)))
                                )
                            )

                await asyncio.sleep(self.deletion_grace)
                channel = guild.get_channel(channel_id)
                if channel is None:
                    self.db.remove_voice_room(channel_id)
                    return
                if getattr(channel, "members", []):
                    # Quelqu'un est revenu : on restaure le panneau normal.
                    if record is not None:
                        record = self.db.voice_room(channel_id) or record
                        await self.refresh_panel(channel, record)
                    return
                await self.delete_room(channel)
            except asyncio.CancelledError:  # pragma: no cover - arrêt propre
                raise
            except Exception:  # pragma: no cover - jamais bloquant
                log.exception("Suppression différée impossible pour %s", channel_id)
            finally:
                self._deletion_tasks.pop(channel_id, None)

        self._deletion_tasks[channel_id] = asyncio.create_task(_later(), name=f"vespara-tv-delete-{channel_id}")

    def cancel_pending_delete(self, channel_id: int) -> None:
        task = self._deletion_tasks.pop(int(channel_id), None)
        if task is not None and not task.done():
            task.cancel()

    # ------------------------------------------------------------------ #
    # Rattachement automatique (résilience)
    # ------------------------------------------------------------------ #
    async def find_panel_message(self, channel: Any) -> Any | None:
        """Cherche le panneau de gestion dans l'historique du chat du vocal."""
        history = getattr(channel, "history", None)
        if history is None:
            return None
        bot_id = getattr(getattr(self.bot, "user", None), "id", None)
        try:
            async for message in history(limit=50):
                author = getattr(message, "author", None)
                if bot_id is not None and getattr(author, "id", None) != bot_id:
                    continue
                if is_panel_message(message):
                    return message
        except (discord.HTTPException, AttributeError, TypeError, KeyError):
            log.debug("Historique du salon %s illisible", getattr(channel, "id", "?"), exc_info=True)
        return None

    async def adopt(
        self, channel: Any, *, message: Any | None = None, save: bool = True
    ) -> dict[str, Any] | None:
        """Rattache un salon existant au système quand sa fiche a été perdue.

        Le propriétaire est relu dans le panneau (ou déduit des permissions),
        l'état (verrouillé / privé / places / expulsions) est reconstruit depuis
        le salon Discord : un redéploiement ne casse donc plus les vocaux.
        """
        if self.is_managed(channel):
            return self.room(channel)

        guild = getattr(channel, "guild", None)
        if guild is None:
            return None

        hub_id = self.hub_id(guild.id)
        if hub_id is None or self._channel_id(channel) == hub_id:
            return None

        panel = message if message is not None and is_panel_message(message) else None
        if panel is None:
            panel = await self.find_panel_message(channel)

        owner_id = parse_panel_owner(getattr(panel, "embeds", None) or []) if panel else None
        if owner_id is None:
            owner_id = owner_from_overwrites(channel)
        if owner_id is None:
            log.info("Salon %s ignoré : impossible d'identifier un propriétaire", getattr(channel, "id", "?"))
            return None

        record = record_from_channel(channel, owner_id, panel_message_id=getattr(panel, "id", None))
        record["name"] = str(getattr(channel, "name", "") or "")
        self.db.add_voice_room(record)
        if save:
            await self.db.save()
        log.warning(
            "Salon temporaire rattaché : %s (%s) — propriétaire %s (%s)",
            record["name"],
            record["channel_id"],
            owner_id,
            "panneau retrouvé" if panel else "déduit des permissions",
        )
        await self.refresh_panel(channel, record)
        return record

    def candidate_channels(self, guild: discord.Guild) -> list[Any]:
        """Salons vocaux susceptibles d'être d'anciens vocaux temporaires."""
        hub = self.hub(guild)
        hub_id = getattr(hub, "id", None) or self.hub_id(guild.id)
        config = self.config(guild.id)

        category_id = config.get("voice_category_id")
        if not category_id:
            category = getattr(hub, "category", None)
            category_id = getattr(category, "id", None)

        candidates: list[Any] = []
        for channel in getattr(guild, "voice_channels", []) or []:
            if getattr(channel, "id", None) == hub_id:
                continue
            if self.is_managed(channel):
                continue
            if category_id:
                channel_category = getattr(channel, "category", None)
                channel_category_id = getattr(channel_category, "id", None)
                if channel_category_id is not None and channel_category_id != int(category_id):
                    continue
                if channel_category_id is None and getattr(channel, "category", None) is not None:
                    continue
            candidates.append(channel)
            if len(candidates) >= TEMPVOICE_RECOVERY_MAX_CHANNELS:
                break
        return candidates

    async def recover_hub(self, guild: discord.Guild) -> Any | None:
        """Retrouve le salon générateur si sa configuration a été perdue."""
        hub = self.hub(guild)
        if hub is not None:
            return hub

        config = self.config(guild.id)
        expected = (config.get("voice_hub_name") or TEMPVOICE_HUB_NAME).strip()
        match = None
        for channel in getattr(guild, "voice_channels", []) or []:
            if getattr(channel, "name", "") == expected:
                match = channel
                break
        if match is None:
            return None

        config["voice_hub_id"] = match.id
        config["voice_hub_name"] = expected
        await self.db.save()
        log.warning("Salon générateur retrouvé par son nom : %s (%s)", expected, match.id)
        return match

    async def recover_guild(self, guild: discord.Guild) -> dict[str, Any]:
        """Rattache tous les vocaux orphelins d'un serveur."""
        await self.recover_hub(guild)
        if self.hub_id(guild.id) is None:
            return {"adopted": 0, "scanned": 0, "records": []

            }

        candidates = self.candidate_channels(guild)
        records: list[dict[str, Any]] = []
        for channel in candidates:
            try:
                record = await self.adopt(channel, save=False)
                if record is not None:
                    records.append(record)
            except Exception:  # pragma: no cover - un salon ne doit rien bloquer
                log.exception("Rattachement impossible pour %s", getattr(channel, "id", "?"))
        if records:
            await self.db.save()
        return {"adopted": len(records), "scanned": len(candidates), "records": records}

    # ------------------------------------------------------------------ #
    # Panneau
    # ------------------------------------------------------------------ #
    async def send_panel(self, channel: Any, record: dict[str, Any]) -> Any | None:
        """Publie le panneau de gestion dans le chat du salon temporaire."""
        from ..ui.tempvoice import TempVoicePanel  # import tardif (cycle UI ↔ service)

        try:
            message = await channel.send(
                embed=room_panel_embed(self.bot, channel, record),
                view=TempVoicePanel(self.bot),
            )
        except discord.HTTPException:
            log.warning("Impossible de publier le panneau du salon %s", getattr(channel, "id", "?"))
            return None

        record["panel_message_id"] = message.id
        self.db.schedule_save(0.5)
        return message

    async def refresh_panel(self, channel: Any, record: dict[str, Any]) -> None:
        """Met à jour le panneau, ou le republie s'il a été supprimé."""
        from ..ui.tempvoice import TempVoicePanel

        emb = room_panel_embed(self.bot, channel, record)
        message_id = record.get("panel_message_id")
        if message_id:
            try:
                message = channel.get_partial_message(int(message_id))
                await message.edit(embed=emb, view=TempVoicePanel(self.bot))
                return
            except discord.NotFound:
                pass
            except (discord.HTTPException, AttributeError):
                log.debug("Rafraîchissement du panneau impossible pour %s", getattr(channel, "id", "?"))
                return
        await self.send_panel(channel, record)

    async def sync_permissions(self, channel: Any, record: dict[str, Any]) -> None:
        """Applique les permissions correspondant à l'état du salon."""
        guild = getattr(channel, "guild", None)
        if guild is None:
            return
        try:
            await channel.edit(overwrites=build_room_overwrites(guild, record), reason="Gestion du vocal temporaire")
        except discord.HTTPException:
            log.warning("Permissions du salon %s non appliquées", getattr(channel, "id", "?"), exc_info=True)

    def _save(self, *, now: bool = False) -> None:
        """Sauvegarde la base (immédiate pour les changements structurants)."""
        if now:
            self.db.schedule_save(0)
        else:
            self.db.schedule_save(0.5)

    # ------------------------------------------------------------------ #
    # Actions du propriétaire
    # ------------------------------------------------------------------ #
    async def rename(self, channel: Any, record: dict[str, Any], name: str) -> str:
        clean = " ".join(str(name).split()).strip()
        if not clean:
            raise ValueError("Le nom ne peut pas être vide.")
        clean = clean[:TEMPVOICE_NAME_MAX_LENGTH]
        await channel.edit(name=clean, reason="Renommage du vocal temporaire")
        record["name"] = clean
        self._save()
        await self.refresh_panel(channel, record)
        return clean

    async def set_limit(self, channel: Any, record: dict[str, Any], limit: int) -> int:
        limit = max(0, min(TEMPVOICE_MAX_LIMIT, int(limit)))
        await channel.edit(user_limit=limit, reason="Limite de places du vocal temporaire")
        record["limit"] = limit
        self._save()
        await self.refresh_panel(channel, record)
        return limit

    async def set_locked(self, channel: Any, record: dict[str, Any], locked: bool) -> None:
        record["locked"] = bool(locked)
        await self.sync_permissions(channel, record)
        self._save()
        await self.refresh_panel(channel, record)

    async def set_hidden(self, channel: Any, record: dict[str, Any], hidden: bool) -> None:
        record["hidden"] = bool(hidden)
        await self.sync_permissions(channel, record)
        self._save()
        await self.refresh_panel(channel, record)

    async def kick(self, channel: Any, record: dict[str, Any], member: discord.Member) -> None:
        """Expulse un membre du salon et lui en bloque l'accès."""
        if int(member.id) == int(record.get("owner_id") or 0):
            raise ValueError("Le propriétaire ne peut pas s'expulser lui-même.")
        record["denied"] = sorted({int(uid) for uid in record.get("denied", [])} | {member.id})
        record["allowed"] = [int(uid) for uid in record.get("allowed", []) if int(uid) != member.id]
        await self.sync_permissions(channel, record)
        voice = getattr(member, "voice", None)
        if voice is not None and getattr(voice, "channel", None) is not None and voice.channel.id == channel.id:
            with contextlib.suppress(discord.HTTPException):
                await member.move_to(None, reason="Expulsion du vocal temporaire")
        self._save()
        await self.refresh_panel(channel, record)

    async def permit(self, channel: Any, record: dict[str, Any], member: discord.Member) -> None:
        """Autorise explicitement un membre (utile quand le salon est verrouillé)."""
        record["denied"] = [int(uid) for uid in record.get("denied", []) if int(uid) != member.id]
        record["allowed"] = sorted({int(uid) for uid in record.get("allowed", [])} | {member.id})
        # Le salon peut rester verrouillé : l'autorisation est nominative.
        await self.sync_permissions(channel, record)
        self._save()
        await self.refresh_panel(channel, record)

    async def transfer(self, channel: Any, record: dict[str, Any], member: discord.Member) -> None:
        """Transfère la propriété du salon."""
        if int(member.id) == int(record.get("owner_id") or 0):
            raise ValueError("Ce membre est déjà le propriétaire du salon.")
        record["owner_id"] = member.id
        record["denied"] = [int(uid) for uid in record.get("denied", []) if int(uid) != member.id]
        await self.sync_permissions(channel, record)
        self._save(now=True)
        await self.refresh_panel(channel, record)

    async def claim(self, channel: Any, record: dict[str, Any], member: discord.Member) -> None:
        """Récupère le salon quand le propriétaire n'est plus là."""
        if owner_is_present(channel, record):
            raise ValueError("Le propriétaire est encore dans le salon.")
        await self.transfer(channel, record, member)

    # ------------------------------------------------------------------ #
    # Événements vocaux
    # ------------------------------------------------------------------ #
    async def handle_voice_update(
        self,
        member: discord.Member,
        before: Any,
        after: Any,
    ) -> None:
        """Point d'entrée de `on_voice_state_update`."""
        if getattr(member, "bot", False):
            return
        guild = getattr(member, "guild", None)
        if guild is None:
            return

        arrived = getattr(after, "channel", None)
        left = getattr(before, "channel", None)

        # Quelqu'un revient dans un salon en attente de suppression : on annule.
        if arrived is not None and self.is_managed(arrived):
            self.cancel_pending_delete(arrived.id)

        # Entrée dans le salon générateur → création du vocal personnel.
        hub_id = self.hub_id(guild.id)
        if (
            arrived is not None
            and hub_id is not None
            and arrived.id == hub_id
            and (left is None or left.id != hub_id)
        ):
            await self.create_room(member, arrived)
            return

        # Sortie d'un salon temporaire → transfert éventuel puis nettoyage.
        if left is None or left.id == hub_id or not self.is_managed(left):
            return

        record = self.room(left)
        if record is None:
            return

        channel = guild.get_channel(left.id) or left
        remaining = [m for m in getattr(channel, "members", []) if not getattr(m, "bot", False)]

        if not remaining:
            self._schedule_delete(guild, left.id)
            return

        if int(record.get("owner_id") or 0) == member.id:
            # Le propriétaire est parti : on passe le salon au membre suivant.
            try:
                await self.transfer(channel, record, remaining[0])
            except (ValueError, discord.HTTPException):
                log.debug("Transfert automatique impossible pour %s", left.id, exc_info=True)

    # ------------------------------------------------------------------ #
    # Maintenance
    # ------------------------------------------------------------------ #
    async def prune(self) -> int:
        """Supprime les fiches dont le salon n'existe plus (redémarrage, suppression manuelle)."""
        removed = 0
        for key, record in list(self.db.voice_rooms().items()):
            guild = self.bot.get_guild(int(record.get("guild_id") or 0))
            channel = guild.get_channel(int(record.get("channel_id") or 0)) if guild else None
            if channel is None:
                self.db.voice_rooms().pop(key, None)
                removed += 1
        if removed:
            self.db.schedule_save(0.5)
            log.info("%s salon(s) temporaire(s) orphelin(s) nettoyé(s)", removed)
        return removed

    async def close(self) -> None:
        for task in list(self._deletion_tasks.values()):
            task.cancel()
        self._deletion_tasks.clear()


# --------------------------------------------------------------------------- #
# Aides de couleur pour l'UI
# --------------------------------------------------------------------------- #
def state_color(record: dict[str, Any]) -> int:
    if record.get("hidden"):
        return COLOR_MUTED
    if record.get("locked"):
        return COLOR_WARNING
    return COLOR_SUCCESS


__all__ = [
    "PANEL_TITLE",
    "TempVoiceManager",
    "build_room_overwrites",
    "can_manage_room",
    "format_room_name",
    "hub_embed",
    "owner_is_present",
    "room_panel_embed",
    "room_state_label",
    "state_color",
]
