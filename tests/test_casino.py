"""Tests du casino : blackjack, machine à sous, roulette et dés."""

from __future__ import annotations

import random
import unittest

from bot.constants import (
    CASINO_BLACKJACK_NATURAL,
    CASINO_DICE_PAYOUTS,
    CASINO_ROULETTE_PAYOUTS,
    CASINO_SLOTS_PAYOUTS,
    SLOT_SYMBOLS,
)
from bot.services.casino import (
    BlackjackSession,
    Card,
    dice_wins,
    hand_value,
    is_blackjack,
    new_deck,
    normalize_dice_bet,
    normalize_roulette_bet,
    render_hand,
    roll_dice,
    roulette_color,
    roulette_wins,
    spin_roulette,
    spin_slots,
)


def cards(*labels: str) -> list[Card]:
    """`cards("A♠", "K♥")` -> liste de cartes."""
    return [Card(label[:-1], label[-1]) for label in labels]


# --------------------------------------------------------------------------- #
# Cartes
# --------------------------------------------------------------------------- #
class CardTests(unittest.TestCase):
    def test_deck_has_52_unique_cards(self) -> None:
        deck = new_deck(random.Random(1))
        self.assertEqual(len(deck), 52)
        self.assertEqual(len(set(deck)), 52)

    def test_hand_value_handles_aces(self) -> None:
        self.assertEqual(hand_value(cards("A♠", "K♥")), 21)
        self.assertEqual(hand_value(cards("A♠", "A♥", "9♦")), 21)
        self.assertEqual(hand_value(cards("A♠", "A♥", "A♦", "A♣")), 14)
        self.assertEqual(hand_value(cards("K♠", "Q♥", "J♦")), 30)
        self.assertEqual(hand_value(cards("10♠", "6♥")), 16)

    def test_is_blackjack(self) -> None:
        self.assertTrue(is_blackjack(cards("A♠", "K♥")))
        self.assertFalse(is_blackjack(cards("A♠", "5♥", "5♦")))
        self.assertFalse(is_blackjack(cards("10♠", "9♥")))

    def test_render_hand(self) -> None:
        rendered = render_hand(cards("A♠", "10♥"))
        self.assertIn("A♠ 10♥", rendered)
        self.assertIn("21", rendered)
        hidden = render_hand(cards("A♠"), hidden=True)
        self.assertIn("??", hidden)


