# Chess Mistake Coach — Backend

FastAPI backend that wraps the Stockfish engine to power a chess app which
tells you about a mistake **before** you commit to a move.

## What it does

- **Book moves (plies 1-3):** flagged as `Book`, no deep analysis needed.
- **From ply 4 onward:** every candidate move is analyzed and classified:
  `Brilliant`, `Best Move`, `Excellent`, `Good`, `Inaccuracy`, `Mistake`,
  `Blunder`, `Worst Move`.
- **Pre-move warning:** call `/api/move/precheck` with a move *before*
  playing it. If it's bad (Inaccuracy or worse), the response includes:
  - a plain-English warning message
  - a **threat preview**: the opponent's best reply and the resulting
    evaluation (or "mate in N" if it's a mating threat)
  - the top 3 engine alternatives, so the UI can suggest better moves
- **Commit endpoint:** once the player confirms (heeding the warning or
  not), `/api/move/commit` actually plays the move and updates game state.

## Setup

### 1. Install Stockfish (the engine binary itself)

```bash
# Ubuntu/Debian
sudo apt-get install stockfish

# macOS
brew install stockfish

# Or download a binary directly:
# https://stockfishchess.org/download/
```

Note where the binary lives (`which stockfish` on Linux/macOS).

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Point the app at your Stockfish binary (if not on PATH)

```bash
export STOCKFISH_PATH=/usr/games/stockfish   # adjust to your system
```

### 4. Run the server

```bash
uvicorn app.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for interactive Swagger docs.

## API Reference

### `POST /api/game/new`
Starts a new game. Body: `{ "starting_fen": null }` (optional custom FEN).
Returns the initial game state including `game_id`.

### `POST /api/move/precheck`  ⭐ core feature
Body:
```json
{ "game_id": "...", "move_uci": "e2e4" }
```
Response:
```json
{
  "label": "Blunder",
  "cp_loss": 220,
  "explanation": "...",
  "best_move_san": "Nf3",
  "top_alternatives": [ ... ],
  "should_warn": true,
  "warning_message": "Careful -- after ..., your opponent has ... leading to mate in 3.",
  "threat_preview": {
    "opponent_best_reply_san": "Qxh7#",
    "resulting_pv": ["..."],
    "is_mate_threat": true,
    "mate_in": 3
  }
}
```
Call this the moment the user drops a piece on the board, **before**
actually moving it. If `should_warn` is true, show the character's
speech-bubble warning and let the user choose to proceed or pick a
different move.

### `POST /api/move/commit`
Actually plays the move once the player has decided. Body identical to
precheck. Updates the server-side board and returns the new FEN/PGN.

### `GET /api/game/{game_id}/state`
Full current game state: FEN, PGN, move history with each move's label.

### `GET /api/engine/best-moves/{game_id}?n=3`
Standalone "suggest a good move" endpoint, independent of any move the
player is currently considering.

## Project structure

```
chess-mistake-coach/
├── requirements.txt
├── README.md
└── app/
    ├── __init__.py
    ├── main.py           # FastAPI routes
    ├── engine.py          # Stockfish UCI wrapper
    ├── classifier.py      # move classification logic (book/blunder/brilliant...)
    ├── game_manager.py    # in-memory game state + orchestration
    └── schemas.py         # request/response models
```

## Notes / next steps

- Game state is **in-memory** (a Python dict) — fine for a prototype, but
  swap in Redis or a DB before going multi-instance/production.
- `MoveClassifier._is_brilliant_candidate` is a heuristic (sacrifice +
  still-best-move + not-already-winning). Real "brilliant" detection
  (like chess.com's) is genuinely hard; treat this as a reasonable v1.
- The opening "book" is currently a small hardcoded set of common first
  moves. For real opening coverage, swap in a polyglot `.bin` book or an
  ECO-code lookup table.
- Consider adding a WebSocket endpoint if you want live analysis to
  stream in as Stockfish deepens its search, instead of waiting for a
  fixed depth.
