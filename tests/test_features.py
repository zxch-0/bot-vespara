"""Tests de bout en bout (sans Discord) des giveaways et de l'auto-responder."""

from __future__ import annotations

import tempfile
import time
import types
import unittest
from pathlib import Path
from typing import Any

import discord

from bot.cogs.autoresponder import Autoresponder, match_response
from bot.database import Database
from bot.services.giveaways import GiveawayManager, build_giveaway_embed


# --------------------------------------------------------------------------- #
# Doubles de test
# --------------------------------------------------------------------------- #
class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.id = message_id
        self.edits: list[dict[str, Any]] = []
        self.deleted = False
        self.jump_url = f"https://discord.test/{message_id}"

    async def edit(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)

    async def delete(self) -> None:
        self.deleted = True


class FakeChannel:
    def __init__(self, channel_id: int = 999) -> None:
        self.id = channel_id
        self.mention = f"<#{channel_id}>"
        self.sent: list[dict[str, Any]] = []
        self.messages: dict[int, FakeMessage] = {}
        self._counter = 1000

    async def send(self, **kwargs: Any) -> FakeMessage:
        self._counter += 1
        message = FakeMessage(self._counter)
        self.messages[message.id] = message
        self.sent.append(kwargs)
        return message

    async def fetch_message(self, message_id: int) -> FakeMessage:
        return self.messages[message_id]


class FakeGuild:
    def __init__(self, guild_id: int = 1) -> None:
        self.id = guild_id
        self.icon = None


class FakeUser:
    def __init__(self, user_id: int = 42, name: str = "Membre") -> None:
        self.id = user_id
        self.display_name = name
        self.roles: list[Any] = []


class FakeResponse:
    def __init__(self) -> None:
        self.embeds: list[discord.Embed] = []

    def is_done(self) -> bool:
        return False

    async def send_message(self, **kwargs: Any) -> None:
        self.embeds.append(kwargs.get("embed"))


class FakeInteraction:
    def __init__(self, user: FakeUser | None = None) -> None:
        self.user = user or FakeUser()
        self.guild = FakeGuild()
        self.response = FakeResponse()


class FakeBot:
    """Assez de surface pour GiveawayManager et Autoresponder."""

    def __init__(self, database: Database, channel: FakeChannel | None = None) -> None:
        self.db = database
        self.settings = types.SimpleNamespace(brand="Vespara", tagline="Le serveur chill")
        self.guild = FakeGuild()
        self.channel = channel or FakeChannel()
        self.intents = types.SimpleNamespace(message_content=True)
        self.tree = types.SimpleNamespace(remove_command=lambda *a, **k: None)
        self.views: list[Any] = []
        self.user = None
        self.latency = 0.01

    def get_channel(self, channel_id: int):
        return self.channel if channel_id == self.channel.id else None

    def get_guild(self, guild_id: int):
        return self.guild if guild_id == self.guild.id else None

    def add_view(self, view: Any) -> None:
        self.views.append(view)


