"""Économie, niveaux, boutique et administration (`/eco`, `/boutique`, `/eco-admin`)."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import is_server_admin, is_staff
from ..constants import (
    CURRENCY_EMOJI,
    ECONOMY_MAX_LEVEL,
    EMOJI,
    MAX_LEVEL_REWARDS,
    MAX_SHOP_ITEMS,
)
from ..helpers import (
    embed,
    error,
    gradient_color,
    info,
    reply_ephemeral,
    success,
    warning,
)
from ..services.economy import (
    SHOP_KINDS,
    Cooldown,
    EconomyError,
    EconomyManager,
    InsufficientFunds,
    default_shop_item,
    format_coins,
    format_coins_short,
    humanize_short,
    level_from_total_xp,
    total_xp_for_level,
    xp_for_level,
)
from ..ui.economy import (
    ShopView,
    inventory_embeds,
    leaderboard_embeds,
    level_badge,
    level_up_embed,
    paginate,
    profile_embed,
    progress_line,
    shop_embed,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)

KIND_CHOICES = [
    app_commands.Choice(name=label, value=key) for key, label in SHOP_KINDS.items()
]


def parse_amount(raw: str) -> int:
    """Accepte `1 000`, `1k`, `1.5k`, `2m`, `all` est géré par l'appelant."""
    text = str(raw).strip().lower().replace(" ", "").replace("_", "").replace(",", ".")
    if not text:
        raise EconomyError("Indique un montant.")
    multiplier = 1
    if text.endswith("k"):
        multiplier, text = 1_000, text[:-1]
    elif text.endswith("m"):
        multiplier, text = 1_000_000, text[:-1]
    try:
        value = float(text) * multiplier
    except ValueError as exc:
        raise EconomyError(f"Montant invalide : « {raw} ».") from exc
    if value < 0 or value != value:  # négatif ou NaN
        raise EconomyError("Le montant doit être positif.")
    return int(round(value))


