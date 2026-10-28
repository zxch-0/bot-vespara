"""Tests des salons vocaux temporaires (sans connexion Discord)."""

from __future__ import annotations

import asyncio
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any

import discord

from bot.database import Database
from bot.services.tempvoice import (
    TempVoiceManager,
    build_room_overwrites,
    can_manage_room,
    format_room_name,
    room_panel_embed,
    room_state_label,
)


# --------------------------------------------------------------------------- #
# Doubles de test
# --------------------------------------------------------------------------- #
class FakeComponent:
    def __init__(self, custom_id: str) -> None:
        self.custom_id = custom_id


class FakeRow:
    def __init__(self, *custom_ids: str) -> None:
        self.children = [FakeComponent(custom_id) for custom_id in custom_ids]


class FakeMessage:
    def __init__(
        self,
        message_id: int,
        *,
        author: Any = None,
        embeds: list[Any] | None = None,
        components: list[Any] | None = None,
    ) -> None:
        self.id = message_id
        self.edits: list[dict[str, Any]] = []
        self.deleted = False
        self.jump_url = f"https://discord.test/{message_id}"
        self.author = author or types.SimpleNamespace(id=0)
        self.embeds = embeds or []
        self.components = components or []

    async def edit(self, **kwargs: Any) -> "FakeMessage":
        self.edits.append(kwargs)
        return self

    async def delete(self) -> None:
        self.deleted = True


class FakePartialMessage:
    """Message non chargé : `edit` échoue en NotFound s'il a été supprimé."""

    def __init__(self, channel: "FakeVoiceChannel", message_id: int) -> None:
        self.channel = channel
        self.id = message_id

    async def edit(self, **kwargs: Any) -> FakeMessage:
        if self.id not in self.channel._messages:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        return await self.channel._messages[self.id].edit(**kwargs)


class FakeMember:
    def __init__(
        self,
        member_id: int,
        guild: "FakeGuild",
        name: str = "Membre",
        *,
        bot: bool = False,
        roles: list[Any] | None = None,
        permissions: discord.Permissions | None = None,
    ) -> None:
        self.id = member_id
        self.guild = guild
        self.name = name
        self.display_name = name
        self.bot = bot
        self.roles = roles or []
        self.guild_permissions = permissions or discord.Permissions.none()
        self.voice = types.SimpleNamespace(channel=None)
        self.moves: list[Any] = []

    def __str__(self) -> str:
        return self.display_name

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    async def move_to(self, channel: Any, reason: str | None = None) -> None:
        if self.voice.channel is not None and self in self.voice.channel.members:
            self.voice.channel.members.remove(self)
        self.voice.channel = channel
        self.moves.append(channel)
        if channel is not None:
            channel.members.append(self)


class FakeRole:
    def __init__(self, role_id: int = 1) -> None:
        self.id = role_id
        self.name = "@everyone"


class FakeVoiceChannel:
    def __init__(
        self,
        guild: "FakeGuild",
        name: str,
        channel_id: int,
        *,
        category: Any = None,
        overwrites: dict[Any, Any] | None = None,
        user_limit: int = 0,
    ) -> None:
        self.id = channel_id
        self.name = name
        self.guild = guild
        self.category = category
        self.overwrites = dict(overwrites or {})
        self.user_limit = user_limit
        self.members: list[FakeMember] = []
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.deleted = False
        self._messages: dict[int, FakeMessage] = {}
        self._counter = 5000

    @property
    def mention(self) -> str:
        return f"<#{self.id}>"

    async def send(self, **kwargs: Any) -> FakeMessage:
        self._counter += 1
        view = kwargs.get("view")
        components = [
            FakeRow(*[item.custom_id for item in getattr(view, "children", []) if getattr(item, "custom_id", None)])
        ] if view is not None else []
        message = FakeMessage(
            self._counter,
            author=getattr(getattr(self, "guild", None), "me", None),
            embeds=[kwargs["embed"]] if kwargs.get("embed") else [],
            components=components,
        )
        self._messages[message.id] = message
        self.sent.append(kwargs)
        return message

    async def fetch_message(self, message_id: int) -> FakeMessage:
        return self._messages[message_id]

    async def history(self, limit: int = 50):
        for message in list(self._messages.values())[-limit:]:
            yield message

    def get_partial_message(self, message_id: int) -> FakeMessage:
        return FakePartialMessage(self, message_id)

    async def edit(self, **kwargs: Any) -> "FakeVoiceChannel":
        self.edits.append(kwargs)
        if "name" in kwargs:
            self.name = kwargs["name"]
        if "user_limit" in kwargs:
            self.user_limit = kwargs["user_limit"]
        if "overwrites" in kwargs:
            self.overwrites = dict(kwargs["overwrites"])
        return self

    async def delete(self, reason: str | None = None) -> None:
        self.deleted = True
        self.guild.channels.pop(self.id, None)


