"""Tests for Stage 4: Game logger and stats aggregation."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import random
from dcc_chess.game import Game
from dcc_chess.ai import random_draft, random_back_rank, random_move, random_abilities
from dcc_chess.logger import GameRecord, StatsAggregator


def run_game_and_record(game_id: int) -> GameRecord:
    """Run a game and return a GameRecord."""
    wp = random_draft()
    bp = random_draft()
    game = Game(
        white_pawns=wp, black_pawns=bp,
        white_back_rank=random_back_rank(),
        black_back_rank=random_back_rank(),
    )
    winner, reason = game.play_full_game(random_move, random_abilities)
    return GameRecord(
        game_id=game_id,
        winner=winner.value if winner else None,
        result_reason=reason,
        turns=game.state.turn_number,
        white_pawns=wp,
        black_pawns=bp,
        events=game.state.events,
    )


def test_game_record_parsing():
    """GameRecord should parse events into ability attempts and captures."""
    random.seed(42)
    record = run_game_and_record(1)

    assert record.turns > 0, "Game should have turns"
    assert len(record.events) > 0, "Should have events"
    assert len(record.ability_attempts) > 0, "Should have ability attempts"
    assert len(record.captures) > 0, "Should have captures"

    # Check ability attempt structure
    a = record.ability_attempts[0]
    assert "ability" in a, "Should have ability name"
    assert "result" in a, "Should have result"

    print(f"  ✓ test_game_record_parsing passed — {len(record.ability_attempts)} abilities, "
          f"{len(record.captures)} captures, {record.turns} turns")


def test_stats_aggregator():
    """StatsAggregator should compute correct stats from multiple games."""
    random.seed(99)
    agg = StatsAggregator()

    for i in range(5):
        record = run_game_and_record(i)
        agg.add_game(record)

    assert agg.total_games == 5
    assert agg.avg_game_length() > 0

    # Win rates should sum to ~1.0
    wr = agg.win_rates()
    assert abs(sum(wr.values()) - 1.0) < 0.01, f"Win rates should sum to 1, got {sum(wr.values())}"

    # Ability stats should have entries
    ab = agg.ability_stats()
    assert len(ab) > 0, "Should have ability stats"

    # Draft frequency should include all 11 pawns (with 5 games it's very likely)
    df = agg.pawn_draft_frequency()
    assert len(df) > 0, "Should have draft frequency"

    print(f"  ✓ test_stats_aggregator passed — {agg.total_games} games, "
          f"{len(ab)} abilities tracked, avg {agg.avg_game_length():.1f} turns")


def test_report_generation():
    """Report should generate without errors and contain key sections."""
    random.seed(77)
    agg = StatsAggregator()

    for i in range(3):
        record = run_game_and_record(i)
        agg.add_game(record)

    report = agg.generate_report()
    assert len(report) > 100, "Report should be substantial"
    assert "Win Rates" in report
    assert "Ability Stats" in report
    assert "Pawn Draft Frequency" in report
    assert "Capture Stats" in report
    assert "SIMULATION REPORT" in report

    print("  ✓ test_report_generation passed")
    print("\n--- Sample Report (3 games) ---")
    print(report)


def run_all():
    print("=" * 60)
    print("Stage 4 Tests: Game Logger + Stats")
    print("=" * 60)

    print("\n[Game Record]")
    test_game_record_parsing()

    print("\n[Stats Aggregator]")
    test_stats_aggregator()

    print("\n[Report Generation]")
    test_report_generation()

    print("\n" + "=" * 60)
    print("All Stage 4 tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all()
