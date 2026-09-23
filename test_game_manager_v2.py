import os
import unittest
from unittest.mock import patch

import chess

from app.game_manager import Game, GameManager


class DummyClassifier:
    def classify_move(self, board, move, ply_number, use_v2=False):
        return {
            "label": "Excellent",
            "cp_loss": 0,
            "analysis_version": "v2" if use_v2 else "v1",
        }


class GameManagerV2Tests(unittest.TestCase):
    def setUp(self):
        self.manager = GameManager(None, None, DummyClassifier())
        self.manager.games["game-1"] = Game()

    def test_commit_reuses_bound_analysis_and_writes_true_pre_move_fen(self):
        game = self.manager.games["game-1"]
        initial_fen = game.board.fen()
        classification = {"label": "Mistake", "cp_loss": 90, "analysis_version": "v2"}
        game.last_precheck_move_uci = "e2e4"
        game.last_precheck_classification = classification
        game.last_analysis_id = "analysis-1"
        game.analyses["analysis-1"] = {"fen": initial_fen, "move_uci": "e2e4"}

        self.manager.commit_move("game-1", "e2e4", "analysis-1")

        entry = game.move_history[-1]
        self.assertEqual(entry["classification"], "Mistake")
        self.assertEqual(entry["fen_before"], initial_fen)
        self.assertEqual(entry["analysis_version"], "v2")
        self.assertEqual(entry["analysis_id"], "analysis-1")
        self.assertFalse(game.analyses)

    def test_stale_analysis_cannot_be_committed_or_explained(self):
        game = self.manager.games["game-1"]
        game.last_analysis_id = "current"
        with self.assertRaisesRegex(ValueError, "stale"):
            self.manager.commit_move("game-1", "e2e4", "old")
        with self.assertRaisesRegex(ValueError, "stale"):
            self.manager.explain_move("game-1", "e2e4", "old")

    def test_undo_invalidates_pending_analysis(self):
        game = self.manager.games["game-1"]
        game.board.push_uci("e2e4")
        game.move_history.append({"san": "e4"})
        game.last_analysis_id = "analysis-1"
        game.analyses["analysis-1"] = {"fen": game.board.fen(), "move_uci": "e7e5"}

        self.manager.undo_last_move("game-1", plies=1)

        self.assertIsNone(game.last_analysis_id)
        self.assertFalse(game.analyses)
        self.assertEqual(game.board.fen(), chess.Board().fen())

    def test_rollout_flag_has_safe_zero_and_full_percent_boundaries(self):
        with patch.dict(os.environ, {"COACH_V2_ROLLOUT_PERCENT": "0"}):
            self.assertFalse(self.manager._v2_enabled("any-game"))
        with patch.dict(os.environ, {"COACH_V2_ROLLOUT_PERCENT": "100"}):
            self.assertTrue(self.manager._v2_enabled("any-game"))


if __name__ == "__main__":
    unittest.main()
