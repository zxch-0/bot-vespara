"""Logique pure des commandes rigolotes (aucun appel Discord ici).

Tout ce qui peut être testé sans réseau vit dans ce module :

* jauges déterministes (`/iq`, `/sus`, `/simp`, `/aura`) : un membre obtient
  toujours le même score, ce qui rend les blagues cohérentes entre deux appels ;
* `/ship` : compatibilité amoureuse, elle aussi stable dans le temps ;
* ressources texte (blagues, piques, compliments, horoscopes) ;
* `/duel` : simulation de combat tour par tour ;
* `/pfc` : pierre-feuille-ciseaux ;
* `/de`, `/pileouface` : hasard simple.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Iterable


# --------------------------------------------------------------------------- #
# Hasard déterministe (même membre = même score)
# --------------------------------------------------------------------------- #
def stable_score(*parts: Any, low: int = 0, high: int = 100) -> int:
    """Score stable entre `low` et `high` dérivé des `parts` fournies.

    Utilise un hachage (et non `hash()`, qui change à chaque démarrage) pour que
    « ton QI » reste le même d'un redémarrage du bot à l'autre.
    """
    if high <= low:
        return low
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return low + value % (high - low + 1)


def ratio_from_score(score: int, maximum: int = 100) -> float:
    if maximum <= 0:
        return 0.0
    return min(1.0, max(0.0, score / maximum))


# --------------------------------------------------------------------------- #
# Nettoyage de texte (utilisé par /dire et /citation)
# --------------------------------------------------------------------------- #
_CONTROL_CHARS_RE = None


def clean_text(raw: str) -> str:
    """Nettoie un texte saisi : retire les caractères invisibles et les espaces superflus.

    Les mentions sont neutralisées côté envoi (`AllowedMentions.none()`), ce qui
    évite qu'un `/dire` puisse pinguer tout le serveur.
    """
    global _CONTROL_CHARS_RE
    if _CONTROL_CHARS_RE is None:  # pragma: no cover - initialisation unique
        import re

        _CONTROL_CHARS_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
    text = _CONTROL_CHARS_RE.sub("", str(raw or ""))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


# --------------------------------------------------------------------------- #
# Jauges rigolotes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Gauge:
    """Résultat d'une jauge comique (`/iq`, `/simp`…)."""

    kind: str
    score: int
    maximum: int
    title: str
    emoji: str
    verdict: str
    comment: str

    @property
    def ratio(self) -> float:
        return ratio_from_score(self.score, self.maximum)

    @property
    def label(self) -> str:
        return f"{self.score} / {self.maximum}"


# Ordre = du plus bas au plus haut ; on choisit le verdict par palier.
IQ_VERDICTS: tuple[tuple[int, str, str], ...] = (
    (20, "🪨 Caillou certifié", "Tu as réussi à perdre un débat contre un caillou. Bravo."),
    (40, "🍞 Pain de mie", "Pas grave : la moyenne du serveur est basse aussi."),
    (60, "🧠 Esprit normal", "Ni génie ni catastrophe. Le juste milieu, quoi."),
    (80, "🚀 Cerveau turbo", "Tu réfléchis plus vite que ton ombre. Impressionnant."),
    (95, "🧬 Alien", "Les scientifiques aimeraient te poser deux ou trois questions."),
    (101, "🌟 Galaxie", "Ton cerveau a sa propre météo. On te respecte."),
)

SIMPLY_VERDICTS: tuple[tuple[int, str, str], ...] = (
    (20, "🧊 De marbre", "Tu ne simpes pas. Tu es un roc. Un roc froid."),
    (40, "😐 Raisonnable", "Tu gardes la tête froide… pour l'instant."),
    (60, "😳 À surveiller", "Ça commence à devenir suspect, très cher."),
    (80, "💘 Simp confirmé", "Tu réponds dans les 3 secondes, on t'a vu."),
    (101, "🫠 Simp légendaire", "Ton cœur a un abonnement premium chez cette personne."),
)

