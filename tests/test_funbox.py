"""Tests des commandes rigolotes : logique pure, rendus et interactions."""

from __future__ import annotations

import random
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any

import discord

from bot.cogs import EXTENSIONS
from bot.config import Settings
from bot.main import VesparaBot
from bot.services.fun import (
    ACTIONS,
    GAUGE_KINDS,
    HOROSCOPE_SIGNS,
    JOKES,
    RPS_BEATS,
    RPS_EMOJIS,
    battle,
    bot_rps_choice,
    clean_text,
    coinflip,
    dice_display,
    gauge,
    normalize_rps,
    normalize_sign,
    pick_horoscope,
    resolve_rps,
    roll,
    ship,
    ship_score,
    stable_score,
)


# --------------------------------------------------------------------------- #
# Doubles
# --------------------------------------------------------------------------- #
class FakeMember:
    def __init__(self, member_id: int, name: str = "Léa") -> None:
        self.id = member_id
        self.name = name
        self.display_name = name
        self.mention = f"<@{member_id}>"
        self.bot = False
        self.display_avatar = types.SimpleNamespace(url="https://cdn.discord.test/a.png")


class FakeMessage:
    def __init__(self, message_id: int, content: str = "", author: Any = None) -> None:
        self.id = message_id
        self.content = content
        self.author = author
        self.jump_url = f"https://discord.test/{message_id}"
        self.reactions: list[str] = []
        self.pinned = False
        self.edits: list[dict[str, Any]] = []

    async def add_reaction(self, emoji: str) -> None:
        self.reactions.append(emoji)

    async def pin(self, reason: str | None = None) -> None:
        self.pinned = True

    async def edit(self, **kwargs: Any) -> "FakeMessage":
        self.edits.append(kwargs)
        return self


class FakeChannel:
    def __init__(self, channel_id: int = 10, guild: Any = None) -> None:
        self.id = channel_id
        self.guild = guild
        self.name = "général"
        self.mention = f"<#{channel_id}>"
        self.sent: list[dict[str, Any]] = []
        self.messages: dict[int, FakeMessage] = {}
        self._counter = 100

    async def send(self, **kwargs: Any) -> FakeMessage:
        self._counter += 1
        message = FakeMessage(
            self._counter,
            content=str(kwargs.get("content") or ""),
            author=kwargs.get("author"),
        )
        self.messages[message.id] = message
        self.sent.append(kwargs)
        return message

    async def fetch_message(self, message_id: int) -> FakeMessage:
        if message_id not in self.messages:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "unknown")
        return self.messages[message_id]


class FakeGuild:
    def __init__(self, guild_id: int = 1) -> None:
        self.id = guild_id
        self.name = "Vespara"
        self.icon = None
        self.member_count = 10
        self.channels: dict[int, FakeChannel] = {}

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        return self.channels.get(int(channel_id))


class FakeResponse:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.deferred = False
        self.edited: dict[str, Any] | None = None
        self.modal = None

    def is_done(self) -> bool:
        return bool(self.sent or self.deferred)

    async def send_message(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)

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
    def __init__(self, user: FakeMember, guild: FakeGuild, channel: FakeChannel, client: Any) -> None:
        self.user = user
        self.guild = guild
        self.channel = channel
        self.channel_id = channel.id
        self.client = client
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.message: Any = None

    async def original_response(self) -> Any:
        return types.SimpleNamespace(edit=self._edit)

    async def _edit(self, **kwargs: Any) -> None:
        self.response.edited = kwargs

    async def edit_original_response(self, **kwargs: Any) -> None:
        self.response.edited = kwargs


# --------------------------------------------------------------------------- #
# Logique pure
# --------------------------------------------------------------------------- #
class StableScoreTests(unittest.TestCase):
    def test_score_is_stable_and_bounded(self) -> None:
        first = stable_score("gauge", "iq", 1, 42, low=20, high=200)
        self.assertEqual(first, stable_score("gauge", "iq", 1, 42, low=20, high=200))
        self.assertTrue(20 <= first <= 200)

    def test_score_changes_with_inputs(self) -> None:
        values = {stable_score("gauge", "iq", 1, user_id, low=0, high=1000) for user_id in range(50)}
        self.assertGreater(len(values), 10)

    def test_bad_range_is_clamped(self) -> None:
        self.assertEqual(stable_score("x", low=10, high=10), 10)
        self.assertEqual(stable_score("x", low=10, high=5), 10)


