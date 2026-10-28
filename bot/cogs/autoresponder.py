"""Réponses automatiques configurables par serveur (staff uniquement)."""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import is_staff
from ..constants import (
    AUTORESPONDER_MODES,
    COLOR,
    COLOR_INFO,
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
    truncate,
    warning,
)
from ..ui.common import ConfirmView
from ..ui.paginator import Paginator

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Correspondance des déclencheurs
# --------------------------------------------------------------------------- #
def match_response(content: str, response: dict) -> bool:
    """Indique si `content` déclenche `response`."""
    trigger = str(response.get("trigger") or "")
    if not trigger or not content:
        return False

    mode = str(response.get("mode") or "contains")
    case_sensitive = bool(response.get("case_sensitive", False))

    if mode == "regex":
        try:
            return re.search(trigger, content, 0 if case_sensitive else re.IGNORECASE) is not None
        except re.error:
            return False

    haystack = content if case_sensitive else content.casefold()
    needle = trigger if case_sensitive else trigger.casefold()

    if mode == "startswith":
        return haystack.lstrip().startswith(needle)
    if mode == "endswith":
        return haystack.rstrip().endswith(needle)
    if mode == "exact":
        return haystack.strip() == needle.strip()
    return needle in haystack


def _clean_reply(text: str) -> str:
    return truncate(text.strip(), 1900)


# --------------------------------------------------------------------------- #
# Autocomplétion
# --------------------------------------------------------------------------- #
async def response_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if interaction.guild is None:
        return []
    current = current.lower()
    items = interaction.client.db.autoresponses(interaction.guild.id)  # type: ignore[attr-defined]
    choices = []
    for item in items[:25]:
        label = truncate(f"#{item['id']} · {item['trigger']} · {AUTORESPONDER_MODES.get(item.get('mode', 'contains'), '')}", 100)
        if current in label.lower():
            choices.append(app_commands.Choice(name=label, value=str(item["id"])))
    return choices


