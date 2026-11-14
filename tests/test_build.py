"""Tests de `/build` : noms de salons, plan, permissions et construction."""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from typing import Any

import discord

import bot.services.serverbuild as serverbuild
from bot.cogs import EXTENSIONS
from bot.config import Settings
from bot.main import VesparaBot
from bot.services.serverbuild import (
    FANCY_MAP,
    SIMPLE_RULES,
    BuildOptions,
    build_plan,
    build_server,
    count_channels,
    fancy,
    format_category_name,
    format_channel_name,
    plan_embed,
    result_embed,
    slugify,
)
from bot.ui.common import ConfirmView


# --------------------------------------------------------------------------- #
# Doubles Discord minimalistes pour la création de salons
# --------------------------------------------------------------------------- #
class FakeRole:
    def __init__(self, role_id: int, name: str) -> None:
        self.id = role_id
        self.name = name
        self.mention = f"<@&{role_id}>"


class FakeChannel:
    _counter = 0

    def __init__(self, name: str, *, guild: "FakeGuild", kind: str = "text", **kwargs: Any) -> None:
        FakeChannel._counter += 1
        self.id = FakeChannel._counter
        self.name = name
        self.guild = guild
        self.kind = kind
        self.topic = kwargs.get("topic")
        self.overwrites = kwargs.get("overwrites") or {}
        self.category = kwargs.get("category")
        self.mention = f"<#{self.id}>"
        self.sent: list[dict[str, Any]] = []
        self.permissions = discord.Permissions.all()
        self.nickname = None

    async def send(self, **kwargs: Any) -> Any:
        self.sent.append(kwargs)
        return self

    def permissions_for(self, member: Any) -> discord.Permissions:
        return self.permissions


class FakeGuild:
    def __init__(self, guild_id: int = 7) -> None:
        self.id = guild_id
        self.name = "Serveur test"
        self.icon = None
        self.default_role = FakeRole(0, "@everyone")
        self.me = type(
            "Me",
            (),
            {
                "id": 999,
                "guild_permissions": discord.Permissions(administrator=True),
                "mention": "<@999>",
            },
        )()
        self.created_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.categories: list[FakeChannel] = []
        self.text_channels: list[FakeChannel] = []
        self.voice_channels: list[FakeChannel] = []

    async def create_category(self, name: str, **kwargs: Any) -> FakeChannel:
        category = FakeChannel(name, guild=self, kind="category", **kwargs)
        self.categories.append(category)
        self.created_calls.append(("category", name, kwargs))
        return category

    async def create_text_channel(self, name: str, **kwargs: Any) -> FakeChannel:
        channel = FakeChannel(name, guild=self, kind="text", **kwargs)
        self.text_channels.append(channel)
        self.created_calls.append(("text", name, kwargs))
        return channel

    async def create_voice_channel(self, name: str, **kwargs: Any) -> FakeChannel:
        channel = FakeChannel(name, guild=self, kind="voice", **kwargs)
        self.voice_channels.append(channel)
        self.created_calls.append(("voice", name, kwargs))
        return channel


