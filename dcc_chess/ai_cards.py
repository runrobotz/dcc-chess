"""AI Card deck and trigger resolution for DCC Chess.

Certain dice rolls -- double 1s, double 3s, or a 6+2 -- summon a card from
a shared 14-card deck that affects the current turn, a piece, or the board.
The deck is shuffled once at game start and cards are drawn one at a time;
once the deck is empty, the trigger still fires but nothing happens.
"""

import random
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from .pieces import Color, PieceType
from .board import BOARD_SIZE, CENTER_SQUARE
from .pawns import PAWN_CHARACTERS

if TYPE_CHECKING:
    from .abilities import GameState
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


# ── Card 4: System Reset ─────────────────────────────────────────────

def _resolve_system_reset(gs: "GameState", color: "Color", dice: Optional["DungeonDice"]) -> None:
    gs.system_reset_active = True
    _set_outcome(gs, "System Reset", color, "No abilities can be activated by either player this turn.")


# ── Card 5: Main Character Syndrome ─────────────────────────────────

def _resolve_main_character_syndrome(gs: "GameState", color: "Color", dice: Optional["DungeonDice"]) -> None:
    gs.main_character_syndrome_active = True
    _set_outcome(gs, "Main Character Syndrome", color, "No pawns can move this turn for either player.")


# ── Card 6: What a Bitch ─────────────────────────────────────────────

def _resolve_what_a_bitch(gs: "GameState", color: "Color", dice: Optional["DungeonDice"]) -> None:
    if gs.insta_kill_card.get(color, False):
        _set_outcome(gs, "What a Bitch", color, f"{color.value.title()} already holds an Insta-Kill Boss Card -- nothing happens.")
        return
    gs.insta_kill_card[color] = True
    _set_outcome(gs, "What a Bitch", color, f"{color.value.title()} receives an Insta-Kill Boss Card.")


# ── Card 7: You a Bitch ──────────────────────────────────────────────

def _resolve_you_a_bitch(gs: "GameState", color: Color, dice: Optional["DungeonDice"]) -> None:
    opponent = color.opponent
    my_count = len(gs.board.all_pieces(color))
    opp_count = len(gs.board.all_pieces(opponent))
    if my_count >= opp_count:
        _set_outcome(gs, "You a Bitch", color,
                     "No effect -- you have equal or more pieces than your opponent.")
        return

    roll_map = {1: None, 2: PieceType.DONUT, 3: PieceType.MONGO,
                4: PieceType.KATIA, 5: PieceType.SAMANTHA, 6: None}

    def candidates_for(roll):
        ptype = roll_map[roll]
        if ptype is None:
            return ptype, []
        return ptype, [p for p in gs.board.captured[color]
                       if p.piece_type == ptype and not p.permanently_dead]

    roll1 = random.randint(1, 6)
    ptype, candidates = candidates_for(roll1)
    rolls = [roll1]
    if not candidates:
        roll2 = random.randint(1, 6)
        rolls.append(roll2)
        ptype, candidates = candidates_for(roll2)

    gs.log_event("you_a_bitch_roll", rolls=rolls, result=(ptype.value if ptype else None))

    if not candidates:
        _set_outcome(gs, "You a Bitch", color, f"Rolled {rolls} -- no eligible piece to resurrect.")
        return

    revived = random.choice(candidates)
    gs.board.captured[color].remove(revived)

    back_rank = 0 if color == Color.WHITE else BOARD_SIZE - 1
    open_cols = [c for c in range(BOARD_SIZE) if gs.board.get(back_rank, c) is None]
    if not open_cols:
        gs.board.captured[color].append(revived)  # put it back
        _set_outcome(gs, "You a Bitch", color,
                     f"Rolled {ptype.value} but there's no open square on your back rank.")
        return

    spawn_col = random.choice(open_cols)
    gs.board.set(back_rank, spawn_col, revived)
    revived.has_moved = True
    gs.log_event("you_a_bitch_resurrect", piece=repr(revived), pos=[back_rank, spawn_col])
    _set_outcome(gs, "You a Bitch", color, f"Resurrected {ptype.value} on the back rank.")


# ── Card 8: Lottery Ticket ───────────────────────────────────────────

def _resolve_lottery_ticket(gs: "GameState", color: Color, dice: Optional["DungeonDice"]) -> None:
    roll = random.randint(1, 6)
    gs.log_event("lottery_ticket_roll", roll=roll)
    if roll <= 3:
        _resolve_custard(gs, color)
    else:
        _resolve_fireball(gs, color)


