"""Commande `/build` : construire un serveur Discord complet en une commande.

Crée les catégories, les salons d'information, de communauté, vocaux et staff,
applique les permissions, publie les messages d'accueil (dont l'embed de
règlement) et enregistre les salons dans la configuration du bot.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import is_server_admin
from ..constants import EMOJI
from ..helpers import error, info, reply_ephemeral, warning
from ..services.serverbuild import (
    BuildOptions,
    build_plan,
    build_server,
    count_channels,
    plan_embed,
    result_embed,
)
from ..ui.common import ConfirmView

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)

# Confirmation obligatoire au-delà de ce nombre de salons à créer.
CONFIRM_THRESHOLD = 10


class Build(commands.Cog):
    """`/build` — génère une structure de serveur propre et complète."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot

    @app_commands.command(
        name="build",
        description="Construire un serveur complet : annonces, règlement, commandes bot, logs…",
    )
    @app_commands.describe(
        apercu="Afficher le plan détaillé sans rien créer",
        confirmer="Créer les salons sans demander de confirmation",
        regles="Créer le salon règlement avec son embed",
        logs="Créer les salons de logs réservés au staff",
        vocal="Créer le générateur de vocaux temporaires",
        economie="Créer les salons niveaux et casino",
        texte_regles="Règlement personnalisé (markdown accepté)",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @is_server_admin()
    async def build(
        self,
        interaction: discord.Interaction,
        apercu: bool = False,
        confirmer: bool = False,
        regles: bool = True,
        logs: bool = True,
        vocal: bool = True,
        economie: bool = True,
        texte_regles: str | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await reply_ephemeral(
                interaction, error("Commande utilisable uniquement sur un serveur.")
            )
            return

        brand = self.bot.settings.brand
        options = BuildOptions(
            regles=regles,
            logs=logs,
            vocal=vocal,
            economie=economie,
            texte_regles=(texte_regles or "").strip() or None,
        )
        plan = build_plan(options)

        # --------------------------------------------------------------- #
        # Aperçu : aucun appel réseau
        # --------------------------------------------------------------- #
        if apercu:
            await reply_ephemeral(interaction, plan_embed(plan, brand=brand))
            return

        me = guild.me
        permissions = getattr(me, "guild_permissions", None) if me is not None else None
        if (
            permissions is not None
            and not (permissions.manage_channels or permissions.administrator)
        ):
            await reply_ephemeral(
                interaction,
                error(
                    "Il me manque la permission **Gérer les salons** pour construire le serveur.",
                    title="Permission manquante",
                ),
            )
            return

        total = count_channels(plan)

        # --------------------------------------------------------------- #
        # Confirmation anti-fausse manip
        # --------------------------------------------------------------- #
        if not confirmer and total > CONFIRM_THRESHOLD:
            view = ConfirmView(
                author_id=interaction.user.id,
                confirm_label=f"Construire {total} salons",
                danger=False,
                timeout=90,
            )
            message = info(
                f"Je vais créer **{len(plan)} catégories** et **{total} salons** "
                f"dans **{guild.name}**.\n\n"
                "Les salons qui portent déjà le bon nom seront **réutilisés** "
                "(aucun doublon, rien n'est supprimé).\n\n"
                "*Ajoute `confirmer:True` pour passer cette étape la prochaine fois.*",
                title=f"{EMOJI['gear']} Prêt à construire ?",
            )
            confirmed = await view.prompt(interaction, message)
            if confirmed is not True:
                return

        # --------------------------------------------------------------- #
        # Construction
        # --------------------------------------------------------------- #
        if interaction.response.is_done():
            edit = getattr(interaction, "edit_original_response", None)
            if edit is not None:
                await edit(
                    embed=info(
                        f"Construction en cours… {total} salon(s) à traiter.",
                        title=f"{EMOJI['gear']} Patiente un instant",
                    )
                )
        else:
            await interaction.response.defer(thinking=True, ephemeral=True)

        result = await build_server(
            self.bot,
            guild,
            options=options,
            actor=interaction.user,
            reason=f"/build par {interaction.user}",
        )

        emb = result_embed(result, brand=brand)
        try:
            await interaction.followup.send(embed=emb, ephemeral=True)
        except Exception:  # pragma: no cover - interaction expirée
            log.debug("Envoi du résumé /build impossible", exc_info=True)
            return

        if result.failed_count:
            await interaction.followup.send(
                embed=warning(
                    "Certains salons n'ont pas pu être créés : vérifie mes permissions "
                    "et la limite de 500 salons par serveur.",
                    title="Construction partielle",
                ),
                ephemeral=True,
            )


async def setup(bot: "VesparaBot") -> None:
    await bot.add_cog(Build(bot))
