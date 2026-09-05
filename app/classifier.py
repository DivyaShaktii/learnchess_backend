"""
Move classification engine.

Mirrors the category system you described:
  1. Early plies (1-3)         -> "Book"      (known opening theory)
  2. Ply 4-5 onward             -> real analysis kicks in, blunders start
                                    getting flagged with a pre-move warning
  3. Rest of the game           -> every move gets a label along a spectrum:
                                    Brilliant / Best / Excellent / Good /
                                    Inaccuracy / Mistake / Blunder / Worst

Classification is centipawn-loss based (the standard approach used by
chess.com / lichess-style analysis): we compare the engine's evaluation
of the position after the played move vs. after its own top choice.
"""

import chess
from typing import Optional
from .engine import StockfishEngine, CP_MATE

LABELS = {
    "BOOK": "Book",
    "BEST": "Best Move",
    "BRILLIANT": "Brilliant",
    "EXCELLENT": "Excellent",
    "GOOD": "Good",
    "INACCURACY": "Inaccuracy",
    "MISTAKE": "Mistake",
    "BLUNDER": "Blunder",
    "WORST": "Worst Move",
    "OPENING_PAWN_WARNING": "Opening Pawn Warning",
    "OPENING_PRINCIPLE": "Opening Principle",
}

# A small, extensible opening book of common first moves (uci) for both
# colors. Extend this freely, or swap in a real opening-book/ECO lookup later.
BOOK_MOVES_UCI = {
    "e2e4", "e7e5", "d2d4", "d7d5", "g1f3", "b8c6", "c2c4", "g8f6",
    "e7e6", "c7c5", "d7d6", "g7g6", "b1c3", "f8b4", "f1c4", "f8c5",
    "c7c6", "b7b6", "g2g3", "f2f4", "b8a6", "g8h6",
}

WARN_LABELS = {LABELS["INACCURACY"], LABELS["MISTAKE"], LABELS["BLUNDER"], LABELS["WORST"], LABELS["OPENING_PAWN_WARNING"]}
BOX_LABELS = {LABELS["INACCURACY"], LABELS["MISTAKE"], LABELS["BLUNDER"], LABELS["WORST"], LABELS["OPENING_PAWN_WARNING"]}

import random

