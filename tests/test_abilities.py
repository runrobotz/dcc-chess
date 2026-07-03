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


# ── Carl Abilities ────────────────────────────────────────────────

def test_bulldozer_success():
    """Bulldozer should grant extra king moves when die >= 4."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.CARL, Color.WHITE)
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [4, 1, 1]

    extra = gs.try_bulldozer((4, 4), d, 0)
    assert extra is not None, "Bulldozer should succeed with die=4"
    assert len(extra) > 0, "Should have extra move squares"
    # Verify extra moves are 2 squares away
    for r, c in extra:
        assert max(abs(r - 4), abs(c - 4)) == 2, f"({r},{c}) not 2 sq from (4,4)"
    print("  ✓ test_bulldozer_success passed")


def test_bulldozer_fail():
    """Bulldozer should fail when die < 4."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.CARL, Color.WHITE)
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [3, 1, 1]

    extra = gs.try_bulldozer((4, 4), d, 0)
    assert extra is None, "Bulldozer should fail with die=3"
    print("  ✓ test_bulldozer_fail passed")


def test_narrators_favor():
    """Narrator's Favor should slow Carl for 3 turns."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.CARL, Color.WHITE)
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [6, 1, 1]

    result = gs.try_narrators_favor(Color.WHITE, d, 0)
    assert result == True, "Should succeed with die=6"
    assert gs.carl_slowed[Color.WHITE] == 3
    assert gs.narrators_favor_used[Color.WHITE] == True
    print("  ✓ test_narrators_favor passed")


def test_narrators_favor_once_per_game():
    """Narrator's Favor can only be used once per game."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.CARL, Color.WHITE)
    gs = GameState(b)
    gs.narrators_favor_used[Color.WHITE] = True
    d = DungeonDice()
    d.roll()
    d.dice = [6, 6, 6]

    result = gs.try_narrators_favor(Color.WHITE, d, 0)
    assert result == False, "Should fail — already used"
    print("  ✓ test_narrators_favor_once_per_game passed")


# ── Donut Abilities ───────────────────────────────────────────────

def test_divas_entrance():
    """Diva's Entrance should add phantom threat square."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.DONUT, Color.WHITE)
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [3, 1, 1]

    result = gs.try_divas_entrance((4, 4), d, 0, (5, 5))
    assert result == True
    assert (5, 5) in gs.phantom_threats[Color.WHITE]
    print("  ✓ test_divas_entrance passed")


def test_resurrection():
    """Resurrection should bring back a captured piece."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.DONUT, Color.WHITE)
    place(b, 0, 0, PieceType.CARL, Color.WHITE)  # Need king on board

    # Simulate a captured piece
    captured_rook = Piece(PieceType.SAMANTHA, Color.WHITE)
    b.captured[Color.WHITE].append(captured_rook)

    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [6, 1, 1]

    result = gs.try_resurrection((4, 4), d, 0, Color.WHITE)
    assert result is not None, "Should resurrect a piece"
    assert len(b.captured[Color.WHITE]) == 0, "Captured list should be empty"
    print("  ✓ test_resurrection passed")


# ── Mongo Abilities ───────────────────────────────────────────────

def test_rampaging_charge():
    """Rampaging Charge should allow orthogonal movement."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.MONGO, Color.WHITE)
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [4, 1, 1]

    extra = gs.try_rampaging_charge((4, 4), d, 0)
    assert extra is not None, "Should succeed"
    # Should include orthogonal squares
    ortho = [(3, 4), (5, 4), (4, 3), (4, 5)]
    for sq in ortho:
        assert sq in extra, f"Should include orthogonal {sq}"
    print("  ✓ test_rampaging_charge passed")


def test_rampaging_charge_once():
    """Rampaging Charge is once per game per Mongo."""
    b = make_empty_board()
    mongo = place(b, 4, 4, PieceType.MONGO, Color.WHITE)
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [4, 4, 1]

    gs.try_rampaging_charge((4, 4), d, 0)
    extra = gs.try_rampaging_charge((4, 4), d, 1)
    assert extra is None, "Second use should fail"
    print("  ✓ test_rampaging_charge_once passed")


def test_mongo_smash():
    """Mongo Smash should capture piece outside normal range."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.MONGO, Color.WHITE)
    # Place enemy on orthogonal square (not reachable by bishop normally)
    place(b, 4, 5, PieceType.PAWN, Color.BLACK, "Zev")
    place(b, 0, 0, PieceType.CARL, Color.WHITE)
    place(b, 9, 9, PieceType.CARL, Color.BLACK)

    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [3, 1, 1]

    result = gs.try_mongo_smash((4, 4), d, 0)
    assert result == True, "Mongo Smash should capture orthogonal enemy"
    assert b.get(4, 5) is None, "Enemy should be removed"
    print("  ✓ test_mongo_smash passed")


# ── Katia Abilities ───────────────────────────────────────────────