# --------------------------------------------------------------------------- #
# Blackjack
# --------------------------------------------------------------------------- #
class BlackjackTests(unittest.TestCase):
    def test_natural_blackjack_pays_bonus(self) -> None:
        session = BlackjackSession.start(100, random.Random(0))
        # On force les mains pour tester toutes les branches
        session.player = cards("A♠", "K♥")
        session.dealer = cards("9♣", "7♦")
        session.finished = False
        session._resolve(natural=True)
        self.assertTrue(session.finished)
        self.assertEqual(session.outcome, "blackjack")
        self.assertEqual(session.payout, int(100 * CASINO_BLACKJACK_NATURAL))

    def test_win_lose_push(self) -> None:
        session = BlackjackSession.start(100, random.Random(2))
        session.finished = False
        session.player = cards("10♠", "9♥")
        session.dealer = cards("10♣", "8♦")
        session.stand()
        self.assertEqual(session.outcome, "player")
        self.assertEqual(session.payout, 200)
        self.assertEqual(session.net, 100)

        push = BlackjackSession.start(50, random.Random(3))
        push.finished = False
        push.player = cards("10♠", "9♥")
        push.dealer = cards("10♣", "9♦")
        push.stand()
        self.assertEqual(push.outcome, "push")
        self.assertEqual(push.payout, 50)
        self.assertEqual(push.net, 0)

        lose = BlackjackSession.start(50, random.Random(4))
        lose.finished = False
        lose.player = cards("10♠", "5♥")
        lose.dealer = cards("10♣", "9♦")
        lose.stand()
        self.assertEqual(lose.outcome, "dealer")
        self.assertEqual(lose.payout, 0)

    def test_bust(self) -> None:
        session = BlackjackSession.start(100, random.Random(5))
        session.player = cards("10♠", "6♥")
        session.dealer = cards("10♣", "7♦")
        session.deck = cards("2♥", "3♦", "K♠")  # la dernière carte est piochée
        session.hit()
        self.assertTrue(session.finished)
        self.assertEqual(session.outcome, "bust")
        self.assertEqual(session.payout, 0)

    def test_stand_plays_dealer(self) -> None:
        session = BlackjackSession.start(100, random.Random(6))
        session.player = cards("10♠", "8♥")
        session.dealer = cards("2♣", "3♦")
        session.deck = cards("K♠", "K♥", "2♦")
        session.stand()
        self.assertGreaterEqual(session.dealer_value, 17)
        self.assertTrue(session.finished)

    def test_double_doubles_bet(self) -> None:
        session = BlackjackSession.start(100, random.Random(7))
        session.finished = False
        session.player = cards("5♠", "6♥")
        session.dealer = cards("9♣", "7♦")
        session.deck = cards("10♦", "2♠", "2♥")
        self.assertTrue(session.can_double())
        self.assertTrue(session.double())
        self.assertEqual(session.bet, 200)
        self.assertTrue(session.finished)
        self.assertFalse(session.can_double())

    def test_surrender_returns_half(self) -> None:
        session = BlackjackSession.start(101, random.Random(8))
        session.finished = False
        session.player = cards("10♠", "6♥")
        session.dealer = cards("A♣", "K♦")
        self.assertTrue(session.surrender())
        self.assertEqual(session.outcome, "surrender")
        self.assertEqual(session.payout, 50)
        self.assertFalse(session.surrender())  # déjà terminée

    def test_actions_after_finish_are_ignored(self) -> None:
        session = BlackjackSession.start(100, random.Random(9))
        session.player = cards("10♠", "9♥")
        session.dealer = cards("10♣", "8♦")
        session.stand()
        hand_before = list(session.player)
        self.assertFalse(session.hit())
        session.stand()
        self.assertEqual(session.player, hand_before)

    def test_player_view_hides_dealer_card(self) -> None:
        session = BlackjackSession.start(100, random.Random(10))
        session.finished = False
        session.player = cards("10♠", "9♥")
        session.dealer = cards("K♣", "2♦")
        view = session.player_view()
        self.assertIn("??", view)
        self.assertIn("19", view)


# --------------------------------------------------------------------------- #
# Machine à sous
# --------------------------------------------------------------------------- #
class SlotsTests(unittest.TestCase):
    def test_jackpot_pays_max(self) -> None:
        # On force trois symboles identiques en bouchonnant choice
        class Rigged(random.Random):
            def choice(self, seq):  # noqa: ARG002
                return "💎"

        result = spin_slots(100, Rigged())
        self.assertEqual(result.reels, ("💎", "💎", "💎"))
        self.assertEqual(result.multiplier, CASINO_SLOTS_PAYOUTS[3])
        self.assertEqual(result.payout, 1200)

    def test_two_matches_pay_small(self) -> None:
        class Rigged(random.Random):
            def __init__(self) -> None:
                super().__init__(0)
                self.calls = 0

            def choice(self, seq):
                self.calls += 1
                return "🍒" if self.calls < 3 else "🍋"

        result = spin_slots(100, Rigged())
        self.assertEqual(result.multiplier, CASINO_SLOTS_PAYOUTS[2])
        self.assertEqual(result.payout, 220)

    def test_no_match_pays_nothing(self) -> None:
        class Rigged(random.Random):
            def __init__(self) -> None:
                super().__init__(0)
                self.calls = 0

            def choice(self, seq):
                self.calls += 1
                return (SLOT_SYMBOLS[0], SLOT_SYMBOLS[1], SLOT_SYMBOLS[2])[self.calls - 1]

        result = spin_slots(50, Rigged())
        self.assertEqual(result.payout, 0)
        self.assertFalse(result.won)

    def test_random_spins_are_consistent(self) -> None:
        rng = random.Random(42)
        for _ in range(300):
            result = spin_slots(100, rng)
            self.assertEqual(len(result.reels), 3)
            self.assertTrue(all(symbol in SLOT_SYMBOLS for symbol in result.reels))
            self.assertEqual(result.net, result.payout - result.bet)


