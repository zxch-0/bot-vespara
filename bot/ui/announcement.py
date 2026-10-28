"""Modal de rédaction et aperçu d'une annonce."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from ..constants import COLOR_ANNOUNCE, EMOJI, FOOTER
from ..helpers import embed, error, reply_error, success

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot


@dataclass(slots=True)
class AnnouncementDraft:
    title: str
    content: str
    color: int = COLOR_ANNOUNCE
    image_url: str | None = None

    def to_embed(self, author: discord.abc.User) -> discord.Embed:
        emb = embed(
            title=self.title or "📢 Annonce",
            description=self.content or "*Aucun contenu.*",
            color=self.color,
            footer=FOOTER,
        )
        emb.set_author(name=author.display_name, icon_url=author.display_avatar.url)
        if self.image_url:
            emb.set_image(url=self.image_url)
        return emb


class AnnouncementModal(discord.ui.Modal):
    """Formulaire de rédaction (titre + contenu)."""

    def __init__(
        self,
        bot: "VesparaBot",
        *,
        channel: discord.TextChannel,
        mention_text: str | None,
        color: int,
        image_url: str | None,
        initial: AnnouncementDraft | None = None,
        preview_message: discord.Message | None = None,
    ) -> None:
        super().__init__(title="Modifier l'annonce" if initial else "Nouvelle annonce", timeout=600)
        self.bot = bot
        self.channel = channel
        self.mention_text = mention_text
        self.color = color
        self.image_url = image_url
        self.preview_message = preview_message

        self.title_input = discord.ui.TextInput(
            label="Titre",
            placeholder="Ex : Soirée jeux ce samedi !",
            max_length=200,
            required=True,
            default=initial.title if initial else None,
        )
        self.content_input = discord.ui.TextInput(
            label="Contenu",
            placeholder="Décris l'annonce… (le markdown Discord est accepté)",
            style=discord.TextStyle.paragraph,
            max_length=3800,
            required=True,
            default=initial.content if initial else None,
        )
        self.add_item(self.title_input)
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        draft = AnnouncementDraft(
            title=str(self.title_input.value).strip(),
            content=str(self.content_input.value).strip(),
            color=self.color,
            image_url=self.image_url,
        )
        preview = AnnouncementPreview(
            self.bot,
            draft=draft,
            channel=self.channel,
            mention_text=self.mention_text,
            author_id=interaction.user.id,
        )
        emb = draft.to_embed(interaction.user)

        if self.preview_message is not None:
            try:
                await interaction.response.edit_message(
                    content=f"{EMOJI['info']} Aperçu — salon {self.channel.mention}",
                    embed=emb,
                    view=preview,
                )
                return
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            content=f"{EMOJI['info']} Aperçu — salon {self.channel.mention}",
            embed=emb,
            view=preview,
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, exc: Exception) -> None:
        await reply_error(interaction, f"Le formulaire a échoué : `{exc}`")


class AnnouncementPreview(discord.ui.View):
    """Aperçu privé avec Publication / Modification / Annulation."""

    def __init__(
        self,
        bot: "VesparaBot",
        *,
        draft: AnnouncementDraft,
        channel: discord.TextChannel,
        mention_text: str | None,
        author_id: int,
        timeout: float = 900.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.draft = draft
        self.channel = channel
        self.mention_text = mention_text
        self.author_id = author_id

    # ------------------------------------------------------------------ #
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=error("Cet aperçu ne t'appartient pas."), ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Publier", emoji="📣", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        allowed_mentions = discord.AllowedMentions.none()
        if self.mention_text:
            allowed_mentions = discord.AllowedMentions(everyone=True, roles=True, users=True)

        try:
            message = await self.channel.send(
                content=self.mention_text,
                embed=self.draft.to_embed(interaction.user),
                allowed_mentions=allowed_mentions,
            )
        except discord.Forbidden:
            await reply_error(
                interaction,
                f"Je n'ai pas la permission d'écrire dans {self.channel.mention}.",
            )
            return
        except discord.HTTPException as exc:
            await reply_error(interaction, f"Discord a refusé l'envoi : `{exc}`")
            return

        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            content=None,
            embed=success(
                f"Annonce publiée dans {self.channel.mention} !\n"
                f"→ [Voir le message]({message.jump_url})",
                title="Annonce envoyée",
            ),
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Modifier", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        modal = AnnouncementModal(
            self.bot,
            channel=self.channel,
            mention_text=self.mention_text,
            color=self.draft.color,
            image_url=self.draft.image_url,
            initial=self.draft,
            preview_message=interaction.message,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Annuler", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(
            content=None,
            embed=embed(
                title=f"{EMOJI['warning']} Annonce annulée",
                description="Aucun message n'a été publié.",
                color=0x6B7280,
            ),
            view=None,
        )
