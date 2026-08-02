import sqlite3
import random
import uuid
import chess
from pathlib import Path
from typing import Dict, Optional

DB_PATH = Path(__file__).parent / "data" / "puzzles2.db"

LEVELS = {
    1: {"theme": "mateIn1", "min_rating": 600, "max_rating": 1200},
    2: {"theme": "mateIn2", "min_rating": 1000, "max_rating": 1600},
    3: {"theme": "fork",    "min_rating": 1200, "max_rating": 1800},  # note: pin/skewer handled below
    4: {"theme": "sacrifice", "min_rating": 1600, "max_rating": 2200},
    5: {"theme": "endgame", "min_rating": 1800, "max_rating": 2400},
}

class PuzzleSession:
    def __init__(self, puzzle_id: str, fen: str, moves: list[str]):
        self.puzzle_id = puzzle_id
        self.board = chess.Board(fen)
        self.moves = moves          # full solution sequence, UCI
        self.solved_index = 0       # how many moves in `moves` completed so far
        # Apply the opponent's automatic setup move (moves[0]) immediately --
        # Lichess FEN is the position BEFORE this move.
        self.board.push_uci(moves[0])
        self.solved_index = 1

    @property
    def is_solved(self) -> bool:
        return self.solved_index >= len(self.moves)

    @property
    def expected_move(self) -> Optional[str]:
        return self.moves[self.solved_index] if not self.is_solved else None

class PuzzleManager:
    def __init__(self):
        self.sessions: Dict[str, PuzzleSession] = {}

    def _query_random_puzzle(self, level: int) -> tuple[str, str, str]:
        cfg = LEVELS[level]
        conn = sqlite3.connect(DB_PATH)
        # Level 3 decision locked in: match ANY of fork/pin/skewer,
        # not just "fork" alone. Other levels use a single theme.
        if level == 3:
            where_theme = "(themes LIKE '%fork%' OR themes LIKE '%pin%' OR themes LIKE '%skewer%')"
            params = (cfg["min_rating"], cfg["max_rating"])
            cur = conn.execute(
                f"SELECT puzzle_id, fen, moves FROM puzzles "
                f"WHERE {where_theme} AND rating BETWEEN ? AND ? "
                f"ORDER BY RANDOM() LIMIT 1",
                params,
            )
        else:
            cur = conn.execute(
                "SELECT puzzle_id, fen, moves FROM puzzles "
                "WHERE themes LIKE ? AND rating BETWEEN ? AND ? "
                "ORDER BY RANDOM() LIMIT 1",
                (f"%{cfg['theme']}%", cfg["min_rating"], cfg["max_rating"]),
            )
        row = cur.fetchone()
        conn.close()
        if not row:
            raise ValueError(f"No puzzles found for level {level}")
        return row  # (puzzle_id, fen, moves)

    def start_puzzle(self, level: int) -> dict:
        puzzle_id, fen, moves_str = self._query_random_puzzle(level)
        moves = moves_str.split()
        session_id = str(uuid.uuid4())
        session = PuzzleSession(puzzle_id, fen, moves)
        self.sessions[session_id] = session
        res = {
            "session_id": session_id,
            "fen": session.board.fen(),
            "side_to_move": "white" if session.board.turn else "black",
        }
        if level <= 2 and session.expected_move:
            res["first_move_source"] = session.expected_move[:2]
        return res

    def attempt_move(self, session_id: str, move_uci: str) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError("Puzzle session not found")

        if move_uci != session.expected_move:
            return {"correct": False, "fen": session.board.fen(), "solved": False}

        session.board.push_uci(move_uci)
        session.solved_index += 1

        opponent_reply = None
        if not session.is_solved:
            # Auto-play the opponent's scripted reply
            opponent_reply = session.expected_move
            session.board.push_uci(opponent_reply)
            session.solved_index += 1

        return {
            "correct": True,
            "opponent_reply_uci": opponent_reply,
            "solved": session.is_solved,
            "fen": session.board.fen(),
        }

    def get_hint_square(self, session_id: str) -> Optional[str]:
        session = self.sessions.get(session_id)
        if not session or session.is_solved:
            return None
        return session.expected_move[:2]  # origin square of the correct move