def test_combat_roll():
    """Combat Roll should offer retreat to previously threatened squares."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.KATIA, Color.WHITE)
    gs = GameState(b)

    # Store current threats
    gs.update_katia_threats()
    threats = gs.katia_last_threats.get((4, 4), [])
    assert len(threats) == 8, f"Katia should threaten 8 squares, got {len(threats)}"

    d = DungeonDice()
    d.roll()
    d.dice = [3, 1, 1]

    retreats = gs.try_combat_roll((4, 4), d, 0)
    assert retreats is not None, "Should have retreat options"
    assert len(retreats) > 0
    print("  ✓ test_combat_roll passed")


def test_dual_threat():
    """Dual Threat should add phantom threat square."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.KATIA, Color.WHITE)
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [5, 1, 1]

    result = gs.try_dual_threat((4, 4), d, 0, (6, 6))
    assert result == True
    assert (6, 6) in gs.phantom_threats[Color.WHITE]
    print("  ✓ test_dual_threat passed")


# ── Samantha Abilities ────────────────────────────────────────────

def test_the_mouth():
    """The Mouth should reroll a die."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.SAMANTHA, Color.WHITE)
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [3, 1, 1]

    result = gs.try_the_mouth((4, 4), d, 0)
    assert result is not None, "Should reroll successfully"
    assert gs.mouth_used_this_turn == True
    print("  ✓ test_the_mouth passed")


def test_the_mouth_once_per_turn():
    """The Mouth can only be used once per turn."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.SAMANTHA, Color.WHITE)
    gs = GameState(b)
    gs.mouth_used_this_turn = True
    d = DungeonDice()
    d.roll()
    d.dice = [3, 3, 1]

    result = gs.try_the_mouth((4, 4), d, 0)
    assert result is None, "Should fail — already used this turn"
    print("  ✓ test_the_mouth_once_per_turn passed")


def test_portal_spike():
    """Portal Spike should teleport Samantha on rank/file."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.SAMANTHA, Color.WHITE)
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [5, 1, 1]

    random.seed(42)
    result = gs.try_portal_spike((4, 4), d, 0)
    assert result is not None, "Should teleport"
    assert b.get(4, 4) is None, "Original square should be empty"
    r, c = result
    assert r == 4 or c == 4, "Should be on same rank or file"
    print("  ✓ test_portal_spike passed")


# ── Pawn Ability Tests ────────────────────────────────────────────

def test_pack_rally():
    """Zev's Pack Rally should buff adjacent pawns."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.PAWN, Color.WHITE, "Zev")
    place(b, 4, 5, PieceType.PAWN, Color.WHITE, "Mordecai")
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [3, 1, 1]

    result = gs.try_pack_rally((4, 4), d, 0)
    assert result == True
    assert (4, 5) in gs.zev_buff_pawns
    print("  ✓ test_pack_rally passed")


def test_iron_wall():
    """Sledge's Iron Wall should make him invulnerable."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.PAWN, Color.WHITE, "Sledge")
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [3, 1, 1]

    result = gs.try_iron_wall((4, 4), d, 0)
    assert result == True
    assert gs.is_piece_invulnerable(4, 4)
    assert not gs.is_piece_movable(4, 4, b.get(4, 4))
    print("  ✓ test_iron_wall passed")


def test_suppression():
    """Imani's Suppression should suppress adjacent enemy."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.PAWN, Color.WHITE, "Imani")
    place(b, 4, 5, PieceType.KATIA, Color.BLACK)
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [4, 1, 1]

    result = gs.try_suppression((4, 4), d, 0)
    assert result == True
    assert gs.is_piece_suppressed(4, 5)
    print("  ✓ test_suppression passed")


def test_recruit():
    """Slugalo's Recruit should switch adjacent enemy pawn's side."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.PAWN, Color.WHITE, "Slugalo")
    place(b, 4, 5, PieceType.PAWN, Color.BLACK, "Mordecai")
    gs = GameState(b)
    gs.pawn_ability_uses["white_Slugalo"] = {"Recruit": 1}
    d = DungeonDice()
    d.roll()
    d.dice = [3, 1, 1]

    result = gs.try_recruit((4, 4), d, 0)
    assert result == True
    recruited = b.get(4, 5)
    assert recruited.color == Color.WHITE, "Recruited pawn should be white now"
    print("  ✓ test_recruit passed")


def test_smoke_bomb():
    """Louie's Smoke Bomb should create blocked zone."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.PAWN, Color.WHITE, "Louie")
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [4, 1, 1]

    random.seed(42)
    result = gs.try_smoke_bomb((4, 4), d, 0)
    assert result == True
    assert len(gs.smoke_zones) == 1
    assert (4, 4) in gs.louie_cant_move
    print("  ✓ test_smoke_bomb passed")


def test_titan_stride():
    """Prepotente's Titan Stride should allow 2-square forward."""
    b = make_empty_board()
    p = place(b, 4, 4, PieceType.PAWN, Color.WHITE, "Prepotente")
    p.has_moved = True
    gs = GameState(b)
    d = DungeonDice()
    d.roll()
    d.dice = [3, 1, 1]

    result = gs.try_titan_stride((4, 4), d, 0)
    assert result == (6, 4), f"Should move to (6,4), got {result}"
    print("  ✓ test_titan_stride passed")