# --------------------------------------------------------------------------- #
# Noms de salons
# --------------------------------------------------------------------------- #
class ChannelNameTests(unittest.TestCase):
    def test_fancy_map_covers_ascii(self) -> None:
        self.assertEqual(fancy("Pings"), "𝑃𝑖𝑛𝑔𝑠")
        self.assertNotIn("P", fancy("Pings"))

    def test_channel_name_matches_expected_theme(self) -> None:
        self.assertEqual(
            format_channel_name("Pings", "🎐"),
            "-➠˗ˏˋ🎐┆𝑃𝑖𝑛𝑔𝑠ˎˊ˗",
        )

    def test_channel_name_strips_accents_and_spaces(self) -> None:
        name = format_channel_name("Règles & infos", "📜")
        self.assertTrue(name.startswith("-➠˗ˏˋ📜┆"))
        self.assertTrue(name.endswith("ˎˊ˗"))
        self.assertNotIn(" ", name)
        self.assertNotIn("è", name)

    def test_channel_name_without_emoji(self) -> None:
        self.assertEqual(format_channel_name("Logs-bot"), "-➠˗ˏˋ┆𝐿𝑜𝑔𝑠-𝑏𝑜𝑡ˎˊ˗")

    def test_channel_name_respects_discord_limit(self) -> None:
        name = format_channel_name("x" * 300, "🎐")
        self.assertLessEqual(len(name), 100)
        self.assertTrue(name.startswith("-➠˗ˏˋ🎐┆"))
        self.assertTrue(name.endswith("ˎˊ˗"))

    def test_category_name_keeps_decorations(self) -> None:
        name = format_category_name("Informations", "📌")
        self.assertEqual(name, "˗ˏˋ📌┆𝐼𝑛𝑓𝑜𝑟𝑚𝑎𝑡𝑖𝑜𝑛𝑠ˎˊ˗")
        self.assertLessEqual(len(format_category_name("y" * 200, "🎐")), 100)

    def test_slugify(self) -> None:
        self.assertEqual(slugify("Règles & infos"), "Regles-infos")
        self.assertEqual(slugify("  "), "")
        self.assertEqual(slugify("Logs-membres"), "Logs-membres")

    def test_every_letter_is_styled(self) -> None:
        for letter in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            self.assertIn(letter, FANCY_MAP)
            if not letter.isdigit():
                self.assertNotEqual(FANCY_MAP[letter], letter, letter)


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #
class PlanTests(unittest.TestCase):
    def test_default_plan_contains_expected_channels(self) -> None:
        plan = build_plan()
        keys = {spec.key for category in plan for spec in category.channels}
        for expected in (
            "regles",
            "annonces",
            "giveaways",
            "commandes",
            "pings",
            "logs-messages",
            "staff",
            "vocal-hub",
        ):
            self.assertIn(expected, keys)
        self.assertGreaterEqual(count_channels(plan), 15)

    def test_options_remove_channels(self) -> None:
        plan = build_plan(BuildOptions(regles=False, logs=False, vocal=False, economie=False))
        keys = {spec.key for category in plan for spec in category.channels}
        self.assertNotIn("regles", keys)
        self.assertNotIn("logs-bot", keys)
        self.assertNotIn("vocal-hub", keys)
        self.assertNotIn("casino", keys)
        self.assertIn("annonces", keys)
        self.assertIn("commandes", keys)

    def test_rules_and_staff_channels_are_restricted(self) -> None:
        plan = build_plan()
        specs = {spec.key: spec for category in plan for spec in category.channels}
        self.assertEqual(specs["regles"].access, "read_only")
        self.assertEqual(specs["staff"].access, "staff")
        self.assertEqual(specs["logs-messages"].access, "staff")
        self.assertEqual(specs["general"].access, "public")
        self.assertEqual(specs["vocal-hub"].kind, "voice")

    def test_plan_embed_lists_channels(self) -> None:
        emb = plan_embed(build_plan())
        self.assertIn("𝑃𝑖𝑛𝑔𝑠", emb.to_dict()["fields"][1]["value"])
        self.assertLessEqual(len(emb.fields), 25)


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #
class BuildTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        settings = Settings(
            token="fake",
            database_path=Path(self.tmp.name) / "db.json",
            staff_permission="manage_guild",
        )
        self.bot = VesparaBot(settings)
        for extension in EXTENSIONS:
            await self.bot.load_extension(extension)
        # Aucune pause anti-spam en test : les créations sont instantanées.
        self._delay = serverbuild.BUILD_DELAY
        serverbuild.BUILD_DELAY = 0
        self.guild = FakeGuild()

    async def asyncTearDown(self) -> None:
        serverbuild.BUILD_DELAY = self._delay
        for name in list(self.bot.cogs):
            await self.bot.remove_cog(name)
        await self.bot.close()
        self.tmp.cleanup()

    async def test_command_is_registered_and_admin_only(self) -> None:
        command = self.bot.tree.get_command("build")
        self.assertIsNotNone(command)
        # Réservée aux administrateurs : invisible pour les autres membres
        self.assertEqual(
            command.default_permissions.value,  # type: ignore[union-attr]
            discord.Permissions(administrator=True).value,
        )
        self.assertTrue(command.checks)  # type: ignore[union-attr]
        names = {parameter.name for parameter in command.parameters}  # type: ignore[union-attr]
        self.assertIn("apercu", names)
        self.assertIn("confirmer", names)

    async def test_build_creates_channels_and_messages(self) -> None:
        result = await build_server(self.bot, self.guild, actor=None)
        self.assertIsNone(result.error)
        self.assertFalse(result.failed, result.failed)
        self.assertGreaterEqual(result.created_count, 15)

        names = [name for _, name, _ in self.guild.created_calls]
        for expected in (
            "-➠˗ˏˋ📜┆𝑅𝑒𝑔𝑙𝑒𝑠ˎˊ˗",
            "-➠˗ˏˋ📢┆𝐴𝑛𝑛𝑜𝑛𝑐𝑒𝑠ˎˊ˗",
            "-➠˗ˏˋ🤖┆𝐶𝑜𝑚𝑚𝑎𝑛𝑑𝑒𝑠-𝑏𝑜𝑡ˎˊ˗",
            "-➠˗ˏˋ🎐┆𝑃𝑖𝑛𝑔𝑠ˎˊ˗",
            "˗ˏˋ📌┆𝐼𝑛𝑓𝑜𝑟𝑚𝑎𝑡𝑖𝑜𝑛𝑠ˎˊ˗",
        ):
            self.assertIn(expected, names)

        # Chaque salon du plan a un nom unique et une longueur valide.
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(len(name) <= 100 for name in names))

    async def test_build_publishes_rules_embed(self) -> None:
        result = await build_server(self.bot, self.guild, actor=None)
        rules_channel = result.channels["regles"]
        self.assertTrue(rules_channel.sent)
        embed = rules_channel.sent[0]["embed"].to_dict()
        self.assertIn("Règlement", embed["title"])
        self.assertEqual(embed["description"], SIMPLE_RULES)
        # Le règlement est enregistré pour /rules
        self.assertEqual(self.bot.db.guild(self.guild.id)["rules"], SIMPLE_RULES)

    async def test_build_publishes_several_intros(self) -> None:
        result = await build_server(self.bot, self.guild, actor=None)
        with_message = [spec for spec in result.channels.values() if getattr(spec, "sent", None)]
        self.assertGreaterEqual(len(with_message), 8)
        # Les vocaux classiques restent muets, le générateur reçoit son mode d'emploi
        # (Discord permet d'écrire dans le chat d'un salon vocal).
        self.assertFalse(result.channels["vocal-general"].sent)
        self.assertTrue(result.channels["vocal-hub"].sent)

    async def test_config_is_saved(self) -> None:
        result = await build_server(self.bot, self.guild, actor=None)
        settings = self.bot.db.guild(self.guild.id)
        self.assertEqual(settings["announce_channel_id"], result.channels["annonces"].id)
        self.assertEqual(settings["casino_channel_id"], result.channels["casino"].id)
        self.assertEqual(settings["levelup_channel_id"], result.channels["niveaux"].id)
        self.assertEqual(settings["voice_hub_id"], result.channels["vocal-hub"].id)

    async def test_existing_config_is_kept(self) -> None:
        settings = self.bot.db.guild(self.guild.id)
        settings["announce_channel_id"] = 4242
        await build_server(self.bot, self.guild, actor=None)
        self.assertEqual(self.bot.db.guild(self.guild.id)["announce_channel_id"], 4242)

    async def test_permissions_are_applied(self) -> None:
        result = await build_server(self.bot, self.guild, actor=None)
        read_only = result.channels["regles"].overwrites
        everyone = self.guild.default_role
        self.assertFalse(read_only[everyone].send_messages)
        self.assertTrue(read_only[everyone].view_channel)

        staff = result.channels["staff"].overwrites
        self.assertFalse(staff[everyone].view_channel)
        self.assertIn(self.guild.me, staff)

        self.assertEqual(result.channels["general"].overwrites, {})

    async def test_build_is_idempotent(self) -> None:
        await build_server(self.bot, self.guild, actor=None)
        created_first = len(self.guild.created_calls)
        result = await build_server(self.bot, self.guild, actor=None)
        self.assertEqual(result.created_count, 0)
        self.assertGreaterEqual(result.reused_count, 15)
        self.assertEqual(len(self.guild.created_calls), created_first)
        self.assertFalse([channel for channel in self.guild.text_channels if len(channel.sent) > 1])

    async def test_build_without_permission(self) -> None:
        self.guild.me.guild_permissions = discord.Permissions(send_messages=True)
        result = await build_server(self.bot, self.guild, actor=None)
        self.assertIsNotNone(result.error)
        self.assertEqual(self.guild.created_calls, [])

    async def test_failures_are_reported(self) -> None:
        async def boom(*args: Any, **kwargs: Any) -> Any:
            raise discord.HTTPException(
                response=type("R", (), {"status": 500, "reason": "boom"})(), message="boom"
            )

        self.guild.create_text_channel = boom  # type: ignore[method-assign]
        result = await build_server(self.bot, self.guild, actor=None)
        self.assertTrue(result.failed)
        emb = result_embed(result)
        self.assertIn("partiellement", emb.description.lower())
        self.assertIn("Échecs", [field.name for field in emb.fields])

    async def test_custom_rules_text(self) -> None:
        result = await build_server(
            self.bot,
            self.guild,
            options=BuildOptions(texte_regles="Sois sympa."),
            actor=None,
        )
        embed = result.channels["regles"].sent[0]["embed"].to_dict()
        self.assertEqual(embed["description"], "Sois sympa.")
        self.assertEqual(self.bot.db.guild(self.guild.id)["rules"], "Sois sympa.")

    async def test_staff_warning_without_role(self) -> None:
        result = await build_server(self.bot, self.guild, actor=None)
        self.assertTrue(any("staff" in text for text in result.warnings))

    async def test_result_embed_summary(self) -> None:
        result = await build_server(self.bot, self.guild, actor=None)
        emb = result_embed(result)
        self.assertIn("Serveur construit", emb.title)
        names = [field.name for field in emb.fields]
        self.assertIn("Créés", names)



