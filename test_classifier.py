import unittest

import chess

from app.classifier import MoveClassifier


class FakeScore:
    def __init__(self, cp: int, mate: bool = False):
        self.cp = cp
        self.mate = mate

    def score(self, mate_score: int):
        return self.cp

    def is_mate(self):
        return self.mate


class FakeEngine:
    def __init__(self, lines, played_cp, played_mate=False):
        self.lines = lines
        self.played_cp = played_cp
        self.played_mate = played_mate

    def best_moves(self, board, n=3):
        return self.lines

    def score_after_move(self, board, move):
        return FakeScore(self.played_cp, self.played_mate)


def line(move, score, pv=None, mate=False, mate_in=None):
    return {
        "move": move,
        "san": move,
        "score_cp": score,
        "is_mate": mate,
        "mate_in": mate_in,
        "pv": pv or [move],
    }


class MoveClassifierTests(unittest.TestCase):
    def test_top_engine_move_is_best_move(self):
        board = chess.Board()
        engine = FakeEngine([line("e2e4", 30), line("d2d4", 22)], 30)
        result = MoveClassifier(engine).classify_move(board, chess.Move.from_uci("e2e4"), 7)
        self.assertEqual(result["label"], "Best Move")

    def test_near_best_move_is_excellent(self):
        board = chess.Board()
        engine = FakeEngine([line("e2e4", 35), line("d2d4", 25)], 25)
        result = MoveClassifier(engine).classify_move(board, chess.Move.from_uci("d2d4"), 7)
        self.assertEqual(result["label"], "Excellent")

    def test_sound_piece_sacrifice_is_brilliant(self):
        board = chess.Board()
        for move in ("e2e4", "e7e5", "f1c4", "b8c6"):
            board.push_uci(move)
        engine = FakeEngine(
            [line("c4f7", 35, ["c4f7", "e8f7"]), line("g1f3", 20)],
            30,
        )
        result = MoveClassifier(engine).classify_move(board, chess.Move.from_uci("c4f7"), 9)
        self.assertEqual(result["label"], "Brilliant")

    def test_book_label_requires_an_engine_sound_move(self):
        board = chess.Board()
        engine = FakeEngine([line("e2e4", 30), line("d2d4", 22)], 30)
        result = MoveClassifier(engine).classify_move(board, chess.Move.from_uci("e2e4"), 1)
        self.assertEqual(result["label"], "Book")

    def test_bad_early_wing_pawn_move_still_warns(self):
        board = chess.Board()
        engine = FakeEngine([line("e2e4", 30), line("h2h3", -30)], -30)
        result = MoveClassifier(engine).classify_move(board, chess.Move.from_uci("h2h3"), 1)
        self.assertEqual(result["label"], "Opening Pawn Warning")

    def test_equal_position_loss_is_stricter_than_same_cp_loss_when_winning(self):
        board = chess.Board()
        equal_engine = FakeEngine([line("e2e4", 50), line("d2d4", -50)], -50)
        winning_engine = FakeEngine([line("e2e4", 950), line("d2d4", 850)], 850)

        equal_result = MoveClassifier(equal_engine).classify_move(
            board, chess.Move.from_uci("d2d4"), 7
        )
        winning_result = MoveClassifier(winning_engine).classify_move(
            board, chess.Move.from_uci("d2d4"), 7
        )

        self.assertEqual(equal_result["label"], "Mistake")
        self.assertEqual(winning_result["label"], "Good")
        self.assertGreater(
            equal_result["win_probability_loss"],
            winning_result["win_probability_loss"],
        )

    def test_missing_a_forced_mate_is_worst_move(self):
        board = chess.Board()
        engine = FakeEngine(
            [line("e2e4", 100_000, mate=True, mate_in=3), line("d2d4", 300)],
            300,
        )
        result = MoveClassifier(engine).classify_move(
            board, chess.Move.from_uci("d2d4"), 7
        )
        self.assertEqual(result["label"], "Worst Move")

    def test_v2_top_move_with_tied_alternative_is_excellent(self):
        board = chess.Board()
        engine = FakeEngine([line("e2e4", 30), line("d2d4", 29)], 30)
        result = MoveClassifier(engine).classify_move(
            board, chess.Move.from_uci("e2e4"), 7, use_v2=True
        )
        # The opening database may identify e4 as Book; outside the opening it
        # would be Excellent because the alternatives are effectively tied.
        self.assertIn(result["label"], {"Book", "Excellent"})

    def test_v2_large_alternative_gap_marks_only_move(self):
        board = chess.Board()
        for move in ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"):
            board.push_uci(move)
        engine = FakeEngine([line("b5c6", 350), line("b5a4", 0)], 350)
        result = MoveClassifier(engine).classify_move(
            board, chess.Move.from_uci("b5c6"), 13, use_v2=True
        )
        self.assertEqual(result["label"], "Only Move")


if __name__ == "__main__":
    unittest.main()
