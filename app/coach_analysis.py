"""Deterministic evidence and wording for human-readable chess coaching."""

from __future__ import annotations

import chess

PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}
PIECE_NAMES = {
    chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
    chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
}
CENTER = {chess.D4, chess.E4, chess.D5, chess.E5}
HARMFUL_POSITIONAL_FACTORS = {
    "active_piece_exchange",
    "weakened_king_defense",
    "lost_king_defender",
    "damaged_pawn_structure",
    "lost_bishop_pair",
    "loss_of_outpost",
    "lost_passed_pawn",
    "loss_of_development",
    "loss_of_tempo",
}


def game_phase(board: chess.Board, opening: dict | None = None) -> str:
    if opening or board.ply() < 12:
        return "opening"
    pieces = len(board.piece_map())
    non_pawn = sum(
        len(board.pieces(kind, color)) * PIECE_VALUES[kind]
        for color in chess.COLORS for kind in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
    )
    if pieces <= 7 or (not board.pieces(chess.QUEEN, chess.WHITE) and not board.pieces(chess.QUEEN, chess.BLACK) and non_pawn <= 20):
        return "endgame"
    return "middlegame"


def _mobility(board: chess.Board, square: chess.Square) -> int:
    piece = board.piece_at(square)
    if not piece:
        return 0
    return len(board.attacks(square) - board.occupied_co[piece.color])


def _pawn_files(board: chess.Board, color: chess.Color) -> list[int]:
    return [chess.square_file(square) for square in board.pieces(chess.PAWN, color)]


def _doubled_isolated(board: chess.Board, color: chess.Color) -> int:
    files = _pawn_files(board, color)
    doubled = sum(max(0, files.count(file) - 1) for file in set(files))
    isolated = sum(1 for file in files if file - 1 not in files and file + 1 not in files)
    return doubled + isolated


def _king_pressure(board: chess.Board, color: chess.Color) -> int:
    king = board.king(color)
    if king is None:
        return 0
    ring = board.attacks(king) | {king}
    return sum(1 for square in ring if board.is_attacked_by(not color, square))


def _king_defenders(board: chess.Board, color: chess.Color) -> int:
    king = board.king(color)
    if king is None:
        return 0
    ring = board.attacks(king) | {king}
    return sum(1 for square in ring if board.is_attacked_by(color, square))


def _passed_pawns(board: chess.Board, color: chess.Color) -> int:
    count = 0
    for square in board.pieces(chess.PAWN, color):
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        opposing = board.pieces(chess.PAWN, not color)
        blocked = False
        for enemy in opposing:
            enemy_file = chess.square_file(enemy)
            enemy_rank = chess.square_rank(enemy)
            ahead = enemy_rank > rank if color == chess.WHITE else enemy_rank < rank
            if ahead and abs(enemy_file - file) <= 1:
                blocked = True
                break
        if not blocked:
            count += 1
    return count


def _knight_outposts(board: chess.Board, color: chess.Color) -> int:
    count = 0
    enemy_pawns = board.pieces(chess.PAWN, not color)
    for square in board.pieces(chess.KNIGHT, color):
        rank = chess.square_rank(square)
        advanced = rank >= 3 if color == chess.WHITE else rank <= 4
        pawn_supported = any(
            square in board.attacks(pawn) for pawn in board.pieces(chess.PAWN, color)
        )
        pawn_chased = any(square in board.attacks(pawn) for pawn in enemy_pawns)
        if advanced and pawn_supported and not pawn_chased:
            count += 1
    return count


def _undeveloped_minor_pieces(board: chess.Board, color: chess.Color) -> int:
    home = (chess.B1, chess.G1, chess.C1, chess.F1) if color == chess.WHITE else (chess.B8, chess.G8, chess.C8, chess.F8)
    return sum(
        1 for square in home
        if (piece := board.piece_at(square))
        and piece.color == color
        and piece.piece_type in (chess.KNIGHT, chess.BISHOP)
    )


def _center_openness(board: chess.Board) -> int:
    """Higher is more open: count missing pawns on central files."""
    central_pawns = sum(
        1 for square in board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK)
        if chess.square_file(square) in (2, 3, 4, 5)
    )
    return 8 - central_pawns