def _resolve_custard(gs: "GameState", color: Color) -> None:
    options = _find_spent_limited_abilities(gs, color)
    if not options:
        _set_outcome(gs, "Lottery Ticket", color, "Custard: No spent abilities to reset.")
        return
    gs.pending_ai_card_decision = {
        "type": "custard",
        "card": "Lottery Ticket",
        "color": color.value,
        "options": options,
    }
    # Resolution pauses here -- ai_card_active stays populated (outcome still None)
    # until /ai_card/custard_choice picks one of `options` by index.


def _find_spent_limited_abilities(gs: "GameState", color: Color) -> List[Dict]:
    """Every limited-use ability belonging to `color` that is currently fully spent,
    as a list of {label, reset} the player can choose from.

    Only covers trackers an ability's own try_* method actually reads. Several
    similarly-named GameState fields (group_climax_active, cockroach_used,
    rampage_used) are dead/unused -- see KNOWN_BUGS.md -- and are deliberately
    excluded here so "resetting" one always does something real.
    """
    options: List[Dict] = []

    for pawn_key, ability_map in gs.pawn_ability_uses.items():
        if not pawn_key.startswith(f"{color.value}_"):
            continue
        pawn_name = pawn_key.split("_", 1)[1]
        if pawn_name == "Quasar":
            continue  # Quasar's Mediation uses its own counter, handled below
        for ability_name, uses_left in ability_map.items():
            if uses_left <= 0:
                options.append({
                    "label": f"{pawn_name} — {ability_name}",
                    "reset": {"type": "pawn_ability", "pawn_key": pawn_key, "color": color.value,
                              "ability_name": ability_name, "pawn_name": pawn_name},
                })

    if gs.plot_armor_used.get(color, False):
        options.append({"label": "Carl — Plot Armor", "reset": {"type": "plot_armor", "color": color.value}})
    if gs.leader_uses.get(color, 2) <= 0:
        options.append({"label": "Carl — Leader", "reset": {"type": "leader", "color": color.value}})

    if gs.resurrection_used.get(color, False):
        options.append({"label": "Donut — Resurrection", "reset": {"type": "resurrection", "color": color.value}})

    for (c, piece_id), used in gs.rampaging_charge_used.items():
        if c == color and used:
            options.append({"label": "Mongo — Rampaging Charge",
                             "reset": {"type": "rampaging_charge", "color": color.value, "piece_id": piece_id}})

    if gs.she_tank_uses.get(color, 2) <= 0:
        options.append({"label": "Katia — She Tank", "reset": {"type": "she_tank", "color": color.value}})

    for (c, piece_id), used in gs.portal_spike_used.items():
        if c == color and used:
            options.append({"label": "Samantha — Portal Spike",
                             "reset": {"type": "portal_spike", "color": color.value, "piece_id": piece_id}})
    for (c, piece_id), used in gs.slut_shame_used.items():
        if c == color and used:
            options.append({"label": "Samantha — Slut Shame",
                             "reset": {"type": "slut_shame", "color": color.value, "piece_id": piece_id}})

    if gs.quasar_uses.get(color, 0) >= 2:
        options.append({"label": "Quasar — Mediation", "reset": {"type": "quasar_mediation", "color": color.value}})

    for i, opt in enumerate(options):
        opt["index"] = i
    return options


def _apply_custard_reset(gs: "GameState", reset: Dict) -> None:
    t = reset["type"]
    color = Color(reset["color"])
    if t == "pawn_ability":
        char = PAWN_CHARACTERS.get(reset["pawn_name"])
        max_uses = char.ability.uses_per_game if char and char.ability.uses_per_game else 1
        gs.pawn_ability_uses.setdefault(reset["pawn_key"], {})[reset["ability_name"]] = max_uses
    elif t == "plot_armor":
        gs.plot_armor_used[color] = False
    elif t == "leader":
        gs.leader_uses[color] = 2
    elif t == "resurrection":
        gs.resurrection_used[color] = False
    elif t == "rampaging_charge":
        gs.rampaging_charge_used[(color, reset["piece_id"])] = False
    elif t == "she_tank":
        gs.she_tank_uses[color] = 2
    elif t == "portal_spike":
        gs.portal_spike_used[(color, reset["piece_id"])] = False
    elif t == "slut_shame":
        gs.slut_shame_used[(color, reset["piece_id"])] = False
    elif t == "quasar_mediation":
        gs.quasar_uses[color] = 0