class FakeGuild:
    def __init__(self, guild_id: int = 1) -> None:
        self.id = guild_id
        self.name = "Vespara"
        self.icon = None
        self.default_role = FakeRole(1)
        self.me = FakeMember(999, self, "Vespara", bot=True, permissions=discord.Permissions.all())
        self.channels: dict[int, Any] = {}
        self.members_by_id: dict[int, FakeMember] = {999: self.me}
        self._next_id = 1000

    @property
    def voice_channels(self) -> list[Any]:
        return [channel for channel in self.channels.values() if isinstance(channel, FakeVoiceChannel)]

    def get_channel(self, channel_id: int) -> Any | None:
        return self.channels.get(int(channel_id))

    def get_member(self, member_id: int) -> FakeMember | None:
        return self.members_by_id.get(int(member_id))

    def add_member(self, member: FakeMember) -> FakeMember:
        self.members_by_id[member.id] = member
        return member

    async def create_voice_channel(
        self,
        name: str,
        *,
        category: Any = None,
        user_limit: int = 0,
        overwrites: dict[Any, Any] | None = None,
        reason: str | None = None,
    ) -> FakeVoiceChannel:
        self._next_id += 1
        channel = FakeVoiceChannel(
            self, name, self._next_id, category=category, overwrites=overwrites, user_limit=user_limit
        )
        self.channels[channel.id] = channel
        return channel


class FakeBot:
    def __init__(self, database: Database, guild: FakeGuild) -> None:
        self.db = database
        self.settings = types.SimpleNamespace(brand="Vespara", tagline="Le serveur chill", staff_role_id=None)
        self.guild = guild
        self.guilds = [guild]

    def get_guild(self, guild_id: int) -> FakeGuild | None:
        return self.guild if int(guild_id) == self.guild.id else None


# --------------------------------------------------------------------------- #
# Helpers purs
# --------------------------------------------------------------------------- #
class RoomNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guild = FakeGuild()
        self.member = FakeMember(7, self.guild, "Léa 🍃")

    def test_default_template(self) -> None:
        self.assertEqual(format_room_name(None, self.member), "Vocal de Léa 🍃")

    def test_custom_template(self) -> None:
        self.assertEqual(format_room_name("{user} · 🔊", self.member), "Léa 🍃 · 🔊")
        self.assertEqual(format_room_name("Salon n°{count}", self.member, 4), "Salon n°4")
        self.assertEqual(format_room_name("Vocal de {username}", self.member), "Vocal de Léa 🍃")

    def test_invalid_template_falls_back(self) -> None:
        self.assertEqual(format_room_name("{inconnu}", self.member), "Vocal de Léa 🍃")
        self.assertEqual(format_room_name("{", self.member), "Vocal de Léa 🍃")

    def test_braces_are_neutralised(self) -> None:
        member = FakeMember(8, self.guild, "{user.__class__}")
        self.assertEqual(format_room_name("Vocal de {user}", member), "Vocal de (user.__class__)")

    def test_length_is_capped(self) -> None:
        member = FakeMember(9, self.guild, "x" * 300)
        self.assertLessEqual(len(format_room_name("{user}", member)), 100)


class OverwriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guild = FakeGuild()
        self.owner = self.guild.add_member(FakeMember(42, self.guild, "Proprio"))

    def test_public_room(self) -> None:
        record = {"owner_id": 42, "locked": False, "hidden": False}
        overwrites = build_room_overwrites(self.guild, record)

        everyone = overwrites[self.guild.default_role]
        self.assertTrue(everyone.view_channel)
        self.assertTrue(everyone.connect)

        owner = overwrites[self.owner]
        self.assertTrue(owner.manage_channels)
        self.assertTrue(owner.move_members)

        bot_overwrite = overwrites[self.guild.me]
        self.assertTrue(bot_overwrite.manage_channels)

    def test_locked_and_hidden(self) -> None:
        record = {"owner_id": 42, "locked": True, "hidden": True}
        everyone = build_room_overwrites(self.guild, record)[self.guild.default_role]
        self.assertFalse(everyone.connect)
        self.assertFalse(everyone.view_channel)
        self.assertEqual(room_state_label(record), "🙈 Privé (invisible)")

    def test_denied_and_allowed_members(self) -> None:
        banned = self.guild.add_member(FakeMember(100, self.guild, "Banni"))
        allowed = self.guild.add_member(FakeMember(101, self.guild, "Invité"))
        record = {"owner_id": 42, "denied": [100], "allowed": [101]}
        overwrites = build_room_overwrites(self.guild, record)
        self.assertFalse(overwrites[banned].connect)
        self.assertTrue(overwrites[allowed].connect)

    def test_state_labels(self) -> None:
        self.assertIn("Public", room_state_label({}))
        self.assertIn("Verrouillé", room_state_label({"locked": True}))


class PermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guild = FakeGuild()
        self.bot = FakeBot(Database(":memory:"), self.guild)
        self.record = {"owner_id": 42}

    def test_owner_can_manage(self) -> None:
        self.assertTrue(can_manage_room(self.bot, FakeMember(42, self.guild), self.guild, self.record))

    def test_other_member_cannot_manage(self) -> None:
        member = FakeMember(43, self.guild)
        self.assertFalse(can_manage_room(self.bot, member, self.guild, self.record))

    def test_admin_can_manage(self) -> None:
        admin = FakeMember(44, self.guild, permissions=discord.Permissions(administrator=True))
        self.assertTrue(can_manage_room(self.bot, admin, self.guild, self.record))

    def test_staff_role_can_manage(self) -> None:
        role = FakeRole(777)
        self.bot.db.guild(self.guild.id)["staff_role_id"] = role.id
        staff = FakeMember(45, self.guild, roles=[role])
        self.assertTrue(can_manage_room(self.bot, staff, self.guild, self.record))


