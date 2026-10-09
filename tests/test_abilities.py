"""Tests for Stage 2: Dungeon Dice system and all abilities."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import random
from dcc_chess.pieces import Piece, PieceType, Color
from dcc_chess.board import Board, BOARD_SIZE
from dcc_chess.dice import DungeonDice
from dcc_chess.abilities import GameState
from dcc_chess.pawns import PAWN_CHARACTERS
from dcc_chess.movement import pseudo_legal_moves_for_piece, is_in_check


def make_empty_board():
    return Board()


def place(board, row, col, piece_type, color, pawn_name=None):
    p = Piece(piece_type, color, pawn_name=pawn_name)
    board.set(row, col, p)
    return p


# ── Dice System Tests ─────────────────────────────────────────────

def test_dice_roll():
    """Dice should produce 3 values between 1-6."""
    d = DungeonDice()
    values = d.roll()
    assert len(values) == 3
    for v in values:
        assert 1 <= v <= 6
    assert d.remaining_count == 3
    print("  ✓ test_dice_roll passed")


def test_dice_spend():
    """Spending a die should consume it regardless of success."""
    d = DungeonDice()
    d.roll()
    d.dice = [3, 5, 1]  # Force values

    # Floor 4: die[0]=3 should fail
    result = d.spend_die(0, 4)
    assert result == False
    assert d.remaining_count == 2

    # Floor 4: die[1]=5 should succeed
    result = d.spend_die(1, 4)
    assert result == True
    assert d.remaining_count == 1

    print("  ✓ test_dice_spend passed")


def test_dice_spend_already_used():
    """Can't spend an already-used die."""
    d = DungeonDice()
    d.roll()
    d.spend_die(0, 1)
    try:
        d.spend_die(0, 1)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    print("  ✓ test_dice_spend_already_used passed")


def test_dice_reroll():
    """Reroll should change die value."""
    d = DungeonDice()
    d.roll()
    d.dice = [1, 1, 1]
    random.seed(42)
    new_val = d.reroll_die(0)
    assert 1 <= new_val <= 6
    assert d.dice[0] == new_val
    print("  ✓ test_dice_reroll passed")


def test_dice_best_die():
    """Best die selection should prefer lowest die that meets floor."""
    d = DungeonDice()
    d.roll()
    d.dice = [2, 4, 6]

    # Floor 4: should pick die[1]=4 (lowest that meets)
    idx = d.get_best_die_for_floor(4)
    assert idx == 1, f"Should pick die 1, got {idx}"

    # Floor 7: nothing meets, should pick lowest (die[0]=2)
    idx = d.get_best_die_for_floor(7)
    assert idx == 0, f"Should pick die 0, got {idx}"

    print("  ✓ test_dice_best_die passed")


# ── Mordecai, Ghost Tokens, and Status Effects ───────────────────

def test_mordecai_haunt():
    """Mordecai's Haunt should leave ghost token on capture."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.PAWN, Color.BLACK, "Mordecai")
    attacker = place(b, 4, 5, PieceType.SAMANTHA, Color.WHITE)

    gs = GameState(b)
    captured = Piece(PieceType.PAWN, Color.BLACK, pawn_name="Mordecai")
    gs.process_post_capture(captured, (4, 4), attacker, (4, 5))
    assert (4, 4) in gs.ghost_tokens, "Ghost token should be placed"
    assert gs.ghost_tokens[(4, 4)] == 3
    assert gs.mordecai_respawn_pending[0]["turns_left"] == 3
    print("  ✓ test_mordecai_haunt passed")


def test_ghost_token_blocks():
    """Ghost tokens should block movement."""
    b = make_empty_board()
    gs = GameState(b)
    gs.ghost_tokens[(4, 4)] = 2
    assert gs.is_square_blocked(4, 4)
    print("  ✓ test_ghost_token_blocks passed")


def test_ghost_token_expires():
    """Ghost tokens should expire after 2 turns."""
    b = make_empty_board()
    gs = GameState(b)
    gs.ghost_tokens[(4, 4)] = 2

    gs.end_turn()  # Turn 1
    assert (4, 4) in gs.ghost_tokens
    gs.end_turn()  # Turn 2
    assert (4, 4) not in gs.ghost_tokens
    print("  ✓ test_ghost_token_expires passed")


def test_status_effects_on_legal_moves():
    """Status effects should filter legal moves."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.SAMANTHA, Color.WHITE)
    place(b, 0, 0, PieceType.CARL, Color.WHITE)
    gs = GameState(b)
    gs.current_player = Color.WHITE

    # Block a square with ghost token
    gs.ghost_tokens[(4, 7)] = 2

    moves = gs.get_legal_moves_with_status(Color.WHITE)
    to_squares = [to for _, to in moves if _[0] == 4 and _[1] == 4]
    assert (4, 7) not in to_squares, "Ghost-blocked square should not be a valid move"
    print("  ✓ test_status_effects_on_legal_moves passed")


# ── Quasar Mediation Test ─────────────────────────────────────────

def test_quasar_mediation():
    """Quasar mediation should sometimes defend a non-Carl piece (defender must
    win the 2d6-vs-2d6 roll-off by 2 or more), and sometimes fail.

    A fresh board/GameState is built each iteration so that a Mediation roll
    which happens to trigger an AI Summon card can't cascade into later trials.
    """
    defended = 0
    captured = 0
    for _ in range(300):
        b = make_empty_board()
        place(b, 4, 4, PieceType.PAWN, Color.WHITE, "Zev")
        place(b, 4, 5, PieceType.SAMANTHA, Color.BLACK)
        place(b, 0, 0, PieceType.PAWN, Color.WHITE, "Quasar")  # Quasar alive anywhere
        # White Carl kept clear of the attacking Samantha's rank/file -- Mediation
        # cannot fire while the defending side's Carl is in check.
        place(b, 0, 9, PieceType.CARL, Color.WHITE)
        place(b, 9, 0, PieceType.CARL, Color.BLACK)

        gs = GameState(b)
        result = gs.attempt_capture((4, 5), (4, 4))
        if result == "defended_quasar":
            defended += 1
        else:
            captured += 1

    assert defended > 0, "Quasar should defend at least sometimes"
    assert captured > 0, "Quasar should fail at least sometimes"
    print(f"  ✓ test_quasar_mediation passed (defended={defended}, captured={captured} in 300 trials)")


# ── Run All Tests ─────────────────────────────────────────────────

def run_all():
    print("=" * 60)
    print("Stage 2 Tests: Dungeon Dice + Abilities")
    print("=" * 60)

    print("\n[Dice System]")
    test_dice_roll()
    test_dice_spend()
    test_dice_spend_already_used()
    test_dice_reroll()
    test_dice_best_die()

    print("\n[Pawn Abilities]")
    test_mordecai_haunt()

    print("\n[Status Effects]")
    test_ghost_token_blocks()
    test_ghost_token_expires()
    test_status_effects_on_legal_moves()

    print("\n[Quasar Mediation]")
    test_quasar_mediation()

    print("\n" + "=" * 60)
    print("All Stage 2 tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all()