# --------------------------------------------------------------------------- #
# Groupe /eco (tout le monde)
# --------------------------------------------------------------------------- #
@app_commands.guild_only()
class EcoGroup(app_commands.Group, name="eco", description="Économie, niveaux et profil"):
    def __init__(self, cog: "Economy") -> None:
        super().__init__()
        self.cog = cog

    @property
    def manager(self) -> EconomyManager:
        return self.cog.manager

    # ------------------------------------------------------------------ #
    @app_commands.command(name="profil", description="Voir ton profil (coins, niveau, statistiques)")
    @app_commands.describe(membre="Membre à consulter (défaut : toi)")
    async def profil(
        self, interaction: discord.Interaction, membre: discord.Member | None = None
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        target = membre or interaction.user
        await reply_ephemeral(
            interaction, profile_embed(self.manager, interaction.guild, target)
        )

    @app_commands.command(name="solde", description="Afficher ton solde de coins")
    @app_commands.describe(membre="Membre à consulter (défaut : toi)")
    async def solde(
        self, interaction: discord.Interaction, membre: discord.Member | None = None
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        target = membre or interaction.user
        record = self.manager.account(interaction.guild.id, target.id, user_name=str(target))
        info_level = level_from_total_xp(int(record.get("xp") or 0))
        balance = int(record.get("coins") or 0)
        emb = embed(
            title=f"{CURRENCY_EMOJI} Solde de {getattr(target, 'display_name', target)}",
            description=(
                f"## {format_coins(balance)}\n"
                f"{level_badge(info_level.level)} niveau {info_level.level} · "
                f"{progress_line(info_level)}"
            ),
            color=gradient_color("or", 0.2),
            accent="or",
            thumbnail=getattr(getattr(target, "display_avatar", None), "url", None),
        )
        await reply_ephemeral(interaction, emb)

    @app_commands.command(name="classement", description="Classement des membres les plus riches")
    @app_commands.describe(par="Classer par coins ou par expérience")
    @app_commands.choices(
        par=[
            app_commands.Choice(name="🪙 Coins", value="coins"),
            app_commands.Choice(name="📈 Niveau / XP", value="xp"),
        ]
    )
    async def classement(
        self, interaction: discord.Interaction, par: app_commands.Choice[str] | None = None
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        by = par.value if par else "coins"
        pages = leaderboard_embeds(self.manager, interaction.guild, by=by)
        await paginate(interaction, pages)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="daily", description="Récupérer ta récompense journalière (série bonus)")
    async def daily(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        try:
            result = self.manager.claim_daily(interaction.guild.id, interaction.user.id)
        except Cooldown as exc:
            await reply_ephemeral(interaction, warning(str(exc), title="Déjà réclamé aujourd'hui"))
            return

        streak = result["streak"]
        fire = "🔥" * min(5, streak)
        emb = success(
            f"## +{format_coins(result['amount'])}\n"
            f"{fire} Série : **{streak} jour(s)** · multiplicateur ×{result['multiplier']:g}\n"
            f"{CURRENCY_EMOJI} Nouveau solde : **{format_coins(result['balance'])}**",
            title="Récompense récupérée !",
        )
        emb.color = gradient_color("or", 0.3)
        await reply_ephemeral(interaction, emb)

    @app_commands.command(name="work", description="Travailler pour gagner quelques coins (1 h)")
    async def work(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        try:
            result = self.manager.claim_work(interaction.guild.id, interaction.user.id)
        except Cooldown as exc:
            await reply_ephemeral(interaction, warning(str(exc), title="Tu es fatigué"))
            return

        emb = success(
            f"💼 Tu as bossé : **{result['job']}** !\n\n"
            f"## +{format_coins(result['amount'])}\n"
            f"{CURRENCY_EMOJI} Solde : **{format_coins(result['balance'])}**\n\n"
            f"⏳ Reviens dans **{humanize_short(3600)}**.",
            title="Salaire versé",
        )
        await reply_ephemeral(interaction, emb)

    @app_commands.command(name="payer", description="Virer des coins à un autre membre")
    @app_commands.describe(membre="Destinataire", montant="Montant (ex. 250, 1k)")
    async def payer(
        self, interaction: discord.Interaction, membre: discord.Member, montant: str
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        if membre.bot:
            await reply_ephemeral(interaction, error("Les bots n'ont pas besoin de coins. 🤖"))
            return
        try:
            amount = parse_amount(montant)
            balance = self.manager.transfer(
                interaction.guild.id, interaction.user.id, membre.id, amount
            )
        except InsufficientFunds as exc:
            await reply_ephemeral(interaction, error(str(exc), title="Solde insuffisant"))
            return
        except EconomyError as exc:
            await reply_ephemeral(interaction, error(str(exc)))
            return

        await reply_ephemeral(
            interaction,
            success(
                f"{interaction.user.mention} a envoyé **{format_coins(amount)}** à {membre.mention} !\n"
                f"Il te reste **{format_coins(balance)}**.",
                title="Virement effectué",
            ),
        )

    @app_commands.command(name="niveau", description="Voir la progression d'un membre en détail")
    @app_commands.describe(membre="Membre à consulter (défaut : toi)")
    async def niveau(
        self, interaction: discord.Interaction, membre: discord.Member | None = None
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        target = membre or interaction.user
        record = self.manager.account(interaction.guild.id, target.id, user_name=str(target))
        info_level = level_from_total_xp(int(record.get("xp") or 0))
        next_roles = [
            reward
            for reward in self.manager.level_rewards(interaction.guild.id)
            if int(reward.get("level") or 0) > info_level.level
        ]
        next_roles.sort(key=lambda reward: int(reward.get("level") or 0))

        emb = embed(
            title=f"{level_badge(info_level.level)} Niveau {info_level.level} — {getattr(target, 'display_name', target)}",
            description=progress_line(info_level),
            color=gradient_color("ocean", 0.3),
            accent="ocean",
            thumbnail=getattr(getattr(target, "display_avatar", None), "url", None),
            icon=EMOJI["chart"],
        )
        emb.add_field(name="XP totale", value=f"{info_level.total:,} XP".replace(",", " "), inline=True)
        emb.add_field(name="Messages", value=str(int(record.get("messages") or 0)), inline=True)
        emb.add_field(
            name="XP du niveau suivant",
            value=f"{xp_for_level(info_level.level):,} XP".replace(",", " "),
            inline=True,
        )
        if next_roles:
            emb.add_field(
                name="🔓 Prochaines récompenses",
                value="\n".join(
                    f"• niveau {int(reward['level'])} → <@&{int(reward['role_id'])}>"
                    for reward in next_roles[:5]
                    if reward.get("role_id")
                )
                or "*Aucun rôle configuré*",
                inline=False,
            )
        else:
            emb.add_field(
                name="🌱 À venir",
                value="Le staff n'a pas encore configuré de récompense de niveau.",
                inline=False,
            )
        await reply_ephemeral(interaction, emb)


# --------------------------------------------------------------------------- #
# Groupe /boutique (tout le monde)
# --------------------------------------------------------------------------- #
@app_commands.guild_only()
class ShopGroup(app_commands.Group, name="boutique", description="Boutique du serveur"):
    def __init__(self, cog: "Economy") -> None:
        super().__init__()
        self.cog = cog

    @property
    def manager(self) -> EconomyManager:
        return self.cog.manager

    @app_commands.command(name="voir", description="Parcourir la boutique et acheter")
    async def voir(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        emb, _pages = shop_embed(self.manager, interaction.guild, interaction.user)
        view = ShopView(self.manager, interaction.guild, interaction.user.id)
        await interaction.response.send_message(embed=emb, view=view, ephemeral=True)

    @app_commands.command(name="acheter", description="Acheter un article par son nom")
    @app_commands.describe(article="Nom de l'article (autocomplétion disponible)")
    async def acheter(self, interaction: discord.Interaction, article: str) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        item = self.manager.find_shop_item(interaction.guild.id, article)
        if item is None:
            await reply_ephemeral(
                interaction,
                error(
                    f"Aucun article nommé « {article} ». Utilise `/boutique voir` pour la liste.",
                    title="Article introuvable",
                ),
            )
            return
        try:
            result = self.manager.purchase(interaction.guild.id, interaction.user.id, item)
        except EconomyError as exc:
            await reply_ephemeral(interaction, error(str(exc), title="Achat impossible"))
            return

        from ..ui.economy import deliver_purchase, resolve_member

        bonus = await deliver_purchase(interaction.client, resolve_member(interaction), item)
        await reply_ephemeral(
            interaction,
            success(
                f"**{item.get('name')}** acheté pour **{format_coins(result['price'])}** !\n"
                f"Solde : **{format_coins(result['balance'])}**\n\n{bonus}",
                title="Achat validé",
            ),
        )

    @acheter.autocomplete("article")
    async def acheter_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        needle = current.casefold()
        items = [
            item
            for item in self.manager.shop_items(interaction.guild.id)
            if item.get("enabled", True) and needle in str(item.get("name", "")).casefold()
        ]
        return [
            app_commands.Choice(
                name=f"{item.get('name')} · {format_coins(item.get('price', 0))}"[:100],
                value=str(item.get("name"))[:100],
            )
            for item in items[:25]
        ]

    @app_commands.command(name="inventaire", description="Voir tes achats")
    async def inventaire(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        pages = inventory_embeds(self.manager, interaction.guild, interaction.user)
        await paginate(interaction, pages)


# --------------------------------------------------------------------------- #
# Groupe /eco-admin (staff)
# --------------------------------------------------------------------------- #
@app_commands.guild_only()
class EcoAdminGroup(app_commands.Group, name="eco-admin", description="Gérer l'économie et la boutique"):
    def __init__(self, cog: "Economy") -> None:
        super().__init__()
        self.cog = cog

    @property
    def manager(self) -> EconomyManager:
        return self.cog.manager

    # ------------------------------------------------------------------ #
    @app_commands.command(name="donner", description="Créditer des coins à un membre")
    @app_commands.describe(membre="Bénéficiaire", montant="Montant (ex. 500, 2k)")
    @is_staff()
    async def donner(
        self, interaction: discord.Interaction, membre: discord.Member, montant: str
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        try:
            amount = parse_amount(montant)
        except EconomyError as exc:
            await reply_ephemeral(interaction, error(str(exc)))
            return
        balance = self.manager.add_coins(interaction.guild.id, membre.id, amount, reason="admin")
        await reply_ephemeral(
            interaction,
            success(
                f"**{format_coins(amount)}** ajoutés à {membre.mention}.\n"
                f"Son solde : **{format_coins(balance)}**.",
                title="Crédit effectué",
            ),
        )

    @app_commands.command(name="retirer", description="Débiter des coins à un membre")
    @app_commands.describe(membre="Membre concerné", montant="Montant (ex. 500, 2k)")
    @is_staff()
    async def retirer(
        self, interaction: discord.Interaction, membre: discord.Member, montant: str
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        try:
            amount = parse_amount(montant)
            balance = self.manager.remove_coins(
                interaction.guild.id, membre.id, amount, reason="admin"
            )
        except InsufficientFunds as exc:
            await reply_ephemeral(interaction, error(str(exc)))
            return
        except EconomyError as exc:
            await reply_ephemeral(interaction, error(str(exc)))
            return
        await reply_ephemeral(
            interaction,
            success(
                f"**{format_coins(amount)}** retirés à {membre.mention}.\n"
                f"Son solde : **{format_coins(balance)}**.",
                title="Débit effectué",
            ),
        )

    @app_commands.command(name="xp", description="Ajouter de l'XP (et des niveaux) à un membre")
    @app_commands.describe(membre="Membre concerné", montant="XP à ajouter")
    @is_staff()
    async def xp(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        montant: app_commands.Range[int, 1, 1_000_000],
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        result = self.manager.grant_xp(interaction.guild.id, membre.id, int(montant))
        roles = await self.manager.apply_level_rewards(membre, result["levels"])
        if result["leveled_up"]:
            await self.cog.announce_level_up(interaction.guild, membre, result["level"])
        text = f"{membre.mention} reçoit **{montant} XP** → niveau **{result['level']}**."
        if result["leveled_up"]:
            text += f"\n🎁 Bonus : **{format_coins(result['coins_bonus'])}**"
        if roles:
            text += "\n🏅 Rôles débloqués : " + ", ".join(role.mention for role in roles)
        await reply_ephemeral(interaction, success(text, title="XP ajoutée"))

    # ------------------------------------------------------------------ #
    @app_commands.command(name="article-ajouter", description="Ajouter un article à la boutique")
    @app_commands.describe(
        nom="Nom de l'article",
        prix="Prix en coins",
        type="Type de récompense",
        role="Rôle à donner (type « rôle »)",
        description="Description affichée",
        emoji="Emoji de l'article",
        stock="Stock limité (vide = illimité)",
        niveau_requis="Niveau minimum pour acheter",
        limite_par_membre="Nombre maximum d'achats par membre",
        coins="Coins donnés (type « coins »)",
    )
    @app_commands.choices(type=KIND_CHOICES)
    @is_staff()
    async def article_ajouter(
        self,
        interaction: discord.Interaction,
        nom: str,
        prix: app_commands.Range[int, 0, 10_000_000],
        type: app_commands.Choice[str] | None = None,
        role: discord.Role | None = None,
        description: str | None = None,
        emoji: str | None = None,
        stock: app_commands.Range[int, 0, 100_000] | None = None,
        niveau_requis: app_commands.Range[int, 1, ECONOMY_MAX_LEVEL] | None = None,
        limite_par_membre: app_commands.Range[int, 1, 1000] | None = None,
        coins: app_commands.Range[int, 1, 10_000_000] | None = None,
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        if len(self.manager.shop_items(interaction.guild.id)) >= MAX_SHOP_ITEMS:
            await reply_ephemeral(
                interaction, error(f"La boutique est pleine ({MAX_SHOP_ITEMS} articles maximum).")
            )
            return

        kind = type.value if type else ("role" if role else ("coins" if coins else "custom"))
        if kind == "role" and role is None:
            await reply_ephemeral(interaction, error("Indique le `role` à donner pour ce type d'article."))
            return
        if kind == "coins" and not coins:
            await reply_ephemeral(interaction, error("Indique le nombre de `coins` à donner."))
            return
        if self.manager.find_shop_item(interaction.guild.id, nom) is not None:
            await reply_ephemeral(interaction, error(f"Un article « {nom} » existe déjà."))
            return

        item = self.manager.add_shop_item(
            interaction.guild.id,
            default_shop_item()
            | {
                "name": nom[:100],
                "description": (description or "")[:300],
                "kind": kind,
                "price": int(prix),
                "emoji": emoji or ("🏷️" if kind == "role" else "🎁"),
                "role_id": role.id if role else None,
                "amount": int(coins or 0),
                "stock": int(stock) if stock is not None else None,
                "requires_level": int(niveau_requis) if niveau_requis else None,
                "max_per_user": int(limite_par_membre) if limite_par_membre else None,
            },
        )
        emb = success(
            f"**{item['emoji']} {item['name']}** est en vente pour **{format_coins(item['price'])}**.\n"
            f"Type : {SHOP_KINDS.get(item['kind'], item['kind'])}"
            + (f" · rôle {role.mention}" if role else "")
            + (f" · stock {item['stock']}" if item["stock"] is not None else "")
            + (f" · niveau {item['requires_level']}+" if item["requires_level"] else ""),
            title="Article ajouté",
        )
        emb.set_footer(text=f"Vespara • Boutique • id {item['id']}")
        await reply_ephemeral(interaction, emb)

    @app_commands.command(name="article-supprimer", description="Supprimer un article de la boutique")
    @app_commands.describe(article="Nom de l'article")
    @is_staff()
    async def article_supprimer(self, interaction: discord.Interaction, article: str) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        item = self.manager.find_shop_item(interaction.guild.id, article)
        if item is None:
            await reply_ephemeral(interaction, error(f"Article « {article} » introuvable."))
            return
        self.manager.remove_shop_item(interaction.guild.id, item["id"])
        await reply_ephemeral(
            interaction, success(f"**{item['name']}** a été retiré de la boutique.", title="Article supprimé")
        )

    @app_commands.command(name="article-modifier", description="Modifier un article existant")
    @app_commands.describe(
        article="Nom de l'article à modifier",
        nouveau_nom="Nouveau nom",
        prix="Nouveau prix",
        stock="Nouveau stock (0 = rupture)",
        niveau_requis="Nouveau niveau minimum",
        actif="Mettre en vente ou retirer de la vente",
        description="Nouvelle description",
    )
    @is_staff()
    async def article_modifier(
        self,
        interaction: discord.Interaction,
        article: str,
        nouveau_nom: str | None = None,
        prix: app_commands.Range[int, 0, 10_000_000] | None = None,
        stock: app_commands.Range[int, 0, 100_000] | None = None,
        niveau_requis: app_commands.Range[int, 1, ECONOMY_MAX_LEVEL] | None = None,
        actif: bool | None = None,
        description: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        item = self.manager.find_shop_item(interaction.guild.id, article)
        if item is None:
            await reply_ephemeral(interaction, error(f"Article « {article} » introuvable."))
            return

        changes: list[str] = []
        if nouveau_nom:
            item["name"] = nouveau_nom[:100]
            changes.append(f"nom → **{item['name']}**")
        if prix is not None:
            item["price"] = int(prix)
            changes.append(f"prix → **{format_coins(prix)}**")
        if stock is not None:
            item["stock"] = int(stock)
            changes.append(f"stock → **{stock}**")
        if niveau_requis is not None:
            item["requires_level"] = int(niveau_requis)
            changes.append(f"niveau → **{niveau_requis}**")
        if actif is not None:
            item["enabled"] = bool(actif)
            changes.append("en vente" if actif else "retiré de la vente")
        if description is not None:
            item["description"] = description[:300]
            changes.append("description mise à jour")

        self.manager.db.schedule_save(0.5)
        if not changes:
            await reply_ephemeral(interaction, info("Aucun changement demandé.", title="Rien à faire"))
            return
        await reply_ephemeral(
            interaction,
            success("• " + "\n• ".join(changes), title=f"Article « {item['name']} » modifié"),
        )

    @app_commands.command(name="article-liste", description="Lister tous les articles de la boutique")
    @is_staff()
    async def article_liste(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        items = self.manager.shop_items(interaction.guild.id)
        if not items:
            await reply_ephemeral(
                interaction,
                info(
                    "Aucun article. Ajoute-en un avec `/eco-admin article-ajouter`.",
                    title="Boutique vide",
                ),
            )
            return

        lines = []
        for item in items[:30]:
            state = "✅" if item.get("enabled", True) else "🚫"
            stock = f" · 📦 {item['stock']}" if item.get("stock") is not None else ""
            lines.append(
                f"{state} {item.get('emoji', '🎁')} **{item.get('name')}** — "
                f"{format_coins(item.get('price', 0))} · {SHOP_KINDS.get(str(item.get('kind')), '?')}{stock}"
            )
        emb = embed(
            title=f"{EMOJI['gift']} Articles — {interaction.guild.name}",
            description="\n".join(lines),
            color=gradient_color("rose", 0.15),
            accent="rose",
        )
        emb.set_footer(text=f"Vespara • {len(items)}/{MAX_SHOP_ITEMS} articles")
        await reply_ephemeral(interaction, emb)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="recompense", description="Donner un rôle automatiquement à un niveau")
    @app_commands.describe(
        niveau="Niveau requis",
        role="Rôle à attribuer",
        retirer="Supprimer la récompense de ce niveau",
    )
    @is_staff()
    async def recompense(
        self,
        interaction: discord.Interaction,
        niveau: app_commands.Range[int, 1, ECONOMY_MAX_LEVEL],
        role: discord.Role | None = None,
        retirer: bool = False,
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        rewards = self.manager.level_rewards(interaction.guild.id)

        if retirer:
            before = len(rewards)
            rewards[:] = [reward for reward in rewards if int(reward.get("level") or 0) != int(niveau)]
            if len(rewards) == before:
                await reply_ephemeral(interaction, error(f"Aucune récompense au niveau {niveau}."))
                return
            self.manager.db.schedule_save(0.5)
            await reply_ephemeral(
                interaction, success(f"La récompense du niveau **{niveau}** est supprimée.")
            )
            return

        if role is None:
            await reply_ephemeral(interaction, error("Indique le `role` à attribuer."))
            return
        if role.is_default() or role.managed:
            await reply_ephemeral(interaction, error("Choisis un rôle normal (ni @everyone ni intégration)."))
            return
        if len(rewards) >= MAX_LEVEL_REWARDS:
            await reply_ephemeral(
                interaction, error(f"Maximum {MAX_LEVEL_REWARDS} récompenses de niveau.")
            )
            return

        existing = self.manager.reward_for_level(interaction.guild.id, int(niveau))
        if existing is not None:
            existing["role_id"] = role.id
        else:
            rewards.append({"level": int(niveau), "role_id": role.id})
        rewards.sort(key=lambda reward: int(reward.get("level") or 0))
        self.manager.db.schedule_save(0.5)

        await reply_ephemeral(
            interaction,
            success(
                f"Le rôle {role.mention} sera attribué automatiquement au **niveau {niveau}**.",
                title="Récompense enregistrée",
            ),
        )

    @app_commands.command(name="parametres", description="Régler l'XP et les annonces de niveau")
    @app_commands.describe(
        xp_actif="Activer ou désactiver le gain d'XP par message",
        multiplicateur="Multiplicateur d'XP (ex. 1.5)",
        salon_niveau="Salon où annoncer les passages de niveau (vide = salon courant)",
        annonces="Activer ou désactiver les annonces de niveau",
        salon_casino="Restreindre le casino à un salon (vide = partout)",
        effacer_salon="Effacer le salon d'annonce des niveaux",
        effacer_casino="Effacer la restriction du casino",
    )
    @is_staff()
    async def parametres(
        self,
        interaction: discord.Interaction,
        xp_actif: bool | None = None,
        multiplicateur: app_commands.Range[float, 0.1, 10.0] | None = None,
        salon_niveau: discord.TextChannel | None = None,
        annonces: bool | None = None,
        salon_casino: discord.TextChannel | None = None,
        effacer_salon: bool = False,
        effacer_casino: bool = False,
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        settings = self.manager.db.guild(interaction.guild.id)
        changes: list[str] = []
        if xp_actif is not None:
            settings["xp_enabled"] = bool(xp_actif)
            changes.append(f"XP par message : {'✅ activée' if xp_actif else '🚫 désactivée'}")
        if multiplicateur is not None:
            settings["xp_rate"] = float(multiplicateur)
            changes.append(f"multiplicateur d'XP : ×{float(multiplicateur):g}")
        if salon_niveau is not None:
            settings["levelup_channel_id"] = salon_niveau.id
            changes.append(f"annonces de niveau dans {salon_niveau.mention}")
        if annonces is not None:
            settings["levelup_enabled"] = bool(annonces)
            changes.append(f"annonces de niveau : {'✅' if annonces else '🚫'}")
        if salon_casino is not None:
            settings["casino_channel_id"] = salon_casino.id
            changes.append(f"casino limité à {salon_casino.mention}")
        if effacer_salon:
            settings["levelup_channel_id"] = None
            changes.append("salon d'annonce réinitialisé")
        if effacer_casino:
            settings["casino_channel_id"] = None
            changes.append("casino de nouveau accessible partout")
        self.manager.db.schedule_save(0.5)

        if not changes:
            channel_text = (
                f"<#{int(settings['levelup_channel_id'])}>"
                if settings.get("levelup_channel_id")
                else "salon courant"
            )
            casino_text = (
                f"<#{int(settings['casino_channel_id'])}>"
                if settings.get("casino_channel_id")
                else "partout"
            )
            await reply_ephemeral(
                interaction,
                info(
                    f"XP par message : {'✅' if settings.get('xp_enabled', True) else '🚫'}\n"
                    f"Multiplicateur : ×{float(settings.get('xp_rate') or 1):g}\n"
                    f"Annonces de niveau : {'✅' if settings.get('levelup_enabled', True) else '🚫'}\n"
                    f"Salon d'annonce : {channel_text}\n"
                    f"Salon du casino : {casino_text}",
                    title="Paramètres d'économie",
                ),
            )
            return
        await reply_ephemeral(
            interaction, success("• " + "\n• ".join(changes), title="Paramètres mis à jour")
        )

    @app_commands.command(name="reinitialiser", description="Remettre à zéro l'économie d'un membre")
    @app_commands.describe(membre="Membre concerné", tout="Réinitialiser aussi son XP et son inventaire")
    @is_server_admin()
    async def reinitialiser(
        self, interaction: discord.Interaction, membre: discord.Member, tout: bool = False
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        record = self.manager.account(interaction.guild.id, membre.id)
        from ..services.economy import default_user

        fresh = default_user()
        record["coins"] = fresh["coins"]
        record["gambled"] = 0
        record["won"] = 0
        record["lost"] = 0
        record["games"] = 0
        record["best_win"] = 0
        if tout:
            record["xp"] = 0
            record["level"] = 1
            record["inventory"] = {}
        self.manager.db.schedule_save(0.5)
        await reply_ephemeral(
            interaction,
            success(
                f"Le compte de {membre.mention} a été réinitialisé"
                + (" (coins, XP et inventaire)." if tout else " (coins et statistiques)."),
                title="Réinitialisation",
            ),
        )

    @app_commands.command(name="etat", description="Statistiques globales de l'économie du serveur")
    @is_staff()
    async def etat(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        guild = interaction.guild
        manager = self.manager
        total = self.manager.db.total_coins(guild.id)
        entries = manager.leaderboard(guild.id, limit=1000)
        settings = manager.db.guild(guild.id)
        items = manager.shop_items(guild.id)

        emb = embed(
            title=f"{CURRENCY_EMOJI} Économie — {guild.name}",
            color=gradient_color("or", 0.25),
            accent="or",
            thumbnail=guild.icon.url if guild.icon else None,
        )
        emb.add_field(name="Membres suivis", value=str(len(entries)), inline=True)
        emb.add_field(name="Coins en circulation", value=format_coins_short(total), inline=True)
        emb.add_field(name="Articles", value=f"{len(items)}/{MAX_SHOP_ITEMS}", inline=True)
        emb.add_field(
            name="XP par message",
            value="✅ activée" if settings.get("xp_enabled", True) else "🚫 désactivée",
            inline=True,
        )
        emb.add_field(
            name="Multiplicateur", value=f"×{float(settings.get('xp_rate') or 1):g}", inline=True
        )
        emb.add_field(
            name="Récompenses de niveau", value=str(len(manager.level_rewards(guild.id))), inline=True
        )
        emb.add_field(
            name="Salon casino",
            value=(
                f"<#{int(settings['casino_channel_id'])}>"
                if settings.get("casino_channel_id")
                else "partout"
            ),
            inline=True,
        )
        if entries:
            podium = "\n".join(
                f"{'🥇🥈🥉'[index]} <@{entry['user_id']}> — {format_coins_short(entry['value'])}"
                for index, entry in enumerate(entries[:3])
            )
            emb.add_field(name="Podium", value=podium or "—", inline=False)
        emb.set_footer(text="Vespara • Économie • /eco-admin pour tout configurer")
        await reply_ephemeral(interaction, emb)


# --------------------------------------------------------------------------- #
# Cog
# --------------------------------------------------------------------------- #
class Economy(commands.Cog):
    """Économie, niveaux, boutique et récompenses."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self.manager = EconomyManager(bot)
        bot.economy = self.manager  # type: ignore[attr-defined]
        self.eco = EcoGroup(self)
        self.boutique = ShopGroup(self)
        self.admin = EcoAdminGroup(self)

    async def cog_unload(self) -> None:
        for group in (self.eco, self.boutique, self.admin):
            self.bot.tree.remove_command(group.name)
        if getattr(self.bot, "economy", None) is self.manager:
            self.bot.economy = None  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # XP à chaque message
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if not message.content and not message.attachments:
            return

        settings = self.bot.db.guild(message.guild.id)
        if not settings.get("xp_enabled", True):
            return

        xp = self.manager.message_xp(message.guild.id, message.author.id)
        if not xp:
            return
        rate = float(settings.get("xp_rate") or 1.0)
        xp = max(1, int(xp * rate))

        record = self.manager.account(message.guild.id, message.author.id, user_name=str(message.author))
        record["messages"] = int(record.get("messages") or 0) + 1
        result = self.manager.grant_xp(message.guild.id, message.author.id, xp)
        await self.manager.apply_level_rewards(message.author, result["levels"])

        if not result["leveled_up"]:
            return

        target = message.channel
        channel_id = settings.get("levelup_channel_id")
        if channel_id:
            fetched = message.guild.get_channel(int(channel_id))
            if fetched is not None and hasattr(fetched, "send"):
                target = fetched
        if not settings.get("levelup_enabled", True):
            return

        info_level = level_from_total_xp(int(self.manager.account(message.guild.id, message.author.id).get("xp") or 0))
        emb = level_up_embed(message.author, result["level"], info_level, result["coins_bonus"])
        with contextlib.suppress(discord.HTTPException):
            await target.send(  # type: ignore[union-attr]
                content=message.author.mention,
                embed=emb,
                allowed_mentions=discord.AllowedMentions(users=True),
            )

    # ------------------------------------------------------------------ #
    # Niveau gagné hors message (commande /eco-admin xp)
    # ------------------------------------------------------------------ #
    async def announce_level_up(
        self, guild: discord.Guild, member: discord.Member, level: int
    ) -> None:
        settings = self.bot.db.guild(guild.id)
        if not settings.get("levelup_enabled", True):
            return
        channel = guild.get_channel(int(settings.get("levelup_channel_id") or 0)) or guild.system_channel
        if channel is None or not hasattr(channel, "send"):
            return
        with contextlib.suppress(discord.HTTPException):
            await channel.send(  # type: ignore[union-attr]
                embed=level_up_embed(
                    member, level, level_from_total_xp(total_xp_for_level(level)), 0
                )
            )


async def setup(bot: "VesparaBot") -> None:
    cog = Economy(bot)
    await bot.add_cog(cog)
    for group in (cog.eco, cog.boutique, cog.admin):
        bot.tree.add_command(group, override=True)


__all__ = ["Economy", "parse_amount"]
