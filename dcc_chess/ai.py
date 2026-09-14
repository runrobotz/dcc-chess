"""AI players for DCC Chess simulation.

Provides two AI implementations:
- Random AI: picks random legal moves and randomly attempts abilities.
- Smart AI: uses positional evaluation (checkmate > capture > avoid > advance)
  and context-aware ability spending.
"""

import copy
import random
import time
from collections import deque
from typing import List, Tuple, Optional, Dict

from .pieces import Piece, PieceType, Color
from .board import Board, BOARD_SIZE, PAWN_ROSTER
from .dice import DungeonDice
from .abilities import GameState
from .pawns import PAWN_CHARACTERS, AbilityTrigger
from .movement import (is_checkmate, is_in_check, is_square_attacked, is_stalemate,
                       all_legal_moves, pseudo_legal_moves_for_piece)

# How many of the AI's own most-recent resulting board positions smart_move()
# remembers, for repetition avoidance (see _deprioritize_repeated_positions).
AI_POSITION_HISTORY_LEN = 6


# Piece value table for smart AI
PIECE_VALUES: Dict[PieceType, int] = {
    PieceType.CARL: 1000,
    PieceType.DONUT: 9,
    PieceType.SAMANTHA: 5,
    PieceType.MONGO: 3,
    PieceType.KATIA: 3,
    PieceType.PAWN: 1,
    PieceType.DUNGEON_BOSS: 9,
}

# Strategic weight added on top of an ability's floor cost when
# smart_abilities() ranks major-piece candidates against each other. Positive
# for abilities only offered when there's a genuine tactical reason to use
# them (a real precondition, not just affordability); negative for generic
# filler abilities with little or no precondition, so they act as a last
# resort rather than a default pick. Absent (0) for every pawn ability --
# this only re-weights the major-piece set.
MAJOR_PRIORITY_BONUS: Dict[str, int] = {
    "plot_armor": 20,   # only offered while Carl is in check
    "rampage": 6,
    "she_tank": 6,
    "slut_shame": 6,
    "cockroach": 4,
    "puddle_jump": 3,
    "pet_carrier": 0,
    "leader": -3,        # eats every remaining die -- deliberate use only
    "blitzed": -5,        # no real precondition -- filler
    "miss_me": -8,         # only offered when dice are already weak -- last resort
}


def random_draft(count: int = 8) -> List[str]:
    """Draft unique pawns from the roster. Default 8 per player.

    "The AI" is never draftable in any game mode, so it's excluded from the pool.
    """
    draftable = [name for name in PAWN_ROSTER if name != "The AI"]
    return random.sample(draftable, count)


def random_back_rank() -> List[int]:
    """Pick 8 random columns out of 10 for major piece placement."""
    return sorted(random.sample(range(BOARD_SIZE), 8))


def random_move(game_state: GameState, legal_moves: List[Tuple]) -> Tuple:
    """Pick a random legal move."""
    return random.choice(legal_moves)


def random_abilities(game_state: GameState, dice: DungeonDice, color: Color):
    """Randomly attempt abilities with available dice.

    Strategy: iterate through all pieces, try to use abilities when dice are available.
    Order is randomized so no piece is always prioritized.
    """
    if dice.remaining_count == 0:
        return

    pieces = game_state.board.all_pieces(color)
    random.shuffle(pieces)

    for row, col, piece in pieces:
        if dice.remaining_count == 0:
            break

        if game_state.is_piece_suppressed(row, col):
            continue

        # Global Game Settings toggles apply to the AI too.
        if piece.is_pawn and not getattr(game_state, "pawns_enabled", True):
            continue
        if not piece.is_pawn and not getattr(game_state, "major_abilities_enabled", True):
            continue

        # Major piece abilities
        if piece.piece_type == PieceType.CARL:
            _try_carl_abilities(game_state, dice, (row, col), piece)
        elif piece.piece_type == PieceType.DONUT:
            _try_donut_abilities(game_state, dice, (row, col), piece)
        elif piece.piece_type == PieceType.MONGO:
            _try_mongo_abilities(game_state, dice, (row, col), piece)
        elif piece.piece_type == PieceType.KATIA:
            _try_katia_abilities(game_state, dice, (row, col), piece)
        elif piece.piece_type == PieceType.SAMANTHA:
            _try_samantha_abilities(game_state, dice, (row, col), piece)
        elif piece.is_pawn and piece.pawn_name:
            _try_pawn_ability(game_state, dice, (row, col), piece)


def _try_carl_abilities(gs: GameState, dice: DungeonDice, pos: Tuple[int, int], piece: Piece):
    """Try Carl's abilities randomly."""
    if dice.remaining_count == 0:
        return

    # 50% chance to try Bulldozer if dice available
    if random.random() < 0.5:
        idx = dice.get_best_die_for_floor(4)
        if idx is not None:
            gs.try_bulldozer(pos, dice, idx)
            # Note: Bulldozer grants extra moves but AI already moved.
            # In a real game this would be used before moving.
            # For simulation purposes, the ability fires and is logged.


def _try_donut_abilities(gs: GameState, dice: DungeonDice, pos: Tuple[int, int], piece: Piece):
    """Try Donut's abilities randomly."""
    if dice.remaining_count == 0:
        return

    abilities = []
    if random.random() < 0.6:
        abilities.append("diva")
    if not gs.resurrection_used[piece.color] and gs.board.captured[piece.color]:
        if random.random() < 0.7:
            abilities.append("resurrect")

    random.shuffle(abilities)
    for ab in abilities:
        if dice.remaining_count == 0:
            break
        if ab == "diva":
            idx = dice.get_best_die_for_floor(3)
            if idx is not None:
                # Pick a random adjacent square as phantom threat
                r, c = pos
                adj = [(r + dr, c + dc) for dr in [-1, 0, 1] for dc in [-1, 0, 1]
                       if (dr != 0 or dc != 0) and gs.board.in_bounds(r + dr, c + dc)]
                if adj:
                    gs.try_divas_entrance(pos, dice, idx, random.choice(adj))
        elif ab == "resurrect":
            idx = dice.get_best_die_for_floor(6)
            if idx is not None:
                gs.try_resurrection(pos, dice, idx, piece.color)


