# Known Bugs

Pre-existing issues found incidentally while working on other features.
Tracked here so they don't get lost or re-"discovered" later.

_No open bugs._

---

## Fixed

### Signet's Succubus never took effect

`try_succubus()` added targets to `succubus_pending`, but nothing ever promoted that set or
checked it in `is_piece_movable()` -- the ability spent the die and did nothing, for both
Signet and Juice Box.

Fixed: 2026-10-01 (v0.67). Added `succubus_pieces`, promoted from `succubus_pending` in
`start_turn()` (same pattern as frozen/restrained/she_tank) and checked in
`is_piece_movable()`. Shown as a status entry and a 💋 board badge.

### Blood Magic always failed to resurrect

`try_blood_magic()` and app.py's targeted Miriam handler resurrected from
`GameState.captured_pieces`, which only Rampage ever writes to -- normal captures land in
`board.captured`. The pool was always empty, so the spell spent both dice and failed.
Once the pool was non-empty, the targeted handler also crashed: it imported `BOARD_SIZE` from
`dcc_chess.pieces` (it doesn't exist there), and a second inline `Color` import in the same
function made `Color` an unbound local.

Fixed: 2026-10-01 (v0.67). New `GameState.blood_magic_candidates()` reads `board.captured`
(pawns only, never Orthrus or permanently-dead pieces); both paths use it, and the inline
imports were removed.

### Juice Box combined-dice cards and AI costs

Her sidebar card ignored `requires_combined`, so a discounted combined ability could show green
with one die and burn the turn on click. The AI priced her copies at the base cost (no +1)
and never passed a Lava Surge direction.

Fixed: 2026-10-01 (v0.67).


### Raul the Crab's Group Climax doesn't actually reduce ability costs

`try_group_climax()` in `dcc_chess/abilities.py` set `group_climax_pending[color] = True`
when the ability fired, and `GameState.__init__` also defined a `group_climax_active` dict --
but nothing ever promoted `group_climax_pending` to `group_climax_active` (no `start_turn()`
handling, unlike the analogous pending/active pairs for suppressed/frozen/restrained/she_tank),
and nothing ever read `group_climax_active` when checking an ability's floor cost. The ability
logged success and consumed the dice, but the "-2 to ability costs next turn" effect never
actually applied.

Found: 2026-08-07, while building the AI Card system's "AI's Pet" / "Dirty Tootsies" cards,
which needed a *working* cost-modifier mechanism and ended up implementing their own
(`DungeonDice.floor_modifier`) rather than reusing this broken one.

Fixed: 2026-08-26 (Chunk 4). Added `GameState.promote_group_climax(dice)`, called at every
turn-start dice-roll site (`/start_turn`, dev auto-start, `_play_ai_turn`); it applies
`dice.floor_modifier -= 2` for the player whose turn is starting when their Group Climax is
pending, clears the pending flag, and sets `group_climax_active` (which now drives the
sidebar "Group Climax (buff)" status entry). `end_turn()` clears `group_climax_active`.
The frontend applies the modifier to displayed/checked ability costs via `effectiveFloor()`.
