"""Test « fumée » : exécute toutes les commandes avec des interactions simulées.

Objectif : garantir qu'aucune commande ne lève d'exception de rendu (embed,
arguments par défaut, absence de latence, base vide…) sans avoir besoin de
Discord. Chaque commande est appelée via son `callback` avec des objets factices.
"""

from __future__ import annotations

import datetime as dt
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any

import discord
from discord import app_commands

from bot.cogs import EXTENSIONS
from bot.config import Settings
from bot.constants import TEMPVOICE_DELETE_GRACE
from bot.main import VesparaBot


# --------------------------------------------------------------------------- #
# Doubles Discord
# --------------------------------------------------------------------------- #
class _Asset:
    url = "https://cdn.discord.test/avatar.png"


class FakeRole:
    def __init__(self, role_id: int = 0, name: str = "Rôle") -> None:
        self.id = role_id
        self.name = name
        self.mention = f"<@&{role_id}>"
        self.managed = False
        self.position = role_id
        self.members: list[Any] = []
        self.hoist = False
        self.permissions = discord.Permissions.all()
        self.color = discord.Colour(0x8B5CF6)
        self.created_at = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
        self.mentionable = False
        self.position = role_id

    def is_default(self) -> bool:
        return self.id == 0


class FakeMember:
    def __init__(self, member_id: int, guild: "FakeGuild", name: str = "Léa", *, bot: bool = False) -> None:
        self.id = member_id
        self.guild = guild
        self.name = name
        self.display_name = name
        self.mention = f"<@{member_id}>"
        self.bot = bot
        self.roles: list[Any] = []
        self.guild_permissions = discord.Permissions(administrator=True)
        self.display_avatar = _Asset()
        self.voice = None
        self.created_at = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
        self.joined_at = dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc)
        self.nick = None
        self.top_role = FakeRole(1)
        self.color = None

    async def add_roles(self, role: Any, reason: str | None = None) -> None:
        self.roles.append(role)


class FakeChannel:
    def __init__(self, channel_id: int, guild: "FakeGuild") -> None:
        self.id = channel_id
        self.guild = guild
        self.name = "général"
        self.mention = f"<#{channel_id}>"
        self.sent: list[dict[str, Any]] = []
        self.members: list[Any] = []
        self.category = None

    async def send(self, **kwargs: Any) -> Any:
        self.sent.append(kwargs)
        return types.SimpleNamespace(id=len(self.sent), edit=self._edit, delete=self._delete)

    async def _edit(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)

    async def _delete(self) -> None:
        return None

    def get_partial_message(self, message_id: int) -> Any:
        return types.SimpleNamespace(id=message_id, edit=self._edit)

    async def fetch_message(self, message_id: int) -> Any:
        return types.SimpleNamespace(id=message_id, edit=self._edit)

    def permissions_for(self, member: Any) -> discord.Permissions:
        return discord.Permissions.all()


class FakeGuild:
    def __init__(self, guild_id: int = 1) -> None:
        self.id = guild_id
        self.name = "Vespara"
        self.icon = None
        self.member_count = 10
        self.default_role = FakeRole(0, "@everyone")
        self.roles: list[FakeRole] = [self.default_role]
        self.system_channel = None
        self.description = "Le serveur chill"
        self.owner_id = 42
        self.owner = None
        self.created_at = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
        self.premium_subscription_count = 3
        self.premium_tier = 1
        self.verification_level = discord.VerificationLevel.low
        self.features: list[str] = []
        self.rules_channel = None
        self.afk_channel = None
        self.banner = None
        self.channels: dict[int, FakeChannel] = {}
        self._members: dict[int, FakeMember] = {}

    @property
    def me(self) -> FakeMember:
        return FakeMember(999, self, "Vespara", bot=True)

    @property
    def members(self) -> list[FakeMember]:
        return list(self._members.values())

    @property
    def voice_channels(self) -> list[FakeChannel]:
        return [channel for channel in self.channels.values() if isinstance(channel, FakeChannel)]

    @property
    def text_channels(self) -> list[FakeChannel]:
        return list(self.channels.values())

    def get_role(self, role_id: int) -> FakeRole | None:
        return next((role for role in self.roles if role.id == role_id), None)

    def get_member(self, member_id: int) -> FakeMember | None:
        return self._members.get(int(member_id))

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        return self.channels.get(int(channel_id))

    def add_member(self, member: FakeMember) -> FakeMember:
        self._members[member.id] = member
        return member


