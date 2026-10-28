"""Utilitaires partagés : durées, embeds, formatage, réponses sûres."""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any, Sequence

import discord

from .constants import (
    COLOR,
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_MUTED,
    COLOR_SUCCESS,
    COLOR_WARNING,
    EMOJI,
    FOOTER,
    LOADING_FRAMES,
    PROGRESS_EMPTY,
    PROGRESS_FULL,
    PROGRESS_HEAD,
    THEME_GRADIENTS,
)

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Durées
# --------------------------------------------------------------------------- #
_UNITS: dict[str, int] = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "seconde": 1,
    "secondes": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "heure": 3600,
    "heures": 3600,
    "j": 86400,
    "jour": 86400,
    "jours": 86400,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "sem": 604800,
    "semaine": 604800,
    "semaines": 604800,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
}

_DURATION_TOKEN = re.compile(r"(\d+)([a-zà-ÿ]+)?")


def parse_duration(raw: str) -> int:
    """Convertit `1h30`, `2 jours`, `45m`, `90` (minutes) en secondes.

    :raises ValueError: si le format n'est pas reconnu.
    """
    if not isinstance(raw, str):
        raise ValueError("Durée invalide.")
    text = raw.strip().lower().replace(" ", "").replace(",", "").replace("et", "")
    if not text:
        raise ValueError("Durée vide.")

    # Nombre seul -> minutes
    if text.isdigit():
        return int(text) * 60

    total = 0
    index = 0
    while index < len(text):
        match = _DURATION_TOKEN.match(text, index)
        if match is None:
            raise ValueError(f"Format de durée invalide près de « {text[index:]} ».")

        value = int(match.group(1))
        unit = match.group(2)
        if unit is None:
            # « 1h30 » : le dernier nombre sans unité est compté en minutes.
            if match.end() != len(text):
                raise ValueError("Précise l'unité (s, m, h, j, sem).")
            total += value * 60
        else:
            seconds = _UNITS.get(unit)
            if seconds is None:
                raise ValueError(f"Unité inconnue : « {unit} » (utilise s, m, h, j ou sem).")
            total += value * seconds
        index = match.end()

    if total <= 0:
        raise ValueError("La durée doit être supérieure à zéro.")
    return total


