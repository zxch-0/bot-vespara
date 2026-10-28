"""Rendus et vues de l'économie : profil, classement, boutique, inventaire."""

from __future__ import annotations

import asyncio
import contextlib
import random
from typing import TYPE_CHECKING, Any

import discord

from ..constants import (
    COLOR_ECONOMY,
    COLOR_ERROR,
    COLOR_SUCCESS,
    CURRENCY_EMOJI,
    EMOJI,
    SPARKLES,
)
from ..helpers import (
    animated_progress,
    embed,
    error,
    gradient_color,
    percent_bar,
    success,
    truncate,
)
from ..services.economy import (
    SHOP_KINDS,
    EconomyError,
    EconomyManager,
    LevelInfo,
    format_coins,
    format_coins_short,
    humanize_short,
    level_from_total_xp,
    xp_for_level,
)
from .paginator import Paginator

if TYPE_CHECKING:  # pragma: no cover
    pass


# --------------------------------------------------------------------------- #
# Aides de haut niveau
# --------------------------------------------------------------------------- #
def level_badge(level: int) -> str:
    """Petit badge esthétique selon le palier atteint."""
    for threshold, badge in (
        (100, "🌌"),
        (75, "💠"),
        (50, "🏆"),
        (30, "👑"),
        (20, "💎"),
        (10, "🌟"),
        (5, "⭐"),
    ):
        if level >= threshold:
            return badge
    return "🌱"


def progress_line(info: LevelInfo) -> str:
    """`▰▰▰◆▱▱ 42 % · 120 / 288 XP`."""
    return (
        f"{animated_progress(info.ratio, 16)}\n"
        f"`{info.xp:>5}` / `{info.needed}` XP → **niveau {info.level + 1}**"
    )


# --------------------------------------------------------------------------- #
# Profil
# --------------------------------------------------------------------------- #
def profile_embed(
    manager: EconomyManager,
    guild: discord.Guild,
    member: discord.Member | discord.User,
    *,
    highlight: bool = False,
) -> discord.Embed:
    """Carte de profil économique (coins, niveau, statistiques)."""
    record = manager.account(guild.id, member.id, user_name=str(member))
    info = level_from_total_xp(int(record.get("xp") or 0))
    rank_coins, total_members = manager.rank_of(guild.id, member.id, by="coins")
    inventory = record.get("inventory") or {}
    owned = sum(int(count) for count in inventory.values())

    emb = embed(
        title=f"{level_badge(info.level)} {getattr(member, 'display_name', member)}",
        description=(
            f"{SPARKLES[0]} **Niveau {info.level}** · {format_coins_short(record.get('coins', 0))}\n"
            f"{progress_line(info)}"
        ),
        color=gradient_color("or", min(1.0, info.level / 50)) if not highlight else COLOR_ECONOMY,
        thumbnail=getattr(getattr(member, "display_avatar", None), "url", None),
        icon=EMOJI["sparkles"],
    )
    emb.add_field(name=f"{CURRENCY_EMOJI} Solde", value=format_coins(record.get("coins", 0)), inline=True)
    emb.add_field(
        name=f"{EMOJI['chart']} Classement",
        value=f"**#{rank_coins}** / {total_members} membres",
        inline=True,
    )
    emb.add_field(name=f"{EMOJI['book']} Inventaire", value=f"{owned} article(s)", inline=True)
    emb.add_field(
        name="💬 Messages",
        value=f"{int(record.get('messages') or 0):,}".replace(",", " "),
        inline=True,
    )
    emb.add_field(
        name="🎲 Casino",
        value=(
            f"{int(record.get('games') or 0)} partie(s)\n"
            f"miser {format_coins_short(record.get('gambled', 0))}"
        ),
        inline=True,
    )
    best = int(record.get("best_win") or 0)
    emb.add_field(
        name="🏆 Meilleur gain",
        value=format_coins_short(best) if best else "—",
        inline=True,
    )
    daily_streak = int(record.get("daily_streak") or 0)
    if daily_streak:
        emb.add_field(
            name="🔥 Série journalière",
            value=f"{daily_streak} jour(s) d'affilée",
            inline=True,
        )
    emb.set_footer(
        text=f"Vespara • Économie • {info.total} XP au total",
        icon_url=getattr(getattr(member, "display_avatar", None), "url", None),
    )
    return emb


