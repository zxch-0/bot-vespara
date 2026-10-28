"""Vérifie le chargement des cogs et la structure des commandes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import discord
from discord import app_commands

from bot.cogs import EXTENSIONS
from bot.config import Settings
from bot.main import VesparaBot


class CommandTreeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        settings = Settings(
            token="fake-token",
            database_path=Path(self.tmp.name) / "vespara.json",
            staff_permission="manage_guild",
        )
        self.bot = VesparaBot(settings)
        for extension in EXTENSIONS:
            await self.bot.load_extension(extension)
        self.bot.apply_command_visibility()

    async def asyncTearDown(self) -> None:
        for name in list(self.bot.cogs):
            await self.bot.remove_cog(name)
        await self.bot.close()
        self.tmp.cleanup()

    # ------------------------------------------------------------------ #
    def test_public_commands_exist(self) -> None:
        expected = {
            "menu",
            "ping",
            "botinfo",
            "userinfo",
            "avatar",
            "banner",
            "serverinfo",
            "roleinfo",
            "rules",
            "giveaways",
        }
        names = {command.name for command in self.bot.tree.get_commands()}
        self.assertTrue(expected.issubset(names), expected - names)

    def test_staff_commands_are_hidden(self) -> None:
        for root in ("giveaway", "annonce", "autoresponder", "config", "vocal"):
            command = self.bot.tree.get_command(root)
            self.assertIsNotNone(command, root)
            self.assertIsNotNone(command.default_permissions, root)  # type: ignore[union-attr]
            self.assertEqual(command.default_permissions.value, discord.Permissions(manage_guild=True).value)  # type: ignore[union-attr]

    def test_staff_subcommands_have_role_check(self) -> None:
        for root in ("giveaway", "autoresponder", "config", "vocal"):
            group = self.bot.tree.get_command(root)
            self.assertIsInstance(group, app_commands.Group)
            for subcommand in group.commands:  # type: ignore[union-attr]
                with self.subTest(command=f"/{root} {subcommand.name}"):
                    self.assertEqual(len(subcommand.checks), 1)

        annonce = self.bot.tree.get_command("annonce")
        self.assertTrue(annonce.checks)  # type: ignore[union-attr]

    def test_staffrole_is_admin_only(self) -> None:
        command = self.bot.tree.get_command("staffrole")
        self.assertIsNotNone(command)
        self.assertEqual(command.default_permissions.value, discord.Permissions(administrator=True).value)  # type: ignore[union-attr]
        self.assertTrue(command.checks)  # type: ignore[union-attr]

    def test_public_commands_are_not_restricted(self) -> None:
        for name in ("menu", "ping", "rules", "avatar"):
            command = self.bot.tree.get_command(name)
            self.assertIsNone(command.default_permissions, name)  # type: ignore[union-attr]

    def test_commands_serialize(self) -> None:
        for command in self.bot.tree.get_commands():
            payload = command.to_dict(self.bot.tree)
            self.assertTrue(payload["name"])
            self.assertTrue(payload["description"])
            if isinstance(command, app_commands.Group):
                self.assertTrue(command.commands)
                for subcommand in command.commands:
                    self.assertTrue(subcommand.to_dict(self.bot.tree)["name"])

    def test_giveaway_manager_registered(self) -> None:
        self.assertIsNotNone(self.bot.giveaway_manager)

    def test_tempvoice_manager_registered(self) -> None:
        self.assertIsNotNone(self.bot.tempvoice)

    def test_vocal_subcommands(self) -> None:
        group = self.bot.tree.get_command("vocal")
        self.assertIsInstance(group, app_commands.Group)
        names = {subcommand.name for subcommand in group.commands}  # type: ignore[union-attr]
        self.assertEqual(
            names,
            {"installer", "etat", "modele", "limite", "rattacher", "nettoyer", "desactiver"},
        )

    def test_command_count_includes_subcommands(self) -> None:
        # 18 commandes racine + 5 giveaways + 7 autoresponder + 4 config + 7 vocal
        self.assertEqual(self.bot.command_count, 41)

    def test_magic_ball_commands(self) -> None:
        for name in ("boule", "8ball"):
            command = self.bot.tree.get_command(name)
            self.assertIsNotNone(command, name)
            # Commande publique : aucune permission staff requise
            self.assertIsNone(command.default_permissions, name)  # type: ignore[union-attr]
            # Un cooldown anti-spam est bien appliqué
            self.assertEqual(len(command.checks), 1, name)  # type: ignore[union-attr]
            (parameter,) = command.parameters  # type: ignore[union-attr]
            self.assertEqual(parameter.name, "question")
            self.assertTrue(parameter.required)
            self.assertEqual((parameter.min_value, parameter.max_value), (3, 200))

    def test_magic_ball_is_not_staff_restricted(self) -> None:
        from bot.constants import STAFF_COMMAND_ROOTS

        self.assertNotIn("boule", STAFF_COMMAND_ROOTS)
        self.assertNotIn("8ball", STAFF_COMMAND_ROOTS)

    def test_custom_ids_are_unique(self) -> None:
        from bot.ui.giveaway import GiveawayView
        from bot.ui.menu import MenuView

        view = GiveawayView(self.bot, "12")
        ids = [item.custom_id for item in view.children]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(custom_id.endswith(":12") for custom_id in ids))

        menu_ids = [item.custom_id for item in MenuView(self.bot).children]
        self.assertEqual(len(menu_ids), len(set(menu_ids)))
        self.assertTrue(all(custom_id.startswith("vespara:menu:") for custom_id in menu_ids))


class GiveawayEmbedTests(unittest.IsolatedAsyncioTestCase):
    def test_embed_contains_key_information(self) -> None:
        from bot.services.giveaways import build_giveaway_embed

        record = {
            "id": "1",
            "guild_id": 1,
            "prize": "Nitro 1 mois",
            "started_at": 1_000_000,
            "ends_at": 1_003_600,
            "entries": [10, 20],
            "winners": [],
            "winners_count": 1,
            "ended": False,
            "host_name": "zxc",
        }
        emb = build_giveaway_embed(record)
        self.assertIn("Nitro 1 mois", emb.title)
        self.assertEqual(len(emb.fields), 3)
        self.assertIn("participant", emb.fields[1].name.lower())
        self.assertIn("zxc", emb.footer.text)

    def test_ended_embed_lists_winners(self) -> None:
        from bot.services.giveaways import build_giveaway_embed

        record = {
            "id": "2",
            "guild_id": 1,
            "prize": "Steam",
            "started_at": 1_000_000,
            "ends_at": 1_003_600,
            "ended_at": 1_003_600,
            "entries": [10, 20],
            "winners": [20],
            "winners_count": 1,
            "ended": True,
            "host_name": "zxc",
        }
        emb = build_giveaway_embed(record)
        self.assertIn("Steam", emb.title)
        self.assertIn("<@20>", emb.description)


if __name__ == "__main__":
    unittest.main()
