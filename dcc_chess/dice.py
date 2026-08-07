"""Dungeon Dice system for DCC Chess.

Each turn, a player rolls 2d6. They may spend one die on one ability if the
roll meets or beats the ability's Floor Number. Players can bank one die to
save it for later turns or reactions. AI summon triggers on double 1s, double 3s,
or one 6 and one 2.
"""

import random
from typing import List, Optional


class DungeonDice:
    """Manages the 2-die pool with banking system."""

    def __init__(self):
        self.dice: List[int] = []  # The 2 rolled values
        self.used: List[bool] = []  # Track which dice have been spent
        self.banked_die: dict = {"white": None, "black": None}  # Banked die per player
        self.pulled_from_bank: bool = False  # Whether player pulled from bank this turn

    def roll(self) -> List[int]:
        """Roll 2d6 for this turn."""
        self.dice = [random.randint(1, 6) for _ in range(2)]
        self.used = [False, False]
        self.pulled_from_bank = False
        return self.dice[:]

    @property
    def available_dice(self) -> List[int]:
        """Return indices of unspent dice."""
        return [i for i in range(2) if not self.used[i]]

    @property
    def remaining_count(self) -> int:
        return len(self.available_dice)

    def spend_die(self, die_index: int, floor_number: int) -> bool:
        """Spend a die on an ability. Returns True if the roll meets the floor.

        The die is consumed regardless of success.

        Args:
            die_index: which die (0 or 1) to spend
            floor_number: minimum roll needed for success

        Returns:
            True if roll >= floor_number, False otherwise
        """
        if die_index < 0 or die_index >= 2:
            raise ValueError(f"Invalid die index: {die_index}")
        if self.used[die_index]:
            raise ValueError(f"Die {die_index} already spent")

        self.used[die_index] = True
        return self.dice[die_index] >= floor_number

    def bank_die(self, die_index: int, player: str) -> bool:
        """Bank a die to save it for later. Returns True if successful.
        
        Can only bank if:
        - No die is currently banked for this player
        - The die hasn't been used
        - At least one die remains unused after banking
        
        Args:
            die_index: which die (0 or 1) to bank
            player: "white" or "black"
        """
        if self.banked_die[player] is not None:
            return False
        if die_index < 0 or die_index >= 2:
            return False
        if self.used[die_index]:
            return False
        
        self.banked_die[player] = self.dice[die_index]
        self.used[die_index] = True
        return True
    
    def pull_from_bank(self, player: str) -> bool:
        """Pull the banked die before rolling. Must be called before roll().
        
        Returns True if successful. The banked die is discarded and player
        rolls both dice fresh.
        
        Args:
            player: "white" or "black"
        """
        if self.banked_die[player] is None:
            return False
        
        self.banked_die[player] = None
        self.pulled_from_bank = True
        return True
    
    def spend_banked_die(self, floor_number: int, player: str) -> bool:
        """Spend the banked die (for reactions). Returns True if meets floor.
        
        The banked die is consumed regardless of success.
        
        Args:
            floor_number: minimum roll needed
            player: "white" or "black"
        """
        if self.banked_die[player] is None:
            raise ValueError("No banked die to spend")
        
        value = self.banked_die[player]
        self.banked_die[player] = None
        return value >= floor_number
    
    def combine_dice(self, floor_number: int) -> bool:
        """Combine both dice for high-cost abilities (>6).

        Returns True if combined value meets floor. Both dice are consumed.
        """
        if len(self.available_dice) < 2:
            raise ValueError("Need both dice available to combine")

        total = self.dice[0] + self.dice[1]
        self.used[0] = True
        self.used[1] = True
        return total >= floor_number

    def can_combine_for_cost(self, floor_number: int) -> bool:
        """Check if both dice are available and their combined sum meets floor.
        Non-destructive — does NOT consume the dice.
        """
        if len(self.available_dice) < 2:
            return False
        return self.dice[0] + self.dice[1] >= floor_number

    def spend_combined(self, floor_number: int) -> bool:
        """Spend both dice for a combined-cost ability.
        Returns True if the combined sum meets floor. Both dice are consumed.
        Raises ValueError if fewer than 2 dice are available.
        """
        if len(self.available_dice) < 2:
            raise ValueError("Need both dice available to combine")
        total = self.dice[0] + self.dice[1]
        self.used[0] = True
        self.used[1] = True
        return total >= floor_number
    
    def check_ai_summon_trigger(self) -> bool:
        """Check if the rolled dice trigger AI summon.

        Triggers on: double 1s, double 3s, or one 6 and one 2 (any order).
        Returns True if triggered.
        """
        if len(self.dice) != 2:
            return False
        return is_ai_summon_roll(self.dice[0], self.dice[1])

    def get_best_die_for_floor(self, floor_number: int) -> Optional[int]:
        """Find the best available die to attempt a given floor number.

        Strategy: use the lowest die that still meets the floor.
        If none meet it, use the lowest die (waste the worst one).
        Returns die index, or None if no dice available.
        """
        available = self.available_dice
        if not available:
            return None

        # Sort by value
        available_sorted = sorted(available, key=lambda i: self.dice[i])

        # Try to find lowest die that meets floor
        for idx in available_sorted:
            if self.dice[idx] >= floor_number:
                return idx

        # No die meets floor — return lowest (least waste)
        return available_sorted[0]

    def reroll_die(self, die_index: int) -> int:
        """Reroll a specific die (for Samantha's 'The Mouth' ability).

        Returns the new value.
        """
        if die_index < 0 or die_index >= 2:
            raise ValueError(f"Invalid die index: {die_index}")
        if self.used[die_index]:
            raise ValueError(f"Die {die_index} already spent, can't reroll")

        self.dice[die_index] = random.randint(1, 6)
        return self.dice[die_index]

    def apply_modifier(self, die_index: int, modifier: int):
        """Apply a modifier to a die value (e.g. Zev's +1 buff).

        Clamps to 1-6 range (a d6 can't go above 6 or below 1).
        """
        if die_index < 0 or die_index >= 2:
            return
        self.dice[die_index] = max(1, min(6, self.dice[die_index] + modifier))


def is_ai_summon_roll(d1: int, d2: int) -> bool:
    """Check whether a pair of d6 values triggers the AI Card summon.

    Triggers on: double 1s, double 3s, or one 6 and one 2 (any order).
    Shared by DungeonDice.check_ai_summon_trigger and any other roll of two
    dice that should be able to trigger it (e.g. a Mediation roll-off).
    """
    if (d1 == 1 and d2 == 1) or (d1 == 3 and d2 == 3):
        return True
    if (d1 == 6 and d2 == 2) or (d1 == 2 and d2 == 6):
        return True
    return False