def level_up_embed(member: Any, level: int, info: LevelInfo, coins: int) -> discord.Embed:
    """Annonce animée d'un passage de niveau."""
    emb = embed(
        title=f"{SPARKLES[0]} Niveau {level} débloqué !",
        description=(
            f"Bravo {getattr(member, 'mention', member)} 🎉\n"
            f"Tu passes au **niveau {level}** {level_badge(level)}\n\n"
            f"{percent_bar(info.ratio, 14)}\n"
            f"🎁 **+{format_coins(coins)}** offerts"
        ),
        color=gradient_color("menthe", 0.2),
        accent="menthe",
        icon="⚡",
    )
    emb.set_thumbnail(url=getattr(getattr(member, "display_avatar", None), "url", None))
    return emb


# --------------------------------------------------------------------------- #
# Classement
# --------------------------------------------------------------------------- #
MEDALS = ("🥇", "🥈", "🥉")


def leaderboard_embeds(
    manager: EconomyManager,
    guild: discord.Guild,
    *,
    by: str = "coins",
    per_page: int = 10,
) -> list[discord.Embed]:
    """Classement paginé (coins ou XP)."""
    entries = manager.leaderboard(guild.id, limit=100, by=by)
    if not entries:
        return [
            embed(
                title=f"{EMOJI['chart']} Classement",
                description="Personne n'a encore de coins… Lance-toi avec `/eco daily` !",
                color=COLOR_ECONOMY,
            )
        ]

    pages: list[discord.Embed] = []
    total_pages = (len(entries) + per_page - 1) // per_page
    for page_index in range(total_pages):
        chunk = entries[page_index * per_page : (page_index + 1) * per_page]
        lines = []
        for offset, entry in enumerate(chunk):
            position = page_index * per_page + offset
            medal = MEDALS[position] if position < len(MEDALS) else f"`#{position + 1}`"
            member = guild.get_member(entry["user_id"])
            name = getattr(member, "display_name", None) or entry.get("name") or f"Membre {entry['user_id']}"
            if by == "coins":
                value = format_coins_short(entry["value"])
            else:
                value = f"{level_badge(entry['level'])} niv. {entry['level']} · {entry['value']:,} XP"
            lines.append(f"{medal} **{truncate(str(name), 24)}** — {value}")

        emb = embed(
            title=f"{'🪙' if by == 'coins' else '📈'} Classement — {'richesse' if by == 'coins' else 'niveaux'}",
            description="\n".join(lines),
            color=gradient_color("or", page_index / max(1, total_pages - 1)),
            accent="or",
            icon=EMOJI["crown"],
        )
        emb.set_footer(
            text=f"Vespara • page {page_index + 1}/{total_pages} • {len(entries)} membres classés"
        )
        pages.append(emb)
    return pages


# --------------------------------------------------------------------------- #
# Boutique
# --------------------------------------------------------------------------- #
def item_line(item: dict[str, Any], *, owned: int = 0, balance: int | None = None) -> str:
    """Une ligne de boutique lisible et colorée."""
    price = int(item.get("price") or 0)
    emoji = item.get("emoji") or "🎁"
    kind = SHOP_KINDS.get(str(item.get("kind")), "Récompense")
    details: list[str] = [f"`{format_coins_short(price)}`"]
    if item.get("kind") == "role" and item.get("role_id"):
        details.append(f"rôle <@&{int(item['role_id'])}>")
    if item.get("kind") == "coins" and item.get("amount"):
        details.append(f"+{format_coins_short(item['amount'])}")
    if item.get("requires_level"):
        details.append(f"🔒 niveau {int(item['requires_level'])}")
    stock = item.get("stock")
    if stock is not None:
        details.append(f"📦 {int(stock)} restant(s)")
    if owned:
        details.append(f"✅ x{owned}")
    if not item.get("enabled", True):
        details.append("🚫 retiré de la vente")
    if balance is not None and price > balance:
        details.append("💤 trop cher")

    return f"{emoji} **{item.get('name')}** · {kind}\n　 {' · '.join(details)}"


