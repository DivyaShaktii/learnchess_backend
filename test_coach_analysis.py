import unittest

import chess

from app.coach_analysis import build_explanation, exchange_ledger, interruption_policy
from app.opening_book import OpeningBook


class CoachAnalysisTests(unittest.TestCase):
    def test_equal_exchange_never_claims_piece_loss(self):
        board = chess.Board("4k3/8/2p5/3b4/5N2/8/8/4K3 w - - 0 1")
        move = chess.Move.from_uci("f4d5")
        continuation = ["c6d5", "e1f2", "e8f7"]
        ledger = exchange_ledger(board, move, continuation)
        explanation = build_explanation(
            board, move, "Inaccuracy", 5.0, continuation, "Kf2", "middlegame"
        )
        self.assertEqual(ledger["gained"], 3)
        self.assertEqual(ledger["lost"], 3)
        self.assertEqual(ledger["net"], 0)
        self.assertNotIn("loses a knight", explanation["detail"].lower())
        self.assertNotEqual(explanation["primary_reason"], "material_loss")

    def test_unsettled_line_cannot_make_definite_material_claim(self):
        board = chess.Board("4k3/8/2p5/3b4/5N2/8/8/4K3 w - - 0 1")
        move = chess.Move.from_uci("f4d5")
        explanation = build_explanation(
            board, move, "Mistake", 10.0, [], "Kf2", "middlegame"
        )
        self.assertFalse(explanation["material"]["exchange_complete"])
        self.assertNotEqual(explanation["primary_reason"], "material_loss")

    def test_popup_policy_is_mode_aware(self):
        policy = interruption_policy("Inaccuracy", 5.0, 0.8, "fork")
        self.assertEqual(policy["normal"], "popup")
        self.assertEqual(policy["roast"], "popup")
        self.assertEqual(policy["professional"], "audio")
        self.assertEqual(interruption_policy("Good", 2, 1, "fork")["normal"], "none")

    def test_position_based_opening_lookup(self):
        board = chess.Board()
        board.push_uci("e2e4")
        opening = OpeningBook().identify(board)
        self.assertIsNotNone(opening)
        self.assertTrue(opening.eco.startswith("B") or opening.eco.startswith("C"))


if __name__ == "__main__":
    unittest.main()
