"""Run 100 DCC Chess games and print a summary report.

Usage: python run_simulation.py [num_games]
"""

import sys
import time

from dcc_chess.game import Game
from dcc_chess.ai import random_draft, random_back_rank, random_move, random_abilities, smart_move, smart_abilities
from dcc_chess.logger import GameRecord, StatsAggregator


def run_simulation(num_games: int = 100):
    agg = StatsAggregator()
    start_time = time.time()

    for i in range(num_games):
        wp = random_draft()
        bp = random_draft()
        game = Game(
            white_pawns=wp,
            black_pawns=bp,
            white_back_rank=random_back_rank(),
            black_back_rank=random_back_rank(),
        )

        winner, reason = game.play_full_game(smart_move, smart_abilities)

        record = GameRecord(
            game_id=i + 1,
            winner=winner.value if winner else None,
            result_reason=reason,
            turns=game.state.turn_number,
            white_pawns=wp,
            black_pawns=bp,
            events=game.state.events,
        )
        agg.add_game(record)

        # Progress indicator
        if (i + 1) % 10 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            eta = (num_games - i - 1) / rate
            print(f"  Game {i+1:3d}/{num_games} done  "
                  f"({elapsed:.1f}s elapsed, ~{eta:.0f}s remaining)", flush=True)

    elapsed = time.time() - start_time
    print(f"\nCompleted {num_games} games in {elapsed:.1f}s "
          f"({elapsed/num_games:.2f}s per game)\n")

    report = agg.generate_report()
    print(report)

    # Flag checks
    avg_len = agg.avg_game_length()
    wr = agg.win_rates()
    flags = []
    if avg_len > 120:
        flags.append(f"⚠ AVG GAME LENGTH {avg_len:.1f} > 120 turns — consider further adjustments")
    if abs(wr.get('white', 0) - wr.get('black', 0)) > 0.15:
        flags.append(f"⚠ WIN RATE IMBALANCE: white={wr.get('white',0)*100:.1f}% "
                     f"black={wr.get('black',0)*100:.1f}% — possible first-move advantage")
    if flags:
        print("\n" + "=" * 70)
        print("  FLAGS")
        print("=" * 70)
        for f in flags:
            print(f"  {f}")
        print()
    else:
        print("\n  ✓ No flags — game length and win rates look good.\n")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    run_simulation(n)