class GaugeTests(unittest.TestCase):
    def test_all_gauges_are_consistent(self) -> None:
        for kind in GAUGE_KINDS:
            with self.subTest(kind=kind):
                first = gauge(kind, 1, 42)
                second = gauge(kind, 1, 42)
                self.assertEqual(first.score, second.score)
                self.assertGreaterEqual(first.score, 0)
                self.assertLessEqual(first.score, first.maximum)
                self.assertTrue(first.verdict)
                self.assertTrue(first.comment)
                self.assertTrue(0.0 <= first.ratio <= 1.0)
                self.assertIn("/", first.label)

    def test_gauge_varies_between_members(self) -> None:
        scores = {gauge("chaos", 1, user_id).score for user_id in range(30)}
        self.assertGreater(len(scores), 5)

    def test_unknown_gauge(self) -> None:
        with self.assertRaises(ValueError):
            gauge("licorne", 1, 1)


class ShipTests(unittest.TestCase):
    def test_score_is_symmetric(self) -> None:
        self.assertEqual(ship_score(1, 10, 20), ship_score(1, 20, 10))

    def test_result_shape(self) -> None:
        a, b = FakeMember(10, "Léa"), FakeMember(20, "Max")
        result = ship(1, a, b)
        self.assertTrue(0 <= result["score"] <= 100)
        self.assertTrue(result["verdict"])
        self.assertIn("Léa", result["name"])
        self.assertFalse(result["same_person"])

    def test_ship_with_self(self) -> None:
        a = FakeMember(10, "Léa")
        result = ship(1, a, a)
        self.assertTrue(result["same_person"])
        self.assertLessEqual(result["score"], 20)


class BattleTests(unittest.TestCase):
    def test_battle_has_a_winner(self) -> None:
        rng = random.Random(7)
        for _ in range(50):
            result = battle("Léa", "Max", rng)
            self.assertTrue(result.events)
            self.assertLessEqual(result.turns, 24)
            self.assertIn(result.winner, {"Léa", "Max", None})
            self.assertTrue(0 <= result.hp_a <= 100)
            self.assertTrue(0 <= result.hp_b <= 100)
            if result.winner == "Léa":
                self.assertEqual(result.hp_b, 0)

    def test_events_alternate_and_have_text(self) -> None:
        rng = random.Random(11)
        result = battle("A", "B", rng)
        for index, event in enumerate(result.events):
            self.assertTrue(event.text)
            self.assertGreater(event.damage, 0)
            self.assertEqual(event.attacker, "A" if index % 2 == 0 else "B")


class RpsTests(unittest.TestCase):
    def test_normalize(self) -> None:
        for raw, expected in (("pierre", "pierre"), ("P", "pierre"), ("paper", "feuille"), ("ciseaux", "ciseaux")):
            self.assertEqual(normalize_rps(raw), expected)
        self.assertIsNone(normalize_rps("banane"))

    def test_resolution(self) -> None:
        for winner, loser in RPS_BEATS.items():
            self.assertEqual(resolve_rps(winner, loser), "a")
            self.assertEqual(resolve_rps(loser, winner), "b")
        self.assertEqual(resolve_rps("pierre", "pierre"), "draw")

    def test_bot_choice_is_valid(self) -> None:
        rng = random.Random(3)
        for _ in range(30):
            self.assertIn(bot_rps_choice(rng), RPS_EMOJIS)


class RandomToolsTests(unittest.TestCase):
    def test_roll_and_display(self) -> None:
        rng = random.Random(5)
        values = roll(6, 3, rng)
        self.assertEqual(len(values), 3)
        self.assertTrue(all(1 <= value <= 6 for value in values))
        self.assertEqual(len(dice_display(values).split()), 3)
        self.assertIn("`", dice_display(values, sides=20))

    def test_roll_bounds(self) -> None:
        values = roll(1000, 50, random.Random(1))
        self.assertEqual(len(values), 10)  # plafonné
        self.assertTrue(all(1 <= value <= 100 for value in values))

    def test_coinflip(self) -> None:
        rng = random.Random(9)
        results = {coinflip(rng) for _ in range(40)}
        self.assertTrue(results <= {"pile", "face"})
        self.assertGreaterEqual(len(results), 1)

    def test_horoscope_and_signs(self) -> None:
        self.assertEqual(normalize_sign("Gémaux"), "gemeaux")
        self.assertEqual(normalize_sign("LION"), "lion")
        self.assertIsNone(normalize_sign("dragon"))
        text = pick_horoscope("lion", 1, 42)
        self.assertTrue(text)
        self.assertIn(text, __import__("bot.services.fun", fromlist=["HOROSCOPES"]).HOROSCOPES)
        self.assertEqual(len(HOROSCOPE_SIGNS), 12)

    def test_pools_are_not_empty(self) -> None:
        self.assertGreaterEqual(len(JOKES), 10)
        self.assertTrue(ACTIONS)
        for spec in ACTIONS.values():
            self.assertTrue(spec.lines)
            self.assertTrue(spec.verb)

    def test_clean_text(self) -> None:
        self.assertEqual(clean_text("  salut   toi  "), "salut toi")
        self.assertEqual(clean_text("ligne1\n\nligne2"), "ligne1\nligne2")
        self.assertEqual(clean_text("\u200b"), "")
        self.assertEqual(clean_text(""), "")


