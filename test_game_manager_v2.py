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


class WarningClassifier:
    def classify_move(self, board, move, ply_number, use_v2=False):
        return {
            "label": "Blunder",
            "cp_loss": 180,
            "win_probability_loss": 20,
            "best_move_san": "Kf2",
            "analysis_version": "v2" if use_v2 else "v1",
            "top_alternatives": [],
            "explanation": "Engine warning",
        }


class ExchangeEngine:
    def threat_preview(self, board, move, depth=None):
        return {
            "opponent_best_reply": "c6d5",
            "opponent_best_reply_san": "cxd5",
            "resulting_pv": ["c6d5", "e1f2", "e8f7"],
            "score_after_reply_cp": -180,
            "is_mate_threat": False,
            "mate_in": None,
        }


class RobotEngine:
    def __init__(self):
        self.rating = None
        self.time_limit = None

    def set_strength(self, rating):
        self.rating = rating

    def best_moves(self, board, n=1, time_limit=None):
        self.time_limit = time_limit
        return [{"move": "e2e4"}]


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

    def test_robot_move_uses_short_bounded_analysis(self):
        robot = RobotEngine()
        manager = GameManager(None, robot, DummyClassifier())
        manager.games["fast-game"] = Game(opponent_rating=1850)

        with patch.dict(os.environ, {"ROBOT_MOVE_TIME_LIMIT_SECONDS": "0.45"}):
            result = manager.get_robot_move("fast-game")

        self.assertEqual(robot.rating, 1850)
        self.assertEqual(robot.time_limit, 0.45)
        self.assertEqual(result["moves"][0]["move"], "e2e4")

    def test_robot_move_limit_cannot_be_configured_above_one_second(self):
        robot = RobotEngine()
        manager = GameManager(None, robot, DummyClassifier())
        manager.games["fast-game"] = Game()

        with patch.dict(os.environ, {"ROBOT_MOVE_TIME_LIMIT_SECONDS": "5"}):
            manager.get_robot_move("fast-game")

        self.assertEqual(robot.time_limit, 1.0)

    def test_legacy_rollout_game_suppresses_false_equal_pawn_trade_warning(self):
        manager = GameManager(ExchangeEngine(), None, WarningClassifier())
        manager.games["trade-game"] = Game("4k3/8/2p5/3p4/4P3/8/8/4K3 w - - 0 1")
        with patch.dict(os.environ, {"COACH_V2_ROLLOUT_PERCENT": "0"}):
            result = manager.precheck_move("trade-game", "e4d5")
        self.assertEqual(result["label"], "Good")
        self.assertEqual(result["engine_label"], "Blunder")
        self.assertFalse(result["should_warn"])
        self.assertIsNone(result["warning_message"])


if __name__ == "__main__":
    unittest.main()
