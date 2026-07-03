"""Chunk 2 ability implementations for DCC Chess.

This file contains all the new ability implementations for major pieces and pawns.
These will be integrated into the main abilities.py file.
"""

import random
from typing import List, Tuple, Optional, Dict, Set

from .pieces import Piece, PieceType, Color
from .board import Board, BOARD_SIZE
from .dice import DungeonDice


# ── PRIORITY GROUP 1: Simple Status Effects ──────────────────────

def try_sic_em(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
               die_index: int) -> bool:
    """Lucia Mar's Sic Em (Floor 3): Restrain 1 enemy piece within 2 squares."""
    piece = self.board.get(*pawn_pos)
    if piece is None or not piece.is_pawn or piece.pawn_name != "Lucia Mar":
        return False
    if self.is_piece_suppressed(*pawn_pos):
        return False

    success = dice.spend_die(die_index, 3)
    self.log_event("ability_roll", piece="Lucia Mar", ability="Sic Em",
                   die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
    if not success:
        return False

    r, c = pawn_pos
    # Find enemy pieces within 2 squares
    targets = []
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if self.board.in_bounds(nr, nc):
                target = self.board.get(nr, nc)
                if target and target.color != piece.color:
                    targets.append((nr, nc))

    if not targets:
        return False

    # Pick random target and restrain it
    target_pos = random.choice(targets)
    self.restrained_pending.add(target_pos)
    self.log_event("sic_em", target_pos=target_pos, detail="Restrained for next turn")
    return True


def try_frozen(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
               die_index: int) -> bool:
    """Elle McGib's Frozen (Floor 5): Freeze enemy piece within 5 squares."""
    piece = self.board.get(*pawn_pos)
    if piece is None or not piece.is_pawn or piece.pawn_name != "Elle McGib":
        return False
    if self.is_piece_suppressed(*pawn_pos):
        return False

    success = dice.spend_die(die_index, 5)
    self.log_event("ability_roll", piece="Elle McGib", ability="Frozen",
                   die_value=dice.dice[die_index], floor=5, result="success" if success else "fail")
    if not success:
        return False

    r, c = pawn_pos
    # Find enemy pieces within 5 squares
    targets = []
    for dr in range(-5, 6):
        for dc in range(-5, 6):
            if dr == 0 and dc == 0:
                continue
            if abs(dr) > 5 or abs(dc) > 5:
                continue
            nr, nc = r + dr, c + dc
            if self.board.in_bounds(nr, nc):
                target = self.board.get(nr, nc)
                if target and target.color != piece.color:
                    targets.append((nr, nc))

    if not targets:
        return False

    # Pick random target and freeze it
    target_pos = random.choice(targets)
    self.frozen_pending.add(target_pos)
    self.log_event("frozen", target_pos=target_pos, detail="Frozen for next turn")
    return True


def try_suppress(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                 die_index: int) -> bool:
    """Imani's Suppress (Floor 4): Enemy piece within 2 squares loses abilities."""
    piece = self.board.get(*pawn_pos)
    if piece is None or not piece.is_pawn or piece.pawn_name != "Imani":
        return False
    if self.is_piece_suppressed(*pawn_pos):
        return False

    success = dice.spend_die(die_index, 4)
    self.log_event("ability_roll", piece="Imani", ability="Suppress",
                   die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
    if not success:
        return False

    r, c = pawn_pos
    # Find enemy pieces within 2 squares
    targets = []
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if self.board.in_bounds(nr, nc):
                target = self.board.get(nr, nc)
                if target and target.color != piece.color:
                    targets.append((nr, nc))

    if not targets:
        return False

    # Pick random target and suppress it
    target_pos = random.choice(targets)
    self.suppressed_pending.add(target_pos)
    self.log_event("suppress", target_pos=target_pos, detail="Suppressed for next turn")
    return True


def try_body_guard(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                   die_index: int) -> bool:
    """Sledge's Body Guard (Floor 3): Become immovable and invulnerable for 2 turns."""
    piece = self.board.get(*pawn_pos)
    if piece is None or not piece.is_pawn or piece.pawn_name != "Sledge":
        return False
    if self.is_piece_suppressed(*pawn_pos):
        return False

    success = dice.spend_die(die_index, 3)
    self.log_event("ability_roll", piece="Sledge", ability="Body Guard",
                   die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
    if not success:
        return False

    # Make Sledge immovable and invulnerable for 2 turns
    self.iron_wall_pieces[pawn_pos] = 2
    self.log_event("body_guard", pos=pawn_pos, detail="Immovable and invulnerable for 2 turns")
    return True


# ── PRIORITY GROUP 2: Movement Modifiers ──────────────────────────

def try_biggest_fan(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                    die_index: int) -> bool:
    """Zev's Biggest Fan (Floor 3): All friendly pieces get +1 to dice next turn."""
    piece = self.board.get(*pawn_pos)
    if piece is None or not piece.is_pawn or piece.pawn_name != "Zev":
        return False
    if self.is_piece_suppressed(*pawn_pos):
        return False

    success = dice.spend_die(die_index, 3)
    self.log_event("ability_roll", piece="Zev", ability="Biggest Fan",
                   die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
    if not success:
        return False

    # Set buff to activate next turn
    self.zev_buff_active[piece.color] = True
    self.log_event("biggest_fan", detail="All friendly pieces get +1 to dice next turn")
    return True


def try_special_boy(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                    die_index: int) -> Optional[List[Tuple[int, int]]]:
    """Prepotente's Special Boy (Floor 4): Move 2 squares forward."""
    piece = self.board.get(*pawn_pos)
    if piece is None or not piece.is_pawn or piece.pawn_name != "Prepotente":
        return None
    if self.is_piece_suppressed(*pawn_pos):
        return None

    success = dice.spend_die(die_index, 4)
    self.log_event("ability_roll", piece="Prepotente", ability="Special Boy",
                   die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
    if not success:
        return None

    r, c = pawn_pos
    forward = piece.color.direction
    moves = []
    
    # Check if Carl is in check
    carl_pos = self.board.find_king(piece.color)
    carl_in_check = False
    if carl_pos:
        from .movement import is_in_check
        carl_in_check = is_in_check(self.board, piece.color)
    
    if carl_in_check:
        # Can move 2 squares in any direction
        for dr in [-2, -1, 0, 1, 2]:
            for dc in [-2, -1, 0, 1, 2]:
                if dr == 0 and dc == 0:
                    continue
                if abs(dr) > 2 or abs(dc) > 2:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc) and not self.is_square_blocked(nr, nc):
                    target = self.board.get(nr, nc)
                    if target is None or target.color != piece.color:
                        moves.append((nr, nc))
    else:
        # Move 2 squares forward
        nr = r + (2 * forward)
        if self.board.in_bounds(nr, c) and not self.is_square_blocked(nr, c):
            target = self.board.get(nr, c)
            if target is None or target.color != piece.color:
                moves.append((nr, c))
        # Can also capture diagonally 2 forward
        for dc in [-2, -1, 1, 2]:
            nc = c + dc
            nr = r + (2 * forward)
            if self.board.in_bounds(nr, nc) and not self.is_square_blocked(nr, nc):
                target = self.board.get(nr, nc)
                if target and target.color != piece.color:
                    moves.append((nr, nc))
    
    return moves if moves else None


def try_suppressing_fire(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                         die_index: int) -> bool:
    """Florin's Suppressing Fire (Floor 4): Push enemy piece 2 squares away."""
    piece = self.board.get(*pawn_pos)
    if piece is None or not piece.is_pawn or piece.pawn_name != "Florin":
        return False
    if self.is_piece_suppressed(*pawn_pos):
        return False

    success = dice.spend_die(die_index, 4)
    self.log_event("ability_roll", piece="Florin", ability="Suppressing Fire",
                   die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
    if not success:
        return False

    r, c = pawn_pos
    # Find enemy pieces
    targets = []
    for dr in range(-5, 6):
        for dc in range(-5, 6):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if self.board.in_bounds(nr, nc):
                target = self.board.get(nr, nc)
                if target and target.color != piece.color:
                    targets.append((nr, nc, target))

    if not targets:
        return False

    # Pick random target
    tr, tc, target = random.choice(targets)
    
    # Calculate push direction (away from Florin)
    dr = tr - r
    dc = tc - c
    # Normalize to direction
    if dr != 0:
        dr = dr // abs(dr)
    if dc != 0:
        dc = dc // abs(dc)
    
    # Try to push 2 squares
    pushed = 0
    final_r, final_c = tr, tc
    for i in range(1, 3):
        nr = tr + (dr * i)
        nc = tc + (dc * i)
        if self.board.in_bounds(nr, nc) and not self.is_square_blocked(nr, nc):
            if self.board.get(nr, nc) is None:
                final_r, final_c = nr, nc
                pushed = i
            else:
                break
        else:
            break
    
    if pushed > 0:
        self.board.set(tr, tc, None)
        self.board.set(final_r, final_c, target)
        self.log_event("suppressing_fire", target=repr(target),
                       from_pos=(tr, tc), to_pos=(final_r, final_c), pushed=pushed)
        return True
    
    return False


def try_lava_surge_chunk2(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                          die_index: int) -> bool:
    """Chris's Lava Surge (Floor 4): Cover 3 squares with lava for 2 turns."""
    piece = self.board.get(*pawn_pos)
    if piece is None or not piece.is_pawn or piece.pawn_name != "Chris":
        return False
    if self.is_piece_suppressed(*pawn_pos):
        return False

    success = dice.spend_die(die_index, 4)
    self.log_event("ability_roll", piece="Chris", ability="Lava Surge",
                   die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
    if not success:
        return False

    r, c = pawn_pos
    # Cover Chris's square and 1 square on each side in rank or file
    # Randomly choose rank or file
    if random.choice([True, False]):
        # Rank (horizontal)
        lava_squares = [(r, c), (r, c-1), (r, c+1)]
    else:
        # File (vertical)
        lava_squares = [(r, c), (r-1, c), (r+1, c)]
    
    # Add lava zones
    for lr, lc in lava_squares:
        if self.board.in_bounds(lr, lc):
            self.lava_zones[(lr, lc)] = 2
    
    # Chris can't move for 2 turns
    self.chris_stuck.add(pawn_pos)
    
    self.log_event("lava_surge", pos=pawn_pos, lava_squares=lava_squares,
                   detail="Lava for 2 turns, Chris stuck")
    return True


# ── PRIORITY GROUP 3: Zone Blocking ───────────────────────────────

def try_air_strike(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                   die_index: int) -> bool:
    """Louie's Air Strike (Floor 6, requires combined): Create 2x2 blocked zone."""
    piece = self.board.get(*pawn_pos)
    if piece is None or not piece.is_pawn or piece.pawn_name != "Louie":
        return False
    if self.is_piece_suppressed(*pawn_pos):
        return False

    # Requires combined dice (total >= 6)
    if not dice.can_combine_for_cost(6):
        return False
    
    dice.spend_combined(6)
    self.log_event("ability_roll", piece="Louie", ability="Air Strike",
                   detail="Combined dice for cost 6", result="success")

    r, c = pawn_pos
    # Find valid 2x2 zones within 4 squares
    valid_zones = []
    for dr in range(-4, 5):
        for dc in range(-4, 5):
            zone_r, zone_c = r + dr, c + dc
            # Check if 2x2 zone is valid
            if self.board.in_bounds(zone_r, zone_c) and self.board.in_bounds(zone_r+1, zone_c+1):
                valid_zones.append((zone_r, zone_c))
    
    if valid_zones:
        zone_pos = random.choice(valid_zones)
        self.smoke_zones.append({"pos": zone_pos, "turns": 3})
        self.louie_cant_move.add(pawn_pos)
        self.log_event("air_strike", zone_pos=zone_pos, detail="2x2 blocked for 3 turns")
        return True
    
    return False


def try_lava_spit_chunk2(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                         die_index: int) -> bool:
    """Bad Llama's Lava Spit (Floor 4): Create 2x2 zone that forces movement."""
    piece = self.board.get(*pawn_pos)
    if piece is None or not piece.is_pawn or piece.pawn_name != "Bad Llama":
        return False
    if self.is_piece_suppressed(*pawn_pos):
        return False

    success = dice.spend_die(die_index, 4)
    self.log_event("ability_roll", piece="Bad Llama", ability="Lava Spit",
                   die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
    if not success:
        return False

    r, c = pawn_pos
    # Find valid 2x2 zones within 4 squares
    valid_zones = []
    for dr in range(-4, 5):
        for dc in range(-4, 5):
            zone_r, zone_c = r + dr, c + dc
            # Check if 2x2 zone is valid
            if self.board.in_bounds(zone_r, zone_c) and self.board.in_bounds(zone_r+1, zone_c+1):
                valid_zones.append((zone_r, zone_c))
    
    if valid_zones:
        zone_pos = random.choice(valid_zones)
        self.lava_spit_zones.append({"pos": zone_pos, "turns": 1})
        self.log_event("lava_spit", zone_pos=zone_pos, detail="2x2 zone forces movement")
        return True
    
    return False
