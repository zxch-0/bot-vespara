"""Point d'entrée du bot Discord Vespara."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import platform
import signal
import sys
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from . import __version__
from .checks import AdminOnly, StaffOnly
from .cogs import EXTENSIONS
from .config import Settings, load_settings
from .constants import (
    COLOR,
    EMOJI,
    FOOTER,
    STAFF_COMMAND_ROOTS,
)
from .database import Database
from .helpers import embed, error, info, reply_ephemeral, utcnow
from .ui.menu import MenuView
from .web import StatusServer

log = logging.getLogger(__name__)


class VesparaBot(commands.Bot):
    """Bot principal : charge les cogs, synchronise les commandes, expose le web."""

    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # indispensable pour l'auto-responder
        intents.members = True  # arriver à résoudre les rôles des membres

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
            activity=discord.Game(name="/menu · Vespara"),
            status=discord.Status.online,
        )
        self.settings = settings
        self.db = Database(settings.database_path)
        self.started_at = utcnow()
        self.web = StatusServer(self)
        self.giveaway_manager: Any = None  # injecté par le cog giveaways
        self.tempvoice: Any = None  # injecté par le cog tempvoice
        self.economy: Any = None  # injecté par le cog economy
        self._startup_logged = False

    # ------------------------------------------------------------------ #
    # Propriétés utilitaires
    # ------------------------------------------------------------------ #
    @property
    def uptime(self) -> float:
        return max(0.0, (utcnow() - self.started_at).total_seconds())

    @property
    def latency_ms(self) -> int:
        """Latence websocket en ms — `0` tant que le heartbeat n'a pas répondu."""
        latency = self.latency
        if latency != latency or latency <= 0:  # NaN / non connecté
            return 0
        return round(latency * 1000)

    @property
    def memory_usage(self) -> float:
        """Mémoire résidente du process (Mo) — 0 si indisponible."""
        try:
            import resource

            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except Exception:  # pragma: no cover - systèmes sans resource
            return 0.0

    @property
    def command_count(self) -> int:
        """Nombre total de commandes, sous-commandes incluses."""
        return sum(1 for _ in self.tree.walk_commands())

    @property
    def staff_permissions(self) -> discord.Permissions:
        """Permission utilisée pour masquer les commandes staff."""
        permission = self.settings.staff_permission
        if permission == "administrator":
            return discord.Permissions(administrator=True)
        return discord.Permissions(**{permission: True})

    # ------------------------------------------------------------------ #
    # Démarrage
    # ------------------------------------------------------------------ #
    async def setup_hook(self) -> None:
        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
                log.debug("Extension chargée : %s", extension)
            except Exception:
                log.exception("Impossible de charger l'extension %s", extension)

        # Vue persistante du panneau /menu (boutons toujours fonctionnels)
        self.add_view(MenuView(self))

        self.apply_command_visibility()
        self.tree.on_error = self.on_app_command_error

        await self.sync_commands()
        await self.web.start()
        self._install_signal_handlers()

    def apply_command_visibility(self) -> None:
        """Applique la permission de visibilité configurée aux commandes staff."""
        permissions = self.staff_permissions
        for root in STAFF_COMMAND_ROOTS:
            command = self.tree.get_command(root)
            if command is None:
                log.warning("Commande staff introuvable : /%s", root)
                continue
            command.default_permissions = permissions  # type: ignore[union-attr]
        log.info(
            "Commandes staff masquées derrière la permission « %s »",
            self.settings.staff_permission_label,
        )

        staffrole = self.tree.get_command("staffrole")
        if staffrole is not None:
            staffrole.default_permissions = discord.Permissions(administrator=True)  # type: ignore[union-attr]

    async def sync_commands(self) -> None:
        """Synchronise les slash commands (serveur de test prioritaire)."""
        scope = self.settings.command_scope
        guild_id = self.settings.guild_id

        try:
            if guild_id and scope in {"guild", "both"}:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("%s commande(s) synchronisée(s) sur le serveur %s", len(synced), guild_id)

            if scope in {"global", "both"} or not guild_id:
                synced = await self.tree.sync()
                log.info("%s commande(s) synchronisée(s) globalement", len(synced))
        except discord.HTTPException as exc:
            log.error("Synchronisation des commandes impossible : %s", exc)
            log.error(
                "Vérifie que le bot a bien le scope `applications.commands` et qu'il est invité "
                "sur le serveur."
            )

    def _install_signal_handlers(self) -> None:
        """Arrêt propre sur SIGTERM (Render) et SIGINT."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover
            return

        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, ValueError, RuntimeError):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.close()))

    # ------------------------------------------------------------------ #
    # Événements
    # ------------------------------------------------------------------ #
    async def on_ready(self) -> None:
        if self._startup_logged:
            log.info("Reconnexion à Discord en tant que %s", self.user)
        else:
            self._startup_logged = True
            log.info("=" * 62)
            log.info("%s v%s connecté en tant que %s", self.settings.brand, __version__, self.user)
            log.info("Serveurs : %s · Commandes : %s", len(self.guilds), self.command_count)
            log.info("Config : %s", self.settings.describe())
            if not self.intents.message_content:
                log.warning(
                    "L'intent « Message Content » est désactivé : l'auto-responder ne "
                    "fonctionnera pas. Active-le dans le portail développeur Discord."
                )
            if not self.settings.staff_role_id:
                log.warning(
                    "Aucun STAFF_ROLE_ID configuré : définis le rôle staff avec /staffrole "
                    "ou la variable d'environnement STAFF_ROLE_ID."
                )
            log.info("=" * 62)

        with contextlib.suppress(discord.HTTPException):
            # Présence tournante : un peu de vie sur la page du serveur.
            activities = (
                discord.Game(name="/menu · Vespara"),
                discord.Activity(type=discord.ActivityType.watching, name=f"{len(self.guilds)} serveur(s)"),
                discord.Activity(type=discord.ActivityType.listening, name="/eco daily 🪙"),
                discord.Activity(type=discord.ActivityType.playing, name="au casino 🎲"),
            )
            self._presence_index = (getattr(self, "_presence_index", 0) + 1) % len(activities)
            await self.change_presence(
                activity=activities[self._presence_index], status=discord.Status.online
            )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Message de bienvenue dans le premier salon disponible."""
        log.info("Nouveau serveur : %s (%s)", guild.name, guild.id)
        target = guild.system_channel
        if target is None or not target.permissions_for(guild.me).send_messages:
            target = next(
                (
                    channel
                    for channel in guild.text_channels
                    if channel.permissions_for(guild.me).send_messages
                ),
                None,
            )
        if target is None:
            return

        emb = embed(
            title=f"{EMOJI['wave']} Merci de m'avoir ajouté sur {guild.name} !",
            description=(
                "Je gère les **giveaways**, les **annonces**, les **réponses automatiques**, "
                "les **vocaux temporaires**, l'**économie avec niveaux et boutique** et même "
                "un **casino** — le tout derrière un **menu** clair.\n\n"
                "**Pour commencer**\n"
                "• `/menu` — afficher le menu du serveur\n"
                "• `/staffrole` — définir le rôle staff (administrateur)\n"
                "• `/config voir` — vérifier la configuration\n"
                "• `/vocal installer` — activer les vocaux personnels\n"
                "• `/eco-admin article-ajouter` — remplir la boutique\n"
                "• `/eco-admin recompense` — rôles débloqués par niveau\n\n"
                "*Les commandes de gestion sont réservées au rôle staff.*"
            ),
            color=COLOR,
            thumbnail=guild.icon.url if guild.icon else None,
        )
        emb.set_footer(text=FOOTER)
        try:
            await target.send(embed=emb)
        except discord.HTTPException:
            log.debug("Message de bienvenue impossible sur %s", guild.id)

    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: app_commands.Command | app_commands.ContextMenu
    ) -> None:
        """Journalise les commandes staff dans le salon de logs (si configuré)."""
        if not self.settings.log_channel_id:
            return
        root = command.qualified_name.split()[0]
        if root not in STAFF_COMMAND_ROOTS:
            return

        channel = self.get_channel(self.settings.log_channel_id)
        if channel is None or not hasattr(channel, "send"):
            return

        emb = embed(
            title=f"{EMOJI['gear']} Commande staff",
            description=f"{interaction.user.mention} a utilisé **/{command.qualified_name}**",
            color=COLOR,
        )
        emb.add_field(name="Salon", value=interaction.channel.mention if interaction.channel else "—", inline=True)
        emb.add_field(name="Serveur", value=interaction.guild.name if interaction.guild else "MP", inline=True)
        emb.set_footer(text=FOOTER)
        with contextlib.suppress(discord.HTTPException):
            await channel.send(embed=emb)  # type: ignore[union-attr]

    # ------------------------------------------------------------------ #
    # Gestion des erreurs de commandes
    # ------------------------------------------------------------------ #
    async def on_app_command_error(
        self, interaction: discord.Interaction, exception: app_commands.AppCommandError
    ) -> None:
        original: BaseException = getattr(exception, "original", exception)

        if isinstance(original, StaffOnly):
            await reply_ephemeral(
                interaction,
                error(
                    "Cette commande est réservée au **staff** du serveur.\n"
                    "Si tu penses avoir les droits, demande à un administrateur de vérifier "
                    "`/staffrole`.",
                    title="Accès refusé",
                ),
            )
            return

        if isinstance(original, AdminOnly):
            await reply_ephemeral(
                interaction,
                error("Cette commande est réservée aux **administrateurs** du serveur."),
            )
            return

        if isinstance(original, app_commands.NoPrivateMessage):
            await reply_ephemeral(
                interaction, error("Cette commande n'est pas disponible en message privé.")
            )
            return

        if isinstance(original, app_commands.MissingPermissions):
            missing = ", ".join(original.missing_permissions)
            await reply_ephemeral(
                interaction, error(f"Il me manque les permissions suivantes : `{missing}`.")
            )
            return

        if isinstance(original, app_commands.BotMissingPermissions):
            missing = ", ".join(original.missing_permissions)
            await reply_ephemeral(
                interaction,
                error(
                    f"Je n'ai pas les permissions nécessaires pour cette action : `{missing}`.\n"
                    "Ajoute-les à mon rôle puis réessaie."
                ),
            )
            return

        if isinstance(original, app_commands.CommandOnCooldown):
            await reply_ephemeral(
                interaction,
                info(f"Doucement ! Réessaie dans **{original.retry_after:.1f} s**."),
            )
            return

        if isinstance(original, discord.Forbidden):
            await reply_ephemeral(
                interaction,
                error(
                    "Discord m'a refusé l'action (permissions insuffisantes ou hiérarchie des rôles)."
                ),
            )
            return

        log.error(
            "Erreur dans la commande /%s",
            getattr(exception, "command", None).qualified_name
            if getattr(exception, "command", None)
            else "?",
            exc_info=original,
        )
        await reply_ephemeral(
            interaction,
            error(
                "Une erreur inattendue s'est produite. Réessaie dans un instant ; "
                "si le problème persiste, préviens l'équipe."
            ),
        )

    # ------------------------------------------------------------------ #
    # Arrêt
    # ------------------------------------------------------------------ #
    async def close(self) -> None:
        log.info("Arrêt du bot…")
        with contextlib.suppress(Exception):
            await self.web.stop()
        with contextlib.suppress(Exception):
            await self.db.close()
        await super().close()


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #
def configure_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)

    log.info("Démarrage de %s v%s", settings.brand, __version__)
    log.info("Python %s · discord.py %s", platform.python_version(), discord.__version__)

    if not settings.is_configured:
        log.error(
            "Aucun token Discord trouvé. Définis la variable d'environnement DISCORD_TOKEN "
            "(voir .env.example)."
        )
        log.error("Sur Render : Dashboard → Environment → Add Environment Variable.")
        sys.exit(1)

    bot = VesparaBot(settings)
    try:
        bot.run(settings.token, log_handler=None)
    except discord.LoginFailure:
        log.error(
            "Connexion refusée : le token est invalide ou a été réinitialisé. "
            "Régénère-le dans le portail développeur Discord."
        )
        sys.exit(1)
    except discord.PrivilegedIntentsRequired as exc:
        log.error(
            "Intents privilégiés manquants (%s). Active « Message Content Intent » et "
            "« Server Members Intent » dans l'onglet Bot du portail développeur Discord.",
            exc,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Arrêt demandé (Ctrl+C).")
    except Exception:
        log.exception("Le bot s'est arrêté sur une erreur inattendue.")
        sys.exit(1)


if __name__ == "__main__":
    run()