def test_elle_mcgib_frozen_immunity():
    """Elle McGib should survive one capture attempt."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.PAWN, Color.WHITE, "Elle McGib")
    place(b, 4, 5, PieceType.SAMANTHA, Color.BLACK)
    place(b, 0, 0, PieceType.CARL, Color.WHITE)
    place(b, 9, 9, PieceType.CARL, Color.BLACK)

    gs = GameState(b)
    gs.pawn_ability_uses["white_Elle McGib"] = {"Frozen Immunity": 1}

    result = gs.attempt_capture((4, 5), (4, 4))
    assert result == "defended_elle", f"Should be defended, got {result}"
    assert b.get(4, 4) is not None, "Elle should still be on the board"
    print("  ✓ test_elle_mcgib_frozen_immunity passed")


def test_mordecai_haunt():
    """Mordecai's Haunt should leave ghost token on capture."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.PAWN, Color.BLACK, "Mordecai")
    attacker = place(b, 4, 5, PieceType.SAMANTHA, Color.WHITE)

    gs = GameState(b)
    captured = Piece(PieceType.PAWN, Color.BLACK, pawn_name="Mordecai")
    gs.process_post_capture(captured, (4, 4), attacker, (4, 5))
    assert (4, 4) in gs.ghost_tokens, "Ghost token should be placed"
    assert gs.ghost_tokens[(4, 4)] == 2
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


def test_carl_slowed_movement():
    """Slowed Carl should only move every other turn."""
    b = make_empty_board()
    carl = place(b, 4, 4, PieceType.CARL, Color.WHITE)
    gs = GameState(b)
    gs.carl_slowed[Color.WHITE] = 3
    gs.carl_slowed_can_move[Color.WHITE] = True
    gs.current_player = Color.WHITE

    # Turn 1: can move
    assert gs.is_piece_movable(4, 4, carl)

    gs.end_turn()  # Ticks down, flips can_move
    gs.current_player = Color.WHITE  # Force back for testing

    # Turn 2: can't move
    assert not gs.is_piece_movable(4, 4, carl)

    gs.end_turn()
    gs.current_player = Color.WHITE

    # Turn 3: can move again
    assert gs.is_piece_movable(4, 4, carl)

    gs.end_turn()
    # Should auto-recover (slowed = 0)
    assert gs.carl_slowed[Color.WHITE] == 0
    assert gs.carl_slowed_can_move[Color.WHITE] == True
    print("  ✓ test_carl_slowed_movement passed")


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
    """Quasar mediation should sometimes defend."""
    b = make_empty_board()
    place(b, 4, 4, PieceType.PAWN, Color.WHITE, "Zev")
    place(b, 4, 5, PieceType.SAMANTHA, Color.BLACK)
    place(b, 0, 0, PieceType.PAWN, Color.WHITE, "Quasar")  # Quasar alive anywhere
    place(b, 0, 5, PieceType.CARL, Color.WHITE)
    place(b, 9, 0, PieceType.CARL, Color.BLACK)

    gs = GameState(b)

    # Run multiple times to see both outcomes
    defended = 0
    captured = 0
    for i in range(100):
        gs.quasar_uses[Color.WHITE] = 0
        result = gs.attempt_capture((4, 5), (4, 4))
        if result == "defended_quasar":
            defended += 1
        else:
            captured += 1

    assert defended > 0, "Quasar should defend at least sometimes"
    assert captured > 0, "Quasar should fail at least sometimes"
    print(f"  ✓ test_quasar_mediation passed (defended={defended}, captured={captured} in 100 trials)")


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

    print("\n[Carl Abilities]")
    test_bulldozer_success()
    test_bulldozer_fail()
    test_narrators_favor()
    test_narrators_favor_once_per_game()

    print("\n[Donut Abilities]")
    test_divas_entrance()
    test_resurrection()

    print("\n[Mongo Abilities]")
    test_rampaging_charge()
    test_rampaging_charge_once()
    test_mongo_smash()

    print("\n[Katia Abilities]")
    test_combat_roll()
    test_dual_threat()

    print("\n[Samantha Abilities]")
    test_the_mouth()
    test_the_mouth_once_per_turn()
    test_portal_spike()

    print("\n[Pawn Abilities]")
    test_pack_rally()
    test_iron_wall()
    test_suppression()
    test_recruit()
    test_smoke_bomb()
    test_titan_stride()
    test_elle_mcgib_frozen_immunity()
    test_mordecai_haunt()

    print("\n[Status Effects]")
    test_ghost_token_blocks()
    test_ghost_token_expires()
    test_carl_slowed_movement()
    test_status_effects_on_legal_moves()

    print("\n[Quasar Mediation]")
    test_quasar_mediation()

    print("\n" + "=" * 60)
    print("All Stage 2 tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all()
