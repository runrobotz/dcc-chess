"""Tests for Stage 3: Random AI players + full game integration."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import random
from dcc_chess.pieces import Color
from dcc_chess.board import PAWN_ROSTER
from dcc_chess.game import Game
from dcc_chess.ai import random_draft, random_back_rank, random_move, random_abilities


def test_random_draft():
    """Draft should produce 10 unique pawns."""
    draft = random_draft()
    assert len(draft) == 10, f"Draft should have 10 pawns, got {len(draft)}"
    assert len(set(draft)) == 10, "All pawns should be unique"
    for name in draft:
        assert name in PAWN_ROSTER, f"{name} not in roster"
    print("  ✓ test_random_draft passed")


def test_random_back_rank():
    """Back rank should be 8 sorted unique columns from 0-9."""
    rank = random_back_rank()
    assert len(rank) == 8
    assert len(set(rank)) == 8
    assert rank == sorted(rank)
    for c in rank:
        assert 0 <= c < 10
    print("  ✓ test_random_back_rank passed")


def test_single_game():
    """Run a single full game and verify it terminates."""
    random.seed(42)
    wp = random_draft()
    bp = random_draft()
    wbr = random_back_rank()
    bbr = random_back_rank()

    game = Game(
        white_pawns=wp, black_pawns=bp,
        white_back_rank=wbr, black_back_rank=bbr,
    )

    winner, reason = game.play_full_game(random_move, random_abilities)

    assert game.game_over, "Game should be over"
    assert reason in ("checkmate", "stalemate", "king_captured", "max_turns"), \
        f"Unexpected result: {reason}"

    print(f"  ✓ test_single_game passed — {reason}, winner={winner}, "
          f"turns={game.state.turn_number}, events={len(game.state.events)}")


def test_multiple_games():
    """Run 5 games to verify stability."""
    results = {"checkmate": 0, "stalemate": 0, "king_captured": 0, "max_turns": 0}
    total_turns = 0
    total_events = 0

    for i in range(5):
        game = Game()
        winner, reason = game.play_full_game(random_move, random_abilities)
        results[reason] = results.get(reason, 0) + 1
        total_turns += game.state.turn_number
        total_events += len(game.state.events)

    avg_turns = total_turns / 5
    avg_events = total_events / 5

    print(f"  ✓ test_multiple_games passed — 5 games completed")
    print(f"    Results: {results}")
    print(f"    Avg turns: {avg_turns:.1f}, Avg events: {avg_events:.1f}")


def test_game_events_logged():
    """Verify that game events are being logged."""
    random.seed(123)
    game = Game()
    game.play_full_game(random_move, random_abilities)

    events = game.state.events
    assert len(events) > 0, "Should have logged events"

    # Check for move events
    move_events = [e for e in events if e["type"] == "move"]
    assert len(move_events) > 0, "Should have move events"

    # Check for dice roll events
    dice_events = [e for e in events if e["type"] == "dice_roll"]
    assert len(dice_events) > 0, "Should have dice roll events"

    # Check for ability events
    ability_events = [e for e in events if e["type"] in ("ability_roll", "ability_auto")]
    print(f"  ✓ test_game_events_logged passed — {len(events)} total events, "
          f"{len(move_events)} moves, {len(dice_events)} dice rolls, "
          f"{len(ability_events)} ability attempts")


def test_game_with_abilities_firing():
    """Run games until we see at least one ability fire."""
    abilities_seen = set()

    for i in range(20):
        random.seed(i * 7)
        game = Game()
        game.play_full_game(random_move, random_abilities)

        for event in game.state.events:
            if event["type"] == "ability_roll":
                abilities_seen.add(event.get("ability", "unknown"))
            elif event["type"] == "ability_auto":
                abilities_seen.add(event.get("ability", "unknown"))

    assert len(abilities_seen) > 0, "Should see at least one ability across 20 games"
    print(f"  ✓ test_game_with_abilities_firing passed — abilities seen: {abilities_seen}")


def run_all():
    print("=" * 60)
    print("Stage 3 Tests: Random AI Players + Full Game")
    print("=" * 60)

    print("\n[Draft & Setup]")
    test_random_draft()
    test_random_back_rank()

    print("\n[Single Game]")
    test_single_game()

    print("\n[Event Logging]")
    test_game_events_logged()

    print("\n[Multiple Games]")
    test_multiple_games()

    print("\n[Ability Firing]")
    test_game_with_abilities_firing()

    print("\n" + "=" * 60)
    print("All Stage 3 tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all()