def _positional_factors(before: chess.Board, after: chess.Board, mover: chess.Color, move: chess.Move) -> list[str]:
    factors: list[str] = []
    moving_piece = before.piece_at(move.from_square)
    captured_piece = before.piece_at(move.to_square)
    if moving_piece and captured_piece and moving_piece.piece_type in (chess.KNIGHT, chess.BISHOP):
        captured_mobility = _mobility(before, move.to_square)
        if _mobility(before, move.from_square) >= captured_mobility + 3:
            factors.append("active_piece_exchange")
    before_center = sum(1 for square in CENTER if before.is_attacked_by(mover, square))
    after_center = sum(1 for square in CENTER if after.is_attacked_by(mover, square))
    if after_center < before_center:
        factors.append("loss_of_central_control")
    if _king_pressure(after, mover) > _king_pressure(before, mover):
        factors.append("weakened_king_defense")
    if _king_defenders(after, mover) < _king_defenders(before, mover):
        factors.append("lost_king_defender")
    if _doubled_isolated(after, mover) > _doubled_isolated(before, mover):
        factors.append("damaged_pawn_structure")
    before_pair = len(before.pieces(chess.BISHOP, mover)) >= 2
    after_pair = len(after.pieces(chess.BISHOP, mover)) >= 2
    if before_pair and not after_pair:
        factors.append("lost_bishop_pair")
    if _knight_outposts(after, mover) < _knight_outposts(before, mover):
        factors.append("loss_of_outpost")
    if _passed_pawns(after, mover) < _passed_pawns(before, mover):
        factors.append("lost_passed_pawn")
    if _undeveloped_minor_pieces(after, mover) > _undeveloped_minor_pieces(before, mover):
        factors.append("loss_of_development")
    if before.ply() < 20 and moving_piece and move.to_square in (
        chess.B1, chess.G1, chess.C1, chess.F1, chess.B8, chess.G8, chess.C8, chess.F8,
    ):
        factors.append("loss_of_tempo")
    if _center_openness(after) > _center_openness(before):
        factors.append("opened_center")
    elif _center_openness(after) < _center_openness(before):
        factors.append("closed_center")
    return factors


def _tactical_theme(board: chess.Board, move: chess.Move) -> str | None:
    after = board.copy()
    after.push(move)
    moved = after.piece_at(move.to_square)
    if moved:
        valuable_targets = [
            square for square in after.attacks(move.to_square)
            if (piece := after.piece_at(square)) and piece.color != moved.color and PIECE_VALUES[piece.piece_type] >= 3
        ]
        if len(valuable_targets) >= 2:
            return "fork"
    opponent = after.turn
    if any(after.is_pinned(opponent, square) for square in after.piece_map() if after.color_at(square) == opponent):
        return "pin"
    return None


def _opponent_tactical_theme(board: chess.Board, candidate: chess.Move, continuation: list[str]) -> str | None:
    """Verify a tactic created by the opponent's first engine continuation."""
    if not continuation:
        return None
    probe = board.copy()
    try:
        probe.push(candidate)
        reply = chess.Move.from_uci(continuation[0])
        if reply not in probe.legal_moves:
            return None
        return _tactical_theme(probe, reply)
    except (ValueError, AssertionError):
        return None


def exchange_ledger(board: chess.Board, candidate: chess.Move, continuation: list[str], max_plies: int = 8) -> dict:
    mover = board.turn
    probe = board.copy()
    sequence = [candidate.uci(), *continuation][:max_plies]
    gained = lost = quiet = 0
    gained_pieces: list[str] = []
    lost_pieces: list[str] = []
    played: list[str] = []
    for uci in sequence:
        try:
            move = chess.Move.from_uci(uci)
            if move not in probe.legal_moves:
                break
            captured = probe.piece_at(move.to_square)
            if probe.is_en_passant(move):
                captured = chess.Piece(chess.PAWN, not probe.turn)
            checking = probe.gives_check(move)
            if captured:
                value = PIECE_VALUES[captured.piece_type]
                if probe.turn == mover:
                    gained += value
                    gained_pieces.append(PIECE_NAMES[captured.piece_type])
                else:
                    lost += value
                    lost_pieces.append(PIECE_NAMES[captured.piece_type])
                quiet = 0
            elif checking or move.promotion:
                quiet = 0
            else:
                quiet += 1
            played.append(uci)
            probe.push(move)
            if quiet >= 2:
                break
        except (ValueError, AssertionError):
            break
    complete = quiet >= 2 or probe.is_game_over()
    return {
        "gained": gained,
        "lost": lost,
        "net": gained - lost,
        "gained_pieces": gained_pieces,
        "lost_pieces": lost_pieces,
        "exchange_complete": complete,
        "plies_analyzed": len(played),
        "line": played,
    }


def interruption_policy(label: str, probability_loss: float, confidence: float, reason: str) -> dict:
    severe = label in {"Mistake", "Blunder", "Worst Move"}
    instructive = label == "Inaccuracy" and probability_loss >= 4 and confidence >= 0.65 and reason != "complex_engine_preference"
    return {
        "normal": "popup" if severe or instructive else ("audio" if label == "Inaccuracy" else "none"),
        "professional": "popup" if severe else ("audio" if label == "Inaccuracy" else "none"),
        "roast": "popup" if severe or instructive else ("audio" if label == "Inaccuracy" else "none"),
        "off": "none",
    }


def is_benign_exchange(explanation: dict) -> bool:
    """Return true only for a verified, settled trade with no adverse evidence.

    This deliberately works for every piece type. It is used to prevent a
    shallow engine fluctuation from turning a plain pawn, minor-piece, rook,
    queen, or mixed-material exchange into a misleading warning.
    """
    material = explanation.get("material") or {}
    factors = set(explanation.get("positional_factors") or [])
    return bool(
        material.get("exchange_complete")
        and material.get("gained", 0) > 0
        and material.get("lost", 0) > 0
        and material.get("net", 0) >= 0
        and not explanation.get("tactical_theme")
        and explanation.get("primary_reason") not in {
            "missed_mate", "allows_mate", "tablebase_outcome_change", "king_danger",
        }
        and not factors.intersection(HARMFUL_POSITIONAL_FACTORS)
    )


