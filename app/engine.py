"""
Thin wrapper around the Stockfish UCI engine using python-chess.

Requires a Stockfish binary installed on the machine:
  - Ubuntu/Debian: sudo apt-get install stockfish
  - macOS:         brew install stockfish
  - Or download directly from https://stockfishchess.org/download/

Set the STOCKFISH_PATH env var to point at the binary if it's not
on your PATH (e.g. STOCKFISH_PATH=/usr/games/stockfish).
"""

import logging
import os
import chess
import chess.engine
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

def _find_stockfish() -> str:
    """Return STOCKFISH_PATH env var if set, otherwise look for the stockfish
    binary next to this file or in the parent directory, then fall back to PATH."""
    if "STOCKFISH_PATH" in os.environ:
        return os.environ["STOCKFISH_PATH"]
    # Look for stockfish binary beside engine.py or one level up (Backend/)
    here = Path(__file__).parent
    candidates = [
        here / "stockfish",
        here.parent / "stockfish",
        here / "stockfish.exe",
        here.parent / "stockfish.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return "stockfish"  # fall back to PATH

STOCKFISH_PATH = _find_stockfish()
CP_MATE = 100_000


import threading

class StockfishEngine:
    def __init__(self, path: str = STOCKFISH_PATH, depth: int = 14,
                 threads: int = 2, hash_mb: int = 128):
        self.path = path
        self.depth = depth
        self.threads = threads
        self.hash_mb = hash_mb
        self.lock = threading.Lock()
        self.engine = None
        self._start_engine(raise_on_failure=False)

    def _start_engine(self, raise_on_failure: bool = True):
        import stat
        if os.name != 'nt' and os.path.exists(self.path):
            try:
                st = os.stat(self.path)
                os.chmod(self.path, st.st_mode | stat.S_IEXEC)
            except Exception:
                pass
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(self.path)
            self.engine.configure({"Threads": self.threads, "Hash": self.hash_mb})
        except FileNotFoundError as e:
            self.engine = None
            message = (
                f"Could not find Stockfish binary at '{self.path}'. "
                f"Install Stockfish and/or set the STOCKFISH_PATH env var."
            )
            if raise_on_failure:
                raise RuntimeError(message) from e
            logger.warning(
                "%s The engine will be started lazily on first use.", message
            )

    def _ensure_engine(self):
        """Lazily (re)start the underlying Stockfish process if it isn't
        running yet, raising a clear error if the binary truly can't be found."""
        if self.engine is None:
            self._start_engine(raise_on_failure=True)

    def set_strength(self, elo: Optional[int]):
        """Limit this engine instance's playing strength to the given Elo
        (1320-3190), or pass None to restore full strength."""
        self._ensure_engine()
        with self.lock:
            if elo is not None:
                elo = max(1320, min(3190, elo))
                self.engine.configure({"UCI_LimitStrength": True, "UCI_Elo": elo})
            else:
                self.engine.configure({"UCI_LimitStrength": False})

    def _safe_analyse(self, board: chess.Board, limit: chess.engine.Limit, multipv: Optional[int] = None):
        """Thread-safe engine analysis with automatic process recovery.

        Validates the board first so an illegal position raises ValueError
        rather than crashing the Stockfish process.
        """
        # Sanity-check the board before handing it to the engine.
        # An invalid board (e.g. from a race-condition double-commit) would
        # cause the engine to crash and leave isRobotThinking stuck = True.
        status = board.status()
        if status != chess.STATUS_VALID:
            raise ValueError(
                f"Invalid board position (status={status:#x}, fen={board.fen()}). "
                "Cannot analyse."
            )

        self._ensure_engine()
        with self.lock:
            try:
                if multipv:
                    return self.engine.analyse(board, limit, multipv=multipv)
                return self.engine.analyse(board, limit)
            except chess.engine.EngineError:
                # Engine crashed — restart it then retry once.
                try:
                    self.engine.quit()
                except Exception:
                    pass
                self._start_engine()
                if multipv:
                    return self.engine.analyse(board, limit, multipv=multipv)
                return self.engine.analyse(board, limit)
            except Exception as e:
                try:
                    self.engine.quit()
                except Exception:
                    pass
                self._start_engine()
                raise

    def close(self):
        with self.lock:
            try:
                if self.engine is not None:
                    self.engine.quit()
            except Exception:
                pass

    def best_moves(self, board: chess.Board, n: int = 3, depth: Optional[int] = None) -> List[dict]:
        """Top-N candidate moves with evaluation, from the mover's perspective.

        Uses whichever limit fires first: the configured depth OR 1.5 s.
        This keeps the robot responsive while still playing decent moves.
        Move-quality analysis (precheck/commit) uses pure depth limits for accuracy.
        """
        limit = chess.engine.Limit(depth=depth or self.depth, time=1.5)
        multipv = min(n, board.legal_moves.count()) or 1
        infos = self._safe_analyse(board, limit, multipv=multipv)
        if isinstance(infos, dict):
            infos = [infos]

        results = []
        for info in infos:
            if not isinstance(info, dict) or "score" not in info:
                continue
            pv = info.get("pv", [])
            move = pv[0] if pv else None
            score = info["score"].pov(board.turn)
            results.append({
                "move": move.uci() if move else None,
                "san": board.san(move) if move and move in board.legal_moves else (move.uci() if move else None),
                "score_cp": score.score(mate_score=CP_MATE),
                "is_mate": score.is_mate(),
                "mate_in": score.mate() if score.is_mate() else None,
                "pv": [m.uci() for m in pv[:5]],
            })
        return results

    def score_after_move(self, board: chess.Board, move: chess.Move,
                          depth: Optional[int] = None) -> chess.engine.PovScore:
        """Evaluate the resulting position, from the perspective of the player
        who just moved (so we can compare it directly to their pre-move best score)."""
        new_board = board.copy()
        new_board.push(move)
        limit = chess.engine.Limit(depth=depth or self.depth)
        info = self._safe_analyse(new_board, limit)
        return info["score"].pov(board.turn)

    def threat_preview(self, board: chess.Board, move: chess.Move,
                        depth: Optional[int] = None) -> dict:
        """Simulate playing `move`, then find the opponent's best reply --
        this is the 'here's how you could get punished' preview."""
        new_board = board.copy()
        new_board.push(move)
        limit = chess.engine.Limit(depth=depth or self.depth)
        info = self._safe_analyse(new_board, limit)
        pv = info.get("pv", [])
        reply = pv[0] if pv else None
        score = info["score"].pov(board.turn)  # from original mover's perspective
        return {
            "opponent_best_reply": reply.uci() if reply else None,
            "opponent_best_reply_san": new_board.san(reply) if reply else None,
            "resulting_pv": [m.uci() for m in pv[:6]],
            "score_after_reply_cp": score.score(mate_score=CP_MATE),
            "is_mate_threat": score.is_mate(),
            "mate_in": score.mate() if score.is_mate() else None,
        }

