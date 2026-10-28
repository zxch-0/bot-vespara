"""Tests de la boule magique 🎱."""

from __future__ import annotations

import asyncio
import random
import time
import unittest

from bot.constants import (
    COLOR_ERROR,
    COLOR_MUTED,
    COLOR_SUCCESS,
    COLOR_WARNING,
    MAGIC8BALL_ANSWERS,
    MAGIC8BALL_TONES,
)
from bot.services.magic_ball import (
    ANSWER_EMOJIS,
    MagicAnswer,
    answer_choices,
    answer_embed,
    clean_question,
    draw_answer,
    shake_embed,
)
from bot.ui.ball import MagicBallView


class FakeAsset:
    url = "https://cdn.discord.test/avatar.png"


class FakeUser:
    id = 1
    mention = "<@1>"
    display_name = "zxc"
    display_avatar = FakeAsset()


class DrawAnswerTests(unittest.TestCase):
    def test_answer_belongs_to_its_tone(self) -> None:
        rng = random.Random(1234)
        for _ in range(500):
            answer = draw_answer(rng)
            self.assertIn(answer.tone, MAGIC8BALL_ANSWERS)
            self.assertIn(answer.text, MAGIC8BALL_ANSWERS[answer.tone])
            self.assertEqual(answer.label, MAGIC8BALL_TONES[answer.tone])

    def test_colors_follow_tone(self) -> None:
        expected = {"oui": COLOR_SUCCESS, "peut_etre": COLOR_WARNING, "non": COLOR_ERROR}
        rng = random.Random(99)
        for _ in range(300):
            answer = draw_answer(rng)
            self.assertEqual(answer.color, expected[answer.tone])
            self.assertEqual(answer.emoji, ANSWER_EMOJIS[answer.tone])

    def test_all_tones_are_reachable(self) -> None:
        rng = random.Random(7)
        tones = {draw_answer(rng).tone for _ in range(300)}
        self.assertEqual(tones, {"oui", "peut_etre", "non"})

    def test_answer_pool(self) -> None:
        answers = answer_choices()
        self.assertEqual(len(answers), sum(len(values) for values in MAGIC8BALL_ANSWERS.values()))
        self.assertEqual(len(answers), len(set(answers)), "les réponses doivent être uniques")
        self.assertGreaterEqual(len(answers), 21)
        for tone in ("oui", "peut_etre", "non"):
            self.assertGreaterEqual(len(MAGIC8BALL_ANSWERS[tone]), 7)


class QuestionTests(unittest.TestCase):
    def test_clean_question_collapses_spaces(self) -> None:
        self.assertEqual(clean_question("  Est-ce   que\nça marche ? "), "Est-ce que ça marche ?")

    def test_clean_question_truncates(self) -> None:
        cleaned = clean_question("a" * 1000)
        self.assertLessEqual(len(cleaned), 400)
        self.assertTrue(cleaned.endswith("…"))


class EmbedTests(unittest.TestCase):
    def test_answer_embed(self) -> None:
        answer = MagicAnswer(tone="oui", text="Absolument !", color=COLOR_SUCCESS, label="positive")
        emb = answer_embed("On part en soirée ?", answer, author=FakeUser())  # type: ignore[arg-type]

        self.assertIn("Boule magique", emb.title)
        self.assertIn("Absolument !", emb.description)
        self.assertIn("<@1>", emb.description)
        self.assertIn("On part en soirée ?", emb.description)
        self.assertEqual(emb.colour.value, COLOR_SUCCESS)
        self.assertIn("positive", emb.footer.text)
        self.assertEqual(emb.author.name, "zxc")
        self.assertEqual(emb.author.icon_url, FakeAsset.url)

    def test_shake_embed(self) -> None:
        emb = shake_embed("On part en soirée ?")
        self.assertIn("se secoue", emb.description)
        self.assertIn("On part en soirée ?", emb.description)
        self.assertEqual(emb.colour.value, COLOR_MUTED)


class MagicBallViewTests(unittest.TestCase):
    def test_single_shake_button(self) -> None:
        view = MagicBallView(question="Test ?", author_id=1)
        self.assertEqual(len(view.children), 1)
        self.assertEqual(view.children[0].label, "Secouer à nouveau")
        self.assertFalse(view.children[0].disabled)

    def test_author_is_allowed(self) -> None:
        view = MagicBallView(question="Test ?", author_id=1)

        class Interaction:
            user = type("U", (), {"id": 1})()

        self.assertTrue(asyncio.run(view.interaction_check(Interaction())))  # type: ignore[arg-type]

    def test_other_user_is_refused(self) -> None:
        view = MagicBallView(question="Test ?", author_id=1)

        class Response:
            def __init__(self) -> None:
                self.called = False

            def is_done(self) -> bool:
                return False

            async def send_message(self, **kwargs) -> None:
                self.called = True

        class Interaction:
            user = type("U", (), {"id": 2})()
            response = Response()

        interaction = Interaction()
        self.assertFalse(asyncio.run(view.interaction_check(interaction)))  # type: ignore[arg-type]
        self.assertTrue(interaction.response.called)


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------- #
# Flux complet de la commande (sans Discord)
# --------------------------------------------------------------------------- #
class FakeFollowup:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, **kwargs) -> None:
        self.sent.append(kwargs)


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = False
        self.thinking = False
        self.edited: list[dict] = []
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def defer(self, *, thinking: bool = False) -> None:
        self.deferred = True
        self.thinking = thinking
        self._done = True


