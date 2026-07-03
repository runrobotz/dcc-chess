"""Pawn roster definitions for DCC Chess.

Each pawn has a single active ability with a Floor Number (or auto-trigger).
21 characters in the roster; each player drafts 8.
"""

from enum import Enum
from typing import Optional


class AbilityTrigger(Enum):
    """How an ability is activated."""
    FLOOR_ROLL = "floor_roll"      # Costs a die, must meet floor number
    AUTO_ON_CAPTURE = "auto_capture"  # Triggers automatically when captured (no die)
    AUTO_DEFENSE = "auto_defense"    # Triggers automatically to negate capture (no die)
    NO_ROLL = "no_roll"             # No die needed, but limited uses


class PawnAbility:
    """Definition of a pawn's ability."""

    def __init__(
        self,
        name: str,
        description: str,
        floor_number: int,
        trigger: AbilityTrigger,
        uses_per_game: Optional[int] = None,  # None = unlimited
        requires_combined: bool = False,  # True if ability needs both dice combined
    ):
        self.name = name
        self.description = description
        self.floor_number = floor_number
        self.trigger = trigger
        self.uses_per_game = uses_per_game
        self.requires_combined = requires_combined


class PawnCharacter:
    """Definition of a pawn character in the roster."""

    def __init__(self, name: str, ability: PawnAbility, is_female: bool = False):
        self.name = name
        self.ability = ability
        self.is_female = is_female


# ── The Full Roster ───────────────────────────────────────────────

