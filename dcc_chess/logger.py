"""Game event logging and stats aggregation for DCC Chess.

Per-game tracking:
- Every ability fired: which piece, which ability, die roll, success/fail
- Captures: who captured whom, on what turn
- Game length (turns)
- Which pawns were drafted by each side
- Promotion events

Aggregate across games:
- Ability success rate per ability
- Average game length
- Pawn draft frequency
- Piece capture frequency
- Win rate by side (white vs black)
"""

from typing import List, Dict, Optional
from collections import defaultdict, Counter


class GameRecord:
    """Record of a single completed game."""

    def __init__(
        self,
        game_id: int,
        winner: Optional[str],
        result_reason: str,
        turns: int,
        white_pawns: List[str],
        black_pawns: List[str],
        events: List[Dict],
    ):
        self.game_id = game_id
        self.winner = winner  # "white", "black", or None (draw)
        self.result_reason = result_reason
        self.turns = turns
        self.white_pawns = white_pawns
        self.black_pawns = black_pawns
        self.events = events

        # Derived stats
        self.ability_attempts = []
        self.captures = []
        self.promotions = []
        self._parse_events()

    def _parse_events(self):
        for e in self.events:
            etype = e.get("type", "")
            if etype == "ability_roll":
                self.ability_attempts.append({
                    "piece": e.get("piece"),
                    "ability": e.get("ability"),
                    "die_value": e.get("die_value"),
                    "floor": e.get("floor"),
                    "result": e.get("result"),
                    "turn": e.get("turn"),
                    "player": e.get("player"),
                })
            elif etype == "ability_auto":
                self.ability_attempts.append({
                    "piece": e.get("piece"),
                    "ability": e.get("ability"),
                    "result": e.get("result", "auto"),
                    "turn": e.get("turn"),
                    "player": e.get("player"),
                })
            elif etype == "move" and e.get("captured"):
                self.captures.append({
                    "attacker": e.get("piece"),
                    "captured": e.get("captured"),
                    "turn": e.get("turn"),
                    "player": e.get("player"),
                })
            elif etype == "mediation_capture":
                self.captures.append({
                    "attacker": "Quasar(mediation)",
                    "captured": e.get("captured"),
                    "turn": e.get("turn"),
                    "player": e.get("player"),
                })
            elif etype == "mongo_smash_capture":
                self.captures.append({
                    "attacker": "Mongo(smash)",
                    "captured": e.get("target"),
                    "turn": e.get("turn"),
                    "player": e.get("player"),
                })
            elif etype == "lava_surge_capture":
                self.captures.append({
                    "attacker": "Chris(lava)",
                    "captured": e.get("captured"),
                    "turn": e.get("turn"),
                    "player": e.get("player"),
                })
            elif etype == "lava_spit_capture":
                self.captures.append({
                    "attacker": "Bad Llama(spit)",
                    "captured": e.get("captured"),
                    "turn": e.get("turn"),
                    "player": e.get("player"),
                })
            elif etype == "resurrection":
                self.promotions.append({
                    "type": "resurrection",
                    "piece": e.get("piece"),
                    "turn": e.get("turn"),
                })