def resolve_custard_choice(gs: "GameState", index) -> Tuple[bool, str]:
    """Resolve a pending Custard decision by option index. Returns (ok, message)."""
    pending = gs.pending_ai_card_decision
    if not pending or pending.get("type") != "custard":
        return False, "No pending Custard decision"
    options = pending.get("options", [])
    if not isinstance(index, int) or index < 0 or index >= len(options):
        return False, "Invalid option index"

    chosen = options[index]
    _apply_custard_reset(gs, chosen["reset"])
    color = Color(pending["color"])
    gs.pending_ai_card_decision = None
    gs.log_event("custard_reset", choice=chosen["label"], player=color.value)
    _set_outcome(gs, "Lottery Ticket", color, f"Custard: reset {chosen['label']}.")
    return True, "ok"


def _scale_1_to_9(roll: int) -> int:
    """Map a 1-6 die roll onto the 1-9 range (avoids the board's outer edge columns/rows)."""
    return 1 + round((roll - 1) * 8 / 5)


def _resolve_fireball(gs: "GameState", color: Color) -> None:
    col_roll = random.randint(1, 6)
    row_roll = random.randint(1, 6)
    col = _scale_1_to_9(col_roll)
    row = _scale_1_to_9(row_roll)
    gs.log_event("fireball_target", col_roll=col_roll, row_roll=row_roll, row=row, col=col)

    target = gs.board.get(row, col)
    if target is None:
        _set_outcome(gs, "Lottery Ticket", color,
                     f"Fireball: Lucky -- the targeted square ({row}, {col}) was empty.")
        return

    gs.board.set(row, col, None)
    target.permanently_dead = True
    gs.board.captured[target.color].append(target)
    gs.log_event("fireball_kill", target=repr(target), pos=[row, col])
    _set_outcome(gs, "Lottery Ticket", color,
                 f"Fireball struck ({row}, {col}) -- {target!r} was permanently killed.")


# ── Card 9: Too Boring ───────────────────────────────────────────────

def _resolve_too_boring(gs: "GameState", color: Color, dice: Optional["DungeonDice"]) -> None:
    skipped: List[str] = []
    pending = _too_boring_build_step(gs, color, 1, skipped)
    if pending is None:
        pending = _too_boring_build_step(gs, color, 2, skipped)
    if pending is None:
        _finish_too_boring(gs, color, skipped)
        return
    pending["_skipped_so_far"] = skipped
    gs.pending_ai_card_decision = pending


def _too_boring_build_step(gs: "GameState", triggering_color: Color, step_num: int,
                            skipped: List[str]) -> Optional[Dict]:
    opponent = triggering_color.opponent
    if step_num == 1:
        chooser, eliminate_color = opponent, triggering_color
    else:
        chooser, eliminate_color = triggering_color, opponent

    targets = [[r, c] for r, c, p in gs.board.all_pieces(eliminate_color) if p.is_pawn]
    if not targets:
        skipped.append(eliminate_color.value)
        gs.log_event("too_boring_skip", color=eliminate_color.value, detail="No pawns to eliminate")
        return None

    return {
        "type": "too_boring",
        "card": "Too Boring",
        "step": step_num,
        "triggering_color": triggering_color.value,
        "chooser_color": chooser.value,
        "eliminate_color": eliminate_color.value,
        "valid_targets": targets,
    }


def _finish_too_boring(gs: "GameState", triggering_color: Color, skipped: List[str]) -> None:
    if skipped:
        msg = f"Both eliminations resolved ({', '.join(skipped)} had no pawns to eliminate)."
    else:
        msg = "Both players lost a pawn."
    _set_outcome(gs, "Too Boring", triggering_color, msg)


def resolve_too_boring_choice(gs: "GameState", row, col) -> Tuple[bool, str]:
    """Resolve one step of a pending Too Boring decision. Returns (ok, message)."""
    pending = gs.pending_ai_card_decision
    if not pending or pending.get("type") != "too_boring":
        return False, "No pending Too Boring decision"
    if not isinstance(row, int) or not isinstance(col, int) or [row, col] not in pending.get("valid_targets", []):
        return False, "Invalid target -- must select one of the highlighted pawns"

    eliminate_color = Color(pending["eliminate_color"])
    triggering_color = Color(pending["triggering_color"])
    step = pending["step"]
    skipped = pending.get("_skipped_so_far", [])

    piece = gs.board.get(row, col)
    if piece is None or not piece.is_pawn or piece.color != eliminate_color:
        return False, "Target is no longer valid"

    gs.board.set(row, col, None)
    piece.permanently_dead = True
    gs.board.captured[eliminate_color].append(piece)
    gs.log_event("too_boring_eliminate", piece=repr(piece), pos=[row, col], color=eliminate_color.value)

    gs.pending_ai_card_decision = None

    if step == 1:
        pending2 = _too_boring_build_step(gs, triggering_color, 2, skipped)
        if pending2 is not None:
            pending2["_skipped_so_far"] = skipped
            gs.pending_ai_card_decision = pending2
            return True, "ok"
    _finish_too_boring(gs, triggering_color, skipped)
    return True, "ok"


