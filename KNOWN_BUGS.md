# Known Bugs

Pre-existing issues found incidentally while working on other features.
Tracked here so they don't get lost or re-"discovered" later.

### Rampage bypasses every capture protection

`try_rampage()` removes each enemy piece on Mongo's knight squares directly (`board.set(...,
None)`) instead of going through `attempt_capture()`, and neither it nor app.py's
`/ability/get_targets` Rampage branch checks `is_piece_invulnerable()`. So Rampage:

- captures **Ren**, ignoring Indestructible (per DESIGN.md he can only be removed by the
  enemy Carl or Blood Magic);
- captures **Sledge** (or Juice Box) while **Body Guard** is active (`iron_wall_pieces`);
- never gives **Quasar's Mediation** its chance to defend the threatened piece.

The enemy Carl is already excluded. Found: 2026-10-01, while fixing Rampage victims not
reaching the graveyard (they now land in `board.captured` and run `process_post_capture`).

### Gun Show and Succubus don't match their designed abilities

The designed behavior (the ability text in `dcc_chess/pawns.py` and the game overview PDF) is
correct; the code needs to change to match it. DESIGN.md currently records the code as
authoritative for these two and should be updated when they're fixed.

- **Gun Show** (Stripper Anaconda) should pull any one female piece, friendly or enemy, 1
  square closer to Anaconda by the shortest route. Donut always counts as female. The live
  `try_gun_show()` instead gives all friendly male pieces +2 to dice rolls for 2 turns
  (`gun_show_active[color] = 2`).
- **Succubus** (Signet) should pull any one male piece, friendly or enemy, 1 square closer to
  Signet by the shortest route. Carl can never be targeted. The live `try_succubus()` instead
  stops every enemy male piece within 3 squares (except Carl) from moving on its next turn
  (`succubus_pending` -> `succubus_pieces`).

Both are also reachable through Juice Box's Shapeshift, so her copies need the same fix.
Found: 2026-10-09, while rebuilding the game overview PDF.

### What a Bitch's Insta-Kill Boss Card can't be used

The What a Bitch AI card sets `GameState.insta_kill_card[color] = True` and the sidebar shows an
Insta-Kill badge, but nothing in `app.py`, `abilities.py`, or `game.js` ever reads or spends
it: there's no route, button, or AI logic for playing the card during a boss battle.
Found: 2026-10-09, while rebuilding the game overview PDF.

---

## Fixed

### Cockroach and Rampage sidebar use counters never decremented

`get_piece_abilities()` in `app.py` read `game_state.cockroach_used` (Donut's Cockroach) and
`game_state.rampage_used` (Mongo's Rampage) to compute `uses_left`, but nothing ever writes
either field. The real once-per-game flags are `resurrection_used` (set by
`try_cockroach()`) and `rampaging_charge_used` (set by `try_rampage()`) -- the ones `ai.py`
and `ai_cards.py` (whose ability-reset card restores them) already use. Both cards always
showed 1 use left; clicking one after it was spent failed and burned the turn's dice.

Fixed: 2026-10-01 (v0.69). The sidebar now reads `resurrection_used` /
`rampaging_charge_used`. Display-only change; the unused `cockroach_used` / `rampage_used`
fields are still declared in `GameState.__init__`.

### Blood Magic could double-spawn a Mordecai awaiting respawn

A captured Mordecai lands in `board.captured` *and* is queued in `mordecai_respawn_pending`;
his Manager Benefit respawn also never removes him from `board.captured`. Blood Magic
(`blood_magic_candidates()`, used by both `try_blood_magic()` and app.py's targeted Miriam
handler) didn't exclude him, so it could resurrect him while his respawn was still pending
(he then appeared twice when it fired), or after he had already respawned (the same Piece on
two squares at once).

Fixed: 2026-10-01 (v0.69). `blood_magic_candidates()` now applies the same filter as
`cockroach_candidates()`: any piece already on the board or pending a Mordecai respawn is
skipped.

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