def humanize_duration(seconds: float) -> str:
    """Formate une durée en français : `2 j 3 h`, `45 min`, `12 s`."""
    seconds = int(max(0, seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days} j")
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if not parts and secs:
        parts.append(f"{secs} s")
    return " ".join(parts) or "0 s"


def progress_bar(ratio: float, length: int = 14) -> str:
    """Barre de progression unicode (0.0 -> vide, 1.0 -> pleine)."""
    ratio = min(1.0, max(0.0, float(ratio)))
    filled = round(ratio * length)
    return "▰" * filled + "▱" * (length - filled)


def animated_progress(ratio: float, length: int = 14) -> str:
    """Barre de progression avec une tête lumineuse : plus jolie à lire."""
    ratio = min(1.0, max(0.0, float(ratio)))
    length = max(4, int(length))
    filled = round(ratio * (length - 1))
    if ratio >= 1.0:
        return PROGRESS_FULL * length
    ease = "▰" * filled
    head = PROGRESS_HEAD if filled < length - 1 else PROGRESS_FULL
    rest = PROGRESS_EMPTY * (length - 1 - filled)
    return ease + head + rest


def percent_bar(ratio: float, length: int = 12) -> str:
    """« ▰▰▰▱▱ 42 % » — prêt à coller dans un embed."""
    return f"{animated_progress(ratio, length)} `{round(max(0.0, min(1.0, ratio)) * 100):>3.0f} %`"


def spinner(step: int) -> str:
    """Petite animation d'attente (appelée à chaque frame)."""
    return LOADING_FRAMES[step % len(LOADING_FRAMES)]


def typing_dots(step: int, maximum: int = 3) -> str:
    """Suffixe animé « . », « .. », « ... »."""
    return "." * ((step % maximum) + 1)


def gradient_color(accent: str | None = None, position: float = 0.0) -> int:
    """Couleur d'un dégradé de thème (0.0 → début, 1.0 → fin)."""
    colors = THEME_GRADIENTS.get((accent or "").lower()) or [COLOR]
    if len(colors) == 1:
        return colors[0]
    position = min(1.0, max(0.0, float(position)))
    index = round(position * (len(colors) - 1))
    return colors[index]


def accent_color(accent: str | None) -> int:
    """Couleur principale d'un thème (ou couleur par défaut)."""
    return gradient_color(accent, 0.0)


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #
def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def timestamp(ts: float | dt.datetime | None) -> str:
    """Timestamp Discord (`<t:...:R>`) à partir d'un epoch ou d'un datetime."""
    if ts is None:
        return "—"
    if isinstance(ts, dt.datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        ts = ts.timestamp()
    return discord.utils.format_dt(dt.datetime.fromtimestamp(float(ts), dt.timezone.utc), "R")


def full_timestamp(ts: float | dt.datetime | None) -> str:
    if ts is None:
        return "—"
    if isinstance(ts, dt.datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        ts = ts.timestamp()
    return discord.utils.format_dt(dt.datetime.fromtimestamp(float(ts), dt.timezone.utc), "f")


def short_date(ts: float | dt.datetime | None) -> str:
    if ts is None:
        return "—"
    if isinstance(ts, dt.datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        ts = ts.timestamp()
    return dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).strftime("%d/%m/%Y à %H:%M")


# --------------------------------------------------------------------------- #
# Embeds
# --------------------------------------------------------------------------- #
def embed(
    *,
    title: str | None = None,
    description: str | None = None,
    color: int = COLOR,
    footer: str | None = FOOTER,
    thumbnail: str | None = None,
    image: str | None = None,
    timestamp_now: bool = True,
    accent: str | None = None,
    icon: str | None = None,
    icon_url: str | None = None,
) -> discord.Embed:
    """Crée un embed aux couleurs de Vespara.

    `accent` choisit un dégradé de thème (`violet`, `menthe`, `or`, `feu`,
    `ocean`, `rose`, `nuit`…) et remplace la couleur par défaut. `icon` ajoute
    un petit emoji devant le pied de page.
    """
    if accent:
        color = accent_color(accent)
    emb = discord.Embed(title=title, description=description, color=color)
    if footer:
        text = f"{icon} {footer}" if icon else footer
        if icon_url:
            emb.set_footer(text=text, icon_url=icon_url)
        else:
            emb.set_footer(text=text)
    if thumbnail:
        emb.set_thumbnail(url=thumbnail)
    if image:
        emb.set_image(url=image)
    if timestamp_now:
        emb.timestamp = utcnow()
    return emb


def success(message: str, *, title: str | None = None) -> discord.Embed:
    heading = title or "C'est fait !"
    return embed(
        title=f"{EMOJI['success']} {heading}",
        description=message,
        color=COLOR_SUCCESS,
        icon=EMOJI["sparkles"],
    )


def error(message: str, *, title: str | None = None) -> discord.Embed:
    return embed(
        title=f"{EMOJI['error']} {title or 'Oups'} ",
        description=message,
        color=COLOR_ERROR,
    )


def muted(message: str, *, title: str | None = None) -> discord.Embed:
    """Embed discret (états neutres, historique vide…)."""
    return embed(title=title, description=message, color=COLOR_MUTED)


def warning(message: str, *, title: str | None = None) -> discord.Embed:
    return embed(title=f"{EMOJI['warning']} {title or 'Attention'}", description=message, color=COLOR_WARNING)


def info(message: str, *, title: str | None = None) -> discord.Embed:
    return embed(title=f"{EMOJI['info']} {title or 'Information'}", description=message, color=COLOR_INFO)


# --------------------------------------------------------------------------- #
# Réponses / divers
# --------------------------------------------------------------------------- #
def truncate(text: str, length: int = 1024) -> str:
    if len(text) <= length:
        return text
    return text[: max(0, length - 1)] + "…"


def mention_list(user_ids: Sequence[int], limit: int = 40) -> str:
    if not user_ids:
        return "—"
    shown = [f"<@{uid}>" for uid in user_ids[:limit]]
    extra = len(user_ids) - len(shown)
    text = ", ".join(shown)
    if extra > 0:
        text += f" … et {extra} autre{'s' if extra > 1 else ''}"
    return text


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    return singular if count <= 1 else (plural_form or f"{singular}s")


async def reply_ephemeral(interaction: discord.Interaction, emb: discord.Embed, **kwargs: Any) -> None:
    """Répond en éphémère, que l'interaction ait été différée ou non."""
    if interaction.response.is_done():
        await interaction.followup.send(embed=emb, ephemeral=True, **kwargs)
    else:
        await interaction.response.send_message(embed=emb, ephemeral=True, **kwargs)


async def reply_error(interaction: discord.Interaction, message: str, *, title: str | None = None) -> None:
    await reply_ephemeral(interaction, error(message, title=title))