def _try_mongo_abilities(gs: GameState, dice: DungeonDice, pos: Tuple[int, int], piece: Piece):
    """Try Mongo's abilities randomly."""
    if dice.remaining_count == 0:
        return

    abilities = []
    if random.random() < 0.4:
        abilities.append("charge")
    if random.random() < 0.5:
        abilities.append("smash")

    random.shuffle(abilities)
    for ab in abilities:
        if dice.remaining_count == 0:
            break
        if ab == "charge":
            idx = dice.get_best_die_for_floor(4)
            if idx is not None:
                gs.try_rampaging_charge(pos, dice, idx)
        elif ab == "smash":
            idx = dice.get_best_die_for_floor(3)
            if idx is not None:
                gs.try_mongo_smash(pos, dice, idx)


def _try_katia_abilities(gs: GameState, dice: DungeonDice, pos: Tuple[int, int], piece: Piece):
    """Try Katia's abilities randomly."""
    if dice.remaining_count == 0:
        return

    if random.random() < 0.4:
        idx = dice.get_best_die_for_floor(3)
        if idx is not None:
            retreats = gs.try_combat_roll(pos, dice, idx)
            if retreats:
                # Execute retreat
                dest = random.choice(retreats)
                gs.board.set(pos[0], pos[1], None)
                gs.board.set(dest[0], dest[1], piece)

    if dice.remaining_count > 0 and random.random() < 0.4:
        idx = dice.get_best_die_for_floor(5)
        if idx is not None:
            r, c = pos
            adj = [(r + dr, c + dc) for dr in [-2, -1, 0, 1, 2] for dc in [-2, -1, 0, 1, 2]
                   if (dr != 0 or dc != 0) and gs.board.in_bounds(r + dr, c + dc)]
            if adj:
                gs.try_dual_threat(pos, dice, idx, random.choice(adj))


def _try_samantha_abilities(gs: GameState, dice: DungeonDice, pos: Tuple[int, int], piece: Piece):
    """Try Samantha's abilities randomly."""
    if dice.remaining_count == 0:
        return

    # The Mouth: reroll a die (do this first since it improves other rolls)
    if not gs.mouth_used_this_turn and random.random() < 0.6:
        idx = dice.get_best_die_for_floor(3)
        if idx is not None:
            gs.try_the_mouth(pos, dice, idx)

    if dice.remaining_count == 0:
        return

    # Portal Spike
    if random.random() < 0.3:
        idx = dice.get_best_die_for_floor(5)
        if idx is not None:
            gs.try_portal_spike(pos, dice, idx)


def _pick_chris_direction(gs: GameState, pos: Tuple[int, int]) -> Optional[str]:
    """Pick a valid Lava Surge direction for Chris, or None if neither is valid."""
    for direction in ("horizontal", "vertical"):
        if gs.chris_lava_surge_direction_valid(pos, direction):
            return direction
    return None


def _try_pawn_ability(gs: GameState, dice: DungeonDice, pos: Tuple[int, int], piece: Piece):
    """Try a pawn's ability based on its character."""
    if dice.remaining_count == 0:
        return

    name = piece.pawn_name

    # Juice Box has no ability of her own -- she uses one of the abilities
    # she's captured from enemy pawns, each at that pawn's own floor/cost.
    if name == "Juice Box":
        if pos in gs.juice_box_used_this_turn:
            return
        captured_list = gs.juice_box_captured.get(gs.juice_box_key(pos), [])
        options = [n for n in captured_list
                   if PAWN_CHARACTERS.get(n) and PAWN_CHARACTERS[n].ability.trigger == AbilityTrigger.FLOOR_ROLL]
        if not options or random.random() > 0.5:
            return
        captured_name = random.choice(options)
        cchar = PAWN_CHARACTERS[captured_name]
        idx = dice.get_best_die_for_floor(cchar.ability.floor_number)
        if idx is None:
            return
        gs.try_juice_box_use_captured_ability(pos, cchar.ability.name, dice, idx,
                                              use_combined=cchar.ability.requires_combined)
        return

    char = PAWN_CHARACTERS.get(name)
    if char is None:
        return

    # Auto-trigger abilities don't need dice (Mordecai, Garret, Quasar, Orthrus)
    if char.ability.trigger != AbilityTrigger.FLOOR_ROLL:
        return

    # Random chance to attempt (don't always waste dice)
    if random.random() > 0.5:
        return

    idx = dice.get_best_die_for_floor(char.ability.floor_number)
    if idx is None:
        return

    if name == "Zev":
        gs.try_biggest_fan(pos, dice, idx)
    elif name == "The AI":
        gs.try_glitch(pos, dice, idx)
    elif name == "Prepotente":
        result = gs.try_special_boy(pos, dice, idx)
        if result:
            dest = random.choice(result)
            gs.board.set(pos[0], pos[1], None)
            gs.board.set(dest[0], dest[1], piece)
            piece.has_moved = True
    elif name == "Elle McGib":
        gs.try_frozen(pos, dice, idx)
    elif name == "Imani":
        gs.try_suppress(pos, dice, idx)
    elif name == "Slugalo":
        gs.try_one_of_us(pos, dice)
    elif name == "Louie":
        gs.try_air_strike(pos, dice, idx)
    elif name == "Sledge":
        gs.try_body_guard(pos, dice, idx)
    elif name == "Stripper Anaconda":
        gs.try_gun_show(pos, dice, idx)
    elif name == "Lucia Mar":
        gs.try_sic_em(pos, dice, idx)
    elif name == "Chris":
        direction = _pick_chris_direction(gs, pos)
        if direction:
            gs.try_lava_surge_chunk2(pos, dice, idx, direction=direction)
    elif name == "Florin":
        gs.try_suppressing_fire(pos, dice, idx)
    elif name == "Signet":
        gs.try_succubus(pos, dice, idx)
    elif name == "Miriam Dom":
        gs.try_blood_magic(pos, dice)
    elif name == "Raul the Crab":
        gs.try_group_climax(pos, dice)
    elif name == "Bad Llama":
        gs.try_lava_spit_chunk2(pos, dice, idx)


