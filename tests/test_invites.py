"""Tests unitaires de la logique d'invitations (comptage, sélection, rendus)."""

from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace
from typing import Any

from bot.ui.invites import (
    count_by_inviter,
    invite_link_embed,
    leaderboard_embeds,
    pick_invite,
    ranked,
    stats_embed,
    usable,
)

UTC = dt.timezone.utc


# --------------------------------------------------------------------------- #
# Doubles de test
# --------------------------------------------------------------------------- #
class FakeMember:
    def __init__(self, member_id: int, name: str = "Membre", *, bot: bool = False) -> None:
        self.id = member_id
        self.name = name
        self.display_name = name
        self.bot = bot
        self.display_avatar = SimpleNamespace(url=f"https://cdn.discord.test/{member_id}.png")


class FakeGuild:
    def __init__(self) -> None:
        self.id = 1
        self.name = "Vespara"
        self.icon = None
        self._members: dict[int, FakeMember] = {}

    def add_member(self, member: FakeMember) -> FakeMember:
        self._members[member.id] = member
        return member

    def get_member(self, member_id: int) -> FakeMember | None:
        return self._members.get(int(member_id))


def make_invite(
    inviter: FakeMember | None,
    *,
    url: str = "https://discord.gg/abc",
    max_uses: int = 0,
    uses: int = 0,
    expires_at: dt.datetime | None = None,
) -> Any:
    return SimpleNamespace(
        inviter=inviter,
        url=url,
        max_uses=max_uses,
        uses=uses,
        expires_at=expires_at,
    )


# --------------------------------------------------------------------------- #
# Comptage / tri
# --------------------------------------------------------------------------- #
class CountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lea = FakeMember(1, "Léa")
        self.max = FakeMember(2, "Max")
        self.bot_user = FakeMember(9, "Bot", bot=True)

    def test_counts_per_member(self) -> None:
        invites = [
            make_invite(self.lea, url="https://discord.gg/a"),
            make_invite(self.lea, url="https://discord.gg/b"),
            make_invite(self.max, url="https://discord.gg/c"),
        ]
        self.assertEqual(count_by_inviter(invites), {1: 2, 2: 1})

    def test_bots_and_unknown_inviters_ignored(self) -> None:
        invites = [
            make_invite(self.bot_user),
            make_invite(None),
            make_invite(self.lea),
        ]
        self.assertEqual(count_by_inviter(invites), {1: 1})

    def test_empty(self) -> None:
        self.assertEqual(count_by_inviter([]), {})


class UsableTests(unittest.TestCase):
    def test_permanent_invite_is_usable(self) -> None:
        self.assertTrue(usable(make_invite(FakeMember(1))))

    def test_expired_invite_is_not_usable(self) -> None:
        expired = make_invite(FakeMember(1), expires_at=dt.datetime(2020, 1, 1, tzinfo=UTC))
        self.assertFalse(usable(expired))

    def test_future_expiry_is_usable(self) -> None:
        future = make_invite(FakeMember(1), expires_at=dt.datetime(2999, 1, 1, tzinfo=UTC))
        self.assertTrue(usable(future))

    def test_exhausted_invite_is_not_usable(self) -> None:
        exhausted = make_invite(FakeMember(1), max_uses=5, uses=5)
        self.assertFalse(usable(exhausted))
        partial = make_invite(FakeMember(1), max_uses=5, uses=4)
        self.assertTrue(usable(partial))


class PickInviteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lea = FakeMember(1, "Léa")
        self.max = FakeMember(2, "Max")
        self.now = dt.datetime(2026, 1, 1, tzinfo=UTC)

    def test_prefers_permanent_invite(self) -> None:
        limited = make_invite(self.lea, url="https://discord.gg/limited", max_uses=100)
        permanent = make_invite(self.lea, url="https://discord.gg/permanent")
        self.assertIs(pick_invite([limited, permanent], now=self.now), permanent)

    def test_prefers_most_remaining_uses(self) -> None:
        low = make_invite(self.lea, url="https://discord.gg/low", max_uses=5, uses=4)
        high = make_invite(self.lea, url="https://discord.gg/high", max_uses=100, uses=10)
        self.assertIs(pick_invite([low, high], now=self.now), high)

    def test_skips_expired_and_exhausted(self) -> None:
        expired = make_invite(self.lea, url="https://discord.gg/expired", expires_at=self.now)
        exhausted = make_invite(self.max, url="https://discord.gg/full", max_uses=1, uses=1)
        good = make_invite(self.max, url="https://discord.gg/good", max_uses=10, uses=3)
        invites = [expired, exhausted, good]
        self.assertIs(pick_invite(invites, now=self.now), good)

    def test_no_candidate(self) -> None:
        self.assertIsNone(pick_invite([], now=self.now))
        expired = make_invite(self.lea, expires_at=self.now)
        self.assertIsNone(pick_invite([expired], now=self.now))


