import uuid
import chess
import chess.pgn
from typing import Dict, Optional

from .engine import StockfishEngine
from .classifier import MoveClassifier, WARN_LABELS, BOX_LABELS


class Game:
    def __init__(self, starting_fen: Optional[str] = None, opponent_rating: Optional[int] = 1500):
        self.board = chess.Board(starting_fen) if starting_fen else chess.Board()
        self.move_history = []  # [{ply, uci, san, label, cp_loss}]
        self.opponent_rating = opponent_rating

    @property
    def next_ply(self) -> int:
        """1-indexed ply number of the move about to be played."""
        return len(self.board.move_stack) + 1


class GameManager:
    def __init__(self, engine: StockfishEngine, opponent_engine: StockfishEngine, classifier: MoveClassifier):
        self.engine = engine
        self.opponent_engine = opponent_engine
        self.classifier = classifier
        self.games: Dict[str, Game] = {}

    # -- lifecycle -----------------------------------------------------
    def new_game(self, starting_fen: Optional[str] = None, opponent_rating: Optional[int] = 1500) -> str:
        game_id = str(uuid.uuid4())
        self.games[game_id] = Game(starting_fen, opponent_rating)
        return game_id

    def get_game(self, game_id: str) -> Game:
        if game_id not in self.games:
            raise KeyError("Game not found")
        return self.games[game_id]

    def get_robot_move(self, game_id: str) -> dict:
        # Note: opponent_engine is a single shared instance. If this ever needs to
        # serve multiple simultaneous games at different ratings, strength-setting
        # would race between requests. Fine for single-player; would need engine pool
        # if ever multi-user.
        game = self.get_game(game_id)
        self.opponent_engine.set_strength(game.opponent_rating)
        moves = self.opponent_engine.best_moves(game.board, n=1)
        return {"moves": moves}

    # -- core feature: check a move BEFORE it's committed --------------
    def precheck_move(self, game_id: str, move_uci: str) -> dict:
        game = self.get_game(game_id)
        board = game.board
        move = self._parse_move(board, move_uci)

        classification = self.classifier.classify_move(board, move, game.next_ply)

        result = dict(classification)
        should_warn = classification["label"] in WARN_LABELS
        is_box_tier = classification["label"] in BOX_LABELS
        result["should_warn"] = should_warn
        result["is_box_tier"] = is_box_tier
        result["threat_preview"] = None
        result["warning_message"] = None

        if should_warn:
            threat = self.engine.threat_preview(board, move)
            result["threat_preview"] = threat
            result["refutation_sequence"] = threat.get("resulting_pv", [])
            result["warning_message"] = self._build_warning(classification, threat, board, move)

        return result

    def _build_warning(self, classification, threat, board, move) -> str:
        san = board.san(move)
        if threat.get("is_mate_threat") and threat.get("mate_in"):
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
    def commit_move(self, game_id: str, move_uci: str) -> dict:
        game = self.get_game(game_id)
        board = game.board
        move = self._parse_move(board, move_uci)

        classification = self.classifier.classify_move(board, move, game.next_ply)
        san = board.san(move)
        ply = game.next_ply
        board.push(move)

        game.move_history.append({
            "ply": ply,
            "uci": move_uci,
            "san": san,
            "classification": classification["label"],
            "cp_loss": classification["cp_loss"],
            "fen_before": board.fen(),
        })

        return {
            "fen": board.fen(),
            "san": san,
            "classification": classification["label"],
            "is_game_over": board.is_game_over(),
            "result": board.result() if board.is_game_over() else None,
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
