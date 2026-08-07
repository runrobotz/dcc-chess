# Known Bugs

Pre-existing issues found incidentally while working on other features.
Not fixed yet — tracked here so they don't get lost or re-"discovered" later.

## Raul the Crab's Group Climax doesn't actually reduce ability costs

`try_group_climax()` in `dcc_chess/abilities.py` sets `group_climax_pending[color] = True`
when the ability fires, and `GameState.__init__` also defines a `group_climax_active` dict --
but nothing ever promotes `group_climax_pending` to `group_climax_active` (no `start_turn()`
handling, unlike the analogous pending/active pairs for suppressed/frozen/restrained/she_tank),
and nothing ever reads `group_climax_active` when checking an ability's floor cost. The ability
logs success and consumes the dice, but the "-2 to ability costs next turn" effect never
actually applies.

Found: 2026-08-07, while building the AI Card system's "AI's Pet" / "Dirty Tootsies" cards,
which needed a *working* cost-modifier mechanism and ended up implementing their own
(`DungeonDice.floor_modifier`) rather than reusing this broken one.
