"""AI players for DCC Chess simulation.

Provides two AI implementations:
- Random AI: picks random legal moves and randomly attempts abilities.
- Smart AI: uses positional evaluation (checkmate > capture > avoid > advance)
  and context-aware ability spending.
"""

import random
from typing import List, Tuple, Optional, Dict

from .pieces import Piece, PieceType, Color
from .board import Board, BOARD_SIZE, PAWN_ROSTER
from .dice import DungeonDice
from .abilities import GameState
from .pawns import PAWN_CHARACTERS, AbilityTrigger
from .movement import is_checkmate, is_in_check, is_square_attacked


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


def random_draft(count: int = 8) -> List[str]:
    """Draft unique pawns from the roster of 21. Default 8 per player."""
    return random.sample(PAWN_ROSTER, count)


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

def smart_move(game_state: GameState, legal_moves: List[Tuple]) -> Tuple:
    """Pick a move using positional priorities.

    Priority 1: Checkmate — always take it.
    Priority 2: Capture highest-value enemy piece.
    Priority 3: Avoid squares attacked by lower/equal-value enemies (disabled after turn 80).
    Priority 4: Advance toward opponent's side.

    After turn 80: aggression escalation — skip safety filter, take any capture.
    After turn 150: add randomness to break repetition loops.
    """
    board = game_state.board
    color = game_state.current_player
    opponent = color.opponent
    turn = game_state.turn_number
    desperate = turn >= 80
    very_desperate = turn >= 150

    # Priority 1: Checkmate
    for move in legal_moves:
        if _is_checkmate_move(board, move, opponent):
            return move

    # Priority 2: Captures — sorted by victim value descending
    captures = []
    non_captures = []
    for move in legal_moves:
        (fr, fc), (tr, tc) = move
        target = board.get(tr, tc)
        if target is not None and target.color == opponent:
            captures.append((move, PIECE_VALUES.get(target.piece_type, 1)))
        else:
            non_captures.append(move)

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

    # Priority 4: Advance toward opponent's side
    # White prefers higher rows, black prefers lower rows
    if color == Color.WHITE:
        candidate_moves.sort(key=lambda m: m[1][0], reverse=True)
    else:
        candidate_moves.sort(key=lambda m: m[1][0])

    # Pick from the top advancing moves (add slight randomness among top tier)
    if len(candidate_moves) > 3:
        best_row = candidate_moves[0][1][0]
        top_tier = [m for m in candidate_moves if m[1][0] == best_row]
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

        if piece.piece_type == PieceType.MONGO:
            # Mongo Smash: offensive if enemy in range
            if _has_enemy_in_range(board, row, col, 2, opponent):
                offensive_attempts.append(("mongo_smash", (row, col), piece, 3))
            if not game_state.rampaging_charge_used.get((piece.color, id(piece)), False):
                if _has_enemy_in_range(board, row, col, 1, opponent):
                    offensive_attempts.append(("rampaging_charge", (row, col), piece, 4))

        elif piece.piece_type == PieceType.KATIA:
            if game_state.katia_last_threats.get((row, col)):
                defensive_attempts.append(("combat_roll", (row, col), piece, 3))

        elif piece.piece_type == PieceType.SAMANTHA:
            if not game_state.mouth_used_this_turn:
                # The Mouth is always useful — improves dice
                defensive_attempts.append(("the_mouth", (row, col), piece, 3))

        elif piece.piece_type == PieceType.DONUT:
            if not game_state.resurrection_used[color] and board.captured[color]:
                defensive_attempts.append(("resurrect", (row, col), piece, 6))
            if _has_enemy_in_range(board, row, col, 2, opponent):
                offensive_attempts.append(("diva", (row, col), piece, 4))

        elif piece.piece_type == PieceType.CARL:
            # Bulldozer is useful when near enemies
            if _has_enemy_in_range(board, row, col, 2, opponent):
                offensive_attempts.append(("bulldozer", (row, col), piece, 4))

        elif piece.is_pawn and piece.pawn_name:
            _categorize_pawn_ability(game_state, board, row, col, piece,
                                     opponent, offensive_attempts, defensive_attempts)

    # Sort by floor descending (high-value abilities get best dice first)
    offensive_attempts.sort(key=lambda x: x[3], reverse=True)
    defensive_attempts.sort(key=lambda x: x[3], reverse=True)

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
    if ability_name == "mongo_smash":
        gs.try_mongo_smash(pos, dice, die_idx)
    elif ability_name == "rampaging_charge":
        gs.try_rampaging_charge(pos, dice, die_idx)
    elif ability_name == "combat_roll":
        retreats = gs.try_combat_roll(pos, dice, die_idx)
        if retreats:
            dest = random.choice(retreats)
            gs.board.set(pos[0], pos[1], None)
            gs.board.set(dest[0], dest[1], piece)
    elif ability_name == "the_mouth":
        gs.try_the_mouth(pos, dice, die_idx)
    elif ability_name == "resurrect":
        gs.try_resurrection(pos, dice, die_idx, color)
    elif ability_name == "diva":
        r, c = pos
        opponent = color.opponent
        # Target a square with an enemy nearby
        adj = [(r + dr, c + dc) for dr in [-1, 0, 1] for dc in [-1, 0, 1]
               if (dr != 0 or dc != 0) and gs.board.in_bounds(r + dr, c + dc)]
        enemy_adj = [sq for sq in adj if gs.board.get(*sq) and gs.board.get(*sq).color == opponent]
        target = random.choice(enemy_adj) if enemy_adj else (random.choice(adj) if adj else None)
        if target:
            gs.try_divas_entrance(pos, dice, die_idx, target)
    elif ability_name == "bulldozer":
        gs.try_bulldozer(pos, dice, die_idx)
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