# ══════════════════════════════════════════════════════════════════
# Smart Positional AI
# ══════════════════════════════════════════════════════════════════

# Minimax search depth and wall-clock budget for smart_move(). If a search
# blows through the time limit (a busy midgame position with many legal
# moves per ply), smart_move falls back to the older priority-ladder logic
# for that turn rather than let the game hang.
MINIMAX_DEPTH = 3
MINIMAX_TIME_LIMIT_SECONDS = 5.0

CENTER_SQUARES = {
    (4, 4), (4, 5), (4, 6),
    (5, 4), (5, 5), (5, 6),
    (6, 4), (6, 5), (6, 6),
}


class _MinimaxTimeout(Exception):
    """Raised internally when a minimax search exceeds its time budget."""


def smart_move(game_state: GameState, legal_moves: List[Tuple]) -> Tuple:
    """Pick a move via minimax search (see _select_minimax_move), falling back
    to the older positional priority ladder if the search times out or finds
    nothing, then record its resulting board position in the AI's short-term
    history so future calls can deprioritize moves that would repeat it.
    """
    move = _select_minimax_move(game_state, legal_moves)
    if move is None:
        move = _select_smart_move(game_state, legal_moves)
    _record_ai_position(game_state, move)
    return move


def evaluate_board(board: Board, gs: GameState, color: Color) -> float:
    """Score `board` from `color`'s perspective -- higher is better for `color`.

    Combines material (own pieces minus enemy pieces, by PIECE_VALUES) with
    positional bonuses: check/checkmate status for both kings, mobility,
    center-square occupation, and pawn advancement.
    """
    opponent = color.opponent
    score = 0.0

    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            piece = board.get(r, c)
            if piece is None:
                continue

            sign = 1 if piece.color == color else -1
            score += sign * PIECE_VALUES.get(piece.piece_type, 1)

            if (r, c) in CENTER_SQUARES:
                score += sign * 0.2

            if piece.piece_type == PieceType.PAWN:
                if piece.color == Color.WHITE and r > 2:
                    score += sign * (r - 2) * 0.1
                elif piece.color == Color.BLACK and r < 9:
                    score += sign * (9 - r) * 0.1

    if is_in_check(board, color):
        score -= 50
    if is_checkmate(board, color):
        score -= 10000
    if is_in_check(board, opponent):
        score += 30
    if is_checkmate(board, opponent):
        score += 10000

    # Mobility uses pseudo-legal move counts (no per-move legality/check
    # simulation) -- evaluate_board runs at every minimax leaf, and the fully
    # legal count (all_legal_moves) is ~10x more expensive at this piece
    # density. Close enough as a mobility signal; see _quick_mobility.
    score += 0.1 * _quick_mobility(board, color)

    return score


def _quick_mobility(board: Board, color: Color) -> int:
    """Cheap mobility proxy: total pseudo-legal destination squares across
    all of `color`'s pieces, skipping the make_move/undo_move legality check
    that all_legal_moves does for every candidate move.
    """
    return sum(len(pseudo_legal_moves_for_piece(board, r, c))
               for r, c, _piece in board.all_pieces(color))


def _order_moves_for_search(board: Board, moves: List[Tuple], color: Color) -> List[Tuple]:
    """Sort moves to try captures (richest first) and center-square landings
    before quiet moves, without simulating anything -- this is what lets
    alpha-beta prune effectively instead of scanning near the full tree.
    """
    def key(move):
        (_fr, _fc), (tr, tc) = move
        target = board.get(tr, tc)
        capture_value = (PIECE_VALUES.get(target.piece_type, 1)
                         if target is not None and target.color != color else 0)
        center_bonus = 1 if (tr, tc) in CENTER_SQUARES else 0
        return (-capture_value, -center_bonus)

    return sorted(moves, key=key)


def minimax(board: Board, gs: GameState, depth: int, alpha: float, beta: float,
            maximizing_color: Color, root_color: Color, deadline: float) -> float:
    """Minimax search with alpha-beta pruning, evaluating leaves from
    `root_color`'s perspective. `deadline` is a time.monotonic() timestamp;
    exceeding it raises _MinimaxTimeout so the caller can abandon the search.
    """
    if time.monotonic() > deadline:
        raise _MinimaxTimeout()

    if (depth == 0
            or is_checkmate(board, maximizing_color)
            or is_stalemate(board, maximizing_color)):
        return evaluate_board(board, gs, root_color)

    legal_moves = all_legal_moves(board, maximizing_color)
    if not legal_moves:
        return evaluate_board(board, gs, root_color)
    legal_moves = _order_moves_for_search(board, legal_moves, maximizing_color)

    opponent_color = maximizing_color.opponent

    if maximizing_color == root_color:
        max_eval = -float('inf')
        for move in legal_moves:
            board_copy = copy.deepcopy(board)
            board_copy.make_move(*move)
            eval_score = minimax(board_copy, gs, depth - 1, alpha, beta,
                                 opponent_color, root_color, deadline)
            max_eval = max(max_eval, eval_score)
            alpha = max(alpha, eval_score)
            if beta <= alpha:
                break
        return max_eval
    else:
        min_eval = float('inf')
        for move in legal_moves:
            board_copy = copy.deepcopy(board)
            board_copy.make_move(*move)
            eval_score = minimax(board_copy, gs, depth - 1, alpha, beta,
                                 opponent_color, root_color, deadline)
            min_eval = min(min_eval, eval_score)
            beta = min(beta, eval_score)
            if beta <= alpha:
                break
        return min_eval


