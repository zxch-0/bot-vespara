"""Boule magique 🎱 : tirage des réponses et construction des embeds."""

from __future__ import annotations

import random
from dataclasses import dataclass

import discord

from ..constants import (
    COLOR_MUTED,
    EMOJI,
    FOOTER,
    MAGIC8BALL_ANSWERS,
    MAGIC8BALL_COLORS,
    MAGIC8BALL_EMOJI,
    MAGIC8BALL_EMOJIS,
    MAGIC8BALL_TONES,
)
from ..helpers import embed, truncate

ANSWER_EMOJIS = MAGIC8BALL_EMOJIS
MAX_QUESTION_LENGTH = 400


@dataclass(frozen=True, slots=True)
class MagicAnswer:
    """Une réponse de la boule, avec sa tonalité."""

    tone: str
    text: str
    color: int
    label: str

    @property
    def emoji(self) -> str:
        return MAGIC8BALL_EMOJIS.get(self.tone, MAGIC8BALL_EMOJI)


def draw_answer(rng: random.Random | None = None) -> MagicAnswer:
    """Tire une réponse aléatoire, équitablement entre les trois tonalités."""
    picker = rng or random
    tone = picker.choice(tuple(MAGIC8BALL_ANSWERS))
    text = picker.choice(MAGIC8BALL_ANSWERS[tone])
    return MagicAnswer(
        tone=tone,
        text=text,
        color=MAGIC8BALL_COLORS.get(tone, COLOR_MUTED),
        label=MAGIC8BALL_TONES.get(tone, tone),
    )


def clean_question(question: str) -> str:
    """Nettoie la question saisie par l'utilisateur."""
    cleaned = " ".join(str(question).split())
    return truncate(cleaned, MAX_QUESTION_LENGTH)


def shake_embed(question: str) -> discord.Embed:
    """Embed affiché pendant que la boule se secoue."""
    return embed(
        title=f"{MAGIC8BALL_EMOJI} Boule magique",
        description=f"## 🔮 La boule se secoue…\n\n> {clean_question(question)}",
        color=COLOR_MUTED,
        footer=FOOTER,
    )


def answer_embed(question: str, answer: MagicAnswer, *, author: discord.abc.User) -> discord.Embed:
    """Embed final avec la réponse de la boule."""
    emb = embed(
        title=f"{MAGIC8BALL_EMOJI} Boule magique",
        description=(
            f"## {answer.emoji} {answer.text}\n\n"
            f"{EMOJI['reply']} **Question de {author.mention}**\n"
            f"> {clean_question(question)}"
        ),
        color=answer.color,
        footer=f"{FOOTER} • Réponse {answer.label}",
    )
    emb.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    return emb


def answer_choices() -> list[str]:
    """Toutes les réponses possibles, pratique pour les tests et la doc."""
    return [text for answers in MAGIC8BALL_ANSWERS.values() for text in answers]


__all__ = [
    "ANSWER_EMOJIS",
    "MAX_QUESTION_LENGTH",
    "MagicAnswer",
    "answer_choices",
    "answer_embed",
    "clean_question",
    "draw_answer",
    "shake_embed",
]