# ── Card 10: Matt's Drunk Again ──────────────────────────────────────

def _resolve_matts_drunk_again(gs: "GameState", color: Color, dice: Optional["DungeonDice"]) -> None:
    roll = random.randint(1, 6)

    if gs.swap_active:
        gs.swap_turns_remaining += roll
        gs.log_event("matts_drunk_again", roll=roll, extended=True,
                     swap_turns_remaining=gs.swap_turns_remaining)
        _set_outcome(gs, "Matt's Drunk Again", color,
                     f"A swap is already active -- extended by {roll} turns "
                     f"({gs.swap_turns_remaining} remaining).")
        return

    gs.swap_active = True
    gs.swap_turns_remaining = roll
    gs.original_colors = {
        f"{r},{c}": p.color.value
        for r, c, p in gs.board.all_pieces(Color.WHITE) + gs.board.all_pieces(Color.BLACK)
    }
    gs.log_event("matts_drunk_again", roll=roll, extended=False, swap_turns_remaining=roll)
    _set_outcome(gs, "Matt's Drunk Again", color,
                 f"Control swapped! Each player controls the other's pieces for {roll} turns.")


# ── Cards 11-14: Summon cards ────────────────────────────────────────

_BOSS_MAX_HP = {
    "Rage Elemental": 6,
    "Feral Goose": 0,
    "Emberus": 8,
    "Goblin Murder Dozer": 5,
}


def _boss_spawn_squares(boss_name: str) -> List[Tuple[int, int]]:
    cr, cc = CENTER_SQUARE
    if boss_name == "Emberus":
        return [(cr, cc), (cr - 1, cc), (cr + 1, cc), (cr, cc - 1), (cr, cc + 1)]
    return [(cr, cc)]


def _spawn_boss(gs: "GameState", boss_name: str) -> None:
    squares = _boss_spawn_squares(boss_name)

    # Any piece standing on a spawn square is permanently killed.
    for (r, c) in squares:
        occupant = gs.board.get(r, c)
        if occupant is not None:
            gs.board.set(r, c, None)
            occupant.permanently_dead = True
            gs.board.captured[occupant.color].append(occupant)
            gs.log_event("boss_spawn_kill", piece=repr(occupant), pos=[r, c])

    gs.boss_active = True
    gs.active_boss = boss_name
    gs.boss_hp = _BOSS_MAX_HP.get(boss_name, 0)
    gs.boss_max_hp = gs.boss_hp
    gs.boss_position = CENTER_SQUARE
    gs.boss_squares = squares
    gs.log_event("boss_summoned", boss=boss_name, hp=gs.boss_hp,
                 position=list(CENTER_SQUARE), squares=[list(s) for s in squares])


def _resolve_summon_card(gs: "GameState", color: Color, dice: Optional["DungeonDice"], card_name: str) -> None:
    boss_name = SUMMON_CARD_BOSS_TYPES[card_name]

    if gs.boss_active:
        gs.pending_boss_summon = boss_name
        gs.log_event("boss_summon_queued", boss=boss_name, detail="A boss is already active")
        _set_outcome(gs, card_name, color,
                     f"A boss is already active -- {boss_name} will be summoned next.")
        return

    _spawn_boss(gs, boss_name)
    _set_outcome(gs, card_name, color, f"{boss_name} has been summoned!")


_CARD_HANDLERS = {
    "AI's Pet": _resolve_ai_s_pet,
    "Dirty Tootsies": _resolve_dirty_tootsies,
    "Mana Toast": _resolve_mana_toast,
    "System Reset": _resolve_system_reset,
    "Main Character Syndrome": _resolve_main_character_syndrome,
    "What a Bitch": _resolve_what_a_bitch,
    "You a Bitch": _resolve_you_a_bitch,
    "Lottery Ticket": _resolve_lottery_ticket,
    "Too Boring": _resolve_too_boring,
    "Matt's Drunk Again": _resolve_matts_drunk_again,
    "Summon Rage Elemental": lambda gs, color, dice: _resolve_summon_card(gs, color, dice, "Summon Rage Elemental"),
    "Summon Feral Goose": lambda gs, color, dice: _resolve_summon_card(gs, color, dice, "Summon Feral Goose"),
    "Summon Emberus": lambda gs, color, dice: _resolve_summon_card(gs, color, dice, "Summon Emberus"),
    "Summon Goblin Murder Dozer": lambda gs, color, dice: _resolve_summon_card(gs, color, dice, "Summon Goblin Murder Dozer"),
}
