"""Boss Event system for DCC Chess (Chunk 3 Part 3).

Stage A: compass-roll movement. Each round, after both players finish their
turns, both players roll 1d6; the sum maps to a compass direction the boss
moves in. Direction is fixed relative to the board, not to either player:
North always means toward row 10 (Black's back rank).
"""

import random
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from .board import BOARD_SIZE

if TYPE_CHECKING:
    from .abilities import GameState


# (row_delta, col_delta). North = toward row 10, East = toward column 10.
COMPASS_DELTAS: Dict[str, Tuple[int, int]] = {
    "N": (1, 0),
    "NE": (1, 1),
    "E": (0, 1),
    "SE": (-1, 1),
    "S": (-1, 0),
    "SW": (-1, -1),
    "W": (0, -1),
    "NW": (1, -1),
}

SUM_TO_DIRECTION: Dict[int, Optional[str]] = {
    2: "N", 3: "NE", 4: "E", 5: "SE", 6: "S", 7: "SW", 8: "W", 9: "NW",
    10: None, 11: None, 12: None,
}

# Squares moved per boss turn. Anything not listed here moves 1.
BOSS_MOVE_DISTANCE: Dict[str, int] = {
    "Goblin Murder Dozer": 2,
}


def direction_for_sum(total: int) -> Optional[str]:
    """Compass direction for a combined two-die roll, or None for 10-12 (no movement)."""
    return SUM_TO_DIRECTION.get(total)


def _kill_piece_at(gs: "GameState", row: int, col: int) -> None:
    piece = gs.board.get(row, col)
    if piece is None:
        return
    gs.board.set(row, col, None)
    piece.permanently_dead = True
    gs.board.captured[piece.color].append(piece)
    gs.log_event("boss_movement_kill", piece=repr(piece), pos=[row, col])


def _squares_in_bounds(squares: List[Tuple[int, int]]) -> bool:
    return all(0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE for r, c in squares)


def resolve_boss_movement(gs: "GameState") -> Dict:
    """Sum the two stored boss-turn rolls and move the boss accordingly.

    Any piece (either color) on a square the boss lands on OR passes through
    (relevant for bosses that move more than 1 square) is permanently killed.
    Clears gs.boss_turn_rolls / gs.boss_turn_active as a side effect. Always
    logs a terminal event ("boss_moved" or "boss_no_movement") describing the
    outcome, which the frontend uses to drive the movement animation.
    """
    white_roll = gs.boss_turn_rolls.get("white")
    black_roll = gs.boss_turn_rolls.get("black")
    total = (white_roll or 0) + (black_roll or 0)
    direction = direction_for_sum(total)

    gs.boss_turn_rolls = {"white": None, "black": None}
    gs.boss_turn_active = False

    if not gs.boss_active or gs.boss_position is None:
        gs.log_event("boss_no_movement", white_roll=white_roll, black_roll=black_roll,
                     total=total, direction=direction, reason="no_boss_active")
        return {"moved": False, "direction": direction, "total": total}

    if direction is None:
        gs.log_event("boss_no_movement", boss=gs.active_boss, white_roll=white_roll,
                     black_roll=black_roll, total=total, direction=None, reason="rolled_10_to_12")
        return {"moved": False, "direction": None, "total": total}

    old_position = gs.boss_position
    old_squares = list(gs.boss_squares)
    dr, dc = COMPASS_DELTAS[direction]
    distance = BOSS_MOVE_DISTANCE.get(gs.active_boss, 1)

    # Every square the boss's shape sweeps through, one step at a time, so
    # multi-square movers (Goblin Murder Dozer) kill pieces they pass through
    # as well as the square they land on.
    swept_square_sets: List[List[Tuple[int, int]]] = []
    for step in range(1, distance + 1):
        step_squares = [(r + dr * step, c + dc * step) for (r, c) in old_squares]
        if not _squares_in_bounds(step_squares):
            gs.log_event("boss_no_movement", boss=gs.active_boss, white_roll=white_roll,
                         black_roll=black_roll, total=total, direction=direction,
                         reason="would_leave_board")
            return {"moved": False, "direction": direction, "total": total}
        swept_square_sets.append(step_squares)

    for step_squares in swept_square_sets:
        for (r, c) in step_squares:
            _kill_piece_at(gs, r, c)

    final_squares = swept_square_sets[-1]
    gs.boss_position = final_squares[0]
    gs.boss_squares = final_squares

    gs.log_event("boss_moved", boss=gs.active_boss, direction=direction, distance=distance,
                 white_roll=white_roll, black_roll=black_roll, total=total,
                 from_pos=list(old_position), to_pos=list(gs.boss_position),
                 from_squares=[list(s) for s in old_squares],
                 to_squares=[list(s) for s in final_squares])

    return {
        "moved": True,
        "direction": direction,
        "total": total,
        "from_pos": list(old_position),
        "to_pos": list(gs.boss_position),
        "to_squares": [list(s) for s in final_squares],
    }