class RankedTests(unittest.TestCase):
    def test_sorted_by_count_then_name(self) -> None:
        guild = FakeGuild()
        guild.add_member(FakeMember(3, "Zoé"))
        lea = guild.add_member(FakeMember(1, "Léa"))
        guild.add_member(FakeMember(2, "Max"))
        # Zoé B n'a pas d'invitation : absente de `counts` (comptage réel).
        guild.add_member(FakeMember(4, "Zoé B"))

        counts = {3: 5, 1: 5, 2: 2}
        entries = ranked(guild, counts)
        self.assertEqual([member.id for member, _ in entries], [1, 3, 2])
        self.assertEqual(entries[0], (lea, 5))

    def test_members_left_guild_are_skipped(self) -> None:
        guild = FakeGuild()
        guild.add_member(FakeMember(1, "Léa"))
        entries = ranked(guild, {1: 3, 999: 10})
        self.assertEqual(entries, [(guild.get_member(1), 3)])


# --------------------------------------------------------------------------- #
# Rendus
# --------------------------------------------------------------------------- #
class LeaderboardRenderTests(unittest.TestCase):
    def _guild_with(self, count: int) -> tuple[FakeGuild, list[tuple[FakeMember, int]]]:
        guild = FakeGuild()
        entries = [
            (guild.add_member(FakeMember(100 + index, f"Membre {index:02d}")), 20 - index)
            for index in range(count)
        ]
        return guild, entries

    def test_empty(self) -> None:
        guild, _ = self._guild_with(0)
        pages = leaderboard_embeds(guild, [])
        self.assertEqual(len(pages), 1)
        self.assertIn("Aucune invitation", pages[0].description)

    def test_pagination_and_medals(self) -> None:
        guild, entries = self._guild_with(12)
        pages = leaderboard_embeds(guild, entries, per_page=10, total_invites=150)
        self.assertEqual(len(pages), 2)

        first, second = pages
        self.assertIn("🥇", first.description)
        self.assertIn("🥈", first.description)
        self.assertIn("🥉", first.description)
        self.assertIn("Membre 00", first.description)
        self.assertNotIn("Membre 10", first.description)
        self.assertIn("`#11`", second.description)
        self.assertIn("Membre 11", second.description)
        self.assertIn("page 1/2", first.footer.text)
        self.assertIn("12 classé(s)", first.footer.text)
        self.assertIn("150 invitation(s) active(s)", first.footer.text)

    def test_top_member_bar_is_full(self) -> None:
        guild, entries = self._guild_with(3)
        page = leaderboard_embeds(guild, entries)[0]
        first_line = page.description.splitlines()[0]
        self.assertIn("▰▰▰▰▰▰▰▰", first_line)


class StatsEmbedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guild = FakeGuild()
        self.lea = self.guild.add_member(FakeMember(1, "Léa"))

    def test_ranked_member(self) -> None:
        emb = stats_embed(
            self.guild,
            self.lea,
            count=7,
            rank=2,
            ranked_count=10,
            invite_url="https://discord.gg/lea",
        )
        self.assertEqual(emb.fields[0].value, "7")
        self.assertEqual(emb.fields[1].value, "**#2** / 10 classé(s)")
        self.assertIn("https://discord.gg/lea", emb.fields[2].value)
        self.assertEqual(emb.thumbnail.url, "https://cdn.discord.test/1.png")

    def test_member_without_invites(self) -> None:
        emb = stats_embed(self.guild, self.lea, count=0, rank=None, ranked_count=10)
        self.assertEqual(emb.fields[0].value, "0")
        self.assertIn("Hors classement", emb.fields[1].value)
        self.assertEqual(emb.fields[2].value, "—")


class InviteLinkEmbedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guild = FakeGuild()
        self.lea = FakeMember(1, "Léa")

    def test_permanent_invite(self) -> None:
        invite = make_invite(self.lea, url="https://discord.gg/vespara", uses=12)
        emb = invite_link_embed(self.guild, invite)
        self.assertIn("Vespara", emb.title)
        self.assertIn("https://discord.gg/vespara", emb.description)
        values = {field.name: field.value for field in emb.fields}
        self.assertEqual(values["Lien"], "https://discord.gg/vespara")
        self.assertEqual(values["Créée par"], "Léa")
        self.assertEqual(values["Utilisations"], "12 (illimitée)")
        self.assertEqual(values["Expire"], "Jamais")

    def test_limited_invite_with_expiry(self) -> None:
        expires_at = dt.datetime(2026, 12, 31, 23, 59, tzinfo=UTC)
        invite = make_invite(
            self.lea, url="https://discord.gg/limit", max_uses=25, uses=8, expires_at=expires_at
        )
        emb = invite_link_embed(self.guild, invite)
        values = {field.name: field.value for field in emb.fields}
        self.assertEqual(values["Utilisations"], "8 / 25")
        self.assertIn("<t:", values["Expire"])

    def test_unknown_creator(self) -> None:
        invite = make_invite(None, url="https://discord.gg/ghost")
        emb = invite_link_embed(self.guild, invite)
        values = {field.name: field.value for field in emb.fields}
        self.assertEqual(values["Créée par"], "Inconnue")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
