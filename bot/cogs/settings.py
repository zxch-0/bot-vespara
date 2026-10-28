"""Configuration du serveur (staff / administrateurs)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import (
    command_visibility_notice,
    is_server_admin,
    is_staff,
    resolve_staff_role,
    staff_role_has_visibility_permission,
)
from ..constants import (
    COLOR,
    EMOJI,
    FOOTER,
    MAX_AUTORESPONSES,
)
from ..helpers import (
    embed,
    error,
    info,
    reply_ephemeral,
    success,
    warning,
)
from ..ui.menu import MenuView

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Modal du règlement
# --------------------------------------------------------------------------- #
class RulesModal(discord.ui.Modal, title="Règlement du serveur"):
    def __init__(self, bot: "VesparaBot", *, current: str) -> None:
        super().__init__(timeout=900)
        self.bot = bot
        self.rules_input = discord.ui.TextInput(
            label="Règlement",
            style=discord.TextStyle.paragraph,
            max_length=3500,
            required=True,
            default=current[:3500],
            placeholder="Rédige le règlement… (markdown accepté)",
        )
        self.add_item(self.rules_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return
        settings = self.bot.db.guild(interaction.guild.id)
        settings["rules"] = str(self.rules_input.value).strip()
        self.bot.db.schedule_save(0.5)
        await reply_ephemeral(
            interaction,
            success("Le règlement a été mis à jour. Les membres peuvent le lire avec `/rules`."),
        )

    async def on_error(self, interaction: discord.Interaction, exc: Exception) -> None:
        await reply_ephemeral(interaction, error(f"Enregistrement impossible : `{exc}`"))


# --------------------------------------------------------------------------- #
# Groupe /config
# --------------------------------------------------------------------------- #
@app_commands.guild_only()
class ConfigGroup(app_commands.Group, name="config", description="Configurer le bot sur ce serveur"):
    @app_commands.command(name="voir", description="Afficher la configuration actuelle")
    @is_staff()
    async def voir(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return

        bot: "VesparaBot" = interaction.client  # type: ignore[assignment]
        db = bot.db
        guild = interaction.guild
        settings = db.guild(guild.id)

        staff_role = resolve_staff_role(bot, guild)
        announce_channel = guild.get_channel(int(settings["announce_channel_id"])) if settings.get("announce_channel_id") else None
        panel_channel = guild.get_channel(int(settings["panel_channel_id"])) if settings.get("panel_channel_id") else None
        responses = db.autoresponses(guild.id)
        active = db.guild_giveaways(guild.id)
        voice_hub = guild.get_channel(int(settings["voice_hub_id"])) if settings.get("voice_hub_id") else None
        voice_rooms = db.guild_voice_rooms(guild.id)
        cooldown = int(settings.get("autoresponder_cooldown") or 0)

        emb = embed(
            title=f"{EMOJI['gear']} Configuration de {bot.settings.brand}",
            description=f"*{command_visibility_notice(bot, guild)}*",
            color=COLOR,
            thumbnail=guild.icon.url if guild.icon else None,
        )
        emb.add_field(
            name="Rôle staff",
            value=staff_role.mention if staff_role else "❌ Non configuré (`/staffrole`)",
            inline=True,
        )
        emb.add_field(
            name="Salon des annonces",
            value=announce_channel.mention if announce_channel else "Salon courant",
            inline=True,
        )
        emb.add_field(
            name="Panneau du menu",
            value=panel_channel.mention if panel_channel else "Non publié",
            inline=True,
        )
        emb.add_field(
            name="Règlement",
            value="Personnalisé" if settings.get("rules") else "Par défaut",
            inline=True,
        )
        emb.add_field(
            name="Réponses automatiques",
            value=f"{len(responses)}/{MAX_AUTORESPONSES} · cooldown {cooldown} s",
            inline=True,
        )
        emb.add_field(name="Giveaways en cours", value=str(len(active)), inline=True)
        emb.add_field(
            name="Vocaux temporaires",
            value=(
                f"{voice_hub.mention} · {len(voice_rooms)} actif(s)"
                if voice_hub
                else "❌ Non installé (`/vocal installer`)"
            ),
            inline=True,
        )
        economy_items = db.guild(guild.id).get("shop_items") or []
        emb.add_field(
            name="Économie",
            value=(
                f"{len(economy_items)} article(s) · "
                f"{len(db.guild(guild.id).get('level_rewards') or [])} récompense(s) de niveau"
            ),
            inline=True,
        )
        emb.add_field(
            name="Commandes",
            value=(
                "`/config salon-annonces` · salon des annonces\n"
                "`/config reglement` · éditer le règlement\n"
                "`/config menu` · publier le panneau du menu\n"
                "`/vocal installer` · installer les vocaux temporaires\n"
                "`/eco-admin etat` · économie, boutique et niveaux\n"
                "`/staffrole` · définir le rôle staff (admin)"
            ),
            inline=False,
        )
        emb.set_footer(text=FOOTER)
        await reply_ephemeral(interaction, emb)

    @app_commands.command(name="salon-annonces", description="Définir le salon par défaut des annonces")
    @app_commands.describe(salon="Salon à utiliser (laisser vide pour revenir au salon courant)")
    @is_staff()
    async def announce_channel(
        self, interaction: discord.Interaction, salon: discord.TextChannel | None = None
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return
        bot: "VesparaBot" = interaction.client  # type: ignore[assignment]
        settings = bot.db.guild(interaction.guild.id)
        settings["announce_channel_id"] = salon.id if salon else None
        bot.db.schedule_save(0.5)
        if salon is None:
            await reply_ephemeral(
                interaction, success("Les annonces utiliseront désormais le salon courant.")
            )
        else:
            await reply_ephemeral(
                interaction, success(f"Les annonces seront publiées dans {salon.mention}.")
            )

    @app_commands.command(name="reglement", description="Éditer ou réinitialiser le règlement du serveur")
    @app_commands.describe(reinitialiser="Revenir au règlement par défaut")
    @is_staff()
    async def rules(
        self, interaction: discord.Interaction, reinitialiser: bool = False
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return
        bot: "VesparaBot" = interaction.client  # type: ignore[assignment]
        settings = bot.db.guild(interaction.guild.id)

        if reinitialiser:
            settings["rules"] = None
            bot.db.schedule_save(0.5)
            await reply_ephemeral(interaction, success("Le règlement par défaut est rétabli."))
            return

        from ..constants import DEFAULT_RULES

        current = settings.get("rules") or DEFAULT_RULES
        await interaction.response.send_modal(RulesModal(bot, current=current))

    @app_commands.command(name="menu", description="Publier le panneau du menu dans un salon")
    @app_commands.describe(salon="Salon où publier (défaut : salon courant)")
    @is_staff()
    async def publish_menu(
        self, interaction: discord.Interaction, salon: discord.TextChannel | None = None
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return
        bot: "VesparaBot" = interaction.client  # type: ignore[assignment]
        channel = salon or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await reply_ephemeral(interaction, error("Choisis un salon textuel valide."))
            return

        from ..ui.builders import menu_embed

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            message = await channel.send(
                embed=menu_embed(bot, interaction.guild),
                view=MenuView(bot),
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error(f"Je n'ai pas la permission d'écrire dans {channel.mention}."),
                ephemeral=True,
            )
            return

        settings = bot.db.guild(interaction.guild.id)
        settings["panel_channel_id"] = channel.id
        settings["panel_message_id"] = message.id
        bot.db.schedule_save(0.5)

        await interaction.followup.send(
            embed=success(
                f"Panneau publié dans {channel.mention} !\n→ [Voir le message]({message.jump_url})",
                title="Menu publié",
            ),
            ephemeral=True,
        )


# --------------------------------------------------------------------------- #
# Cog
# --------------------------------------------------------------------------- #
class Settings(commands.Cog):
    """Configuration du serveur et rôle staff."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self.config = ConfigGroup()

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.config.name)

    @app_commands.command(name="staffrole", description="Définir le rôle qui peut utiliser les commandes staff")
    @app_commands.describe(role="Rôle staff (laisser vide pour voir la configuration actuelle)")
    @app_commands.guild_only()
    @is_server_admin()
    async def staffrole(
        self, interaction: discord.Interaction, role: discord.Role | None = None
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return

        settings = self.bot.db.guild(interaction.guild.id)
        if role is None:
            current = resolve_staff_role(self.bot, interaction.guild)
            await reply_ephemeral(
                interaction,
                info(
                    command_visibility_notice(self.bot, interaction.guild, detailed=True)
                    if current is None
                    else (
                        f"Le rôle staff actuel est {current.mention}.\n\n"
                        + command_visibility_notice(self.bot, interaction.guild, detailed=True)
                    )
                ),
            )
            return

        if role.is_default() or role.managed:
            await reply_ephemeral(
                interaction, error("Choisis un rôle normal (ni @everyone, ni un rôle d'intégration).")
            )
            return

        settings["staff_role_id"] = role.id
        self.bot.db.schedule_save(0.5)

        if staff_role_has_visibility_permission(self.bot, role):
            await reply_ephemeral(
                interaction,
                success(
                    f"{role.mention} est maintenant le rôle staff.\n"
                    f"Seuls ses membres voient et utilisent les commandes de gestion.",
                    title="Rôle staff défini",
                ),
            )
            return

        await reply_ephemeral(
            interaction,
            warning(
                f"{role.mention} est maintenant le rôle staff et ses membres pourront utiliser "
                f"les commandes de gestion.\n\n"
                f"⚠️ En revanche, ils ne les **verront pas** tant que le rôle n'a pas la permission "
                f"**{self.bot.settings.staff_permission_label}**.\n\n"
                f"Deux solutions :\n"
                f"• Accordé cette permission à {role.mention} dans les paramètres du rôle ;\n"
                f"• Ou définis les permissions des commandes dans **Paramètres du serveur → "
                f"Intégrations → {self.bot.settings.brand}**.",
                title="Rôle staff défini (visibilité à compléter)",
            ),
        )


async def setup(bot: "VesparaBot") -> None:
    cog = Settings(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.config, override=True)
