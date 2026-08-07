"""AI Card deck and trigger resolution for DCC Chess.

Certain dice rolls -- double 1s, double 3s, or a 6+2 -- summon a card from
a shared 14-card deck that affects the current turn, a piece, or the board.
The deck is shuffled once at game start and cards are drawn one at a time;
once the deck is empty, the trigger still fires but nothing happens.
"""

import random
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .abilities import GameState
    from .pieces import Color


AI_CARD_NAMES: List[str] = [
    "Lottery Ticket",
    "You a Bitch",
    "AI's Pet",
    "Dirty Tootsies",
    "System Reset",
    "Too Boring",
    "Main Character Syndrome",
    "Matt's Drunk Again",
    "Mana Toast",
    "What a Bitch",
    "Summon Rage Elemental",
    "Summon Feral Goose",
    "Summon Emberus",
    "Summon Goblin Murder Dozer",
]

AI_CARD_DESCRIPTIONS: Dict[str, str] = {
    "Lottery Ticket": "Roll a die. 1-3: Custard -- reset one limited-use ability. "
                       "4-6: Fireball -- a random square is struck and its piece is permanently killed.",
    "You a Bitch": "If you're down in piece count, roll a die for a chance to resurrect a major piece.",
    "AI's Pet": "All your ability costs are reduced by 1 this turn.",
    "Dirty Tootsies": "All your ability costs are increased by 1 this turn.",
    "System Reset": "No abilities can be activated by either player this turn.",
    "Too Boring": "Each player permanently loses one pawn, chosen by their opponent.",
    "Main Character Syndrome": "No pawns can move this turn for either player.",
    "Matt's Drunk Again": "Both players swap control of each other's pieces for a random number of turns.",
    "Mana Toast": "You must immediately reroll both of your dice.",
    "What a Bitch": "You receive an Insta-Kill Boss Card, usable during any boss battle.",
    "Summon Rage Elemental": "A Rage Elemental boss is summoned.",
    "Summon Feral Goose": "A Feral Goose boss is summoned.",
    "Summon Emberus": "An Emberus boss is summoned.",
    "Summon Goblin Murder Dozer": "A Goblin Murder Dozer boss is summoned.",
}

# Maps each "Summon <Boss>" card to the boss type name it spawns. Used by
# Part 3's boss event system -- Stage B only sets the flag/pending state.
SUMMON_CARD_BOSS_TYPES: Dict[str, str] = {
    "Summon Rage Elemental": "Rage Elemental",
    "Summon Feral Goose": "Feral Goose",
    "Summon Emberus": "Emberus",
    "Summon Goblin Murder Dozer": "Goblin Murder Dozer",
}


def build_ai_deck() -> List[str]:
    """Return a freshly shuffled AI Card deck (one copy of each card)."""
    deck = AI_CARD_NAMES[:]
    random.shuffle(deck)
    return deck


def maybe_trigger_ai_card(gs: "GameState", d1: int, d2: int, triggering_color: "Color") -> Optional[str]:
    """Check a pair of d6 values for the AI summon pattern and draw a card if so.

    `triggering_color` is whichever player's action produced this roll (their
    own dice roll, or their side of a Mediation roll-off). Returns the drawn
    card's name, or None if the roll didn't trigger (or the deck was empty).
    """
    from .dice import is_ai_summon_roll

    if not is_ai_summon_roll(d1, d2):
        return None
    return draw_ai_card(gs, triggering_color)


def draw_ai_card(gs: "GameState", triggering_color: "Color") -> Optional[str]:
    """Draw the top card from the AI deck and resolve its effect.

    Returns the drawn card's name, or None if the deck is empty -- the
    trigger still fires (and is logged) but nothing happens.
    """
    gs.log_event("ai_summon_trigger", player=triggering_color.value)

    if not gs.ai_card_deck:
        gs.log_event("ai_card_deck_empty", player=triggering_color.value)
        return None

    card_name = gs.ai_card_deck.pop(0)
    gs.ai_cards_drawn.append(card_name)
    gs.ai_card_active = {
        "name": card_name,
        "description": AI_CARD_DESCRIPTIONS.get(card_name, ""),
        "drawn_by": triggering_color.value,
        "outcome": None,
    }
    gs.log_event("ai_card_drawn", card=card_name, player=triggering_color.value)

    resolve_ai_card_effect(gs, card_name, triggering_color)

    return card_name


def resolve_ai_card_effect(gs: "GameState", card_name: str, color: "Color") -> None:
    """Apply the drawn card's effect and clear `ai_card_active` when done.

    Stage A: logs the resolution only -- individual card effects are wired
    in as Stage B lands, replacing this stub one card at a time.
    """
    gs.log_event("ai_card_resolved", card=card_name, player=color.value)
    gs.ai_card_active = None
