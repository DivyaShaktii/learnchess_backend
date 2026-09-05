from pydantic import BaseModel, Field
from typing import List, Optional


class NewGameRequest(BaseModel):
    starting_fen: Optional[str] = None
    opponent_rating: Optional[int] = 1500  # 1320-3190, default mid-range
    user_id: Optional[str] = None


class PreMoveCheckRequest(BaseModel):
    game_id: str
    move_uci: str  # e.g. "e2e4"


class MoveAlternative(BaseModel):
    move: Optional[str] = None
    san: Optional[str] = None
    score_cp: Optional[int] = None
    is_mate: bool = False
    mate_in: Optional[int] = None
    pv: List[str] = Field(default_factory=list)


class ThreatPreview(BaseModel):
    opponent_best_reply: Optional[str] = None
    opponent_best_reply_san: Optional[str] = None
    resulting_pv: List[str] = Field(default_factory=list)
    score_after_reply_cp: Optional[int] = None
    is_mate_threat: bool = False
    mate_in: Optional[int] = None


class PreMoveCheckResponse(BaseModel):
    label: str
    cp_loss: int
    explanation: str
    played_eval_cp: Optional[int] = None
    best_eval_cp: Optional[int] = None
    best_move_uci: Optional[str] = None
    best_move_san: Optional[str] = None
    top_alternatives: List[MoveAlternative] = Field(default_factory=list)
    threat_preview: Optional[ThreatPreview] = None
    refutation_sequence: Optional[List[str]] = None
    should_warn: bool = False
    is_box_tier: bool = False
    warning_message: Optional[str] = None


class CommitMoveRequest(BaseModel):
    game_id: str
    move_uci: str


class CommitMoveResponse(BaseModel):
    fen: str
    san: str
    classification: str
    is_game_over: bool
    result: Optional[str] = None


class GameStateResponse(BaseModel):
    game_id: str
    fen: str
    pgn: str
    turn: str
    is_game_over: bool
    result: Optional[str] = None
    move_history: List[dict] = Field(default_factory=list)
    opponent_rating: Optional[int] = None

class StartPuzzleRequest(BaseModel):
    level: int  # 1-5

class PuzzleAttemptRequest(BaseModel):
    session_id: str
    move_uci: str

class PuzzleStateResponse(BaseModel):
    session_id: Optional[str] = None
    fen: str
    side_to_move: Optional[str] = None
    correct: Optional[bool] = None
    opponent_reply_uci: Optional[str] = None
    solved: Optional[bool] = None
    first_move_source: Optional[str] = None

class CreateOrderRequest(BaseModel):
    user_id: str

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    user_id: str