SUS_VERDICTS: tuple[tuple[int, str, str], ...] = (
    (20, "😇 Innocent", "Trop innocent. C'est louche."),
    (45, "🤨 Suspect", "Il y a un petit quelque chose… mais ça va."),
    (70, "🕵️ Très sus", "On va garder un œil sur toi, discrètement."),
    (90, "🚨 AMONG US", "Imposteur repéré. Éjection immédiate (non)."),
    (101, "👽 Extra-terrestre", "Tu viens clairement d'une autre planète."),
)

AURA_VERDICTS: tuple[tuple[int, str, str], ...] = (
    (20, "🌫️ Aura de brouillard", "Personne ne t'a vu arriver. Ni partir."),
    (45, "🍃 Aura chill", "Ni trop, ni trop peu : la vibe est correcte."),
    (70, "🔥 Aura chaude", "Tu rentres dans un salon, la température monte."),
    (90, "👑 Aura royale", "Le serveur s'incline. Littéralement."),
    (101, "🌌 Aura cosmique", "Tu es une constellation à toi tout seul."),
)

CHAOS_VERDICTS: tuple[tuple[int, str, str], ...] = (
    (20, "🧸 Calme plat", "Tu es le membre le plus prévisible du serveur."),
    (45, "🎈 Petite folie", "Tu oses dire bonjour en majuscules. Fou."),
    (70, "🎪 Chaos contrôlé", "Le chaos te suit, mais il met sa ceinture."),
    (90, "🌪️ Tempête", "Les logs du serveur tremblent quand tu te connectes."),
    (101, "💥 Big Bang", "Tu es l'origine de 3 redémarrages du bot. Bravo."),
)

GAUGE_KINDS: dict[str, dict[str, Any]] = {
    "iq": {
        "title": "Quotient intellectuel",
        "emoji": "🧠",
        "maximum": 200,
        "verdicts": IQ_VERDICTS,
        "range": (20, 200),
    },
    "simp": {
        "title": "Niveau de simp",
        "emoji": "💘",
        "maximum": 100,
        "verdicts": SIMPLY_VERDICTS,
        "range": (0, 100),
    },
    "sus": {
        "title": "Suspicion",
        "emoji": "🕵️",
        "maximum": 100,
        "verdicts": SUS_VERDICTS,
        "range": (0, 100),
    },
    "aura": {
        "title": "Aura",
        "emoji": "✨",
        "maximum": 100,
        "verdicts": AURA_VERDICTS,
        "range": (0, 100),
    },
    "chaos": {
        "title": "Niveau de chaos",
        "emoji": "🌪️",
        "maximum": 100,
        "verdicts": CHAOS_VERDICTS,
        "range": (0, 100),
    },
}


def pick_verdict(kind: str, score: int) -> tuple[str, str]:
    """Choisit (verdict, commentaire) pour un score donné."""
    config = GAUGE_KINDS.get(kind)
    if config is None:
        return ("❓ Inconnu", "Aucune idée de ce que ça veut dire.")
    for threshold, verdict, comment in config["verdicts"]:
        if score < threshold:
            return verdict, comment
    return config["verdicts"][-1][1], config["verdicts"][-1][2]


def gauge(kind: str, guild_id: int, user_id: int) -> Gauge:
    """Jauge stable d'un membre (le même membre obtient toujours le même score)."""
    config = GAUGE_KINDS.get(kind)
    if config is None:
        raise ValueError(f"Jauge inconnue : {kind}")
    low, high = config["range"]
    score = stable_score("gauge", kind, guild_id, user_id, low=low, high=high)
    verdict, comment = pick_verdict(kind, score)
    return Gauge(
        kind=kind,
        score=score,
        maximum=int(config["maximum"]),
        title=str(config["title"]),
        emoji=str(config["emoji"]),
        verdict=verdict,
        comment=comment,
    )


# --------------------------------------------------------------------------- #
# /ship
# --------------------------------------------------------------------------- #
SHIP_VERDICTS: tuple[tuple[int, str, str], ...] = (
    (10, "💔 Aucune chance", "Même le bot n'y croit pas. Passe à autre chose."),
    (25, "🥶 Froid polaire", "Vous êtes dans deux galaxies différentes."),
    (40, "🤔 À travailler", "Il y a une étincelle… mais elle est mouillée."),
    (55, "🙂 Pas mal", "Ça peut le faire avec un peu d'effort."),
    (70, "😍 Bonne vibe", "Le serveur vous voit déjà ensemble."),
    (85, "💞 Presque parfait", "Il ne manque que l'officialisation."),
    (101, "❤️‍🔥 MARIAGE", "On réserve la salle ? Le bot est témoin."),
)