# --------------------------------------------------------------------------- #
# Gestionnaire
# --------------------------------------------------------------------------- #
class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.json")
        self.guild = FakeGuild()
        self.bot = FakeBot(self.db, self.guild)
        self.manager = TempVoiceManager(self.bot)  # type: ignore[arg-type]
        self.manager.deletion_grace = 0

        self.hub = FakeVoiceChannel(self.guild, "➕ Créer ton vocal", 900)
        self.guild.channels[self.hub.id] = self.hub
        settings = self.db.guild(self.guild.id)
        settings["voice_hub_id"] = self.hub.id
        settings["voice_name_template"] = "Vocal de {user}"

        self.owner = self.guild.add_member(FakeMember(42, self.guild, "Léa"))
        self.other = self.guild.add_member(FakeMember(43, self.guild, "Max"))

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        await self.db.close()
        self.tmp.cleanup()

    async def _join_hub(self, member: FakeMember) -> Any:
        before = types.SimpleNamespace(channel=None)
        after = types.SimpleNamespace(channel=self.hub)
        await self.manager.handle_voice_update(member, before, after)
        return self.db.voice_room_of(self.guild.id, member.id)

    def _leave(self, member: FakeMember, channel: Any) -> Any:
        return types.SimpleNamespace(channel=channel), types.SimpleNamespace(channel=None)

    # ------------------------------------------------------------------ #
    async def test_join_hub_creates_room(self) -> None:
        record = await self._join_hub(self.owner)
        self.assertIsNotNone(record)

        channel = self.guild.get_channel(record["channel_id"])
        self.assertIsNotNone(channel)
        self.assertEqual(channel.name, "Vocal de Léa")
        self.assertEqual(self.owner.voice.channel, channel)
        self.assertEqual(record["owner_id"], self.owner.id)
        self.assertIn(self.guild.default_role, channel.overwrites)

        # Le panneau de gestion est publié immédiatement dans le chat du vocal
        self.assertEqual(len(channel.sent), 1)
        self.assertIn("embed", channel.sent[0])
        self.assertIsNotNone(channel.sent[0]["view"])
        self.assertIsNotNone(record["panel_message_id"])

    async def test_rejoining_hub_returns_to_existing_room(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])
        self.owner.voice.channel = None
        channel.members.clear()

        second = await self._join_hub(self.owner)
        self.assertEqual(second["channel_id"], record["channel_id"])
        self.assertEqual(len(self.db.guild_voice_rooms(self.guild.id)), 1)
        self.assertEqual(self.owner.voice.channel, channel)

    async def test_second_member_gets_its_own_room(self) -> None:
        first = await self._join_hub(self.owner)
        second = await self._join_hub(self.other)
        self.assertNotEqual(first["channel_id"], second["channel_id"])
        self.assertEqual(len(self.db.guild_voice_rooms(self.guild.id)), 2)

    async def test_empty_room_is_deleted(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])

        before, after = self._leave(self.owner, channel)
        self.owner.voice.channel = None
        channel.members.clear()
        await self.manager.handle_voice_update(self.owner, before, after)

        await asyncio.sleep(0.1)
        self.assertTrue(channel.deleted)
        self.assertIsNone(self.db.voice_room(record["channel_id"]))

    async def test_owner_leaving_transfers_the_room(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])

        # Max rejoint le salon de Léa et Léa s'en va
        self.other.voice.channel = channel
        channel.members.append(self.other)

        before, after = self._leave(self.owner, channel)
        self.owner.voice.channel = None
        channel.members.remove(self.owner)
        await self.manager.handle_voice_update(self.owner, before, after)

        self.assertEqual(record["owner_id"], self.other.id)
        self.assertFalse(channel.deleted)

    async def test_room_survives_briefly_when_not_empty(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])
        self.other.voice.channel = channel
        channel.members.append(self.other)

        before, after = self._leave(self.owner, channel)
        channel.members.remove(self.owner)
        await self.manager.handle_voice_update(self.owner, before, after)
        await asyncio.sleep(0.05)
        self.assertFalse(channel.deleted)

    # ------------------------------------------------------------------ #
    async def test_delete_room_cleans_database(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])
        await self.manager.delete_room(channel)
        self.assertTrue(channel.deleted)
        self.assertIsNone(self.db.voice_room(record["channel_id"]))

    async def test_rename_and_limit(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])

        name = await self.manager.rename(channel, record, "  Chill & musique  ")
        self.assertEqual(name, "Chill & musique")
        self.assertEqual(channel.name, "Chill & musique")
        self.assertEqual(record["name"], "Chill & musique")

        await self.manager.set_limit(channel, record, 5)
        self.assertEqual(channel.user_limit, 5)
        self.assertEqual(record["limit"], 5)

        # Le panneau est rafraîchi après chaque action
        self.assertTrue(channel._messages[record["panel_message_id"]].edits)

    async def test_rename_rejects_empty_name(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])
        with self.assertRaises(ValueError):
            await self.manager.rename(channel, record, "   ")

    async def test_lock_hide_and_unlock(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])

        await self.manager.set_locked(channel, record, True)
        self.assertTrue(record["locked"])
        self.assertFalse(channel.overwrites[self.guild.default_role].connect)

        await self.manager.set_hidden(channel, record, True)
        self.assertFalse(channel.overwrites[self.guild.default_role].view_channel)

        await self.manager.set_locked(channel, record, False)
        await self.manager.set_hidden(channel, record, False)
        everyone = channel.overwrites[self.guild.default_role]
        self.assertTrue(everyone.connect)
        self.assertTrue(everyone.view_channel)

    async def test_kick_and_permit(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])
        self.other.voice.channel = channel
        channel.members.append(self.other)

        await self.manager.kick(channel, record, self.other)
        self.assertIn(self.other.id, record["denied"])
        self.assertIsNone(self.other.voice.channel)
        self.assertFalse(channel.overwrites[self.other].connect)

        with self.assertRaises(ValueError):
            await self.manager.kick(channel, record, self.owner)

        await self.manager.permit(channel, record, self.other)
        self.assertNotIn(self.other.id, record["denied"])
        self.assertIn(self.other.id, record["allowed"])
        self.assertTrue(channel.overwrites[self.other].connect)

    async def test_transfer_and_claim(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])
        self.other.voice.channel = channel
        channel.members.append(self.other)

        await self.manager.transfer(channel, record, self.other)
        self.assertEqual(record["owner_id"], self.other.id)
        self.assertNotIn(self.owner, channel.overwrites)
        self.assertIn(self.other, channel.overwrites)

        # Le propriétaire est présent : impossible de récupérer le salon
        with self.assertRaises(ValueError):
            await self.manager.claim(channel, record, self.owner)

        # Le propriétaire part : Léa peut récupérer le salon
        channel.members = [self.owner]
        self.owner.voice.channel = channel
        await self.manager.claim(channel, record, self.owner)
        self.assertEqual(record["owner_id"], self.owner.id)

    async def test_panel_embed_content(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])
        emb = room_panel_embed(self.bot, channel, record)

        self.assertIn(channel.name, emb.title)
        values = {field.name: field.value for field in emb.fields}
        self.assertIn(f"<@{self.owner.id}>", values["👑 Propriétaire"])
        self.assertIn("Léa", values["🔊 Connectés"])

    async def test_prune_removes_orphan_records(self) -> None:
        record = await self._join_hub(self.owner)
        channel = self.guild.get_channel(record["channel_id"])
        self.guild.channels.pop(channel.id)  # salon supprimé hors du bot

        removed = await self.manager.prune()
        self.assertEqual(removed, 1)
        self.assertIsNone(self.db.voice_room(record["channel_id"]))

    async def test_room_limit_is_respected(self) -> None:
        from bot.constants import TEMPVOICE_MAX_ROOMS

        for index in range(TEMPVOICE_MAX_ROOMS):
            self.db.add_voice_room({"channel_id": 10_000 + index, "guild_id": self.guild.id, "owner_id": index})
        self.assertIsNone(await self.manager.create_room(self.owner, self.hub))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


