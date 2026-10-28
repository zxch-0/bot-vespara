"""Économie, niveaux et boutique : la logique pure, testable sans Discord.

Tout est stocké dans la base JSON existante :

* ``users`` → « guild_id:user_id » : coins, xp, inventaire, statistiques ;
* ``guilds`` → boutique (articles), récompenses de niveau, paramètres.

Les fonctions de ce module ne dépendent que de données simples : le cog et
l'interface ne s'occupent que du rendu.
"""

from __future__ import annotations

import logging
import random
import time
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import discord

from ..constants import (
    CURRENCY_EMOJI,
    CURRENCY_NAME,
    DAILY_STREAK_MULTIPLIERS,
    ECONOMY_COINS_PER_LEVEL,
    ECONOMY_DAILY_BASE,
    ECONOMY_DAILY_COOLDOWN,
    ECONOMY_DAILY_STREAK_BONUS,
    ECONOMY_DAILY_STREAK_MAX,
    ECONOMY_MAX_BET,
    ECONOMY_MAX_LEVEL,
    ECONOMY_MIN_BET,
    ECONOMY_START_BALANCE,
    ECONOMY_WORK_COOLDOWN,
    ECONOMY_WORK_MAX,
    ECONOMY_WORK_MIN,
    ECONOMY_XP_BASE,
    ECONOMY_XP_EXPONENT,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Erreurs métier (affichées telles quelles à l'utilisateur)
# --------------------------------------------------------------------------- #
class EconomyError(Exception):
    """Erreur attendue : le message est montré au membre."""


class InsufficientFunds(EconomyError):
    def __init__(self, needed: int, balance: int) -> None:
        super().__init__(
            f"Il te manque **{format_coins(needed - balance)}** : tu as "
            f"{format_coins(balance)}."
        )
        self.needed = needed
        self.balance = balance


class Cooldown(EconomyError):
    def __init__(self, retry_after: float, label: str = "Cette action") -> None:
        super().__init__(
            f"{label} est en recharge : reviens dans "
            f"**{humanize_short(retry_after)}**."
        )
        self.retry_after = retry_after


# --------------------------------------------------------------------------- #
# Formatage
# --------------------------------------------------------------------------- #
def format_coins(amount: float | int) -> str:
    """`12345` -> « 12 345 coins » (espace insécable fine)."""
    value = int(round(float(amount)))
    return f"{value:,}".replace(",", " ") + f" {CURRENCY_NAME}"


def format_coins_short(amount: float | int) -> str:
    """`12345` -> « 🪙 12 345 » (format compact pour les tableaux)."""
    value = int(round(float(amount)))
    return f"{CURRENCY_EMOJI} {value:,}".replace(",", " ")


def humanize_short(seconds: float) -> str:
    """Durée courte : `3 h 12 min`, `8 min`, `42 s`."""
    seconds = int(max(1, seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} j {hours} h"
    if hours:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    if minutes:
        return f"{minutes} min {secs} s" if secs else f"{minutes} min"
    return f"{secs} s"


# --------------------------------------------------------------------------- #
# Niveaux / XP (mathématiques pures)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1024)
def xp_for_level(level: int) -> int:
    """XP nécessaire pour passer du niveau `level` au suivant (mis en cache)."""
    level = max(1, int(level))
    return int(ECONOMY_XP_BASE * (level ** ECONOMY_XP_EXPONENT))


@lru_cache(maxsize=1)
def cumulative_xp() -> tuple[int, ...]:
    """Table des seuils cumulés : `cumulative_xp()[n]` = XP pour atteindre le niveau n+2.

    Précalculée une fois : la conversion XP → niveau est ensuite logarithmique
    (bisect) au lieu de boucler à chaque message.
    """
    thresholds: list[int] = [0]
    total = 0
    for level in range(1, ECONOMY_MAX_LEVEL + 1):
        total += xp_for_level(level)
        thresholds.append(total)
    return tuple(thresholds)


@dataclass(frozen=True, slots=True)
class LevelInfo:
    level: int
    xp: int  # XP dans le niveau courant
    needed: int  # XP requis pour le niveau suivant
    total: int  # XP cumulée
    ratio: float

    @property
    def label(self) -> str:
        return f"Niveau {self.level}"


def level_from_total_xp(total_xp: int) -> LevelInfo:
    """Convertit une XP cumulée en niveau + progression (recherche dichotomique)."""
    total_xp = max(0, int(total_xp))
    thresholds = cumulative_xp()
    level = bisect_right(thresholds, total_xp)  # nombre de paliers franchis
    level = max(1, min(level, ECONOMY_MAX_LEVEL))
    base = thresholds[level - 1]
    needed = xp_for_level(level)
    remaining = max(0, total_xp - base)
    if needed <= 0:  # pragma: no cover - garde-fou
        return LevelInfo(level, 0, 1, total_xp, 1.0)
    ratio = 1.0 if level >= ECONOMY_MAX_LEVEL else min(1.0, remaining / needed)
    return LevelInfo(level, remaining, needed, total_xp, ratio)


def total_xp_for_level(level: int) -> int:
    """XP cumulée nécessaire pour atteindre `level`."""
    level = max(1, min(int(level), ECONOMY_MAX_LEVEL))
    return cumulative_xp()[level - 1]


def level_up_rewards(level: int) -> int:
    """Coins offerts lors d'un passage de niveau."""
    return ECONOMY_COINS_PER_LEVEL * max(1, int(level))


# --------------------------------------------------------------------------- #
# Modèles
# --------------------------------------------------------------------------- #
def default_user() -> dict[str, Any]:
    return {
        "coins": ECONOMY_START_BALANCE,
        "xp": 0,
        "level": 1,
        "messages": 0,
        "daily_at": 0.0,
        "daily_streak": 0,
        "work_at": 0.0,
        "gambled": 0,
        "won": 0,
        "lost": 0,
        "games": 0,
        "best_win": 0,
        "inventory": {},
        "created_at": None,
    }


def default_shop_item() -> dict[str, Any]:
    return {
        "id": "",
        "name": "Article",
        "description": "",
        "kind": "custom",  # role | coins | ticket | custom
        "price": 1000,
        "emoji": "🎁",
        "role_id": None,
        "amount": 0,  # pour kind == coins
        "stock": None,  # None = illimité
        "max_per_user": None,
        "requires_level": None,
        "enabled": True,
        "created_at": None,
    }


SHOP_KINDS: dict[str, str] = {
    "role": "Rôle Discord",
    "coins": "Coins",
    "ticket": "Ticket (lot à réclamer)",
    "custom": "Récompense libre",
}


# --------------------------------------------------------------------------- #
# Gestionnaire
# --------------------------------------------------------------------------- #
class EconomyManager:
    """Accès haut niveau aux comptes, à la boutique et aux niveaux."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self.db = bot.db
        self._xp_cooldowns: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # Comptes
    # ------------------------------------------------------------------ #
    @staticmethod
    def _key(guild_id: int, user_id: int) -> str:
        return f"{int(guild_id)}:{int(user_id)}"

    def users(self) -> dict[str, dict[str, Any]]:
        return self.db.data.setdefault("users", {})

    def account(self, guild_id: int, user_id: int, *, user_name: str | None = None) -> dict[str, Any]:
        """Renvoie (en la créant) la fiche économique d'un membre."""
        key = self._key(guild_id, user_id)
        record = self.users().setdefault(key, default_user())
        for field_name, value in default_user().items():
            record.setdefault(field_name, value)
        if user_name:
            record["name"] = user_name
        if record.get("created_at") is None:
            record["created_at"] = time.time()
        return record

    def balance(self, guild_id: int, user_id: int) -> int:
        return int(self.account(guild_id, user_id).get("coins") or 0)

    def add_coins(
        self,
        guild_id: int,
        user_id: int,
        amount: int,
        *,
        reason: str = "economy",
        save: bool = True,
    ) -> int:
        """Crédite (ou débite si négatif) un compte et renvoie le nouveau solde."""
        record = self.account(guild_id, user_id)
        record["coins"] = max(0, int(record.get("coins") or 0) + int(amount))
        if amount:
            log.debug("Économie : %+d %s (%s) pour %s", amount, reason, user_id, guild_id)
        if save:
            self.db.schedule_save(0.5)
        return int(record["coins"])

    def remove_coins(self, guild_id: int, user_id: int, amount: int, *, reason: str = "economy") -> int:
        record = self.account(guild_id, user_id)
        balance = int(record.get("coins") or 0)
        if amount > balance:
            raise InsufficientFunds(int(amount), balance)
        return self.add_coins(guild_id, user_id, -int(amount), reason=reason)

    def bet(self, guild_id: int, user_id: int, amount: int, *, game: str) -> int:
        """Valide une mise puis la débite (renvoie le nouveau solde)."""
        amount = int(amount)
        if amount < ECONOMY_MIN_BET:
            raise EconomyError(f"La mise minimale est de **{format_coins(ECONOMY_MIN_BET)}**.")
        if amount > ECONOMY_MAX_BET:
            raise EconomyError(f"La mise maximale est de **{format_coins(ECONOMY_MAX_BET)}**.")
        record = self.account(guild_id, user_id)
        record["gambled"] = int(record.get("gambled") or 0) + amount
        return self.remove_coins(guild_id, user_id, amount, reason=f"mise {game}")

    def payout(self, guild_id: int, user_id: int, amount: int, *, bet: int = 0) -> int:
        """Crédite un gain et met à jour les statistiques de jeu."""
        record = self.account(guild_id, user_id)
        amount = max(0, int(amount))
        if amount:
            record["won"] = int(record.get("won") or 0) + amount
            record["best_win"] = max(int(record.get("best_win") or 0), amount)
        net = amount - int(bet)
        if net < 0:
            record["lost"] = int(record.get("lost") or 0) + abs(net)
        record["games"] = int(record.get("games") or 0) + 1
        return self.add_coins(guild_id, user_id, amount, reason="gain casino")

    def count_game(self, guild_id: int, user_id: int) -> None:
        """Comptabilise une partie perdue (aucun gain versé)."""
        record = self.account(guild_id, user_id)
        record["games"] = int(record.get("games") or 0) + 1
        self.db.schedule_save(0.5)

    def transfer(self, guild_id: int, giver_id: int, receiver_id: int, amount: int) -> int:
        """Virement entre deux membres (retourne le solde du donneur)."""
        if giver_id == receiver_id:
            raise EconomyError("Tu ne peux pas te virer des coins à toi-même.")
        if amount <= 0:
            raise EconomyError("Le montant doit être positif.")
        self.remove_coins(guild_id, giver_id, amount, reason="virement")
        self.add_coins(guild_id, receiver_id, amount, reason="virement reçu")
        return self.balance(guild_id, giver_id)

    # ------------------------------------------------------------------ #
    # Journaliers / travail
    # ------------------------------------------------------------------ #
    def claim_daily(self, guild_id: int, user_id: int, now: float | None = None) -> dict[str, Any]:
        """Réclame la récompense journalière (série de jours bonus)."""
        now = time.time() if now is None else now
        record = self.account(guild_id, user_id)
        last = float(record.get("daily_at") or 0)
        elapsed = now - last
        if last and elapsed < ECONOMY_DAILY_COOLDOWN:
            raise Cooldown(ECONOMY_DAILY_COOLDOWN - elapsed, "Le `/eco daily`")

        streak = int(record.get("daily_streak") or 0)
        streak = streak + 1 if last and elapsed < ECONOMY_DAILY_COOLDOWN * 2 else 1
        streak = min(streak, ECONOMY_DAILY_STREAK_MAX)
        multiplier = DAILY_STREAK_MULTIPLIERS[min(streak, len(DAILY_STREAK_MULTIPLIERS)) - 1]
        bonus = ECONOMY_DAILY_STREAK_BONUS * (streak - 1)
        amount = int((ECONOMY_DAILY_BASE + bonus) * multiplier)

        record["daily_at"] = now
        record["daily_streak"] = streak
        balance = self.add_coins(guild_id, user_id, amount, reason="daily")
        return {
            "amount": amount,
            "streak": streak,
            "multiplier": multiplier,
            "balance": balance,
            "next_at": now + ECONOMY_DAILY_COOLDOWN,
        }

    def claim_work(
        self, guild_id: int, user_id: int, rng: random.Random | None = None, now: float | None = None
    ) -> dict[str, Any]:
        """Petit « travail » horaire : gain aléatoire."""
        now = time.time() if now is None else now
        record = self.account(guild_id, user_id)
        last = float(record.get("work_at") or 0)
        if last and now - last < ECONOMY_WORK_COOLDOWN:
            raise Cooldown(ECONOMY_WORK_COOLDOWN - (now - last), "Le `/eco work`")

        rng = rng or random
        amount = rng.randint(ECONOMY_WORK_MIN, ECONOMY_WORK_MAX)
        record["work_at"] = now
        balance = self.add_coins(guild_id, user_id, amount, reason="work")
        return {
            "amount": amount,
            "balance": balance,
            "next_at": now + ECONOMY_WORK_COOLDOWN,
            "job": rng.choice(WORK_JOBS),
        }

    # ------------------------------------------------------------------ #
    # XP & niveaux
    # ------------------------------------------------------------------ #
    def grant_xp(self, guild_id: int, user_id: int, amount: int) -> dict[str, Any]:
        """Ajoute de l'XP et gère les passages de niveau (+ coins bonus)."""
        record = self.account(guild_id, user_id)
        old_level = int(record.get("level") or 1)
        record["xp"] = int(record.get("xp") or 0) + max(0, int(amount))
        info = level_from_total_xp(int(record["xp"]))
        record["level"] = info.level

        rewards: list[int] = []
        if info.level > old_level:
            for level in range(old_level + 1, info.level + 1):
                bonus = level_up_rewards(level)
                self.add_coins(guild_id, user_id, bonus, reason=f"niveau {level}", save=False)
                rewards.append(level)
        self.db.schedule_save(0.5)
        return {
            "level": info.level,
            "previous_level": old_level,
            "leveled_up": info.level > old_level,
            "levels": rewards,
            "info": info,
            "coins_bonus": sum(level_up_rewards(level) for level in rewards),
        }

    def message_xp(self, guild_id: int, user_id: int, *, now: float | None = None) -> int:
        """XP gagnée en discutant (avec un cooldown anti-spam en mémoire)."""
        from ..constants import ECONOMY_XP_COOLDOWN, ECONOMY_XP_MAX, ECONOMY_XP_MIN

        now = time.time() if now is None else now
        key = self._key(guild_id, user_id)
        last = self._xp_cooldowns.get(key, 0.0)
        if now - last < ECONOMY_XP_COOLDOWN:
            return 0
        self._xp_cooldowns[key] = now
        return random.randint(ECONOMY_XP_MIN, ECONOMY_XP_MAX)

    # ------------------------------------------------------------------ #
    # Récompenses de niveau (rôles automatiques)
    # ------------------------------------------------------------------ #
    def level_rewards(self, guild_id: int) -> list[dict[str, Any]]:
        return self.db.guild(guild_id).setdefault("level_rewards", [])

    def reward_for_level(self, guild_id: int, level: int) -> dict[str, Any] | None:
        for reward in self.level_rewards(guild_id):
            if int(reward.get("level") or 0) == int(level):
                return reward
        return None

    async def apply_level_rewards(self, member: discord.Member, levels: list[int]) -> list[discord.Role]:
        """Donne les rôles débloqués par les niveaux atteints."""
        if not levels:
            return []
        guild = member.guild
        given: list[discord.Role] = []
        for level in levels:
            reward = self.reward_for_level(guild.id, level)
            if not reward or not reward.get("role_id"):
                continue
            role = guild.get_role(int(reward["role_id"]))
            if role is None or role in member.roles:
                continue
            try:
                await member.add_roles(role, reason=f"Récompense de niveau {level}")
                given.append(role)
            except discord.HTTPException:
                log.warning("Impossible d'ajouter le rôle %s à %s", role.id, member.id, exc_info=True)
        return given

    # ------------------------------------------------------------------ #
    # Boutique
    # ------------------------------------------------------------------ #
    def shop_items(self, guild_id: int) -> list[dict[str, Any]]:
        return self.db.guild(guild_id).setdefault("shop_items", [])

    def shop_item(self, guild_id: int, item_id: str) -> dict[str, Any] | None:
        for item in self.shop_items(guild_id):
            if str(item.get("id")) == str(item_id):
                return item
        return None

    def find_shop_item(self, guild_id: int, name: str) -> dict[str, Any] | None:
        needle = name.casefold().strip()
        for item in self.shop_items(guild_id):
            if str(item.get("name", "")).casefold().strip() == needle:
                return item
        for item in self.shop_items(guild_id):
            if needle and needle in str(item.get("name", "")).casefold():
                return item
        return None

    def add_shop_item(self, guild_id: int, item: dict[str, Any]) -> dict[str, Any]:
        record = default_shop_item() | item
        record["id"] = str(record.get("id") or self.db.new_token_id())
        record["created_at"] = record.get("created_at") or time.time()
        self.shop_items(guild_id).append(record)
        self.db.schedule_save(0.5)
        return record

    def remove_shop_item(self, guild_id: int, item_id: str) -> bool:
        items = self.shop_items(guild_id)
        for index, item in enumerate(items):
            if str(item.get("id")) == str(item_id):
                items.pop(index)
                self.db.schedule_save(0.5)
                return True
        return False

    def inventory(self, guild_id: int, user_id: int) -> dict[str, int]:
        record = self.account(guild_id, user_id)
        inventory = record.setdefault("inventory", {})
        return inventory

    def purchase(self, guild_id: int, user_id: int, item: dict[str, Any]) -> dict[str, Any]:
        """Achète un article (retourne un récapitulatif de l'achat)."""
        if not item.get("enabled", True):
            raise EconomyError("Cet article n'est plus en vente.")
        record = self.account(guild_id, user_id)
        level = level_from_total_xp(int(record.get("xp") or 0)).level
        required = item.get("requires_level")
        if required and level < int(required):
            raise EconomyError(f"Cet article demande le **niveau {required}** (tu es niveau {level}).")

        inventory = self.inventory(guild_id, user_id)
        owned = int(inventory.get(str(item["id"]), 0))
        limit = item.get("max_per_user")
        if limit is not None and owned >= int(limit):
            raise EconomyError(f"Tu possèdes déjà cet article ({owned}/{limit}).")

        stock = item.get("stock")
        if stock is not None and int(stock) <= 0:
            raise EconomyError("Cet article est en rupture de stock.")

        price = int(item.get("price") or 0)
        self.remove_coins(guild_id, user_id, price, reason=f"achat {item['id']}")

        inventory[str(item["id"])] = owned + 1
        if stock is not None:
            item["stock"] = max(0, int(stock) - 1)
        self.db.schedule_save(0.5)

        return {
            "item": item,
            "price": price,
            "owned": inventory[str(item["id"])],
            "balance": int(record.get("coins") or 0),
        }

    # ------------------------------------------------------------------ #
    # Classements
    # ------------------------------------------------------------------ #
    def leaderboard(self, guild_id: int, *, limit: int = 10, by: str = "coins") -> list[dict[str, Any]]:
        prefix = f"{int(guild_id)}:"
        entries = []
        for key, record in self.users().items():
            if not key.startswith(prefix):
                continue
            value = int(record.get("coins") or 0) if by == "coins" else int(record.get("xp") or 0)
            entries.append(
                {
                    "user_id": int(key.split(":", 1)[1]),
                    "value": value,
                    "name": record.get("name"),
                    "level": level_from_total_xp(int(record.get("xp") or 0)).level,
                }
            )
        entries.sort(key=lambda entry: entry["value"], reverse=True)
        return entries[: max(1, int(limit))]

    def rank_of(self, guild_id: int, user_id: int, *, by: str = "coins") -> tuple[int, int]:
        """Rang du membre et nombre de membres classés (un seul passage)."""
        prefix = f"{int(guild_id)}:"
        key = "coins" if by == "coins" else "xp"
        mine = int((self.users().get(f"{prefix}{int(user_id)}") or {}).get(key) or 0)
        better = 0
        total = 0
        for user_key, record in self.users().items():
            if not user_key.startswith(prefix):
                continue
            total += 1
            if int(record.get(key) or 0) > mine:
                better += 1
        return better + 1, total


# --------------------------------------------------------------------------- #
# Saveurs (travail, blackjack, slots…)
# --------------------------------------------------------------------------- #
WORK_JOBS: tuple[str, ...] = (
    "tu as animé un giveaway surprise",
    "tu as aidé un nouveau membre à trouver les salons",
    "tu as modéré le chat avec brio",
    "tu as streamé une partie endiablée",
    "tu as écrit un guide pour le serveur",
    "tu as organisé une soirée jeux",
    "tu as remonté le moral de tout le monde",
    "tu as réparé le bot (enfin, presque)",
    "tu as chanté au karaoké du serveur",
    "tu as gagné une partie de UNO",
)


def xp_embed_state(record: dict[str, Any]) -> LevelInfo:
    """Progression d'un compte, prête pour l'affichage."""
    return level_from_total_xp(int(record.get("xp") or 0))


__all__ = [
    "Cooldown",
    "EconomyError",
    "EconomyManager",
    "InsufficientFunds",
    "LevelInfo",
    "SHOP_KINDS",
    "WORK_JOBS",
    "default_shop_item",
    "default_user",
    "format_coins",
    "format_coins_short",
    "humanize_short",
    "level_from_total_xp",
    "level_up_rewards",
    "total_xp_for_level",
    "xp_for_level",
    "xp_embed_state",
]
