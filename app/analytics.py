from typing import List, Dict

def calculate_rating_adjustment(current_rating: int, move_history: List[Dict]) -> int:
    """
    Calculates a new predicted rating based on the average centipawn (CP) loss
    of the moves played in the game.
    """
    if not move_history:
        return current_rating
        
    valid_moves = [m for m in move_history if 'cp_loss' in m and m['cp_loss'] is not None]
    
    if not valid_moves:
        return current_rating
        
    total_cp_loss = sum(m['cp_loss'] for m in valid_moves)
    avg_cp_loss = total_cp_loss / len(valid_moves)
    
    # Very basic heuristic:
    # 0-15 avg CP loss: Grandmaster level, increase rating significantly
    # 15-30: Master level, increase slightly
    # 30-50: Club player, no change or slight decrease
    # >50: Beginner, decrease rating
    
    if avg_cp_loss <= 15:
        adjustment = 15
    elif avg_cp_loss <= 30:
        adjustment = 5
    elif avg_cp_loss <= 50:
        adjustment = -5
    else:
        adjustment = -15
        
    new_rating = max(400, current_rating + adjustment) # Floor at 400
    return new_rating