class StatsAggregator:
    """Aggregates stats across multiple games."""

    def __init__(self):
        self.records: List[GameRecord] = []

    def add_game(self, record: GameRecord):
        self.records.append(record)

    @property
    def total_games(self) -> int:
        return len(self.records)

    def win_rates(self) -> Dict[str, float]:
        """Win rate by side."""
        counts = Counter()
        for r in self.records:
            if r.winner:
                counts[r.winner] += 1
            else:
                counts["draw"] += 1
        total = self.total_games
        return {k: v / total for k, v in counts.items()} if total > 0 else {}

    def avg_game_length(self) -> float:
        if not self.records:
            return 0
        return sum(r.turns for r in self.records) / len(self.records)

    def median_game_length(self) -> float:
        if not self.records:
            return 0
        lengths = sorted(r.turns for r in self.records)
        n = len(lengths)
        if n % 2 == 0:
            return (lengths[n // 2 - 1] + lengths[n // 2]) / 2
        return lengths[n // 2]

    def result_breakdown(self) -> Dict[str, int]:
        counts = Counter()
        for r in self.records:
            counts[r.result_reason] += 1
        return dict(counts)

    def ability_stats(self) -> Dict[str, Dict]:
        """Per-ability success rate, total attempts, total successes."""
        stats = defaultdict(lambda: {"attempts": 0, "successes": 0, "fails": 0, "auto": 0})
        for r in self.records:
            for a in r.ability_attempts:
                name = a.get("ability", "unknown")
                stats[name]["attempts"] += 1
                result = a.get("result", "")
                if result == "success":
                    stats[name]["successes"] += 1
                elif result == "fail":
                    stats[name]["fails"] += 1
                elif result == "auto":
                    stats[name]["auto"] += 1

        # Calculate rates
        for name, s in stats.items():
            rollable = s["successes"] + s["fails"]
            s["success_rate"] = s["successes"] / rollable if rollable > 0 else None

        return dict(stats)

    def pawn_draft_frequency(self) -> Dict[str, int]:
        """How often each pawn was drafted (total across both sides)."""
        counts = Counter()
        for r in self.records:
            for name in r.white_pawns:
                counts[name] += 1
            for name in r.black_pawns:
                counts[name] += 1
        return dict(counts.most_common())

    def piece_capture_frequency(self) -> Dict[str, int]:
        """How often each piece type was captured."""
        counts = Counter()
        for r in self.records:
            for cap in r.captures:
                captured = cap.get("captured", "unknown")
                counts[captured] += 1
        return dict(counts.most_common())

    def capture_stats_summary(self) -> Dict:
        """Total captures and average per game."""
        total = sum(len(r.captures) for r in self.records)
        return {
            "total_captures": total,
            "avg_per_game": total / self.total_games if self.total_games > 0 else 0,
        }

    def generate_report(self) -> str:
        """Generate a full summary report."""
        lines = []
        lines.append("=" * 70)
        lines.append("  DUNGEON CRAWLER CARL CHESS — SIMULATION REPORT")
        lines.append("=" * 70)
        lines.append(f"\nGames played: {self.total_games}")
        lines.append(f"Average game length: {self.avg_game_length():.1f} turns")
        lines.append(f"Median game length: {self.median_game_length():.0f} turns")

        # Results
        lines.append("\n--- Result Breakdown ---")
        for reason, count in sorted(self.result_breakdown().items()):
            pct = count / self.total_games * 100
            lines.append(f"  {reason:20s}: {count:4d} ({pct:5.1f}%)")

        # Win rates
        lines.append("\n--- Win Rates ---")
        for side, rate in sorted(self.win_rates().items()):
            lines.append(f"  {side:20s}: {rate*100:5.1f}%")

        # Ability stats
        lines.append("\n--- Ability Stats ---")
        lines.append(f"  {'Ability':<30s} {'Attempts':>8s} {'Success':>8s} {'Fail':>6s} {'Auto':>6s} {'Rate':>7s}")
        lines.append("  " + "-" * 67)
        ab_stats = self.ability_stats()
        for name in sorted(ab_stats.keys()):
            s = ab_stats[name]
            rate_str = f"{s['success_rate']*100:.1f}%" if s['success_rate'] is not None else "  auto"
            lines.append(
                f"  {name:<30s} {s['attempts']:>8d} {s['successes']:>8d} "
                f"{s['fails']:>6d} {s['auto']:>6d} {rate_str:>7s}"
            )

        # Flag extreme ability stats
        lines.append("\n--- Ability Flags ---")
        flagged = False
        for name, s in ab_stats.items():
            if s["success_rate"] is not None:
                if s["success_rate"] >= 0.85 and s["attempts"] >= 10:
                    lines.append(f"  ⚠ {name}: potentially overpowered ({s['success_rate']*100:.1f}% success)")
                    flagged = True
                elif s["success_rate"] <= 0.15 and s["attempts"] >= 10:
                    lines.append(f"  ⚠ {name}: potentially too difficult ({s['success_rate']*100:.1f}% success)")
                    flagged = True
        if not flagged:
            lines.append("  No extreme ability rates detected.")

        # Pawn draft frequency
        lines.append("\n--- Pawn Draft Frequency ---")
        draft_freq = self.pawn_draft_frequency()
        total_drafts = self.total_games * 2  # 2 players per game
        max_possible = total_drafts * 10 / 11  # Expected if uniform
        for name, count in draft_freq.items():
            pct = count / (total_drafts) * 100 if total_drafts > 0 else 0
            flag = ""
            if pct < 35.0:
                flag = " ⚠ drafted <35%"
            lines.append(f"  {name:<25s}: {count:4d} drafts ({pct:5.1f}%){flag}")

        # Flag pawns never/always drafted
        lines.append("\n--- Draft Flags ---")
        from .board import PAWN_ROSTER
        undrafted = [name for name in PAWN_ROSTER if name not in draft_freq]
        if undrafted:
            for name in undrafted:
                lines.append(f"  ⚠ {name}: never drafted in {self.total_games} games")
        else:
            lines.append("  All pawns were drafted at least once.")

        # Capture stats
        lines.append("\n--- Capture Stats ---")
        cap_summary = self.capture_stats_summary()
        lines.append(f"  Total captures: {cap_summary['total_captures']}")
        lines.append(f"  Average per game: {cap_summary['avg_per_game']:.1f}")

        # Most captured pieces
        lines.append("\n  Most frequently captured:")
        cap_freq = self.piece_capture_frequency()
        for name, count in list(cap_freq.items())[:15]:
            lines.append(f"    {name:<40s}: {count:4d}")

        lines.append("\n" + "=" * 70)
        return "\n".join(lines)