def shop_embed(
    manager: EconomyManager,
    guild: discord.Guild,
    user: discord.Member | discord.User,
    *,
    page: int = 0,
    per_page: int = 6,
) -> tuple[discord.Embed, int]:
    """Page de boutique (retourne l'embed et le nombre total de pages)."""
    items = [item for item in manager.shop_items(guild.id) if item.get("enabled", True)]
    balance = manager.balance(guild.id, user.id)
    record = manager.account(guild.id, user.id)
    inventory = record.get("inventory") or {}

    if not items:
        emb = embed(
            title=f"{EMOJI['gift']} Boutique",
            description=(
                "La boutique est encore vide…\nLes administrateurs peuvent ajouter des "
                "articles avec `/eco-admin article ajouter`."
            ),
            color=COLOR_ECONOMY,
            accent="violet",
        )
        return emb, 1

    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = items[page * per_page : (page + 1) * per_page]

    emb = embed(
        title=f"{EMOJI['gift']} Boutique de {guild.name}",
        description=(
            f"{SPARKLES[0]} Ton solde : **{format_coins(balance)}**\n"
            "Choisis un article dans le menu ci-dessous pour l'acheter.\n\u200b"
        ),
        color=gradient_color("rose", page / max(1, total_pages - 1) if total_pages > 1 else 0.2),
        accent="rose",
        thumbnail=guild.icon.url if guild.icon else None,
        icon=EMOJI["gift"],
    )
    for item in chunk:
        emb.add_field(
            name=f"{item.get('emoji') or '🎁'} {item.get('name')}",
            value=truncate(
                (item.get("description") or "*Pas de description*")
                + "\n"
                + item_line(item, owned=int(inventory.get(str(item["id"]), 0)), balance=balance).split("\n")[-1],
                1000,
            ),
            inline=False,
        )
    emb.set_footer(text=f"Vespara • Boutique • page {page + 1}/{total_pages}")
    return emb, total_pages


def safe_emoji(raw: Any) -> str | None:
    """Emoji utilisable dans un `SelectOption` (unicode court ou emoji custom)."""
    value = str(raw or "").strip()
    if not value:
        return None
    if value.startswith("<") and value.endswith(">"):  # <:nom:id>
        value = value.split(":")[-1].rstrip(">")
        return value or None
    return value if len(value) <= 4 else None


class ShopSelect(discord.ui.Select):
    """Menu déroulant des articles de la page courante."""

    def __init__(self, manager: EconomyManager, guild: discord.Guild, items: list[dict[str, Any]], user_id: int):
        options = []
        for item in items[:25]:
            price = int(item.get("price") or 0)
            options.append(
                discord.SelectOption(
                    label=truncate(str(item.get("name")), 100),
                    value=str(item["id"]),
                    description=truncate(f"{format_coins(price)} — {item.get('description') or ''}", 100),
                    emoji=safe_emoji(item.get("emoji")) or "🎁",
                )
            )
        super().__init__(
            placeholder="🛒 Choisir un article…",
            options=options or [discord.SelectOption(label="Vide", value="none")],
            min_values=1,
            max_values=1,
        )
        self.manager = manager
        self.guild = guild
        self.items = items
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=error("Ce menu ne t'appartient pas : relance `/boutique`."), ephemeral=True
            )
            return
        item_id = self.values[0]
        item = self.manager.shop_item(self.guild.id, item_id)
        if item is None:
            await interaction.response.send_message(embed=error("Cet article n'existe plus."), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=purchase_confirm_embed(self.manager, self.guild, interaction.user, item),
            view=PurchaseConfirmView(self.manager, self.guild, item, interaction.user.id),
            ephemeral=True,
        )


