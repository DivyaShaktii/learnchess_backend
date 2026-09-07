from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

import sys
import asyncio
import chess
import os
import json
import razorpay
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv(override=True)

razorpay_key_id = os.getenv("RAZORPAY_KEY_ID", "rzp_test_TTYOP1jpVr4bFq")
razorpay_key_secret = os.getenv("RAZORPAY_KEY_SECRET", "2bxfsCA8tTg4CEbNdmwSoeSH")
razorpay_webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

# Razorpay client will be instantiated per-request to avoid stale connection pools
def get_razorpay_client():
    return razorpay.Client(auth=(razorpay_key_id, razorpay_key_secret))


supabase_url: str = os.getenv("SUPABASE_URL", "https://ipwanamxxugjtpksotxq.supabase.co")
supabase_key: str = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlwd2FuYW14eHVnanRwa3NvdHhxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1ODAzNzYsImV4cCI6MjEwMzE1NjM3Nn0.qUDvpcGryR07yaAXPkxZYUfadM9C37wDRInEYOoSf-U")
supabase: Client = create_client(supabase_url, supabase_key)

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from .engine import StockfishEngine
from .classifier import MoveClassifier
from .game_manager import GameManager
from .analytics import calculate_rating_adjustment
from .schemas import (
    NewGameRequest, PreMoveCheckRequest, PreMoveCheckResponse,
    CommitMoveRequest, CommitMoveResponse, GameStateResponse,
    StartPuzzleRequest, PuzzleAttemptRequest, PuzzleStateResponse,
    CreateOrderRequest, VerifyPaymentRequest,
)

from .puzzle_manager import PuzzleManager

engine: StockfishEngine = None
opponent_engine: StockfishEngine = None
manager: GameManager = None
puzzle_manager = PuzzleManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, opponent_engine, manager
    engine = StockfishEngine(depth=14)
    opponent_engine = StockfishEngine(depth=14)
    classifier = MoveClassifier(engine)
    manager = GameManager(engine, opponent_engine, classifier, supabase=supabase)
    yield
    engine.close()
    opponent_engine.close()


app = FastAPI(title="Chess Mistake Coach API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your frontend's origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/game/new")
def new_game(req: NewGameRequest):
    game_id = manager.new_game(req.starting_fen, req.opponent_rating, req.user_id)
    return manager.get_state(game_id)


