"""Panneau de gestion des salons vocaux temporaires.

Tout se passe dans le **chat texte du salon vocal créé** : un embed et une série
de boutons persistants (ils fonctionnent encore après un redémarrage du bot).
Chaque panneau retrouve son salon grâce à l'interaction elle-même, si bien
qu'une seule vue persistante suffit pour tous les salons.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import discord

from ..constants import EMOJI, TEMPVOICE_MAX_LIMIT
from ..helpers import error, reply_ephemeral, success
from ..services.tempvoice import (
    TempVoiceManager,
    can_manage_room,
    room_state_label,
)
from .common import ConfirmView

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

PANEL_PREFIX = "vespara:tv"
NOT_A_ROOM = (
    "Impossible de rattacher ce salon au système de vocaux temporaires.\n"
    "Vérifie que le panneau appartient bien à ce salon, ou relance "
    "`/vocal installer` côté staff."
)


def get_manager(client: Any) -> TempVoiceManager | None:
    """Récupère le gestionnaire de vocaux attaché au bot."""
    return getattr(client, "tempvoice", None)


class TempVoicePanel(discord.ui.View):
    """Panneau persistant publié dans le chat de chaque salon temporaire."""

    def __init__(self, bot: "VesparaBot") -> None:
        super().__init__(timeout=None)
        self.bot = bot

    # ------------------------------------------------------------------ #
    # Résolution & contrôles
    # ------------------------------------------------------------------ #
    def _manager(self, interaction: discord.Interaction) -> TempVoiceManager | None:
        return get_manager(interaction.client) or get_manager(self.bot)

    async def _channel_and_record(
        self, interaction: discord.Interaction
    ) -> tuple[TempVoiceManager, Any, dict[str, Any]] | None:
        """Retrouve le salon et sa fiche — en rattachant le salon au besoin.

        Si la fiche a disparu (redémarrage, base éphémère…), le bot relit son
        panneau et les permissions du salon pour le remettre dans le système.
        """
        manager = self._manager(interaction)
        if manager is None:
            return None
        channel = interaction.channel
        if channel is None:
            channel = getattr(interaction.client, "get_channel", lambda _id: None)(interaction.channel_id)
        if channel is None:
            return None

        record = manager.room(channel)
        if record is None:
            record = await manager.adopt(channel, message=getattr(interaction, "message", None))
        if record is None:
            return None
        return manager, channel, record

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await self._channel_and_record(interaction) is None:
            await interaction.response.send_message(embed=error(NOT_A_ROOM), ephemeral=True)
            return False
        return True

    async def _owner_action(
        self, interaction: discord.Interaction
    ) -> tuple[TempVoiceManager, Any, dict[str, Any]] | None:
        """Comme `_channel_and_record`, mais vérifie en plus les droits de gestion."""
        resolved = await self._channel_and_record(interaction)
        if resolved is None:
            await interaction.response.send_message(embed=error(NOT_A_ROOM), ephemeral=True)
            return None
        manager, channel, record = resolved
        if not can_manage_room(self.bot, interaction.user, interaction.guild, record):
            owner_id = int(record.get("owner_id") or 0)
            await interaction.response.send_message(
                embed=error(
                    f"Seul le propriétaire du salon (<@{owner_id}>) — ou le staff — peut faire ça.\n"
                    "Si le propriétaire est parti, utilise **Récupérer**.",
                    title="Action réservée",
                ),
                ephemeral=True,
            )
            return None
        return manager, channel, record

    def _member_choices(self, interaction: discord.Interaction, channel: Any) -> list[discord.Member]:
        return [member for member in getattr(channel, "members", []) if not member.bot]

    # ------------------------------------------------------------------ #
    # Boutons
    # ------------------------------------------------------------------ #
    @discord.ui.button(
        label="Renommer", emoji=EMOJI["pencil"], style=discord.ButtonStyle.primary, custom_id=f"{PANEL_PREFIX}:rename", row=0
    )
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._owner_action(interaction)
        if resolved is None:
            return
        manager, channel, record = resolved
        await interaction.response.send_modal(RenameRoomModal(manager, channel, record))

    @discord.ui.button(
        label="Places", emoji=EMOJI["users"], style=discord.ButtonStyle.secondary, custom_id=f"{PANEL_PREFIX}:limit", row=0
    )
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._owner_action(interaction)
        if resolved is None:
            return
        manager, channel, record = resolved
        await interaction.response.send_modal(LimitRoomModal(manager, channel, record))

    @discord.ui.button(
        label="Verrouiller",
        emoji=EMOJI["lock"],
        style=discord.ButtonStyle.secondary,
        custom_id=f"{PANEL_PREFIX}:lock",
        row=0,
    )
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._owner_action(interaction)
        if resolved is None:
            return
        manager, channel, record = resolved
        if record.get("locked"):
            await reply_ephemeral(
                interaction, error("Le salon est déjà verrouillé.", title="Rien à faire")
            )
            return
        await manager.set_locked(channel, record, True)
        await reply_ephemeral(
            interaction,
            success(
                "Ton salon est **verrouillé** : plus personne ne peut le rejoindre.\n"
                "Utilise **Autoriser** pour ouvrir l'accès à quelqu'un en particulier.",
                title="Salon verrouillé",
            ),
        )

    @discord.ui.button(
        label="Déverrouiller",
        emoji=EMOJI["unlock"],
        style=discord.ButtonStyle.secondary,
        custom_id=f"{PANEL_PREFIX}:unlock",
        row=0,
    )
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._owner_action(interaction)
        if resolved is None:
            return
        manager, channel, record = resolved
        if not record.get("locked"):
            await reply_ephemeral(
                interaction, error("Le salon est déjà ouvert à tout le monde.", title="Rien à faire")
            )
            return
        await manager.set_locked(channel, record, False)
        await reply_ephemeral(
            interaction,
            success(
                "Ton salon est de nouveau **ouvert** : tout le monde peut le rejoindre.",
                title="Salon déverrouillé",
            ),
        )

    @discord.ui.button(
        label="Masquer",
        emoji=EMOJI["eye_off"],
        style=discord.ButtonStyle.secondary,
        custom_id=f"{PANEL_PREFIX}:hide",
        row=1,
    )
    async def hide(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._owner_action(interaction)
        if resolved is None:
            return
        manager, channel, record = resolved
        if record.get("hidden"):
            await reply_ephemeral(interaction, error("Le salon est déjà masqué.", title="Rien à faire"))
            return
        await manager.set_hidden(channel, record, True)
        await reply_ephemeral(
            interaction,
            success(
                "Ton salon est maintenant **privé** : il n'apparaît plus dans la liste des salons.\n"
                "Les membres autorisés et toi pouvez toujours le voir.",
                title="Salon masqué",
            ),
        )

    @discord.ui.button(
        label="Afficher",
        emoji=EMOJI["eye"],
        style=discord.ButtonStyle.secondary,
        custom_id=f"{PANEL_PREFIX}:show",
        row=1,
    )
    async def show(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._owner_action(interaction)
        if resolved is None:
            return
        manager, channel, record = resolved
        if not record.get("hidden"):
            await reply_ephemeral(interaction, error("Le salon est déjà visible.", title="Rien à faire"))
            return
        await manager.set_hidden(channel, record, False)
        await reply_ephemeral(
            interaction, success("Ton salon est de nouveau **visible** par tout le monde.", title="Salon affiché")
        )

    @discord.ui.button(
        label="Expulser",
        emoji=EMOJI["no_entry"],
        style=discord.ButtonStyle.danger,
        custom_id=f"{PANEL_PREFIX}:kick",
        row=1,
    )
    async def kick(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._owner_action(interaction)
        if resolved is None:
            return
        manager, channel, record = resolved
        members = self._member_choices(interaction, channel)
        if not members:
            await reply_ephemeral(
                interaction, error("Personne à expulser : ton salon est vide.", title="Salon vide")
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"{EMOJI['no_entry']} Expulser un membre",
                description=(
                    "Choisis la personne à sortir du salon.\n"
                    "*Elle sera déconnectée et ne pourra plus revenir tant que tu ne l'autorises pas.*"
                ),
                color=0xED4245,
            ),
            view=MemberSelectView(
                manager=manager,
                channel=channel,
                record=record,
                author_id=interaction.user.id,
                action="kick",
                placeholder="Qui veux-tu expulser ?",
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Autoriser",
        emoji=EMOJI["success"],
        style=discord.ButtonStyle.secondary,
        custom_id=f"{PANEL_PREFIX}:permit",
        row=1,
    )
    async def permit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._owner_action(interaction)
        if resolved is None:
            return
        manager, channel, record = resolved
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"{EMOJI['success']} Autoriser un membre",
                description=(
                    "Choisis la personne à autoriser.\n"
                    "*Elle pourra rejoindre ton salon même s'il est verrouillé ou privé.*"
                ),
                color=0x3BA55D,
            ),
            view=MemberSelectView(
                manager=manager,
                channel=channel,
                record=record,
                author_id=interaction.user.id,
                action="permit",
                placeholder="Qui veux-tu autoriser ?",
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Transférer",
        emoji=EMOJI["handshake"],
        style=discord.ButtonStyle.secondary,
        custom_id=f"{PANEL_PREFIX}:transfer",
        row=2,
    )
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._owner_action(interaction)
        if resolved is None:
            return
        manager, channel, record = resolved
        members = [m for m in self._member_choices(interaction, channel) if m.id != interaction.user.id]
        if not members:
            await reply_ephemeral(
                interaction, error("Il n'y a personne d'autre dans le salon.", title="Salon vide")
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"{EMOJI['handshake']} Transférer le salon",
                description=(
                    "Choisis le nouveau propriétaire.\n"
                    "*Tu perdras les droits de gestion du salon.*"
                ),
                color=0x8B5CF6,
            ),
            view=MemberSelectView(
                manager=manager,
                channel=channel,
                record=record,
                author_id=interaction.user.id,
                action="transfer",
                placeholder="Nouveau propriétaire…",
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Récupérer",
        emoji=EMOJI["crown"],
        style=discord.ButtonStyle.success,
        custom_id=f"{PANEL_PREFIX}:claim",
        row=2,
    )
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._channel_and_record(interaction)
        if resolved is None:
            await interaction.response.send_message(embed=error(NOT_A_ROOM), ephemeral=True)
            return
        manager, channel, record = resolved
        if int(record.get("owner_id") or 0) == interaction.user.id:
            await reply_ephemeral(
                interaction, error("Tu es déjà le propriétaire de ce salon.", title="Rien à faire")
            )
            return
        voice = getattr(interaction.user, "voice", None)
        if voice is None or getattr(voice, "channel", None) is None or voice.channel.id != channel.id:
            await reply_ephemeral(
                interaction,
                error("Rejoins d'abord le salon vocal pour pouvoir le récupérer.", title="Pas dans le salon"),
            )
            return
        try:
            await manager.claim(channel, record, interaction.user)
        except ValueError as exc:
            await reply_ephemeral(interaction, error(str(exc), title="Impossible"))
            return
        await reply_ephemeral(
            interaction,
            success(
                f"Tu es maintenant le propriétaire de **{channel.name}** 👑",
                title="Salon récupéré",
            ),
        )

    @discord.ui.button(
        label="Supprimer",
        emoji=EMOJI["trash"],
        style=discord.ButtonStyle.danger,
        custom_id=f"{PANEL_PREFIX}:delete",
        row=2,
    )
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._owner_action(interaction)
        if resolved is None:
            return
        manager, channel, record = resolved
        confirm = ConfirmView(author_id=interaction.user.id, confirm_label="Supprimer le salon")
        confirmed = await confirm.prompt(
            interaction,
            discord.Embed(
                title=f"{EMOJI['trash']} Supprimer le salon",
                description=(
                    f"Supprimer **{channel.name}** et déconnecter les membres présents ?\n\n"
                    "*Cette action est irréversible.*"
                ),
                color=0xED4245,
            ),
        )
        if not confirmed:
            return
        await interaction.followup.send(
            embed=success("Salon supprimé. À bientôt ! 👋", title="Salon fermé"), ephemeral=True
        )
        await manager.delete_room(channel, reason=f"Suppression demandée par {interaction.user}")

    @discord.ui.button(
        label="Actualiser",
        emoji=EMOJI["refresh"],
        style=discord.ButtonStyle.secondary,
        custom_id=f"{PANEL_PREFIX}:refresh",
        row=2,
    )
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        resolved = await self._channel_and_record(interaction)
        if resolved is None:
            await interaction.response.send_message(embed=error(NOT_A_ROOM), ephemeral=True)
            return
        manager, channel, record = resolved
        await interaction.response.defer(thinking=False)
        await manager.refresh_panel(channel, record)
        with contextlib.suppress(discord.HTTPException):
            await interaction.followup.send(
                embed=success(
                    f"Panneau à jour · état : {room_state_label(record)}", title="Actualisé"
                ),
                ephemeral=True,
            )


# --------------------------------------------------------------------------- #
# Modals
# --------------------------------------------------------------------------- #
class RenameRoomModal(discord.ui.Modal, title="Renommer le salon"):
    def __init__(self, manager: TempVoiceManager, channel: Any, record: dict[str, Any]) -> None:
        super().__init__(timeout=300)
        self.manager = manager
        self.channel = channel
        self.record = record
        self.name_input = discord.ui.TextInput(
            label="Nouveau nom",
            placeholder="Ex : Chill & musique 🎶",
            max_length=100,
            min_length=1,
            default=str(record.get("name") or getattr(channel, "name", ""))[:100],
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            name = await self.manager.rename(self.channel, self.record, str(self.name_input.value))
        except (ValueError, discord.HTTPException) as exc:
            await reply_ephemeral(
                interaction, error(f"Renommage impossible : {exc}", title="Échec")
            )
            return
        await reply_ephemeral(
            interaction, success(f"Le salon s'appelle maintenant **{name}**.", title="Salon renommé")
        )

    async def on_error(self, interaction: discord.Interaction, exc: Exception) -> None:
        await reply_ephemeral(interaction, error(f"Renommage impossible : `{exc}`"))


class LimitRoomModal(discord.ui.Modal, title="Limite de places"):
    def __init__(self, manager: TempVoiceManager, channel: Any, record: dict[str, Any]) -> None:
        super().__init__(timeout=300)
        self.manager = manager
        self.channel = channel
        self.record = record
        self.limit_input = discord.ui.TextInput(
            label=f"Nombre de places (0 à {TEMPVOICE_MAX_LIMIT})",
            placeholder="0 = illimité",
            max_length=2,
            min_length=1,
            default=str(int(record.get("limit") or 0)),
        )
        self.add_item(self.limit_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.limit_input.value).strip()
        if not raw.isdigit():
            await reply_ephemeral(
                interaction,
                error(f"Indique un nombre entier entre 0 et {TEMPVOICE_MAX_LIMIT}."),
            )
            return
        try:
            limit = await self.manager.set_limit(self.channel, self.record, int(raw))
        except discord.HTTPException as exc:
            await reply_ephemeral(interaction, error(f"Modification impossible : {exc}", title="Échec"))
            return
        text = "Le salon accepte de nouveau **toutes les places**." if limit == 0 else f"Le salon est limité à **{limit} place(s)**."
        await reply_ephemeral(interaction, success(text, title="Limite mise à jour"))

    async def on_error(self, interaction: discord.Interaction, exc: Exception) -> None:
        await reply_ephemeral(interaction, error(f"Modification impossible : `{exc}`"))


# --------------------------------------------------------------------------- #
# Sélecteur de membre (éphémère, non persistant)
# --------------------------------------------------------------------------- #
class MemberSelectView(discord.ui.View):
    def __init__(
        self,
        *,
        manager: TempVoiceManager,
        channel: Any,
        record: dict[str, Any],
        author_id: int,
        action: str,
        placeholder: str,
    ) -> None:
        super().__init__(timeout=120)
        self.manager = manager
        self.channel = channel
        self.record = record
        self.author_id = author_id
        self.action = action

        select = discord.ui.UserSelect(placeholder=placeholder, min_values=1, max_values=1)
        select.callback = self._on_select  # type: ignore[method-assign]
        self.select = select
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=error("Ce menu ne t'appartient pas."), ephemeral=True
            )
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        target_id = int(self.select.values[0])
        guild = interaction.guild
        member = guild.get_member(target_id) if guild is not None else None
        if member is None:
            await interaction.response.send_message(
                embed=error("Membre introuvable sur ce serveur."), ephemeral=True
            )
            return

        connected = {m.id for m in getattr(self.channel, "members", [])}
        try:
            if self.action == "kick":
                if target_id not in connected:
                    raise ValueError(f"{member.display_name} n'est pas dans ton salon.")
                await self.manager.kick(self.channel, self.record, member)
                text = f"{member.mention} a été **expulsé** du salon et ne peut plus le rejoindre."
                title = "Membre expulsé"
            elif self.action == "permit":
                await self.manager.permit(self.channel, self.record, member)
                text = f"{member.mention} peut désormais rejoindre ton salon."
                title = "Membre autorisé"
            elif self.action == "transfer":
                if target_id not in connected:
                    raise ValueError(f"{member.display_name} doit être dans le salon pour en devenir propriétaire.")
                await self.manager.transfer(self.channel, self.record, member)
                text = f"{member.mention} est le nouveau propriétaire du salon 👑"
                title = "Propriété transférée"
            else:  # pragma: no cover - garde-fou
                raise ValueError("Action inconnue.")
        except ValueError as exc:
            await interaction.response.send_message(embed=error(str(exc)), ephemeral=True)
            return
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                embed=error(f"Action impossible : {exc}", title="Échec"), ephemeral=True
            )
            return

        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            embed=success(text, title=title), view=self
        )
        self.stop()


__all__ = ["PANEL_PREFIX", "MemberSelectView", "TempVoicePanel", "get_manager"]
