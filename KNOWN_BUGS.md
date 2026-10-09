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

### What a Bitch's Insta-Kill Boss Card can't be used

The What a Bitch AI card sets `GameState.insta_kill_card[color] = True` and the sidebar shows an
Insta-Kill badge, but nothing in `app.py`, `abilities.py`, or `game.js` ever reads or spends
it: there's no route, button, or AI logic for playing the card during a boss battle.
Found: 2026-10-09, while rebuilding the game overview PDF.

### Mongo's Pet Carrier can never release him once stored

Storing Mongo takes him off the board (`board.set(mongo_pos, None)`), but `try_pet_carrier()`
starts with `piece = self.board.get(*mongo_pos)` and returns False when that square is empty --
so the release branch below it is unreachable. The sidebar card and `/ability/get_targets` both
work from Mongo's board square too, and a stored Mongo has none. Once stored, he never comes
back (and the AI's Pet Carrier "release" pick never fires).
Found: 2026-10-09, while making Pet Carrier check for self-check (v0.80).

### The offline simulator starts every game on an empty board

`Board.setup_initial_position()` in `dcc_chess/board.py` picks rosters and back-rank columns but
then places nothing -- both placement steps are `pass` placeholders left from when placement
moved to the browser's placement phase. `Game` (`dcc_chess/game.py`) builds its board with it, so
every simulated game starts with no pieces and ends as "checkmate" at turn 0 (a missing Carl
counts as in check). `run_simulation.py`'s reports are therefore meaningless, and it's behind
several of the long-standing test failures (`test_initial_position`, `test_flexible_back_rank`,
`test_board_display`, `test_game_events_logged`, `test_game_with_abilities_firing`,
`test_game_record_parsing`, `test_stats_aggregator`). The live game is unaffected: app.py places
pieces itself (placement phase, or Dev Game layouts). AI-vs-AI testing currently goes through the
server routes instead.
Found: 2026-10-09, while testing the v0.80 random AI.

---

## Fixed

### The AI used abilities after it moved, and an ability could leave its own Carl in check

`_play_ai_turn()` in app.py (and `Game.play_turn()` in `dcc_chess/game.py`) moved first, then
rolled and spent dice -- the reverse of a human's roll -> ability -> move. An ability used after
the move could open a line to the AI's own Carl, and the turn then ended with Carl in check: in
an AI-vs-AI game, Black's Prepotente used Special Boy after Black moved, exposing Black's Carl,
and White's Donut captured him outright on the next move. Nothing stopped a human from doing the
same: several abilities moved or removed pieces without checking that the caster's own Carl
stayed safe (Special Boy, Leader, Puddle Jump, Pet Carrier, Rampage, Slut Shame, Suppressing
Fire, Blood Magic). Special Boy could also land on the enemy Carl's square and capture him
directly, and a piece it captured never reached the graveyard.
Found: 2026-10-09, in AI-vs-AI testing for v0.79.

Fixed: 2026-10-09 (v0.80). The AI now rolls, uses at most one ability, then moves -- in
`_play_ai_turn()` and `Game.play_turn()` -- and skips abilities under System Reset. Every ability
that moves or removes pieces checks `GameState.leaves_carl_in_check()` before spending anything,
and those abilities' targeting lists (`special_boy_destinations`, `leader_pull_destinations`,
`puddle_jump_destinations`, `rampage_plan`, `slut_shame_targets`, `suppressing_fire_pushes`,
`blood_magic_sacrifices`) leave out anything unsafe. Special Boy never targets Carl, Ren, Body
Guard, or Orthrus, and its captures go through `apply_ability_move()` into the graveyard. As a
backstop, capturing Carl is never a legal move (`get_legal_moves_with_status`). Tests:
`tests/test_ai_turn_safety.py`.

### The random AI used retired legacy abilities

`random_abilities()` in `dcc_chess/ai.py` fired abilities no piece has anymore (Bulldozer,
Diva's Entrance, Resurrection, Rampaging Charge, Mongo Smash, Combat Roll, Dual Threat, The
Mouth, Portal Spike, Glitch) and could fire two abilities in one turn. Mongo Smash captured Carl
directly: in an AI-vs-AI game, White's Mongo Smash captured Black's Carl. The `/ability` route
also still dispatched these names (DESIGN.md Section 2), so a hand-crafted request could use them.
Found: 2026-10-09, in AI-vs-AI testing for v0.79.

Fixed: 2026-10-09 (v0.80). The random AI picks from the same table of current abilities the smart
AI dispatches (`MAJOR_ABILITY_KEYS` / `PAWN_ABILITY_KEYS`), one per turn, and the retired names
were removed from the `/ability` route ("Unknown ability"). After v0.80 the retired `try_*`
methods, the state only they used, and their old tests were deleted as well. Tests:
`tests/test_ai_turn_safety.py`.

### A Slut Shame respawn could appear twice and put a Carl in check

`end_turn()` respawned a swallowed pawn with a nested loop whose `break` only left the inner loop,
so the same pawn was placed once in each of up to three rows. The respawn (and Mordecai's
Manager Benefit respawn) also ignored zones and could land a piece attacking the Carl of the
player whose turn was just ending -- the other side then moved next and took that Carl. In an
AI-vs-AI game, Black's Samantha had swallowed White's Louie; he reappeared on two squares at the
end of Black's turn, one of them attacking Black's Carl, and White captured Carl outright. If no
square was free, the pawn (or Mordecai) was silently lost.
Found: 2026-10-09, in AI-vs-AI testing for v0.80 (random AI, seed 5005).

Fixed: 2026-10-09 (v0.80). Both respawns place the piece exactly once, on an open, unzoned
square that doesn't put the player whose turn is ending in check (`_safe_respawn_square`); with
none free, the piece waits and tries again at the end of the next turn. Lottery Ticket's
Fireball also fizzles if it strikes Carl's square. Tests: `tests/test_ai_turn_safety.py`.

### Gun Show and Succubus didn't match their designed abilities

`try_gun_show()` gave all friendly male pieces +2 to dice rolls for 2 turns
(`gun_show_active[color] = 2`, which nothing ever read), and `try_succubus()` stopped every
enemy male piece within 3 squares from moving on its next turn (`succubus_pending` ->
`succubus_pieces`). Neither pulled anything, and Juice Box's copies ran the same code.

Fixed: 2026-10-09 (v0.79). Both now pull one piece of the matching gender, friendly or
enemy, 1 King step toward the caster through a shared `GameState._try_pull` /
`pull_targets` (Carl, Orthrus, immovable, and adjacent pieces excluded; the pull square
must be empty and unzoned; no self-check). With no valid target the card is grey and
`/ability` rejects the request before touching the dice. Players pick the target on the
board, the AI pulls only when it gains material safety (`_best_pull`), and the battle log
reads "Signet used Succubus — pulled White Mongo to E5". The old buff/pin state, the
💋 board badge, the leftover Enthrall code, and the unused `piece_genders` overrides were
removed. Tests: `tests/test_pull_abilities.py`.

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
