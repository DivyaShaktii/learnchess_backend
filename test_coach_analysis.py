import unittest

import chess

from app.coach_analysis import build_explanation, exchange_ledger, interruption_policy, is_benign_exchange
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

    def test_settled_pawn_exchange_is_benign(self):
        board = chess.Board("4k3/8/2p5/3p4/4P3/8/8/4K3 w - - 0 1")
        explanation = build_explanation(
            board, chess.Move.from_uci("e4d5"), "Mistake", 10.0,
            ["c6d5", "e1f2", "e8f7"], "Kf2", "middlegame",
        )
        self.assertEqual(explanation["material"]["net"], 0)
        self.assertTrue(is_benign_exchange(explanation))
        self.assertNotIn("lose", explanation["summary"].lower())

    def test_settled_rook_exchange_is_benign(self):
        board = chess.Board("4k3/8/8/rr6/R7/8/8/4K3 w - - 0 1")
        explanation = build_explanation(
            board, chess.Move.from_uci("a4a5"), "Blunder", 20.0,
            ["b5a5", "e1f2", "e8f7"], "Kf2", "middlegame",
        )
        self.assertEqual(explanation["material"]["gained"], 5)
        self.assertEqual(explanation["material"]["lost"], 5)
        self.assertTrue(is_benign_exchange(explanation))

    def test_bishop_and_queen_exchanges_are_fully_accounted(self):
        cases = [
            (
                "4kr2/5n2/8/8/2B5/8/8/4K3 w - - 0 1",
                "c4f7", ["f8f7", "e1d2", "e8d7"], 3, False,
            ),
            (
                "4k3/8/8/qr6/Q7/8/8/4K3 w - - 0 1",
                "a4a5", ["b5a5", "e1f2", "e8f7"], 9, True,
            ),
        ]
        for fen, candidate, continuation, value, should_be_benign in cases:
            with self.subTest(candidate=candidate):
                board = chess.Board(fen)
                explanation = build_explanation(
                    board, chess.Move.from_uci(candidate), "Blunder", 20.0,
                    continuation, "Kf2", "middlegame",
                )
                self.assertEqual(explanation["material"]["gained"], value)
                self.assertEqual(explanation["material"]["lost"], value)
                self.assertTrue(explanation["material"]["exchange_complete"])
                self.assertEqual(is_benign_exchange(explanation), should_be_benign)


if __name__ == "__main__":
    unittest.main()
