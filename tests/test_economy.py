"""Tests de l'économie, des niveaux et de la boutique."""

from __future__ import annotations

import random
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any

from bot.cogs.economy import parse_amount
from bot.constants import ECONOMY_MAX_BET, ECONOMY_START_BALANCE
from bot.database import Database
from bot.services.economy import (
    Cooldown,
    EconomyError,
    EconomyManager,
    InsufficientFunds,
    default_shop_item,
    format_coins,
    format_coins_short,
    humanize_short,
    level_from_total_xp,
    level_up_rewards,
    total_xp_for_level,
    xp_for_level,
)


# --------------------------------------------------------------------------- #
# Doubles
# --------------------------------------------------------------------------- #
class FakeGuild:
    def __init__(self, guild_id: int = 1, name: str = "Vespara") -> None:
        self.id = guild_id
        self.name = name
        self.icon = None
        self.roles: dict[int, Any] = {}

    def get_role(self, role_id: int) -> Any | None:
        return self.roles.get(int(role_id))

    def get_member(self, member_id: int) -> Any | None:
        return None


class FakeRole:
    def __init__(self, role_id: int = 500, name: str = "Actif") -> None:
        self.id = role_id
        self.name = name
        self.mention = f"<@&{role_id}>"


class FakeMember:
    def __init__(self, member_id: int = 42, guild: FakeGuild | None = None, name: str = "Léa") -> None:
        self.id = member_id
        self.name = name
        self.display_name = name
        self.mention = f"<@{member_id}>"
        self.guild = guild or FakeGuild()
        self.roles: list[Any] = []
        self.added: list[Any] = []

    async def add_roles(self, role: Any, reason: str | None = None) -> None:
        self.roles.append(role)
        self.added.append(role)


class FakeBot:
    def __init__(self, database: Database) -> None:
        self.db = database
        self.settings = types.SimpleNamespace(brand="Vespara", tagline="Le serveur chill")


# --------------------------------------------------------------------------- #
# Formules pures
# --------------------------------------------------------------------------- #
class LevelMathTests(unittest.TestCase):
    def test_xp_curve_is_increasing(self) -> None:
        values = [xp_for_level(level) for level in range(1, 30)]
        self.assertTrue(all(b >= a for a, b in zip(values, values[1:], strict=False)))
        self.assertEqual(values[0], 120)

    def test_level_from_total_xp(self) -> None:
        self.assertEqual(level_from_total_xp(0).level, 1)
        info = level_from_total_xp(120)
        self.assertEqual((info.level, info.xp), (2, 0))
        # Juste avant le niveau suivant
        before = level_from_total_xp(total_xp_for_level(3) - 1)
        self.assertEqual(before.level, 2)
        self.assertGreater(before.ratio, 0.9)

    def test_progress_ratio_bounds(self) -> None:
        for total in (0, 50, 500, 12_345):
            info = level_from_total_xp(total)
            self.assertGreaterEqual(info.ratio, 0.0)
            self.assertLessEqual(info.ratio, 1.0)

    def test_level_up_rewards(self) -> None:
        self.assertEqual(level_up_rewards(1), 25)
        self.assertGreater(level_up_rewards(10), level_up_rewards(2))

    def test_humanize_and_format(self) -> None:
        self.assertEqual(humanize_short(30), "30 s")
        self.assertEqual(humanize_short(3600), "1 h")
        self.assertEqual(humanize_short(3661), "1 h 1 min")
        self.assertEqual(format_coins(1234), "1 234 coins")
        self.assertTrue(format_coins_short(1234).startswith("🪙"))

    def test_parse_amount(self) -> None:
        self.assertEqual(parse_amount("250"), 250)
        self.assertEqual(parse_amount("1 000"), 1000)
        self.assertEqual(parse_amount("1k"), 1000)
        self.assertEqual(parse_amount("1.5k"), 1500)
        self.assertEqual(parse_amount("2M"), 2_000_000)
        for bad in ("", "abc", "-5"):
            with self.subTest(value=bad), self.assertRaises(EconomyError):
                parse_amount(bad)


