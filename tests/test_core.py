"""Tests des utilitaires, de la base de données et du serveur de statut."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from bot.cogs.autoresponder import match_response
from bot.config import Settings
from bot.database import Database
from bot.helpers import humanize_duration, parse_duration, progress_bar
from bot.web import INDEX_HTML, StatusServer


class DurationTests(unittest.TestCase):
    def test_minutes_by_default(self) -> None:
        self.assertEqual(parse_duration("30"), 1800)
        self.assertEqual(parse_duration("30m"), 1800)
        self.assertEqual(parse_duration("30 min"), 1800)

    def test_compound_durations(self) -> None:
        self.assertEqual(parse_duration("1h30"), 5400)
        self.assertEqual(parse_duration("1h30m"), 5400)
        self.assertEqual(parse_duration("2 jours"), 172800)
        self.assertEqual(parse_duration("1 sem"), 604800)
        self.assertEqual(parse_duration("1h et 30min"), 5400)
        self.assertEqual(parse_duration("1j2h3m4s"), 86400 + 7200 + 180 + 4)

    def test_invalid_durations(self) -> None:
        for value in ("", "abc", "10x", "-5", "1h abc"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_duration(value)

    def test_humanize(self) -> None:
        self.assertEqual(humanize_duration(45), "45 s")
        self.assertEqual(humanize_duration(90), "1 min")
        self.assertEqual(humanize_duration(3660), "1 h 1 min")
        self.assertEqual(humanize_duration(90061), "1 j 1 h 1 min")

    def test_progress_bar(self) -> None:
        self.assertEqual(progress_bar(0), "▱" * 14)
        self.assertEqual(progress_bar(1), "▰" * 14)
        self.assertEqual(len(progress_bar(0.5, 10)), 10)


class MatchTests(unittest.TestCase):
    def _response(self, **overrides) -> dict:
        base = {
            "id": "1",
            "trigger": "bonjour",
            "reply": "Salut !",
            "mode": "contains",
            "case_sensitive": False,
        }
        base.update(overrides)
        return base

    def test_contains(self) -> None:
        response = self._response()
        self.assertTrue(match_response("Bonjour tout le monde", response))
        self.assertTrue(match_response("BONJOUR", response))
        self.assertFalse(match_response("salut", response))

    def test_startswith(self) -> None:
        response = self._response(trigger="!ip", mode="startswith")
        self.assertTrue(match_response("!ip", response))
        self.assertTrue(match_response("  !ip du serveur", response))
        self.assertFalse(match_response("mon !ip", response))

    def test_endswith(self) -> None:
        response = self._response(trigger="?", mode="endswith")
        self.assertTrue(match_response("une question ?", response))
        self.assertFalse(match_response("? une question", response))

    def test_exact_case_sensitive(self) -> None:
        response = self._response(trigger="Vespara", mode="exact", case_sensitive=True)
        self.assertTrue(match_response("Vespara", response))
        self.assertFalse(match_response("vespara", response))
        self.assertTrue(match_response("  Vespara  ", response))

    def test_regex(self) -> None:
        response = self._response(trigger=r"^!giveaway\s+\d+$", mode="regex")
        self.assertTrue(match_response("!giveaway 12", response))
        self.assertFalse(match_response("giveaway 12", response))

    def test_invalid_regex_is_safe(self) -> None:
        response = self._response(trigger="([", mode="regex")
        self.assertFalse(match_response("test", response))

    def test_empty(self) -> None:
        self.assertFalse(match_response("", self._response()))
        self.assertFalse(match_response("bonjour", self._response(trigger="")))


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "data" / "vespara.json"
        self.db = Database(self.path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_guild_defaults(self) -> None:
        settings = self.db.guild(123)
        self.assertIsNone(settings["staff_role_id"])
        self.assertEqual(settings["autoresponder_cooldown"], 8)
        self.assertIsNotNone(settings["created_at"])

    def test_autoresponses_crud(self) -> None:
        record = self.db.add_autoresponse(
            1, {"id": self.db.next_id(), "trigger": "Bonjour", "reply": "Salut !"}
        )
        self.assertEqual(len(self.db.autoresponses(1)), 1)
        self.assertIsNotNone(self.db.find_autoreply(1, "bonjour"))
        self.assertIs(self.db.autoreply_by_id(1, record["id"]), record)
        self.assertTrue(self.db.remove_autoresponse(1, record["id"]))
        self.assertEqual(self.db.clear_autoresponses(1), 0)

        self.db.add_autoresponse(1, {"id": "42", "trigger": "a", "reply": "b"})
        self.assertEqual(self.db.clear_autoresponses(1), 1)
        self.assertEqual(self.db.autoresponses(1), [])

    def test_giveaway_lifecycle(self) -> None:
        record = self.db.add_giveaway(
            {
                "id": self.db.next_id(),
                "guild_id": 1,
                "prize": "Nitro",
                "started_at": 0,
                "ends_at": 10,
                "created_at": 0,
                "entries": [],
                "ended": False,
            }
        )
        self.assertEqual(len(self.db.active_giveaways()), 1)
        self.assertEqual(self.db.guild_giveaways(1)[0]["prize"], "Nitro")
        self.assertEqual(self.db.stats()["active_giveaways"], 1)

        record["ended"] = True
        record["ended_at"] = 0
        self.assertEqual(self.db.active_giveaways(), [])
        self.assertEqual(self.db.prune_giveaways(older_than=0), 1)

    def test_persistence_roundtrip(self) -> None:
        self.db.guild(7)["staff_role_id"] = 99
        self.db.add_autoresponse(7, {"id": "1", "trigger": "x", "reply": "y"})
        asyncio.run(self.db.save())

        self.assertTrue(self.path.is_file())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["guilds"]["7"]["staff_role_id"], 99)

        reloaded = Database(self.path)
        self.assertEqual(reloaded.guild(7)["staff_role_id"], 99)
        self.assertEqual(len(reloaded.autoresponses(7)), 1)

    def test_corrupted_file_is_recovered(self) -> None:
        asyncio.run(self.db.save())
        self.path.write_text("{ pas du json", encoding="utf-8")
        recovered = Database(self.path)
        self.assertEqual(recovered.data["guilds"], {})


class _FakeTree:
    def get_commands(self) -> list:
        return [1, 2, 3]


class _FakeBot:
    def __init__(self, database: Database) -> None:
        self.settings = Settings(token="x", brand="Vespara", tagline="Le serveur chill")
        self.db = database
        self.tree = _FakeTree()
        self.guilds: list = []
        self.latency = 0.042
        self.user = None

    def is_ready(self) -> bool:
        return True

    @property
    def uptime(self) -> float:
        return 3671.0


class StatusServerTests(unittest.TestCase):
    def test_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "db.json")
            bot = _FakeBot(db)
            payload = StatusServer(bot).status_payload()  # type: ignore[arg-type]

        self.assertEqual(payload["status"], "online")
        self.assertEqual(payload["brand"], "Vespara")
        self.assertEqual(payload["guilds"], 0)
        self.assertEqual(payload["commands"], 3)
        self.assertEqual(payload["latency_ms"], 42)
        self.assertIn("1 h", payload["uptime_human"])

    def test_html_template(self) -> None:
        self.assertIn("__BRAND__", INDEX_HTML)
        self.assertIn("api/status", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
