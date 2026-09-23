"""Position-based ECO lookup backed by a pinned Lichess CC0 snapshot."""

from dataclasses import dataclass
from pathlib import Path
import csv
import chess


@dataclass(frozen=True)
class OpeningInfo:
    eco: str
    name: str
    family: str
    variation: str | None

    def as_dict(self) -> dict:
        return {
            "eco": self.eco,
            "name": self.name,
            "family": self.family,
            "variation": self.variation,
        }


def normalized_epd(board: chess.Board) -> str:
    fields = board.fen().split()
    # Lichess opening EPD includes legal en-passant squares and omits clocks.
    return " ".join(fields[:4])


class OpeningBook:
    def __init__(self, data_path: Path | None = None):
        self.data_path = data_path or Path(__file__).with_name("data") / "openings.tsv"
        self._positions: dict[str, OpeningInfo] = {}
        self._load()

    def _load(self) -> None:
        if not self.data_path.exists():
            return
        with self.data_path.open(encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source, delimiter="\t"):
                epd = row.get("epd", "").strip()
                name = row.get("name", "").strip()
                if not epd or not name:
                    continue
                family, separator, rest = name.partition(":")
                self._positions[epd] = OpeningInfo(
                    eco=row.get("eco", "").strip(),
                    name=name,
                    family=family.strip(),
                    variation=rest.strip() if separator else None,
                )

    def identify(self, board: chess.Board) -> OpeningInfo | None:
        probe = board.copy(stack=True)
        while True:
            match = self._positions.get(normalized_epd(probe))
            if match:
                return match
            if not probe.move_stack:
                return None
            probe.pop()

    def identify_after(self, board: chess.Board, move: chess.Move) -> OpeningInfo | None:
        probe = board.copy(stack=True)
        probe.push(move)
        return self.identify(probe)

