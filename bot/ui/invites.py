"""Rendus et helpers des invitations : lien du serveur, stats et classement."""

from __future__ import annotations

import datetime as dt
from typing import Any

import discord

from ..constants import EMOJI
from ..helpers import animated_progress, embed, gradient_color, muted, timestamp, truncate

MEDALS = ("🥇", "🥈", "🥉")


# --------------------------------------------------------------------------- #
# Helpers (logique pure, testable sans Discord)
# --------------------------------------------------------------------------- #
def usable(invite: Any, *, now: dt.datetime | None = None) -> bool:
    """Une invitation est utilisable si elle n'est ni expirée ni épuisée."""
    expires_at = getattr(invite, "expires_at", None)
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=dt.timezone.utc)
        current = now or dt.datetime.now(dt.timezone.utc)
        if current >= expires_at:
            return False
    max_uses = getattr(invite, "max_uses", 0) or 0
    if max_uses and getattr(invite, "uses", 0) >= max_uses:
        return False
    return True


def pick_invite(invites: list[Any], *, now: dt.datetime | None = None) -> Any | None:
    """Choisit la meilleure invitation active à partager.

    Priorité aux invitations **sans expiration et sans limite d'utilisation**,
    puis au plus grand nombre d'utilisations restantes, puis à l'expiration la
    plus lointaine.
    """
    candidates = [invite for invite in invites if usable(invite, now=now)]
    if not candidates:
        return None

    def score(invite: Any) -> tuple[int, int, float]:
        expires_at = invite.expires_at
        permanent = 1 if (not invite.max_uses and expires_at is None) else 0
        remaining = (invite.max_uses - invite.uses) if invite.max_uses else 10_000
        expires = expires_at.timestamp() if expires_at is not None else float("inf")
        return permanent, remaining, expires

    return sorted(candidates, key=score, reverse=True)[0]


def count_by_inviter(invites: list[Any]) -> dict[int, int]:
    """Nombre d'invitations par membre (bots et invitations sans créateur ignorés)."""
    counts: dict[int, int] = {}
    for invite in invites:
        inviter = getattr(invite, "inviter", None)
        if inviter is None or getattr(inviter, "bot", False):
            continue
        counts[inviter.id] = counts.get(inviter.id, 0) + 1
    return counts


def ranked(guild: discord.Guild, counts: dict[int, int]) -> list[tuple[discord.Member, int]]:
    """Membres présents sur le serveur, triés par invitations décroissantes.

    Égalité départagée par le nom (ordre alphabétique).
    """
    entries: list[tuple[discord.Member, int]] = []
    for user_id, count in counts.items():
        member = guild.get_member(user_id)
        if member is not None:
            entries.append((member, count))
    entries.sort(key=lambda item: (-item[1], str(item[0].display_name).casefold()))
    return entries


# --------------------------------------------------------------------------- #
# Embeds
# --------------------------------------------------------------------------- #
def invite_link_embed(guild: discord.Guild, invite: Any) -> discord.Embed:
    """Embed du lien d'invitation (copiable, avec détails d'expiration)."""
    inviter = getattr(invite, "inviter", None)
    creator = getattr(inviter, "display_name", None) or getattr(inviter, "name", None) or "Inconnue"
    max_uses = getattr(invite, "max_uses", 0) or 0
    uses = f"{invite.uses} / {max_uses}" if max_uses else f"{invite.uses} (illimitée)"

    emb = embed(
        title=f"{EMOJI['door']} Lien d'invitation — {guild.name}",
        description=f"[Rejoindre {guild.name}]({invite.url})",
        color=gradient_color("violet", 0.25),
        accent="violet",
        thumbnail=guild.icon.url if guild.icon else None,
        icon=EMOJI["handshake"],
    )
    emb.add_field(name="Lien", value=str(invite.url), inline=False)
    emb.add_field(name="Créée par", value=truncate(str(creator), 100), inline=True)
    emb.add_field(name="Utilisations", value=uses, inline=True)
    expires_at = getattr(invite, "expires_at", None)
    emb.add_field(name="Expire", value=timestamp(expires_at) if expires_at else "Jamais", inline=True)
    emb.set_footer(text=f"Vespara • {guild.name} • /invites classement")
    return emb


def leaderboard_embeds(
    guild: discord.Guild,
    entries: list[tuple[discord.Member, int]],
    *,
    per_page: int = 10,
    total_invites: int = 0,
) -> list[discord.Embed]:
    """Classement paginé des membres qui ont le plus invité (podium 🥇🥈🥉)."""
    if not entries:
        return [
            muted(
                "Aucune invitation active n'a été comptée sur ce serveur…\n"
                "Invitez vos amis, ils apparaîtront ici ! 🤝",
                title=f"{EMOJI['crown']} Classement des invitations — {guild.name}",
            )
        ]

    top = max(count for _, count in entries) or 1
    total_pages = (len(entries) + per_page - 1) // per_page
    pages: list[discord.Embed] = []
    for page_index in range(total_pages):
        chunk = entries[page_index * per_page : (page_index + 1) * per_page]
        lines: list[str] = []
        for offset, (member, count) in enumerate(chunk):
            position = page_index * per_page + offset
            medal = MEDALS[position] if position < len(MEDALS) else f"`#{position + 1}`"
            name = truncate(str(member.display_name), 20)
            bar = animated_progress(count / top, 10)
            lines.append(f"{medal} **{name}** — {bar} **{count}**")

        emb = embed(
            title=f"{EMOJI['crown']} Classement des invitations — {guild.name}",
            description="\n".join(lines),
            color=gradient_color("violet", page_index / max(1, total_pages - 1)),
            accent="violet",
            thumbnail=guild.icon.url if guild.icon else None,
            icon=EMOJI["sparkles"],
        )
        footer = f"Vespara • page {page_index + 1}/{total_pages} • {len(entries)} classé(s)"
        if total_invites:
            footer += f" • {total_invites} invitation(s) active(s)"
        emb.set_footer(text=footer)
        pages.append(emb)
    return pages


def stats_embed(
    guild: discord.Guild,
    member: discord.Member,
    *,
    count: int,
    rank: int | None,
    ranked_count: int,
    invite_url: str | None = None,
) -> discord.Embed:
    """Statistiques d'invitation d'un membre (nombre, rang, son lien actif)."""
    rank_text = f"**#{rank}** / {ranked_count} classé(s)" if rank else "Hors classement"
    link = f"[Copier le lien d'invitation]({invite_url})" if invite_url else "—"

    emb = embed(
        title=f"{EMOJI['handshake']} Invitations — {getattr(member, 'display_name', member)}",
        color=gradient_color("violet", 0.35),
        accent="violet",
        thumbnail=getattr(getattr(member, "display_avatar", None), "url", None),
        icon=EMOJI["handshake"],
    )
    emb.add_field(name="Invitations actives", value=str(count), inline=True)
    emb.add_field(name="Rang", value=rank_text, inline=True)
    emb.add_field(name="Lien actif", value=link, inline=True)
    emb.set_footer(text=f"Vespara • {guild.name} • /invites classement")
    return emb


__all__ = [
    "MEDALS",
    "count_by_inviter",
    "invite_link_embed",
    "leaderboard_embeds",
    "pick_invite",
    "ranked",
    "stats_embed",
    "usable",
]