# --------------------------------------------------------------------------- #
# Panneau de gestion (boutons)
# --------------------------------------------------------------------------- #
class FakeResponse:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.modal: Any = None
        self.deferred = False
        self.edited: dict[str, Any] | None = None

    def is_done(self) -> bool:
        return bool(self.messages or self.modal or self.deferred)

    async def send_message(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)

    async def send_modal(self, modal: Any) -> None:
        self.modal = modal
        self.messages.append({"modal": modal})

    async def defer(self, **kwargs: Any) -> None:
        self.deferred = True

    async def edit_message(self, **kwargs: Any) -> None:
        self.edited = kwargs


class FakeFollowup:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


class FakeInteraction:
    def __init__(self, user: FakeMember, channel: Any, client: Any) -> None:
        self.user = user
        self.channel = channel
        self.channel_id = channel.id
        self.guild = channel.guild
        self.client = client
        self.response = FakeResponse()
        self.followup = FakeFollowup()


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.json")
        self.guild = FakeGuild()
        self.bot = FakeBot(self.db, self.guild)
        self.manager = TempVoiceManager(self.bot)  # type: ignore[arg-type]
        self.manager.deletion_grace = 0
        self.bot.tempvoice = self.manager  # type: ignore[attr-defined]

        self.hub = FakeVoiceChannel(self.guild, "➕ Créer ton vocal", 900)
        self.guild.channels[self.hub.id] = self.hub
        self.db.guild(self.guild.id)["voice_hub_id"] = self.hub.id

        self.owner = self.guild.add_member(FakeMember(42, self.guild, "Léa"))
        self.other = self.guild.add_member(FakeMember(43, self.guild, "Max"))
        self.channel = await self.manager.create_room(self.owner, self.hub)
        self.record = self.db.voice_room_of(self.guild.id, self.owner.id)

        from bot.ui.tempvoice import TempVoicePanel

        self.panel = TempVoicePanel(self.bot)  # type: ignore[arg-type]

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        await self.db.close()
        self.tmp.cleanup()

    def interaction(self, user: FakeMember | None = None) -> FakeInteraction:
        return FakeInteraction(user or self.owner, self.channel, self.bot)

    # ------------------------------------------------------------------ #
    def test_panel_has_all_actions(self) -> None:
        ids = {item.custom_id for item in self.panel.children}
        expected = {
            "vespara:tv:rename",
            "vespara:tv:limit",
            "vespara:tv:lock",
            "vespara:tv:unlock",
            "vespara:tv:hide",
            "vespara:tv:show",
            "vespara:tv:kick",
            "vespara:tv:permit",
            "vespara:tv:transfer",
            "vespara:tv:claim",
            "vespara:tv:delete",
            "vespara:tv:refresh",
        }
        self.assertEqual(ids, expected)
        self.assertTrue(self.panel.is_persistent())

    async def test_lock_button_from_owner(self) -> None:
        interaction = self.interaction()
        self.assertTrue(await self.panel.interaction_check(interaction))
        await self.panel.lock.callback(interaction)  # type: ignore[union-attr]
        self.assertTrue(self.record["locked"])
        self.assertIn("verrouillé", interaction.response.messages[-1]["embed"].description.lower())

    async def test_button_refused_for_stranger(self) -> None:
        interaction = self.interaction(self.other)
        await self.panel.lock.callback(interaction)  # type: ignore[union-attr]
        self.assertFalse(self.record["locked"])
        self.assertIn("propriétaire", interaction.response.messages[-1]["embed"].description.lower())

    async def test_rename_modal_updates_channel(self) -> None:
        interaction = self.interaction()
        await self.panel.rename.callback(interaction)  # type: ignore[union-attr]
        modal = interaction.response.modal
        self.assertIsNotNone(modal)

        modal.name_input._value = "Soirée chill 🎶"
        submit = FakeInteraction(self.owner, self.channel, self.bot)
        await modal.on_submit(submit)  # type: ignore[arg-type]
        self.assertEqual(self.channel.name, "Soirée chill 🎶")

    async def test_limit_modal_rejects_invalid_input(self) -> None:
        interaction = self.interaction()
        await self.panel.limit.callback(interaction)  # type: ignore[union-attr]
        modal = interaction.response.modal

        modal.limit_input._value = "beaucoup"
        submit = FakeInteraction(self.owner, self.channel, self.bot)
        await modal.on_submit(submit)  # type: ignore[arg-type]
        self.assertIn("nombre", submit.response.messages[-1]["embed"].description.lower())

        modal.limit_input._value = "3"
        ok = FakeInteraction(self.owner, self.channel, self.bot)
        await modal.on_submit(ok)  # type: ignore[arg-type]
        self.assertEqual(self.channel.user_limit, 3)

    async def test_kick_flow(self) -> None:
        self.other.voice.channel = self.channel
        self.channel.members.append(self.other)

        interaction = self.interaction()
        await self.panel.kick.callback(interaction)  # type: ignore[union-attr]
        view = interaction.response.messages[-1]["view"]
        select = view.children[0]
        select._values = [str(self.other.id)]

        confirm = FakeInteraction(self.owner, self.channel, self.bot)
        await select.callback(confirm)
        self.assertIn(self.other.id, self.record["denied"])
        self.assertIsNone(self.other.voice.channel)
        self.assertIn("expulsé", confirm.response.edited["embed"].description)

    async def test_claim_requires_absent_owner_and_membership(self) -> None:
        # Max n'est pas connecté : refus
        interaction = self.interaction(self.other)
        await self.panel.claim.callback(interaction)  # type: ignore[union-attr]
        self.assertIn("rejoins", interaction.response.messages[-1]["embed"].description.lower())

        # Max rejoint le salon mais Léa est là : refus
        self.other.voice.channel = self.channel
        self.channel.members.append(self.owner)
        self.channel.members.append(self.other)
        second = self.interaction(self.other)
        await self.panel.claim.callback(second)  # type: ignore[union-attr]
        self.assertIn("encore", second.response.messages[-1]["embed"].description.lower())
        self.assertEqual(self.record["owner_id"], self.owner.id)

        # Léa s'en va : Max récupère le salon
        self.channel.members = [self.other]
        self.owner.voice.channel = None
        third = self.interaction(self.other)
        await self.panel.claim.callback(third)  # type: ignore[union-attr]
        self.assertEqual(self.record["owner_id"], self.other.id)

    async def test_refresh_republishes_deleted_panel(self) -> None:
        old_id = self.record["panel_message_id"]
        self.channel._messages.pop(old_id)

        interaction = self.interaction()
        await self.panel.refresh.callback(interaction)  # type: ignore[union-attr]
        self.assertTrue(interaction.response.deferred)
        self.assertNotEqual(self.record["panel_message_id"], old_id)
        self.assertEqual(len(self.channel.sent), 2)

    async def test_panel_outside_managed_room(self) -> None:
        from bot.ui.tempvoice import TempVoicePanel

        stranger_channel = FakeVoiceChannel(self.guild, "général", 4242)
        self.guild.channels[stranger_channel.id] = stranger_channel
        interaction = FakeInteraction(self.owner, stranger_channel, self.bot)
        panel = TempVoicePanel(self.bot)  # type: ignore[arg-type]
        self.assertFalse(await panel.interaction_check(interaction))
        self.assertIn(
            "vocaux temporaires", interaction.response.messages[-1]["embed"].description
        )