class BuildCommandTests(unittest.IsolatedAsyncioTestCase):
    """La commande elle-même : aperçu, confirmation et exécution."""

    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.bot = VesparaBot(
            Settings(
                token="fake3",
                database_path=Path(self.tmp.name) / "db.json",
                staff_permission="manage_guild",
            )
        )
        for extension in EXTENSIONS:
            await self.bot.load_extension(extension)
        self._delay = serverbuild.BUILD_DELAY
        serverbuild.BUILD_DELAY = 0
        self.guild = FakeGuild(9)
        self.command = self.bot.tree.get_command("build")

    async def asyncTearDown(self) -> None:
        serverbuild.BUILD_DELAY = self._delay
        for name in list(self.bot.cogs):
            await self.bot.remove_cog(name)
        await self.bot.close()
        self.tmp.cleanup()

    class Actor:
        """Auteur de la commande : doit être hachable (clé de permissions)."""

        id = 1
        mention = "<@1>"

        def __str__(self) -> str:
            return "admin"

    def interaction(self) -> Any:
        interaction = types.SimpleNamespace(
            guild=self.guild,
            user=self.Actor(),
            response=types.SimpleNamespace(
                is_done=lambda: False,
                send_message=self._record("response"),
                defer=self._defer,
            ),
            followup=types.SimpleNamespace(send=self._record("followup")),
            edit_original_response=self._record("edit"),
        )
        interaction.sent = []
        interaction.deferred = False
        return interaction

    def _record(self, box: str) -> Any:
        async def _send(**kwargs: Any) -> None:
            self._last_sent.append((box, kwargs))

        _send.__name__ = box
        return _send

    async def _defer(self, **kwargs: Any) -> None:
        self._deferred = True

    async def test_preview_creates_nothing(self) -> None:
        self._last_sent: list[tuple[str, dict[str, Any]]] = []
        self._deferred = False
        interaction = self.interaction()
        await self.command.callback(self.bot.get_cog("Build"), interaction, apercu=True)  # type: ignore[union-attr]
        self.assertEqual(self.guild.created_calls, [])
        box, kwargs = self._last_sent[0]
        self.assertEqual(box, "response")
        self.assertIn("Aperçu", kwargs["embed"].title)

    async def test_confirmation_declined_creates_nothing(self) -> None:
        self._last_sent = []
        self._deferred = False
        interaction = self.interaction()
        # La vue de confirmation attend un clic : on la fait expirer tout de suite.
        original_prompt = ConfirmView.prompt

        async def _fake_prompt(view: Any, interaction: Any, emb: Any, **kwargs: Any) -> bool:
            return False

        ConfirmView.prompt = _fake_prompt  # type: ignore[method-assign]
        try:
            await self.command.callback(self.bot.get_cog("Build"), interaction)  # type: ignore[union-attr]
        finally:
            ConfirmView.prompt = original_prompt  # type: ignore[method-assign]
        self.assertEqual(self.guild.created_calls, [])

    async def test_confirmed_build_runs(self) -> None:
        self._last_sent = []
        self._deferred = False
        interaction = self.interaction()

        async def _fake_prompt(view: Any, interaction: Any, emb: Any, **kwargs: Any) -> bool:
            return True

        original_prompt = ConfirmView.prompt
        ConfirmView.prompt = _fake_prompt  # type: ignore[method-assign]
        try:
            await self.command.callback(self.bot.get_cog("Build"), interaction, confirmer=True)  # type: ignore[union-attr]
        finally:
            ConfirmView.prompt = original_prompt  # type: ignore[method-assign]

        self.assertTrue(self._deferred)
        self.assertGreaterEqual(len(self.guild.created_calls), 15)
        box, kwargs = self._last_sent[-1]
        self.assertEqual(box, "followup")
        self.assertIn("Serveur construit", kwargs["embed"].title)