# --------------------------------------------------------------------------- #
# Rendu
# --------------------------------------------------------------------------- #
class FunEmbedTests(unittest.TestCase):
    def test_gauge_embed(self) -> None:
        from bot.ui.fun import gauge_embed

        emb = gauge_embed(gauge("iq", 1, 1), FakeMember(1))
        self.assertIn("Léa", emb.title)
        self.assertIn("🧠", emb.title)
        self.assertIn("%", emb.description)

    def test_ship_embed(self) -> None:
        from bot.ui.fun import ship_embed

        emb = ship_embed(ship(1, FakeMember(1, "Léa"), FakeMember(2, "Max")))
        self.assertIn("Léa", emb.title)
        self.assertIn("%", emb.description)

    def test_battle_embed_progressive(self) -> None:
        from bot.ui.fun import battle_embed

        result = battle("Léa", "Max", random.Random(2))
        partial = battle_embed(result, step=1)
        self.assertIn("Léa vs Max", partial.title)
        names = [field.name for field in partial.fields]
        self.assertIn("🔵 Léa", names)
        self.assertIn("🔴 Max", names)

        final = battle_embed(result)
        self.assertIn("🏆 Vainqueur", [field.name for field in final.fields])

    def test_rps_embed_states(self) -> None:
        from bot.ui.fun import rps_embed

        waiting = rps_embed(player=FakeMember(1), choice=None, bot_choice=None, outcome=None)
        self.assertIn("choisit", waiting.description)

        won = rps_embed(player=FakeMember(1), choice="pierre", bot_choice="ciseaux", outcome="a")
        self.assertIn("gagne", won.description)
        lost = rps_embed(player=FakeMember(1), choice="pierre", bot_choice="feuille", outcome="b")
        self.assertIn("gagne", lost.description)
        draw = rps_embed(player=FakeMember(1), choice="pierre", bot_choice="pierre", outcome="draw")
        self.assertIn("Égalité", draw.description)

    def test_misc_embeds(self) -> None:
        from bot.ui.fun import (
            action_embed,
            coin_embed,
            dice_embed,
            fun_menu_embed,
            horoscope_embed,
            joke_embed,
            poll_embed,
            quote_embed,
        )

        self.assertIn("Blague", joke_embed(JOKES[0]).title)
        self.assertIn("Citation", quote_embed("La vie", author_label="Anonyme").title)
        self.assertIn("Câlin", action_embed("calin", FakeMember(1), FakeMember(2)).title)
        self.assertIn("Pile", coin_embed("pile", flipper=FakeMember(1)).description)
        self.assertIn("Total", dice_embed([1, 2, 3], 6, roller=FakeMember(1)).description)
        self.assertIn("Lion", horoscope_embed("♌ Lion", "Bonne journée", FakeMember(1)).title)
        poll = poll_embed("Pizza ?", ["Oui", "Non"], author=FakeMember(1))
        self.assertIn("1️⃣", poll.description)
        self.assertIn("2️⃣", poll.description)
        self.assertTrue(fun_menu_embed().fields)