def _select_minimax_move(game_state: GameState, legal_moves: List[Tuple]) -> Optional[Tuple]:
    """Search `legal_moves` with minimax at MINIMAX_DEPTH and return the best
    one, skipping past a top pick that would repeat a recent position (same
    intent as the priority ladder's repetition avoidance). Returns None if
    there are no legal moves or the search times out, signaling smart_move
    to fall back to the priority ladder.
    """
    if not legal_moves:
        return None

    board = game_state.board
    color = game_state.current_player
    deadline = time.monotonic() + MINIMAX_TIME_LIMIT_SECONDS
    ordered_moves = _order_moves_for_search(board, legal_moves, color)

    scored_moves = []
    try:
        for move in ordered_moves:
            board_copy = copy.deepcopy(board)
            board_copy.make_move(*move)
            score = minimax(board_copy, game_state, MINIMAX_DEPTH - 1,
                            -float('inf'), float('inf'),
                            color.opponent, color, deadline)
            scored_moves.append((score, move))
    except _MinimaxTimeout:
        print("Warning: minimax search exceeded the 5s time limit; "
              "falling back to the priority-ladder AI for this turn.")
        return None

    scored_moves.sort(key=lambda sm: sm[0], reverse=True)

    for _score, move in scored_moves:
        if not _would_repeat_position(game_state, board, move):
            return move
    return scored_moves[0][1]


def _select_smart_move(game_state: GameState, legal_moves: List[Tuple]) -> Tuple:
    """Pick a move using positional priorities.

    Priority 1: Checkmate — always take it.
    Priority 2: A move that delivers check AND captures — best victim value.
    Priority 3: Capture a high-value piece (>= Samantha) — outranks a bare check.
    Priority 4: Deliver check — preferred over capturing a low-value piece (pawn,
                Mongo, Katia). Among checking moves, one that also grabs material wins.
    Priority 5: Any remaining capture — sorted by victim value descending.
    Priority 6: Avoid squares attacked by lower/equal-value enemies (disabled after turn 80).
    Priority 7: Advance toward opponent's side, deprioritizing moves that would
                repeat a position from the AI's last 6 recorded moves.

    After turn 80: aggression escalation — skip safety filter, take any capture.
    After turn 150: add randomness to break repetition loops.
    """
    board = game_state.board
    color = game_state.current_player
    opponent = color.opponent
    turn = game_state.turn_number
    desperate = turn >= 80
    very_desperate = turn >= 150

    # Value at/above which a capture is worth more than delivering check.
    # Below it (pawn, Mongo, Katia) a checking move is preferred instead --
    # this is what stops the AI endlessly recapturing a respawning pawn while
    # it already has the enemy Carl boxed in.
    CHECK_BEATS_CAPTURE_BELOW = PIECE_VALUES[PieceType.SAMANTHA]  # 5

    # Priority 1: Checkmate
    for move in legal_moves:
        if _is_checkmate_move(board, move, opponent):
            return move

    # Classify every move: capture value (0 if not a capture) + whether it checks.
    captures = []
    non_captures = []
    for move in legal_moves:
        (fr, fc), (tr, tc) = move
        target = board.get(tr, tc)
        if target is not None and target.color == opponent:
            captures.append((move, PIECE_VALUES.get(target.piece_type, 1)))
        else:
            non_captures.append(move)

    checking_moves = [m for m in legal_moves if _is_check_move(board, m, opponent)]
    checking_set = set(checking_moves)

    # Priority 2: a checking move that also captures — take the richest one.
    checking_captures = sorted(
        [(m, v) for (m, v) in captures if m in checking_set],
        key=lambda x: x[1], reverse=True,
    )
    if checking_captures:
        return checking_captures[0][0]

    # Priority 3: a high-value capture outranks a bare (non-capturing) check.
    high_value_captures = sorted(
        [(m, v) for (m, v) in captures if v >= CHECK_BEATS_CAPTURE_BELOW],
        key=lambda x: x[1], reverse=True,
    )
    if high_value_captures:
        return high_value_captures[0][0]

    # Priority 4: deliver check — preferred over capturing a low-value piece.
    # Prefer a checking move that also picks up material along the way.
    if checking_moves:
        def _cap_value(m):
            (_, _), (tr, tc) = m
            t = board.get(tr, tc)
            return PIECE_VALUES.get(t.piece_type, 1) if (t is not None and t.color == opponent) else 0
        checking_moves.sort(key=_cap_value, reverse=True)
        return checking_moves[0]

    # Priority 5: remaining captures (all low-value now) — richest first.
    if captures:
        captures.sort(key=lambda x: x[1], reverse=True)
        return captures[0][0]

    # Very desperate: add randomness to break loops
    if very_desperate and random.random() < 0.3:
        return random.choice(legal_moves)

    # Priority 3: Filter out moves into danger (skip when desperate)
    if not desperate:
        safe_moves = []
        for move in non_captures:
            (fr, fc), (tr, tc) = move
            mover = board.get(fr, fc)
            if mover is None:
                safe_moves.append(move)
                continue
            mover_value = PIECE_VALUES.get(mover.piece_type, 1)
            if _is_square_safe(board, tr, tc, mover_value, opponent):
                safe_moves.append(move)
        candidate_moves = safe_moves if safe_moves else non_captures if non_captures else legal_moves
    else:
        candidate_moves = non_captures if non_captures else legal_moves

    # Repetition avoidance: a move landing on a board position already seen in
    # the AI's last AI_POSITION_HISTORY_LEN recorded positions is deprioritized
    # -- pushed to the bottom of candidate_moves, never dropped outright, so the
    # AI still has a legal move if every option happens to repeat. This is what
    # stops it getting trapped shuffling a piece between the same few squares
    # (see AI_POSITION_HISTORY_LEN / _record_ai_position).
    repeated = {move: _would_repeat_position(game_state, board, move) for move in candidate_moves}

    # Priority 7: Advance toward opponent's side
    # White prefers higher rows, black prefers lower rows. Repetition status is
    # the primary sort key (non-repeating first) with advancement as the
    # tiebreaker, so both preferences apply together rather than one undoing
    # the other.
    def _sort_key(m):
        row = m[1][0]
        return (repeated[m], -row if color == Color.WHITE else row)

    candidate_moves.sort(key=_sort_key)

    # Pick from the top tier (same repetition status + same row as the best
    # candidate), adding slight randomness among equally-good options.
    if len(candidate_moves) > 3:
        best_key = _sort_key(candidate_moves[0])
        top_tier = [m for m in candidate_moves if _sort_key(m) == best_key]
        return random.choice(top_tier)
    return candidate_moves[0]