# --------------------------------------------------------------------------- #
# Gestionnaire
# --------------------------------------------------------------------------- #
class EconomyManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.json")
        self.bot = FakeBot(self.db)
        self.manager = EconomyManager(self.bot)  # type: ignore[arg-type]
        self.guild = FakeGuild()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    # ------------------------------------------------------------------ #
    def test_new_account_starts_with_balance(self) -> None:
        record = self.manager.account(self.guild.id, 1)
        self.assertEqual(record["coins"], ECONOMY_START_BALANCE)
        self.assertEqual(level_from_total_xp(record["xp"]).level, 1)

    def test_add_and_remove_coins(self) -> None:
        self.manager.add_coins(self.guild.id, 1, 500)
        self.assertEqual(self.manager.balance(self.guild.id, 1), ECONOMY_START_BALANCE + 500)

        self.manager.remove_coins(self.guild.id, 1, 600)
        self.assertEqual(self.manager.balance(self.guild.id, 1), 0)

        with self.assertRaises(InsufficientFunds):
            self.manager.remove_coins(self.guild.id, 1, 10)

    def test_transfer(self) -> None:
        self.manager.add_coins(self.guild.id, 1, 400)
        self.manager.transfer(self.guild.id, 1, 2, 300)
        self.assertEqual(self.manager.balance(self.guild.id, 1), ECONOMY_START_BALANCE + 100)
        self.assertEqual(self.manager.balance(self.guild.id, 2), ECONOMY_START_BALANCE + 300)

        with self.assertRaises(EconomyError):
            self.manager.transfer(self.guild.id, 1, 1, 10)
        with self.assertRaises(InsufficientFunds):
            self.manager.transfer(self.guild.id, 2, 1, 10_000_000)

    def test_bet_limits(self) -> None:
        self.manager.add_coins(self.guild.id, 1, ECONOMY_MAX_BET + 1000)
        with self.assertRaises(EconomyError):
            self.manager.bet(self.guild.id, 1, 5, game="test")  # trop petite
        with self.assertRaises(EconomyError):
            self.manager.bet(self.guild.id, 1, ECONOMY_MAX_BET + 1, game="test")  # trop grande

        before = self.manager.balance(self.guild.id, 1)
        self.manager.bet(self.guild.id, 1, 100, game="test")
        self.assertEqual(self.manager.balance(self.guild.id, 1), before - 100)
        self.assertEqual(self.manager.account(self.guild.id, 1)["gambled"], 100)

    def test_grant_xp_levels_up(self) -> None:
        result = self.manager.grant_xp(self.guild.id, 1, xp_for_level(1))
        self.assertTrue(result["leveled_up"])
        self.assertEqual(result["level"], 2)
        self.assertEqual(result["coins_bonus"], level_up_rewards(2))
        self.assertGreater(
            self.manager.balance(self.guild.id, 1), ECONOMY_START_BALANCE
        )

        record = self.manager.account(self.guild.id, 1)
        self.assertEqual(record["level"], 2)

    def test_grant_xp_multiple_levels(self) -> None:
        total = total_xp_for_level(6)
        result = self.manager.grant_xp(self.guild.id, 1, total)
        self.assertEqual(result["level"], 6)
        self.assertEqual(result["levels"], [2, 3, 4, 5, 6])

    def test_daily_and_cooldown(self) -> None:
        now = 1_000_000.0
        first = self.manager.claim_daily(self.guild.id, 1, now=now)
        self.assertGreater(first["amount"], 0)
        self.assertEqual(first["streak"], 1)

        with self.assertRaises(Cooldown):
            self.manager.claim_daily(self.guild.id, 1, now=now + 60)

        # Lendemain : la série continue
        second = self.manager.claim_daily(self.guild.id, 1, now=now + 86_400)
        self.assertEqual(second["streak"], 2)
        self.assertGreaterEqual(second["amount"], first["amount"])

        # Trop longtemps après : la série repart à 1
        third = self.manager.claim_daily(self.guild.id, 1, now=now + 86_400 * 10)
        self.assertEqual(third["streak"], 1)

    def test_work_cooldown(self) -> None:
        now = 5_000.0
        result = self.manager.claim_work(self.guild.id, 1, rng=random.Random(3), now=now)
        self.assertGreater(result["amount"], 0)
        self.assertTrue(result["job"])

        with self.assertRaises(Cooldown):
            self.manager.claim_work(self.guild.id, 1, now=now + 10)

    def test_message_xp_cooldown(self) -> None:
        now = 10_000.0
        self.assertGreater(self.manager.message_xp(self.guild.id, 1, now=now), 0)
        self.assertEqual(self.manager.message_xp(self.guild.id, 1, now=now + 1), 0)
        self.assertGreater(self.manager.message_xp(self.guild.id, 1, now=now + 120), 0)

    # ------------------------------------------------------------------ #
    def test_shop_crud_and_purchase(self) -> None:
        item = self.manager.add_shop_item(
            self.guild.id,
            default_shop_item()
            | {"name": "Rôle VIP", "kind": "role", "price": 200, "role_id": 5, "stock": 2},
        )
        self.assertEqual(len(self.manager.shop_items(self.guild.id)), 1)
        self.assertIs(self.manager.find_shop_item(self.guild.id, "vip"), item)

        self.manager.add_coins(self.guild.id, 1, 1000)
        result = self.manager.purchase(self.guild.id, 1, item)
        self.assertEqual(result["owned"], 1)
        self.assertEqual(item["stock"], 1)
        self.assertEqual(result["balance"], ECONOMY_START_BALANCE + 800)
        self.assertEqual(self.manager.inventory(self.guild.id, 1)[str(item["id"])], 1)

        # Rupture de stock
        self.manager.purchase(self.guild.id, 1, item)
        with self.assertRaises(EconomyError):
            self.manager.purchase(self.guild.id, 1, item)

        self.assertTrue(self.manager.remove_shop_item(self.guild.id, item["id"]))
        self.assertEqual(self.manager.shop_items(self.guild.id), [])

    def test_purchase_requires_level_and_limit(self) -> None:
        item = self.manager.add_shop_item(
            self.guild.id,
            default_shop_item() | {"name": "Trophée", "price": 10, "requires_level": 5},
        )
        self.manager.add_coins(self.guild.id, 1, 1000)
        with self.assertRaises(EconomyError):
            self.manager.purchase(self.guild.id, 1, item)

        self.manager.grant_xp(self.guild.id, 1, total_xp_for_level(6))
        self.manager.purchase(self.guild.id, 1, item)  # niveau suffisant

        limited = self.manager.add_shop_item(
            self.guild.id, default_shop_item() | {"name": "Unique", "price": 1, "max_per_user": 1}
        )
        self.manager.purchase(self.guild.id, 1, limited)
        with self.assertRaises(EconomyError):
            self.manager.purchase(self.guild.id, 1, limited)

    def test_purchase_insufficient_funds(self) -> None:
        item = self.manager.add_shop_item(
            self.guild.id, default_shop_item() | {"name": "Cher", "price": 999_999}
        )
        with self.assertRaises(InsufficientFunds):
            self.manager.purchase(self.guild.id, 1, item)

    def test_disabled_item_cannot_be_bought(self) -> None:
        item = self.manager.add_shop_item(
            self.guild.id, default_shop_item() | {"name": "Off", "price": 1, "enabled": False}
        )
        with self.assertRaises(EconomyError):
            self.manager.purchase(self.guild.id, 1, item)

    # ------------------------------------------------------------------ #
    def test_leaderboard_and_rank(self) -> None:
        self.manager.add_coins(self.guild.id, 1, 500)
        self.manager.add_coins(self.guild.id, 2, 1500)
        self.manager.add_coins(self.guild.id, 3, 10)
        other_guild = FakeGuild(2)
        self.manager.add_coins(other_guild.id, 1, 99_999)

        entries = self.manager.leaderboard(self.guild.id)
        self.assertEqual([entry["user_id"] for entry in entries], [2, 1, 3])
        # Les comptes d'un autre serveur ne polluent pas le classement
        self.assertEqual(len(entries), 3)

        rank, total = self.manager.rank_of(self.guild.id, 1)
        self.assertEqual((rank, total), (2, 3))

        by_xp = self.manager.leaderboard(self.guild.id, by="xp")
        self.assertEqual(len(by_xp), 3)

    async def test_level_role_rewards(self) -> None:
        guild = FakeGuild()
        role = FakeRole(77)
        guild.roles[77] = role
        member = FakeMember(1, guild)
        self.manager.level_rewards(guild.id).append({"level": 3, "role_id": 77})

        given = await self.manager.apply_level_rewards(member, [3])
        self.assertEqual(given, [role])
        self.assertIn(role, member.roles)

        # Deuxième passage : pas de doublon
        given_again = await self.manager.apply_level_rewards(member, [3])
        self.assertEqual(given_again, [])
        self.assertEqual(len(member.added), 1)

    def test_stats_and_total_coins(self) -> None:
        self.manager.account(self.guild.id, 1)
        self.manager.account(self.guild.id, 2)
        total = self.db.total_coins(self.guild.id)
        self.assertEqual(total, ECONOMY_START_BALANCE * 2)
        self.assertEqual(self.db.stats()["accounts"], 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


# --------------------------------------------------------------------------- #
# Rendu (embeds) et interface
# --------------------------------------------------------------------------- #
class FakeUser:
    id = 42
    mention = "<@42>"
    display_name = "Léa"

    class _Asset:
        url = "https://cdn.discord.test/avatar.png"

    display_avatar = _Asset()


class EconomyEmbedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.json")
        self.bot = FakeBot(self.db)
        self.manager = EconomyManager(self.bot)  # type: ignore[arg-type]
        self.guild = FakeGuild()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    def test_profile_embed(self) -> None:
        from bot.ui.economy import profile_embed

        self.manager.add_coins(self.guild.id, 42, 250)
        emb = profile_embed(self.manager, self.guild, FakeUser())  # type: ignore[arg-type]
        self.assertIn("Léa", emb.title)
        fields = {field.name: field.value for field in emb.fields}
        self.assertIn("350", fields["🪙 Solde"])  # 100 de départ + 250
        self.assertIn("Classement", " ".join(fields))

    def test_leaderboard_embeds_pagination(self) -> None:
        from bot.ui.economy import leaderboard_embeds

        for user_id in range(1, 26):
            self.manager.add_coins(self.guild.id, user_id, user_id * 10)
        pages = leaderboard_embeds(self.manager, self.guild, per_page=10)
        self.assertEqual(len(pages), 3)
        self.assertIn("page 1/3", pages[0].footer.text)

        empty = leaderboard_embeds(self.manager, FakeGuild(99))
        self.assertEqual(len(empty), 1)
        self.assertIn("Personne", empty[0].description)

    def test_shop_embed_and_item_line(self) -> None:
        from bot.ui.economy import item_line, shop_embed

        item = self.manager.add_shop_item(
            self.guild.id,
            default_shop_item()
            | {"name": "Rôle VIP", "kind": "role", "price": 300, "role_id": 5, "emoji": "💎"},
        )
        line = item_line(item, owned=1, balance=500)
        self.assertIn("Rôle VIP", line)
        self.assertIn("x1", line)

        emb, pages = shop_embed(self.manager, self.guild, FakeUser())  # type: ignore[arg-type]
        self.assertEqual(pages, 1)
        self.assertIn("Boutique", emb.title)

        empty_guild = FakeGuild(5)
        emb_empty, _ = shop_embed(self.manager, empty_guild, FakeUser())  # type: ignore[arg-type]
        self.assertIn("vide", emb_empty.description)

    def test_inventory_embeds(self) -> None:
        from bot.ui.economy import inventory_embeds

        empty = inventory_embeds(self.manager, self.guild, FakeUser())  # type: ignore[arg-type]
        self.assertIn("vide", empty[0].description)

        item = self.manager.add_shop_item(
            self.guild.id, default_shop_item() | {"name": "Ticket", "price": 1}
        )
        self.manager.add_coins(self.guild.id, 42, 10)
        self.manager.purchase(self.guild.id, 42, item)
        pages = inventory_embeds(self.manager, self.guild, FakeUser())  # type: ignore[arg-type]
        self.assertIn("Ticket", pages[0].description)

    def test_level_up_embed(self) -> None:
        from bot.services.economy import level_from_total_xp
        from bot.ui.economy import level_up_embed

        info = level_from_total_xp(300)
        emb = level_up_embed(FakeUser(), info.level, info, 50)
        self.assertIn("Niveau", emb.title)
        self.assertIn("50 coins", emb.description)

    def test_safe_emoji(self) -> None:
        from bot.ui.economy import safe_emoji

        self.assertEqual(safe_emoji("💎"), "💎")
        self.assertEqual(safe_emoji("<:custom:12345>"), "12345")
        self.assertIsNone(safe_emoji(""))
        self.assertIsNone(safe_emoji("un emoji trop long"))


class CasinoEmbedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.json")
        self.bot = FakeBot(self.db)
        self.bot.settings = types.SimpleNamespace(brand="Vespara", tagline="chill")
        self.manager = EconomyManager(self.bot)  # type: ignore[arg-type]
        self.bot.economy = self.manager  # type: ignore[attr-defined]
        self.guild = FakeGuild()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    def test_blackjack_embed_states(self) -> None:
        from bot.services.casino import BlackjackSession, Card
        from bot.ui.casino import blackjack_embed

        session = BlackjackSession.start(100)
        session.player = [Card("10", "♠"), Card("9", "♥")]
        session.dealer = [Card("K", "♣"), Card("2", "♦")]
        emb = blackjack_embed(session, member=FakeUser(), balance=900)
        self.assertIn("??", emb.description)
        self.assertIn("Blackjack", emb.title)

        session.stand()
        final = blackjack_embed(session, member=FakeUser(), balance=1000)
        names = [field.name for field in final.fields]
        self.assertIn("Résultat", names)

    def test_slots_embed(self) -> None:
        from bot.ui.casino import slots_embed

        spinning = slots_embed(("🍒", "🍋", "🔔"), 100, spinning=True)
        self.assertIn("tournent", spinning.description)

        result = slots_embed(("💎", "💎", "💎"), 100, payout=1200, label="JACKPOT", balance=2000)
        self.assertIn("JACKPOT", result.description)
        self.assertIn("Gain", result.description)

    def test_roulette_and_dice_embeds(self) -> None:
        from bot.services.casino import roll_dice, spin_roulette
        from bot.ui.casino import dice_embed, roulette_embed

        roulette = spin_roulette(100, "rouge", number=3)
        emb = roulette_embed(roulette, balance=500)
        self.assertIn("Roulette", emb.title)
        self.assertIn("rouge", emb.description)  # numéro 3 = rouge
        self.assertIn("Gagné", emb.description)

        dice = roll_dice(100, "sept", dice=(3, 4))
        d_emb = dice_embed(dice, balance=500)
        self.assertIn("Dés", d_emb.title)
        self.assertIn("7", d_emb.description)

    def test_casino_home_embed(self) -> None:
        from bot.ui.casino import casino_home_embed

        emb = casino_home_embed(self.bot, self.guild, 500)  # type: ignore[arg-type]
        text = " ".join(field.name for field in emb.fields)
        for game in ("Blackjack", "sous", "Roulette", "Dés"):
            self.assertIn(game, text)

    def test_blackjack_view_buttons(self) -> None:
        from bot.services.casino import BlackjackSession
        from bot.ui.casino import BlackjackView

        session = BlackjackSession.start(100)
        view = BlackjackView(self.bot, self.manager, session, FakeUser(), self.guild)  # type: ignore[arg-type]
        labels = [item.label for item in view.children]
        self.assertEqual(labels, ["Tirer", "Rester", "Doubler", "Abandonner"])
        self.assertFalse(any(item.disabled for item in view.children))

        session.stand()
        view._refresh()
        self.assertTrue(all(item.disabled for item in view.children))
