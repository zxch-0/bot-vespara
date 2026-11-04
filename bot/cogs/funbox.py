"""Commandes rigolotes : `/dire`, `/sondage`, `/duel`, `/ship`, `/pfc`, `/blague`…

Deux familles :

* **réservées au staff** — `/dire` (le bot parle, admin seulement), `/sondage` et
  `/citation`, qui publient un message visible par tout le monde ;
* **ouvertes à tous** — jauges (`/iq`, `/sus`, `/simp`, `/aura`, `/chaos`),
  `/ship`, `/duel`, `/pfc`, `/blague`, `/pique`, `/complimente`, `/horoscope`,
  `/calin`, `/baffe`, `/tapote`, `/pileouface` et `/de`.
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import is_server_admin, is_staff
from ..helpers import embed, error, reply_ephemeral, success, warning
from ..services.fun import (
    COMPLIMENTS,
    HOROSCOPE_SIGNS,
    JOKES,
    ROASTS,
    battle,
    clean_text,
    coinflip,
    gauge,
    normalize_sign,
    pick_from,
    pick_horoscope,
    roll,
    ship,
)
from ..ui.fun import (
    RpsView,
    action_embed,
    animate_battle,
    battle_embed,
    coin_embed,
    dice_embed,
    fun_menu_embed,
    gauge_embed,
    horoscope_embed,
    joke_embed,
    publish_poll,
    quote_embed,
    rps_embed,
    send_say,
    ship_embed,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..main import VesparaBot

log = logging.getLogger(__name__)

MAX_SAY_LENGTH = 1900
MAX_CITATION_LENGTH = 1500
ACCENT_CHOICES = [
    app_commands.Choice(name=label, value=value)
    for label, value in (
        ("Violet", "violet"),
        ("Nuit", "nuit"),
        ("Menthe", "menthe"),
        ("Or", "or"),
        ("Feu", "feu"),
        ("Océan", "ocean"),
        ("Rose", "rose"),
    )
]


def _text_channel(interaction: discord.Interaction, salon: Any | None) -> Any | None:
    """Salon textuel ciblé (`salon` ou salon courant), ou ``None`` s'il est invalide."""
    channel = salon or interaction.channel
    return channel if isinstance(channel, discord.TextChannel) else None