# --------------------------------------------------------------------------- #
# Roulette
# --------------------------------------------------------------------------- #
class RouletteTests(unittest.TestCase):
    def test_colors(self) -> None:
        self.assertEqual(roulette_color(0), "vert")
        self.assertEqual(roulette_color(1), "rouge")
        self.assertEqual(roulette_color(2), "noir")
        self.assertEqual(roulette_color(36), "rouge")

    def test_even_money_bets(self) -> None:
        self.assertTrue(roulette_wins("rouge", 3))
        self.assertFalse(roulette_wins("rouge", 4))
        self.assertTrue(roulette_wins("pair", 18))
        self.assertTrue(roulette_wins("impair", 19))
        self.assertTrue(roulette_wins("bas", 18))
        self.assertFalse(roulette_wins("bas", 19))
        self.assertTrue(roulette_wins("haut", 36))

    def test_zero_only_wins_green(self) -> None:
        self.assertTrue(roulette_wins("vert", 0))
        for bet in ("rouge", "noir", "pair", "impair", "bas", "haut"):
            self.assertFalse(roulette_wins(bet, 0), bet)

    def test_single_number(self) -> None:
        self.assertTrue(roulette_wins("nombre", 17, 17))
        self.assertFalse(roulette_wins("nombre", 17, 18))
        result = spin_roulette(100, "nombre", 17, number=17)
        self.assertEqual(result.multiplier, CASINO_ROULETTE_PAYOUTS["nombre"])
        self.assertEqual(result.payout, 3600)

    def test_normalize_bets(self) -> None:
        self.assertEqual(normalize_roulette_bet("Rouge"), ("rouge", None))
        self.assertEqual(normalize_roulette_bet("red"), ("rouge", None))
        self.assertEqual(normalize_roulette_bet("17"), ("nombre", 17))
        with self.assertRaises(ValueError):
            normalize_roulette_bet("banane")
        with self.assertRaises(ValueError):
            normalize_roulette_bet("")

    def test_random_spins(self) -> None:
        rng = random.Random(11)
        for _ in range(200):
            result = spin_roulette(10, "noir", rng=rng)
            self.assertTrue(0 <= result.number <= 36)
            self.assertEqual(result.color, roulette_color(result.number))
            self.assertEqual(result.net, result.payout - result.stake)

    def test_invalid_number(self) -> None:
        with self.assertRaises(ValueError):
            spin_roulette(10, "nombre", 37, number=37)


# --------------------------------------------------------------------------- #
# Dés
# --------------------------------------------------------------------------- #
class DiceTests(unittest.TestCase):
    def test_bets(self) -> None:
        self.assertTrue(dice_wins("pair", 2, 4))
        self.assertTrue(dice_wins("impair", 2, 3))
        self.assertTrue(dice_wins("sept", 3, 4))
        self.assertTrue(dice_wins("double", 5, 5))
        self.assertTrue(dice_wins("haut", 5, 6))
        self.assertTrue(dice_wins("bas", 1, 2))
        self.assertFalse(dice_wins("sept", 1, 1))

    def test_roll_and_payout(self) -> None:
        result = roll_dice(100, "sept", dice=(3, 4))
        self.assertEqual(result.total, 7)
        self.assertEqual(result.payout, int(100 * CASINO_DICE_PAYOUTS["sept"]))
        self.assertTrue(result.won)

        lost = roll_dice(100, "sept", dice=(1, 1))
        self.assertEqual(lost.payout, 0)
        self.assertFalse(lost.won)

    def test_normalize(self) -> None:
        self.assertEqual(normalize_dice_bet("Pairs"), "pair")
        self.assertEqual(normalize_dice_bet("7"), "sept")
        self.assertEqual(normalize_dice_bet("double"), "double")
        with self.assertRaises(ValueError):
            normalize_dice_bet("banane")

    def test_roll_with_rng(self) -> None:
        rng = random.Random(5)
        for _ in range(100):
            result = roll_dice(10, "pair", rng=rng)
            self.assertTrue(1 <= result.dice[0] <= 6)
            self.assertTrue(1 <= result.dice[1] <= 6)
            self.assertEqual(result.total, sum(result.dice))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