# --------------------------------------------------------------------------- #
# Rattachement automatique (résilience après perte de la base)
# --------------------------------------------------------------------------- #
class PanelParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guild = FakeGuild()
        self.owner = self.guild.add_member(FakeMember(42, self.guild, "Léa"))

    def test_is_panel_message(self) -> None:
        from bot.services.tempvoice import is_panel_message

        panel = FakeMessage(1, components=[FakeRow("vespara:tv:rename", "vespara:tv:lock")])
        other = FakeMessage(2, components=[FakeRow("autre:button")])
        self.assertTrue(is_panel_message(panel))
        self.assertFalse(is_panel_message(other))
        self.assertFalse(is_panel_message(FakeMessage(3)))

    def test_parse_owner_from_marker_and_field(self) -> None:
        from bot.services.tempvoice import parse_panel_owner

        marked = discord.Embed(title="x")
        marked.set_footer(text="Vespara • vespara:temproom:42 • Salon temporaire")
        self.assertEqual(parse_panel_owner([marked]), 42)

        field_based = discord.Embed(title="x")
        field_based.add_field(name="👑 Propriétaire", value="<@!43>", inline=True)
        self.assertEqual(parse_panel_owner([field_based]), 43)
        self.assertIsNone(parse_panel_owner([]))

    def test_owner_from_overwrites(self) -> None:
        from bot.services.tempvoice import owner_from_overwrites

        channel = FakeVoiceChannel(self.guild, "vocal", 1)
        channel.overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(connect=True),
            self.guild.me: discord.PermissionOverwrite(manage_channels=True),
            self.owner: discord.PermissionOverwrite(manage_channels=True),
            self.guild.add_member(FakeMember(50, self.guild, "Autre")): discord.PermissionOverwrite(
                connect=False
            ),
        }
        self.assertEqual(owner_from_overwrites(channel), self.owner.id)

    def test_record_from_channel_reads_discord_state(self) -> None:
        from bot.services.tempvoice import record_from_channel

        channel = FakeVoiceChannel(self.guild, "Chill", 7, user_limit=4)
        banned = self.guild.add_member(FakeMember(60, self.guild, "Banni"))
        invited = self.guild.add_member(FakeMember(61, self.guild, "Invité"))
        channel.overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=False),
            self.owner: discord.PermissionOverwrite(manage_channels=True),
            banned: discord.PermissionOverwrite(connect=False),
            invited: discord.PermissionOverwrite(connect=True),
        }

        record = record_from_channel(channel, self.owner.id, panel_message_id=12)
        self.assertEqual(record["channel_id"], 7)
        self.assertEqual(record["guild_id"], self.guild.id)
        self.assertEqual(record["owner_id"], self.owner.id)
        self.assertEqual(record["panel_message_id"], 12)
        self.assertEqual(record["limit"], 4)
        self.assertTrue(record["locked"])
        self.assertTrue(record["hidden"])
        self.assertEqual(record["denied"], [60])
        self.assertEqual(record["allowed"], [61])
        self.assertTrue(record["recovered"])


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.json")
        self.guild = FakeGuild()
        self.bot = FakeBot(self.db, self.guild)
        self.bot.user = types.SimpleNamespace(id=999)
        self.manager = TempVoiceManager(self.bot)  # type: ignore[arg-type]
        self.manager.deletion_grace = 0
        self.bot.tempvoice = self.manager  # type: ignore[attr-defined]

        self.hub = FakeVoiceChannel(self.guild, "➕ Créer ton vocal", 900)
        self.guild.channels[self.hub.id] = self.hub
        settings = self.db.guild(self.guild.id)
        settings["voice_hub_id"] = self.hub.id
        settings["voice_hub_name"] = "➕ Créer ton vocal"

        self.owner = self.guild.add_member(FakeMember(42, self.guild, "Léa"))
        self.channel = await self.manager.create_room(self.owner, self.hub)
        self.record = self.db.voice_room_of(self.guild.id, self.owner.id)
        self.panel_message = self.channel._messages[self.record["panel_message_id"]]

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        await self.db.close()
        self.tmp.cleanup()

    def _lose_database(self) -> None:
        """Simule un redémarrage avec disque éphémère : les fiches disparaissent."""
        self.db.voice_rooms().clear()

    async def test_panel_footer_carries_marker(self) -> None:
        footer = self.panel_message.embeds[0].footer.text
        self.assertIn(f"vespara:temproom:{self.owner.id}", footer)

    async def test_recover_guild_reattaches_rooms(self) -> None:
        self._lose_database()
        self.assertIsNone(self.db.voice_room_of(self.guild.id, self.owner.id))

        report = await self.manager.recover_guild(self.guild)

        self.assertEqual(report["adopted"], 1)
        record = self.db.voice_room_of(self.guild.id, self.owner.id)
        self.assertIsNotNone(record)
        self.assertEqual(record["channel_id"], self.channel.id)
        self.assertEqual(record["panel_message_id"], self.panel_message.id)
        # Le panneau est rafraîchi, pas dupliqué
        self.assertEqual(len(self.channel.sent), 1)

    async def test_recover_keeps_room_state(self) -> None:
        await self.manager.set_locked(self.channel, self.record, True)
        await self.manager.set_limit(self.channel, self.record, 3)
        self._lose_database()

        await self.manager.recover_guild(self.guild)
        record = self.db.voice_room_of(self.guild.id, self.owner.id)
        self.assertTrue(record["locked"])
        self.assertEqual(record["limit"], 3)

    async def test_recover_hub_by_name(self) -> None:
        settings = self.db.guild(self.guild.id)
        settings["voice_hub_id"] = None
        recovered = await self.manager.recover_hub(self.guild)
        self.assertIs(recovered, self.hub)
        self.assertEqual(settings["voice_hub_id"], self.hub.id)

    async def test_recover_ignores_foreign_channel(self) -> None:
        foreign = FakeVoiceChannel(self.guild, "Salon staff", 950)
        self.guild.channels[foreign.id] = foreign
        self._lose_database()

        report = await self.manager.recover_guild(self.guild)
        self.assertEqual(report["adopted"], 1)  # uniquement le vrai vocal
        self.assertFalse(self.manager.is_managed(foreign))

    async def test_panel_button_reattaches_detached_room(self) -> None:
        from bot.ui.tempvoice import TempVoicePanel

        self._lose_database()
        panel = TempVoicePanel(self.bot)  # type: ignore[arg-type]

        interaction = FakeInteraction(self.owner, self.channel, self.bot)
        interaction.message = self.panel_message
        self.assertTrue(await panel.interaction_check(interaction))

        await panel.lock.callback(interaction)  # type: ignore[union-attr]
        record = self.db.voice_room_of(self.guild.id, self.owner.id)
        self.assertIsNotNone(record)
        self.assertTrue(record["locked"])
        self.assertFalse(self.channel.overwrites[self.guild.default_role].connect)

    async def test_detached_room_without_panel_uses_permissions(self) -> None:
        self._lose_database()
        self.channel._messages.clear()  # panneau supprimé
        self.channel.overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
            self.guild.me: discord.PermissionOverwrite(manage_channels=True),
            self.owner: discord.PermissionOverwrite(manage_channels=True, connect=True),
        }

        report = await self.manager.recover_guild(self.guild)
        self.assertEqual(report["adopted"], 1)
        record = self.db.voice_room_of(self.guild.id, self.owner.id)
        self.assertIsNotNone(record)
        # Un nouveau panneau est publié puisque l'ancien n'existe plus
        self.assertEqual(len(self.channel.sent), 2)

    async def test_candidate_channels_ignores_tracked_rooms(self) -> None:
        self.assertEqual(self.manager.candidate_channels(self.guild), [])
        self._lose_database()
        self.assertEqual(len(self.manager.candidate_channels(self.guild)), 1)