def _is_checkmate_move(board: Board, move: Tuple, opponent: Color) -> bool:
    """Test if a move results in checkmate for the opponent."""
    (fr, fc), (tr, tc) = move
    piece = board.get(fr, fc)
    if piece is None:
        return False

    old_ep = board.en_passant_target
    old_moved = piece.has_moved
    target = board.get(tr, tc)
    is_ep = (piece.is_pawn and (tr, tc) == board.en_passant_target and target is None)
    promotion_rank = BOARD_SIZE - 1 if piece.color == Color.WHITE else 0
    is_promo = piece.is_pawn and tr == promotion_rank

    captured = board.make_move((fr, fc), (tr, tc))
    result = is_checkmate(board, opponent)
    board.undo_move((fr, fc), (tr, tc), captured, is_ep, old_ep,
                    old_moved, is_promo, piece if is_promo else None)
    return result


def _is_check_move(board: Board, move: Tuple, opponent: Color) -> bool:
    """Test if a move leaves the opponent's Carl in check (but not mate)."""
    (fr, fc), (tr, tc) = move
    piece = board.get(fr, fc)
    if piece is None:
        return False
    # A missing king makes is_in_check() report True for every move -- guard so
    # a kingless boss-co-op opponent doesn't make the AI think it checks always.
    if board.find_king(opponent) is None:
        return False

    old_ep = board.en_passant_target
    old_moved = piece.has_moved
    target = board.get(tr, tc)
    is_ep = (piece.is_pawn and (tr, tc) == board.en_passant_target and target is None)
    promotion_rank = BOARD_SIZE - 1 if piece.color == Color.WHITE else 0
    is_promo = piece.is_pawn and tr == promotion_rank

    captured = board.make_move((fr, fc), (tr, tc))
    result = is_in_check(board, opponent)
    board.undo_move((fr, fc), (tr, tc), captured, is_ep, old_ep,
                    old_moved, is_promo, piece if is_promo else None)
    return result


# ── Repetition avoidance (Bug 2) ────────────────────────────────────

def _board_position_signature(board: Board) -> tuple:
    """A hashable snapshot of every occupied square (position, piece type,
    color, pawn name) -- two calls return equal tuples iff the board is in
    the same position.
    """
    entries = []
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            p = board.get(r, c)
            if p is not None:
                entries.append((r, c, p.piece_type, p.color, p.pawn_name))
    return tuple(entries)


def _resulting_position_signature(board: Board, move: Tuple) -> tuple:
    """The board signature `move` would produce, computed without permanently
    mutating the board (make_move + undo_move, same as _is_check_move above).
    """
    (fr, fc), (tr, tc) = move
    piece = board.get(fr, fc)
    if piece is None:
        return _board_position_signature(board)

    old_ep = board.en_passant_target
    old_moved = piece.has_moved
    target = board.get(tr, tc)
    is_ep = (piece.is_pawn and (tr, tc) == board.en_passant_target and target is None)
    promotion_rank = BOARD_SIZE - 1 if piece.color == Color.WHITE else 0
    is_promo = piece.is_pawn and tr == promotion_rank

    captured = board.make_move((fr, fc), (tr, tc))
    sig = _board_position_signature(board)
    board.undo_move((fr, fc), (tr, tc), captured, is_ep, old_ep,
                    old_moved, is_promo, piece if is_promo else None)
    return sig


def _would_repeat_position(game_state: GameState, board: Board, move: Tuple) -> bool:
    """True if `move` would land on a position already in the AI's recent-
    position history (see _record_ai_position). No history yet -- e.g. the
    AI's first move of the game -- means nothing can repeat.
    """
    history = getattr(game_state, "_ai_position_history", None)
    if not history:
        return False
    return _resulting_position_signature(board, move) in history