class MoveClassifier:
    def __init__(self, engine: StockfishEngine, book_ply_limit: int = 3):
        self.engine = engine
        self.book_ply_limit = book_ply_limit

    def classify_move(self, board: chess.Board, move: chess.Move, ply_number: int) -> dict:
        san = board.san(move)
        uci = move.uci()

        played_english = self._san_to_english(board, move, san)
        
        # 1) Book-move shortcut for the opening
        if ply_number <= self.book_ply_limit:
            piece = board.piece_at(move.from_square)
            if piece and piece.piece_type == chess.PAWN:
                file_idx = chess.square_file(move.from_square)
                if file_idx in (0, 1, 6, 7): # a, b, g, h
                    return {
                        "label": LABELS["OPENING_PAWN_WARNING"],
                        "cp_loss": 50,
                        "best_move_san": san,
                        "best_move_uci": uci,
                        "top_alternatives": [],
                        "explanation": "Build your minor pieces.",
                    }

            if uci in BOOK_MOVES_UCI:
                msg = random.choice(["Build your minor pieces.", "Develop your center."])
                return {
                    "label": LABELS["OPENING_PRINCIPLE"],
                    "cp_loss": 0,
                    "best_move_san": san,
                    "best_move_uci": uci,
                    "top_alternatives": [],
                    "explanation": msg,
                }
        # 2) Ask the engine for its top lines from the current position
        top_lines = self.engine.best_moves(board, n=3)
        if not top_lines or top_lines[0]["move"] is None:
            return {
                "label": LABELS["BEST"], "cp_loss": 0,
                "best_move_san": san, "best_move_uci": uci,
                "top_alternatives": [], "explanation": "No alternative lines found.",
            }

        best_cp = top_lines[0]["score_cp"]
        best_is_mate = top_lines[0]["is_mate"]
        best_uci = top_lines[0]["move"]

        # 3) Evaluate the position that actually results from the played move
        played_score = self.engine.score_after_move(board, move)
        played_cp = played_score.score(mate_score=CP_MATE)
        played_is_mate = played_score.is_mate()

        cp_loss = self._cp_loss(best_cp, played_cp, best_is_mate, played_is_mate)
        is_top_move = (uci == best_uci)

        label = self._label_from_cp_loss(cp_loss, is_top_move, board, move, played_cp)

        try:
            best_english = self._san_to_english(board, chess.Move.from_uci(best_uci), top_lines[0]["san"]) if best_uci else ""
        except Exception:
            best_english = top_lines[0].get("san", "") if top_lines else ""

        return {
            "label": label,
            "cp_loss": cp_loss,
            "played_eval_cp": played_cp,
            "best_eval_cp": best_cp,
            "best_move_uci": best_uci,
            "best_move_san": top_lines[0]["san"],
            "top_alternatives": top_lines,
            "explanation": self._explain(label, played_english, best_english, cp_loss),
        }

    def _cp_loss(self, best_cp, played_cp, best_mate, played_mate) -> int:
        if best_mate and not played_mate:
            return 1000  # threw away a forced mate
        if not best_mate and played_mate and played_cp < 0:
            return 2000  # walked into getting mated
        return max(0, best_cp - played_cp)

    def _label_from_cp_loss(self, cp_loss, is_top_move, board, move, played_cp) -> str:
        if is_top_move:
            return LABELS["GOOD"]
        if cp_loss <= 25:
            return LABELS["GOOD"]
        if cp_loss <= 60:
            return LABELS["INACCURACY"]
        if cp_loss <= 150:
            return LABELS["MISTAKE"]
        if cp_loss <= 300:
            return LABELS["BLUNDER"]
        return LABELS["WORST"]

    def _is_brilliant_candidate(self, board: chess.Board, move: chess.Move, played_cp: int) -> bool:
        """Heuristic 'brilliant' detector: the engine's top choice, it gives up
        material, the sacrificed piece is left on an attacked square, and the
        position wasn't already completely winning beforehand (so it's a real
        turning point, not just mopping up)."""
        piece_values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
        moving_piece = board.piece_at(move.from_square)
        if moving_piece is None:
            return False
        captured = board.piece_at(move.to_square)
        gives_up_value = piece_values.get(moving_piece.piece_type, 0)
        gains_value = piece_values.get(captured.piece_type, 0) if captured else 0

        temp_board = board.copy()
        temp_board.push(move)
        is_attacked = temp_board.is_attacked_by(not board.turn, move.to_square)

        sacrifices = is_attacked and gives_up_value > gains_value
        not_already_crushing = abs(played_cp) < 600
        return sacrifices and not_already_crushing

    def _explain(self, label, played_san, best_san, cp_loss) -> str:
        if label in (LABELS["BOOK"], LABELS["BEST"], LABELS["BRILLIANT"]):
            return f"{played_san} is a great choice."
        return (
            f"{played_san} gives up roughly {cp_loss} centipawns of advantage "
            f"compared to the strongest move here, {best_san}."
        )

    def _san_to_english(self, board: chess.Board, move: chess.Move, san: str) -> str:
        piece = board.piece_at(move.from_square)
        if not piece: return san
        
        piece_names = {
            chess.PAWN: "Pawn", chess.KNIGHT: "Knight", chess.BISHOP: "Bishop",
            chess.ROOK: "Rook", chess.QUEEN: "Queen", chess.KING: "King"
        }
        name = piece_names.get(piece.piece_type, "")
        
        # Castling
        if san in ("O-O", "O-O-O"):
            return "Kingside Castling" if san == "O-O" else "Queenside Castling"

        to_sq = chess.square_name(move.to_square)
        if "x" in san:
            return f"{name} captures on {to_sq}"
        
        return f"{name} to {to_sq}"