class FakeInteraction:
    def __init__(self, user: FakeUser | None = None) -> None:
        self.user = user or FakeUser()
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.edits: list[dict] = []

    async def edit_original_response(self, **kwargs) -> None:
        self.edits.append(kwargs)


class BouleCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        import tempfile
        from pathlib import Path

        from bot.cogs.fun import Fun
        from bot.database import Database

        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "db.json")
        self.bot = type("Bot", (), {"db": self.db, "settings": type("S", (), {"brand": "Vespara"})()})()
        self.cog = Fun(self.bot)  # type: ignore[arg-type]

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def test_ask_shows_shake_then_answer(self) -> None:
        from unittest.mock import patch

        interaction = FakeInteraction()
        with patch("bot.cogs.fun.SHAKE_DELAY", 0):
            await self.cog._ask(interaction, "Est-ce que je vais gagner ?")  # type: ignore[arg-type]

        self.assertTrue(interaction.response.deferred)
        self.assertTrue(interaction.response.thinking)

        # 1er edit : la boule se secoue · 2e edit : la réponse
        self.assertEqual(len(interaction.edits), 2)
        self.assertIn("se secoue", interaction.edits[0]["embed"].description)
        answer = interaction.edits[1]["embed"]
        self.assertIn("Question de <@1>", answer.description)
        self.assertIn("Est-ce que je vais gagner ?", answer.description)
        self.assertIn("view", interaction.edits[1])
        self.assertEqual(interaction.followup.sent, [])

    async def test_ask_falls_back_to_followup(self) -> None:
        from unittest.mock import patch

        import discord

        class BrokenInteraction(FakeInteraction):
            async def edit_original_response(self, **kwargs) -> None:
                self.edits.append(kwargs)
                if len(self.edits) > 1:
                    from unittest.mock import Mock

                    raise discord.HTTPException(Mock(status=500, reason="Boom"), "échec simulé")

        interaction = BrokenInteraction()
        with patch("bot.cogs.fun.SHAKE_DELAY", 0):
            await self.cog._ask(interaction, "Ça va marcher ?")  # type: ignore[arg-type]

        self.assertEqual(len(interaction.followup.sent), 1)
        self.assertIn("Ça va marcher ?", interaction.followup.sent[0]["embed"].description)


class ShakeButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_shake_again_updates_message(self) -> None:
        from unittest.mock import patch

        from bot.ui.ball import MagicBallView

        view = MagicBallView(question="On y va ?", author_id=1)

        class Response:
            def __init__(self) -> None:
                self.edited: dict | None = None

            async def edit_message(self, **kwargs) -> None:
                self.edited = kwargs

        class Interaction:
            user = FakeUser()
            response = Response()

            def __init__(self) -> None:
                self.edits: list[dict] = []

            async def edit_original_response(self, **kwargs) -> None:
                self.edits.append(kwargs)

        interaction = Interaction()
        with patch("bot.ui.ball.SHAKE_DELAY", 0):
            await view._shake_again(interaction)  # type: ignore[arg-type]

        self.assertIn("se secoue", interaction.response.edited["embed"].description)
        self.assertEqual(len(interaction.edits), 1)
        self.assertIn("On y va ?", interaction.edits[0]["embed"].description)

    async def test_shake_button_rate_limited(self) -> None:
        from bot.ui.ball import MagicBallView

        view = MagicBallView(question="On y va ?", author_id=1)
        view._last_press = time.monotonic()

        class Response:
            def __init__(self) -> None:
                self.edited = None
                self.messages: list[dict] = []

            def is_done(self) -> bool:
                return False

            async def edit_message(self, **kwargs) -> None:
                self.edited = kwargs

            async def send_message(self, **kwargs) -> None:
                self.messages.append(kwargs)

        class Interaction:
            user = FakeUser()
            response = Response()

        interaction = Interaction()
        await view._shake_again(interaction)  # type: ignore[arg-type]

        # Le message n'est pas modifié : un simple avertissement éphémère est envoyé
        self.assertIsNone(interaction.response.edited)
        self.assertEqual(len(interaction.response.messages), 1)
        self.assertTrue(interaction.response.messages[0]["ephemeral"])
        self.assertIn("Doucement", interaction.response.messages[0]["embed"].description)