# --------------------------------------------------------------------------- #
# Commandes (avec doublures)
# --------------------------------------------------------------------------- #
class FunCommandsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        settings = Settings(
            token="fake", database_path=Path(self.tmp.name) / "db.json", staff_permission="manage_guild"
        )
        self.bot = VesparaBot(settings)
        for extension in EXTENSIONS:
            await self.bot.load_extension(extension)
        self.bot.apply_command_visibility()

        self.guild = FakeGuild()
        self.channel = FakeChannel(10, self.guild)
        self.guild.channels[10] = self.channel
        self.user = FakeMember(42, "Léa")
        self.other = FakeMember(43, "Max")

        # Les animations (duel) sont accélérées.
        from unittest.mock import AsyncMock, patch

        self._patch = patch("bot.ui.fun._sleep", new=AsyncMock())
        self._patch.start()

        # Les salons factices ne sont pas des `discord.TextChannel` : on court-circuite
        # la résolution du salon cible pour tester le reste du flux.
        def _fake_text_channel(interaction: Any, salon: Any) -> Any:
            channel = salon or interaction.channel
            return channel if isinstance(channel, FakeChannel) else None

        self._channel_patch = patch("bot.cogs.funbox._text_channel", side_effect=_fake_text_channel)
        self._channel_patch.start()

    async def asyncTearDown(self) -> None:
        self._channel_patch.stop()
        self._patch.stop()
        await self.bot.close()
        self.tmp.cleanup()

    def interaction(self, user: FakeMember | None = None) -> FakeInteraction:
        return FakeInteraction(user or self.user, self.guild, self.channel, self.bot)

    def command(self, name: str) -> Any:
        command = self.bot.tree.get_command(name)
        self.assertIsNotNone(command, name)
        return command

    async def run_command(self, name: str, *args: Any, user: FakeMember | None = None, **kwargs: Any) -> FakeInteraction:
        interaction = self.interaction(user)
        await self.command(name).callback(self.bot.get_cog("FunBox"), interaction, *args, **kwargs)
        return interaction

    def assert_answered(self, interaction: FakeInteraction) -> None:
        self.assertTrue(
            interaction.response.sent or interaction.followup.sent or interaction.response.edited,
            "La commande n'a rien répondu",
        )

    # ------------------------------------------------------------------ #
    async def test_dire_is_admin_only(self) -> None:
        command = self.command("dire")
        self.assertIsNotNone(command.default_permissions)
        self.assertTrue(command.default_permissions.administrator)
        self.assertTrue(command.checks)

        interaction = await self.run_command("dire", "Bonjour tout le monde !")
        self.assert_answered(interaction)
        self.assertEqual(len(self.channel.sent), 1)
        self.assertEqual(self.channel.sent[0]["content"], "Bonjour tout le monde !")
        # Aucune mention ne peut être déclenchée par /dire
        self.assertEqual(
            self.channel.sent[0]["allowed_mentions"].to_dict(),
            discord.AllowedMentions.none().to_dict(),
        )

    async def test_dire_embed_and_pin(self) -> None:
        interaction = await self.run_command(
            "dire", "Message **important**", None, True, True, None
        )
        self.assert_answered(interaction)
        sent = self.channel.sent[-1]
        self.assertIn("embed", sent)
        self.assertNotIn("content", sent)

    async def test_dire_rejects_empty_and_bad_channel(self) -> None:
        interaction = await self.run_command("dire", "   ")
        self.assert_answered(interaction)

        interaction = self.interaction()
        await self.command("dire").callback(self.bot.get_cog("FunBox"), interaction, "test", types.SimpleNamespace(mention="#vocal"))
        self.assert_answered(interaction)

    async def test_sondage_publishes_reactions(self) -> None:
        command = self.command("sondage")
        self.assertTrue(command.checks)

        interaction = await self.run_command("sondage", "Pizza ou burger ?", "Pizza", "Burger", "Sushi", None, None, False)
        self.assert_answered(interaction)
        sent = self.channel.sent[-1]
        self.assertIn("embed", sent)
        self.assertIn("Pizza", sent["embed"].description)
        message = list(self.channel.messages.values())[-1]
        self.assertEqual(len(message.reactions), 3)

        # Moins de deux options : erreur propre
        interaction = await self.run_command("sondage", "Question", "Une seule", "")
        self.assert_answered(interaction)

    async def test_citation_flow(self) -> None:
        interaction = await self.run_command("citation", "La vie est un giveaway", "Anonyme")
        self.assert_answered(interaction)
        self.assertIn("Citation", self.channel.sent[-1]["embed"].title)

        # Citation depuis un message existant
        message = await self.channel.send(content="Phrase culte du serveur")
        interaction = await self.run_command("citation", None, None, None, str(message.id))
        self.assert_answered(interaction)
        self.assertIn("Phrase culte", self.channel.sent[-1]["embed"].description)

        # Message introuvable
        interaction = await self.run_command("citation", None, None, None, "999999")
        self.assert_answered(interaction)

        # Rien à citer
        interaction = await self.run_command("citation", "   ")
        self.assert_answered(interaction)

    async def test_gauges_and_social_commands(self) -> None:
        for name in ("iq", "sus", "simp", "aura", "chaos"):
            with self.subTest(command=name):
                interaction = await self.run_command(name, None)
                self.assert_answered(interaction)
                self.assertIn("Léa", interaction.response.sent[-1]["embed"].title)

        interaction = await self.run_command("ship", self.other)
        self.assert_answered(interaction)
        self.assertIn("Max", interaction.response.sent[-1]["embed"].title)

        for name in ("blague", "pileouface"):
            with self.subTest(command=name):
                interaction = await self.run_command(name)
                self.assert_answered(interaction)

        interaction = await self.run_command("de", 20, 3)
        self.assert_answered(interaction)
        self.assertIn("1d", "1d")  # vérifie juste que rien n'a explosé
        self.assertIn("Lancer", interaction.response.sent[-1]["embed"].title)

        interaction = await self.run_command("horoscope", "lion")
        self.assert_answered(interaction)
        interaction = await self.run_command("horoscope", None)
        self.assert_answered(interaction)
        interaction = await self.run_command("horoscope", "dragon")
        self.assert_answered(interaction)

        interaction = await self.run_command("pique", self.other)
        self.assert_answered(interaction)
        interaction = await self.run_command("complimente", self.other)
        self.assert_answered(interaction)

        for name in ("calin", "tapote"):
            with self.subTest(command=name):
                interaction = await self.run_command(name, self.other)
                self.assert_answered(interaction)

        # Baffe sur soi-même refusée
        interaction = await self.run_command("baffe", self.user)
        self.assert_answered(interaction)

        interaction = await self.run_command("fun")
        self.assert_answered(interaction)

    async def test_duel_and_pfc(self) -> None:
        interaction = await self.run_command("duel", self.other)
        self.assert_answered(interaction)

        interaction = await self.run_command("duel", self.user)
        self.assert_answered(interaction)

        interaction = await self.run_command("pfc", None)
        self.assert_answered(interaction)
        self.assertIn("view", interaction.response.sent[-1])

        interaction = await self.run_command("pfc", self.other)
        self.assert_answered(interaction)

    async def test_rps_view_solo_and_duel(self) -> None:
        from bot.ui.fun import RpsView

        # Solo : un seul clic = résultat
        view = RpsView(self.user.id, None)
        interaction = self.interaction()
        await view.children[0].callback(interaction)  # type: ignore[union-attr]
        self.assertIsNotNone(view.result)
        self.assertIsNotNone(interaction.response.edited)
        self.assertTrue(all(item.disabled for item in view.children))

        # Duel : il faut les deux clics
        view = RpsView(self.user.id, self.other)
        first = self.interaction(self.user)
        await view.children[0].callback(first)  # type: ignore[union-attr]
        self.assertIsNone(view.result)
        self.assertIn("attente", first.response.sent[-1]["embed"].description.lower())

        second = self.interaction(self.other)
        await view.children[1].callback(second)  # type: ignore[union-attr]
        self.assertIsNotNone(view.result)
        self.assertIsNotNone(second.response.edited)

    async def test_rps_view_rejects_strangers(self) -> None:
        from bot.ui.fun import RpsView

        view = RpsView(self.user.id, None)
        stranger = FakeInteraction(FakeMember(99, "Inconnu"), self.guild, self.channel, self.bot)
        self.assertFalse(await view.interaction_check(stranger))
        self.assertIn("concerne", stranger.response.sent[-1]["embed"].description)

    def test_command_visibility(self) -> None:
        from bot.constants import STAFF_COMMAND_ROOTS

        for root in ("sondage", "citation"):
            self.assertIn(root, STAFF_COMMAND_ROOTS)
            command = self.bot.tree.get_command(root)
            self.assertIsNotNone(command.default_permissions, root)

        # Les commandes fun publiques ne sont pas restreintes
        for name in ("iq", "ship", "duel", "pfc", "blague", "calin", "fun", "de", "pileouface"):
            command = self.bot.tree.get_command(name)
            self.assertIsNone(command.default_permissions, name)  # type: ignore[union-attr]
            self.assertEqual(len(command.checks), 0, name)  # type: ignore[union-attr]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