def ship_score(guild_id: int, user_a: int, user_b: int) -> int:
    """Compatibilité stable entre deux membres (l'ordre n'importe pas)."""
    first, second = sorted((int(user_a), int(user_b)))
    return stable_score("ship", guild_id, first, second, low=0, high=100)


def ship_verdict(score: int) -> tuple[str, str]:
    for threshold, verdict, comment in SHIP_VERDICTS:
        if score < threshold:
            return verdict, comment
    return SHIP_VERDICTS[-1][1], SHIP_VERDICTS[-1][2]


def ship(guild_id: int, member_a: Any, member_b: Any) -> dict[str, Any]:
    """Prépare un résultat de `/ship`."""
    score = ship_score(guild_id, int(member_a.id), int(member_b.id))
    verdict, comment = ship_verdict(score)
    same_person = int(member_a.id) == int(member_b.id)
    if same_person:
        verdict = "🪞 Amour de soi"
        comment = "2/10 : tu prends la place de deux personnes dans le couple."
        score = max(1, score // 6)
    return {
        "score": score,
        "verdict": verdict,
        "comment": comment,
        "a": member_a,
        "b": member_b,
        "same_person": same_person,
        "name": f"{getattr(member_a, 'display_name', '?')} × {getattr(member_b, 'display_name', '?')}",
    }


# --------------------------------------------------------------------------- #
# Blagues, piques, compliments, horoscopes
# --------------------------------------------------------------------------- #
JOKES: tuple[str, ...] = (
    "Pourquoi les développeurs préfèrent-ils le noir ? Parce que la lumière attire les bugs. 🐛",
    "Un octet entre dans un bar et commande une bière. Le barman lui dit : « Désolé, on ne sert pas les mineurs. »",
    "Pourquoi le bot n'a jamais peur ? Parce qu'il a des `try/except` partout. 🛡️",
    "Qu'est-ce qu'un canard qui pète ? Un coin-coin-ouf. 🦆",
    "J'ai demandé à mon Wi-Fi s'il allait bien. Il m'a répondu : « Signal faible, mais je tiens bon. »",
    "Pourquoi les plongeurs plongent-ils en arrière ? Parce que sinon, ils tombent dans le bateau. 🤿",
    "Un serveur Discord entre dans un bar. Le serveur du bar lui dit : « Désolé, on ne sert pas les bots. »",
    "Pourquoi le livre de maths est-il triste ? Parce qu'il a trop de problèmes. 📘",
    "Qu'est-ce qu'un fantôme qui fait du sport ? Un esprit de compétition. 👻",
    "Mon code ne bugue jamais… il développe juste des fonctionnalités surprises. ✨",
    "Pourquoi les vaches ne postent jamais sur Discord ? Parce qu'elles préfèrent les « meuh »-ssages privés. 🐮",
    "C'est l'histoire d'un ping qui n'arrivait jamais… bon, fin de l'histoire, tu ne l'as pas reçue.",
    "Pourquoi l'épouvantail a-t-il reçu un prix ? Parce qu'il était exceptionnel dans son domaine. 🌾",
    "Un pixel dit à un autre pixel : « T'as l'air fatigué. » L'autre : « Oui, je manque de résolution. »",
    "Quel est le comble pour un électricien ? De ne pas être au courant. ⚡",
)

ROASTS: tuple[str, ...] = (
    "Tu es la preuve vivante que la barre du niveau a été enterrée.",
    "Tu as une tête à avoir perdu un débat contre ton propre reflet.",
    "Ton historique de recherche doit ressembler à un poème tragique.",
    "Tu es comme un point-virgule : personne ne sait vraiment à quoi tu sers.",
    "Tu cours si lentement que les escargots te doublent en soupirant.",
    "Ta playlist pourrait servir de berceuse à un pare-feu.",
    "Tu as le charisme d'un mode maintenance.",
    "Tu es le genre de personne qui perd une partie de solitaire.",
    "Si l'intelligence était un bus, tu attendrais la ligne suivante.",
    "Même ton écran de veille a plus de personnalité.",
    "Tu brilles tellement peu qu'on te confond avec un mode avion.",
    "Tu es une mise à jour obligatoire un dimanche soir.",
)

COMPLIMENTS: tuple[str, ...] = (
    "Ta simple présence rend ce serveur 12 % plus supportable (statistique inventée).",
    "Tu as le charisme d'un générique de série que tout le monde chante.",
    "Ton énergie est plus stable que le Wi-Fi du serveur.",
    "Tu es la personne que tout le monde veut dans son équipe de UNO.",
    "Ton sens de l'humour vaut au moins trois abonnements à un stand-up.",
    "Tu es comme un ctrl+Z : toujours rassurant.",
    "Ta bonne humeur devrait être remboursée par la sécurité sociale.",
    "Tu illumines le chat comme un mode sombre bien réglé.",
    "Tu es la preuve qu'on peut être drôle sans être méchant.",
    "Tu as la classe d'une notification qu'on a envie d'ouvrir.",
)

HOROSCOPES: tuple[str, ...] = (
    "Les astres annoncent une journée parfaite pour le chaos, à condition de ne pas toucher au render.",
    "Mercure est en rétrograde : n'ouvre pas la boutique aujourd'hui, tu vas acheter un rôle inutile.",
    "Vénus te protège : quelqu'un va réagir à ton message dans les 4 minutes. Ce n'est peut-être pas une coïncidence.",
    "La lune est alignée avec ton salon vocal : tu vas parler 20 minutes dans le vide.",
    "Saturne te conseille de relancer le bot. Ça ne corrigera rien, mais ça te fera du bien.",
    "Un bug cosmique t'attend : la commande qui marchait hier ne marchera plus demain.",
    "Jupiter promet une pluie de coins. En réalité, tu vas juste gagner un giveaway de 3 personnes.",
    "Cette semaine, ton destin est écrit en JSON, mais il manque une virgule.",
    "Neptune te dit : la prudence est une vertu, surtout en `/casino mise-max`.",
    "Pluton (oui, Pluton) te rappelle que même les petites planètes ont de grandes ambitions.",
)

HOROSCOPE_SIGNS: dict[str, str] = {
    "belier": "♈ Bélier",
    "taureau": "♉ Taureau",
    "gemeaux": "♊ Gémeaux",
    "cancer": "♋ Cancer",
    "lion": "♌ Lion",
    "vierge": "♍ Vierge",
    "balance": "♎ Balance",
    "scorpion": "♏ Scorpion",
    "sagittaire": "♐ Sagittaire",
    "capricorne": "♑ Capricorne",
    "verseau": "♒ Verseau",
    "poissons": "♓ Poissons",
}

HOROSCOPE_ALIASES: dict[str, str] = {
    "bélier": "belier",
    "gémaux": "gemeaux",
    "gemeau": "gemeaux",
    "gémeaux": "gemeaux",
    "vergeau": "verseau",
    "poisson": "poissons",
    "scorpio": "scorpion",
    "capricorn": "capricorne",
    "sagitaire": "sagittaire",
    "balence": "balance",
}


def normalize_sign(raw: str) -> str | None:
    """Normalise un signe du zodiaque (accents, fautes courantes)."""
    value = (raw or "").strip().casefold()
    value = HOROSCOPE_ALIASES.get(value, value)
    return value if value in HOROSCOPE_SIGNS else None


def pick_horoscope(sign: str, guild_id: int, user_id: int) -> str:
    """Horoscope stable de la semaine pour un membre."""
    index = stable_score("horoscope", sign, guild_id, user_id, low=0, high=len(HOROSCOPES) - 1)
    return HOROSCOPES[index]


def pick_from(pool: Iterable[str], rng: random.Random | None = None) -> str:
    """Choisit une phrase au hasard dans un pool."""
    items = tuple(pool)
    if not items:
        return "…"
    return (rng or random).choice(items)


# --------------------------------------------------------------------------- #
# /duel : simulation de combat
# --------------------------------------------------------------------------- #
@dataclass
class BattleEvent:
    """Un tour de combat."""

    attacker: str
    defender: str
    damage: int
    text: str


@dataclass
class BattleResult:
    """Résultat complet d'un duel (prêt à animer)."""

    fighter_a: str
    fighter_b: str
    hp_a: int
    hp_b: int
    events: list[BattleEvent] = field(default_factory=list)
    winner: str | None = None
    loser: str | None = None

    @property
    def turns(self) -> int:
        return len(self.events)


ATTACKS: tuple[tuple[str, int], ...] = (
    ("lance un cookie à pleine vitesse", 12),
    ("déploie une attaque de mauvaise foi", 18),
    ("envoie un ping à 3 h du matin", 9),
    ("balance un meme vieux de 2012", 14),
    ("cite les règles du serveur", 11),
    ("fait un triangle d'arguments", 16),
    ("invoque le modo suprême", 22),
    ("lance une citation philosophique", 8),
    ("sort son attaque spéciale : le silence gênant", 15),
    ("envoie un vocal de 4 minutes", 13),
    ("déclenche un débat sur les ananas sur la pizza", 20),
    ("spamme des emojis de feu", 10),
)

DEFENSES: tuple[str, ...] = (
    "mais glisse sur une peau de banane",
    "et c'est super efficace",
    "pendant que l'autre regarde ailleurs",
    "avec un bruit de trompette",
    "en criant « ATTENTION DERRIÈRE TOI »",
    "et l'adversaire applaudit malgré lui",
)


def battle(name_a: str, name_b: str, rng: random.Random | None = None) -> BattleResult:
    """Simule un duel animé entre deux combattants."""
    rng = rng or random.Random()
    result = BattleResult(fighter_a=name_a, fighter_b=name_b, hp_a=100, hp_b=100)
    turn = 0
    while result.hp_a > 0 and result.hp_b > 0 and turn < 24:
        a_attacks = turn % 2 == 0
        attacker = name_a if a_attacks else name_b
        defender = name_b if a_attacks else name_a
        action, base = rng.choice(ATTACKS)
        damage = max(4, base + rng.randint(-4, 6))
        text = f"**{attacker}** {action} {rng.choice(DEFENSES)} — **{damage}** dégâts !"
        if a_attacks:
            result.hp_b = max(0, result.hp_b - damage)
        else:
            result.hp_a = max(0, result.hp_a - damage)
        result.events.append(BattleEvent(attacker, defender, damage, text))
        turn += 1

    if result.hp_a <= 0 and result.hp_b <= 0:  # double KO improbable
        result.winner = result.loser = None
    elif result.hp_b <= 0:
        result.winner, result.loser = name_a, name_b
    else:
        result.winner, result.loser = name_b, name_a
    return result


# --------------------------------------------------------------------------- #
# /pfc : pierre-feuille-ciseaux
# --------------------------------------------------------------------------- #
RPS_EMOJIS: dict[str, str] = {"pierre": "🪨", "feuille": "📄", "ciseaux": "✂️"}
RPS_LABELS: dict[str, str] = {"pierre": "Pierre", "feuille": "Feuille", "ciseaux": "Ciseaux"}
RPS_BEATS: dict[str, str] = {"pierre": "ciseaux", "feuille": "pierre", "ciseaux": "feuille"}


def normalize_rps(raw: str) -> str | None:
    value = (raw or "").strip().casefold()
    aliases = {
        "p": "pierre",
        "rock": "pierre",
        "caillou": "pierre",
        "f": "feuille",
        "paper": "feuille",
        "papier": "feuille",
        "c": "ciseaux",
        "scissors": "ciseaux",
        "ciso": "ciseaux",
    }
    value = aliases.get(value, value)
    return value if value in RPS_EMOJIS else None


def resolve_rps(choice_a: str, choice_b: str) -> str:
    """Renvoie `a`, `b` ou `draw`."""
    if choice_a == choice_b:
        return "draw"
    return "a" if RPS_BEATS[choice_a] == choice_b else "b"


def bot_rps_choice(rng: random.Random | None = None) -> str:
    return (rng or random).choice(tuple(RPS_EMOJIS))


# --------------------------------------------------------------------------- #
# /de et /pileouface
# --------------------------------------------------------------------------- #
DICE_FACES: tuple[str, ...] = ("⚀", "⚁", "⚂", "⚃", "⚄", "⚅")


def roll(sides: int = 6, count: int = 1, rng: random.Random | None = None) -> list[int]:
    """Lance `count` dés à `sides` faces (2 à 100 faces, 1 à 10 dés)."""
    sides = max(2, min(100, int(sides)))
    count = max(1, min(10, int(count)))
    rng = rng or random
    return [rng.randint(1, sides) for _ in range(count)]


def dice_display(values: list[int], sides: int = 6) -> str:
    """Représentation lisible d'un lancer."""
    if sides == 6:
        return " ".join(DICE_FACES[value - 1] for value in values)
    return " · ".join(f"`{value}`" for value in values)


def coinflip(rng: random.Random | None = None) -> str:
    """`pile` ou `face`."""
    return (rng or random).choice(("pile", "face"))


COIN_EMOJIS: dict[str, str] = {"pile": "🪙", "face": "🎯"}


# --------------------------------------------------------------------------- #
# Actions rigolotes (/calin, /baffe…)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ActionSpec:
    key: str
    label: str
    emoji: str
    verb: str
    color: int
    lines: tuple[str, ...]


ACTIONS: dict[str, ActionSpec] = {
    "calin": ActionSpec(
        key="calin",
        label="Câlin",
        emoji="🤗",
        verb="fait un câlin à",
        color=0xF472B6,
        lines=(
            "un câlin de 10 secondes, avec le petit tapotement dans le dos",
            "un câlin si fort que la gravité a hésité",
            "un câlin virtuel certifié anti-stress",
            "un câlin de groupe, tout le serveur s'y met",
        ),
    ),
    "baffe": ActionSpec(
        key="baffe",
        label="Baffe",
        emoji="🫲",
        verb="met une baffe à",
        color=0xEF4444,
        lines=(
            "avec un bruit de dessin animé (`PAF !`)",
            "une baffe si légère qu'elle en devient un compliment",
            "une baffe avec élan de rotation, comme dans les animés",
            "une baffe qui a fait un bruit de moustique vexé",
        ),
    ),
    "tapote": ActionSpec(
        key="tapote",
        label="Tapote",
        emoji="🫳",
        verb="tapote la tête de",
        color=0x8B5CF6,
        lines=(
            "doucement, en disant « c'est bien, c'est bien »",
            "comme on tapote un petit chien très fier de lui",
            "avec un « *pat pat* » audible depuis l'espace",
            "trois fois, puis une pause dramatique",
        ),
    ),
}

ACTION_CHOICES = tuple(ACTIONS)


def action_line(key: str, rng: random.Random | None = None) -> str:
    spec = ACTIONS.get(key)
    if spec is None:
        return "…"
    return pick_from(spec.lines, rng)


__all__ = [
    "ACTIONS",
    "ACTION_CHOICES",
    "ActionSpec",
    "ATTACKS",
    "BattleEvent",
    "BattleResult",
    "CHAOS_VERDICTS",
    "COIN_EMOJIS",
    "COMPLIMENTS",
    "DICE_FACES",
    "GAUGE_KINDS",
    "Gauge",
    "HOROSCOPES",
    "HOROSCOPE_SIGNS",
    "IQ_VERDICTS",
    "JOKES",
    "ROASTS",
    "RPS_BEATS",
    "RPS_EMOJIS",
    "RPS_LABELS",
    "SHIP_VERDICTS",
    "SIMPLY_VERDICTS",
    "SUS_VERDICTS",
    "AURA_VERDICTS",
    "action_line",
    "battle",
    "bot_rps_choice",
    "clean_text",
    "coinflip",
    "dice_display",
    "gauge",
    "normalize_rps",
    "normalize_sign",
    "pick_from",
    "pick_horoscope",
    "pick_verdict",
    "ratio_from_score",
    "resolve_rps",
    "roll",
    "ship",
    "ship_score",
    "ship_verdict",
    "stable_score",
]