def build_explanation(
    board: chess.Board, move: chess.Move, label: str, probability_loss: float,
    continuation: list[str], best_move_san: str | None, phase: str,
    mate_reason: str | None = None, opening: dict | None = None,
) -> dict:
    after = board.copy()
    after.push(move)
    material = exchange_ledger(board, move, continuation)
    factors = _positional_factors(board, after, board.turn, move)
    tactic = _opponent_tactical_theme(board, move, continuation)

    if mate_reason:
        reason, confidence = mate_reason, 1.0
    elif material["exchange_complete"] and material["net"] < 0:
        reason, confidence = "material_loss", 0.95
    elif (
        material["exchange_complete"]
        and material["gained"]
        and material["net"] == 0
        and set(factors).intersection(HARMFUL_POSITIONAL_FACTORS)
    ):
        reason, confidence = "equal_but_unfavorable_exchange", 0.82
    elif tactic:
        reason, confidence = tactic, 0.9
    elif "weakened_king_defense" in factors:
        reason, confidence = "king_danger", 0.78
    elif "damaged_pawn_structure" in factors:
        reason, confidence = "damaged_pawn_structure", 0.74
    elif "loss_of_outpost" in factors:
        reason, confidence = "loss_of_outpost", 0.74
    elif "loss_of_development" in factors:
        reason, confidence = "loss_of_development", 0.7
    elif "loss_of_tempo" in factors:
        reason, confidence = "loss_of_tempo", 0.68
    elif "loss_of_central_control" in factors:
        reason, confidence = "lost_initiative", 0.68
    elif opening and phase == "opening":
        reason, confidence = "opening_principle", 0.7
    else:
        reason, confidence = "complex_engine_preference", 0.4

    best_text = f" Consider {best_move_san} instead." if best_move_san else ""
    if reason == "material_loss" and confidence >= 0.85:
        pieces = material["lost_pieces"]
        lost = pieces[0] if len(pieces) == 1 else "material"
        summary = f"The analyzed line leaves you down a {lost}."
        follow_up = f"This continuation loses a {lost} without enough material in return.{best_text}"
    elif reason == "equal_but_unfavorable_exchange":
        summary = "The material stays equal, but the exchange worsens your position."
        follow_up = f"The trade is equal in material, but it gives up your more useful piece.{best_text}"
    elif (
        material["exchange_complete"]
        and material["gained"] > 0
        and material["lost"] > 0
        and material["net"] >= 0
        and not set(factors).intersection(HARMFUL_POSITIONAL_FACTORS)
        and not tactic
    ):
        summary = "This is a balanced material exchange."
        follow_up = "The analyzed capture sequence finishes without a verified material or positional loss."
    elif reason == "king_danger":
        summary = "This move increases the pressure around your king."
        follow_up = f"The continuation weakens your king's protection.{best_text}"
    elif reason == "damaged_pawn_structure":
        summary = "This continuation damages your pawn structure."
        follow_up = f"The trade leaves weaker or isolated pawns behind.{best_text}"
    elif reason == "loss_of_outpost":
        summary = "This move gives up a useful knight outpost."
        follow_up = f"Your knight loses a protected square where enemy pawns could not challenge it.{best_text}"
    elif reason == "loss_of_development":
        summary = "This move puts one of your developed pieces back."
        follow_up = f"You lose development time while the opponent can improve another piece.{best_text}"
    elif reason == "loss_of_tempo":
        summary = "This move loses time in the opening."
        follow_up = f"The piece returns home instead of helping your development.{best_text}"
    elif reason in {"missed_mate", "allows_mate"}:
        summary = "This move mishandles a forced checkmate."
        follow_up = "The engine sees a forced mating sequence in this position."
    elif tactic:
        summary = f"This line allows a {tactic}."
        follow_up = f"The opponent's continuation uses a {tactic} to gain an advantage.{best_text}"
    else:
        summary = "Stockfish prefers another move, but there is no verified immediate material loss."
        follow_up = f"The engine prefers a different continuation.{best_text}"

    immediate = {
        "Inaccuracy": "Hold on. Think about other moves. There may be a better option.",
        "Mistake": "This is a mistake. Take your time and think about this position.",
        "Blunder": "That is a blunder.",
        "Worst Move": "That is a serious blunder.",
    }.get(label, f"{label}.")
    tier = "high" if confidence >= 0.85 else "medium" if confidence >= 0.65 else "low"
    return {
        "primary_reason": reason,
        "confidence": {"score": round(confidence, 2), "tier": tier},
        "summary": summary,
        "detail": follow_up,
        "material": material,
        "tactical_theme": tactic,
        "positional_factors": factors,
        "principal_variation": continuation[:8],
        "speech": {"immediate": immediate, "follow_up": follow_up},
        "interruption": interruption_policy(label, probability_loss, confidence, reason),
    }