def _record_ai_position(game_state: GameState, move: Optional[Tuple]) -> None:
    """Append the position after the AI's just-chosen move to its short-term
    history, capped at AI_POSITION_HISTORY_LEN entries (oldest drops off).
    Lazily attached to the GameState instance itself (rather than a module-
    level cache) so it stays scoped to this one game and needs no change to
    GameState's own definition.
    """
    if move is None:
        return
    history = getattr(game_state, "_ai_position_history", None)
    if history is None:
        history = deque(maxlen=AI_POSITION_HISTORY_LEN)
        game_state._ai_position_history = history
    history.append(_resulting_position_signature(game_state.board, move))


def _is_square_safe(board: Board, row: int, col: int,
                    mover_value: int, opponent: Color) -> bool:
    """Check if a square is safe — not attacked by enemy of lower/equal value."""
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            p = board.get(r, c)
            if p is None or p.color != opponent:
                continue
            attacker_value = PIECE_VALUES.get(p.piece_type, 1)
            if attacker_value > mover_value:
                continue  # Only worried about lower/equal value attackers
            # Check if this attacker can reach (row, col)
            if p.is_pawn:
                direction = p.color.direction
                if r + direction == row and abs(c - col) == 1:
                    return False
            else:
                from .movement import pseudo_legal_moves_for_piece
                if (row, col) in pseudo_legal_moves_for_piece(board, r, c):
                    return False
    return True


def smart_abilities(game_state: GameState, dice: DungeonDice, color: Color):
    """Spend dice on abilities intelligently based on board state.

    Priority: offensive abilities when enemies in range > defensive/utility > skip.
    """
    if dice.remaining_count == 0:
        return

    board = game_state.board
    opponent = color.opponent
    pieces = board.all_pieces(color)

    # Categorize abilities into offensive and defensive attempts
    offensive_attempts = []
    defensive_attempts = []

    for row, col, piece in pieces:
        if game_state.is_piece_suppressed(row, col):
            continue

        # Global Game Settings toggles apply to the AI too.
        if piece.is_pawn and not getattr(game_state, "pawns_enabled", True):
            continue
        if not piece.is_pawn and not getattr(game_state, "major_abilities_enabled", True):
            continue

        if piece.piece_type == PieceType.MONGO:
            # Rampage: offensive, only when there's something nearby worth
            # rampaging through, and the once-per-game charge is unspent.
            if (_has_enemy_in_range(board, row, col, 2, opponent)
                    and not game_state.rampaging_charge_used.get((piece.color, id(piece)), False)):
                offensive_attempts.append(("rampage", (row, col), piece, 8))
            # Pet Carrier: retreat Mongo to safety when threatened, or release
            # him once he's already stored — never a routine pick otherwise.
            key = (piece.color, id(piece))
            if game_state.mongo_stored.get(key, False):
                defensive_attempts.append(("pet_carrier", (row, col), piece, 4))
            elif _has_enemy_in_range(board, row, col, 1, opponent):
                defensive_attempts.append(("pet_carrier", (row, col), piece, 4))

        elif piece.piece_type == PieceType.KATIA:
            # She Tank: disrupt a nearby enemy while uses remain.
            if (_has_enemy_in_range(board, row, col, 3, opponent)
                    and game_state.she_tank_uses.get(piece.color, 2) > 0):
                offensive_attempts.append(("she_tank", (row, col), piece, 6))
            # Blitzed has no real precondition -- keep it as filler, not a
            # default pick (see MAJOR_PRIORITY_BONUS below).
            defensive_attempts.append(("blitzed", (row, col), piece, 5))

        elif piece.piece_type == PieceType.SAMANTHA:
            # Slut Shame: offensive, once per game, when a pawn is in reach.
            if (_has_enemy_in_range(board, row, col, 3, opponent)
                    and not game_state.slut_shame_used.get((piece.color, id(piece)), False)):
                offensive_attempts.append(("slut_shame", (row, col), piece, 8))
            # Miss Me? rerolls this turn's whole dice pool -- costs floor 5,
            # so it's only worth it (and only actually affordable) when one
            # die is good enough to pay for it (>= 5) but the roll as a whole
            # is uneven (the other die is weak), i.e. spending the good die
            # to reroll everything in hopes of two usable dice. This replaces
            # the old "The Mouth" filler pick with the ability actually shown
            # to players, and keeps it a last resort rather than a default.
            available = sorted(dice.dice[i] for i in range(len(dice.dice)) if not dice.used[i])
            if len(available) >= 2 and available[-1] >= 5 and available[0] <= 3:
                defensive_attempts.append(("miss_me", (row, col), piece, 5))

        elif piece.piece_type == PieceType.DONUT:
            # Cockroach: resurrect when there's a captured piece to bring back.
            if not game_state.resurrection_used[color] and board.captured[color]:
                defensive_attempts.append(("cockroach", (row, col), piece, 7))
            # Puddle Jump: offensive reposition/strike when enemies are in reach.
            if _has_enemy_in_range(board, row, col, 3, opponent):
                offensive_attempts.append(("puddle_jump", (row, col), piece, 5))

        elif piece.piece_type == PieceType.CARL:
            # Plot Armor is an emergency escape -- only worth considering when
            # Carl is actually in check, never a routine pick.
            if not game_state.plot_armor_used.get(color, False) and is_in_check(board, color):
                defensive_attempts.append(("plot_armor", (row, col), piece, 8))
            # Leader eats every remaining die this turn to reposition a
            # back-line major -- keep it available but heavily deprioritized
            # (see MAJOR_PRIORITY_BONUS) so it's not spent casually.
            if game_state.leader_uses.get(color, 2) > 0:
                defensive_attempts.append(("leader", (row, col), piece, 0))

        elif piece.is_pawn and piece.pawn_name:
            _categorize_pawn_ability(game_state, board, row, col, piece,
                                     opponent, offensive_attempts, defensive_attempts)

    # Sort by strategic priority descending, not raw floor cost. Floor cost
    # alone let a cheap, always-affordable, no-precondition ability (the old
    # "The Mouth") dominate over rarer, more valuable, harder-to-afford
    # abilities (Plot Armor, She Tank, Rampage, Puddle Jump, Leader, Blitzed,
    # Miss Me?, ...) that were never even being considered. MAJOR_PRIORITY_BONUS
    # adds a strategic weight on top of floor for majors only (pawns are
    # unaffected -- the bonus defaults to 0) so genuinely conditioned abilities
    # (only offered when there's a real reason to use them) rank above generic
    # filler abilities with no precondition, which become last resorts.
    def _priority_key(entry):
        name, _pos, _piece, floor = entry
        return floor + MAJOR_PRIORITY_BONUS.get(name, 0)

    offensive_attempts.sort(key=_priority_key, reverse=True)
    defensive_attempts.sort(key=_priority_key, reverse=True)

    # Spend dice: offensive first, then defensive; reserve 1 die for movement
    for ability_name, pos, piece, floor in offensive_attempts:
        if dice.remaining_count <= 1:
            break  # Reserve last die for movement
        idx = dice.get_best_die_for_floor(floor)
        if idx is None:
            continue  # Skip this ability, try others with lower floors
        _execute_smart_ability(game_state, dice, ability_name, pos, piece, idx, color)

    for ability_name, pos, piece, floor in defensive_attempts:
        if dice.remaining_count <= 1:
            break  # Reserve last die for movement
        idx = dice.get_best_die_for_floor(floor)
        if idx is None:
            continue  # Skip this ability, try others with lower floors
        _execute_smart_ability(game_state, dice, ability_name, pos, piece, idx, color)


