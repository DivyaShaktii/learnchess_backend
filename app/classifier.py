"""
Move classification engine.

Move quality is primarily based on centipawn loss, but labels that carry
extra meaning use extra evidence. Severity uses change in expected winning
chances, not a flat CP table, so the same CP loss matters much more in an
equal position than it does when one side is already overwhelmingly ahead:
  - Book requires a known opening move that is also engine-sound.
  - Best Move requires the engine's first choice.
  - Brilliant requires a best/near-best move plus a sound material sacrifice.
"""

import math
import chess
from .engine import StockfishEngine, CP_MATE
from .opening_book import OpeningBook
from .coach_analysis import game_phase

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

class MoveClassifier:
    def __init__(self, engine: StockfishEngine, book_ply_limit: int = 6, opening_book: OpeningBook | None = None):
        self.engine = engine
        self.book_ply_limit = book_ply_limit
        self.opening_book = opening_book or OpeningBook()

    def classify_move(self, board: chess.Board, move: chess.Move, ply_number: int, use_v2: bool = False) -> dict:
        san = board.san(move)
        uci = move.uci()

        played_english = self._san_to_english(board, move, san)
        
        # Always analyse first. Opening heuristics must never hide a real mistake.
        # Captures are especially vulnerable to shallow horizon noise. Give
        # exchanges two extra plies so both the best line and played move are
        # compared after the likely recapture sequence has had time to settle.
        exchange_depth = 16 if board.is_capture(move) else None
        top_lines = self.engine.best_moves(board, n=5, depth=exchange_depth)
        if not top_lines or top_lines[0]["move"] is None:
            return {
                "label": LABELS["BEST"], "cp_loss": 0,
                "best_move_san": san, "best_move_uci": uci,
                "top_alternatives": [], "explanation": "No alternative lines found.",
            }

        best_cp = top_lines[0]["score_cp"]
        best_is_mate = top_lines[0]["is_mate"]
        best_uci = top_lines[0]["move"]

        # Evaluate the position that actually results from the played move.
        played_score = self.engine.score_after_move(board, move, depth=exchange_depth)
        played_cp = played_score.score(mate_score=CP_MATE)
        played_is_mate = played_score.is_mate()

        cp_loss = self._cp_loss(best_cp, played_cp, best_is_mate, played_is_mate)
        best_win_probability = self._win_probability(best_cp)
        played_win_probability = self._win_probability(played_cp)
        win_probability_loss = max(0.0, best_win_probability - played_win_probability)
        is_top_move = (uci == best_uci)
        opening_match = self.opening_book.identify_after(board, move)
        phase = game_phase(board, opening_match.as_dict() if opening_match else None)
        second_cp = top_lines[1]["score_cp"] if len(top_lines) > 1 else best_cp
        second_probability = self._win_probability(second_cp)
        alternative_gap = max(0.0, best_win_probability - second_probability)

        if use_v2:
            label = self._label_v2(
                cp_loss, win_probability_loss, alternative_gap, is_top_move,
                board, move, played_cp, best_cp, best_is_mate,
                played_is_mate, top_lines, phase,
            )
        else:
            label = self._label_from_cp_loss(
                cp_loss, win_probability_loss, is_top_move, board, move,
                played_cp, best_cp, best_is_mate, played_is_mate, top_lines
            )

        if use_v2 and opening_match and cp_loss <= 30 and win_probability_loss <= 2.5 and label not in {
            LABELS["BRILLIANT"], "Only Move", "Great Move"
        }:
            label = LABELS["BOOK"]
        elif not use_v2 and ply_number <= self.book_ply_limit:
            piece = board.piece_at(move.from_square)
            is_wing_pawn = (
                piece is not None
                and piece.piece_type == chess.PAWN
                and chess.square_file(move.from_square) in (0, 1, 6, 7)
            )
            if is_wing_pawn and cp_loss >= 40:
                label = LABELS["OPENING_PAWN_WARNING"]
            elif uci in BOOK_MOVES_UCI and cp_loss <= 25:
                label = LABELS["BOOK"]

        try:
            best_english = self._san_to_english(board, chess.Move.from_uci(best_uci), top_lines[0]["san"]) if best_uci else ""
        except Exception:
            best_english = top_lines[0].get("san", "") if top_lines else ""

        safe_alternatives = []
        for idx, alt in enumerate(top_lines):
            alt_cp = alt.get("score_cp", best_cp)
            alt_mate = alt.get("is_mate", False)
            alt_loss = self._cp_loss(best_cp, alt_cp, best_is_mate, alt_mate)
            alt_copy = dict(alt)
            alt_copy["cp_loss"] = alt_loss
            alt_copy["is_safe"] = (idx == 0 or alt_loss <= 40)
            if idx == 0 or alt_loss <= 40:
                safe_alternatives.append(alt_copy)
                if len(safe_alternatives) >= 3:
                    break

        return {
            "label": label,
            "cp_loss": cp_loss,
            "played_eval_cp": played_cp,
            "best_eval_cp": best_cp,
            "best_move_uci": best_uci,
            "best_move_san": top_lines[0]["san"],
            "best_win_probability": round(best_win_probability, 2),
            "played_win_probability": round(played_win_probability, 2),
            "win_probability_loss": round(win_probability_loss, 2),
            "alternative_gap": round(alternative_gap, 2),
            "game_phase": phase,
            "opening": opening_match.as_dict() if opening_match else None,
            "analysis_version": "v2" if use_v2 else "v1",
            "top_alternatives": safe_alternatives,
            "explanation": self._explain(
                label, played_english, best_english, cp_loss, win_probability_loss
            ),
        }

    def _label_v2(
        self, cp_loss, probability_loss, alternative_gap, is_top_move,
        board, move, played_cp, best_cp, best_is_mate, played_is_mate,
        top_lines, phase,
    ) -> str:
        if (best_is_mate and not played_is_mate) or (played_is_mate and played_cp < 0):
            return LABELS["WORST"]
        if self._is_brilliant_candidate(board, move, cp_loss, played_cp, best_cp, top_lines):
            # A brilliant move must also be meaningfully difficult to replace.
            if alternative_gap >= 4 or best_is_mate:
                return LABELS["BRILLIANT"]
        if is_top_move:
            if alternative_gap >= 10:
                return "Only Move"
            if alternative_gap >= 4:
                return "Great Move"
            if alternative_gap >= 1:
                return LABELS["BEST"]
            return LABELS["EXCELLENT"]

        thresholds = {
            "opening": (1.5, 30, 4, 8, 16, 30),
            "middlegame": (1, 20, 2.5, 7, 15, 30),
            "endgame": (1, 20, 2.5, 5, 10, 20),
        }[phase]
        excellent_wp, excellent_cp, good, inaccurate, mistake, blunder = thresholds
        if probability_loss <= excellent_wp and cp_loss <= excellent_cp:
            return LABELS["EXCELLENT"]
        if probability_loss <= good:
            return LABELS["GOOD"]
        if probability_loss <= inaccurate:
            return LABELS["INACCURACY"]
        if probability_loss <= mistake:
            return LABELS["MISTAKE"]
        if probability_loss <= blunder:
            return LABELS["BLUNDER"]
        return LABELS["WORST"]

    @staticmethod
    def _win_probability(cp: int) -> float:
        """Convert mover-relative evaluation to expected score (0-100).

        This is the Lichess/scalachess logistic evaluation curve, clamped at
        +/-1000cp where practical winning chances have saturated.
        """
        bounded_cp = max(-1000, min(1000, cp))
        return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * bounded_cp)) - 1)

    def _cp_loss(self, best_cp, played_cp, best_mate, played_mate) -> int:
        if best_mate and not played_mate:
            return 1000  # threw away a forced mate
        if not best_mate and played_mate and played_cp < 0:
            return 2000  # walked into getting mated
        return max(0, best_cp - played_cp)

    def _label_from_cp_loss(
        self, cp_loss, win_probability_loss, is_top_move, board, move,
        played_cp, best_cp, best_is_mate, played_is_mate, top_lines
    ) -> str:
        if self._is_brilliant_candidate(
            board, move, cp_loss, played_cp, best_cp, top_lines
        ):
            return LABELS["BRILLIANT"]
        if is_top_move:
            return LABELS["BEST"]
        if (best_is_mate and not played_is_mate) or (
            played_is_mate and played_cp < 0
        ):
            return LABELS["WORST"]
        if cp_loss <= 20 and win_probability_loss <= 1:
            return LABELS["EXCELLENT"]
        if win_probability_loss <= 2.5:
            return LABELS["GOOD"]
        if win_probability_loss <= 7:
            return LABELS["INACCURACY"]
        if win_probability_loss <= 15:
            return LABELS["MISTAKE"]
        if win_probability_loss <= 30:
            return LABELS["BLUNDER"]
        return LABELS["WORST"]

    def _is_brilliant_candidate(
        self, board: chess.Board, move: chess.Move, cp_loss: int,
        played_cp: int, best_cp: int, top_lines: list[dict]
    ) -> bool:
        """Return true only for an engine-sound material sacrifice.

        CP loss alone cannot make a move brilliant. The move must remain within
        15 cp of the engine's best evaluation and intentionally concede at least
        two material points either immediately or in the validated principal
        variation. Positions that remain clearly losing are excluded.
        """
        probability_loss = self._win_probability(best_cp) - self._win_probability(played_cp)
        if cp_loss > 15 or probability_loss > 1 or played_cp < -100 or best_cp < -100 or best_cp > 1000:
            return False

        piece_values = {
            chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
            chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
        }
        moving_piece = board.piece_at(move.from_square)
        if moving_piece is None:
            return False
        if board.move_stack and board.is_capture(move) and board.peek().to_square == move.to_square:
            # Simply taking back the piece captured on the previous move is an
            # ordinary recapture, not an intentional sacrifice.
            return False
        captured = board.piece_at(move.to_square)
        gives_up_value = piece_values.get(moving_piece.piece_type, 0)
        gains_value = piece_values.get(captured.piece_type, 0) if captured else 0

        temp_board = board.copy()
        temp_board.push(move)
        can_be_captured = any(
            reply.to_square == move.to_square and temp_board.is_capture(reply)
            for reply in temp_board.legal_moves
        )
        direct_sacrifice = can_be_captured and gives_up_value - gains_value >= 2

        mover = board.turn
        initial_balance = self._material_balance(board, mover, piece_values)
        matching_line = next(
            (line for line in top_lines if line.get("move") == move.uci()), None
        )
        variation = (matching_line or {}).get("pv", [])[:8]
        variation_board = board.copy()
        for uci in variation:
            try:
                variation_board.push_uci(uci)
            except (ValueError, AssertionError):
                break
        settled_balance = self._material_balance(variation_board, mover, piece_values)
        variation_sacrifice = bool(variation) and initial_balance - settled_balance >= 2
        # The candidate itself must deliberately offer the moved piece for at
        # least a two-point concession. Material dropped by some unrelated
        # later move in the PV cannot make an ordinary pawn trade Brilliant.
        return direct_sacrifice and (variation_sacrifice if variation else True)

    @staticmethod
    def _material_balance(board: chess.Board, color: chess.Color, piece_values: dict) -> int:
        own = sum(
            len(board.pieces(piece_type, color)) * value
            for piece_type, value in piece_values.items()
        )
        opponent = sum(
            len(board.pieces(piece_type, not color)) * value
            for piece_type, value in piece_values.items()
        )
        return own - opponent

    def _explain(self, label, played_san, best_san, cp_loss, win_probability_loss) -> str:
        if label == LABELS["BRILLIANT"]:
            return f"{played_san} is a sound sacrifice that preserves the best continuation."
        if label in (LABELS["BOOK"], LABELS["BEST"]):
            return f"{played_san} is a great choice."
        if label == LABELS["OPENING_PAWN_WARNING"]:
            return "That early wing-pawn move loses time. Develop a piece or contest the center instead."
        return (
            f"{played_san} reduces expected winning chances by about "
            f"{win_probability_loss:.1f} percentage points ({cp_loss} centipawns) "
            f"compared with {best_san}."
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