class FunBox(commands.Cog):
    """Le coin des bêtises du serveur."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self.rng = random.Random()

    # ================================================================== #
    # STAFF : le bot parle, sondages, citations
    # ================================================================== #
    @app_commands.command(
        name="dire",
        description="Faire dire un message au bot, visible par tout le monde (admin)",
    )
    @app_commands.describe(
        message="Ce que le bot doit dire",
        salon="Salon où parler (défaut : salon courant)",
        embed="Envoyer sous forme d'embed plutôt que de texte simple",
        epingler="Épingler le message envoyé",
        accent="Couleur de l'embed",
    )
    @app_commands.choices(accent=ACCENT_CHOICES)
    @app_commands.guild_only()
    @is_server_admin()
    async def dire(
        self,
        interaction: discord.Interaction,
        message: str,
        salon: discord.TextChannel | None = None,
        embed: bool = False,
        epingler: bool = False,
        accent: app_commands.Choice[str] | None = None,
    ) -> None:
        channel = _text_channel(interaction, salon)
        if channel is None:
            await reply_ephemeral(
                interaction, error("Choisis un salon textuel valide.", title="Salon invalide")
            )
            return

        text = clean_text(message)[:MAX_SAY_LENGTH]
        if not text:
            await reply_ephemeral(interaction, error("Le message est vide."))
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            sent = await send_say(
                channel,
                text,
                as_embed=embed,
                accent=accent.value if accent else "violet",
                pin=epingler,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error(
                    f"Je n'ai pas la permission d'écrire dans {channel.mention}.",
                    title="Permission refusée",
                ),
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(
                embed=error(f"Envoi impossible : `{exc}`", title="Échec"), ephemeral=True
            )
            return

        emb = success(
            f"Message envoyé dans {channel.mention} !\n"
            f"→ [Voir le message]({sent.jump_url})"
            + ("\n📌 Message épinglé." if epingler else ""),
            title="C'est dit !",
        )
        await interaction.followup.send(embed=emb, ephemeral=True)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="sondage", description="Créer un sondage public à réactions (staff)")
    @app_commands.describe(
        question="La question posée",
        choix1="Première option",
        choix2="Deuxième option",
        choix3="Troisième option (facultatif)",
        choix4="Quatrième option (facultatif)",
        salon="Salon où publier (défaut : salon courant)",
        multiple="Autoriser plusieurs votes par personne",
    )
    @app_commands.guild_only()
    @is_staff()
    async def sondage(
        self,
        interaction: discord.Interaction,
        question: str,
        choix1: str,
        choix2: str,
        choix3: str | None = None,
        choix4: str | None = None,
        salon: discord.TextChannel | None = None,
        multiple: bool = False,
    ) -> None:
        channel = _text_channel(interaction, salon)
        if channel is None:
            await reply_ephemeral(
                interaction, error("Choisis un salon textuel valide.", title="Salon invalide")
            )
            return

        options = [option for option in (choix1, choix2, choix3, choix4) if option]
        if len(options) < 2:
            await reply_ephemeral(
                interaction, error("Il faut au moins deux options.", title="Sondage incomplet")
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            message = await publish_poll(
                channel,
                question[:250],
                [option[:80] for option in options],
                author=interaction.user,
                multiple=multiple,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error(f"Je ne peux pas écrire dans {channel.mention}.", title="Permission refusée"),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success(
                f"Sondage publié dans {channel.mention} !\n→ [Voter]({message.jump_url})",
                title="Sondage en ligne",
            ),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    @app_commands.command(name="citation", description="Publier une citation mise en valeur (staff)")
    @app_commands.describe(
        texte="La citation (ou un message à citer avec « repondre_a »)",
        auteur="Nom affiché de l'auteur (défaut : toi)",
        salon="Salon où publier (défaut : salon courant)",
        repondre_a="Message à citer (le texte devient alors facultatif)",
    )
    @app_commands.guild_only()
    @is_staff()
    async def citation(
        self,
        interaction: discord.Interaction,
        texte: str | None = None,
        auteur: str | None = None,
        salon: discord.TextChannel | None = None,
        repondre_a: str | None = None,
    ) -> None:
        channel = _text_channel(interaction, salon)
        if channel is None:
            await reply_ephemeral(
                interaction, error("Choisis un salon textuel valide.", title="Salon invalide")
            )
            return

        content = clean_text(texte or "")
        label = auteur or getattr(interaction.user, "display_name", "Anonyme")

        # Raccourci : citer un message existant via son identifiant ou un lien.
        if repondre_a:
            message_id = repondre_a.strip().split("/")[-1]
            if not message_id.isdigit():
                await reply_ephemeral(
                    interaction,
                    error("Donne l'identifiant d'un message (ou son lien Discord)."),
                )
                return
            await interaction.response.defer(thinking=True, ephemeral=True)
            try:
                quoted = await channel.fetch_message(int(message_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                await interaction.followup.send(
                    embed=error("Message introuvable dans ce salon.", title="Introuvable"),
                    ephemeral=True,
                )
                return
            content = content or clean_text(quoted.content)
            label = auteur or getattr(quoted.author, "display_name", "Anonyme")
        else:
            await interaction.response.defer(thinking=True, ephemeral=True)

        if not content:
            await interaction.followup.send(
                embed=error("Ajoute un texte ou précise `repondre_a`.", title="Citation vide"),
                ephemeral=True,
            )
            return

        try:
            sent = await channel.send(
                embed=quote_embed(content[:MAX_CITATION_LENGTH], author_label=label, requester=interaction.user)
            )
        except discord.HTTPException:
            await interaction.followup.send(
                embed=error(f"Impossible d'écrire dans {channel.mention}.", title="Échec"),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=success(
                f"Citation publiée dans {channel.mention} !\n→ [Voir]({sent.jump_url})",
                title="Citation envoyée",
            ),
            ephemeral=True,
        )

    # ================================================================== #
    # TOUT LE MONDE : jauges
    # ================================================================== #
    async def _send_gauge(
        self, interaction: discord.Interaction, kind: str, membre: discord.Member | None
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        target = membre or interaction.user
        result = gauge(kind, interaction.guild.id, target.id)
        await reply_ephemeral(interaction, gauge_embed(result, target))

    @app_commands.command(name="iq", description="Mesurer (très sérieusement) le QI d'un membre")
    @app_commands.describe(membre="Membre à analyser (défaut : toi)")
    async def iq(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        await self._send_gauge(interaction, "iq", membre)

    @app_commands.command(name="sus", description="Calculer la suspicion d'un membre (Among Us style)")
    @app_commands.describe(membre="Membre à suspecter (défaut : toi)")
    async def sus(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        await self._send_gauge(interaction, "sus", membre)

    @app_commands.command(name="simp", description="Mesurer le niveau de simp d'un membre")
    @app_commands.describe(membre="Membre à analyser (défaut : toi)")
    async def simp(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        await self._send_gauge(interaction, "simp", membre)

    @app_commands.command(name="aura", description="Afficher l'aura mystique d'un membre")
    @app_commands.describe(membre="Membre à scanner (défaut : toi)")
    async def aura(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        await self._send_gauge(interaction, "aura", membre)

    @app_commands.command(name="chaos", description="Mesurer le chaos qu'un membre dégage")
    @app_commands.describe(membre="Membre à analyser (défaut : toi)")
    async def chaos(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        await self._send_gauge(interaction, "chaos", membre)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="ship", description="Calculer la compatibilité entre deux membres")
    @app_commands.describe(
        membre="Premier membre", membre2="Second membre (défaut : toi)"
    )
    async def ship_cmd(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        membre2: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return
        other = membre2 or interaction.user
        result = ship(interaction.guild.id, membre, other)
        await reply_ephemeral(interaction, ship_embed(result))

    # ------------------------------------------------------------------ #
    @app_commands.command(name="blague", description="Recevoir une blague (parfois douteuse, jamais méchante)")
    async def blague(self, interaction: discord.Interaction) -> None:
        await reply_ephemeral(interaction, joke_embed(pick_from(JOKES, self.rng)))

    @app_commands.command(name="pique", description="Envoyer une pique (gentille) à un membre")
    @app_commands.describe(membre="Victime de la pique (défaut : toi)")
    async def pique(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        target = membre or interaction.user
        emb = embed(
            title="🌶️ Pique bien envoyée",
            description=(
                f"{getattr(target, 'mention', target)} — {pick_from(ROASTS, self.rng)}\n\n"
                "*Rien de personnel, promis.* 🤝"
            ),
            color=0xEF4444,
            accent="feu",
            icon="🌶️",
        )
        await reply_ephemeral(interaction, emb)

    @app_commands.command(name="complimente", description="Faire un compliment (vrai, en vrai)")
    @app_commands.describe(membre="Membre à complimenter (défaut : toi)")
    async def complimente(
        self, interaction: discord.Interaction, membre: discord.Member | None = None
    ) -> None:
        target = membre or interaction.user
        emb = embed(
            title="💐 Compliment livré",
            description=(
                f"{getattr(target, 'mention', target)} — {pick_from(COMPLIMENTS, self.rng)}\n\n"
                "*Gratuit et sans arrière-pensée.* ✨"
            ),
            color=0x3BA55D,
            accent="menthe",
            icon="💐",
        )
        await reply_ephemeral(interaction, emb)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="horoscope", description="Ton horoscope (inventé, mais inspiré)")
    @app_commands.describe(signe="Ton signe du zodiaque (ex. lion, gemeaux, poissons)")
    async def horoscope(
        self, interaction: discord.Interaction, signe: str | None = None
    ) -> None:
        if interaction.guild is None:
            await reply_ephemeral(interaction, error("Commande utilisable uniquement sur un serveur."))
            return

        if signe is None:
            keys = list(HOROSCOPE_SIGNS)
            signe = keys[gauge("aura", interaction.guild.id, interaction.user.id).score % len(keys)]
            guessed = True
        else:
            guessed = False

        normalized = normalize_sign(signe)
        if normalized is None:
            signes = ", ".join(HOROSCOPE_SIGNS.values())
            await reply_ephemeral(
                interaction,
                error(f"Signe inconnu. Signes disponibles : {signes}", title="Signe introuvable"),
            )
            return

        text = pick_horoscope(normalized, interaction.guild.id, interaction.user.id)
        emb = horoscope_embed(HOROSCOPE_SIGNS[normalized], text, interaction.user)
        if guessed:
            emb.add_field(
                name="Signe deviné",
                value="Le staff peut te le confirmer. *(ou pas du tout)*",
                inline=False,
            )
        await reply_ephemeral(interaction, emb)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="duel", description="Défier un membre dans un combat épique (simulé)")
    @app_commands.describe(adversaire="Le membre à défier")
    async def duel(self, interaction: discord.Interaction, adversaire: discord.Member) -> None:
        if adversaire.bot and adversaire.id != getattr(self.bot.user, "id", None):
            await reply_ephemeral(interaction, error("Les autres bots refusent le combat. 🤖"))
            return
        if adversaire.id == interaction.user.id:
            await reply_ephemeral(
                interaction,
                warning(
                    "Te battre contre toi-même ? Techniquement, tu perdras quand même.",
                    title="Duel impossible",
                ),
            )
            return

        result = battle(interaction.user.display_name, adversaire.display_name, self.rng)
        await interaction.response.send_message(embed=battle_embed(result, step=1))
        message = await interaction.original_response()
        await animate_battle(message, result)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="pfc", description="Pierre-feuille-ciseaux : contre le bot ou un membre")
    @app_commands.describe(adversaire="Membre à défier (vide = le bot)")
    async def pfc(
        self, interaction: discord.Interaction, adversaire: discord.Member | None = None
    ) -> None:
        opponent = adversaire if adversaire and adversaire.id != interaction.user.id else None
        view = RpsView(interaction.user.id, opponent)
        emb = rps_embed(player=interaction.user, choice=None, bot_choice=None, outcome=None)
        if opponent is not None:
            emb.add_field(
                name="Duel en cours",
                value=f"{interaction.user.mention} 🆚 {opponent.mention}\nChacun clique sur un bouton.",
                inline=False,
            )
        await interaction.response.send_message(embed=emb, view=view)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="pileouface", description="Lancer une pièce (pile ou face)")
    async def pileouface(self, interaction: discord.Interaction) -> None:
        await reply_ephemeral(interaction, coin_embed(coinflip(self.rng), flipper=interaction.user))

    @app_commands.command(name="de", description="Lancer des dés (1 à 10 dés, 2 à 100 faces)")
    @app_commands.describe(faces="Nombre de faces par dé (défaut : 6)", nombre="Nombre de dés (défaut : 1)")
    async def de(
        self,
        interaction: discord.Interaction,
        faces: app_commands.Range[int, 2, 100] = 6,
        nombre: app_commands.Range[int, 1, 10] = 1,
    ) -> None:
        values = roll(int(faces), int(nombre), self.rng)
        await reply_ephemeral(interaction, dice_embed(values, int(faces), roller=interaction.user))

    # ------------------------------------------------------------------ #
    @app_commands.command(name="calin", description="Faire un câlin à quelqu'un")
    @app_commands.describe(membre="Destinataire du câlin")
    async def calin(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        await reply_ephemeral(interaction, action_embed("calin", interaction.user, membre))

    @app_commands.command(name="baffe", description="Mettre une baffe (symbolique) à quelqu'un")
    @app_commands.describe(membre="Destinataire de la baffe")
    async def baffe(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        if membre.id == interaction.user.id:
            await reply_ephemeral(
                interaction,
                warning("Te baffer toi-même ? C'est déjà assez dur comme ça.", title="Impossible"),
            )
            return
        await reply_ephemeral(interaction, action_embed("baffe", interaction.user, membre))

    @app_commands.command(name="tapote", description="Tapoter la tête de quelqu'un (pat pat)")
    @app_commands.describe(membre="Destinataire du « pat pat »")
    async def tapote(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        await reply_ephemeral(interaction, action_embed("tapote", interaction.user, membre))

    # ------------------------------------------------------------------ #
    @app_commands.command(name="fun", description="Voir toutes les commandes rigolotes du bot")
    async def fun(self, interaction: discord.Interaction) -> None:
        await reply_ephemeral(interaction, fun_menu_embed())


async def setup(bot: "VesparaBot") -> None:
    await bot.add_cog(FunBox(bot))


__all__ = ["FunBox"]
