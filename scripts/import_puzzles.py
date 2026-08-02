import urllib.request
import zstandard as zstd
import sqlite3
import csv
import io
import os
from pathlib import Path
import random

DB_PATH = Path(__file__).parent.parent / "app" / "data" / "puzzles2.db"
URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
MAX_PER_LEVEL = 5000

LEVELS = {
    1: {"themes": ["mateIn1"], "min": 600, "max": 1200},
    2: {"themes": ["mateIn2"], "min": 1000, "max": 1600},
    3: {"themes": ["fork", "pin", "skewer"], "min": 1200, "max": 1800},
    4: {"themes": ["sacrifice", "discoveredAttack"], "min": 1600, "max": 2200},
    5: {"themes": ["endgame"], "min": 1800, "max": 2400},
}

def get_level(rating, themes_str):
    puzzle_themes = set(themes_str.split())
    for lvl, cfg in LEVELS.items():
        if cfg["min"] <= rating <= cfg["max"]:
            if any(t in puzzle_themes for t in cfg["themes"]):
                return lvl
    return None

def main():
    print(f"Downloading and processing puzzles from {URL}...")
    
    os.makedirs(DB_PATH.parent, exist_ok=True)
    if DB_PATH.exists():
        os.remove(DB_PATH)
        
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE puzzles (
            puzzle_id TEXT PRIMARY KEY,
            fen TEXT NOT NULL,
            moves TEXT NOT NULL,
            rating INTEGER NOT NULL,
            themes TEXT NOT NULL
        )
    ''')
    conn.execute('CREATE INDEX idx_rating ON puzzles(rating)')
    conn.execute('CREATE INDEX idx_themes ON puzzles(themes)')
    
    # Reservoir sampling per level
    reservoirs = {lvl: [] for lvl in LEVELS}
    counts = {lvl: 0 for lvl in LEVELS}
    
    req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        dctx = zstd.ZstdDecompressor()
        with dctx.stream_reader(response) as reader:
            text_stream = io.TextIOWrapper(reader, encoding='utf-8')
            csv_reader = csv.reader(text_stream)
            
            for row in csv_reader:
                if len(row) < 8:
                    continue
                
                if row[0] == "PuzzleId":
                    continue
                    
                puzzle_id = row[0]
                fen = row[1]
                moves = row[2]
                try:
                    rating = int(row[3])
                except ValueError:
                    continue
                themes = row[7]
                
                lvl = get_level(rating, themes)
                if lvl is not None:
                    if len(reservoirs[lvl]) < MAX_PER_LEVEL:
                        reservoirs[lvl].append((puzzle_id, fen, moves, rating, themes))
                        counts[lvl] += 1
                        
                # Early exit if all levels are full
                if all(len(reservoirs[l]) >= MAX_PER_LEVEL for l in LEVELS):
                    print("All levels filled to MAX_PER_LEVEL. Stopping early.")
                    break
                    
                total_seen = sum(counts.values())
                if total_seen > 0 and total_seen % 50000 == 0:
                    print(f"Processed {total_seen} matching puzzles so far...")

    print("Finished reading. Inserting into database...")
    
    for lvl in LEVELS:
        print(f"Level {lvl}: {len(reservoirs[lvl])} puzzles (from {counts[lvl]} matching)")
        conn.executemany(
            'INSERT INTO puzzles (puzzle_id, fen, moves, rating, themes) VALUES (?, ?, ?, ?, ?)',
            reservoirs[lvl]
        )
        
    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")

if __name__ == "__main__":
    main()
