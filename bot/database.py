"""Petite base de données JSON, sans dépendance externe.

Le fichier est chargé au démarrage puis réécrit de manière "atomique" (fichier
temporaire + remplacement) pour éviter de le corrompre. Les sauvegardes sont
regroupées (debounce) afin de ne pas écrire sur le disque à chaque interaction.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DEFAULT_DATA: dict[str, Any] = {
    "version": SCHEMA_VERSION,
    "counter": 0,
    "guilds": {},
    "giveaways": {},
    "autoresponses": {},
    "voice_rooms": {},
}

DEFAULT_GUILD: dict[str, Any] = {
    "staff_role_id": None,
    "announce_channel_id": None,
    "rules": None,
    "autoresponder_cooldown": 8,
    "panel_channel_id": None,
    "created_at": None,
    # Salons vocaux temporaires
    "voice_hub_id": None,
    "voice_hub_name": None,
    "voice_category_id": None,
    "voice_name_template": None,
    "voice_limit": 0,
}


class Database:
    """Accès concurrent-safe (dans un seul process) aux données du bot."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._save_task: asyncio.Task[None] | None = None
        self._closed = False
        self.data: dict[str, Any] = self._read()

    # ------------------------------------------------------------------ #
    # Lecture / écriture du fichier
    # ------------------------------------------------------------------ #
    def _read(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file():
            log.info("Création d'une nouvelle base de données : %s", self.path)
            return copy.deepcopy(DEFAULT_DATA)

        try:
            with self.path.open("r", encoding="utf-8") as fp:
                raw = json.load(fp)
        except (OSError, json.JSONDecodeError) as exc:
            backup = self.path.with_suffix(f".corrupted-{int(time.time())}.json")
            log.error("Base illisible (%s) — sauvegarde dans %s et réinitialisation", exc, backup)
            with contextlib.suppress(OSError):
                self.path.replace(backup)
            return copy.deepcopy(DEFAULT_DATA)

        if not isinstance(raw, dict):
            log.error("Format de base inattendu, réinitialisation.")
            return copy.deepcopy(DEFAULT_DATA)

        for key, default in DEFAULT_DATA.items():
            raw.setdefault(key, copy.deepcopy(default))
        for guild in raw["guilds"].values():
            for key, default in DEFAULT_GUILD.items():
                guild.setdefault(key, copy.deepcopy(default))
        return raw

    def _write_sync(self) -> None:
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fp:
                fp.write(payload)
                fp.flush()
                os.fsync(fp.fileno())
            tmp.replace(self.path)
        except OSError as exc:
            log.error("Impossible d'écrire la base %s : %s", self.path, exc)
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)

    async def save(self) -> None:
        """Sauvegarde immédiate (sérialisée par un verrou)."""
        if self._closed:
            return
        async with self._lock:
            await asyncio.to_thread(self._write_sync)

    def schedule_save(self, delay: float = 2.0) -> None:
        """Programme une sauvegarde groupée dans `delay` secondes."""
        if self._closed:
            return
        if self._save_task and not self._save_task.done():
            return

        async def _later() -> None:
            try:
                await asyncio.sleep(delay)
                await self.save()
            except asyncio.CancelledError:  # pragma: no cover - arrêt propre
                raise
            except Exception:  # pragma: no cover - on ne casse jamais le bot
                log.exception("Échec de la sauvegarde différée")

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Aucune boucle active (script / test) : écriture immédiate.
            self._write_sync()
            return

        self._save_task = asyncio.create_task(_later(), name="vespara-db-save")

    async def close(self) -> None:
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._save_task
        await self.save()
        self._closed = True

    # ------------------------------------------------------------------ #
    # Helpers génériques
    # ------------------------------------------------------------------ #
    def next_id(self) -> str:
        self.data["counter"] = int(self.data.get("counter", 0)) + 1
        return str(self.data["counter"])

    def guild(self, guild_id: int) -> dict[str, Any]:
        """Renvoie (en la créant au besoin) la configuration d'un serveur."""
        key = str(guild_id)
        data = self.data["guilds"].setdefault(key, {})
        for field_name, default in DEFAULT_GUILD.items():
            data.setdefault(field_name, copy.deepcopy(default))
        if data.get("created_at") is None:
            data["created_at"] = time.time()
        return data

    # ------------------------------------------------------------------ #
    # Giveaways
    # ------------------------------------------------------------------ #
    def giveaways(self) -> dict[str, dict[str, Any]]:
        return self.data["giveaways"]

    def get_giveaway(self, giveaway_id: str) -> dict[str, Any] | None:
        return self.data["giveaways"].get(str(giveaway_id))

    def guild_giveaways(self, guild_id: int, *, active_only: bool = True) -> list[dict[str, Any]]:
        items = [g for g in self.data["giveaways"].values() if g.get("guild_id") == guild_id]
        if active_only:
            items = [g for g in items if not g.get("ended")]
        return sorted(items, key=lambda g: g.get("ends_at", 0))

    def active_giveaways(self) -> list[dict[str, Any]]:
        return [g for g in self.data["giveaways"].values() if not g.get("ended")]

    def add_giveaway(self, record: dict[str, Any]) -> dict[str, Any]:
        self.data["giveaways"][str(record["id"])] = record
        self.schedule_save(0.5)
        return record

    def prune_giveaways(self, older_than: float = 60 * 60 * 24 * 30) -> int:
        """Supprime les giveaways terminés depuis plus de `older_than` secondes."""
        now = time.time()
        doomed = [
            gid
            for gid, gw in self.data["giveaways"].items()
            if gw.get("ended") and now - float(gw.get("ended_at") or gw.get("ends_at") or now) > older_than
        ]
        for gid in doomed:
            self.data["giveaways"].pop(gid, None)
        if doomed:
            self.schedule_save()
        return len(doomed)

    # ------------------------------------------------------------------ #
    # Réponses automatiques
    # ------------------------------------------------------------------ #
    def autoresponses(self, guild_id: int) -> list[dict[str, Any]]:
        return self.data["autoresponses"].setdefault(str(guild_id), [])

    def autoreply_by_id(self, guild_id: int, response_id: str) -> dict[str, Any] | None:
        for item in self.autoresponses(guild_id):
            if str(item.get("id")) == str(response_id):
                return item
        return None

    def find_autoreply(self, guild_id: int, trigger: str) -> dict[str, Any] | None:
        needle = trigger.casefold().strip()
        for item in self.autoresponses(guild_id):
            if str(item.get("trigger", "")).casefold().strip() == needle:
                return item
        return None

    def add_autoresponse(self, guild_id: int, record: dict[str, Any]) -> dict[str, Any]:
        self.autoresponses(guild_id).append(record)
        self.schedule_save(0.5)
        return record

    def clear_autoresponses(self, guild_id: int) -> int:
        items = self.autoresponses(guild_id)
        count = len(items)
        if count:
            items.clear()
            self.schedule_save(0.5)
        return count

    def remove_autoresponse(self, guild_id: int, response_id: str) -> bool:
        items = self.autoresponses(guild_id)
        for index, item in enumerate(items):
            if str(item.get("id")) == str(response_id):
                items.pop(index)
                self.schedule_save(0.5)
                return True
        return False

    # ------------------------------------------------------------------ #
    # Salons vocaux temporaires
    # ------------------------------------------------------------------ #
    def voice_rooms(self) -> dict[str, dict[str, Any]]:
        """Tous les salons vocaux temporaires, indexés par identifiant de salon."""
        return self.data.setdefault("voice_rooms", {})

    def voice_room(self, channel_id: int) -> dict[str, Any] | None:
        return self.voice_rooms().get(str(channel_id))

    def guild_voice_rooms(self, guild_id: int) -> list[dict[str, Any]]:
        rooms = [r for r in self.voice_rooms().values() if r.get("guild_id") == guild_id]
        return sorted(rooms, key=lambda r: r.get("created_at", 0))

    def add_voice_room(self, record: dict[str, Any]) -> dict[str, Any]:
        self.voice_rooms()[str(record["channel_id"])] = record
        self.schedule_save(0.5)
        return record

    def remove_voice_room(self, channel_id: int) -> dict[str, Any] | None:
        removed = self.voice_rooms().pop(str(channel_id), None)
        if removed is not None:
            self.schedule_save(0.5)
        return removed

    def voice_room_of(self, guild_id: int, owner_id: int) -> dict[str, Any] | None:
        for record in self.guild_voice_rooms(guild_id):
            if record.get("owner_id") == owner_id:
                return record
        return None

    # ------------------------------------------------------------------ #
    # Statistiques
    # ------------------------------------------------------------------ #
    def stats(self) -> dict[str, int]:
        guilds = self.data["guilds"]
        return {
            "guilds": len(guilds),
            "giveaways": len(self.data["giveaways"]),
            "active_giveaways": len(self.active_giveaways()),
            "autoresponses": sum(len(v) for v in self.data["autoresponses"].values()),
            "voice_rooms": len(self.voice_rooms()),
        }

    @staticmethod
    def new_token_id() -> str:
        """Identifiant aléatoire court (utilisé pour les composants persistants)."""
        return secrets.token_hex(6)