@app.get("/api/game/{game_id}/state", response_model=GameStateResponse)
def get_state(game_id: str):
    try:
        return manager.get_state(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found")


@app.post("/api/game/{game_id}/undo")
def undo_move(game_id: str, plies: int = 2):
    try:
        return manager.undo_last_move(game_id, plies=plies)
    except KeyError:
        raise HTTPException(404, "Game not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/move/precheck", response_model=PreMoveCheckResponse)
def precheck_move(req: PreMoveCheckRequest):
    """Core feature: call this BEFORE committing a move. Returns the move's
    classification (Book / Best / Brilliant / Inaccuracy / Mistake / Blunder...),
    and if it's a bad move, a threat preview + alternatives so the UI can
    warn the player before they confirm."""
    try:
        return manager.precheck_move(req.game_id, req.move_uci)
    except KeyError:
        raise HTTPException(404, "Game not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/move/commit", response_model=CommitMoveResponse)
def commit_move(req: CommitMoveRequest):
    """Call this once the player has confirmed they want to play the move
    (whether or not they heeded the warning)."""
    try:
        res = manager.commit_move(req.game_id, req.move_uci)
        
        # Check if game over to update rating
        if res["is_game_over"]:
            game = manager.get_game(req.game_id)
            if game.user_id:
                try:
                    # Fetch current rating
                    prof = supabase.table("profiles").select("predicted_rating").eq("id", game.user_id).single().execute()
                    current_rating = prof.data.get("predicted_rating", 1500) if prof.data else 1500
                    
                    # Calculate new rating
                    new_rating = calculate_rating_adjustment(current_rating, game.move_history)
                    
                    # Update DB
                    supabase.table("profiles").update({"predicted_rating": new_rating}).eq("id", game.user_id).execute()
                except Exception as e:
                    print(f"Error updating rating: {e}")
                    
        return res
    except KeyError:
        raise HTTPException(404, "Game not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/engine/best-moves/{game_id}")
def best_moves(game_id: str, n: int = 3):
    """Standalone 'show me good options' endpoint -- independent of any
    specific move the player is considering. Guaranteed to only return safe moves (cp_loss <= 25)."""
    try:
        game = manager.get_game(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found")
    
    # Query up to 5 candidates so we can find all genuinely good options across pieces
    raw_moves = engine.best_moves(game.board, n=max(5, n))
    if not raw_moves:
        return {"moves": []}

    best_cp = raw_moves[0].get("score_cp", 0)
    best_mate = raw_moves[0].get("is_mate", False)

    safe_moves = []
    for idx, m in enumerate(raw_moves):
        m_cp = m.get("score_cp", best_cp)
        m_mate = m.get("is_mate", False)
        cp_loss = manager.classifier._cp_loss(best_cp, m_cp, best_mate, m_mate)
        m_copy = dict(m)
        m_copy["cp_loss"] = cp_loss
        m_copy["is_safe"] = (idx == 0 or cp_loss <= 40)
        if idx == 0 or cp_loss <= 40:
            safe_moves.append(m_copy)
            if len(safe_moves) >= n:
                break

    return {"moves": safe_moves}


@app.get("/api/engine/robot-move/{game_id}")
def robot_move(game_id: str):
    """Returns the opponent's move, played at the game's configured
    rating -- separate from the full-strength analysis engine."""
    try:
        return manager.get_robot_move(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found")


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/game/resume")
def resume_game(user_id: str):
    try:
        return manager.resume_game(user_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/api/user/profile")
def user_profile(user_id: str):
    print(f"Fetching user profile for {user_id}")
    try:
        # Get profile data
        try:
            prof = supabase.table("profiles").select("*").eq("id", user_id).single().execute()
            data = prof.data if prof.data else {}
        except Exception as e:
            # If profile doesn't exist yet, we'll just return a default
            data = {"id": user_id, "predicted_rating": 1500}
        
        # Get games played this week (active or completed)
        try:
            games_res = supabase.table("games").select("id", count="exact").eq("user_id", user_id).execute()
            total_games = games_res.count if hasattr(games_res, 'count') and games_res.count is not None else len(games_res.data)
        except Exception:
            total_games = 0
            
        data["total_games"] = total_games
        return data
    except Exception as e:
        print(f"Error in user_profile: {e}")
        raise HTTPException(500, str(e))

@app.get("/api/user/games")
def user_games(user_id: str):
    try:
        res = supabase.table("games").select("id, status, opponent_rating, created_at, fen, move_history").eq("user_id", user_id).order("created_at", desc=True).limit(50).execute()
        # Only include played games (completed, or active with at least 1 move made)
        valid_games = [
            g for g in (res.data or [])
            if (g.get("status") in ("win", "loss", "draw")) or (g.get("move_history") and len(g.get("move_history")) > 0)
        ]
        return {"games": valid_games}
    except Exception as e:
        raise HTTPException(500, str(e))



@app.post("/api/puzzles/start")
def start_puzzle(req: StartPuzzleRequest):
    try:
        return puzzle_manager.start_puzzle(req.level)
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.post("/api/puzzles/attempt")
def attempt_puzzle(req: PuzzleAttemptRequest):
    try:
        return puzzle_manager.attempt_move(req.session_id, req.move_uci)
    except KeyError:
        raise HTTPException(404, "Puzzle session not found")

@app.get("/api/puzzles/hint/{session_id}")
def puzzle_hint(session_id: str):
    square = puzzle_manager.get_hint_square(session_id)
    return {"hint_square": square}

@app.get("/api/puzzles/random")
def random_puzzle(level: int = 1):
    puzzle_id, fen, moves_str = puzzle_manager._query_random_puzzle(level)
    
    uci_moves = moves_str.split()
    board = chess.Board(fen)
    classified_moves = []
    
    for i, uci in enumerate(uci_moves):
        move = chess.Move.from_uci(uci)
        ply = board.ply()
        
        try:
            classification = manager.classifier.classify_move(board, move, ply)
            label = classification["label"]
        except Exception as e:
            label = "Best Move"
            
        board.push(move)
        
        classified_moves.append({
            "uci": uci,
            "classification": label
        })

    return {
        "puzzle_id": puzzle_id,
        "fen": fen,
        "moves": classified_moves
    }

@app.post("/api/payment/create-order")
def create_order(req: CreateOrderRequest):
    try:
        data = {
            "amount": 100, # 1 INR in paise
            "currency": "INR",
            "receipt": req.user_id,
            "notes": {
                "user_id": req.user_id,
            }
        }
        client = get_razorpay_client()
        order = client.order.create(data=data)
        return {"order_id": order["id"], "amount": 100, "currency": "INR"}
    except Exception as e:
        print("RAZORPAY ERROR:", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(500, str(e))

@app.post("/api/payment/verify")
def verify_payment(req: VerifyPaymentRequest):
    try:
        client = get_razorpay_client()
        client.utility.verify_payment_signature({
            'razorpay_order_id': req.razorpay_order_id,
            'razorpay_payment_id': req.razorpay_payment_id,
            'razorpay_signature': req.razorpay_signature
        })

        if req.user_id:
            try:
                supabase.table("profiles").update({"is_premium": True}).eq("id", req.user_id).execute()
                print(f"[Payment Verify] Successfully updated user {req.user_id} to premium in Supabase.")
            except Exception as se:
                print("[Payment Verify] DB update notice:", se)
        
        return {"status": "success"}
    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(400, "Invalid signature")
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/payment/webhook")
async def razorpay_webhook(request: Request):
    """
    Razorpay Webhook endpoint.
    Listens for 'payment.captured' and 'order.paid' events.
    Verifies signature (if RAZORPAY_WEBHOOK_SECRET is configured)
    and automatically marks the user as premium in Supabase.
    """
    try:
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")
        signature = request.headers.get("x-razorpay-signature") or request.headers.get("X-Razorpay-Signature")

        if razorpay_webhook_secret:
            if not signature:
                raise HTTPException(400, "Missing X-Razorpay-Signature header")
            client = get_razorpay_client()
            client.utility.verify_webhook_signature(body_str, signature, razorpay_webhook_secret)

        event_data = json.loads(body_str)
        event_type = event_data.get("event")
        print(f"[Razorpay Webhook] Received event: {event_type}")

        if event_type in ("payment.captured", "order.paid"):
            payload = event_data.get("payload", {})
            payment_entity = payload.get("payment", {}).get("entity", {})
            order_entity = payload.get("order", {}).get("entity", {})

            # Extract user_id from notes, receipt, or description
            user_id = (
                payment_entity.get("notes", {}).get("user_id")
                or order_entity.get("notes", {}).get("user_id")
                or order_entity.get("receipt")
                or payment_entity.get("description")
            )

            if user_id:
                print(f"[Razorpay Webhook] Marking user {user_id} as is_premium=True...")
                supabase.table("profiles").update({"is_premium": True}).eq("id", user_id).execute()
                print(f"[Razorpay Webhook] User {user_id} is now Premium!")
            else:
                print("[Razorpay Webhook] Warning: Could not locate user_id in payload.")

        return {"status": "ok"}
    except razorpay.errors.SignatureVerificationError:
        print("[Razorpay Webhook] Signature verification failed!")
        raise HTTPException(400, "Invalid webhook signature")
    except Exception as e:
        print(f"[Razorpay Webhook] Error processing webhook: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, str(e))
