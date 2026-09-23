"""Bounded, failure-safe client for the public Lichess Syzygy service."""

from collections import OrderedDict
import json
import threading
import time
from urllib.parse import urlencode
from urllib.request import urlopen
import chess


class TablebaseClient:
    def __init__(self, timeout: float = 0.75, cache_size: int = 512, ttl: int = 86400):
        self.timeout = timeout
        self.cache_size = cache_size
        self.ttl = ttl
        self._cache: OrderedDict[str, tuple[float, dict | None]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def eligible(board: chess.Board) -> bool:
        return len(board.piece_map()) <= 7 and not board.has_castling_rights(chess.WHITE) and not board.has_castling_rights(chess.BLACK)

    def probe(self, board: chess.Board) -> dict | None:
        if not self.eligible(board):
            return None
        # Half-move/full-move clocks do not change a Syzygy result. Omitting
        # them makes positions reached through different histories share the
        # same bounded cache entry.
        key = " ".join(board.fen().split()[:4])
        now = time.time()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < self.ttl:
                self._cache.move_to_end(key)
                return cached[1]
        try:
            url = "https://tablebase.lichess.org/standard?" + urlencode({"fen": key})
            with urlopen(url, timeout=self.timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
            result = {
                "category": value.get("category"),
                "dtz": value.get("dtz"),
                "dtm": value.get("dtm"),
                "checkmate": bool(value.get("checkmate")),
                "source": "tablebase",
            }
        except Exception:
            result = None
        with self._lock:
            self._cache[key] = (now, result)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return result
