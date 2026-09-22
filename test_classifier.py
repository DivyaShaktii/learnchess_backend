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
    def __init__(self, lines, played_cp):
        self.lines = lines
        self.played_cp = played_cp

    def best_moves(self, board, n=3):
        return self.lines

    def score_after_move(self, board, move):
        return FakeScore(self.played_cp)


def line(move, score, pv=None):
    return {
        "move": move,
        "san": move,
        "score_cp": score,
        "is_mate": False,
        "mate_in": None,
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


if __name__ == "__main__":
    unittest.main()
