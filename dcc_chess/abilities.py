"""Ability implementations and status effect tracking for DCC Chess.

Handles all major piece abilities and pawn abilities, plus the status
effects they create (ghost tokens, lava and Air Strike zones, frozen, suppressed, etc.).
"""

import random
from typing import List, Tuple, Optional, Dict, Set

from .pieces import Piece, PieceType, Color
from .board import Board, BOARD_SIZE
from .dice import DungeonDice
from .pawns import (
    PAWN_CHARACTERS, PawnCharacter, AbilityTrigger,
    FEMALE_MAJOR_PIECE_TYPES, FEMALE_PAWN_NAMES,
)
from .movement import (
    pseudo_legal_moves_for_piece, legal_moves_for_piece,
    is_in_check, is_square_attacked, all_legal_moves,
    resolve_orthrus_action,
)
from . import ai_cards


# ── Status Effect Types ───────────────────────────────────────────

class StatusEffect:
    """Base for all status effects with turn-based duration."""

    def __init__(self, effect_type: str, duration: int, **kwargs):
        self.effect_type = effect_type
        self.turns_remaining = duration
        self.data = kwargs

    def tick(self):
        """Decrement duration. Returns True if expired."""
        self.turns_remaining -= 1
        return self.turns_remaining <= 0

    def __repr__(self):
        return f"{self.effect_type}(turns={self.turns_remaining}, {self.data})"