class ConfigRecordingTests(unittest.IsolatedAsyncioTestCase):
    """Vérifie que les identifiants enregistrés sont ceux des salons créés."""

    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.bot = VesparaBot(
            Settings(
                token="fake2",
                database_path=Path(self.tmp.name) / "db.json",
                staff_permission="manage_guild",
            )
        )
        for extension in EXTENSIONS:
            await self.bot.load_extension(extension)
        self._delay = serverbuild.BUILD_DELAY
        serverbuild.BUILD_DELAY = 0
        self.guild = FakeGuild(8)

    async def asyncTearDown(self) -> None:
        serverbuild.BUILD_DELAY = self._delay
        for name in list(self.bot.cogs):
            await self.bot.remove_cog(name)
        await self.bot.close()
        self.tmp.cleanup()

    async def test_stored_ids_match_created_channels(self) -> None:
        result = await build_server(self.bot, self.guild, actor=None)
        settings = self.bot.db.guild(self.guild.id)
        self.assertEqual(result.channels["annonces"].id, settings["announce_channel_id"])
        self.assertEqual(result.channels["niveaux"].id, settings["levelup_channel_id"])
        self.assertEqual(result.channels["casino"].id, settings["casino_channel_id"])
        self.assertEqual(result.channels["vocal-hub"].id, settings["voice_hub_id"])
        self.assertEqual(settings["voice_category_id"], result.channels["vocal-hub"].category.id)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