# --------------------------------------------------------------------------- #
# Modal d'ajout
# --------------------------------------------------------------------------- #
class AddAutoresponseModal(discord.ui.Modal, title="Nouvelle réponse automatique"):
    def __init__(
        self,
        bot: "VesparaBot",
        *,
        mode: str,
        case_sensitive: bool,
        use_embed: bool,
    ) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.mode = mode
        self.case_sensitive = case_sensitive
        self.use_embed = use_embed

        self.trigger_input = discord.ui.TextInput(
            label="Déclencheur",
            placeholder="Ex : bonjour, !ip, bienvenue…",
            max_length=150,
            required=True,
        )
        self.reply_input = discord.ui.TextInput(
            label="Réponse du bot",
            placeholder="Texte envoyé automatiquement (markdown accepté)",
            style=discord.TextStyle.paragraph,
            max_length=1800,
            required=True,
        )
        self.add_item(self.trigger_input)
        self.add_item(self.reply_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return

        trigger = str(self.trigger_input.value).strip()
        reply = str(self.reply_input.value).strip()
        db = self.bot.db

        if len(trigger) < 2:
            await reply_ephemeral(
                interaction, error("Le déclencheur doit contenir au moins 2 caractères.")
            )
            return
        if not reply:
            await reply_ephemeral(interaction, error("La réponse ne peut pas être vide."))
            return
        if len(db.autoresponses(interaction.guild.id)) >= MAX_AUTORESPONSES:
            await reply_ephemeral(
                interaction,
                error(f"Limite atteinte : {MAX_AUTORESPONSES} réponses automatiques par serveur."),
            )
            return
        if db.find_autoreply(interaction.guild.id, trigger) is not None:
            await reply_ephemeral(
                interaction, error(f"Un déclencheur « {trigger} » existe déjà sur ce serveur.")
            )
            return
        if self.mode == "regex":
            try:
                re.compile(trigger)
            except re.error as exc:
                await reply_ephemeral(
                    interaction, error(f"Expression régulière invalide : `{exc}`")
                )
                return

        record = {
            "id": db.next_id(),
            "trigger": trigger,
            "reply": reply,
            "mode": self.mode,
            "case_sensitive": self.case_sensitive,
            "embed": self.use_embed,
            "enabled": True,
            "uses": 0,
            "created_by": interaction.user.id,
            "created_at": time.time(),
        }
        db.add_autoresponse(interaction.guild.id, record)

        description = (
            f"**#{record['id']}** · déclencheur `{discord.utils.escape_markdown(trigger)}`\n"
            f"Mode : **{AUTORESPONDER_MODES.get(self.mode, self.mode)}**"
            f"{' · sensible à la casse' if self.case_sensitive else ''}\n"
            f"Réponse : {truncate(reply, 300)}"
        )
        await reply_ephemeral(
            interaction, success(description, title="Réponse automatique créée")
        )

    async def on_error(self, interaction: discord.Interaction, exc: Exception) -> None:
        await reply_ephemeral(interaction, error(f"Le formulaire a échoué : `{exc}`"))


# --------------------------------------------------------------------------- #
# Groupe /autoresponder
# --------------------------------------------------------------------------- #
@app_commands.guild_only()
class AutoresponderGroup(
    app_commands.Group, name="autoresponder", description="Configurer les réponses automatiques"
):
    @app_commands.command(name="add", description="Ajouter une réponse automatique")
    @app_commands.describe(
        mode="Comment le déclencheur doit être détecté",
        casse="Le déclencheur est-il sensible à la casse ?",
        embed="Envoyer la réponse dans un embed",
    )
    @app_commands.choices(
        mode=[app_commands.Choice(name=label, value=key) for key, label in AUTORESPONDER_MODES.items()]
    )
    @is_staff()
    async def add(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str] | None = None,
        casse: bool = False,
        embed: bool = False,
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return
        if len(interaction.client.db.autoresponses(interaction.guild.id)) >= MAX_AUTORESPONSES:  # type: ignore[attr-defined]
            await reply_ephemeral(
                interaction,
                error(f"Limite atteinte : {MAX_AUTORESPONSES} réponses automatiques par serveur."),
            )
            return

        modal = AddAutoresponseModal(
            interaction.client,  # type: ignore[arg-type]
            mode=mode.value if mode else "contains",
            case_sensitive=casse,
            use_embed=embed,
        )
        await interaction.response.send_modal(modal)

    @app_commands.command(name="remove", description="Supprimer une réponse automatique")
    @app_commands.describe(reponse="Réponse à supprimer")
    @app_commands.autocomplete(reponse=response_autocomplete)
    @is_staff()
    async def remove(self, interaction: discord.Interaction, reponse: str) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return
        record = db.autoreply_by_id(interaction.guild.id, reponse)
        if record is None:
            await reply_ephemeral(interaction, error("Réponse automatique introuvable."))
            return
        db.remove_autoresponse(interaction.guild.id, reponse)
        await reply_ephemeral(
            interaction,
            success(
                f"La réponse `{discord.utils.escape_markdown(record['trigger'])}` a été supprimée.",
                title="Supprimée",
            ),
        )

    @app_commands.command(name="toggle", description="Activer ou désactiver une réponse automatique")
    @app_commands.describe(reponse="Réponse concernée")
    @app_commands.autocomplete(reponse=response_autocomplete)
    @is_staff()
    async def toggle(self, interaction: discord.Interaction, reponse: str) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return
        record = db.autoreply_by_id(interaction.guild.id, reponse)
        if record is None:
            await reply_ephemeral(interaction, error("Réponse automatique introuvable."))
            return
        record["enabled"] = not bool(record.get("enabled", True))
        db.schedule_save()
        state = "activée" if record["enabled"] else "désactivée"
        await reply_ephemeral(
            interaction,
            success(
                f"La réponse `{discord.utils.escape_markdown(record['trigger'])}` est maintenant **{state}**."
            ),
        )

    @app_commands.command(name="list", description="Lister les réponses automatiques du serveur")
    @is_staff()
    async def list_(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return

        items = db.autoresponses(interaction.guild.id)
        if not items:
            await reply_ephemeral(
                interaction,
                info("Aucune réponse automatique configurée. Ajoute-en une avec `/autoresponder add` !"),
            )
            return

        cooldown = int(db.guild(interaction.guild.id).get("autoresponder_cooldown") or 0)
        per_page = 4
        pages: list[discord.Embed] = []
        total_pages = (len(items) + per_page - 1) // per_page
        for page_index in range(total_pages):
            chunk = items[page_index * per_page : (page_index + 1) * per_page]
            emb = embed(
                title=f"{EMOJI['reply']} Réponses automatiques ({len(items)})",
                description=f"Cooldown actuel : **{cooldown} s** · page {page_index + 1}/{total_pages}",
                color=COLOR_INFO,
            )
            for record in chunk:
                state = "🟢 activée" if record.get("enabled", True) else "🔴 désactivée"
                emb.add_field(
                    name=f"#{record['id']} · {truncate(record['trigger'], 80)}",
                    value=(
                        f"{state} · mode **{AUTORESPONDER_MODES.get(record.get('mode', 'contains'), '?')}**"
                        f"{' · embed' if record.get('embed') else ''}\n"
                        f"↳ {truncate(record['reply'].replace(chr(10), ' '), 300)}\n"
                        f"`{record.get('uses', 0)} utilisation(s)`"
                    ),
                    inline=False,
                )
            pages.append(emb)

        view = Paginator(pages, author_id=interaction.user.id, show_close=False)
        await reply_ephemeral(interaction, pages[0], view=view)

    @app_commands.command(name="test", description="Tester quelles réponses se déclenchent sur un message")
    @app_commands.describe(message="Texte à tester")
    @is_staff()
    async def test(self, interaction: discord.Interaction, message: str) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return

        items = db.autoresponses(interaction.guild.id)
        matched = [record for record in items if record.get("enabled", True) and match_response(message, record)]
        if not matched:
            await reply_ephemeral(
                interaction,
                info(f"Aucune réponse ne se déclenche pour : « {truncate(message, 300)} »"),
            )
            return

        emb = embed(
            title=f"{EMOJI['sparkles']} {len(matched)} réponse(s) déclenchée(s)",
            description=f"Message testé : « {truncate(message, 300)} »",
            color=COLOR,
        )
        for record in matched[:10]:
            emb.add_field(
                name=f"#{record['id']} · {truncate(record['trigger'], 80)}",
                value=truncate(record["reply"], 400),
                inline=False,
            )
        await reply_ephemeral(interaction, emb)

    @app_commands.command(name="cooldown", description="Définir le délai minimum entre deux réponses")
    @app_commands.describe(secondes="Délai en secondes (0 pour désactiver)")
    @is_staff()
    async def cooldown(
        self, interaction: discord.Interaction, secondes: app_commands.Range[int, 0, 600]
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return
        db = interaction.client.db  # type: ignore[attr-defined]
        settings = db.guild(interaction.guild.id)
        settings["autoresponder_cooldown"] = int(secondes)
        db.schedule_save(0.5)
        await reply_ephemeral(
            interaction,
            success(
                f"Cooldown défini sur **{int(secondes)} s**."
                + (" Les réponses sont maintenant illimitées." if secondes == 0 else "")
            ),
        )

    @app_commands.command(name="reset", description="Supprimer toutes les réponses automatiques")
    @is_staff()
    async def reset(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Action disponible uniquement sur un serveur."))
            return
        items = db.autoresponses(interaction.guild.id)
        if not items:
            await reply_ephemeral(interaction, info("Il n'y a rien à supprimer."))
            return

        confirm = ConfirmView(author_id=interaction.user.id, confirm_label="Tout supprimer")
        accepted = await confirm.prompt(
            interaction,
            warning(
                f"Supprimer les **{len(items)}** réponses automatiques de ce serveur ?\n"
                "Cette action est irréversible.",
                title="Réinitialisation",
            ),
        )
        if not accepted:
            return
        db.clear_autoresponses(interaction.guild.id)
        await interaction.followup.send(
            embed=success("Toutes les réponses automatiques ont été supprimées."), ephemeral=True
        )


# --------------------------------------------------------------------------- #
# Cog + listener
# --------------------------------------------------------------------------- #
class Autoresponder(commands.Cog):
    """Écoute les messages et répond automatiquement selon la configuration."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self._cooldowns: dict[tuple[int, str], float] = {}
        self.autoresponder = AutoresponderGroup()

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.autoresponder.name)

    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not message.content:
            return
        if not self.bot.intents.message_content:
            return

        db = self.bot.db
        responses = db.autoresponses(message.guild.id)
        if not responses:
            return

        settings = db.guild(message.guild.id)
        cooldown = max(0, int(settings.get("autoresponder_cooldown") or 0))
        now = time.time()

        for record in responses:
            if not record.get("enabled", True):
                continue
            if not match_response(message.content, record):
                continue

            key = (message.guild.id, str(record["id"]))
            if cooldown and now - self._cooldowns.get(key, 0.0) < cooldown:
                continue
            self._cooldowns[key] = now
            if len(self._cooldowns) > 1000:
                cutoff = now - 3600
                self._cooldowns = {k: v for k, v in self._cooldowns.items() if v >= cutoff}

            record["uses"] = int(record.get("uses", 0)) + 1
            db.schedule_save(1.0)

            try:
                if record.get("embed"):
                    emb = discord.Embed(description=record["reply"], color=COLOR)
                    emb.set_footer(text=FOOTER)
                    await message.reply(
                        embed=emb,
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    await message.reply(
                        _clean_reply(record["reply"]),
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            except discord.Forbidden:
                log.warning("Impossible de répondre dans le salon %s (permissions)", message.channel)
            except discord.HTTPException as exc:
                log.warning("Échec de la réponse automatique : %s", exc)
            break


async def setup(bot: "VesparaBot") -> None:
    cog = Autoresponder(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.autoresponder, override=True)
