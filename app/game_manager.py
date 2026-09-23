import uuid
import hashlib
import os
import time
import chess
import chess.pgn
from typing import Dict, Optional

from .engine import StockfishEngine
from .classifier import MoveClassifier, WARN_LABELS, BOX_LABELS
from .coach_analysis import build_explanation
from .tablebase import TablebaseClient
from supabase import Client
import json


class Game:
    def __init__(self, starting_fen: Optional[str] = None, opponent_rating: int = 1500):
        self.board = chess.Board(starting_fen) if starting_fen else chess.Board()
        self.move_history = []  # [{ply, uci, san, label, cp_loss}]
        self.opponent_rating = opponent_rating
        self.last_precheck_move_uci = None
        self.last_precheck_classification = None
        self.last_analysis_id = None
        self.analyses: Dict[str, dict] = {}
        self.user_id = None

    @property
    def next_ply(self) -> int:
        """1-indexed ply number of the move about to be played."""
        return self.board.ply() + 1


class GameManager:
    def __init__(self, engine: StockfishEngine, opponent_engine: StockfishEngine, classifier: MoveClassifier, supabase: Client = None):
        self.engine = engine
        self.opponent_engine = opponent_engine
        self.classifier = classifier
        self.supabase = supabase
        self.tablebase = TablebaseClient()
        self.games: Dict[str, Game] = {}

    @staticmethod
    def _v2_enabled(game_id: str) -> bool:
        try:
            percent = max(0, min(100, int(os.getenv("COACH_V2_ROLLOUT_PERCENT", "0"))))
        except ValueError:
            percent = 0
        bucket = int(hashlib.sha256(game_id.encode()).hexdigest()[:8], 16) % 100
        return bucket < percent

    # -- lifecycle -----------------------------------------------------
    def new_game(self, starting_fen: Optional[str] = None, opponent_rating: Optional[int] = 1500, user_id: str = None) -> str:
        game_id = str(uuid.uuid4())
        game = Game(starting_fen, opponent_rating)
        game.user_id = user_id
        self.games[game_id] = game
        
        if self.supabase and user_id:
            try:
                # Clean up previous unplayed (0-move) active games for this user to prevent empty starting-board clutter
                prev_active = self.supabase.table("games").select("id, move_history").eq("user_id", user_id).eq("status", "active").execute()
                for pg in (prev_active.data or []):
                    if not pg.get("move_history") or len(pg["move_history"]) == 0:
                        self.supabase.table("games").delete().eq("id", pg["id"]).execute()

                self.supabase.table("games").insert({
                    "id": game_id,
                    "user_id": user_id,
                    "fen": game.board.fen(),
                    "status": "active",
                    "opponent_rating": opponent_rating
                }).execute()
            except Exception as e:
                print(f"Error saving game to DB: {e}")
                
        return game_id

    def get_game(self, game_id: str) -> Game:
        if game_id not in self.games:
            # Attempt to load from DB
            if self.supabase:
                try:
                    res = self.supabase.table("games").select("*").eq("id", game_id).single().execute()
                    if res.data:
                        game = Game(res.data["fen"], res.data.get("opponent_rating", 1500))
                        game.user_id = res.data["user_id"]
                        game.move_history = res.data.get("move_history", [])
                        self.games[game_id] = game
                        return game
                except Exception as e:
                    print(f"Error loading game {game_id} from DB: {e}")
            raise KeyError("Game not found")
        return self.games[game_id]

    def resume_game(self, user_id: str) -> dict:
        if not self.supabase:
            raise ValueError("Database not configured")
        
        # Find latest active game for user
        res = self.supabase.table("games").select("*").eq("user_id", user_id).eq("status", "active").order("updated_at", desc=True).limit(1).execute()
        if not res.data:
            raise KeyError("No active game found")
            
        db_game = res.data[0]
        game_id = db_game["id"]
        
        game = Game(db_game["fen"], db_game.get("opponent_rating", 1500))
        game.user_id = user_id
        game.move_history = db_game.get("move_history", [])
        self.games[game_id] = game
        
        return self.get_state(game_id)

    def get_robot_move(self, game_id: str) -> dict:
        # Note: opponent_engine is a single shared instance. If this ever needs to
        # serve multiple simultaneous games at different ratings, strength-setting
        # would race between requests. Fine for single-player; would need engine pool
        # if ever multi-user.
        game = self.get_game(game_id)
        self.opponent_engine.set_strength(game.opponent_rating)
        moves = self.opponent_engine.best_moves(game.board, n=1, time_limit=1.5)
        return {"moves": moves}

    # -- core feature: check a move BEFORE it's committed --------------
    def precheck_move(self, game_id: str, move_uci: str) -> dict:
        started = time.perf_counter()
        game = self.get_game(game_id)
        board = game.board
        move = self._parse_move(board, move_uci)
        use_v2 = self._v2_enabled(game_id)

        classification = self.classifier.classify_move(board, move, game.next_ply, use_v2=use_v2)
        evaluation_source = "stockfish"
        tablebase_reason = None
        if use_v2 and self.tablebase.eligible(board):
            before_tb = self.tablebase.probe(board)
            after_board = board.copy()
            after_board.push(move)
            after_tb = self.tablebase.probe(after_board)
            if before_tb and after_tb:
                rank = {"win": 1, "cursed-win": 1, "draw": 0, "blessed-loss": -1, "loss": -1}
                best_result = rank.get(before_tb.get("category"))
                after_for_opponent = rank.get(after_tb.get("category"))
                played_result = -after_for_opponent if after_for_opponent is not None else None
                if best_result is not None and played_result is not None:
                    evaluation_source = "tablebase"
                    if best_result == 1 and played_result == -1:
                        classification["label"] = "Worst Move"
                    elif best_result == 0 and played_result == -1:
                        classification["label"] = "Blunder"
                    elif best_result == 1 and played_result == 0:
                        classification["label"] = "Mistake"
                    if played_result < best_result:
                        tablebase_reason = "tablebase_outcome_change"
        game.last_precheck_move_uci = move_uci
        game.last_precheck_classification = classification

        result = dict(classification)
        should_warn = classification["label"] in WARN_LABELS
        is_box_tier = classification["label"] in BOX_LABELS
        result["should_warn"] = should_warn
        result["is_box_tier"] = is_box_tier
        result["threat_preview"] = None
        result["warning_message"] = None

        if should_warn:
            threat = self.engine.threat_preview(board, move, depth=10 if use_v2 else None)
            result["threat_preview"] = threat
            result["refutation_sequence"] = threat.get("resulting_pv", [])
            result["warning_message"] = self._build_warning(classification, threat, board, move)

        if use_v2:
            analysis_id = str(uuid.uuid4())
            mate_reason = tablebase_reason
            if not mate_reason and classification["label"] == "Worst Move":
                mate_reason = "missed_mate" if classification.get("best_eval_cp") == 100000 else None
            continuation = result.get("refutation_sequence") or []
            explanation = build_explanation(
                board, move, classification["label"],
                classification.get("win_probability_loss", 0), continuation,
                classification.get("best_move_san"), classification.get("game_phase", "middlegame"),
                mate_reason=mate_reason,
                opening=classification.get("opening"),
            )
            explanation["analysis_id"] = analysis_id
            if tablebase_reason:
                explanation.update({
                    "primary_reason": tablebase_reason,
                    "confidence": {"score": 1.0, "tier": "high"},
                    "summary": "This move changes the exact tablebase result.",
                    "detail": "Perfect endgame play changes the expected win, draw, or loss after this move.",
                })
            result.update({
                "analysis_version": "v2",
                "analysis_id": analysis_id,
                "evaluation_source": evaluation_source,
                "coach_explanation": explanation,
                "should_warn": explanation["interruption"]["normal"] == "popup",
                "is_box_tier": explanation["interruption"]["normal"] == "popup",
            })
            game.last_analysis_id = analysis_id
            game.analyses.clear()
            game.analyses[analysis_id] = {
                "fen": board.fen(), "move_uci": move_uci,
                "classification": classification, "result": result,
                "mate_reason": mate_reason,
                "evaluation_source": evaluation_source,
            }

        result["analysis_ms"] = round((time.perf_counter() - started) * 1000)
        print(json.dumps({
            "event": "coach_precheck",
            "game_id": game_id,
            "analysis_id": result.get("analysis_id"),
            "analysis_version": result.get("analysis_version", "v1"),
            "classification": result.get("label"),
            "evaluation_source": result.get("evaluation_source", "stockfish"),
            "duration_ms": result["analysis_ms"],
        }))

        return result

    def explain_move(self, game_id: str, move_uci: str, analysis_id: str) -> dict:
        started = time.perf_counter()
        game = self.get_game(game_id)
        cached = game.analyses.get(analysis_id)
        if not cached or cached["fen"] != game.board.fen() or cached["move_uci"] != move_uci:
            raise ValueError("This analysis is stale. Recheck the move in the current position.")
        move = self._parse_move(game.board, move_uci)
        threat = self.engine.threat_preview(game.board, move, depth=16)
        classification = cached["classification"]
        explanation = build_explanation(
            game.board, move, classification["label"],
            classification.get("win_probability_loss", 0), threat.get("resulting_pv", []),
            classification.get("best_move_san"), classification.get("game_phase", "middlegame"),
            mate_reason=cached.get("mate_reason"),
            opening=classification.get("opening"),
        )
        if cached.get("mate_reason") == "tablebase_outcome_change":
            explanation.update({
                "primary_reason": "tablebase_outcome_change",
                "confidence": {"score": 1.0, "tier": "high"},
                "summary": "This move changes the exact tablebase result.",
                "detail": "Perfect endgame play changes the expected win, draw, or loss after this move.",
            })
        explanation["analysis_id"] = analysis_id
        result = {
            "analysis_version": "v2", "analysis_id": analysis_id,
            "evaluation_source": cached.get("evaluation_source", "stockfish"),
            "coach_explanation": explanation,
            "threat_preview": threat,
            "refutation_sequence": threat.get("resulting_pv", []),
            "analysis_ms": round((time.perf_counter() - started) * 1000),
        }
        print(json.dumps({
            "event": "coach_detailed_analysis",
            "game_id": game_id,
            "analysis_id": analysis_id,
            "duration_ms": result["analysis_ms"],
        }))
        return result

    def _build_warning(self, classification, threat, board, move) -> str:
        if classification["label"] == "Opening Pawn Warning":
            return classification["explanation"]

        san = board.san(move)
        if threat and threat.get("is_mate_threat") and threat.get("mate_in"):
            return (
                f"Careful -- after {san}, your opponent has "
                f"{threat.get('opponent_best_reply_san', 'a strong reply')} "
                f"leading to mate in {abs(threat['mate_in'])}."
            )
        best_san = classification.get("best_move_san")
        reply_san = threat.get("opponent_best_reply_san", "a strong reply")
        return (
            f"{san} is a {classification['label'].lower()}. Your opponent could answer with "
            f"{reply_san}, and the evaluation swings against you. Consider {best_san} instead."
        )

    # -- committing a move ----------------------------------------------
    def commit_move(self, game_id: str, move_uci: str, analysis_id: str | None = None) -> dict:
        game = self.get_game(game_id)
        board = game.board
        move = self._parse_move(board, move_uci)

        if analysis_id and analysis_id != game.last_analysis_id:
            raise ValueError("This move analysis is stale. Please try the move again.")
        if game.last_precheck_move_uci == move_uci and game.last_precheck_classification:
            classification = game.last_precheck_classification
        else:
            classification = self.classifier.classify_move(board, move, game.next_ply)
            
        committed_analysis_id = analysis_id if analysis_id == game.last_analysis_id else None
        game.last_precheck_move_uci = None
        game.last_precheck_classification = None
        game.last_analysis_id = None
        game.analyses.clear()

        san = board.san(move)
        ply = game.next_ply
        fen_before = board.fen()
        board.push(move)

        game.move_history.append({
            "ply": ply,
            "uci": move_uci,
            "san": san,
            "classification": classification["label"],
            "cp_loss": classification["cp_loss"],
            "fen_before": fen_before,
            "analysis_version": classification.get("analysis_version", "v1"),
            "analysis_id": committed_analysis_id,
        })

        is_over = board.is_game_over()
        if self.supabase and game.user_id:
            try:
                new_status = "active"
                if is_over:
                    res = board.result()
                    if res == "1-0":
                        new_status = "win"
                    elif res == "0-1":
                        new_status = "loss"
                    else:
                        new_status = "draw"

                self.supabase.table("games").update({
                    "fen": board.fen(),
                    "move_history": game.move_history,
                    "status": new_status
                }).eq("id", game_id).execute()
            except Exception as e:
                print(f"Error updating game DB: {e}")

        return {
            "fen": board.fen(),
            "san": san,
            "classification": classification["label"],
            "is_game_over": is_over,
            "result": board.result() if is_over else None,
        }

    def undo_last_move(self, game_id: str, plies: int = 2) -> dict:
        game = self.get_game(game_id)
        if plies < 1:
            raise ValueError("plies must be at least 1")

        pops = min(plies, len(game.board.move_stack))
        for _ in range(pops):
            if len(game.board.move_stack) > 0:
                game.board.pop()
            if len(game.move_history) > 0:
                game.move_history.pop()

        # An analysis is bound to the exact pre-move position. Undo always
        # invalidates any popup or detailed-analysis request still in flight.
        game.last_precheck_move_uci = None
        game.last_precheck_classification = None
        game.last_analysis_id = None
        game.analyses.clear()
                
        if self.supabase and game.user_id:
            try:
                self.supabase.table("games").update({
                    "fen": game.board.fen(),
                    "move_history": game.move_history,
                    "status": "active"
                }).eq("id", game_id).execute()
            except Exception as e:
                print(f"Error updating game DB on undo: {e}")
                
        return self.get_state(game_id)

    def get_state(self, game_id: str) -> dict:
        game = self.get_game(game_id)
        board = game.board
        pgn_game = chess.pgn.Game.from_board(board)
        return {
            "game_id": game_id,
            "fen": board.fen(),
            "pgn": str(pgn_game),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "is_game_over": board.is_game_over(),
            "result": board.result() if board.is_game_over() else None,
            "move_history": game.move_history,
            "opponent_rating": getattr(game, 'opponent_rating', 1500),
        }

    @staticmethod
    def _parse_move(board: chess.Board, move_uci: str) -> chess.Move:
        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
            raise ValueError(f"'{move_uci}' is not a validly formatted UCI move")
        if move not in board.legal_moves:
            raise ValueError(f"'{move_uci}' is not a legal move in this position")
        return move
