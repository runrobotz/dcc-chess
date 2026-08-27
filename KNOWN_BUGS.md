# Known Bugs

Pre-existing issues found incidentally while working on other features.
Tracked here so they don't get lost or re-"discovered" later.

_No open bugs._

---

## Fixed

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