PAWN_CHARACTERS = {
    "Zev": PawnCharacter(
        name="Zev",
        ability=PawnAbility(
            name="Biggest Fan",
            description="All friendly pieces get +1 to all dice rolls on the next turn. Takes effect the following turn.",
            floor_number=3,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=True,
    ),

    "The AI": PawnCharacter(
        name="The AI",
        ability=PawnAbility(
            name="Glitch",
            description="Copies a random friendly pawn's active ability for this turn. "
                        "Uses the copied ability's Floor Number.",
            floor_number=0,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=False,
    ),

    "Mordecai": PawnCharacter(
        name="Mordecai",
        ability=PawnAbility(
            name="Manager Benefit",
            description="Cannot attack. When captured, creates a ghost blocking his square and all 8 surrounding squares for 2 full turns. No piece can enter those squares. After 2 turns Mordecai respawns on his player's back rank. While within 1 square of Carl or Donut, their abilities cost 1 less.",
            floor_number=0,
            trigger=AbilityTrigger.AUTO_ON_CAPTURE,
        ),
        is_female=False,
    ),

    "Prepotente": PawnCharacter(
        name="Prepotente",
        ability=PawnAbility(
            name="Special Boy",
            description="Moves 2 squares forward this turn including for captures. If this move specifically saves Carl from check, Prepotente can move 2 squares in any direction.",
            floor_number=4,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=False,
    ),

    "Elle McGib": PawnCharacter(
        name="Elle McGib",
        ability=PawnAbility(
            name="Frozen",
            description="Freeze any one enemy piece within 5 squares for 1 full turn. Frozen piece cannot move or use abilities.",
            floor_number=5,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=True,
    ),

    "Imani": PawnCharacter(
        name="Imani",
        ability=PawnAbility(
            name="Suppress",
            description="One enemy piece within 2 squares loses all abilities for its next turn.",
            floor_number=4,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=True,
    ),

    "Slugalo": PawnCharacter(
        name="Slugalo",
        ability=PawnAbility(
            name="One Of Us",
            description="Recruit any one enemy pawn to your team for the rest of the match. Recruited pawn keeps its ability. If captured it returns to original owner.",
            floor_number=7,
            trigger=AbilityTrigger.FLOOR_ROLL,
            uses_per_game=1,
            requires_combined=True,
        ),
        is_female=False,
    ),

    "Louie": PawnCharacter(
        name="Louie",
        ability=PawnAbility(
            name="Air Strike",
            description="Create a 2x2 blocked zone anywhere within 4 squares. No piece can enter for 3 full turns. Louie cannot move this turn.",
            floor_number=6,
            trigger=AbilityTrigger.FLOOR_ROLL,
            requires_combined=True,
        ),
        is_female=False,
    ),

    "Sledge": PawnCharacter(
        name="Sledge",
        ability=PawnAbility(
            name="Body Guard",
            description="Sledge becomes completely immovable and invulnerable for 2 full turns. Cannot be captured, moved, or affected by any ability.",
            floor_number=3,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=False,
    ),

    "Stripper Anaconda": PawnCharacter(
        name="Stripper Anaconda",
        ability=PawnAbility(
            name="Gun Show",
            description="Pull any one female piece 1 square closer to Anaconda via the shortest route. Female pieces are Donut plus any pieces designated female before the game. Can target friendly or enemy female pieces.",
            floor_number=3,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=False,
    ),

    "Quasar": PawnCharacter(
        name="Quasar",
        ability=PawnAbility(
            name="Mediation",
            description="When a friendly piece is about to be captured, spend banked die to declare Mediation. Both players roll 1 die. Highest roll wins. Winner's piece survives, loser's is captured. Ties reroll. If you win both pieces return to original positions.",
            floor_number=5,
            trigger=AbilityTrigger.NO_ROLL,
            uses_per_game=2,
        ),
        is_female=False,
    ),

    # ── New Pawns ────────────────────────────────────────────────────

    "Lucia Mar": PawnCharacter(
        name="Lucia Mar",
        ability=PawnAbility(
            name="Sic Em",
            description="Restrains 1 enemy piece within 2 squares for the next full turn. Restrained piece cannot move or use abilities.",
            floor_number=3,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=True,
    ),

    "Chris": PawnCharacter(
        name="Chris",
        ability=PawnAbility(
            name="Lava Surge",
            description="Covers Chris's square and 1 square on each side in his current rank or file — 3 squares total — with lava for 2 full turns. No piece can enter those squares. Chris cannot move during those 2 turns.",
            floor_number=4,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=False,
    ),

    "Juice Box": PawnCharacter(
        name="Juice Box",
        ability=PawnAbility(
            name="Shapeshift",
            description="Can copy and use the ability of any pawn she has personally captured during the game. Can switch between captured forms freely. Cannot use an ability the same turn she captures a pawn. If the captured pawn is resurrected by the opponent she loses that ability.",
            floor_number=0,
            trigger=AbilityTrigger.NO_ROLL,
        ),
        is_female=True,
    ),

    "Florin": PawnCharacter(
        name="Florin",
        ability=PawnAbility(
            name="Suppressing Fire",
            description="Push any one enemy piece 2 squares directly away from Florin. If it cannot move 2 full squares it moves as far as possible.",
            floor_number=4,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=False,
    ),

    "Garret": PawnCharacter(
        name="Garret",
        ability=PawnAbility(
            name="Indestructible",
            description="Cannot be captured by any standard capture. Can only be removed by the enemy Carl moving directly onto his square or by Miriam Dom's Blood Magic. Cannot capture enemy pieces. Can move backwards once he reaches the enemy back rank.",
            floor_number=0,
            trigger=AbilityTrigger.NO_ROLL,
        ),
        is_female=False,
    ),

    "Signet": PawnCharacter(
        name="Signet",
        ability=PawnAbility(
            name="Succubus",
            description="Draw any 1 male character — friendly or enemy — 1 square closer to Signet via the shortest route.",
            floor_number=3,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=False,
    ),

    "Miriam Dom": PawnCharacter(
        name="Miriam Dom",
        ability=PawnAbility(
            name="Blood Magic",
            description="Sacrifice any adjacent friendly pawn to resurrect any previously captured friendly pawn on your back rank. Sacrifice does not trigger on-capture effects. Can sacrifice Garret.",
            floor_number=8,
            trigger=AbilityTrigger.FLOOR_ROLL,
            requires_combined=True,
        ),
        is_female=True,
    ),

    "Orthrus": PawnCharacter(
        name="Orthrus",
        ability=PawnAbility(
            name="Aloof",
            description="Always moves 2 squares instead of 1. Can only be captured by major pieces. Cannot be resurrected once captured — permanently removed when killed.",
            floor_number=0,
            trigger=AbilityTrigger.NO_ROLL,
        ),
        is_female=False,
    ),

    "Raul the Crab": PawnCharacter(
        name="Raul the Crab",
        ability=PawnAbility(
            name="Group Climax",
            description="All friendly piece abilities cost 2 less for the next full turn.",
            floor_number=7,
            trigger=AbilityTrigger.FLOOR_ROLL,
            requires_combined=True,
        ),
        is_female=False,
    ),

    "Bad Llama": PawnCharacter(
        name="Bad Llama",
        ability=PawnAbility(
            name="Lava Spit",
            description="Target any 2x2 zone within 4 squares. Any piece in that zone must move out on their next turn or be captured. Mark with tokens.",
            floor_number=4,
            trigger=AbilityTrigger.FLOOR_ROLL,
        ),
        is_female=False,
    ),
}

# Female piece type names (for Stripper Anaconda's Gun Show)
FEMALE_MAJOR_PIECE_TYPES = {"Donut", "Katia", "Samantha"}
FEMALE_PAWN_NAMES = {"Zev", "Elle McGib", "Imani", "Lucia Mar", "Juice Box", "Miriam Dom"}