# --------------------------------------------------------------------------- #
# Giveaways
# --------------------------------------------------------------------------- #
class GiveawayManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.json")
        self.channel = FakeChannel()
        self.bot = FakeBot(self.db, self.channel)
        self.manager = GiveawayManager(self.bot)  # type: ignore[arg-type]

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        await self.db.close()
        self.tmp.cleanup()

    async def _create(self, **overrides: Any) -> dict:
        kwargs = {
            "guild": self.bot.guild,
            "channel": self.channel,
            "host": FakeUser(1, "Hôte"),
            "prize": "Nitro",
            "duration": 3600,
        }
        kwargs.update(overrides)
        return await self.manager.create(**kwargs)

    async def test_create_sends_message_and_persists(self) -> None:
        gw = await self._create()

        self.assertEqual(len(self.channel.sent), 1)
        self.assertIn("embed", self.channel.sent[0])
        self.assertIn("view", self.channel.sent[0])
        self.assertIsNotNone(gw["message_id"])
        self.assertEqual(self.manager.get(gw["id"])["prize"], "Nitro")
        self.assertEqual(self.db.stats()["active_giveaways"], 1)
        self.assertAlmostEqual(gw["ends_at"] - gw["started_at"], 3600, delta=2)

    async def test_join_and_leave(self) -> None:
        gw = await self._create()
        member = FakeUser(42)
        interaction = FakeInteraction(member)

        await self.manager.join(interaction, gw["id"])
        self.assertIn(42, gw["entries"])
        self.assertIn("participant", interaction.response.embeds[0].description.lower())

        # Deuxième participation : message d'information, pas de doublon
        second = FakeInteraction(member)
        await self.manager.join(second, gw["id"])
        self.assertEqual(len(gw["entries"]), 1)
        self.assertIn("déjà", second.response.embeds[0].description)

        await self.manager.leave(FakeInteraction(member), gw["id"])
        self.assertEqual(gw["entries"], [])

    async def test_join_closed_giveaway(self) -> None:
        gw = await self._create()
        gw["ends_at"] = time.time() - 5
        interaction = FakeInteraction()
        await self.manager.join(interaction, gw["id"])
        self.assertEqual(len(interaction.response.embeds), 1)
        self.assertIn("terminé", interaction.response.embeds[0].description)

    async def test_end_selects_winners_and_announces(self) -> None:
        gw = await self._create(winners_count=2)
        for user_id in (10, 20, 30):
            await self.manager.join(FakeInteraction(FakeUser(user_id)), gw["id"])

        winners = await self.manager.end(gw)

        self.assertEqual(len(winners), 2)
        self.assertTrue(set(winners).issubset({10, 20, 30}))
        self.assertTrue(gw["ended"])
        self.assertEqual(gw["winners"], winners)

        # Le message d'origine est mis à jour (embed + boutons désactivés)
        message = self.channel.messages[gw["message_id"]]
        self.assertTrue(message.edits)
        self.assertTrue(all(item.disabled for item in message.edits[-1]["view"].children))

        # Une annonce publique est envoyée avec les mentions
        announcement = self.channel.sent[-1]
        self.assertIn("Félicitations", announcement["content"])
        self.assertIn(f"<@{winners[0]}>", announcement["content"])

    async def test_end_without_participants(self) -> None:
        gw = await self._create()
        winners = await self.manager.end(gw)
        self.assertEqual(winners, [])
        self.assertIn("sans participant", self.channel.sent[-1]["content"].lower())

    async def test_reroll_excludes_previous_winners(self) -> None:
        gw = await self._create(winners_count=1)
        for user_id in (10, 20):
            await self.manager.join(FakeInteraction(FakeUser(user_id)), gw["id"])

        first = (await self.manager.end(gw))[0]
        second = (await self.manager.reroll(gw, 1))[0]

        self.assertNotEqual(first, second)
        self.assertEqual(gw["winners"], [second])
        self.assertGreaterEqual(len(gw["reroll_history"]), 1)

    async def test_delete_removes_everything(self) -> None:
        gw = await self._create()
        message = self.channel.messages[gw["message_id"]]

        await self.manager.delete(gw)

        self.assertTrue(message.deleted)
        self.assertIsNone(self.manager.get(gw["id"]))

    async def test_end_expired(self) -> None:
        gw = await self._create()
        gw["ends_at"] = time.time() - 1
        ended = await self.manager.end_expired()
        self.assertEqual(ended, 1)
        self.assertTrue(gw["ended"])

    async def test_restore_views_registers_persistent_views(self) -> None:
        gw = await self._create()
        await self.manager.restore_views()
        self.assertGreaterEqual(len(self.bot.views), 1)

        await self.manager.end(gw)
        self.bot.views.clear()
        await self.manager.restore_views()
        self.assertEqual(len(self.bot.views), 2)  # giveaway désactivé + reroll

    def test_pick_winners_handles_empty_and_exclusions(self) -> None:
        self.assertEqual(GiveawayManager._pick_winners({"entries": []}, 1), [])
        gw = {"entries": [1, 2]}
        self.assertEqual(sorted(GiveawayManager._pick_winners(gw, 5)), [1, 2])
        winners = GiveawayManager._pick_winners(gw, 1, exclude=[1])
        self.assertEqual(winners, [2])
        # Tout le monde a déjà gagné : on retombe sur la liste complète
        self.assertIn(GiveawayManager._pick_winners(gw, 1, exclude=[1, 2])[0], (1, 2))

    def test_embed_uses_guild_icon_and_progress(self) -> None:
        emb = build_giveaway_embed(
            {
                "id": "1",
                "guild_id": 1,
                "prize": "Jeu Steam",
                "started_at": time.time() - 600,
                "ends_at": time.time() + 600,
                "entries": [1, 2, 3],
                "winners": [],
                "winners_count": 1,
                "ended": False,
                "host_name": "Hôte",
            }
        )
        self.assertIn("▰", emb.description)


# --------------------------------------------------------------------------- #
# Auto-responder
# --------------------------------------------------------------------------- #
class FakeIncomingMessage:
    def __init__(self, content: str, channel: FakeChannel, guild: FakeGuild | None = None) -> None:
        self.content = content
        self.guild = guild or FakeGuild()
        self.channel = channel
        self.author = types.SimpleNamespace(bot=False, id=7)
        self.replies: list[dict[str, Any]] = []

    async def reply(self, content: str | None = None, **kwargs: Any) -> None:
        self.replies.append({"content": content, **kwargs})


class AutoresponderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.json")
        self.channel = FakeChannel()
        self.bot = FakeBot(self.db, self.channel)
        self.cog = Autoresponder(self.bot)  # type: ignore[arg-type]

        self.db.add_autoresponse(
            1,
            {
                "id": "1",
                "trigger": "bonjour",
                "reply": "Salut et bienvenue !",
                "mode": "contains",
                "case_sensitive": False,
                "embed": False,
                "enabled": True,
                "uses": 0,
            },
        )

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def test_replies_and_counts_uses(self) -> None:
        message = FakeIncomingMessage("Bonjour tout le monde", self.channel)
        await self.cog.on_message(message)  # type: ignore[arg-type]

        self.assertEqual(len(message.replies), 1)
        self.assertEqual(message.replies[0]["content"], "Salut et bienvenue !")
        self.assertFalse(message.replies[0]["mention_author"])
        self.assertEqual(self.db.autoresponses(1)[0]["uses"], 1)

    async def test_cooldown_blocks_second_reply(self) -> None:
        self.db.guild(1)["autoresponder_cooldown"] = 60

        first = FakeIncomingMessage("bonjour", self.channel)
        second = FakeIncomingMessage("bonjour encore", self.channel)
        await self.cog.on_message(first)  # type: ignore[arg-type]
        await self.cog.on_message(second)  # type: ignore[arg-type]

        self.assertEqual(len(first.replies), 1)
        self.assertEqual(len(second.replies), 0)

    async def test_disabled_and_bot_messages_ignored(self) -> None:
        self.db.autoresponses(1)[0]["enabled"] = False
        message = FakeIncomingMessage("bonjour", self.channel)
        await self.cog.on_message(message)  # type: ignore[arg-type]
        self.assertEqual(message.replies, [])

        bot_message = FakeIncomingMessage("bonjour", self.channel)
        bot_message.author.bot = True
        self.db.autoresponses(1)[0]["enabled"] = True
        await self.cog.on_message(bot_message)  # type: ignore[arg-type]
        self.assertEqual(bot_message.replies, [])

    async def test_embed_reply(self) -> None:
        self.db.autoresponses(1)[0]["embed"] = True
        message = FakeIncomingMessage("bonjour", self.channel)
        await self.cog.on_message(message)  # type: ignore[arg-type]

        self.assertEqual(len(message.replies), 1)
        self.assertIn("embed", message.replies[0])
        self.assertIsNone(message.replies[0]["content"])

    def test_match_regex_and_exact(self) -> None:
        self.assertTrue(match_response("abc", {"trigger": "abc", "mode": "exact"}))
        self.assertTrue(match_response("test 42", {"trigger": r"\d+", "mode": "regex"}))


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------- #
# Annonces
# --------------------------------------------------------------------------- #
class FakeAsset:
    url = "https://cdn.discord.test/avatar.png"


class FakeAnnounceUser:
    id = 5
    display_name = "Staffeur"
    display_avatar = FakeAsset()


class FakeEditResponse:
    def __init__(self) -> None:
        self.edited: dict[str, Any] | None = None

    def is_done(self) -> bool:
        return False

    async def edit_message(self, **kwargs: Any) -> None:
        self.edited = kwargs

    async def send_message(self, **kwargs: Any) -> None:
        self.edited = kwargs


class FakeAnnounceInteraction:
    def __init__(self) -> None:
        self.user = FakeAnnounceUser()
        self.response = FakeEditResponse()
        self.message = None


class AnnouncementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from bot.ui.announcement import AnnouncementDraft, AnnouncementPreview

        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.json")
        self.channel = FakeChannel()
        self.bot = FakeBot(self.db, self.channel)
        self.draft = AnnouncementDraft(
            title="Soirée jeux",
            content="Ce samedi à 21h !",
            color=0x8B5CF6,
        )
        self.preview = AnnouncementPreview(
            self.bot,  # type: ignore[arg-type]
            draft=self.draft,
            channel=self.channel,  # type: ignore[arg-type]
            mention_text="@everyone",
            author_id=5,
        )

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    def test_embed_contains_draft(self) -> None:
        emb = self.draft.to_embed(FakeAnnounceUser())  # type: ignore[arg-type]
        self.assertEqual(emb.title, "Soirée jeux")
        self.assertEqual(emb.description, "Ce samedi à 21h !")
        self.assertEqual(emb.author.name, "Staffeur")

    async def test_publish_sends_and_confirms(self) -> None:
        interaction = FakeAnnounceInteraction()
        await self.preview.publish.callback(interaction)  # type: ignore[attr-defined]

        self.assertEqual(len(self.channel.sent), 1)
        payload = self.channel.sent[0]
        self.assertEqual(payload["content"], "@everyone")
        self.assertEqual(payload["embed"].title, "Soirée jeux")
        self.assertTrue(payload["allowed_mentions"].everyone)
        self.assertIn("envoyée", interaction.response.edited["embed"].title.lower())
        self.assertTrue(all(item.disabled for item in self.preview.children))

    async def test_cancel_does_nothing(self) -> None:
        interaction = FakeAnnounceInteraction()
        await self.preview.cancel.callback(interaction)  # type: ignore[attr-defined]
        self.assertEqual(self.channel.sent, [])
        self.assertIn("annulée", interaction.response.edited["embed"].title.lower())

    async def test_author_check(self) -> None:
        from bot.ui.announcement import AnnouncementPreview

        other = AnnouncementPreview(
            self.bot,  # type: ignore[arg-type]
            draft=self.draft,
            channel=self.channel,  # type: ignore[arg-type]
            mention_text=None,
            author_id=999,
        )
        interaction = FakeAnnounceInteraction()
        self.assertFalse(await other.interaction_check(interaction))  # type: ignore[arg-type]