class PurchaseConfirmView(discord.ui.View):
    """Confirmation d'achat (éphémère)."""

    def __init__(self, manager: EconomyManager, guild: discord.Guild, item: dict[str, Any], user_id: int):
        super().__init__(timeout=120)
        self.manager = manager
        self.guild = guild
        self.item = item
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=error("Cette confirmation n'est pas la tienne."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Acheter", emoji="🛒", style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            result = self.manager.purchase(self.guild.id, self.user_id, self.item)
        except EconomyError as exc:
            await interaction.response.send_message(embed=error(str(exc)), ephemeral=True)
            return

        reward_text = await deliver_purchase(
            interaction.client, resolve_member(interaction), self.item
        )
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        emb = success(
            f"Tu as acheté **{self.item.get('name')}** pour "
            f"**{format_coins(result['price'])}** !\n"
            f"Solde restant : **{format_coins(result['balance'])}**\n\n{reward_text}",
            title="Achat validé",
        )
        await interaction.response.edit_message(embed=emb, view=self)
        self.stop()


class ShopView(discord.ui.View):
    """Boutique interactive : pagination + sélecteur d'articles."""

    def __init__(self, manager: EconomyManager, guild: discord.Guild, user_id: int, *, page: int = 0):
        super().__init__(timeout=180)
        self.manager = manager
        self.guild = guild
        self.user_id = user_id
        self.page = page
        self.pages = 1
        self._rebuild()

    def _items(self) -> list[dict[str, Any]]:
        return [item for item in self.manager.shop_items(self.guild.id) if item.get("enabled", True)]

    def _rebuild(self) -> None:
        self.clear_items()
        items = self._items()
        self.pages = max(1, (len(items) + 5) // 6)
        self.page = max(0, min(self.page, self.pages - 1))
        chunk = items[self.page * 6 : (self.page + 1) * 6]
        if chunk:
            self.add_item(ShopSelect(self.manager, self.guild, chunk, self.user_id))
        if self.pages > 1:
            previous = discord.ui.Button(
                emoji="◀️", style=discord.ButtonStyle.secondary, disabled=self.page == 0, row=1
            )
            following = discord.ui.Button(
                emoji="▶️",
                style=discord.ButtonStyle.secondary,
                disabled=self.page >= self.pages - 1,
                row=1,
            )
            previous.callback = self._previous  # type: ignore[method-assign]
            following.callback = self._next  # type: ignore[method-assign]
            self.add_item(previous)
            self.add_item(following)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=error("Relance `/boutique` pour ouvrir ton propre menu."), ephemeral=True
            )
            return False
        return True

    def refresh(self) -> None:
        self._rebuild()

    async def _previous(self, interaction: discord.Interaction) -> None:
        self.page -= 1
        self._rebuild()
        await interaction.response.edit_message(
            embed=shop_embed(self.manager, self.guild, interaction.user, page=self.page)[0],
            view=self,
        )

    async def _next(self, interaction: discord.Interaction) -> None:
        self.page += 1
        self._rebuild()
        await interaction.response.edit_message(
            embed=shop_embed(self.manager, self.guild, interaction.user, page=self.page)[0],
            view=self,
        )


def resolve_member(interaction: discord.Interaction) -> Any:
    """Membre complet de l'auteur (utile pour ajouter un rôle)."""
    user = interaction.user
    if isinstance(user, discord.Member):
        return user
    guild = getattr(interaction, "guild", None)
    get_member = getattr(guild, "get_member", None)
    if get_member is not None:
        member = get_member(user.id)
        if member is not None:
            return member
    return None


def purchase_confirm_embed(
    manager: EconomyManager, guild: discord.Guild, user: Any, item: dict[str, Any]
) -> discord.Embed:
    balance = manager.balance(guild.id, user.id)
    price = int(item.get("price") or 0)
    kind = SHOP_KINDS.get(str(item.get("kind")), "Récompense")
    remaining = balance - price
    emb = embed(
        title=f"{item.get('emoji') or '🛒'} {item.get('name')}",
        description=(
            f"{item.get('description') or '*Pas de description*'}\n\n"
            f"**Type** : {kind}\n"
            f"**Prix** : {format_coins(price)}\n"
            f"**Ton solde** : {format_coins(balance)}\n"
            f"**Après achat** : {format_coins(max(0, remaining))}"
        ),
        color=COLOR_SUCCESS if remaining >= 0 else COLOR_ERROR,
        accent="menthe" if remaining >= 0 else None,
        icon=EMOJI["gift"],
    )
    if remaining < 0:
        emb.add_field(
            name="💤 Solde insuffisant",
            value="Il te manque des coins : tente le casino ou `/eco work` !",
            inline=False,
        )
    return emb


async def deliver_purchase(client: Any, member: Any, item: dict[str, Any]) -> str:
    """Applique la récompense d'un achat selon son type."""
    kind = item.get("kind")
    if kind == "coins":
        amount = int(item.get("amount") or 0)
        return f"🎁 Tu récupères **{format_coins(amount)}** dans ton porte-monnaie !"
    if kind == "role" and item.get("role_id") and member is not None and hasattr(member, "guild"):
        role = member.guild.get_role(int(item["role_id"]))
        if role is None:
            return "⚠️ Le rôle lié à cet article a disparu : préviens le staff."
        try:
            await member.add_roles(role, reason="Achat boutique")
            return f"🎁 Rôle {role.mention} ajouté !"
        except discord.HTTPException:
            return "⚠️ Je n'ai pas pu ajouter le rôle (hiérarchie) : le staff va s'en occuper."
    if kind == "ticket":
        return "🎟️ Ticket enregistré : ouvre un message privé au staff pour récupérer ta récompense."
    return "🎁 Récompense enregistrée : un membre du staff va te la remettre."


def inventory_embeds(
    manager: EconomyManager, guild: discord.Guild, user: Any
) -> list[discord.Embed]:
    """Inventaire paginé (par article acheté)."""
    record = manager.account(guild.id, user.id)
    inventory = record.get("inventory") or {}
    if not inventory:
        return [
            embed(
                title=f"{EMOJI['book']} Inventaire",
                description=(
                    "Ton sac est vide…\n"
                    "Découvre la boutique avec `/boutique` et tente les jeux de `/casino` !"
                ),
                color=COLOR_ECONOMY,
            )
        ]

    lines: list[str] = []
    for item_id, count in inventory.items():
        item = manager.shop_item(guild.id, item_id)
        name = item.get("name") if item else f"Article supprimé (`{item_id}`)"
        emoji = (item or {}).get("emoji") or "🎁"
        lines.append(f"{emoji} **{name}** ×{int(count)}")

    pages: list[discord.Embed] = []
    for index in range(0, len(lines), 8):
        emb = embed(
            title=f"{EMOJI['book']} Inventaire de {getattr(user, 'display_name', user)}",
            description="\n".join(lines[index : index + 8]),
            color=gradient_color("ocean", index / max(1, len(lines))),
            accent="ocean",
            icon=EMOJI["book"],
        )
        emb.add_field(name=f"{CURRENCY_EMOJI} Solde", value=format_coins(record.get("coins", 0)), inline=True)
        emb.add_field(name="🎒 Articles", value=str(sum(int(c) for c in inventory.values())), inline=True)
        pages.append(emb)
    return pages


# --------------------------------------------------------------------------- #
# Animations partagées
# --------------------------------------------------------------------------- #
class AnimatedMessage:
    """Fait tourner un message d'attente (spinner) sans bloquer la boucle."""

    def __init__(
        self,
        interaction: discord.Interaction,
        *,
        title: str,
        color: int = COLOR_ECONOMY,
        frames: int = 3,
        delay: float = 0.45,
    ) -> None:
        self.interaction = interaction
        self.title = title
        self.color = color
        self.frames = frames
        self.delay = delay

    def frame_embed(self, step: int) -> discord.Embed:
        from ..helpers import spinner

        dots = "." * ((step % 3) + 1)
        return embed(
            title=f"{spinner(step)} {self.title}{dots}",
            description=f"*{SPARKLES[step % len(SPARKLES)]} Ça tourne…*",
            color=self.color,
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        step = 0
        while not stop_event.is_set() and step < self.frames * 4:
            with contextlib.suppress(discord.HTTPException):
                await self.interaction.edit_original_response(embed=self.frame_embed(step))
            step += 1
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.delay)
            except TimeoutError:
                continue


def random_confetti() -> str:
    from ..constants import CONFETTI

    return random.choice(CONFETTI)


async def paginate(
    interaction: discord.Interaction, pages: list[discord.Embed], *, ephemeral: bool = True
) -> None:
    """Affiche des pages avec le paginateur commun."""
    view = Paginator(pages, author_id=interaction.user.id)
    if interaction.response.is_done():
        await interaction.followup.send(embed=pages[0], view=view, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=ephemeral)


__all__ = [
    "AnimatedMessage",
    "PurchaseConfirmView",
    "ShopSelect",
    "ShopView",
    "deliver_purchase",
    "inventory_embeds",
    "item_line",
    "leaderboard_embeds",
    "level_badge",
    "level_up_embed",
    "paginate",
    "profile_embed",
    "progress_line",
    "safe_emoji",
    "purchase_confirm_embed",
    "random_confetti",
    "resolve_member",
    "shop_embed",
    "xp_for_level",
    "humanize_short",
]
