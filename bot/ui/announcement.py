"""Modal de rédaction et aperçu d'une annonce en message simple (pas d'embed)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from ..constants import EMOJI
from ..helpers import embed, error, reply_error, success

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot


@dataclass(slots=True)
class AnnouncementDraft:
    """Contenu brut qui sera envoyé tel quel par le bot."""

    content: str
    # Champs legacy conservés pour compatibilité (ancien système titre/couleur/image)
    title: str | None = None
    color: int | None = None
    image_url: str | None = None

    def __post_init__(self) -> None:
        # Compat : si l'ancien code passait title+content, on fusionne
        # title est ignoré pour l'envoi, mais on garde la compat.
        if self.title and not self.content:
            self.content = self.title
            self.title = None
        # Si les deux sont fournis (ancien embed), le contenu reste le principal

    def to_preview_embed(self, channel: discord.abc.GuildChannel | discord.TextChannel) -> discord.Embed:
        """Embed d'aperçu privé (ne sera jamais publié) — juste pour confirmer."""
        return embed(
            title=f"{EMOJI['megaphone']} Aperçu de l'annonce",
            description=self.content or "*Aucun contenu.*",
            color=0x8B5CF6,
        )

    # Compat : ancien code appelait to_embed(author) — on garde un alias
    # pour ne pas casser les tests externes qui importeraient encore l'ancienne API.
    def to_embed(self, author: discord.abc.User | None = None) -> discord.Embed:  # type: ignore[override]
        # Ancien comportement : titre + description
        title = self.title or "📢 Annonce"
        desc = self.content or "*Aucun contenu.*"
        # Si on a un title legacy, on l'utilise comme titre d'embed
        emb = embed(
            title=title,
            description=desc,
            color=self.color or 0x8B5CF6,
        )
        if self.image_url:
            emb.set_image(url=self.image_url)
        if author is not None:
            try:
                emb.set_author(name=author.display_name, icon_url=author.display_avatar.url)  # type: ignore[union-attr]
            except Exception:
                pass
        return emb


class AnnouncementModal(discord.ui.Modal):
    """Formulaire de rédaction : un seul champ, le message à envoyer."""

    def __init__(
        self,
        bot: "VesparaBot",
        *,
        channel: discord.TextChannel,
        mention_text: str | None,
        initial: AnnouncementDraft | None = None,
        preview_message: discord.Message | None = None,
    ) -> None:
        super().__init__(title="Modifier l'annonce" if initial else "Nouvelle annonce", timeout=600)
        self.bot = bot
        self.channel = channel
        self.mention_text = mention_text
        self.preview_message = preview_message

        self.content_input = discord.ui.TextInput(
            label="Message",
            placeholder="Tape le message que le bot doit envoyer… (markdown accepté)",
            style=discord.TextStyle.paragraph,
            max_length=2000,
            required=True,
            default=initial.content if initial else None,
        )
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        draft = AnnouncementDraft(content=str(self.content_input.value).strip())
        if not draft.content:
            await reply_error(interaction, "Le message ne peut pas être vide.")
            return

        preview = AnnouncementPreview(
            self.bot,
            draft=draft,
            channel=self.channel,
            mention_text=self.mention_text,
            author_id=interaction.user.id,
        )
        # Embed d'aperçu privé — montre le salon cible + le contenu
        preview_emb = embed(
            title=f"{EMOJI['megaphone']} Aperçu — salon {self.channel.mention}",
            description=draft.content,
            color=0x8B5CF6,
        )
        if self.mention_text:
            preview_emb.add_field(name="Mention", value=self.mention_text, inline=False)
        preview_emb.set_footer(text="Ce message sera envoyé tel quel par le bot (sans embed).")

        if self.preview_message is not None:
            try:
                await interaction.response.edit_message(
                    content=None,
                    embed=preview_emb,
                    view=preview,
                )
                return
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            embed=preview_emb,
            view=preview,
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, exc: Exception) -> None:
        await reply_error(interaction, f"Le formulaire a échoué : `{exc}`")


class AnnouncementPreview(discord.ui.View):
    """Aperçu privé avec Publication / Modification / Annulation — envoi en message brut."""

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

    def _full_content(self) -> str:
        if self.mention_text:
            return f"{self.mention_text}\n{self.draft.content}"
        return self.draft.content

    @discord.ui.button(label="Publier", emoji="📣", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        allowed_mentions = discord.AllowedMentions.none()
        if self.mention_text:
            allowed_mentions = discord.AllowedMentions(everyone=True, roles=True, users=True)

        full_content = self._full_content()

        # Discord limite à 2000 caractères par message — on le vérifie côté bot
        if len(full_content) > 2000:
            await reply_error(
                interaction,
                f"Le message est trop long ({len(full_content)} caractères, max 2000). Raccourcis-le.",
            )
            return

        try:
            message = await self.channel.send(
                content=full_content,
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
        jump_url = getattr(message, "jump_url", None)
        if jump_url:
            desc = f"Message envoyé dans {self.channel.mention} !\n→ [Voir le message]({jump_url})"
        else:
            desc = f"Message envoyé dans {self.channel.mention} !"
        await interaction.response.edit_message(
            content=None,
            embed=success(desc, title="Annonce envoyée"),
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Modifier", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        modal = AnnouncementModal(
            self.bot,
            channel=self.channel,
            mention_text=self.mention_text,
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
