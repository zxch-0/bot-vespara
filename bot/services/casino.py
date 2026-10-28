"""Jeux du casino : logique pure (aucun appel Discord) + rendu des cartes.

Chaque jeu expose une petite « session » immuable-ish que l'interface peut
manipuler pas à pas (blackjack) ou résoudre d'un coup (slots, roulette, dés).
Les fonctions sont testables avec un `random.Random` contrôlé.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from ..constants import (
    CASINO_BLACKJACK_NATURAL,
    CASINO_BLACKJACK_PAYOUT,
    CASINO_DICE_PAYOUTS,
    CASINO_ROULETTE_PAYOUTS,
    CASINO_SLOTS_PAYOUTS,
    DICE_LABELS,
    ROULETTE_LABELS,
    SLOT_SYMBOLS,
)

# --------------------------------------------------------------------------- #
# Cartes
# --------------------------------------------------------------------------- #
SUITS: dict[str, str] = {"♠": "noir", "♥": "rouge", "♦": "rouge", "♣": "noir"}
RANKS: tuple[str, ...] = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")


@dataclass(frozen=True, slots=True)
class Card:
    rank: str
    suit: str

    @property
    def label(self) -> str:
        return f"{self.rank}{self.suit}"

    @property
    def value(self) -> int:
        if self.rank == "A":
            return 11
        if self.rank in {"J", "Q", "K"}:
            return 10
        return int(self.rank)


def new_deck(rng: random.Random | None = None) -> list[Card]:
    """Jeu de 52 cartes mélangé."""
    deck = [Card(rank, suit) for suit in SUITS for rank in RANKS]
    (rng or random).shuffle(deck)
    return deck


def hand_value(hand: list[Card]) -> int:
    """Meilleure valeur d'une main (les as valent 1 ou 11)."""
    total = sum(card.value for card in hand)
    aces = sum(1 for card in hand if card.rank == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_soft(hand: list[Card]) -> bool:
    """Main « souple » : un as compte encore 11."""
    return sum(card.value for card in hand) != hand_value(hand)


def is_blackjack(hand: list[Card]) -> bool:
    return len(hand) == 2 and hand_value(hand) == 21


def render_hand(hand: list[Card], *, hidden: bool = False) -> str:
    """Rendu compact d'une main : `A♠ 10♥` (+ carte cachée)."""
    cards = " ".join(card.label for card in hand)
    if hidden:
        cards += " `??`"
    value = "?" if hidden else str(hand_value(hand))
    return f"`{cards}` · **{value}**"


def card_label(card: Card) -> str:
    return f"{card.rank}{card.suit}"


# --------------------------------------------------------------------------- #
# Blackjack
# --------------------------------------------------------------------------- #
@dataclass
class BlackjackSession:
    """Partie de blackjack : le membre joue, le croupier tire ensuite."""

    bet: int
    deck: list[Card]
    player: list[Card] = field(default_factory=list)
    dealer: list[Card] = field(default_factory=list)
    finished: bool = False
    outcome: str = ""  # player | dealer | push | blackjack | bust | surrender
    payout: int = 0
    doubled: bool = False
    surrendered: bool = False

    # ------------------------------------------------------------------ #
    @classmethod
    def start(cls, bet: int, rng: random.Random | None = None) -> "BlackjackSession":
        session = cls(bet=bet, deck=new_deck(rng))
        session.player = [session.deck.pop(), session.deck.pop()]
        session.dealer = [session.deck.pop(), session.deck.pop()]
        if is_blackjack(session.player):
            session._resolve(natural=True)
        return session

    # ------------------------------------------------------------------ #
    @property
    def player_value(self) -> int:
        return hand_value(self.player)

    @property
    def dealer_value(self) -> int:
        return hand_value(self.dealer)

    def player_view(self) -> str:
        """Main du joueur + croupier (deuxième carte cachée)."""
        dealer = render_hand(self.dealer[:1], hidden=False) if not self.finished else render_hand(self.dealer)
        if not self.finished:
            dealer = f"`{card_label(self.dealer[0])} ??` · **{self.dealer[0].value}**"
        return (
            f"**Croupier** : {dealer}\n"
            f"**Toi** : {render_hand(self.player)}"
        )

    # ------------------------------------------------------------------ #
    def _draw(self) -> Card:
        if not self.deck:
            self.deck = new_deck()
        return self.deck.pop()

    def hit(self) -> bool:
        """Tire une carte. Renvoie False si la partie est terminée."""
        if self.finished:
            return False
        self.player.append(self._draw())
        if self.player_value > 21:
            self._resolve(bust=True)
        return True

    def stand(self) -> None:
        """Le joueur s'arrête : le croupier joue."""
        if self.finished:
            return
        self._play_dealer()
        self._resolve()

    def double(self) -> bool:
        """Double la mise, une seule carte, puis le croupier joue."""
        if self.finished or len(self.player) != 2 or self.doubled:
            return False
        self.doubled = True
        self.bet *= 2
        self.player.append(self._draw())
        if self.player_value > 21:
            self._resolve(bust=True)
        else:
            self._play_dealer()
            self._resolve()
        return True

    def surrender(self) -> bool:
        """Abandon : on récupère la moitié de la mise."""
        if self.finished or len(self.player) != 2:
            return False
        self.surrendered = True
        self.finished = True
        self.outcome = "surrender"
        self.payout = self.bet // 2
        return True

    # ------------------------------------------------------------------ #
    def _play_dealer(self) -> None:
        while self.dealer_value < 17:
            self.dealer.append(self._draw())

    def _resolve(self, *, natural: bool = False, bust: bool = False) -> None:
        self.finished = True
        player = self.player_value
        dealer = self.dealer_value

        if natural:
            self.outcome = "blackjack"
            self.payout = int(self.bet * CASINO_BLACKJACK_NATURAL)
            return
        if bust:
            self.outcome = "bust"
            self.payout = 0
            return
        if dealer > 21 or player > dealer:
            self.outcome = "player"
            self.payout = int(self.bet * CASINO_BLACKJACK_PAYOUT)
            return
        if player == dealer:
            self.outcome = "push"
            self.payout = self.bet
            return
        self.outcome = "dealer"
        self.payout = 0

    @property
    def net(self) -> int:
        """Gain net (paiement - mise)."""
        return self.payout - self.bet

    @property
    def summary(self) -> str:
        return BLACKJACK_OUTCOMES.get(self.outcome, "Partie terminée.")

    def can_double(self) -> bool:
        return not self.finished and len(self.player) == 2 and not self.doubled

    def can_surrender(self) -> bool:
        return not self.finished and len(self.player) == 2


BLACKJACK_OUTCOMES: dict[str, str] = {
    "blackjack": "🂡 **Blackjack !**",
    "player": "🎉 **Tu gagnes !**",
    "dealer": "😵 **Le croupier gagne.**",
    "push": "🤝 **Égalité** — mise remboursée.",
    "bust": "💥 **Tu dépasses 21.**",
    "surrender": "🏳️ **Abandon** — la moitié de la mise est rendue.",
}


# --------------------------------------------------------------------------- #
# Machine à sous
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class SlotsResult:
    reels: tuple[str, str, str]
    multiplier: float
    payout: int
    bet: int

    @property
    def net(self) -> int:
        return self.payout - self.bet

    @property
    def won(self) -> bool:
        return self.payout > 0

    @property
    def display(self) -> str:
        return " ┃ ".join(self.reels)

    @property
    def label(self) -> str:
        if self.multiplier >= CASINO_SLOTS_PAYOUTS[3]:
            return "💎 **JACKPOT !** Trois symboles identiques !"
        if self.multiplier > 1:
            return "✨ **Deux symboles identiques !**"
        return "😶 Rien cette fois…"


def spin_slots(bet: int, rng: random.Random | None = None) -> SlotsResult:
    """Un tirage de machine à sous (3 rouleaux)."""
    rng = rng or random
    reels = tuple(rng.choice(SLOT_SYMBOLS) for _ in range(3))
    if reels[0] == reels[1] == reels[2]:
        multiplier = CASINO_SLOTS_PAYOUTS[3]
        if reels[0] == "7️⃣":  # jackpot des sept
            multiplier *= 2
    elif len(set(reels)) == 2:
        multiplier = CASINO_SLOTS_PAYOUTS[2]
    else:
        multiplier = 0.0
    return SlotsResult(reels, multiplier, int(bet * multiplier), int(bet))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Roulette
# --------------------------------------------------------------------------- #
RED_NUMBERS: frozenset[int] = frozenset(
    {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
)


def roulette_color(number: int) -> str:
    if number == 0:
        return "vert"
    return "rouge" if number in RED_NUMBERS else "noir"


BET_ALIASES: dict[str, str] = {
    "r": "rouge",
    "rouges": "rouge",
    "red": "rouge",
    "n": "noir",
    "noirs": "noir",
    "black": "noir",
    "pairs": "pair",
    "even": "pair",
    "impairs": "impair",
    "odd": "impair",
    "1-18": "bas",
    "bas": "bas",
    "low": "bas",
    "19-36": "haut",
    "haut": "haut",
    "high": "haut",
    "verts": "vert",
    "green": "vert",
    "0": "vert",
    "num": "nombre",
    "number": "nombre",
    "numero": "nombre",
    "numéro": "nombre",
}


def normalize_roulette_bet(raw: str, number: int | None = None) -> tuple[str, int | None]:
    """Transforme la saisie utilisateur en (`pari`, numéro éventuel)."""
    value = (raw or "").strip().casefold()
    if not value:
        raise ValueError("Choisis un pari (rouge, noir, pair, impair, bas, haut, vert, nombre).")
    if value.lstrip("+").isdigit():
        number = int(value)
        return "nombre", number
    bet = BET_ALIASES.get(value, value)
    if bet not in CASINO_ROULETTE_PAYOUTS:
        options = ", ".join(sorted(CASINO_ROULETTE_PAYOUTS))
        raise ValueError(f"Pari inconnu « {raw} ». Choix possibles : {options}.")
    return bet, number


@dataclass(frozen=True, slots=True)
class RouletteResult:
    number: int
    color: str
    bet: str
    bet_number: int | None
    stake: int
    multiplier: float
    payout: int

    @property
    def net(self) -> int:
        return self.payout - self.stake

    @property
    def won(self) -> bool:
        return self.payout > 0

    @property
    def display(self) -> str:
        emoji = {"rouge": "🔴", "noir": "⚫", "vert": "🟢"}[self.color]
        return f"{emoji} **{self.number}** {self.color}"

    @property
    def label(self) -> str:
        if not self.won:
            return "😶 Perdu — la bille n'était pas d'accord."
        return f"🎉 **Gagné !** ({ROULETTE_LABELS.get(self.bet, self.bet)})"


def roulette_wins(bet: str, number: int, bet_number: int | None = None) -> bool:
    color = roulette_color(number)
    if bet == "nombre":
        return bet_number is not None and int(bet_number) == int(number)
    if number == 0:
        return bet == "vert"
    if bet in {"rouge", "noir", "vert"}:
        return color == bet
    if bet == "pair":
        return number % 2 == 0
    if bet == "impair":
        return number % 2 == 1
    if bet == "bas":
        return number <= 18
    if bet == "haut":
        return number >= 19
    return False


def spin_roulette(
    stake: int,
    bet: str,
    bet_number: int | None = None,
    rng: random.Random | None = None,
    number: int | None = None,
) -> RouletteResult:
    """Tour de roulette européen (0 à 36)."""
    rng = rng or random
    if number is None:
        number = rng.randint(0, 36)
    number = int(number)
    if not 0 <= number <= 36:
        raise ValueError("Le numéro doit être compris entre 0 et 36.")
    color = roulette_color(number)
    won = roulette_wins(bet, number, bet_number)
    multiplier = CASINO_ROULETTE_PAYOUTS.get(bet, 0.0) if won else 0.0
    return RouletteResult(
        number=number,
        color=color,
        bet=bet,
        bet_number=bet_number,
        stake=int(stake),
        multiplier=multiplier,
        payout=int(stake * multiplier),
    )


# --------------------------------------------------------------------------- #
# Dés
# --------------------------------------------------------------------------- #
DICE_FACES: tuple[str, ...] = ("⚀", "⚁", "⚂", "⚃", "⚄", "⚅")


@dataclass(frozen=True, slots=True)
class DiceResult:
    dice: tuple[int, int]
    total: int
    bet: str
    stake: int
    multiplier: float
    payout: int

    @property
    def net(self) -> int:
        return self.payout - self.stake

    @property
    def won(self) -> bool:
        return self.payout > 0

    @property
    def display(self) -> str:
        faces = " ".join(DICE_FACES[value - 1] for value in self.dice)
        return f"{faces} · total **{self.total}**"

    @property
    def label(self) -> str:
        if not self.won:
            return "😶 Perdu — les dés ont décidé autrement."
        return f"🎉 **Gagné !** ({DICE_LABELS.get(self.bet, self.bet)})"


def normalize_dice_bet(raw: str) -> str:
    value = (raw or "").strip().casefold()
    aliases = {
        "pairs": "pair",
        "even": "pair",
        "impairs": "impair",
        "odd": "impair",
        "7": "sept",
        "seven": "sept",
        "doubles": "double",
        "haut": "haut",
        "high": "haut",
        "bas": "bas",
        "low": "bas",
    }
    bet = aliases.get(value, value)
    if bet not in CASINO_DICE_PAYOUTS:
        options = ", ".join(sorted(CASINO_DICE_PAYOUTS))
        raise ValueError(f"Pari inconnu « {raw} ». Choix possibles : {options}.")
    return bet


def dice_wins(bet: str, first: int, second: int) -> bool:
    total = first + second
    if bet == "pair":
        return total % 2 == 0
    if bet == "impair":
        return total % 2 == 1
    if bet == "sept":
        return total == 7
    if bet == "double":
        return first == second
    if bet == "haut":
        return total >= 9
    if bet == "bas":
        return total <= 6
    return False


def roll_dice(
    stake: int,
    bet: str,
    rng: random.Random | None = None,
    dice: tuple[int, int] | None = None,
) -> DiceResult:
    rng = rng or random
    values = dice or (rng.randint(1, 6), rng.randint(1, 6))
    first, second = int(values[0]), int(values[1])
    won = dice_wins(bet, first, second)
    multiplier = CASINO_DICE_PAYOUTS.get(bet, 0.0) if won else 0.0
    return DiceResult(
        dice=(first, second),
        total=first + second,
        bet=bet,
        stake=int(stake),
        multiplier=multiplier,
        payout=int(stake * multiplier),
    )


# --------------------------------------------------------------------------- #
# Aides d'affichage
# --------------------------------------------------------------------------- #
def roulette_table() -> str:
    """Petit tableau des paris avec leurs multiplicateurs."""
    lines = []
    for key, label in ROULETTE_LABELS.items():
        if key == "nombre":
            continue
        lines.append(f"{label} · ×{CASINO_ROULETTE_PAYOUTS[key]:g}")
    lines.append(f"🔢 Un numéro exact · ×{CASINO_ROULETTE_PAYOUTS['nombre']:g}")
    return "\n".join(lines)


def dice_table() -> str:
    return "\n".join(
        f"{label} · ×{CASINO_DICE_PAYOUTS[key]:g}" for key, label in DICE_LABELS.items()
    )


def casino_games() -> dict[str, dict[str, Any]]:
    """Catalogue des jeux (nom -> description, gains)."""
    return {
        "blackjack": {
            "name": "🃏 Blackjack",
            "description": "Bats le croupier sans dépasser 21. Blackjack naturel : ×2,5.",
            "command": "/casino blackjack <mise>",
        },
        "slots": {
            "name": "🎰 Machine à sous",
            "description": "Trois symboles identiques : ×12 (×24 avec trois 7️⃣).",
            "command": "/casino slots <mise>",
        },
        "roulette": {
            "name": "🎡 Roulette",
            "description": "Rouge/noir, pair/impair, bas/haut (×2), vert (×14), numéro (×36).",
            "command": "/casino roulette <mise> <pari>",
        },
        "dice": {
            "name": "🎲 Dés",
            "description": "Somme paire/impaire (×2), 7 exact (×6), double (×8).",
            "command": "/casino des <mise> <pari>",
        },
    }


__all__ = [
    "BET_ALIASES",
    "BlackjackSession",
    "Card",
    "DiceResult",
    "RED_NUMBERS",
    "RANKS",
    "RouletteResult",
    "SUITS",
    "SlotsResult",
    "card_label",
    "casino_games",
    "dice_table",
    "dice_wins",
    "hand_value",
    "is_blackjack",
    "is_soft",
    "new_deck",
    "normalize_dice_bet",
    "normalize_roulette_bet",
    "render_hand",
    "roll_dice",
    "roulette_color",
    "roulette_table",
    "roulette_wins",
    "spin_roulette",
    "spin_slots",
]