class FakeResponse:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.modal: Any = None
        self.deferred = False
        self.edited: dict[str, Any] | None = None

    def is_done(self) -> bool:
        return bool(self.sent or self.modal or self.deferred)

    async def send_message(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)

    async def send_modal(self, modal: Any) -> None:
        self.modal = modal
        self.sent.append({"modal": modal})

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
        self.command: Any = None
        self.message: Any = None

    async def original_response(self) -> Any:
        return types.SimpleNamespace(id=1, edit=self._edit)

    async def _edit(self, **kwargs: Any) -> None:
        self.response.edited = kwargs

    async def edit_original_response(self, **kwargs: Any) -> None:
        self.response.edited = kwargs


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
class SmokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        settings = Settings(
            token="fake", database_path=Path(self.tmp.name) / "db.json", staff_permission="manage_guild"
        )
        self.bot = VesparaBot(settings)
        for extension in EXTENSIONS:
            await self.bot.load_extension(extension)
        self.bot.apply_command_visibility()
        # Pas de heartbeat en test : la latence vaut NaN côté discord.py.
        VesparaBot.latency_ms = property(lambda _self: 45)  # type: ignore[assignment]

        self.guild = FakeGuild()
        self.channel = FakeChannel(10, self.guild)
        self.guild.channels[10] = self.channel
        self.owner = self.guild.add_member(FakeMember(42, self.guild, "Léa"))
        self.other = self.guild.add_member(FakeMember(43, self.guild, "Max"))
        self.role = FakeRole(77, "Actif")
        self.guild.roles.append(self.role)

    async def asyncTearDown(self) -> None:
        await self.bot.close()
        self.tmp.cleanup()

    # ------------------------------------------------------------------ #
    def interaction(self) -> FakeInteraction:
        return FakeInteraction(self.owner, self.guild, self.channel, self.bot)

    def group(self, name: str) -> app_commands.Group:
        command = self.bot.tree.get_command(name)
        self.assertIsInstance(command, app_commands.Group, name)
        return command  # type: ignore[return-value]

    async def call(self, group_name: str, command_name: str, *args: Any) -> FakeInteraction:
        group = self.group(group_name)
        command = group.get_command(command_name)
        self.assertIsNotNone(command, f"/{group_name} {command_name}")
        interaction = self.interaction()
        await command.callback(group, interaction, *args)  # type: ignore[union-attr]
        return interaction

    def assert_answered(self, interaction: FakeInteraction) -> None:
        answered = (
            interaction.response.sent
            or interaction.followup.sent
            or interaction.response.edited is not None
        )
        self.assertTrue(answered, "La commande n'a rien répondu")

    # ------------------------------------------------------------------ #
    async def test_economy_commands(self) -> None:
        for name, args in (
            ("profil", (None,)),
            ("solde", (None,)),
            ("classement", (None,)),
            ("daily", ()),
            ("work", ()),
            ("niveau", (None,)),
        ):
            with self.subTest(command=name):
                interaction = await self.call("eco", name, *args)
                self.assert_answered(interaction)

        interaction = await self.call("eco", "payer", self.other, "1k")
        self.assert_answered(interaction)

        # Mauvais montant : message d'erreur, pas d'exception
        interaction = await self.call("eco", "payer", self.other, "beaucoup")
        self.assert_answered(interaction)

    async def test_casino_commands(self) -> None:
        from unittest.mock import AsyncMock, patch

        from bot.services.economy import EconomyManager

        manager = self.bot.economy
        self.assertIsInstance(manager, EconomyManager)
        manager.add_coins(self.guild.id, self.owner.id, 10_000)

        # Les animations (rouleaux, bille, dés) sont accélérées pour le test.
        with (
            patch("bot.ui.casino.asyncio.sleep", new=AsyncMock()),
            patch("bot.cogs.casino.asyncio.sleep", new=AsyncMock()),
        ):
            for name, args in (
                ("accueil", ()),
                ("jeux", ()),
                ("blackjack", (100,)),
                ("slots", (100,)),
                ("roulette", (100, "rouge")),
                ("roulette", (100, "17")),
                ("roulette", (100, "banane")),
                ("des", (100, "sept")),
                ("mise-max", (None, None)),
            ):
                with self.subTest(command=name, args=args):
                    interaction = await self.call("casino", name, *args)
                    self.assert_answered(interaction)

    async def test_casino_channel_restriction(self) -> None:
        self.bot.db.guild(self.guild.id)["casino_channel_id"] = 999
        interaction = await self.call("casino", "slots", 10)
        self.assert_answered(interaction)
        embed = interaction.response.sent[0]["embed"]
        self.assertIn("salon", embed.description.lower())

    async def test_shop_admin_flow(self) -> None:
        interaction = await self.call(
            "eco-admin", "article-ajouter", "Rôle VIP", 300, None, self.role, "Le rôle VIP", "💎", 5, None, 2, None
        )
        self.assert_answered(interaction)

        item = self.bot.economy.find_shop_item(self.guild.id, "Rôle VIP")
        self.assertIsNotNone(item)

        self.bot.economy.add_coins(self.guild.id, self.owner.id, 5000)
        interaction = await self.call("eco-admin", "article-liste")
        self.assert_answered(interaction)

        interaction = await self.call("eco-admin", "article-modifier", "Rôle VIP", "Rôle VIP+", 250)
        self.assert_answered(interaction)

        interaction = await self.call("boutique", "voir")
        self.assert_answered(interaction)

        interaction = await self.call("boutique", "acheter", "Rôle VIP+")
        self.assert_answered(interaction)
        self.assertIn(self.role, self.owner.roles)

        interaction = await self.call("boutique", "inventaire")
        self.assert_answered(interaction)

        interaction = await self.call("eco-admin", "article-supprimer", "Rôle VIP+")
        self.assert_answered(interaction)

        # Article inexistant : message d'erreur propre
        interaction = await self.call("boutique", "acheter", "Fantôme")
        self.assert_answered(interaction)

    async def test_level_rewards_and_xp_command(self) -> None:
        interaction = await self.call("eco-admin", "recompense", 3, self.role, False)
        self.assert_answered(interaction)

        interaction = await self.call("eco-admin", "xp", self.other, 2000)
        self.assert_answered(interaction)
        self.assertIn(self.role, self.other.roles)
        self.assertGreater(self.bot.economy.account(self.guild.id, self.other.id)["level"], 1)

        interaction = await self.call("eco-admin", "recompense", 3, None, True)
        self.assert_answered(interaction)

    async def test_admin_money_and_settings(self) -> None:
        for name, args in (
            ("donner", (self.other, "2k")),
            ("retirer", (self.other, "500")),
            ("etat", ()),
            ("parametres", (True, 1.5, self.channel, True, self.channel, False, False)),
            ("reinitialiser", (self.other, True)),
        ):
            with self.subTest(command=name):
                interaction = await self.call("eco-admin", name, *args)
                self.assert_answered(interaction)

        # Retrait impossible (solde insuffisant) → erreur propre
        interaction = await self.call("eco-admin", "retirer", self.other, "999999")
        self.assert_answered(interaction)

    async def test_menu_and_buttons(self) -> None:
        from bot.ui.menu import MenuView

        interaction = self.interaction()
        menu_command = self.bot.tree.get_command("menu")
        await menu_command.callback(self.bot.get_cog("CommunityMenu"), interaction)  # type: ignore[union-attr]
        self.assert_answered(interaction)

        view = MenuView(self.bot)
        self.assertGreaterEqual(len(view.children), 8)
        for item in view.children:
            interaction = self.interaction()
            await item.callback(interaction)  # type: ignore[union-attr]
            self.assert_answered(interaction)
            self.assertNotIn("erreur", str(interaction.response.sent).lower())

    async def test_ping_and_vocal_state(self) -> None:
        interaction = self.interaction()
        ping = self.bot.tree.get_command("ping")
        await ping.callback(self.bot.get_cog("Utilities"), interaction)  # type: ignore[union-attr]
        self.assertIsNotNone(interaction.response.edited)

        # Sans installation, /vocal etat doit répondre un message d'information
        interaction = await self.call("vocal", "etat")
        self.assert_answered(interaction)

        interaction = await self.call("vocal", "rattacher")
        self.assert_answered(interaction)

    async def test_public_commands_do_not_crash(self) -> None:
        for name in ("userinfo", "serverinfo", "roleinfo", "rules", "giveaways", "botinfo"):
            command = self.bot.tree.get_command(name)
            if command is None:  # pragma: no cover - toutes existent
                continue
            interaction = self.interaction()
            kwargs: dict[str, Any] = {}
            if name == "roleinfo":
                kwargs["role"] = self.role
            with self.subTest(command=name):
                await command.callback(self.bot.get_cog("Utilities"), interaction, **kwargs)  # type: ignore[union-attr]
                self.assert_answered(interaction)

    # ------------------------------------------------------------------ #
    def test_tempvoice_grace_period(self) -> None:
        self.assertEqual(TEMPVOICE_DELETE_GRACE, 5.0)
        manager = self.bot.tempvoice
        self.assertEqual(manager.deletion_grace, 5.0)

    def test_database_schema_has_economy(self) -> None:
        guild = self.bot.db.guild(self.guild.id)
        for key in ("xp_enabled", "xp_rate", "shop_items", "level_rewards", "casino_channel_id"):
            self.assertIn(key, guild)
        self.assertIn("users", self.bot.db.data)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