def _has_enemy_in_range(board: Board, row: int, col: int,
                        distance: int, opponent: Color) -> bool:
    """Check if any enemy piece is within Manhattan distance."""
    for dr in range(-distance, distance + 1):
        for dc in range(-distance, distance + 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = row + dr, col + dc
            if board.in_bounds(nr, nc):
                p = board.get(nr, nc)
                if p and p.color == opponent:
                    return True
    return False


def _categorize_pawn_ability(gs, board, row, col, piece, opponent,
                              offensive, defensive):
    """Sort pawn abilities into offensive/defensive buckets."""
    name = piece.pawn_name

    # Juice Box has no ability of her own -- offer each captured ability at
    # that pawn's own floor/cost, same as a human would see in her sidebar list.
    if name == "Juice Box":
        if (row, col) in gs.juice_box_used_this_turn:
            return
        for captured_name in gs.juice_box_captured.get(gs.juice_box_key((row, col)), []):
            cchar = PAWN_CHARACTERS.get(captured_name)
            if cchar and cchar.ability.trigger == AbilityTrigger.FLOOR_ROLL:
                offensive.append((f"juice_box:{cchar.ability.name}", (row, col), piece,
                                  cchar.ability.floor_number))
        return

    char = PAWN_CHARACTERS.get(name)
    if char is None or char.ability.trigger != AbilityTrigger.FLOOR_ROLL:
        return

    floor = char.ability.floor_number

    if name == "Imani":
        if _has_enemy_in_range(board, row, col, 1, opponent):
            offensive.append(("imani", (row, col), piece, floor))
    elif name == "Elle McGib":
        if _has_enemy_in_range(board, row, col, 5, opponent):
            offensive.append(("elle_mcgib", (row, col), piece, floor))
    elif name == "Slugalo":
        if _has_enemy_in_range(board, row, col, 2, opponent):
            offensive.append(("slugalo", (row, col), piece, floor))
    elif name == "Stripper Anaconda":
        if _has_enemy_in_range(board, row, col, 1, opponent):
            offensive.append(("gun_show", (row, col), piece, floor))
    elif name == "Louie":
        if _has_enemy_in_range(board, row, col, 3, opponent):
            offensive.append(("louie", (row, col), piece, floor))
    elif name == "Prepotente":
        # Titan stride is useful for advancement
        direction = piece.color.direction
        r2 = row + 2 * direction
        if board.in_bounds(r2, col) and board.get(r2, col) is None:
            r1 = row + direction
            if board.get(r1, col) is None:
                defensive.append(("prepotente", (row, col), piece, floor))
    elif name == "Zev":
        # Pack Rally useful if adjacent friendly pawns exist
        has_adj_pawn = False
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = row + dr, col + dc
                if board.in_bounds(nr, nc):
                    adj = board.get(nr, nc)
                    if adj and adj.is_pawn and adj.color == piece.color:
                        has_adj_pawn = True
        if has_adj_pawn:
            defensive.append(("zev", (row, col), piece, floor))
    elif name == "Sledge":
        # Iron Wall if enemy nearby and in danger
        if _has_enemy_in_range(board, row, col, 2, opponent):
            defensive.append(("sledge", (row, col), piece, floor))
    elif name == "The AI":
        # Glitch: only try if there's a good reason
        if _has_enemy_in_range(board, row, col, 2, opponent):
            offensive.append(("the_ai", (row, col), piece, 4))  # Approximate floor
    elif name == "Lucia Mar":
        # Sic Em can target any enemy piece anywhere on the board
        if any(True for _ in board.all_pieces(opponent)):
            offensive.append(("lucia_mar", (row, col), piece, floor))
    elif name == "Chris":
        # Lava Surge is blocked entirely while an enemy is adjacent, and
        # needs at least one direction whose 3 squares are fully empty
        if not gs.chris_lava_surge_adjacent_enemy((row, col)) and _pick_chris_direction(gs, (row, col)):
            offensive.append(("chris", (row, col), piece, floor))
    elif name == "Florin":
        if _has_enemy_in_range(board, row, col, 3, opponent):
            offensive.append(("florin", (row, col), piece, floor))
    elif name == "Signet":
        # Enthrall: only useful if adjacent enemy major piece
        has_adj_major = False
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = row + dr, col + dc
                if board.in_bounds(nr, nc):
                    t = board.get(nr, nc)
                    if t and t.color == opponent and not t.is_pawn:
                        has_adj_major = True
        if has_adj_major:
            offensive.append(("signet", (row, col), piece, floor))
    elif name == "Miriam Dom":
        # Blood Magic: need adjacent friendly pawn AND captured friendly pawn
        has_adj_pawn = False
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = row + dr, col + dc
                if board.in_bounds(nr, nc):
                    t = board.get(nr, nc)
                    if t and t.is_pawn and t.color == piece.color and t.pawn_name != "Miriam Dom":
                        has_adj_pawn = True
        captured_pawns = [p for p in board.captured[piece.color] if p.is_pawn]
        if has_adj_pawn and captured_pawns:
            defensive.append(("miriam_dom", (row, col), piece, floor))
    elif name == "Raul the Crab":
        # Meditative Strike: always useful if Raul didn't move
        if (row, col) not in gs.raul_moved_this_turn:
            defensive.append(("raul", (row, col), piece, floor))
    elif name == "Bad Llama":
        if _has_enemy_in_range(board, row, col, 2, opponent):
            offensive.append(("bad_llama", (row, col), piece, floor))


def _execute_smart_ability(gs, dice, ability_name, pos, piece, die_idx, color):
    """Execute a specific ability attempt."""
    if ability_name == "rampage":
        result = gs.try_rampage(pos, dice)
        if result:
            dest = random.choice(result)
            gs.board.set(pos[0], pos[1], None)
            gs.board.set(dest[0], dest[1], piece)
    elif ability_name == "pet_carrier":
        gs.try_pet_carrier(pos, dice, die_idx)
    elif ability_name == "she_tank":
        r, c = pos
        opponent = color.opponent
        enemies = [(er, ec) for er, ec, ep in gs.board.all_pieces(opponent)]
        if enemies:
            target_pos = random.choice(enemies)
            gs.try_she_tank(pos, dice, target_pos, is_reaction=False)
    elif ability_name == "blitzed":
        gs.try_blitzed(pos, dice, die_idx)
    elif ability_name == "slut_shame":
        gs.try_slut_shame(pos, dice)
    elif ability_name == "miss_me":
        gs.try_miss_me(pos, dice, die_idx, is_reaction=False)
    elif ability_name == "cockroach":
        gs.try_cockroach(pos, dice)
    elif ability_name == "puddle_jump":
        result = gs.try_puddle_jump(pos, dice, die_idx)
        if result:
            dest = random.choice(result)
            gs.board.set(pos[0], pos[1], None)
            gs.board.set(dest[0], dest[1], piece)
    elif ability_name == "plot_armor":
        result = gs.try_plot_armor(pos, dice)
        if result:
            dest = random.choice(result)
            captured = gs.board.make_move(pos, dest)
            if captured:
                gs.process_post_capture(captured, dest, piece, pos)
    elif ability_name == "leader":
        total = gs.try_leader(pos, dice, color.value)
        if total:
            eligible = gs.leader_eligible_pieces(color)
            random.shuffle(eligible)
            for epos in eligible:
                destinations = gs.leader_pull_destinations(epos, pos, total)
                if destinations:
                    dest = random.choice(destinations)
                    pulled = gs.board.get(*epos)
                    gs.board.set(epos[0], epos[1], None)
                    gs.board.set(dest[0], dest[1], pulled)
                    break
    elif ability_name == "imani":
        gs.try_suppress(pos, dice, die_idx)
    elif ability_name == "elle_mcgib":
        gs.try_frozen(pos, dice, die_idx)
    elif ability_name == "slugalo":
        gs.try_one_of_us(pos, dice)
    elif ability_name == "gun_show":
        gs.try_gun_show(pos, dice, die_idx)
    elif ability_name == "louie":
        gs.try_air_strike(pos, dice, die_idx)
    elif ability_name == "prepotente":
        result = gs.try_special_boy(pos, dice, die_idx)
        if result:
            dest = random.choice(result)
            gs.board.set(pos[0], pos[1], None)
            gs.board.set(dest[0], dest[1], piece)
            piece.has_moved = True
    elif ability_name == "zev":
        gs.try_biggest_fan(pos, dice, die_idx)
    elif ability_name == "sledge":
        gs.try_body_guard(pos, dice, die_idx)
    elif ability_name == "the_ai":
        gs.try_glitch(pos, dice, die_idx)
    elif ability_name == "lucia_mar":
        gs.try_sic_em(pos, dice, die_idx)
    elif ability_name == "chris":
        direction = _pick_chris_direction(gs, pos)
        if direction:
            gs.try_lava_surge_chunk2(pos, dice, die_idx, direction=direction)
    elif ability_name.startswith("juice_box:"):
        captured_ability_name = ability_name.split(":", 1)[1]
        cchar = gs.find_captured_ability(pos, captured_ability_name)
        use_combined = bool(cchar and cchar.ability.requires_combined)
        gs.try_juice_box_use_captured_ability(pos, captured_ability_name, dice, die_idx,
                                              use_combined=use_combined)
    elif ability_name == "florin":
        gs.try_suppressing_fire(pos, dice, die_idx)
    elif ability_name == "signet":
        gs.try_succubus(pos, dice, die_idx)
    elif ability_name == "miriam_dom":
        gs.try_blood_magic(pos, dice)
    elif ability_name == "raul":
        gs.try_group_climax(pos, dice)
    elif ability_name == "bad_llama":
        gs.try_lava_spit_chunk2(pos, dice, die_idx)
