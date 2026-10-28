"""Salons vocaux temporaires : `/vocal …` (staff) + gestion automatique.

Le staff installe **une seule fois** le système avec `/vocal installer` : le bot
crée un salon vocal « générateur » accessible à **tout le monde**. Il suffit
ensuite de rejoindre ce salon pour obtenir son vocal personnel, avec un panneau
de gestion directement dans le chat du salon créé.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import is_staff
from ..constants import (
    COLOR,
    COLOR_INFO,
    EMOJI,
    FOOTER,
    TEMPVOICE_DEFAULT_LIMIT,
    TEMPVOICE_HUB_NAME,
    TEMPVOICE_MAX_LIMIT,
    TEMPVOICE_MAX_ROOMS,
    TEMPVOICE_NAME_MAX_LENGTH,
    TEMPVOICE_NAME_TEMPLATE,
)
from ..helpers import embed, error, reply_ephemeral, success, truncate, warning
from ..services.tempvoice import (
    TempVoiceManager,
    format_room_name,
    hub_embed,
    room_state_label,
)
from ..ui.tempvoice import TempVoicePanel

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)

HUB_OVERWRITE = discord.PermissionOverwrite(
    view_channel=True,
    connect=True,
    speak=True,
    stream=True,
    use_voice_activation=True,
)


# --------------------------------------------------------------------------- #
# Groupe /vocal
# --------------------------------------------------------------------------- #
@app_commands.guild_only()
class VocalGroup(app_commands.Group, name="vocal", description="Installer et piloter les vocaux temporaires"):
    def __init__(self, cog: "TempVoice") -> None:
        super().__init__()
        self.cog = cog

    @property
    def bot(self) -> "VesparaBot":
        return self.cog.bot

    @property
    def manager(self) -> TempVoiceManager:
        return self.cog.manager

    # ------------------------------------------------------------------ #
    @app_commands.command(name="installer", description="Créer le salon générateur de vocaux temporaires")
    @app_commands.describe(
        categorie="Catégorie où placer le salon générateur (défaut : aucune)",
        nom="Nom du salon générateur",
        limite="Nombre de places par défaut des vocaux créés (0 = illimité)",
        remplacer="Reconfigurer le système même s'il est déjà installé",
    )
    @is_staff()
    async def installer(
        self,
        interaction: discord.Interaction,
        categorie: discord.CategoryChannel | None = None,
        nom: str | None = None,
        limite: app_commands.Range[int, 0, TEMPVOICE_MAX_LIMIT] | None = None,
        remplacer: bool = False,
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return

        guild = interaction.guild
        settings = self.manager.config(guild.id)
        existing = self.manager.hub(guild)
        if existing is not None and not remplacer:
            await reply_ephemeral(
                interaction,
                warning(
                    f"Le système est déjà installé : {existing.mention}.\n\n"
                    "Rejoins simplement ce salon pour créer ton vocal.\n"
                    "Utilise `/vocal desactiver` pour tout retirer, ou ajoute "
                    "`remplacer:True` pour recréer le salon générateur.",
                    title="Déjà installé",
                ),
            )
            return

        me = guild.me
        if me is not None and not me.guild_permissions.manage_channels:
            await reply_ephemeral(
                interaction,
                error(
                    "Il me manque la permission **Gérer les salons** pour créer le salon générateur.",
                    title="Permission manquante",
                ),
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        overwrites: dict[object, discord.PermissionOverwrite] = {}
        if guild.default_role is not None:
            overwrites[guild.default_role] = HUB_OVERWRITE
        if me is not None:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                send_messages=True,
                manage_channels=True,
                move_members=True,
                manage_roles=True,
                read_message_history=True,
            )

        hub_name = (nom or settings.get("voice_hub_name") or TEMPVOICE_HUB_NAME).strip() or TEMPVOICE_HUB_NAME
        try:
            hub = await guild.create_voice_channel(
                hub_name[:100],
                category=categorie,
                overwrites=overwrites,
                reason=f"Installation des vocaux temporaires par {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error("Permissions insuffisantes pour créer le salon vocal.", title="Échec"),
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(
                embed=error(f"Création impossible : `{exc}`", title="Échec"), ephemeral=True
            )
            return

        settings["voice_hub_id"] = hub.id
        settings["voice_hub_name"] = hub_name
        settings["voice_category_id"] = categorie.id if categorie else None
        settings["voice_name_template"] = settings.get("voice_name_template") or TEMPVOICE_NAME_TEMPLATE
        settings["voice_limit"] = int(limite if limite is not None else (settings.get("voice_limit") or TEMPVOICE_DEFAULT_LIMIT))
        self.bot.db.schedule_save(0.5)

        # Ancien hub éventuel (mode « remplacer »)
        if existing is not None and existing.id != hub.id:
            with contextlib.suppress(discord.HTTPException):
                await existing.delete(reason="Remplacement du salon générateur")

        with contextlib.suppress(discord.HTTPException):
            await hub.send(embed=hub_embed(self.bot, hub))

        template = format_room_name(settings.get("voice_name_template"), interaction.user, 1)
        emb = success(
            f"Le salon générateur {hub.mention} est en place et **accessible à tout le monde**.\n\n"
            f"**Comment ça marche ?**\n"
            f"1. Un membre rejoint {hub.mention} ;\n"
            f"2. Je crée instantanément un vocal personnel (ex. *{template}*), je l'y déplace ;\n"
            f"3. Un **panneau de gestion** apparaît dans le chat du salon créé : renommer, "
            f"verrouiller, limiter les places, expulser, autoriser, transférer, supprimer…\n"
            f"4. Le salon est **supprimé automatiquement** dès qu'il est vide.\n\n"
            f"Places par défaut : **{settings['voice_limit'] or 'illimité'}** · "
            f"jusqu'à **{TEMPVOICE_MAX_ROOMS}** vocaux simultanés.",
            title="Vocaux temporaires installés",
        )
        emb.add_field(name="Astuce", value="`/vocal etat` pour suivre les salons actifs.", inline=False)
        if me is not None and not me.guild_permissions.move_members:
            emb.add_field(
                name=f"{EMOJI['warning']} Permission manquante",
                value=(
                    "Donne-moi la permission **Déplacer des membres** : sans elle, les membres "
                    "ne seront pas déplacés automatiquement dans leur nouveau salon."
                ),
                inline=False,
            )
        emb.color = COLOR
        emb.set_footer(text=FOOTER)
        await interaction.followup.send(embed=emb, ephemeral=True)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="etat", description="Voir la configuration et les vocaux actifs")
    @is_staff()
    async def etat(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return

        guild = interaction.guild
        settings = self.manager.config(guild.id)
        hub = self.manager.hub(guild)
        rooms = self.bot.db.guild_voice_rooms(guild.id)

        if hub is None and not settings.get("voice_hub_id"):
            await reply_ephemeral(
                interaction,
                warning(
                    "Le système n'est pas installé sur ce serveur.\n"
                    "Lance `/vocal installer` pour créer le salon générateur.",
                    title="Non installé",
                ),
            )
            return

        emb = embed(
            title=f"{EMOJI['mic']} Vocaux temporaires — {guild.name}",
            color=COLOR_INFO,
            thumbnail=guild.icon.url if guild.icon else None,
        )
        emb.add_field(
            name="Salon générateur",
            value=hub.mention if hub else f"{EMOJI['error']} introuvable (`/vocal installer`)",
            inline=True,
        )
        emb.add_field(
            name="Catégorie des vocaux",
            value=f"<#{settings['voice_category_id']}>" if settings.get("voice_category_id") else "Celle du générateur",
            inline=True,
        )
        emb.add_field(name="Places par défaut", value=str(settings.get("voice_limit") or "illimité"), inline=True)
        emb.add_field(
            name="Modèle de nom",
            value=f"`{settings.get('voice_name_template') or TEMPVOICE_NAME_TEMPLATE}`",
            inline=True,
        )
        emb.add_field(
            name="Vocaux actifs",
            value=f"{len(rooms)}/{TEMPVOICE_MAX_ROOMS}",
            inline=True,
        )
        emb.add_field(name="\u200b", value="\u200b", inline=True)

        orphans = list(self.manager.candidate_channels(guild))
        if orphans:
            emb.add_field(
                name=f"{EMOJI['warning']} Salons non rattachés",
                value=truncate(
                    "Ces vocaux ressemblent à d'anciens vocaux temporaires mais ne sont plus "
                    "suivis par le bot :\n"
                    + "\n".join(f"• {channel.mention}" for channel in orphans[:10])
                    + "\n→ `/vocal rattacher` pour les remettre dans le système.",
                    1000,
                ),
                inline=False,
            )

        if rooms:
            lines = []
            for record in rooms[:15]:
                channel = guild.get_channel(int(record["channel_id"]))
                owner = f"<@{record['owner_id']}>"
                if channel is None:
                    lines.append(f"• *salon supprimé* · {owner}")
                    continue
                connected = sum(1 for m in getattr(channel, "members", []) if not m.bot)
                limit = int(record.get("limit") or 0)
                places = f"{connected}/{limit}" if limit else f"{connected}/∞"
                lines.append(
                    f"• {channel.mention} · {owner} · {places} · {room_state_label(record)}"
                )
            emb.add_field(name="Détail", value=truncate("\n".join(lines), 1000), inline=False)
        else:
            emb.add_field(name="Détail", value="*Aucun vocal actif pour le moment.*", inline=False)

        emb.add_field(
            name="Commandes",
            value=(
                "`/vocal installer` · créer / recréer le salon générateur\n"
                "`/vocal modele` · personnaliser le nom des vocaux\n"
                "`/vocal limite` · places par défaut\n"
                "`/vocal rattacher` · rattacher les vocaux détachés\n"
                "`/vocal nettoyer` · réparer panneaux et fiches orphelines\n"
                "`/vocal desactiver` · retirer complètement le système"
            ),
            inline=False,
        )
        emb.set_footer(text=FOOTER)
        await reply_ephemeral(interaction, emb)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="modele", description="Choisir le nom donné aux vocaux créés")
    @app_commands.describe(modele="Modèle du nom — variables : {user}, {username}, {count}")
    @is_staff()
    async def modele(self, interaction: discord.Interaction, modele: str) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return

        template = " ".join(modele.split()).strip()[:TEMPVOICE_NAME_MAX_LENGTH]
        if not template:
            await reply_ephemeral(interaction, error("Le modèle ne peut pas être vide."))
            return
        if "{" in template and "{user}" not in template and "{username}" not in template:
            await reply_ephemeral(
                interaction,
                error(
                    "Le modèle doit contenir `{user}`, `{username}` ou `{count}`.\n"
                    "Exemples : `Vocal de {user}`, `{user} · 🔊`, `Salon n°{count}`.",
                    title="Modèle invalide",
                ),
            )
            return

        settings = self.manager.config(interaction.guild.id)
        settings["voice_name_template"] = template
        self.bot.db.schedule_save(0.5)

        preview = format_room_name(template, interaction.user, 1)
        await reply_ephemeral(
            interaction,
            success(
                f"Nouveau modèle enregistré : `{template}`\n"
                f"Exemple pour toi : **{preview}**\n\n"
                "*Les salons déjà créés ne sont pas renommés.*",
                title="Modèle mis à jour",
            ),
        )

    # ------------------------------------------------------------------ #
    @app_commands.command(name="limite", description="Définir le nombre de places par défaut des vocaux")
    @app_commands.describe(places="0 pour illimité")
    @is_staff()
    async def limite(
        self, interaction: discord.Interaction, places: app_commands.Range[int, 0, TEMPVOICE_MAX_LIMIT]
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return

        settings = self.manager.config(interaction.guild.id)
        settings["voice_limit"] = int(places)
        self.bot.db.schedule_save(0.5)

        text = (
            "Les nouveaux vocaux seront **illimités**."
            if places == 0
            else f"Les nouveaux vocaux seront limités à **{places} place(s)**."
        )
        await reply_ephemeral(interaction, success(f"{text}\n*Les salons existants ne changent pas.*"))

    # ------------------------------------------------------------------ #
    @app_commands.command(name="nettoyer", description="Réparer les panneaux et supprimer les fiches orphelines")
    @is_staff()
    async def nettoyer(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        recovery = await self.manager.recover_guild(guild)
        removed = await self.manager.prune()

        repaired = 0
        for record in self.bot.db.guild_voice_rooms(guild.id):
            channel = guild.get_channel(int(record["channel_id"]))
            if channel is None:
                continue
            message_id = record.get("panel_message_id")
            exists = False
            if message_id:
                with contextlib.suppress(discord.HTTPException):
                    await channel.fetch_message(int(message_id))
                    exists = True
            if not exists:
                await self.manager.send_panel(channel, record)
                repaired += 1

        await interaction.followup.send(
            embed=success(
                f"Salons rattachés : **{recovery['adopted']}** (sur {recovery['scanned']} inspecté(s))\n"
                f"Fiches orphelines supprimées : **{removed}**\n"
                f"Panneaux republiés : **{repaired}**",
                title="Nettoyage terminé",
            ),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    @app_commands.command(
        name="rattacher",
        description="Rattacher au système les vocaux qui s'en sont détachés",
    )
    @is_staff()
    async def rattacher(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        hub = await self.manager.recover_hub(guild)
        if hub is None and self.manager.hub_id(guild.id) is None:
            await interaction.followup.send(
                embed=warning(
                    "Aucun salon générateur trouvé : lance d'abord `/vocal installer`.",
                    title="Système non installé",
                ),
                ephemeral=True,
            )
            return

        recovery = await self.manager.recover_guild(guild)
        lines = [
            f"• <#{record['channel_id']}> · <@{record['owner_id']}>"
            for record in recovery["records"][:10]
        ]

        await interaction.followup.send(
            embed=success(
                f"Salons rattachés : **{recovery['adopted']}** (sur {recovery['scanned']} inspecté(s))\n"
                + ("\n".join(lines) if lines else "\n*Aucun salon à rattacher.*"),
                title="Rattachement terminé",
            ),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    @app_commands.command(name="desactiver", description="Retirer le système de vocaux temporaires")
    @app_commands.describe(supprimer_salons="Supprimer aussi les vocaux actuellement ouverts")
    @is_staff()
    async def desactiver(
        self, interaction: discord.Interaction, supprimer_salons: bool = True
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return

        guild = interaction.guild
        settings = self.manager.config(guild.id)
        hub = self.manager.hub(guild)
        if hub is None and not settings.get("voice_hub_id"):
            await reply_ephemeral(
                interaction, warning("Le système n'est pas installé sur ce serveur.", title="Rien à faire")
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        deleted_rooms = 0
        if supprimer_salons:
            for record in list(self.bot.db.guild_voice_rooms(guild.id)):
                channel = guild.get_channel(int(record["channel_id"]))
                if channel is None:
                    self.bot.db.remove_voice_room(int(record["channel_id"]))
                    continue
                await self.manager.delete_room(channel, reason="Désactivation des vocaux temporaires")
                deleted_rooms += 1

        if hub is not None:
            with contextlib.suppress(discord.HTTPException):
                await hub.delete(reason=f"Désactivation par {interaction.user}")

        for key in ("voice_hub_id", "voice_category_id", "voice_name_template", "voice_limit"):
            settings[key] = None if key in {"voice_hub_id", "voice_category_id", "voice_name_template"} else 0
        self.bot.db.schedule_save(0.5)

        await interaction.followup.send(
            embed=success(
                "Le système de vocaux temporaires est désactivé.\n"
                f"Salons générateur supprimé · vocaux supprimés : **{deleted_rooms}**",
                title="Désactivé",
            ),
            ephemeral=True,
        )


# --------------------------------------------------------------------------- #
# Cog
# --------------------------------------------------------------------------- #
class TempVoice(commands.Cog):
    """Salons vocaux temporaires créés à la demande."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self.manager = TempVoiceManager(bot)
        bot.tempvoice = self.manager  # type: ignore[attr-defined]
        self.vocal = VocalGroup(self)
        self._pruned = False

    async def cog_unload(self) -> None:
        await self.manager.close()
        self.bot.tree.remove_command(self.vocal.name)
        if getattr(self.bot, "tempvoice", None) is self.manager:
            self.bot.tempvoice = None  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # Événements
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._pruned:
            return
        self._pruned = True
        try:
            await self.manager.prune()
        except Exception:  # pragma: no cover - jamais bloquant
            log.exception("Nettoyage des vocaux temporaires impossible")

        # Un redémarrage (ou un disque éphémère) ne doit pas « détacher » les
        # vocaux existants : on les rattache à partir de leur panneau.
        for guild in list(getattr(self.bot, "guilds", [])):
            try:
                report = await self.manager.recover_guild(guild)
                if report["adopted"]:
                    log.warning(
                        "%s vocal(aux) temporaire(s) rattaché(s) sur %s", report["adopted"], guild.name
                    )
            except Exception:  # pragma: no cover - jamais bloquant
                log.exception("Rattachement des vocaux temporaires impossible sur %s", guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        try:
            await self.manager.handle_voice_update(member, before, after)
        except Exception:  # pragma: no cover - un vocal ne doit jamais casser le bot
            log.exception("Erreur de gestion du vocal temporaire de %s", getattr(member, "id", "?"))

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        record = self.bot.db.voice_room(channel.id)
        if record is not None:
            self.manager.cancel_pending_delete(channel.id)
            self.bot.db.remove_voice_room(channel.id)
            log.info("Salon temporaire %s supprimé manuellement, fiche retirée", channel.id)
            return

        guild = getattr(channel, "guild", None)
        if guild is None:
            return
        settings = self.bot.db.guild(guild.id)
        if settings.get("voice_hub_id") == channel.id:
            settings["voice_hub_id"] = None
            self.bot.db.schedule_save(0.5)
            log.warning("Salon générateur supprimé sur %s : le système est inactif", guild.id)


async def setup(bot: "VesparaBot") -> None:
    cog = TempVoice(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.vocal, override=True)
    # Vue persistante : les boutons des panneaux restent actifs après redémarrage.
    bot.add_view(TempVoicePanel(bot))
