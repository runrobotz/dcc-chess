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
    from .dice import DungeonDice


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


def maybe_trigger_ai_card(gs: "GameState", d1: int, d2: int, triggering_color: "Color",
                           dice: Optional["DungeonDice"] = None) -> Optional[str]:
    """Check a pair of d6 values for the AI summon pattern and draw a card if so.

    `triggering_color` is whichever player's action produced this roll (their
    own dice roll, or their side of a Mediation roll-off). `dice` is the live
    DungeonDice for this turn, when the roll came from one (some card effects
    -- AI's Pet, Dirty Tootsies, Mana Toast -- need to modify it; a Mediation
    roll-off has no `dice` of its own, so those effects simply have nothing to
    apply to in that case). Returns the drawn card's name, or None if the roll
    didn't trigger (or the deck was empty).
    """
    from .dice import is_ai_summon_roll

    if not is_ai_summon_roll(d1, d2):
        return None
    return draw_ai_card(gs, triggering_color, dice=dice)


def draw_ai_card(gs: "GameState", triggering_color: "Color",
                  dice: Optional["DungeonDice"] = None) -> Optional[str]:
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

    resolve_ai_card_effect(gs, card_name, triggering_color, dice=dice)

    return card_name


def _set_outcome(gs: "GameState", card_name: str, color: "Color", outcome: str) -> None:
    """Record the outcome for the current ai_card_active entry, log it, and clear the flag."""
    if gs.ai_card_active is not None:
        gs.ai_card_active["outcome"] = outcome
    gs.log_event("ai_card_resolved", card=card_name, player=color.value, outcome=outcome)
    gs.ai_card_active = None


def resolve_ai_card_effect(gs: "GameState", card_name: str, color: "Color",
                            dice: Optional["DungeonDice"] = None) -> None:
    """Apply the drawn card's effect and clear `ai_card_active` when done.

    Each card is implemented as its own `_resolve_<card>` function below.
    Cards not yet ported over from Stage A's stub fall through to a no-op
    with a placeholder outcome so drawing them doesn't crash the game.
    """
    handler = _CARD_HANDLERS.get(card_name)
    if handler is None:
        _set_outcome(gs, card_name, color, "Not yet implemented.")
        return
    handler(gs, color, dice)


# ── Card 1: AI's Pet ────────────────────────────────────────────────

def _resolve_ai_s_pet(gs: "GameState", color: "Color", dice: Optional["DungeonDice"]) -> None:
    if dice is None:
        _set_outcome(gs, "AI's Pet", color, "No active dice this turn -- nothing to reduce.")
        return
    dice.floor_modifier -= 1
    _set_outcome(gs, "AI's Pet", color, "All ability costs reduced by 1 this turn.")


# ── Card 2: Dirty Tootsies ──────────────────────────────────────────

def _resolve_dirty_tootsies(gs: "GameState", color: "Color", dice: Optional["DungeonDice"]) -> None:
    if dice is None:
        _set_outcome(gs, "Dirty Tootsies", color, "No active dice this turn -- nothing to increase.")
        return
    dice.floor_modifier += 1
    _set_outcome(gs, "Dirty Tootsies", color, "All ability costs increased by 1 this turn.")


# ── Card 3: Mana Toast ──────────────────────────────────────────────

def _resolve_mana_toast(gs: "GameState", color: "Color", dice: Optional["DungeonDice"]) -> None:
    if dice is None or not dice.dice:
        _set_outcome(gs, "Mana Toast", color, "No active dice this turn to reroll.")
        return
    old_values = dice.dice[:]
    dice.dice = [random.randint(1, 6) for _ in dice.dice]
    dice.used = [False] * len(dice.dice)
    gs.log_event("mana_toast_reroll", old_values=old_values, new_values=dice.dice[:])
    _set_outcome(gs, "Mana Toast", color, f"Rerolled {old_values} -> {dice.dice}.")


_CARD_HANDLERS = {
    "AI's Pet": _resolve_ai_s_pet,
    "Dirty Tootsies": _resolve_dirty_tootsies,
    "Mana Toast": _resolve_mana_toast,
}