class GameState:
    """Tracks all game state beyond the board: abilities, status effects, flags."""

    def __init__(self, board: Board):
        self.board = board

        # Status effects on squares
        self.ghost_tokens: Dict[Tuple[int, int], int] = {}  # pos -> turns remaining

        # Status effects on pieces (keyed by (row, col) of piece)
        self.suppressed_pieces: Set[Tuple[int, int]] = set()  # active this turn
        self.suppressed_pending: Set[Tuple[int, int]] = set()  # applied this turn, active next
        self.stuck_pieces: Dict[Tuple[int, int], int] = {}  # pos -> turns (can't move)
        self.iron_wall_pieces: Dict[Tuple[int, int], int] = {}  # pos -> turns (immovable+invulnerable)

        # ── Major Piece Abilities (New) ──────────────────────────
        # Carl
        self.plot_armor_used: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}  # once per game
        self.leader_uses: Dict[Color, int] = {Color.WHITE: 2, Color.BLACK: 2}  # twice per game

        # Donut
        self.cockroach_used: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}
        # Puddle Jump: shared 10-turn cooldown after use, ticked down in end_turn().
        self.puddle_jump_cooldown: int = 0
        
        # Mongo -- Pet Carrier: the Mongo each side has stored off the board
        # ({"piece": Piece, "turn": turn_number he went in}, or None). He can be
        # released on any later turn of that side's (see mongo_release_squares).
        self.stored_mongo: Dict[Color, Optional[Dict]] = {Color.WHITE: None, Color.BLACK: None}
        # Squares of Mongos released this turn -- they can't move or capture
        # (or Rampage) until their side's next turn.
        self.mongo_released_this_turn: Set[Tuple[int, int]] = set()
        self.rampage_used: Dict[Tuple[Color, int], bool] = {}  # (color, piece_id) -> used
        
        # Katia
        self.she_tank_uses: Dict[Color, int] = {Color.WHITE: 2, Color.BLACK: 2}
        self.she_tank_targets: Set[Tuple[int, int]] = set()  # pieces that can't move this turn
        self.she_tank_pending: Set[Tuple[int, int]] = set()  # applied this turn, active next
        self.blitzed_pieces: Set[Tuple[int, int]] = set()  # pieces that can skip movement this turn
        
        # Samantha
        self.slut_shame_used: Dict[Tuple[Color, int], bool] = {}
        self.swallowed_pawns: List[Dict] = []  # [{piece: Piece, turns_left: int, sam_pos: (r,c)}]
        
        # Once-per-game flags for Cockroach (resurrection_used) and Rampage
        # (rampaging_charge_used), named after the abilities they replaced.
        self.resurrection_used: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}
        self.rampaging_charge_used: Dict[Tuple[Color, int], bool] = {}

        # ── Pawn Ability Tracking (Chunk 2) ──────────────────────
        self.pawn_ability_uses: Dict[str, Dict[str, int]] = {}  # "color_pawnname" -> {ability: uses_left}
        
        # Zev — Biggest Fan: +1 to all dice next turn
        self.zev_buff_active: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}
        
        # Mordecai — Manager Benefit: ghost zones and respawn.
        # `turns_left` counts down 3 -> 0 over the 3 full turns that follow the
        # capture. The end_turn() that fires on the capturing player's own turn
        # must NOT count (no full turn has elapsed yet), so both the respawn
        # entry and its ghost square get one `skip_first_tick` grace tick.
        self.mordecai_respawn_pending: List[Dict] = []  # [{piece, turns_left, color, skip_first_tick}]
        self.mordecai_ghost_fresh: Set[Tuple[int, int]] = set()  # ghost squares awaiting their grace tick
        
        # Elle McGib — Frozen: frozen pieces
        self.frozen_pieces: Set[Tuple[int, int]] = set()  # active this turn
        self.frozen_pending: Set[Tuple[int, int]] = set()  # applied this turn, active next
        
        # Imani — Suppress: suppressed pieces (already tracked above in suppressed_pieces)
        
        # Candy Biggs — Gang Gang!: recruited pawns
        self.recruited_pawns: Dict[Tuple[int, int], Color] = {}  # pos -> original_color
        
        # Louie — Air Strike: can't move flag
        self.louie_cant_move: Set[Tuple[int, int]] = set()
        # Air Strike persistent zones with turn-duration tracking
        self.air_strike_zones: Dict[Tuple[int, int], int] = {}
        
        # Sledge — Body Guard: immovable/invulnerable (uses iron_wall_pieces)
        
        # Quasar — Mediation
        self.quasar_uses: Dict[Color, int] = {Color.WHITE: 0, Color.BLACK: 0}
        
        # Lucia Mar — Sic Em: restrained pieces (can't move or use abilities)
        self.restrained_pieces: Set[Tuple[int, int]] = set()  # active this turn
        self.restrained_pending: Set[Tuple[int, int]] = set()  # applied this turn, active next
        
        # Chris — Lava Surge: lava zones (impassable squares for N turns)
        self.lava_zones: Dict[Tuple[int, int], int] = {}  # pos -> turns remaining
        self.chris_stuck: Set[Tuple[int, int]] = set()  # Chris positions stuck by lava
        
        # Juice Box — Shapeshift: captured pawn abilities. Keyed by (color, id(piece))
        # rather than board position -- she keeps every captured ability as she
        # moves and captures again, not just whatever she captured most recently.
        self.juice_box_captured: Dict[Tuple[Color, int], List[str]] = {}
        self.juice_box_used_this_turn: Set[Tuple[int, int]] = set()  # can't use ability same turn as capture
        # Chunk 4 balance: 1-turn cooldown between acquired-ability uses, per side.
        # Set True after a successful use; cleared at the start of that side's next turn.
        self.juice_box_cooldown: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}
        
        # Florin — Suppressing Fire: push pieces away
        # (handled directly in ability, no persistent state needed)
        
        # Ren — Indestructible: (handled in is_piece_invulnerable)
        
        # Signet — Succubus: pull male pieces closer
        # (handled directly in ability, no persistent state needed)
        
        # Miriam Dom — Blood Magic: (uses existing captured list)
        
        # Orthrus — Aloof: always moves 2 squares, can only be captured by majors
        self.orthrus_permanently_dead: Set[str] = set()  # "color_orthrus" keys
        
        # Raul — Group Climax: cost reduction
        self.group_climax_active: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}
        
        # Bad Llama — Lava Spit: zones that force movement
        self.lava_spit_zones: List[Dict] = []  # [{pos: [(r,c),(r,c)], turns: int}] (1x2 horizontal zones)
        # Bad Llama — Lava Spit: can't move flag (same pattern as louie_cant_move)
        self.bad_llama_cant_move: Set[Tuple[int, int]] = set()

        # ── Additional state referenced by ability methods ────────────
        # Forced retreat (Florin's Suppressing Fire — _apply_forced_retreat reads this)
        self.forced_retreat: Dict[Tuple[int, int], Tuple[int, int]] = {}
        self.forced_retreat_pending: Dict[Tuple[int, int], Tuple[int, int]] = {}

        # Raul the Crab — Group Climax pending next turn
        self.group_climax_pending: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}

        # Stripper Anaconda (Gun Show) / Signet (Succubus): pulls resolve
        # immediately -- no persistent state (see pull_targets / _try_pull).

        # ── AI Card System (Chunk 3) ─────────────────────────────
        self.ai_card_deck: List[str] = ai_cards.build_ai_deck()
        self.ai_cards_drawn: List[str] = []
        self.ai_card_active: Optional[Dict] = None  # currently-resolving/last-drawn card, or None

        # Game Settings (start-screen ⚙️ modal): when False, dice rolls never
        # trigger an AI Card draw. Set from /new_game's `ai_enabled` body field.
        self.ai_summon_enabled: bool = True
        # Game Settings: global ability toggles. When False, that whole class of
        # ability cannot be activated by EITHER player -- the frontend hides the
        # human's cards, and the AI (smart_abilities / random_abilities) skips
        # the matching pieces. Set from /new_game's body fields.
        self.pawns_enabled: bool = True
        self.major_abilities_enabled: bool = True

        # System Reset -- no abilities activatable by anyone, for the rest of this turn
        self.system_reset_active: bool = False
        # Main Character Syndrome -- no pawns can move, for the rest of this turn
        self.main_character_syndrome_active: bool = False
        # What a Bitch -- one-shot Insta-Kill Boss Card, usable during a boss battle (Part 3)
        self.insta_kill_card: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}

        # Lottery Ticket (Custard) / Too Boring -- a card that needs the player to pick a
        # target pauses here instead of resolving immediately: normal gameplay is
        # blocked (see route guards in app.py) until it's resolved via
        # /ai_card/custard_choice or /ai_card/too_boring_choice.
        self.pending_ai_card_decision: Optional[Dict] = None

        # Matt's Drunk Again -- while active, each player controls the OTHER color's
        # pieces. Piece.color itself is never touched (so check/checkmate/board state
        # stay exactly as they'd be without a swap) -- only which side is allowed to
        # move/use-ability on which pieces changes. See controlled_color().
        self.swap_active: bool = False
        self.swap_turns_remaining: int = 0
        # Snapshot of every piece's true color at the moment the swap started, keyed
        # "row,col". Colors are never actually mutated, so this is informational only.
        self.original_colors: Dict[str, str] = {}

        # Boss Event system (Chunk 3 Part 2 sets these; Part 3 implements the fight)
        self.boss_active: bool = False
        self.active_boss: Optional[str] = None
        self.boss_hp: int = 0
        self.boss_max_hp: int = 0
        self.boss_position: Optional[Tuple[int, int]] = None
        self.boss_squares: List[Tuple[int, int]] = []
        # A Summon card drawn while a boss is already active queues here instead of
        # spawning immediately; Part 3's boss-defeat logic will pop and spawn it.
        self.pending_boss_summon: Optional[str] = None

        # Boss Turn (Part 3 Stage A): after Black ends their turn, if a boss is
        # active, both players roll 1 die each before control returns to White.
        self.boss_turn_active: bool = False
        self.boss_turn_rolls: Dict[str, Optional[int]] = {"white": None, "black": None}

        # Samantha's IWKYM (Part 3 Stage B): holds the boss still for 2 boss turns.
        self.iwkym_active: bool = False
        self.iwkym_turns_remaining: int = 0
        self.iwkym_holder_pos: Optional[Tuple[int, int]] = None

        # Boss co-op (Part 3 Stage D): colors whose Carl has permanently fallen
        # during an active boss battle. A fallen color's remaining pieces stay
        # on the board and are still playable (by the surviving player) as
        # extra resources against the boss -- see app.py's _handle_carl_fallen
        # and movement._is_move_legal's missing-king carve-out.
        self.fallen_players: Set[Color] = set()

        # Turn counter
        self.turn_number = 0
        self.current_player = Color.WHITE

        # Event log for this game
        self.events: List[Dict] = []
        self._event_seq: int = 0

    def init_pawn_ability_tracking(self):
        """Initialize per-pawn ability use counters based on drafted pawns."""
        for color in [Color.WHITE, Color.BLACK]:
            for r, c, piece in self.board.all_pieces(color):
                if piece.is_pawn and piece.pawn_name:
                    key = f"{color.value}_{piece.pawn_name}"
                    char = PAWN_CHARACTERS.get(piece.pawn_name)
                    if char and char.ability.uses_per_game is not None:
                        self.pawn_ability_uses[key] = {
                            char.ability.name: char.ability.uses_per_game
                        }

    def log_event(self, event_type: str, **kwargs):
        """Log a game event."""
        self._event_seq += 1
        self.events.append({
            "turn": self.turn_number,
            "player": self.current_player.value,
            "type": event_type,
            **kwargs,
            "seq": self._event_seq,
        })

    @property
    def ai_deck_remaining(self) -> int:
        """Cards left in the AI Card deck, for the frontend deck-count indicator."""
        return len(self.ai_card_deck)

    def draw_ai_card_if_triggered(self, d1: int, d2: int, triggering_color: Color,
                                   dice: Optional[DungeonDice] = None) -> Optional[str]:
        """Check a pair of d6 values for the AI summon pattern and draw a card if so.

        `dice` is the live DungeonDice for this turn's roll, when there is one
        (some card effects need to modify it directly). Returns the drawn
        card's name, or None if it didn't trigger (or the deck was empty).
        """
        return ai_cards.maybe_trigger_ai_card(self, d1, d2, triggering_color, dice=dice)

    def controlled_color(self, color: Optional[Color] = None) -> Color:
        """The color whose pieces `color` (default: current_player) may move or use
        abilities on right now. Equal to `color` normally; flipped to the opponent's
        color while Matt's Drunk Again's control swap is active.
        """
        base = color if color is not None else self.current_player
        return base.opponent if self.swap_active else base

    # ── Boss Combat (Part 3 Stage B) ────────────────────────────────

    def _boss_square_near(self, pos: Tuple[int, int], radius: int = 0) -> bool:
        """True if any current boss square is within `radius` squares (Chebyshev) of pos."""
        if not self.boss_active or not self.boss_squares:
            return False
        pr, pc = pos
        for (br, bc) in self.boss_squares:
            if max(abs(br - pr), abs(bc - pc)) <= radius:
                return True
        return False

    def _line_path(self, from_pos: Tuple[int, int], to_pos: Tuple[int, int],
                    max_distance: int) -> Optional[List[Tuple[int, int]]]:
        """Squares from (excluding) from_pos to (including) to_pos, if to_pos is
        reachable in a straight orthogonal or diagonal line within max_distance.
        Returns None if to_pos isn't aligned with from_pos or is too far.
        """
        fr, fc = from_pos
        tr, tc = to_pos
        dr, dc = tr - fr, tc - fc
        if dr == 0 and dc == 0:
            return None
        if dr != 0 and dc != 0 and abs(dr) != abs(dc):
            return None
        distance = max(abs(dr), abs(dc))
        if distance > max_distance:
            return None
        step_r = (dr > 0) - (dr < 0)
        step_c = (dc > 0) - (dc < 0)
        return [(fr + step_r * i, fc + step_c * i) for i in range(1, distance + 1)]

    def damage_boss(self, amount: int = 1) -> None:
        """Apply damage to the active boss, defeating it once HP reaches 0."""
        if not self.boss_active:
            return
        if self.active_boss == "Feral Goose":
            # Immune to every Special Event Attack -- only the corner/center
            # puzzle (see check_feral_goose_puzzle) can defeat her.
            self.log_event("boss_damage_blocked", boss=self.active_boss,
                           detail="The Feral Goose is immune to all attacks — solve the puzzle to defeat it.")
            return
        self.boss_hp = max(0, self.boss_hp - amount)
        self.log_event("boss_damaged", boss=self.active_boss, amount=amount, boss_hp=self.boss_hp)
        if self.boss_hp <= 0:
            self.defeat_boss()

    def defeat_boss(self) -> None:
        """Clear the active boss and either spawn a queued boss immediately
        (following standard spawn rules, including killing anything on its
        spawn squares) or leave the board clear for normal PvP to resume.
        """
        defeated_name = self.active_boss
        self.boss_active = False
        self.active_boss = None
        self.boss_hp = 0
        self.boss_max_hp = 0
        self.boss_position = None
        self.boss_squares = []
        # A defeated boss also ends any IWKYM hold on it.
        self.iwkym_active = False
        self.iwkym_turns_remaining = 0
        self.iwkym_holder_pos = None
        self.log_event("boss_defeated", boss=defeated_name)

        if self.pending_boss_summon:
            from . import ai_cards
            queued = self.pending_boss_summon
            self.pending_boss_summon = None
            ai_cards.spawn_boss(self, queued)
            self.log_event("queued_boss_spawned", boss=queued)

    def try_insta_kill(self, color: Color) -> bool:
        """Play `color`'s Insta-Kill Boss Card (from What a Bitch): instantly
        defeat the active boss -- any boss, the Feral Goose included -- at no
        dice cost. Consumes the card. False if there's no boss or no card."""
        if not self.boss_active or not self.insta_kill_card.get(color):
            return False
        self.insta_kill_card[color] = False
        self.log_event("insta_kill", player=color.value, boss=self.active_boss)
        self.defeat_boss()
        return True

    # The 4 board corners + center square Feral Goose's puzzle requires to be
    # simultaneously occupied (by any piece, either color) to defeat her.
    FERAL_GOOSE_PUZZLE_SQUARES = [(0, 0), (0, BOARD_SIZE - 1), (BOARD_SIZE - 1, 0),
                                   (BOARD_SIZE - 1, BOARD_SIZE - 1), (5, 5)]

    def check_feral_goose_puzzle(self) -> bool:
        """Called at the end of every turn while a Feral Goose is active. If
        all 5 puzzle squares are simultaneously occupied, she's defeated.
        Returns True if this defeated her, and False in every other case
        (including whenever she isn't the active boss at all) -- the return
        value is diagnostic only; callers must not depend on it to decide
        whether the turn is allowed to end (see end_turn()).

        Logs a "feral_goose_puzzle_check" event on every call while she's
        active, recording which of the 5 squares are currently occupied, so a
        future freeze during her fight can be traced from the event log alone.
        """
        if not self.boss_active or self.active_boss != "Feral Goose":
            return False

        occupied = [self.board.get(r, c) is not None for (r, c) in self.FERAL_GOOSE_PUZZLE_SQUARES]
        solved = all(occupied)
        self.log_event("feral_goose_puzzle_check",
                       squares=[[r, c] for (r, c) in self.FERAL_GOOSE_PUZZLE_SQUARES],
                       occupied=occupied, solved=solved)

        if solved:
            self.log_event("feral_goose_puzzle_solved",
                           detail="Puzzle Solved — The Feral Goose has been defeated!")
            self.defeat_boss()
            return True
        return False

    # ── Turn Lifecycle ────────────────────────────────────────────

    def start_turn(self):
        """Called at the start of each turn. Clears per-turn state."""
        # Rebuild from persistent tracker so Air Strike zones survive across turns
        self.louie_cant_move = set(self.air_strike_zones.keys())
        self.blitzed_pieces.clear()
        self.mongo_released_this_turn.clear()
        self.juice_box_used_this_turn.clear()
        # Juice Box's acquired-ability cooldown lasts until the start of her
        # side's next turn (see try_juice_box_use_captured_ability).
        self.juice_box_cooldown[self.current_player] = False

        # Promote pending suppressed pieces to active (lasts 1 opponent turn)
        self.suppressed_pieces = self.suppressed_pending.copy()
        self.suppressed_pending.clear()

        # Promote pending status effects to active (they last 1 opponent turn)
        self.frozen_pieces = self.frozen_pending.copy()
        self.frozen_pending.clear()
        
        self.restrained_pieces = self.restrained_pending.copy()
        self.restrained_pending.clear()
        
        self.she_tank_targets = self.she_tank_pending.copy()
        self.she_tank_pending.clear()

    def promote_group_climax(self, dice: DungeonDice):
        """Apply Raul the Crab's Group Climax if it's pending for the player whose
        turn is starting: all their ability floor costs drop by 2 for this turn.

        Reuses the same DungeonDice.floor_modifier channel the AI Cards
        "AI's Pet" (-1) and "Dirty Tootsies" (+1) use, and stacks additively
        with them. Must be called after the turn's dice have been rolled (roll()
        resets floor_modifier to 0) and before any ability is attempted.
        """
        color = self.current_player
        if self.group_climax_pending.get(color):
            dice.floor_modifier -= 2
            self.group_climax_pending[color] = False
            self.group_climax_active[color] = True
            self.log_event("group_climax_active",
                           detail="All friendly ability costs reduced by 2 this turn")

    def end_turn(self):
        """Called at end of turn. Tick down durations, swap player."""
        # AI Card effects scoped to "this turn only"
        self.system_reset_active = False
        self.main_character_syndrome_active = False
        # Raul's Group Climax buff is scoped to the single turn it applied on.
        self.group_climax_active = {Color.WHITE: False, Color.BLACK: False}
        # Bad Llama's Lava Spit "cannot move this turn" is scoped to the
        # single turn it was cast on (same pattern as louie_cant_move).
        self.bad_llama_cant_move = set()
        self.mongo_released_this_turn = set()
        # Catch-all for any way Donut left the board this turn that didn't go
        # through process_post_capture / eliminate_piece_permanently (e.g. a
        # Mediation reversal capturing her as the attacker).
        self.drop_stored_mongos_without_donut()

        # Tick ghost tokens. A Mordecai ghost square placed this turn skips its
        # first tick -- the capture turn's own end_turn() shouldn't burn a turn
        # off it (keeps it in sync with the 3-full-turn respawn timer).
        expired_ghosts = []
        for pos, turns in self.ghost_tokens.items():
            if pos in self.mordecai_ghost_fresh:
                self.mordecai_ghost_fresh.discard(pos)
                continue
            self.ghost_tokens[pos] = turns - 1
            if self.ghost_tokens[pos] <= 0:
                expired_ghosts.append(pos)
        for pos in expired_ghosts:
            del self.ghost_tokens[pos]

        # Tick stuck pieces
        expired_stuck = [pos for pos, t in self.stuck_pieces.items() if t - 1 <= 0]
        self.stuck_pieces = {pos: t - 1 for pos, t in self.stuck_pieces.items() if t - 1 > 0}

        # Tick iron wall
        expired_wall = [pos for pos, t in self.iron_wall_pieces.items() if t - 1 <= 0]
        self.iron_wall_pieces = {
            pos: t - 1 for pos, t in self.iron_wall_pieces.items() if t - 1 > 0
        }

        # Tick lava zones
        expired_lava = [pos for pos, t in self.lava_zones.items() if t - 1 <= 0]
        self.lava_zones = {pos: t - 1 for pos, t in self.lava_zones.items() if t - 1 > 0}
        for pos in expired_lava:
            self.chris_stuck.discard(pos)  # Chris can move again when lava expires

        # Tick air strike zones
        self.air_strike_zones = {pos: t - 1 for pos, t in self.air_strike_zones.items() if t - 1 > 0}

        # Tick Puddle Jump cooldown
        if self.puddle_jump_cooldown > 0:
            self.puddle_jump_cooldown -= 1
        
        # Tick lava spit zones
        self.lava_spit_zones = [
            {**zone, "turns": zone["turns"] - 1}
            for zone in self.lava_spit_zones if zone["turns"] - 1 > 0
        ]

        # Swallowed pawns (Slut Shame) respawn on a square next to where
        # Samantha swallowed them. With no safe square free, the pawn waits
        # and tries again at the end of the next turn.
        still_swallowed = []
        for pawn_data in self.swallowed_pawns:
            pawn_data["turns_left"] -= 1
            if pawn_data["turns_left"] > 0:
                still_swallowed.append(pawn_data)
                continue
            sr, sc = pawn_data["samantha_pos"]
            piece = pawn_data["piece"]
            spot = next((sq for sq in [(sr + dr, sc + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)]
                         if sq != (sr, sc) and self._safe_respawn_square(piece, sq)), None)
            if spot is None:
                still_swallowed.append(pawn_data)
                continue
            self.board.set(spot[0], spot[1], piece)
            self.log_event("pawn_respawn", piece=repr(piece), pos=spot)
        self.swallowed_pawns = still_swallowed

        # Mordecai respawn. Skip the grace tick on the capture turn's own
        # end_turn() so exactly 3 full turns pass between death and respawn.
        # With no safe back-rank square free, he waits and tries again at the
        # end of the next turn.
        still_pending = []
        for mord_data in self.mordecai_respawn_pending:
            if mord_data.pop("skip_first_tick", False):
                still_pending.append(mord_data)
                continue
            mord_data["turns_left"] -= 1
            if mord_data["turns_left"] > 0:
                still_pending.append(mord_data)
                continue
            piece = mord_data["piece"]
            back_rank = 0 if mord_data["color"] == Color.WHITE else BOARD_SIZE - 1
            spot = next((sq for sq in [(back_rank, c) for c in range(BOARD_SIZE)]
                         if self._safe_respawn_square(piece, sq)), None)
            if spot is None:
                still_pending.append(mord_data)
                continue
            self.board.set(spot[0], spot[1], piece)
            # NOTE: Mordecai's Manager Benefit respawn is his own passive,
            # not an enemy resurrection, so a Juice Box that captured him
            # keeps that acquired ability. Only an opponent actively
            # resurrecting the pawn (Cockroach / Blood Magic) strips it.
            self.log_event("mordecai_respawn", piece=repr(piece), pos=spot)
        self.mordecai_respawn_pending = still_pending

        # Matt's Drunk Again -- tick down one full turn (this individual player's
        # turn, not a full white+black round); restore normal control at zero.
        if self.swap_active:
            self.swap_turns_remaining -= 1
            if self.swap_turns_remaining <= 0:
                self.swap_active = False
                self.swap_turns_remaining = 0
                self.original_colors = {}
                self.log_event("matts_drunk_again_ended",
                               detail="Control swap ended, normal control restored")

        # Feral Goose puzzle: check at the end of every turn while she's active.
        # Wrapped defensively -- an exception here must never prevent the turn
        # from actually ending (player swap + turn increment below). Without
        # this guard, any failure in the puzzle check would leave the move
        # already applied to the board but control never passed to the other
        # side, soft-locking the game.
        try:
            self.check_feral_goose_puzzle()
        except Exception as exc:
            self.log_event("feral_goose_puzzle_check_error", error=repr(exc))

        # Swap player
        self.current_player = self.current_player.opponent
        self.turn_number += 1

    def _safe_respawn_square(self, piece: Piece, pos: Tuple[int, int]) -> bool:
        """Whether an end-of-turn respawn may put `piece` on pos: an open,
        unzoned square where it doesn't put the player whose turn is ending
        in check -- the other side moves next and could take that Carl."""
        if (not self.board.in_bounds(*pos) or self.board.get(*pos) is not None
                or self.is_square_blocked(*pos)):
            return False
        ender = self.current_player
        if piece.color == ender or self.board.find_king(ender) is None:
            return True
        if is_in_check(self.board, ender):
            return True  # already in check -- this respawn doesn't change that
        self.board.set(pos[0], pos[1], piece)
        try:
            return not is_in_check(self.board, ender)
        finally:
            self.board.set(pos[0], pos[1], None)

    # ── Square Blocking ───────────────────────────────────────────

    def is_square_blocked(self, row: int, col: int) -> bool:
        """Check if a square is blocked by ghost tokens, lava zones, air strike
        zones, or Bad Llama's lava spit zones."""
        if (row, col) in self.ghost_tokens:
            return True
        if (row, col) in self.lava_zones:
            return True
        if (row, col) in self.air_strike_zones:
            return True
        for zone in self.lava_spit_zones:
            if (row, col) in zone["pos"]:
                return True
        return False

    def is_piece_movable(self, row: int, col: int, piece: Piece) -> bool:
        """Check if a piece can move (not stuck, not iron-walled, not frozen, etc.)."""
        # Main Character Syndrome (AI Card): pawns can't move this turn, no exceptions.
        # Major pieces are unaffected.
        if self.main_character_syndrome_active and piece.is_pawn:
            return False
        # A Mongo released from Pet Carrier this turn can't move or capture.
        if (row, col) in self.mongo_released_this_turn:
            return False
        # Blitzed pieces can skip movement requirement
        if (row, col) in self.blitzed_pieces:
            return True
        if (row, col) in self.stuck_pieces:
            return False
        if (row, col) in self.iron_wall_pieces:
            return False
        if (row, col) in self.louie_cant_move:
            return False
        if (row, col) in self.bad_llama_cant_move:
            return False
        if (row, col) in self.chris_stuck:
            return False
        if (row, col) in self.she_tank_targets:
            return False
        if (row, col) in self.frozen_pieces:
            return False
        if (row, col) in self.restrained_pieces:
            return False
        return True

    def is_piece_invulnerable(self, row: int, col: int) -> bool:
        """Check if a piece at this position cannot be captured."""
        if (row, col) in self.iron_wall_pieces:
            return True
        # Ren is indestructible — cannot be captured by normal means.
        # Skipped when pawn abilities are disabled via Game Settings: Ren
        # then behaves as a normal capturable pawn.
        piece = self.board.get(row, col)
        if (self.pawns_enabled and piece and piece.is_pawn
                and piece.pawn_name == "Ren"):
            return True
        return False

    def is_piece_suppressed(self, row: int, col: int) -> bool:
        """Check if a piece cannot use abilities."""
        if (row, col) in self.suppressed_pieces:
            return True
        if (row, col) in self.frozen_pieces:
            return True
        if (row, col) in self.restrained_pieces:
            return True
        return False

    def get_legal_moves_with_status(self, color: Color) -> List[Tuple[Tuple[int, int], Tuple[int, int]]]:
        """Get all legal moves, filtered by status effects (stuck, blocked squares, etc.)."""
        base_moves = all_legal_moves(self.board, color)
        filtered = []
        for (fr, fc), (tr, tc) in base_moves:
            piece = self.board.get(fr, fc)
            if piece is None:
                continue
            if not self.is_piece_movable(fr, fc, piece):
                continue
            if self.is_square_blocked(tr, tc):
                continue
            # Can't capture invulnerable pieces
            target = self.board.get(tr, tc)
            if target and self.is_piece_invulnerable(tr, tc):
                continue
            # Carl is never captured outright, as in chess. Normal play can't
            # leave him exposed, and if some effect ever does, his side still
            # gets its own turn to get out of check (or is checkmated then).
            if target and target.is_king:
                continue
            # During a Boss Event, regular PvP captures are disabled entirely --
            # pieces may still move for positioning, but only Special Event
            # Attacks can deal damage (and only to the boss). Any move that would
            # land on an occupied square (friendly or enemy) is excluded so the
            # board highlights only non-capture destinations.
            if self.boss_active and target is not None:
                continue
            # Ren cannot capture enemy pieces (skipped when pawn abilities
            # are disabled -- he then moves and captures as a normal pawn).
            if (self.pawns_enabled and piece.is_pawn
                    and piece.pawn_name == "Ren" and target is not None):
                continue
            # Orthrus cannot capture pieces (skipped when pawn abilities are
            # disabled -- he is then treated as a normal capturable pawn).
            if (self.pawns_enabled and piece.is_pawn
                    and piece.pawn_name == "Orthrus" and target is not None):
                continue
            # Only major pieces can capture Orthrus (skipped when pawn abilities
            # are disabled).
            if (self.pawns_enabled and target and target.is_pawn
                    and target.pawn_name == "Orthrus" and piece.is_pawn):
                continue
            filtered.append(((fr, fc), (tr, tc)))

        # Forced retreat filter (Florin's Suppressing Fire)
        retreat_filtered = self._apply_forced_retreat(filtered, color)

        return retreat_filtered if retreat_filtered else filtered

    # ── Capture Interception ──────────────────────────────────────

    def _piece_is_checking_opponent_carl(self, piece_pos: Tuple[int, int], piece: Piece) -> bool:
        """True when the piece at `piece_pos` is currently delivering check to the
        OPPONENT's Carl -- i.e. lifting it off the board would relieve that check.

        Quasar's Mediation cannot be used to defend such a piece: saving an
        attacker that is threatening the enemy Carl would otherwise let it
        capture Carl on the following move.
        """
        victim_color = piece.color.opponent
        if self.board.find_king(victim_color) is None:
            return False
        if not is_in_check(self.board, victim_color):
            return False
        pr, pc = piece_pos
        saved = self.board.get(pr, pc)
        self.board.set(pr, pc, None)
        try:
            still_in_check = is_in_check(self.board, victim_color)
        finally:
            self.board.set(pr, pc, saved)
        return not still_in_check

    def attempt_capture(
        self, attacker_pos: Tuple[int, int], defender_pos: Tuple[int, int]
    ) -> str:
        """Process capture with possible interceptions.

        Returns: "captured", "defended_quasar", "defended_orthrus", "defended_ren"
        """
        dr, dc = defender_pos
        defender = self.board.get(dr, dc)
        attacker = self.board.get(*attacker_pos)
        if defender is None:
            return "captured"

        # Every pawn-ability capture interception below (Ren, Orthrus, Quasar)
        # is skipped when pawn abilities are disabled via Game Settings -- those
        # pawns are then treated as ordinary capturable pieces.
        pawn_abilities_on = self.pawns_enabled

        # Check Ren's Indestructible (auto-trigger)
        if pawn_abilities_on and defender.is_pawn and defender.pawn_name == "Ren":
            # Ren can only be captured by enemy Carl or Blood Magic
            if not self.check_ren_special_capture(attacker_pos, defender_pos):
                self.log_event("ability_auto", piece="Ren", ability="Indestructible",
                               result="success", detail="Cannot be captured by non-Carl")
                return "defended_ren"

        # Orthrus can only be captured by major pieces (defense in depth --
        # get_legal_moves_with_status already keeps non-majors from reaching here)
        if pawn_abilities_on and defender.is_pawn and defender.pawn_name == "Orthrus":
            if not self.check_orthrus_capturable(attacker):
                self.log_event("ability_auto", piece="Orthrus", ability="Only Majors Can Capture",
                               result="success", detail="Cannot be captured by non-major pieces")
                return "defended_orthrus"

        # Check Quasar's Mediation (defensive, auto-trigger). Also applies if
        # the defender is Juice Box and has personally captured Mediation --
        # Shapeshift makes it her own passive defense, not just Quasar's.
        quasar_alive = self._find_pawn(defender.color, "Quasar")
        juice_box_has_mediation = (
            defender.is_pawn and defender.pawn_name == "Juice Box"
            and "Mediation" in self.juice_box_captured.get(self.juice_box_key(defender), [])
        )
        # Mediation can never protect Carl himself, cannot fire while the
        # defending side's Carl is in check, and cannot rescue a piece that is
        # itself currently checking the enemy Carl (that would just let it take
        # Carl next move).
        mediation_available = (
            pawn_abilities_on
            and (quasar_alive or juice_box_has_mediation)
            and self.quasar_uses[defender.color] < 2
            and not defender.is_king
            and not is_in_check(self.board, defender.color)
            and not self._piece_is_checking_opponent_carl(defender_pos, defender)
        )
        if mediation_available:
            self.quasar_uses[defender.color] += 1
            defender_saved, atk_total, dfn_total = self._mediation_rolloff(attacker.color)
            self.log_event("ability_auto", piece="Quasar", ability="Mediation",
                           attacker_total=atk_total, defender_total=dfn_total,
                           result="success" if defender_saved else "fail")
            if defender_saved:
                # Defender won the roll-off by 2+ -- the attacker is captured instead.
                self.log_event("mediation_reversal",
                               detail=f"Defender rolled {dfn_total} vs {atk_total} (won by 2+)")
                return "defended_quasar"
            # Tie or attacker wins the roll-off -- capture proceeds normally.

        return "captured"

    def process_post_capture(self, captured_piece: Piece, capture_pos: Tuple[int, int],
                              attacker: Piece, attacker_pos: Tuple[int, int]):
        """Handle effects that trigger after a capture (Mordecai Manager Benefit, Orthrus, Juice Box, etc.)."""
        if captured_piece is None:
            return

        # Orthrus is a single logical piece occupying two squares (head +
        # butt). Whichever of the two was just captured here, the OTHER
        # square must always be cleared together -- this is structural (how
        # his body is represented on the board), not a pawn ability, so it
        # runs unconditionally and BEFORE the pawns_enabled gate below. By
        # the time captured_piece is Orthrus, attempt_capture() has already
        # legitimately allowed the capture (majors-only when pawns_enabled is
        # True, any attacker when it's False -- see attempt_capture), so no
        # further check_orthrus_capturable() re-check is needed here.
        if captured_piece.is_pawn and captured_piece.pawn_name == "Orthrus":
            self.process_orthrus_permanent_death(captured_piece, capture_pos)

        # Pet Carrier: a captured Donut takes her side's stored Mongo with her.
        # A major-piece rule, so it also runs when pawn abilities are off.
        if captured_piece.piece_type == PieceType.DONUT:
            self.drop_stored_mongos_without_donut()

        # Every other post-capture pawn auto-trigger below is skipped when
        # pawn abilities are disabled via Game Settings.
        if not self.pawns_enabled:
            return

        # Mordecai's Manager Benefit (Chunk 2)
        if captured_piece.is_pawn and captured_piece.pawn_name == "Mordecai":
            self.process_mordecai_capture(capture_pos, captured_piece)

        # Juice Box Shapeshift (Chunk 2)
        if attacker.is_pawn and attacker.pawn_name == "Juice Box":
            if captured_piece.is_pawn:
                # Juice Box always ends the capture standing on capture_pos (she moves
                # onto the captured piece's square), so that's her key into
                # juice_box_captured — not attacker_pos, her square before the move.
                self.process_juice_box_capture(capture_pos, captured_piece, capture_pos)

    # ── Helpers ───────────────────────────────────────────────────

    def _find_pawn(self, color: Color, pawn_name: str) -> Optional[Tuple[int, int]]:
        """Find a living pawn by name and color."""
        for r, c, p in self.board.all_pieces(color):
            if p.is_pawn and p.pawn_name == pawn_name:
                return (r, c)
        return None

    def leaves_carl_in_check(self, color: Color, moves=(), removals=(), placements=()) -> bool:
        """True if these board changes would leave `color`'s Carl in check: the
        squares in `removals` emptied, then each (src, dest) in `moves` applied
        (dest's occupant is captured), then each (pos, piece) in `placements`
        put on the board. The board is restored afterwards.

        Every ability that moves or removes pieces checks this before spending
        anything, so no ability can leave its caster's own Carl in check.
        """
        if self.board.find_king(color) is None:
            return False  # boss co-op fallen player -- no Carl to protect
        saved = {}
        for pos in (list(removals) + [sq for move in moves for sq in move]
                    + [pos for pos, _piece in placements]):
            saved.setdefault(tuple(pos), self.board.get(*pos))
        try:
            for r, c in removals:
                self.board.set(r, c, None)
            for (sr, sc), (dr, dc) in moves:
                piece = self.board.get(sr, sc)
                self.board.set(sr, sc, None)
                self.board.set(dr, dc, piece)
            for (r, c), piece in placements:
                self.board.set(r, c, piece)
            return is_in_check(self.board, color)
        finally:
            for (r, c), piece in saved.items():
                self.board.set(r, c, piece)

    def apply_ability_move(self, src: Tuple[int, int], dest: Tuple[int, int]) -> Optional[Piece]:
        """Move the piece on src to dest for an ability (e.g. Special Boy),
        capturing whatever stands on dest the same way a normal capture does:
        into the graveyard, with its on-capture effects. A pawn reaching its
        promotion rank promotes. Returns the captured piece, if any.
        """
        piece = self.board.get(*src)
        captured = self.board.get(*dest)
        self.board.set(src[0], src[1], None)
        self.board.set(dest[0], dest[1], piece)
        piece.has_moved = True
        if captured is not None:
            self.board.captured[captured.color].append(captured)
            self.process_post_capture(captured, dest, piece, src)
        if self._promotes_on(piece, dest):
            self.board._promote_pawn(dest[0], dest[1], piece)
        return captured

    def _apply_forced_retreat(self, moves, color):
        """Filter moves for pieces under Florin's Suppressing Fire.

        Affected pieces must move away from Florin (increase distance) or sidestep.
        """
        if not self.forced_retreat:
            return moves

        result = []
        for (fr, fc), (tr, tc) in moves:
            if (fr, fc) in self.forced_retreat:
                florin_r, florin_c = self.forced_retreat[(fr, fc)]
                old_dist = abs(fr - florin_r) + abs(fc - florin_c)
                new_dist = abs(tr - florin_r) + abs(tc - florin_c)
                if new_dist < old_dist:
                    continue  # Can't advance toward Florin
                if new_dist == old_dist and (tr, tc) == (fr, fc):
                    continue  # Can't stay in place
            result.append(((fr, fc), (tr, tc)))

        # If forced retreat leaves no moves for affected pieces, exempt them
        affected_pieces = set(self.forced_retreat.keys())
        has_move = {pos: False for pos in affected_pieces}
        for (fr, fc), _ in result:
            if (fr, fc) in has_move:
                has_move[(fr, fc)] = True
        all_have_moves = all(has_move.values())
        if not all_have_moves:
            # Exempt pieces with no valid retreat
            return moves
        return result


    # ── Chunk 2 Abilities: Priority Group 1 (Simple Status Effects) ──

    def try_sic_em(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                   die_index: int) -> bool:
        """Lucia Mar's Sic Em (Floor 3): Restrain 1 enemy piece anywhere on the board."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Lucia Mar", "Juice Box"):
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 3)
        self.log_event("ability_roll", piece="Lucia Mar", ability="Sic Em",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if not success:
            return False

        r, c = pawn_pos
        # Find enemy pieces anywhere on the board
        targets = []
        for nr in range(BOARD_SIZE):
            for nc in range(BOARD_SIZE):
                if (nr, nc) == (r, c):
                    continue
                target = self.board.get(nr, nc)
                if target and target.color != piece.color:
                    targets.append((nr, nc))

        if not targets:
            return False

        # Pick random target and restrain it
        target_pos = random.choice(targets)
        self.restrained_pending.add(target_pos)
        self.log_event("sic_em", target=repr(self.board.get(*target_pos)), target_pos=target_pos,
                       detail="Restrained for next turn")
        return True

    def try_frozen(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                   die_index: int, target_pos: Tuple[int, int] = None) -> bool:
        """Elle McGib's Frozen (Floor 5): Freeze enemy piece within 5 squares."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Elle McGib", "Juice Box"):
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 5)
        self.log_event("ability_roll", piece="Elle McGib", ability="Frozen",
                       die_value=dice.dice[die_index], floor=5, result="success" if success else "fail")
        if not success:
            return False

        r, c = pawn_pos
        # Find enemy pieces within 5 squares
        targets = []
        for dr in range(-5, 6):
            for dc in range(-5, 6):
                if dr == 0 and dc == 0:
                    continue
                if abs(dr) > 5 or abs(dc) > 5:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    target = self.board.get(nr, nc)
                    if target and target.color != piece.color:
                        targets.append((nr, nc))

        if not targets:
            return False

        # Use provided target if valid, otherwise pick randomly
        if target_pos and tuple(target_pos) in targets:
            chosen = tuple(target_pos)
        else:
            chosen = random.choice(targets)
        self.frozen_pending.add(chosen)
        self.log_event("frozen", target=repr(self.board.get(*chosen)), target_pos=chosen,
                       detail="Frozen for next turn")
        return True

    def try_suppress(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                     die_index: int) -> bool:
        """Imani's Suppress (Floor 4): Enemy piece within 2 squares loses abilities."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Imani", "Juice Box"):
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Imani", ability="Suppress",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        r, c = pawn_pos
        # Find enemy pieces within 2 squares
        targets = []
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    target = self.board.get(nr, nc)
                    if target and target.color != piece.color:
                        targets.append((nr, nc))

        if not targets:
            return False

        # Pick random target and suppress it
        target_pos = random.choice(targets)
        self.suppressed_pending.add(target_pos)
        self.log_event("suppress", target=repr(self.board.get(*target_pos)), target_pos=target_pos,
                       detail="Suppressed for next turn")
        return True

    def try_body_guard(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                       die_index: int) -> bool:
        """Sledge's Body Guard (Floor 4): Become immovable and invulnerable for 2 turns."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Sledge", "Juice Box"):
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Sledge", ability="Body Guard",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        # Make Sledge immovable and invulnerable for 2 turns
        self.iron_wall_pieces[pawn_pos] = 2
        self.log_event("body_guard", pos=pawn_pos, detail="Immovable and invulnerable for 2 turns")
        return True

    # ── Chunk 2 Abilities: Priority Group 2 (Movement Modifiers) ──

    def try_biggest_fan(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                        die_index: int) -> bool:
        """Zev's Biggest Fan (Floor 3): All friendly pieces get +1 to dice next turn."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Zev", "Juice Box"):
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 3)
        self.log_event("ability_roll", piece="Zev", ability="Biggest Fan",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if not success:
            return False

        # Set buff to activate next turn
        self.zev_buff_active[piece.color] = True
        self.log_event("biggest_fan", detail="All friendly pieces get +1 to dice next turn")
        return True

    def special_boy_destinations(self, pawn_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Prepotente's Special Boy destinations: 2 squares straight forward,
        or a 2-forward diagonal capture (up to 2 columns over); any square
        within 2 while his Carl is in check. Never the enemy Carl, an
        invulnerable piece (Ren, Body Guard), or Orthrus (only majors capture
        him), and never a move that leaves his own Carl in check.
        """
        piece = self.board.get(*pawn_pos)
        if piece is None:
            return []
        r, c = pawn_pos
        forward = piece.color.direction

        if is_in_check(self.board, piece.color):
            candidates = [(r + dr, c + dc) for dr in range(-2, 3) for dc in range(-2, 3)
                          if (dr, dc) != (0, 0)]
            captures_only = set()
        else:
            nr = r + 2 * forward
            candidates = [(nr, c)] + [(nr, c + dc) for dc in (-2, -1, 1, 2)]
            captures_only = set(candidates[1:])  # the diagonals need a piece to capture

        moves = []
        for nr, nc in candidates:
            if not self.board.in_bounds(nr, nc) or self.is_square_blocked(nr, nc):
                continue
            target = self.board.get(nr, nc)
            if target is None:
                if (nr, nc) in captures_only:
                    continue
            elif (target.color == piece.color or target.is_king
                    or self.is_piece_invulnerable(nr, nc) or target.pawn_name == "Orthrus"):
                continue
            if self.leaves_carl_in_check(piece.color, moves=[(pawn_pos, (nr, nc))]):
                continue
            moves.append((nr, nc))
        return moves

    def try_special_boy(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                        die_index: int) -> Optional[List[Tuple[int, int]]]:
        """Prepotente's Special Boy (Floor 4): Move 2 squares forward.

        Returns the destinations (see special_boy_destinations) on success; the
        caller moves him with apply_ability_move. With no destination, nothing
        is spent.
        """
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Prepotente", "Juice Box"):
            return None
        if self.is_piece_suppressed(*pawn_pos):
            return None
        moves = self.special_boy_destinations(pawn_pos)
        if not moves:
            return None

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Prepotente", ability="Special Boy",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        return moves if success else None

    def suppressing_fire_pushes(self, florin_pos: Tuple[int, int]) -> Dict[Tuple[int, int], Tuple[int, int]]:
        """Enemy pieces within 5 squares Florin can push, mapped to where each
        ends up: 2 squares directly away from Florin, stopping early at a piece,
        zone, or the board edge. Never Orthrus (2-square body) or a Body Guard
        piece, never a piece that can't move at all, and never a push that
        leaves Florin's own Carl in check.
        """
        piece = self.board.get(*florin_pos)
        if piece is None:
            return {}
        r, c = florin_pos
        pushes = {}
        for tr in range(max(0, r - 5), min(BOARD_SIZE, r + 6)):
            for tc in range(max(0, c - 5), min(BOARD_SIZE, c + 6)):
                target = self.board.get(tr, tc)
                if (target is None or target.color == piece.color or target.pawn_name == "Orthrus"
                        or (tr, tc) in self.iron_wall_pieces):
                    continue
                dr = (tr > r) - (tr < r)
                dc = (tc > c) - (tc < c)
                dest = None
                for i in (1, 2):
                    nr, nc = tr + dr * i, tc + dc * i
                    if (not self.board.in_bounds(nr, nc) or self.is_square_blocked(nr, nc)
                            or self.board.get(nr, nc) is not None):
                        break
                    dest = (nr, nc)
                if dest and not self.leaves_carl_in_check(piece.color, moves=[((tr, tc), dest)]):
                    pushes[(tr, tc)] = dest
        return pushes

    def try_suppressing_fire(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                             die_index: int) -> bool:
        """Florin's Suppressing Fire (Floor 6): Push enemy piece 2 squares away.
        The target is random (see suppressing_fire_pushes); nothing is spent if
        no enemy piece can be pushed."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Florin", "Juice Box"):
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False
        pushes = self.suppressing_fire_pushes(pawn_pos)
        if not pushes:
            return False

        success = dice.spend_die(die_index, 6)
        self.log_event("ability_roll", piece="Florin", ability="Suppressing Fire",
                       die_value=dice.dice[die_index], floor=6, result="success" if success else "fail")
        if not success:
            return False

        (tr, tc), (final_r, final_c) = random.choice(list(pushes.items()))
        target = self.board.get(tr, tc)
        self.board.set(tr, tc, None)
        self.board.set(final_r, final_c, target)
        self._relocate_piece_status((tr, tc), (final_r, final_c))
        self.log_event("suppressing_fire", target=repr(target), from_pos=(tr, tc),
                       to_pos=(final_r, final_c), pushed=max(abs(final_r - tr), abs(final_c - tc)))
        return True

    def chris_lava_surge_adjacent_enemy(self, pawn_pos: Tuple[int, int]) -> bool:
        """Check whether any enemy piece is adjacent (within 1 square) to Chris."""
        piece = self.board.get(*pawn_pos)
        if piece is None:
            return False
        r, c = pawn_pos
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    t = self.board.get(nr, nc)
                    if t and t.color != piece.color:
                        return True
        return False

    def chris_lava_surge_direction_squares(self, pawn_pos: Tuple[int, int], direction: str) -> List[Tuple[int, int]]:
        """Return the 3 squares (Chris's square + 1 each side) for a given direction."""
        r, c = pawn_pos
        if direction == "horizontal":
            return [(r, c - 1), (r, c), (r, c + 1)]
        return [(r - 1, c), (r, c), (r + 1, c)]

    def chris_lava_surge_direction_valid(self, pawn_pos: Tuple[int, int], direction: str) -> bool:
        """A direction is valid only if all 3 squares are in bounds and completely empty (Chris's own square excepted)."""
        for (sr, sc) in self.chris_lava_surge_direction_squares(pawn_pos, direction):
            if not self.board.in_bounds(sr, sc):
                return False
            if (sr, sc) != pawn_pos and self.board.get(sr, sc) is not None:
                return False
        return True

    def try_lava_surge_chunk2(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                              die_index: int, direction: Optional[str] = None) -> bool:
        """Chris's Lava Surge (Floor 4): Cover 3 squares with lava for 2 turns.

        Chris cannot cast while an enemy is adjacent, and the chosen direction's
        3 squares must be completely empty. `direction` is 'horizontal' or 'vertical'.
        """
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Chris", "Juice Box"):
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False
        if self.chris_lava_surge_adjacent_enemy(pawn_pos):
            return False
        if direction not in ("horizontal", "vertical"):
            return False
        if not self.chris_lava_surge_direction_valid(pawn_pos, direction):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Chris", ability="Lava Surge",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        lava_squares = self.chris_lava_surge_direction_squares(pawn_pos, direction)

        # Add lava zones
        for lr, lc in lava_squares:
            if self.board.in_bounds(lr, lc):
                self.lava_zones[(lr, lc)] = 2

        # Chris can't move for 2 turns
        self.chris_stuck.add(pawn_pos)

        self.log_event("lava_surge", pos=pawn_pos, lava_squares=lava_squares, direction=direction,
                       detail="Lava for 2 turns, Chris stuck")
        return True

    # ── Chunk 2 Abilities: Priority Group 3 (Zone Blocking) ──

    def try_air_strike(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                       die_index: int, target_pos: Optional[Tuple[int, int]] = None) -> bool:
        """Louie's Air Strike (Floor 6, requires combined): Create 2x2 blocked zone.

        `target_pos` is the top-left corner of the 2x2 zone, if the player chose
        one. All 4 squares must be completely empty.
        """
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Louie", "Juice Box"):
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        # Requires combined dice (total >= 6)
        if not dice.can_combine_for_cost(6):
            return False

        dice.spend_combined(6)
        self.log_event("ability_roll", piece="Louie", ability="Air Strike",
                       detail="Combined dice for cost 6", result="success")

        def zone_is_empty(zone_r, zone_c):
            for dr in range(2):
                for dc in range(2):
                    nr, nc = zone_r + dr, zone_c + dc
                    if not self.board.in_bounds(nr, nc) or self.board.get(nr, nc) is not None:
                        return False
            return True

        r, c = pawn_pos
        # Find valid, fully-empty 2x2 zones within 4 squares
        valid_zones = []
        for dr in range(-4, 5):
            for dc in range(-4, 5):
                zone_r, zone_c = r + dr, c + dc
                if zone_is_empty(zone_r, zone_c):
                    valid_zones.append((zone_r, zone_c))

        if target_pos is not None and zone_is_empty(target_pos[0], target_pos[1]):
            zone_pos = tuple(target_pos)
        elif valid_zones:
            zone_pos = random.choice(valid_zones)
        else:
            return False

        self.air_strike_zones.clear()  # Only one active zone at a time
        for dr in range(2):
            for dc in range(2):
                nr, nc = zone_pos[0] + dr, zone_pos[1] + dc
                if self.board.in_bounds(nr, nc):
                    self.air_strike_zones[(nr, nc)] = 2
        self.louie_cant_move = set(self.air_strike_zones.keys())
        self.log_event("air_strike", zone_pos=zone_pos, detail="2x2 blocked for 2 turns")
        return True

    def try_lava_spit_chunk2(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                             die_index: int, target_pos: Optional[Tuple[int, int]] = None) -> bool:
        """Bad Llama's Lava Spit (Floor 4): 1x2 horizontal lava strip within 4
        squares, for 3 full turns. No piece can enter the zone while it's
        active (see is_square_blocked).

        `target_pos`, if given, is the left square of the strip -- it extends
        right, or left if that would run off the board.
        """
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Bad Llama", "Juice Box"):
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Bad Llama", ability="Lava Spit",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        def strip_squares(zr, zc):
            """The 1x2 horizontal pair anchored at (zr, zc), extending right,
            or left if that would run off the board. None if neither fits."""
            if not self.board.in_bounds(zr, zc):
                return None
            if self.board.in_bounds(zr, zc + 1):
                return [(zr, zc), (zr, zc + 1)]
            if self.board.in_bounds(zr, zc - 1):
                return [(zr, zc - 1), (zr, zc)]
            return None

        r, c = pawn_pos
        # Find valid strip anchors within 4 squares
        valid_anchors = []
        for dr in range(-4, 5):
            for dc in range(-4, 5):
                zr, zc = r + dr, c + dc
                if strip_squares(zr, zc) is not None:
                    valid_anchors.append((zr, zc))

        if target_pos is not None and strip_squares(target_pos[0], target_pos[1]) is not None:
            anchor = tuple(target_pos)
        elif valid_anchors:
            anchor = random.choice(valid_anchors)
        else:
            return False

        zone_squares = strip_squares(*anchor)
        self.lava_spit_zones.append({"pos": zone_squares, "turns": 3})
        self.bad_llama_cant_move.add(pawn_pos)
        self.log_event("lava_spit_chunk2", zone=zone_squares,
                       detail="1x2 lava strip for 3 turns")
        return True

    # ── Chunk 2 Abilities: Priority Group 4 (Auto Triggers) ──

    def process_mordecai_capture(self, mordecai_pos: Tuple[int, int], mordecai_piece: Piece):
        """Mordecai's Manager Benefit: Auto-trigger on capture.
        Creates a single-square ghost zone on his captured square and
        schedules respawn after 3 turns.
        """
        # Single ghost square on exactly the square where Mordecai was captured.
        # It gets one grace tick (see end_turn) so it lasts 3 full turns AFTER
        # the capture turn, staying in sync with the respawn timer below.
        self.ghost_tokens[mordecai_pos] = 3
        self.mordecai_ghost_fresh.add(mordecai_pos)

        # Schedule Mordecai respawn 3 full turns after the capture turn.
        self.mordecai_respawn_pending.append({
            "piece": mordecai_piece,
            "turns_left": 3,
            "color": mordecai_piece.color,
            "skip_first_tick": True,
        })

        self.log_event("mordecai_manager_benefit", pos=mordecai_pos,
                       detail="Single ghost square for 3 turns, respawn scheduled")

    def check_mordecai_cost_reduction(self, piece_pos: Tuple[int, int], piece: Piece) -> int:
        """Check if Carl or Donut is within 1 square of Mordecai for cost reduction.
        Returns the cost reduction amount (0 or 1).
        """
        if not (piece.is_king or piece.piece_type == PieceType.DONUT):
            return 0
        
        r, c = piece_pos
        # Check for adjacent Mordecai
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    adj = self.board.get(nr, nc)
                    if (adj and adj.is_pawn and adj.pawn_name == "Mordecai" 
                        and adj.color == piece.color):
                        return 1
        return 0

    def check_ren_special_capture(self, attacker_pos: Tuple[int, int], 
                                  ren_pos: Tuple[int, int]) -> bool:
        """Check if Ren can be captured by this attacker.
        Ren can only be captured by enemy Carl moving onto his square or by Blood Magic.
        Returns True if capture is allowed, False otherwise.
        """
        attacker = self.board.get(*attacker_pos)
        if attacker is None:
            return False
        
        # Only enemy Carl can capture Ren by moving onto his square
        if attacker.is_king:
            return True
        
        return False

    def check_orthrus_capturable(self, attacker: Piece) -> bool:
        """Check if attacker can capture Orthrus.
        Orthrus can only be captured by major pieces.
        """
        if attacker.is_pawn:
            return False
        return True

    def process_orthrus_permanent_death(self, orthrus_piece: Piece, capture_pos: Tuple[int, int]):
        """Mark Orthrus as permanently dead and remove the rest of his 1x2 body.

        capture_pos is whichever of his two squares the attacker actually landed
        on; the other square (head or butt) still references this same Piece
        object and must be cleared too, since the whole creature dies together.
        """
        key = f"{orthrus_piece.color.value}_orthrus"
        self.orthrus_permanently_dead.add(key)

        head_pos = orthrus_piece.orthrus_head_pos
        butt_pos = self.board.orthrus_butt_pos(orthrus_piece)
        other_pos = butt_pos if capture_pos == head_pos else head_pos
        if other_pos is not None and self.board.get(*other_pos) is orthrus_piece:
            self.board.set(other_pos[0], other_pos[1], None)

        self.log_event("orthrus_permanent_death", pos=capture_pos, other_pos=other_pos,
                       detail="Orthrus permanently removed")

    def eliminate_piece_permanently(self, row: int, col: int) -> Optional[Piece]:
        """Remove whatever piece occupies (row, col) from the board entirely
        and mark it permanently dead (excluded from every resurrection
        candidate list, same as Orthrus already always is).

        Orthrus is a 1x2 body -- the same Piece instance occupies both his
        head and butt squares. Eliminating just the targeted square (a plain
        board.set(row, col, None)) leaves his other half behind as an
        unkillable ghost piece, so this clears both of his squares whenever
        either one is targeted. Every ability that permanently removes a pawn
        by square (Too Boring, Lottery Ticket's Fireball, a boss's spawn-kill
        or movement-sweep-kill) should route through this instead of poking
        the board directly.

        Appends the piece to its owner's captured list. Returns the removed
        piece, or None if the square was already empty.
        """
        piece = self.board.get(row, col)
        if piece is None:
            return None

        if piece.is_pawn and piece.pawn_name == "Orthrus" and piece.orthrus_head_pos is not None:
            head_pos = piece.orthrus_head_pos
            butt_pos = self.board.orthrus_butt_pos(piece)
            for pos in (head_pos, butt_pos):
                if pos is not None and self.board.get(*pos) is piece:
                    self.board.set(pos[0], pos[1], None)
            self.orthrus_permanently_dead.add(f"{piece.color.value}_orthrus")
        else:
            self.board.set(row, col, None)

        piece.permanently_dead = True
        self.board.captured[piece.color].append(piece)
        if piece.piece_type == PieceType.DONUT:
            self.drop_stored_mongos_without_donut()
        return piece

    def juice_box_key(self, juice_box_pos_or_piece):
        """Stable identity key for a specific Juice Box piece instance.

        Accepts either her current board position or the Piece object itself.
        Keyed by (color, id(piece)) rather than position -- her captured
        abilities travel with her as she moves and captures again, rather
        than resetting every time she relocates onto a new square.
        """
        piece = (juice_box_pos_or_piece if isinstance(juice_box_pos_or_piece, Piece)
                 else self.board.get(*juice_box_pos_or_piece))
        if piece is None:
            return None
        return (piece.color, id(piece))

    def process_juice_box_capture(self, juice_box_pos: Tuple[int, int],
                                   captured_pawn: Piece, captured_pos: Tuple[int, int]):
        """Juice Box Shapeshift: Auto-trigger when Juice Box captures a pawn.
        Juice Box gains the ability to use the captured pawn's ability.
        """
        if not captured_pawn.is_pawn or not captured_pawn.pawn_name:
            return

        key = self.juice_box_key(juice_box_pos)

        # Only floor-roll abilities are usable through Shapeshift's manual
        # trigger (mirrors the filter ai.py's _try_pawn_ability and
        # _categorize_pawn_ability already apply) -- auto/passive/no-roll
        # abilities like Ren's Indestructible, Quasar's Mediation, or
        # Mordecai's Manager Benefit have no active effect for her to fire,
        # so they must never be added as a usable entry.
        captured_char = PAWN_CHARACTERS.get(captured_pawn.pawn_name)
        gained_ability = (captured_char is not None
                          and captured_char.ability.trigger == AbilityTrigger.FLOOR_ROLL)

        if gained_ability:
            if key not in self.juice_box_captured:
                self.juice_box_captured[key] = []
            if captured_pawn.pawn_name not in self.juice_box_captured[key]:
                self.juice_box_captured[key].append(captured_pawn.pawn_name)

        # Mark that Juice Box can't use ability this turn -- applies to any
        # capture, regardless of whether an ability was actually gained above.
        self.juice_box_used_this_turn.add(juice_box_pos)

        self.log_event("juice_box_shapeshift", pos=juice_box_pos,
                       captured=captured_pawn.pawn_name,
                       detail=("Gained ability, cannot use this turn" if gained_ability
                               else "Captured pawn's ability isn't usable via Shapeshift"))

    def find_captured_ability(self, juice_box_pos: Tuple[int, int], ability_name: str):
        """Look up the PawnCharacter behind one of Juice Box's currently-acquired abilities."""
        captured_list = self.juice_box_captured.get(self.juice_box_key(juice_box_pos), [])
        for pawn_name in captured_list:
            char = PAWN_CHARACTERS.get(pawn_name)
            if char and char.ability.name == ability_name:
                return char
        return None

    def _juice_box_lose_ability(self, pawn_name: str):
        """Strip a captured-ability entry from every Juice Box list.

        Called whenever a pawn is resurrected — per her Shapeshift rule, if the
        opponent brings the captured pawn back, Juice Box loses that ability.
        """
        for jb_key, names in self.juice_box_captured.items():
            if pawn_name in names:
                names.remove(pawn_name)
                self.log_event("juice_box_lost_ability", pawn=pawn_name,
                               detail="Captured pawn was resurrected")

    def try_juice_box_use_captured_ability(self, juice_box_pos: Tuple[int, int],
                                           ability_name: str, dice: DungeonDice,
                                           die_index: int, use_combined: bool = False,
                                           target_pos: Optional[Tuple[int, int]] = None,
                                           direction: Optional[str] = None) -> bool:
        """Juice Box uses a captured pawn's ability, routed to that pawn's real
        implementation. Juice Box's own position stands in for the original
        pawn's position -- the effect originates from wherever she is standing.
        Dice cost/combining is handled by the underlying try_* method itself,
        exactly as it would be for the original pawn.
        """
        piece = self.board.get(*juice_box_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Juice Box":
            return False
        if self.is_piece_suppressed(*juice_box_pos):
            return False

        # Check if Juice Box used ability this turn (captured someone)
        if juice_box_pos in self.juice_box_used_this_turn:
            return False
        # Chunk 4 balance: one acquired-ability use per side per turn cycle.
        if self.juice_box_cooldown.get(piece.color):
            return False

        pawn_char = self.find_captured_ability(juice_box_pos, ability_name)
        if pawn_char is None:
            return False

        name = pawn_char.name
        success = False

        # Chunk 4 balance: an acquired ability costs Juice Box 1 more than the
        # original pawn's base cost. Bump the shared floor modifier for just this
        # delegated call so every spend_die / combine check inside the underlying
        # try_* runs against floor + 1 (stacks additively with AI-Card / Group
        # Climax modifiers, exactly like the server's own checks).
        dice.floor_modifier += 1
        events_before = len(self.events)
        try:
            if name == "Zev":
                success = self.try_biggest_fan(juice_box_pos, dice, die_index)
            elif name == "Elle McGib":
                success = self.try_frozen(juice_box_pos, dice, die_index, target_pos=target_pos)
            elif name == "Imani":
                success = self.try_suppress(juice_box_pos, dice, die_index)
            elif name == "Candy Biggs":
                success = self.try_gang_gang(juice_box_pos, dice, target_pos=target_pos)
            elif name == "Louie":
                success = self.try_air_strike(juice_box_pos, dice, die_index, target_pos=target_pos)
            elif name == "Sledge":
                success = self.try_body_guard(juice_box_pos, dice, die_index)
            elif name == "Stripper Anaconda":
                success = self.try_gun_show(juice_box_pos, dice, die_index, target_pos=target_pos)
            elif name == "Quasar":
                # Mediation is a passive defense (see attempt_capture) that triggers
                # automatically when Juice Box herself is about to be captured --
                # it has no manual, die-spend trigger to fire here.
                success = False
            elif name == "Lucia Mar":
                success = self.try_sic_em(juice_box_pos, dice, die_index)
            elif name == "Chris":
                success = self.try_lava_surge_chunk2(juice_box_pos, dice, die_index, direction=direction)
            elif name == "Florin":
                success = self.try_suppressing_fire(juice_box_pos, dice, die_index)
            elif name == "Signet":
                success = self.try_succubus(juice_box_pos, dice, die_index, target_pos=target_pos)
            elif name == "Miriam Dom":
                success = self.try_blood_magic(juice_box_pos, dice, target_pos=target_pos)
            elif name == "Raul the Crab":
                success = self.try_group_climax(juice_box_pos, dice)
            elif name == "Bad Llama":
                success = self.try_lava_spit_chunk2(juice_box_pos, dice, die_index, target_pos=target_pos)
            elif name == "Prepotente":
                result = self.try_special_boy(juice_box_pos, dice, die_index)
                if result:
                    if target_pos is not None and tuple(target_pos) in result:
                        dest = tuple(target_pos)
                    else:
                        dest = random.choice(result)
                    self.apply_ability_move(juice_box_pos, dest)
                    success = True
            elif name == "Ren":
                # Indestructible is passive and has no active effect to fire.
                success = False
        finally:
            dice.floor_modifier -= 1

        # The delegated try_* logs its ability_roll under the source pawn's
        # name (e.g. "Lucia Mar") -- credit Juice Box in the battle log instead.
        for event in self.events[events_before:]:
            if event.get("type") == "ability_roll":
                event["piece"] = f"Juice Box ({name})"

        if success:
            # Chunk 4 balance: block another acquired-ability use until the start
            # of this side's next turn (see start_turn()).
            self.juice_box_cooldown[piece.color] = True
            self.log_event("juice_box_use_ability", pos=juice_box_pos,
                           ability=ability_name, pawn=name)
        return success

    # ── Chunk 2 Abilities: Priority Group 5 (Complex Major Piece Abilities) ──

    # Major piece types Leader can pull toward Carl. Mongo is excluded --
    # his Knight movement has no "straight line toward Carl" concept, unlike
    # Donut (queen), Katia (bishop), and Samantha (rook).
    LEADER_ELIGIBLE_TYPES = {PieceType.DONUT, PieceType.KATIA, PieceType.SAMANTHA}

    def leader_available_total(self, dice: DungeonDice, player: str) -> int:
        """Non-destructive preview of the combined dice total available for Leader
        this turn: both rolled dice if no banked die exists, or the banked die
        plus whatever single die was rolled this turn if one does. Returns 0 if
        the requirement isn't met (doesn't spend anything).
        """
        available_indices = [i for i in range(len(dice.dice)) if not dice.used[i]]
        rolled_sum = sum(dice.dice[i] for i in available_indices)
        banked = dice.banked_die.get(player)
        if banked is not None:
            if len(available_indices) < 1:
                return 0
            return banked + rolled_sum
        if len(available_indices) < 2:
            return 0
        return rolled_sum

    def leader_eligible_pieces(self, color: Color) -> List[Tuple[int, int]]:
        """Friendly Donut/Katia/Samantha positions Leader could target."""
        return [
            (r, c) for r, c, p in self.board.all_pieces(color)
            if p.piece_type in self.LEADER_ELIGIBLE_TYPES
        ]

    def leader_pull_destinations(self, piece_pos: Tuple[int, int], carl_pos: Tuple[int, int],
                                  max_distance: int) -> List[Tuple[int, int]]:
        """Valid destinations for pulling the piece at `piece_pos` toward `carl_pos`,
        up to `max_distance` squares, respecting that piece's own movement rules
        (diagonal only for Katia, orthogonal only for Samantha, either for Donut)
        and board obstruction. The piece can never land on or pass through any
        occupied square, can never land on Carl's own square, and can't be
        pulled anywhere that leaves its Carl in check.
        """
        piece = self.board.get(*piece_pos)
        if piece is None or max_distance <= 0:
            return []

        pr, pc = piece_pos
        cr, cc = carl_pos
        dr, dc = cr - pr, cc - pc
        if dr == 0 and dc == 0:
            return []

        is_diagonal = dr != 0 and dc != 0 and abs(dr) == abs(dc)
        is_orthogonal = (dr == 0) != (dc == 0)

        if piece.piece_type == PieceType.DONUT:
            allowed = is_diagonal or is_orthogonal
        elif piece.piece_type == PieceType.KATIA:
            allowed = is_diagonal
        elif piece.piece_type == PieceType.SAMANTHA:
            allowed = is_orthogonal
        else:
            allowed = False
        if not allowed:
            return []

        step_r = (dr > 0) - (dr < 0)
        step_c = (dc > 0) - (dc < 0)
        distance_to_carl = max(abs(dr), abs(dc))

        destinations = []
        for dist in range(1, min(max_distance, distance_to_carl - 1) + 1):
            nr, nc = pr + step_r * dist, pc + step_c * dist
            if not self.board.in_bounds(nr, nc):
                break
            if self.is_square_blocked(nr, nc):
                break
            if self.board.get(nr, nc) is not None:
                break
            if self.leaves_carl_in_check(piece.color, moves=[(piece_pos, (nr, nc))]):
                continue
            destinations.append((nr, nc))
        return destinations

    def try_leader(self, carl_pos: Tuple[int, int], dice: DungeonDice,
                   player: str) -> Optional[int]:
        """Carl's Leader (no fixed cost, twice per game): combine all available
        dice (both rolled dice, or the banked die plus the rolled die) into a
        pull distance for one friendly back-line major piece. Consumes all
        available dice (and the bank, if used) as part of activation. Returns
        the combined total on success, or None if unavailable.
        """
        piece = self.board.get(*carl_pos)
        if piece is None or piece.piece_type != PieceType.CARL:
            return None
        if self.is_piece_suppressed(*carl_pos):
            return None
        if self.leader_uses.get(piece.color, 2) <= 0:
            return None

        total = self.leader_available_total(dice, player)
        if total <= 0:
            return None

        available_indices = [i for i in range(len(dice.dice)) if not dice.used[i]]
        if dice.banked_die.get(player) is not None:
            dice.banked_die[player] = None
        for i in available_indices:
            dice.used[i] = True

        self.leader_uses[piece.color] = self.leader_uses.get(piece.color, 2) - 1
        self.log_event("ability_roll", piece="Carl", ability="Leader",
                       detail=f"Combined total {total}", result="success")
        return total

    def puddle_jump_destinations(self, donut_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Pure computation of Donut's legal Puddle Jump destinations: unlimited
        distance in any Queen direction, hopping harmlessly over every piece
        (friendly or enemy) in the path. Only a completely empty square is a
        valid destination -- Puddle Jump can never land on or affect an
        occupied square -- and never one that leaves her Carl in check.
        """
        piece = self.board.get(*donut_pos)
        if piece is None or piece.piece_type != PieceType.DONUT:
            return []

        r, c = donut_pos
        directions = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
        destinations = []
        for dr, dc in directions:
            for distance in range(1, BOARD_SIZE):
                nr, nc = r + dr * distance, c + dc * distance
                if not self.board.in_bounds(nr, nc):
                    break
                if self.is_square_blocked(nr, nc):
                    break
                if (self.board.get(nr, nc) is None
                        and not self.leaves_carl_in_check(piece.color, moves=[(donut_pos, (nr, nc))])):
                    destinations.append((nr, nc))
                # An occupied square (friendly or enemy) is ignored entirely --
                # Puddle Jump never touches pieces in its path, so scanning
                # continues past it instead of stopping on it or capturing it.
        return destinations

    def try_puddle_jump(self, donut_pos: Tuple[int, int], dice: DungeonDice,
                        target_square: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        """Donut's Puddle Jump (Cost 7, requires combined dice, 10-turn cooldown):
        hop unlimited squares in any Queen direction, passing harmlessly over
        every piece along the way, to land on a completely empty square.
        Never captures. Returns the destination on success, or None if the
        attempt was never valid (nothing is spent in that case).
        """
        # Hard check first: an occupied destination is never valid, no matter
        # what else is true -- this is what makes it impossible for Puddle
        # Jump to ever capture Carl (or anything else), even if the
        # reachable-squares computation above were ever wrong.
        if self.board.get(*target_square) is not None:
            return None

        piece = self.board.get(*donut_pos)
        if piece is None or piece.piece_type != PieceType.DONUT:
            return None
        if self.is_piece_suppressed(*donut_pos):
            return None
        if self.puddle_jump_cooldown > 0:
            return None
        if target_square not in self.puddle_jump_destinations(donut_pos):
            return None
        if not dice.can_combine_for_cost(7):
            return None

        dice.spend_combined(7)
        self.puddle_jump_cooldown = 10
        self.log_event("ability_roll", piece="Donut", ability="Puddle Jump",
                       detail="Combined dice for cost 7", result="success")

        self.board.set(donut_pos[0], donut_pos[1], None)
        self.board.set(target_square[0], target_square[1], piece)
        self.log_event("puddle_jump", from_pos=donut_pos, to_pos=target_square)
        return target_square

    def _find_donut(self, color: Color) -> Optional[Tuple[int, int]]:
        """Where `color`'s Donut is on the board, or None."""
        for r, c, p in self.board.all_pieces(color):
            if p.piece_type == PieceType.DONUT:
                return (r, c)
        return None

    def pet_carrier_store_blocker(self, mongo_pos: Tuple[int, int]) -> Optional[str]:
        """Why the Mongo on mongo_pos can't be stored right now, or None if he can.
        Storing needs his side's Donut on the board (she's where he's released),
        no other Mongo of his side already stored, and his Carl staying out of
        check once he's off the board."""
        piece = self.board.get(*mongo_pos)
        if piece is None or piece.piece_type != PieceType.MONGO:
            return "Not a Mongo"
        if self._find_donut(piece.color) is None:
            return "Needs Donut on the board"
        if self.stored_mongo.get(piece.color) is not None:
            return "A Mongo is already stored"
        if self.leaves_carl_in_check(piece.color, removals=[mongo_pos]):
            return "Would expose Carl"
        return None

    def try_pet_carrier(self, mongo_pos: Tuple[int, int], dice: DungeonDice,
                        die_index: int) -> bool:
        """Mongo's Pet Carrier (Floor 4): store Mongo off the board. Releasing
        him later is free and separate (see try_release_mongo). Nothing is
        spent if he can't be stored (see pet_carrier_store_blocker)."""
        piece = self.board.get(*mongo_pos)
        if piece is None or piece.piece_type != PieceType.MONGO:
            return False
        if self.is_piece_suppressed(*mongo_pos):
            return False
        if self.pet_carrier_store_blocker(mongo_pos) is not None:
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Mongo", ability="Pet Carrier",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        self.board.set(*mongo_pos, None)
        self.stored_mongo[piece.color] = {"piece": piece, "turn": self.turn_number}
        self.log_event("pet_carrier_store", piece=repr(piece), pos=list(mongo_pos),
                       detail="Mongo stored")
        return True

    def mongo_release_squares(self, color: Color) -> List[Tuple[int, int]]:
        """Where `color`'s stored Mongo can be released right now: any square
        within 2 of Donut that's empty, not in a blocked zone, not a boss
        square, and doesn't leave his Carl in check. Empty if nothing is
        stored, he went in this same turn, or there's no Donut."""
        entry = self.stored_mongo.get(color)
        if entry is None or entry["turn"] == self.turn_number:
            return []
        donut_pos = self._find_donut(color)
        if donut_pos is None:
            return []
        mongo = entry["piece"]
        boss_squares = set(self.boss_squares)
        dr, dc = donut_pos
        squares = []
        for r in range(dr - 2, dr + 3):
            for c in range(dc - 2, dc + 3):
                if (not self.board.in_bounds(r, c) or self.board.get(r, c) is not None
                        or self.is_square_blocked(r, c) or (r, c) in boss_squares):
                    continue
                if self.leaves_carl_in_check(color, placements=[((r, c), mongo)]):
                    continue
                squares.append((r, c))
        return squares

    def try_release_mongo(self, color: Color, pos: Tuple[int, int]) -> bool:
        """Release `color`'s stored Mongo onto pos (one of mongo_release_squares).
        Free: no dice, not the turn's ability, not its move. He can't move or
        capture for the rest of this turn."""
        pos = tuple(pos)
        if pos not in self.mongo_release_squares(color):
            return False
        mongo = self.stored_mongo[color]["piece"]
        self.stored_mongo[color] = None
        self.board.set(pos[0], pos[1], mongo)
        self.mongo_released_this_turn.add(pos)
        self.log_event("pet_carrier_release", piece=repr(mongo), pos=list(pos),
                       detail="Mongo released")
        return True

    def drop_stored_mongos_without_donut(self):
        """A stored Mongo goes to the graveyard, like a normal capture, as soon
        as his side's Donut is off the board -- however she left it."""
        for color, entry in self.stored_mongo.items():
            if entry is not None and self._find_donut(color) is None:
                self.stored_mongo[color] = None
                self.board.captured[color].append(entry["piece"])
                self.log_event("pet_carrier_lost", piece=repr(entry["piece"]),
                               detail="Donut left the board, so the stored Mongo is captured too")

    def try_blitzed(self, katia_pos: Tuple[int, int], dice: DungeonDice,
                    die_index: int) -> bool:
        """Katia's Blitzed (Floor 5): One friendly piece skips movement requirement."""
        piece = self.board.get(*katia_pos)
        if piece is None or piece.piece_type != PieceType.KATIA:
            return False
        if self.is_piece_suppressed(*katia_pos):
            return False

        success = dice.spend_die(die_index, 5)
        self.log_event("ability_roll", piece="Katia", ability="Blitzed",
                       die_value=dice.dice[die_index], floor=5, result="success" if success else "fail")
        if not success:
            return False

        # Find all friendly pieces
        friendly_pieces = []
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                p = self.board.get(row, col)
                if p and p.color == piece.color:
                    friendly_pieces.append((row, col))
        
        if not friendly_pieces:
            return False
        
        # Pick random friendly piece to blitz
        target_pos = random.choice(friendly_pieces)
        self.blitzed_pieces.add(target_pos)
        self.log_event("blitzed", target=repr(self.board.get(*target_pos)), target_pos=target_pos,
                       detail="Can skip movement this turn")
        return True

    def try_miss_me(self, samantha_pos: Tuple[int, int], dice: DungeonDice,
                    die_index: int, is_reaction: bool = False) -> Optional[List[int]]:
        """Samantha's Miss Me (Floor 5): Reroll dice currently in play.
        Can be used on own turn or as reaction with banked die.
        """
        piece = self.board.get(*samantha_pos)
        if piece is None or piece.piece_type != PieceType.SAMANTHA:
            return None
        if self.is_piece_suppressed(*samantha_pos):
            return None

        if is_reaction:
            # Using banked die as reaction
            if not dice.has_banked_die():
                return None
            # Spend banked die
            dice.pull_from_bank()
            success = dice.dice[die_index] >= 5  # Check if pulled die meets floor
            if not success:
                return None
        else:
            # Normal use on own turn
            success = dice.spend_die(die_index, 5)
            if not success:
                return None

        self.log_event("ability_roll", piece="Samantha", ability="Miss Me",
                       die_value=dice.dice[die_index], floor=5, result="success" if success else "fail",
                       is_reaction=is_reaction)

        # Reroll all available dice
        new_values = []
        for i in range(len(dice.dice)):
            if not dice.used[i]:
                new_val = dice.reroll_die(i)
                new_values.append(new_val)
        
        self.log_event("miss_me_reroll", new_values=new_values, detail="Dice rerolled")
        return new_values if new_values else None

    # ── Chunk 2 Abilities: Priority Group 6 (Reaction Abilities) ──

    def _mediation_rolloff(self, ai_card_color: Color,
                           dice: Optional[DungeonDice] = None) -> Tuple[bool, int, int]:
        """Resolve a Quasar Mediation roll-off. Both sides roll BOTH of their
        dice and add them together (a total of 2-12 each). The defender only
        saves the threatened piece by winning by a margin of 2 or more -- a tie,
        or the defender leading by exactly 1, goes to the attacker.

        The attacker's own two d6 are still fed to the AI-summon-pattern check,
        exactly as any other roll would be. Returns (defender_saved, attacker_total,
        defender_total).
        """
        atk = (random.randint(1, 6), random.randint(1, 6))
        dfn = (random.randint(1, 6), random.randint(1, 6))
        atk_total, dfn_total = atk[0] + atk[1], dfn[0] + dfn[1]
        self.log_event("mediation_rolloff",
                       attacker_dice=list(atk), defender_dice=list(dfn),
                       attacker_total=atk_total, defender_total=dfn_total)
        self.draw_ai_card_if_triggered(atk[0], atk[1], ai_card_color, dice=dice)
        return (dfn_total - atk_total) >= 2, atk_total, dfn_total

    def try_mediation_chunk2(self, quasar_pos: Tuple[int, int], dice: DungeonDice,
                             defender_pos: Tuple[int, int]) -> Optional[str]:
        """Quasar's Mediation (cost 6, twice per game, reaction): when a friendly
        piece *other than Carl* is about to be captured, spend a banked die
        (value >= 6) to declare Mediation. Both players roll both of their dice
        and sum them (2-12); the defender must win by 2 or more to save the
        threatened piece -- a tie or a 1-point defender lead goes to the attacker.

        Cannot be declared while the defending side's Carl is in check, and can
        never be used to defend Carl himself.

        Returns "defender_wins", "attacker_wins", or None if Mediation could not
        be declared.
        """
        piece = self.board.get(*quasar_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Quasar":
            return None

        defender = self.board.get(*defender_pos)
        if defender is None:
            return None
        # Mediation can never protect Carl himself.
        if defender.is_king:
            return None
        # Cannot be declared while the defending side's Carl is in check.
        if is_in_check(self.board, defender.color):
            return None
        # Cannot rescue a piece that is itself currently checking the enemy Carl
        # -- saving it would just let it capture Carl on the next move.
        if self._piece_is_checking_opponent_carl(defender_pos, defender):
            return None

        # Check uses remaining
        pawn_key = f"{piece.color.value}_Quasar"
        uses_left = self.pawn_ability_uses.get(pawn_key, {}).get("Mediation", 2)
        if uses_left <= 0:
            return None

        # Must have a banked die worth at least the cost (6)
        player = piece.color.value
        pulled_value = dice.banked_die.get(player)
        if pulled_value is None or pulled_value < 6:
            return None
        dice.pull_from_bank(player)  # consume the banked die

        # Decrement uses
        if pawn_key not in self.pawn_ability_uses:
            self.pawn_ability_uses[pawn_key] = {}
        self.pawn_ability_uses[pawn_key]["Mediation"] = uses_left - 1

        defender_saved, atk_total, dfn_total = self._mediation_rolloff(
            defender.color.opponent, dice=dice)
        self.log_event("ability_reaction", piece="Quasar", ability="Mediation",
                       banked_die_value=pulled_value,
                       attacker_total=atk_total, defender_total=dfn_total,
                       result="success" if defender_saved else "fail")
        if defender_saved:
            self.log_event("mediation_success",
                           detail=f"Defender {dfn_total} beat Attacker {atk_total} by 2+")
            return "defender_wins"
        self.log_event("mediation_fail",
                       detail=f"Attacker {atk_total} vs Defender {dfn_total} -- attacker wins")
        return "attacker_wins"

    def try_she_tank(self, katia_pos: Tuple[int, int], dice: DungeonDice,
                     target_pos: Tuple[int, int], is_reaction: bool = False) -> bool:
        """Katia's She Tank (Floor 6, twice per game, reaction):
        Prevent one enemy piece from moving on its next turn.
        Can be used as reaction with banked die or on own turn.
        """
        piece = self.board.get(*katia_pos)
        if piece is None or piece.piece_type != PieceType.KATIA:
            return False
        if self.is_piece_suppressed(*katia_pos):
            return False
        
        # Check uses remaining
        uses_left = self.she_tank_uses.get(piece.color, 2)
        if uses_left <= 0:
            return False
        
        if is_reaction:
            # Using banked die as reaction
            if not dice.has_banked_die():
                return False
            pulled_value = dice.pull_from_bank()
            if pulled_value < 6:
                return False
            self.log_event("ability_reaction", piece="Katia", ability="She Tank",
                          banked_die_value=pulled_value, target_pos=target_pos)
        else:
            # Normal use on own turn - need a die meeting cost 6 after this
            # turn's floor modifier (AI's Pet / Dirty Tootsies / Group Climax)
            die_index = -1
            for i in range(len(dice.dice)):
                if not dice.used[i] and dice.dice[i] >= dice._effective_floor(6):
                    die_index = i
                    break
            if die_index == -1:
                return False
            
            success = dice.spend_die(die_index, 6)
            if not success:
                return False
            
            self.log_event("ability_roll", piece="Katia", ability="She Tank",
                          die_value=dice.dice[die_index], floor=6, result="success",
                          target_pos=target_pos)
        
        # Verify target is enemy piece
        target = self.board.get(*target_pos)
        if not target or target.color == piece.color:
            return False
        
        # Decrement uses
        self.she_tank_uses[piece.color] = uses_left - 1
        
        # Add target to pending (will activate next turn)
        self.she_tank_pending.add(target_pos)
        
        self.log_event("she_tank", target=repr(target), target_pos=target_pos,
                      detail="Target cannot move next turn", is_reaction=is_reaction)
        return True

    def plot_armor_destinations(self, carl_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Pure computation of Carl's legal Plot Armor destinations (no dice or
        uses are spent). Up to 3 squares in any King direction; cannot pass
        through occupied squares; can capture on landing (except the enemy
        King, which -- as in standard chess -- is never a valid capture
        target); the destination must not leave Carl in check.
        """
        piece = self.board.get(*carl_pos)
        if piece is None or piece.piece_type != PieceType.CARL:
            return []

        r, c = carl_pos
        directions = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        destinations = []
        for dr, dc in directions:
            for dist in range(1, 4):
                nr, nc = r + dr * dist, c + dc * dist
                if not self.board.in_bounds(nr, nc):
                    break
                if self.is_square_blocked(nr, nc):
                    break
                target = self.board.get(nr, nc)
                if target is not None and (target.color == piece.color or target.is_king):
                    break  # friendly pieces and the enemy King both fully block

                old_en_passant = self.board.en_passant_target
                old_has_moved = piece.has_moved
                captured = self.board.make_move(carl_pos, (nr, nc))
                still_in_check = is_in_check(self.board, piece.color)
                self.board.undo_move(carl_pos, (nr, nc), captured, False,
                                      old_en_passant, old_has_moved, False, None)
                if not still_in_check:
                    destinations.append((nr, nc))

                if target is not None:
                    break  # captured an enemy piece here -- can't travel further
        return destinations

    def try_plot_armor(self, carl_pos: Tuple[int, int], dice: DungeonDice) -> Optional[List[Tuple[int, int]]]:
        """Carl's Plot Armor (Cost 8, requires combined dice, once per game):
        an emergency escape move up to 3 squares in any King direction. Returns
        the list of legal destinations on success, or None if unavailable.
        """
        piece = self.board.get(*carl_pos)
        if piece is None or piece.piece_type != PieceType.CARL:
            return None
        if self.is_piece_suppressed(*carl_pos):
            return None
        if self.plot_armor_used.get(piece.color, False):
            return None
        if not dice.can_combine_for_cost(8):
            return None

        dice.spend_combined(8)
        self.plot_armor_used[piece.color] = True
        self.log_event("ability_roll", piece="Carl", ability="Plot Armor",
                       detail="Combined dice for cost 8", result="success")

        destinations = self.plot_armor_destinations(carl_pos)
        return destinations if destinations else None

    # ── Chunk 2 Abilities: Priority Group 7 (Combined Dice Abilities) ──

    def cockroach_candidates(self, color: Color) -> Tuple[List[Piece], List[Piece]]:
        """(graveyard list, resurrectable pieces) for Cockroach.

        Reads board.captured -- the real graveyard, same as Blood Magic (see
        blood_magic_candidates). Any friendly piece is eligible except Orthrus,
        permanently-dead pieces, and a Mordecai who is already back on the
        board or still awaiting his own Manager Benefit respawn (reviving him
        then would put the same piece on the board twice).
        """
        source = self.board.captured[color]
        on_board = {id(p) for _, _, p in self.board.all_pieces(color)}
        pending_respawn = {id(entry["piece"]) for entry in self.mordecai_respawn_pending}
        candidates = [p for p in source
                      if not p.permanently_dead
                      and not (p.is_pawn and p.pawn_name == "Orthrus")
                      and id(p) not in on_board
                      and id(p) not in pending_respawn]
        return source, candidates

    def cockroach_spawn_squares(self, donut_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Open, unblocked squares adjacent to Donut where Cockroach can place a piece."""
        r, c = donut_pos
        adjacent = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc) and not self.is_square_blocked(nr, nc):
                    if self.board.get(nr, nc) is None:
                        adjacent.append((nr, nc))
        return adjacent

    def try_cockroach(self, donut_pos: Tuple[int, int], dice: DungeonDice,
                      target_pos: Optional[Tuple[int, int]] = None) -> Optional[Piece]:
        """Donut's Cockroach (Floor 7, requires combined, once per game):
        Resurrect one captured friendly piece and place on any open square adjacent to Donut.

        `target_pos`, if given and valid, is the adjacent square to place it on.
        Nothing is spent (and the once-per-game use isn't burned) if there's
        nothing to resurrect or nowhere to put it.
        """
        piece = self.board.get(*donut_pos)
        if piece is None or piece.piece_type != PieceType.DONUT:
            return None
        if self.is_piece_suppressed(*donut_pos):
            return None

        # Check if already used
        if self.resurrection_used.get(piece.color, False):
            return None

        # Requires combined dice (total >= 7)
        if not dice.can_combine_for_cost(7):
            return None

        source, captured = self.cockroach_candidates(piece.color)
        adjacent = self.cockroach_spawn_squares(donut_pos)
        if not captured or not adjacent:
            return None

        dice.spend_combined(7)
        self.log_event("ability_roll", piece="Donut", ability="Cockroach",
                       detail="Combined dice for cost 7", result="success")

        # Mark as used
        self.resurrection_used[piece.color] = True

        # Pick random captured piece to resurrect
        resurrected = random.choice(captured)
        source.remove(resurrected)

        # Use the requested square if valid, otherwise pick randomly
        if target_pos is not None and tuple(target_pos) in adjacent:
            spawn_pos = tuple(target_pos)
        else:
            spawn_pos = random.choice(adjacent)
        self.board.set(spawn_pos[0], spawn_pos[1], resurrected)
        if resurrected.is_pawn and resurrected.pawn_name:
            self._juice_box_lose_ability(resurrected.pawn_name)

        self.log_event("cockroach", piece_resurrected=repr(resurrected), pos=spawn_pos)
        return resurrected

    def rampage_plan(self, mongo_pos: Tuple[int, int]) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
        """(victims, destinations) for Mongo's Rampage: every enemy piece on his
        knight squares that a normal capture could take is captured -- never
        the enemy Carl, and never an invulnerable piece (Ren's Indestructible,
        Body Guard, including Juice Box's copy) -- then he lands on one of
        those squares or an empty one. A destination is only offered if, with
        all the victims gone and Mongo on it, his own Carl isn't in check.
        Quasar's Mediation can still save a victim when the Rampage happens
        (see try_rampage); the picker can't know that in advance.
        """
        piece = self.board.get(*mongo_pos)
        if piece is None:
            return [], []
        r, c = mongo_pos
        squares = []
        victims = []
        for dr, dc in [(2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2)]:
            nr, nc = r + dr, c + dc
            if not self.board.in_bounds(nr, nc) or self.is_square_blocked(nr, nc):
                continue
            target = self.board.get(nr, nc)
            if target is None:
                squares.append((nr, nc))
            elif (target.color != piece.color and not target.is_king
                    and not self.is_piece_invulnerable(nr, nc)):
                # The enemy Carl is never a valid Rampage target -- as in
                # standard chess, Carl is never directly capturable (same
                # rule as plot_armor_destinations's target.is_king check).
                # Ren / Body Guard pieces are skipped like any normal capture
                # would skip them (and he can't land on their squares).
                squares.append((nr, nc))
                victims.append((nr, nc))
        destinations = [sq for sq in squares
                        if not self.leaves_carl_in_check(piece.color, removals=victims,
                                                         moves=[(mongo_pos, sq)])]
        return victims, destinations

    def try_rampage(self, mongo_pos: Tuple[int, int], dice: DungeonDice) -> Optional[List[Tuple[int, int]]]:
        """Mongo's Rampage (Floor 8, requires combined, once per game):
        Mongo captures any piece within his L-shaped movement path, not just final destination.

        Returns his legal landing squares (see rampage_plan) -- just his own
        square if a Mediation save left nowhere else safe; the caller moves
        him. Nothing is spent if he'd have nowhere safe to land.
        """
        piece = self.board.get(*mongo_pos)
        if piece is None or piece.piece_type != PieceType.MONGO:
            return None
        if self.is_piece_suppressed(*mongo_pos):
            return None
        # Just released from Pet Carrier: he can't capture this turn.
        if mongo_pos in self.mongo_released_this_turn:
            return None
        
        # Check if already used
        key = (piece.color, id(piece))
        if self.rampaging_charge_used.get(key, False):
            return None
        
        # Requires combined dice (total >= 8)
        if not dice.can_combine_for_cost(8):
            return None

        captured_pieces, valid_moves = self.rampage_plan(mongo_pos)
        if not valid_moves:
            return None
        
        dice.spend_combined(8)
        self.log_event("ability_roll", piece="Mongo", ability="Rampage",
                       detail="Combined dice for cost 8", result="success")
        
        # Mark as used
        self.rampaging_charge_used[key] = True
        
        # Each victim goes through the normal capture rules (attempt_capture):
        # Quasar's Mediation can save it, in which case it's simply skipped --
        # it stays on its square and Mongo isn't hurt. Captured victims go
        # into board.captured (the graveyard Cockroach / Blood Magic resurrect
        # from) and run process_post_capture, the same on-capture effects as a
        # normal capture -- clearing Orthrus's other body square and
        # triggering Mordecai's Manager Benefit.
        for cap_pos in captured_pieces:
            cap_piece = self.board.get(*cap_pos)
            if cap_piece is None:
                continue  # e.g. Orthrus's second square, cleared with his first
            outcome = self.attempt_capture(mongo_pos, cap_pos)
            if outcome != "captured":
                self.log_event("rampage_skip", pos=list(cap_pos), piece=repr(cap_piece),
                               reason=outcome)
                continue
            self.board.set(cap_pos[0], cap_pos[1], None)
            self.board.captured[cap_piece.color].append(cap_piece)
            self.log_event("rampage_capture", pos=cap_pos, piece=repr(cap_piece))
            self.process_post_capture(cap_piece, cap_pos, piece, mongo_pos)

        # Re-check the landing squares against the board as it now is: a saved
        # victim still occupies its square (and may still guard a line to
        # Carl), and a capture can block its own square (Mordecai's ghost
        # token). If nowhere is left, Mongo stays where he is.
        valid_moves = [m for m in valid_moves
                       if self.board.get(*m) is None and not self.is_square_blocked(*m)
                       and not self.leaves_carl_in_check(piece.color, moves=[(mongo_pos, m)])]
        return valid_moves if valid_moves else [mongo_pos]

    def slut_shame_targets(self, samantha_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Enemy pawns within 3 squares of Samantha that Slut Shame can swallow:
        never Orthrus (a 2-square body), and never a pawn whose removal opens a
        line to her own Carl."""
        piece = self.board.get(*samantha_pos)
        if piece is None:
            return []
        r, c = samantha_pos
        targets = []
        for dr in range(-3, 4):
            for dc in range(-3, 4):
                nr, nc = r + dr, c + dc
                if (dr, dc) == (0, 0) or not self.board.in_bounds(nr, nc):
                    continue
                target = self.board.get(nr, nc)
                if (target and target.is_pawn and target.color != piece.color
                        and target.pawn_name != "Orthrus"
                        and not self.leaves_carl_in_check(piece.color, removals=[(nr, nc)])):
                    targets.append((nr, nc))
        return targets

    def try_slut_shame(self, samantha_pos: Tuple[int, int], dice: DungeonDice,
                       target_pos: Optional[Tuple[int, int]] = None) -> bool:
        """Samantha's Slut Shame (Floor 8, requires combined, once per game):
        Swallow any pawn within 3 squares, temporarily removing it. Respawns within 1 square of Samantha within 5 turns.

        `target_pos`, if given, is the pawn to swallow (it must be one of
        slut_shame_targets); otherwise one is picked at random. Nothing is
        spent if there's no valid target.
        """
        piece = self.board.get(*samantha_pos)
        if piece is None or piece.piece_type != PieceType.SAMANTHA:
            return False
        if self.is_piece_suppressed(*samantha_pos):
            return False
        
        # Check if already used
        key = (piece.color, id(piece))
        if self.slut_shame_used.get(key, False):
            return False
        
        # Requires combined dice (total >= 8)
        if not dice.can_combine_for_cost(8):
            return False

        target_pawns = self.slut_shame_targets(samantha_pos)
        if target_pos is not None:
            target_pos = tuple(target_pos)
            if target_pos not in target_pawns:
                return False
        elif target_pawns:
            target_pos = random.choice(target_pawns)
        else:
            return False

        dice.spend_combined(8)
        self.log_event("ability_roll", piece="Samantha", ability="Slut Shame",
                       detail="Combined dice for cost 8", result="success")
        
        # Mark as used
        self.slut_shame_used[key] = True

        swallowed_pawn = self.board.get(*target_pos)
        
        # Remove from board
        self.board.set(target_pos[0], target_pos[1], None)
        
        # Schedule respawn
        self.swallowed_pawns.append({
            "piece": swallowed_pawn,
            "turns_left": 5,
            "samantha_pos": samantha_pos
        })
        
        self.log_event("slut_shame", swallowed=repr(swallowed_pawn), pos=target_pos,
                       detail="Will respawn within 1 square of Samantha in 5 turns")
        return True

    def try_gang_gang(self, caster_pos: Tuple[int, int], dice: DungeonDice,
                      target_pos: Optional[Tuple[int, int]] = None) -> bool:
        """Candy Biggs's Gang Gang! (Floor 10, requires combined):
        Convert enemy pawn within 2 squares to friendly side.
        """
        piece = self.board.get(*caster_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Candy Biggs", "Juice Box"):
            return False
        if self.is_piece_suppressed(*caster_pos):
            return False

        # Requires combined dice (total >= 10)
        if not dice.can_combine_for_cost(10):
            return False

        dice.spend_combined(10)
        self.log_event("ability_roll", piece="Candy Biggs", ability="Gang Gang!",
                       detail="Combined dice for cost 10", result="success")

        # Find enemy pawns within 2 squares
        r, c = caster_pos
        enemy_pawns = []
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    target = self.board.get(nr, nc)
                    if target and target.is_pawn and target.color != piece.color:
                        enemy_pawns.append((nr, nc))

        if not enemy_pawns:
            return False

        # Use the requested target if valid, otherwise pick randomly
        if target_pos is not None and tuple(target_pos) in enemy_pawns:
            target_pos = tuple(target_pos)
        else:
            target_pos = random.choice(enemy_pawns)
        converted_pawn = self.board.get(*target_pos)
        
        # Change color to friendly
        from .pieces import Color
        converted_pawn.color = piece.color
        
        self.log_event("gang_gang", converted=repr(converted_pawn), pos=target_pos,
                       detail="Enemy pawn converted to friendly")
        return True

    def blood_magic_candidates(self, color: Color) -> Tuple[List[Piece], List[Piece]]:
        """(graveyard list, resurrectable pawns) for Blood Magic.

        Reads board.captured -- where every capture lands (and what the
        sidebar graveyard shows). Pawns only, per the ability text; Orthrus
        and permanently-dead pieces are never eligible, nor is a Mordecai who
        is already back on the board or still awaiting his own Manager Benefit
        respawn (same check as cockroach_candidates).
        """
        source = self.board.captured[color]
        on_board = {id(p) for _, _, p in self.board.all_pieces(color)}
        pending_respawn = {id(entry["piece"]) for entry in self.mordecai_respawn_pending}
        candidates = [p for p in source
                      if p.is_pawn and not p.permanently_dead and p.pawn_name != "Orthrus"
                      and id(p) not in on_board
                      and id(p) not in pending_respawn]
        return source, candidates

    def blood_magic_sacrifices(self, miriam_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Adjacent friendly pawns Miriam Dom can sacrifice: never Orthrus (a
        2-square body), and never one whose removal leaves her Carl in check."""
        piece = self.board.get(*miriam_pos)
        if piece is None:
            return []
        r, c = miriam_pos
        sacrifices = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                nr, nc = r + dr, c + dc
                if (dr, dc) == (0, 0) or not self.board.in_bounds(nr, nc):
                    continue
                target = self.board.get(nr, nc)
                if (target and target.is_pawn and target.color == piece.color
                        and target.pawn_name != "Orthrus"
                        and not self.leaves_carl_in_check(piece.color, removals=[(nr, nc)])):
                    sacrifices.append((nr, nc))
        return sacrifices

    def try_blood_magic(self, miriam_pos: Tuple[int, int], dice: DungeonDice,
                        target_pos: Optional[Tuple[int, int]] = None) -> bool:
        """Miriam Dom's Blood Magic (Floor 8, requires combined):
        Sacrifice one adjacent friendly pawn, then resurrect any previously captured friendly pawn on back rank.

        `target_pos`, if given, is the adjacent friendly pawn to sacrifice (one
        of blood_magic_sacrifices); otherwise one is picked at random. Nothing is
        spent unless there's a sacrifice, a pawn to resurrect, and room for it.
        """
        piece = self.board.get(*miriam_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Miriam Dom", "Juice Box"):
            return False
        if self.is_piece_suppressed(*miriam_pos):
            return False

        # Requires combined dice (total >= 8)
        if not dice.can_combine_for_cost(8):
            return False

        sacrifices = self.blood_magic_sacrifices(miriam_pos)
        # Check for captured friendly pawns to resurrect (Orthrus can never be resurrected)
        source, captured = self.blood_magic_candidates(piece.color)
        back_rank = 0 if piece.color == Color.WHITE else (BOARD_SIZE - 1)
        back_rank_squares = [(back_rank, col) for col in range(BOARD_SIZE)
                             if self.board.get(back_rank, col) is None]
        if not sacrifices or not captured or not back_rank_squares:
            return False
        if target_pos is not None:
            sacrifice_pos = tuple(target_pos)
            if sacrifice_pos not in sacrifices:
                return False
        else:
            sacrifice_pos = random.choice(sacrifices)

        dice.spend_combined(8)
        self.log_event("ability_roll", piece="Miriam Dom", ability="Blood Magic",
                       detail="Combined dice for cost 8", result="success")

        # Remove sacrificed pawn without triggering on-capture effects
        sacrificed = self.board.get(*sacrifice_pos)
        self.board.set(sacrifice_pos[0], sacrifice_pos[1], None)
        # Do NOT add to captured_pieces - it's sacrificed, not captured

        # Resurrect a random captured pawn onto a random open back-rank square
        resurrected = random.choice(captured)
        source.remove(resurrected)
        spawn_pos = random.choice(back_rank_squares)
        self.board.set(spawn_pos[0], spawn_pos[1], resurrected)
        if resurrected.is_pawn and resurrected.pawn_name:
            self._juice_box_lose_ability(resurrected.pawn_name)

        self.log_event("blood_magic", sacrificed=repr(sacrificed), sacrificed_pos=sacrifice_pos,
                       resurrected=repr(resurrected), spawn_pos=spawn_pos)
        return True

    def try_group_climax(self, raul_pos: Tuple[int, int], dice: DungeonDice) -> bool:
        """Raul the Crab's Group Climax (Floor 7, requires combined):
        All friendly pieces get -2 to ability costs next turn.
        """
        piece = self.board.get(*raul_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Raul the Crab", "Juice Box"):
            return False
        if self.is_piece_suppressed(*raul_pos):
            return False
        
        # Requires combined dice (total >= 7)
        if not dice.can_combine_for_cost(7):
            return False
        
        dice.spend_combined(7)
        self.log_event("ability_roll", piece="Raul the Crab", ability="Group Climax",
                       detail="Combined dice for cost 7", result="success")
        
        # Set flag for next turn - reduces all friendly piece ability costs by 2
        self.group_climax_pending[piece.color] = True
        
        self.log_event("group_climax", detail="All friendly pieces get -2 to ability costs next turn")
        return True

    # ── Pull Abilities: Gun Show (Stripper Anaconda) / Succubus (Signet) ──

    # ability name -> (source pawn, floor cost, gender it pulls)
    PULL_ABILITIES = {
        "Gun Show": ("Stripper Anaconda", 5, "female"),
        "Succubus": ("Signet", 6, "male"),
    }

    # Every per-piece status keyed by board square. A pulled piece carries
    # these to its new square -- otherwise a pull could, say, free a Frozen
    # piece or let a She Tank target move this turn.
    _PIECE_STATUS_SETS = (
        "suppressed_pieces", "suppressed_pending", "frozen_pieces", "frozen_pending",
        "restrained_pieces", "restrained_pending", "she_tank_targets", "she_tank_pending",
        "blitzed_pieces", "juice_box_used_this_turn", "bad_llama_cant_move",
        "mongo_released_this_turn",
    )
    _PIECE_STATUS_DICTS = (
        "forced_retreat", "forced_retreat_pending", "recruited_pawns",
    )

    def is_piece_female(self, piece: Piece) -> bool:
        """Donut, Katia, and Samantha (FEMALE_MAJOR_PIECE_TYPES) plus the female
        pawns (FEMALE_PAWN_NAMES) are female. Every other piece is male."""
        if piece.is_pawn:
            return piece.pawn_name in FEMALE_PAWN_NAMES
        return piece.piece_type.value in FEMALE_MAJOR_PIECE_TYPES

    @staticmethod
    def pull_square(caster_pos: Tuple[int, int], target_pos: Tuple[int, int]) -> Tuple[int, int]:
        """The square a pull moves the piece at target_pos to: one King step
        toward the caster, 1 square along each axis that still has distance to
        close. That always cuts the King-move distance by 1 (the shortest
        route), and when a straight and a diagonal step would both do so (the
        target is off the caster's row, column, and diagonals) it takes the
        diagonal, which closes the distance most directly.
        """
        tr, tc = target_pos
        cr, cc = caster_pos
        return (tr + (cr > tr) - (cr < tr), tc + (cc > tc) - (cc < tc))

    @staticmethod
    def _promotes_on(piece: Piece, dest: Tuple[int, int]) -> bool:
        """A pawn moved or pulled onto its promotion rank promotes (Orthrus never does)."""
        promotion_rank = BOARD_SIZE - 1 if piece.color == Color.WHITE else 0
        return piece.is_pawn and piece.pawn_name != "Orthrus" and dest[0] == promotion_rank

    def _pull_exposes_carl(self, color: Color, src: Tuple[int, int], dest: Tuple[int, int]) -> bool:
        """True if pulling the piece on src to dest leaves `color`'s Carl in check."""
        if self.board.find_king(color) is None:
            return False  # boss co-op fallen player -- no Carl to protect
        piece = self.board.get(*src)
        landed = Piece(PieceType.DUNGEON_BOSS, piece.color) if self._promotes_on(piece, dest) else piece
        self.board.set(src[0], src[1], None)
        self.board.set(dest[0], dest[1], landed)
        try:
            return is_in_check(self.board, color)
        finally:
            self.board.set(dest[0], dest[1], None)
            self.board.set(src[0], src[1], piece)

    def pull_targets(self, caster_pos: Tuple[int, int],
                     ability_name: str) -> Dict[Tuple[int, int], Tuple[int, int]]:
        """Every piece the caster on caster_pos can pull with ability_name
        ("Gun Show" or "Succubus"), mapped to the square it would land on.

        Either color, anywhere on the board, of the ability's gender. Never:
        Carl, Orthrus (2-square body), an immovable piece (Body Guard, Lava
        Surge's stuck Chris, stuck pieces), a piece already adjacent to the
        caster, a piece whose pull square is occupied, blocked by a zone, or a
        boss square, or a pull that leaves the caster's own Carl in check.
        """
        caster = self.board.get(*caster_pos)
        if caster is None or ability_name not in self.PULL_ABILITIES:
            return {}
        wants_female = self.PULL_ABILITIES[ability_name][2] == "female"
        boss_squares = set(self.boss_squares)
        cr, cc = caster_pos

        targets = {}
        for color in (Color.WHITE, Color.BLACK):
            for r, c, piece in self.board.all_pieces(color):
                if max(abs(r - cr), abs(c - cc)) <= 1:
                    continue  # the caster itself, or already adjacent
                if piece.is_king or piece.pawn_name == "Orthrus":
                    continue
                if self.is_piece_female(piece) != wants_female:
                    continue
                if ((r, c) in self.iron_wall_pieces or (r, c) in self.stuck_pieces
                        or (r, c) in self.chris_stuck):
                    continue
                dest = self.pull_square(caster_pos, (r, c))
                if (self.board.get(*dest) is not None or self.is_square_blocked(*dest)
                        or dest in boss_squares):
                    continue
                if self._pull_exposes_carl(caster.color, (r, c), dest):
                    continue
                targets[(r, c)] = dest
        return targets

    def _relocate_piece_status(self, old: Tuple[int, int], new: Tuple[int, int]):
        """Move every square-keyed per-piece status from old to new."""
        for name in self._PIECE_STATUS_SETS:
            statuses = getattr(self, name)
            if old in statuses:
                statuses.discard(old)
                statuses.add(new)
        for name in self._PIECE_STATUS_DICTS:
            statuses = getattr(self, name)
            if old in statuses:
                statuses[new] = statuses.pop(old)

    def _try_pull(self, caster_pos: Tuple[int, int], dice: DungeonDice, die_index: int,
                  ability_name: str, target_pos: Optional[Tuple[int, int]] = None) -> bool:
        """Shared Gun Show / Succubus implementation (also Juice Box's copies).

        `target_pos` is the piece to pull; a random valid target is used if it's
        omitted. If there's no valid target, or the requested one isn't valid,
        nothing is spent and this returns False.
        """
        source_pawn, floor, _gender = self.PULL_ABILITIES[ability_name]
        caster = self.board.get(*caster_pos)
        if caster is None or not caster.is_pawn or caster.pawn_name not in (source_pawn, "Juice Box"):
            return False
        if self.is_piece_suppressed(*caster_pos):
            return False

        targets = self.pull_targets(caster_pos, ability_name)
        if target_pos is None and targets:
            target_pos = random.choice(list(targets))
        if target_pos is None or tuple(target_pos) not in targets:
            return False
        target_pos = tuple(target_pos)

        success = dice.spend_die(die_index, floor)
        self.log_event("ability_roll", piece=source_pawn, ability=ability_name,
                       die_value=dice.dice[die_index], floor=floor,
                       result="success" if success else "fail")
        if not success:
            return False

        dest = targets[target_pos]
        target = self.board.get(*target_pos)
        self.board.set(target_pos[0], target_pos[1], None)
        self.board.set(dest[0], dest[1], target)
        target.has_moved = True
        self._relocate_piece_status(target_pos, dest)
        if self._promotes_on(target, dest):
            self.board._promote_pawn(dest[0], dest[1], target)

        caster_label = source_pawn if caster.pawn_name == source_pawn else f"Juice Box ({source_pawn})"
        self.log_event("pull", piece=caster_label, ability=ability_name, target=repr(target),
                       from_pos=list(target_pos), to_pos=list(dest))
        return True

    def try_gun_show(self, anaconda_pos: Tuple[int, int], dice: DungeonDice,
                     die_index: int, target_pos: Optional[Tuple[int, int]] = None) -> bool:
        """Stripper Anaconda's Gun Show (Floor 5): pull any one female piece,
        friendly or enemy, 1 square closer to Anaconda by the shortest route.
        Donut always counts as female.
        """
        return self._try_pull(anaconda_pos, dice, die_index, "Gun Show", target_pos)

    def try_succubus(self, signet_pos: Tuple[int, int], dice: DungeonDice,
                     die_index: int, target_pos: Optional[Tuple[int, int]] = None) -> bool:
        """Signet's Succubus (Floor 6): pull any one male piece, friendly or
        enemy, 1 square closer to Signet by the shortest route. Carl can never
        be targeted.
        """
        return self._try_pull(signet_pos, dice, die_index, "Succubus", target_pos)

    # ── Special Event Attacks (Part 3 Stage B, boss battles only) ───

    def try_jug_o_boom(self, carl_pos: Tuple[int, int], dice: DungeonDice, die_index: int,
                       target_pos: Tuple[int, int]) -> Optional[bool]:
        """Carl's Jug-o-Boom (Cost 4): bomb any square within 3 of Carl. Hits if
        a boss square is the target or adjacent to it. Returns True/False (hit/
        miss) once the die is spent, or None if the attempt was never valid.
        """
        piece = self.board.get(*carl_pos)
        if piece is None or piece.piece_type != PieceType.CARL:
            return None
        if self.is_piece_suppressed(*carl_pos):
            return None
        if not self.boss_active:
            return None
        r, c = carl_pos
        tr, tc = target_pos
        if max(abs(tr - r), abs(tc - c)) > 3:
            return None

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Carl", ability="Jug-o-Boom",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return None

        hit = self._boss_square_near(target_pos, radius=1)
        if hit:
            self.damage_boss(1)
        self.log_event("jug_o_boom", target=list(target_pos), hit=hit)
        return hit

    def try_magic_missile(self, donut_pos: Tuple[int, int], dice: DungeonDice, die_index: int,
                          target_pos: Tuple[int, int]) -> Optional[bool]:
        """Donut's Magic Missile (Cost 5): fire in a straight line up to 5 squares.
        Hits if any boss square lies on the path from Donut to the target.
        """
        piece = self.board.get(*donut_pos)
        if piece is None or piece.piece_type != PieceType.DONUT:
            return None
        if self.is_piece_suppressed(*donut_pos):
            return None
        if not self.boss_active:
            return None

        path = self._line_path(donut_pos, target_pos, max_distance=5)
        if path is None:
            return None

        success = dice.spend_die(die_index, 5)
        self.log_event("ability_roll", piece="Donut", ability="Magic Missile",
                       die_value=dice.dice[die_index], floor=5, result="success" if success else "fail")
        if not success:
            return None

        boss_squares = set(self.boss_squares)
        hit = any(sq in boss_squares for sq in path)
        if hit:
            self.damage_boss(1)
        self.log_event("magic_missile", target=list(target_pos),
                       path=[list(p) for p in path], hit=hit)
        return hit

    def try_gorefest(self, mongo_pos: Tuple[int, int], dice: DungeonDice, die_index: int,
                     target_pos: Tuple[int, int]) -> Optional[bool]:
        """Mongo's Gorefest (Cost 4): attack any square within 2 of Mongo. Hits
        if that exact square is currently occupied by the boss.
        """
        piece = self.board.get(*mongo_pos)
        if piece is None or piece.piece_type != PieceType.MONGO:
            return None
        if self.is_piece_suppressed(*mongo_pos):
            return None
        if not self.boss_active:
            return None
        r, c = mongo_pos
        tr, tc = target_pos
        if max(abs(tr - r), abs(tc - c)) > 2:
            return None

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Mongo", ability="Gorefest",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return None

        hit = tuple(target_pos) in self.boss_squares
        if hit:
            self.damage_boss(1)
        self.log_event("gorefest", target=list(target_pos), hit=hit)
        return hit

    def try_i_need_my_space(self, katia_pos: Tuple[int, int], dice: DungeonDice,
                            die_index: int) -> Optional[Dict]:
        """Katia's I Need My Space (Cost 3): push the boss 2 squares directly
        away from Katia (stopping early at the board edge). Breaks Samantha's
        IWKYM hold if active, leaving her in place. No targeting -- fires
        immediately. Returns the push summary dict, or None if unavailable.
        """
        piece = self.board.get(*katia_pos)
        if piece is None or piece.piece_type != PieceType.KATIA:
            return None
        if self.is_piece_suppressed(*katia_pos):
            return None
        if not self.boss_active or self.boss_position is None:
            return None

        kr, kc = katia_pos
        br, bc = self.boss_position
        dr = (br - kr > 0) - (br - kr < 0)
        dc = (bc - kc > 0) - (bc - kc < 0)
        if dr == 0 and dc == 0:
            return None

        success = dice.spend_die(die_index, 3)
        self.log_event("ability_roll", piece="Katia", ability="I Need My Space",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if not success:
            return None

        from .boss import push_boss
        result = push_boss(self, dr, dc, max_distance=2)

        if self.iwkym_active:
            self.iwkym_active = False
            self.iwkym_turns_remaining = 0
            self.iwkym_holder_pos = None
            self.log_event("iwkym_broken", detail="Katia's push broke Samantha's hold")

        self.log_event("i_need_my_space", direction=[dr, dc], result=result)
        return result

    def try_iwkym(self, samantha_pos: Tuple[int, int], dice: DungeonDice,
                  die_index: int) -> bool:
        """Samantha's IWKYM (Cost 6): must be adjacent to a boss square. Holds
        the boss still for 2 boss turns -- it can't move but can still be hit.
        No targeting -- fires immediately.
        """
        piece = self.board.get(*samantha_pos)
        if piece is None or piece.piece_type != PieceType.SAMANTHA:
            return False
        if self.is_piece_suppressed(*samantha_pos):
            return False
        if not self.boss_active:
            return False
        if not self._boss_square_near(samantha_pos, radius=1):
            return False
        if self.iwkym_active:
            return False

        success = dice.spend_die(die_index, 6)
        self.log_event("ability_roll", piece="Samantha", ability="IWKYM",
                       die_value=dice.dice[die_index], floor=6, result="success" if success else "fail")
        if not success:
            return False

        self.iwkym_active = True
        self.iwkym_turns_remaining = 2
        self.iwkym_holder_pos = samantha_pos
        self.log_event("iwkym_activated", pos=list(samantha_pos))
        return True
