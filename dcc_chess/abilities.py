"""Ability implementations and status effect tracking for DCC Chess.

Handles all major piece abilities and pawn abilities, plus the status
effects they create (ghost tokens, smoke zones, slowed, suppressed, etc.).
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
        self.smoke_zones: List[Dict] = []  # [{pos: (r,c), turns: int}] (2x2, stored as top-left)
        self.phantom_threats: Dict[Color, Set[Tuple[int, int]]] = {
            Color.WHITE: set(), Color.BLACK: set()
        }

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
        
        # Mongo
        self.mongo_stored: Dict[Tuple[Color, int], bool] = {}  # (color, piece_id) -> is_stored
        self.mongo_stored_pos: Dict[Tuple[Color, int], Tuple[int, int]] = {}  # where mongo was stored from
        self.rampage_used: Dict[Tuple[Color, int], bool] = {}  # (color, piece_id) -> used
        
        # Katia
        self.she_tank_uses: Dict[Color, int] = {Color.WHITE: 2, Color.BLACK: 2}
        self.she_tank_targets: Set[Tuple[int, int]] = set()  # pieces that can't move this turn
        self.she_tank_pending: Set[Tuple[int, int]] = set()  # applied this turn, active next
        self.blitzed_pieces: Set[Tuple[int, int]] = set()  # pieces that can skip movement this turn
        
        # Samantha
        self.slut_shame_used: Dict[Tuple[Color, int], bool] = {}
        self.swallowed_pawns: List[Dict] = []  # [{piece: Piece, turns_left: int, sam_pos: (r,c)}]
        
        # ── Old tracking (kept for compatibility) ────────────────
        self.narrators_favor_used: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}
        self.resurrection_used: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}
        self.rampaging_charge_used: Dict[Tuple[Color, int], bool] = {}
        self.portal_spike_used: Dict[Tuple[Color, int], bool] = {}
        self.mouth_used_this_turn: bool = False
        self.katia_last_threats: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}

        # ── Pawn Ability Tracking (Chunk 2) ──────────────────────
        self.pawn_ability_uses: Dict[str, Dict[str, int]] = {}  # "color_pawnname" -> {ability: uses_left}
        
        # Zev — Biggest Fan: +1 to all dice next turn
        self.zev_buff_active: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}
        
        # Mordecai — Manager Benefit: ghost zones and respawn
        self.mordecai_respawn_pending: List[Dict] = []  # [{piece: Piece, turns_left: int, color: Color}]
        
        # Elle McGib — Frozen: frozen pieces
        self.frozen_pieces: Set[Tuple[int, int]] = set()  # active this turn
        self.frozen_pending: Set[Tuple[int, int]] = set()  # applied this turn, active next
        
        # Imani — Suppress: suppressed pieces (already tracked above in suppressed_pieces)
        
        # Slugalo — One Of Us: recruited pawns
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
        
        # Garret — Indestructible: (handled in is_piece_invulnerable)
        
        # Signet — Succubus: pull male pieces closer
        # (handled directly in ability, no persistent state needed)
        
        # Miriam Dom — Blood Magic: (uses existing captured list)
        
        # Orthrus — Aloof: always moves 2 squares, can only be captured by majors
        self.orthrus_permanently_dead: Set[str] = set()  # "color_orthrus" keys
        
        # Raul — Group Climax: cost reduction
        self.group_climax_active: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}
        
        # Bad Llama — Lava Spit: zones that force movement
        self.lava_spit_zones: List[Dict] = []  # [{pos: (r,c), turns: int}] (2x2 zones)

        # ── Additional state referenced by ability methods ────────────
        # Forced retreat (Florin's Suppressing Fire — _apply_forced_retreat reads this)
        self.forced_retreat: Dict[Tuple[int, int], Tuple[int, int]] = {}
        self.forced_retreat_pending: Dict[Tuple[int, int], Tuple[int, int]] = {}

        # Enthrall / Succubus (Signet — _apply_enthrall reads enthralled_pieces)
        self.enthralled_pieces: Dict[Tuple[int, int], Tuple[int, int]] = {}
        self.enthralled_pending: Dict[Tuple[int, int], Tuple[int, int]] = {}
        self.succubus_pending: Set[Tuple[int, int]] = set()

        # Elle McGib — Frozen Immunity one-time-use tracking (attempt_capture reads this)
        self.elle_immunity_used: Dict[str, bool] = {}
        # Keys the player has explicitly declined to auto-trigger for the capture
        # currently being resolved (set by /resolve_elle_decision, consumed by the
        # very next attempt_capture call so it doesn't loop back and re-trigger).
        self.elle_immunity_skip_once: Set[str] = set()

        # Captured pieces (ability methods use self.captured_pieces in addition to board.captured)
        self.captured_pieces: Dict[Color, List] = {Color.WHITE: [], Color.BLACK: []}

        # Zev — Pack Rally buffed pawn positions
        self.zev_buff_pawns: Set[Tuple[int, int]] = set()

        # Lucia Mar — Sicced pending (legacy implementation reference)
        self.sicced_pending: Set[Tuple[int, int]] = set()

        # Raul the Crab — Meditative Strike tracking
        self.raul_moved_this_turn: Set[Tuple[int, int]] = set()
        self.meditative_strike_active: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}

        # Raul the Crab — Group Climax pending next turn
        self.group_climax_pending: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}

        # Stripper Anaconda — Gun Show buff duration tracking
        self.gun_show_active: Dict[Color, int] = {Color.WHITE: 0, Color.BLACK: 0}

        # Piece gender overrides (for gender-based abilities: Gun Show, Succubus, Signet)
        self.piece_genders: Dict[tuple, str] = {}

        # ── AI Card System (Chunk 3) ─────────────────────────────
        self.ai_card_deck: List[str] = ai_cards.build_ai_deck()
        self.ai_cards_drawn: List[str] = []
        self.ai_card_active: Optional[Dict] = None  # currently-resolving/last-drawn card, or None

        # System Reset -- no abilities activatable by anyone, for the rest of this turn
        self.system_reset_active: bool = False
        # Main Character Syndrome -- no pawns can move, for the rest of this turn
        self.main_character_syndrome_active: bool = False
        # What a Bitch -- one-shot Insta-Kill Boss Card, usable during a boss battle (Part 3)
        self.insta_kill_card: Dict[Color, bool] = {Color.WHITE: False, Color.BLACK: False}

        # Lottery Ticket (Custard) / Too Boring -- a card that needs the player to pick a
        # target pauses here instead of resolving immediately. Mirrors the pending_elle_decision
        # pattern: normal gameplay is blocked (see route guards in app.py) until it's resolved
        # via /ai_card/custard_choice or /ai_card/too_boring_choice.
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

    # The 4 board corners + center square Feral Goose's puzzle requires to be
    # simultaneously occupied (by any piece, either color) to defeat her.
    FERAL_GOOSE_PUZZLE_SQUARES = [(0, 0), (0, BOARD_SIZE - 1), (BOARD_SIZE - 1, 0),
                                   (BOARD_SIZE - 1, BOARD_SIZE - 1), (5, 5)]

    def check_feral_goose_puzzle(self) -> bool:
        """Called at the end of every turn while a Feral Goose is active. If
        all 5 puzzle squares are simultaneously occupied, she's defeated.
        Returns True if this defeated her.
        """
        if not self.boss_active or self.active_boss != "Feral Goose":
            return False
        if all(self.board.get(r, c) is not None for r, c in self.FERAL_GOOSE_PUZZLE_SQUARES):
            self.log_event("feral_goose_puzzle_solved",
                           detail="Puzzle Solved — The Feral Goose has been defeated!")
            self.defeat_boss()
            return True
        return False

    # ── Turn Lifecycle ────────────────────────────────────────────

    def start_turn(self):
        """Called at the start of each turn. Clears per-turn state."""
        self.mouth_used_this_turn = False
        # Rebuild from persistent tracker so Air Strike zones survive across turns
        self.louie_cant_move = set(self.air_strike_zones.keys())
        self.phantom_threats[Color.WHITE].clear()
        self.phantom_threats[Color.BLACK].clear()
        self.blitzed_pieces.clear()
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

        # Tick ghost tokens
        expired_ghosts = []
        for pos, turns in self.ghost_tokens.items():
            self.ghost_tokens[pos] = turns - 1
            if self.ghost_tokens[pos] <= 0:
                expired_ghosts.append(pos)
        for pos in expired_ghosts:
            del self.ghost_tokens[pos]

        # Tick smoke zones
        self.smoke_zones = [
            {**sz, "turns": sz["turns"] - 1}
            for sz in self.smoke_zones if sz["turns"] - 1 > 0
        ]

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
        
        # Tick lava spit zones
        self.lava_spit_zones = [
            {**zone, "turns": zone["turns"] - 1}
            for zone in self.lava_spit_zones if zone["turns"] - 1 > 0
        ]

        # Swallowed pawns (Slut Shame)
        respawned = []
        for i, swallowed in enumerate(self.swallowed_pawns):
            swallowed["turns_left"] -= 1
            if swallowed["turns_left"] <= 0:
                respawned.append(i)
        # Respawn in reverse order to avoid index issues
        for i in reversed(respawned):
            pawn_data = self.swallowed_pawns.pop(i)
            # Find Samantha and respawn pawn adjacent
            sam_pos = pawn_data["sam_pos"]
            piece = pawn_data["piece"]
            # Try to find adjacent empty square
            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = sam_pos[0] + dr, sam_pos[1] + dc
                    if self.board.in_bounds(nr, nc) and self.board.get(nr, nc) is None:
                        self.board.set(nr, nc, piece)
                        self.log_event("pawn_respawn", piece=repr(piece), pos=(nr, nc))
                        break
        
        # Mordecai respawn
        mordecai_respawned = []
        for i, mord_data in enumerate(self.mordecai_respawn_pending):
            mord_data["turns_left"] -= 1
            if mord_data["turns_left"] <= 0:
                mordecai_respawned.append(i)
        for i in reversed(mordecai_respawned):
            mord_data = self.mordecai_respawn_pending.pop(i)
            piece = mord_data["piece"]
            color = mord_data["color"]
            # Respawn on back rank
            back_rank = 0 if color == Color.WHITE else 10
            for c in range(BOARD_SIZE):
                if self.board.get(back_rank, c) is None:
                    self.board.set(back_rank, c, piece)
                    # NOTE: Mordecai's Manager Benefit respawn is his own passive,
                    # not an enemy resurrection, so a Juice Box that captured him
                    # keeps that acquired ability. Only an opponent actively
                    # resurrecting the pawn (Cockroach / Blood Magic) strips it.
                    self.log_event("mordecai_respawn", piece=repr(piece), pos=(back_rank, c))
                    break

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

        # Feral Goose puzzle: check at the end of every turn while she's active
        self.check_feral_goose_puzzle()

        # Swap player
        self.current_player = self.current_player.opponent
        self.turn_number += 1

    # ── Square Blocking ───────────────────────────────────────────

    def is_square_blocked(self, row: int, col: int) -> bool:
        """Check if a square is blocked by ghost tokens, smoke zones, lava zones, or air strike zones."""
        if (row, col) in self.ghost_tokens:
            return True
        if (row, col) in self.lava_zones:
            return True
        if (row, col) in self.air_strike_zones:
            return True
        for sz in self.smoke_zones:
            sr, sc = sz["pos"]
            if sr <= row <= sr + 1 and sc <= col <= sc + 1:
                return True
        return False

    def is_piece_movable(self, row: int, col: int, piece: Piece) -> bool:
        """Check if a piece can move (not stuck, not iron-walled, not Carl-slowed, not frozen, etc.)."""
        # Main Character Syndrome (AI Card): pawns can't move this turn, no exceptions.
        # Major pieces are unaffected.
        if self.main_character_syndrome_active and piece.is_pawn:
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
        # Garret is indestructible — cannot be captured by normal means
        piece = self.board.get(row, col)
        if piece and piece.is_pawn and piece.pawn_name == "Garret":
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
            # During a Boss Event, regular PvP captures are disabled entirely --
            # pieces may still move for positioning, but only Special Event
            # Attacks can deal damage (and only to the boss). Any move that would
            # land on an occupied square (friendly or enemy) is excluded so the
            # board highlights only non-capture destinations.
            if self.boss_active and target is not None:
                continue
            # Garret cannot capture enemy pieces
            if piece.is_pawn and piece.pawn_name == "Garret" and target is not None:
                continue
            # Orthrus cannot capture pieces
            if piece.is_pawn and piece.pawn_name == "Orthrus" and target is not None:
                continue
            # Only major pieces can capture Orthrus
            if target and target.is_pawn and target.pawn_name == "Orthrus" and piece.is_pawn:
                continue
            filtered.append(((fr, fc), (tr, tc)))

        # Forced retreat filter (Florin's Suppressing Fire)
        retreat_filtered = self._apply_forced_retreat(filtered, color)

        # Enthrall filter (Signet)
        enthrall_filtered = self._apply_enthrall(retreat_filtered, color)

        return enthrall_filtered if enthrall_filtered else filtered

    # ── Capture Interception ──────────────────────────────────────

    def elle_immunity_available(self, defender_pos: Tuple[int, int]) -> bool:
        """Check (without consuming) whether the Elle McGib at defender_pos can
        still use her once-per-game Frozen Immunity. Used to decide whether to
        pause and prompt her owner before resolving a capture against her.
        """
        dr, dc = defender_pos
        defender = self.board.get(dr, dc)
        if not (defender and defender.is_pawn and defender.pawn_name == "Elle McGib"):
            return False
        key = f"{defender.color.value}_{dr}_{dc}"
        if key in self.elle_immunity_used:
            return False
        pawn_key = f"{defender.color.value}_Elle McGib"
        uses = self.pawn_ability_uses.get(pawn_key, {}).get("Frozen Immunity", 1)
        return uses > 0

    def consume_elle_immunity(self, defender_pos: Tuple[int, int]):
        """Mark Elle McGib's Frozen Immunity as used for the rest of the game."""
        dr, dc = defender_pos
        defender = self.board.get(dr, dc)
        if defender is None:
            return
        key = f"{defender.color.value}_{dr}_{dc}"
        pawn_key = f"{defender.color.value}_Elle McGib"
        uses = self.pawn_ability_uses.get(pawn_key, {}).get("Frozen Immunity", 1)
        self.elle_immunity_used[key] = True
        if pawn_key in self.pawn_ability_uses:
            self.pawn_ability_uses[pawn_key]["Frozen Immunity"] = uses - 1
        self.log_event("ability_auto", piece="Elle McGib", ability="Frozen Immunity",
                       result="success", detail="Capture negated")

    def attempt_capture(
        self, attacker_pos: Tuple[int, int], defender_pos: Tuple[int, int]
    ) -> str:
        """Process capture with possible interceptions.

        Returns: "captured", "defended_quasar", "defended_elle", "defended_narrators_favor", "defended_garret"
        """
        dr, dc = defender_pos
        defender = self.board.get(dr, dc)
        attacker = self.board.get(*attacker_pos)
        if defender is None:
            return "captured"

        # Check Garret's Indestructible (auto-trigger)
        if defender.is_pawn and defender.pawn_name == "Garret":
            # Garret can only be captured by enemy Carl or Blood Magic
            if not self.check_garret_special_capture(attacker_pos, defender_pos):
                self.log_event("ability_auto", piece="Garret", ability="Indestructible",
                               result="success", detail="Cannot be captured by non-Carl")
                return "defended_garret"

        # Orthrus can only be captured by major pieces (defense in depth --
        # get_legal_moves_with_status already keeps non-majors from reaching here)
        if defender.is_pawn and defender.pawn_name == "Orthrus":
            if not self.check_orthrus_capturable(attacker):
                self.log_event("ability_auto", piece="Orthrus", ability="Only Majors Can Capture",
                               result="success", detail="Cannot be captured by non-major pieces")
                return "defended_orthrus"

        # Check Elle McGib's Frozen Immunity (auto-trigger, unless the player
        # already decided against it for this specific capture attempt via
        # /resolve_elle_decision)
        if defender.is_pawn and defender.pawn_name == "Elle McGib":
            key = f"{defender.color.value}_{dr}_{dc}"
            if key in self.elle_immunity_skip_once:
                self.elle_immunity_skip_once.discard(key)
            else:
                pawn_key = f"{defender.color.value}_Elle McGib"
                uses = self.pawn_ability_uses.get(pawn_key, {}).get("Frozen Immunity", 1)
                if uses > 0 and key not in self.elle_immunity_used:
                    self.consume_elle_immunity(defender_pos)
                    return "defended_elle"

        # Check Carl's Narrator's Favor
        if defender.is_king and defender.color in self.narrators_favor_used:
            if not self.narrators_favor_used[defender.color]:
                # Narrator's Favor hasn't been used yet — but it requires a die roll
                # This is handled in the ability phase, not auto. Skip here.
                pass

        # Check Quasar's Mediation (defensive, auto-trigger). Also applies if
        # the defender is Juice Box and has personally captured Mediation --
        # Shapeshift makes it her own passive defense, not just Quasar's.
        quasar_alive = self._find_pawn(defender.color, "Quasar")
        juice_box_has_mediation = (
            defender.is_pawn and defender.pawn_name == "Juice Box"
            and "Mediation" in self.juice_box_captured.get(self.juice_box_key(defender), [])
        )
        # Mediation can never protect Carl himself, and cannot fire while the
        # defending side's Carl is in check.
        mediation_available = (
            (quasar_alive or juice_box_has_mediation)
            and self.quasar_uses[defender.color] < 2
            and not defender.is_king
            and not is_in_check(self.board, defender.color)
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

        # Mordecai's Manager Benefit (Chunk 2)
        if captured_piece.is_pawn and captured_piece.pawn_name == "Mordecai":
            self.process_mordecai_capture(capture_pos, captured_piece)
        
        # Orthrus permanent death: only majors can capture him, and it's final
        if captured_piece.is_pawn and captured_piece.pawn_name == "Orthrus":
            if self.check_orthrus_capturable(attacker):
                self.process_orthrus_permanent_death(captured_piece, capture_pos)
            else:
                # Orthrus cannot be captured by non-majors -- this shouldn't
                # happen since get_legal_moves_with_status already filters it out
                pass
        
        # Juice Box Shapeshift (Chunk 2)
        if attacker.is_pawn and attacker.pawn_name == "Juice Box":
            if captured_piece.is_pawn:
                # Juice Box always ends the capture standing on capture_pos (she moves
                # onto the captured piece's square), so that's her key into
                # juice_box_captured — not attacker_pos, her square before the move.
                self.process_juice_box_capture(capture_pos, captured_piece, capture_pos)

    # ── Major Piece Abilities ─────────────────────────────────────

    def try_bulldozer(self, carl_pos: Tuple[int, int], dice: DungeonDice,
                      die_index: int) -> Optional[List[Tuple[int, int]]]:
        """Carl's Bulldozer (Floor 4): move 2 squares instead of 1.

        Returns list of extra destination squares if successful, None if failed.
        """
        piece = self.board.get(*carl_pos)
        if piece is None or piece.piece_type != PieceType.CARL:
            return None
        if self.is_piece_suppressed(*carl_pos):
            return None

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Carl", ability="Bulldozer",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return None

        # Generate 2-square king moves
        r, c = carl_pos
        extra_moves = []
        for dr in [-2, -1, 0, 1, 2]:
            for dc in [-2, -1, 0, 1, 2]:
                if abs(dr) <= 1 and abs(dc) <= 1:
                    continue  # Normal king moves
                if abs(dr) > 2 or abs(dc) > 2:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc) and not self.is_square_blocked(nr, nc):
                    target = self.board.get(nr, nc)
                    if target is None or (target.color != piece.color and
                                          not self.is_piece_invulnerable(nr, nc)):
                        extra_moves.append((nr, nc))
        return extra_moves

    def try_divas_entrance(self, donut_pos: Tuple[int, int], dice: DungeonDice,
                           die_index: int, target_square: Tuple[int, int]) -> bool:
        """Donut's Diva's Entrance (Floor 4): threaten 1 phantom square for 1 turn."""
        piece = self.board.get(*donut_pos)
        if piece is None or piece.piece_type != PieceType.DONUT:
            return False
        if self.is_piece_suppressed(*donut_pos):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Donut", ability="Diva's Entrance",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if success:
            self.phantom_threats[piece.color].add(target_square)
            return True
        return False

    def try_resurrection(self, donut_pos: Tuple[int, int], dice: DungeonDice,
                         die_index: int, color: Color) -> Optional[Piece]:
        """Donut's Resurrection (Floor 6, 1/game): bring back a captured piece."""
        if self.resurrection_used[color]:
            return None
        piece = self.board.get(*donut_pos)
        if piece is None or piece.piece_type != PieceType.DONUT:
            return None
        if self.is_piece_suppressed(*donut_pos):
            return None

        success = dice.spend_die(die_index, 6)
        self.resurrection_used[color] = True
        self.log_event("ability_roll", piece="Donut", ability="Resurrection",
                       die_value=dice.dice[die_index], floor=6, result="success" if success else "fail")
        if not success:
            return None

        # Find captured pieces (Orthrus and permanently-dead pieces can never be resurrected)
        source = self.board.captured[color]
        candidates = [p for p in source
                      if not p.permanently_dead and not (p.is_pawn and p.pawn_name == "Orthrus")]
        if not candidates:
            return None

        # Pick a random captured piece to resurrect
        revived = random.choice(candidates)
        source.remove(revived)

        # Find empty square adjacent to Donut
        dr, dc = donut_pos
        adj_squares = []
        for ddr in [-1, 0, 1]:
            for ddc in [-1, 0, 1]:
                if ddr == 0 and ddc == 0:
                    continue
                nr, nc = dr + ddr, dc + ddc
                if (self.board.in_bounds(nr, nc) and self.board.get(nr, nc) is None
                        and not self.is_square_blocked(nr, nc)):
                    adj_squares.append((nr, nc))

        if not adj_squares:
            source.append(revived)  # Put it back
            return None

        place_pos = random.choice(adj_squares)
        self.board.set(place_pos[0], place_pos[1], revived)
        revived.has_moved = True
        self.log_event("resurrection", piece=repr(revived), position=place_pos)
        return revived

    def try_rampaging_charge(self, mongo_pos: Tuple[int, int], dice: DungeonDice,
                             die_index: int) -> Optional[List[Tuple[int, int]]]:
        """Mongo's Rampaging Charge (Floor 4, 1/game): move 1 sq orthogonally."""
        piece = self.board.get(*mongo_pos)
        if piece is None or piece.piece_type != PieceType.MONGO:
            return None
        if self.is_piece_suppressed(*mongo_pos):
            return None

        key = (piece.color, id(piece))
        if self.rampaging_charge_used.get(key, False):
            return None

        success = dice.spend_die(die_index, 4)
        self.rampaging_charge_used[key] = True
        self.log_event("ability_roll", piece="Mongo", ability="Rampaging Charge",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return None

        r, c = mongo_pos
        ortho_moves = []
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if self.board.in_bounds(nr, nc) and not self.is_square_blocked(nr, nc):
                target = self.board.get(nr, nc)
                if target is None or (target.color != piece.color and
                                      not self.is_piece_invulnerable(nr, nc)):
                    ortho_moves.append((nr, nc))
        return ortho_moves

    def try_mongo_smash(self, mongo_pos: Tuple[int, int], dice: DungeonDice,
                        die_index: int) -> bool:
        """Mongo's Mongo Smash (Floor 3): capture enemy 1 sq outside normal range."""
        piece = self.board.get(*mongo_pos)
        if piece is None or piece.piece_type != PieceType.MONGO:
            return False
        if self.is_piece_suppressed(*mongo_pos):
            return False

        success = dice.spend_die(die_index, 3)
        self.log_event("ability_roll", piece="Mongo", ability="Mongo Smash",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if not success:
            return False

        # Find enemies 1 square outside normal diagonal range
        r, c = mongo_pos
        normal_moves = set(pseudo_legal_moves_for_piece(self.board, r, c))
        smash_targets = []
        # Check all adjacent + 1 squares
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                nr, nc = r + dr, c + dc
                if (nr, nc) == (r, c):
                    continue
                if not self.board.in_bounds(nr, nc):
                    continue
                if (nr, nc) in normal_moves:
                    continue
                target = self.board.get(nr, nc)
                if target and target.color != piece.color and not self.is_piece_invulnerable(nr, nc):
                    smash_targets.append((nr, nc))

        if smash_targets:
            target_pos = random.choice(smash_targets)
            target_piece = self.board.get(*target_pos)
            cap_result = self.attempt_capture(mongo_pos, target_pos)
            if cap_result == "captured":
                self.board.set(target_pos[0], target_pos[1], None)
                self.board.captured[target_piece.color].append(target_piece)
                self.process_post_capture(target_piece, target_pos, piece, mongo_pos)
                self.log_event("mongo_smash_capture", target=repr(target_piece), pos=target_pos)
                return True
        return False

    def try_combat_roll(self, katia_pos: Tuple[int, int], dice: DungeonDice,
                        die_index: int) -> Optional[List[Tuple[int, int]]]:
        """Katia's Combat Roll (Floor 3): retreat to any square she threatened last turn."""
        piece = self.board.get(*katia_pos)
        if piece is None or piece.piece_type != PieceType.KATIA:
            return None
        if self.is_piece_suppressed(*katia_pos):
            return None

        success = dice.spend_die(die_index, 3)
        self.log_event("ability_roll", piece="Katia", ability="Combat Roll",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if not success:
            return None

        last_threats = self.katia_last_threats.get(katia_pos, [])
        valid_retreats = [
            pos for pos in last_threats
            if self.board.in_bounds(*pos) and self.board.get(*pos) is None
            and not self.is_square_blocked(*pos)
        ]
        return valid_retreats if valid_retreats else None

    def try_dual_threat(self, katia_pos: Tuple[int, int], dice: DungeonDice,
                        die_index: int, target_square: Tuple[int, int]) -> bool:
        """Katia's Dual Threat (Floor 5): after capture, threaten 1 bonus square."""
        piece = self.board.get(*katia_pos)
        if piece is None or piece.piece_type != PieceType.KATIA:
            return False
        if self.is_piece_suppressed(*katia_pos):
            return False

        success = dice.spend_die(die_index, 5)
        self.log_event("ability_roll", piece="Katia", ability="Dual Threat",
                       die_value=dice.dice[die_index], floor=5, result="success" if success else "fail")
        if success:
            self.phantom_threats[piece.color].add(target_square)
            return True
        return False

    def try_the_mouth(self, samantha_pos: Tuple[int, int], dice: DungeonDice,
                      die_index: int) -> Optional[int]:
        """Samantha's The Mouth (Floor 3, 1/turn): reroll 1 Dungeon Die."""
        if self.mouth_used_this_turn:
            return None
        piece = self.board.get(*samantha_pos)
        if piece is None or piece.piece_type != PieceType.SAMANTHA:
            return None
        if self.is_piece_suppressed(*samantha_pos):
            return None

        success = dice.spend_die(die_index, 3)
        self.mouth_used_this_turn = True
        self.log_event("ability_roll", piece="Samantha", ability="The Mouth",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if not success:
            return None

        # Reroll a different die (pick one that's still available)
        available = dice.available_dice
        if available:
            reroll_idx = random.choice(available)
            new_val = dice.reroll_die(reroll_idx)
            self.log_event("the_mouth_reroll", die_index=reroll_idx, new_value=new_val)
            return new_val
        return None

    def try_portal_spike(self, samantha_pos: Tuple[int, int], dice: DungeonDice,
                         die_index: int) -> Optional[Tuple[int, int]]:
        """Samantha's Portal Spike (Floor 5, 1/game): teleport on rank/file."""
        piece = self.board.get(*samantha_pos)
        if piece is None or piece.piece_type != PieceType.SAMANTHA:
            return None
        if self.is_piece_suppressed(*samantha_pos):
            return None

        key = (piece.color, id(piece))
        if self.portal_spike_used.get(key, False):
            return None

        success = dice.spend_die(die_index, 5)
        self.portal_spike_used[key] = True
        self.log_event("ability_roll", piece="Samantha", ability="Portal Spike",
                       die_value=dice.dice[die_index], floor=5, result="success" if success else "fail")
        if not success:
            return None

        r, c = samantha_pos
        destinations = []
        # Same rank
        for nc in range(BOARD_SIZE):
            if nc != c and self.board.get(r, nc) is None and not self.is_square_blocked(r, nc):
                destinations.append((r, nc))
        # Same file
        for nr in range(BOARD_SIZE):
            if nr != r and self.board.get(nr, c) is None and not self.is_square_blocked(nr, c):
                destinations.append((nr, c))

        if destinations:
            dest = random.choice(destinations)
            self.board.set(r, c, None)
            self.board.set(dest[0], dest[1], piece)
            self.log_event("portal_spike_teleport", from_pos=samantha_pos, to_pos=dest)
            return dest
        return None

    # ── Pawn Abilities ────────────────────────────────────────────

    def try_pack_rally(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                       die_index: int) -> bool:
        """Zev's Pack Rally (Floor 3): +1 to adjacent friendly pawns' dice."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Zev":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 3)
        self.log_event("ability_roll", piece="Zev", ability="Pack Rally",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if not success:
            return False

        r, c = pawn_pos
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    adj = self.board.get(nr, nc)
                    if adj and adj.is_pawn and adj.color == piece.color:
                        self.zev_buff_pawns.add((nr, nc))
        self.log_event("pack_rally_buff", buffed=list(self.zev_buff_pawns))
        return True

    def try_glitch(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                   die_index: int) -> bool:
        """The AI's Glitch: copy a random friendly pawn's ability and use it."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "The AI":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        # Find other friendly pawns
        friendly_pawns = [
            (r, c, p) for r, c, p in self.board.all_pieces(piece.color)
            if p.is_pawn and p.pawn_name and p.pawn_name != "The AI"
            and PAWN_CHARACTERS.get(p.pawn_name)
            and PAWN_CHARACTERS[p.pawn_name].ability.trigger == AbilityTrigger.FLOOR_ROLL
        ]
        if not friendly_pawns:
            return False

        # Pick random pawn to copy
        _, _, copied_pawn = random.choice(friendly_pawns)
        copied_char = PAWN_CHARACTERS[copied_pawn.pawn_name]
        copied_floor = copied_char.ability.floor_number

        success = dice.spend_die(die_index, copied_floor)
        self.log_event("ability_roll", piece="The AI", ability=f"Glitch→{copied_char.ability.name}",
                       die_value=dice.dice[die_index], floor=copied_floor,
                       result="success" if success else "fail")
        return success

    def try_titan_stride(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                         die_index: int) -> Optional[Tuple[int, int]]:
        """Prepotente's Titan Stride (Floor 3): move 2 squares forward."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Prepotente":
            return None
        if self.is_piece_suppressed(*pawn_pos):
            return None

        success = dice.spend_die(die_index, 3)
        self.log_event("ability_roll", piece="Prepotente", ability="Titan Stride",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if not success:
            return None

        r, c = pawn_pos
        direction = piece.color.direction
        r2 = r + 2 * direction
        r1 = r + direction
        if (self.board.in_bounds(r2, c) and self.board.get(r2, c) is None
                and self.board.get(r1, c) is None and not self.is_square_blocked(r2, c)):
            return (r2, c)
        return None

    def try_suppression(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                        die_index: int) -> bool:
        """Imani's Suppression (Floor 4): suppress enemy within 1 square."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Imani":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Imani", ability="Suppression",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        r, c = pawn_pos
        targets = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    t = self.board.get(nr, nc)
                    if t and t.color != piece.color:
                        targets.append((nr, nc))
        if targets:
            target_pos = random.choice(targets)
            self.suppressed_pending.add(target_pos)
            self.log_event("suppression_applied", target_pos=target_pos)
            return True
        return False

    def try_recruit(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                    die_index: int) -> bool:
        """Slugalo's Recruit (Floor 3, 1/game): adjacent enemy pawn switches sides."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Slugalo":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        key = f"{piece.color.value}_Slugalo"
        uses = self.pawn_ability_uses.get(key, {}).get("Recruit", 1)
        if uses <= 0:
            return False

        success = dice.spend_die(die_index, 3)
        if key in self.pawn_ability_uses:
            self.pawn_ability_uses[key]["Recruit"] = uses - 1
        self.log_event("ability_roll", piece="Slugalo", ability="Recruit",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if not success:
            return False

        r, c = pawn_pos
        targets = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    t = self.board.get(nr, nc)
                    if t and t.is_pawn and t.color != piece.color:
                        targets.append((nr, nc, t))
        if targets:
            tr, tc, target = random.choice(targets)
            target.color = piece.color  # Switch sides!
            self.log_event("recruit_success", recruited=repr(target), pos=(tr, tc))
            return True
        return False

    def try_smoke_bomb(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                       die_index: int) -> bool:
        """Louie's Smoke Bomb (Floor 4): create 2x2 blocked zone for 3 turns."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Louie":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Louie", ability="Smoke Bomb",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        # Find valid 2x2 zones within 3 squares
        r, c = pawn_pos
        valid_zones = []
        for dr in range(-3, 4):
            for dc in range(-3, 4):
                nr, nc = r + dr, c + dc
                if abs(dr) + abs(dc) > 3:
                    continue
                # Check all 4 squares of the 2x2 zone
                if (self.board.in_bounds(nr, nc) and self.board.in_bounds(nr + 1, nc + 1)):
                    valid_zones.append((nr, nc))

        if valid_zones:
            zone_pos = random.choice(valid_zones)
            self.smoke_zones.append({"pos": zone_pos, "turns": 3})
            self.louie_cant_move.add(pawn_pos)
            self.log_event("smoke_bomb_placed", zone_pos=zone_pos)
            return True
        return False

    def try_iron_wall(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                      die_index: int) -> bool:
        """Sledge's Iron Wall (Floor 3): immovable + invulnerable for 2 turns."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Sledge":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 3)
        self.log_event("ability_roll", piece="Sledge", ability="Iron Wall",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if success:
            self.iron_wall_pieces[pawn_pos] = 2
            return True
        return False

    # ── Helpers ───────────────────────────────────────────────────

    def _find_pawn(self, color: Color, pawn_name: str) -> Optional[Tuple[int, int]]:
        """Find a living pawn by name and color."""
        for r, c, p in self.board.all_pieces(color):
            if p.is_pawn and p.pawn_name == pawn_name:
                return (r, c)
        return None

    def _is_female(self, piece: Piece) -> bool:
        """Check if a piece is female."""
        if piece.piece_type.value in FEMALE_MAJOR_PIECE_TYPES:
            return True
        if piece.is_pawn and piece.pawn_name in FEMALE_PAWN_NAMES:
            return True
        return False

    def update_katia_threats(self):
        """Store current Katia threatened squares for Combat Roll next turn."""
        self.katia_last_threats.clear()
        for color in [Color.WHITE, Color.BLACK]:
            for r, c, p in self.board.all_pieces(color):
                if p.piece_type == PieceType.KATIA:
                    threats = pseudo_legal_moves_for_piece(self.board, r, c)
                    self.katia_last_threats[(r, c)] = threats

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

    def _apply_enthrall(self, moves, color):
        """Filter moves for pieces under Signet's Enthrall.

        Enthralled pieces must end their move closer to Signet.
        """
        if not self.enthralled_pieces:
            return moves

        result = []
        for (fr, fc), (tr, tc) in moves:
            if (fr, fc) in self.enthralled_pieces:
                signet_r, signet_c = self.enthralled_pieces[(fr, fc)]
                old_dist = abs(fr - signet_r) + abs(fc - signet_c)
                new_dist = abs(tr - signet_r) + abs(tc - signet_c)
                if new_dist >= old_dist:
                    continue  # Must move closer
            result.append(((fr, fc), (tr, tc)))

        # If no closer square available, effect is ignored
        affected_pieces = set(self.enthralled_pieces.keys())
        has_closer = {pos: False for pos in affected_pieces}
        for (fr, fc), _ in result:
            if (fr, fc) in has_closer:
                has_closer[(fr, fc)] = True
        if not all(has_closer.values()):
            return moves
        return result


    # ── New Pawn Abilities ─────────────────────────────────────────

    def try_sicced(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                   die_index: int) -> bool:
        """Lucia Mar's Sicced (Floor 4): pin adjacent enemy piece for 1 turn."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Lucia Mar":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Lucia Mar", ability="Sicced",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        r, c = pawn_pos
        targets = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    t = self.board.get(nr, nc)
                    if t and t.color != piece.color:
                        targets.append((nr, nc))
        if targets:
            target_pos = random.choice(targets)
            self.sicced_pending.add(target_pos)
            self.log_event("sicced_applied", target_pos=target_pos)
            return True
        return False

    def try_lava_surge(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                       die_index: int) -> bool:
        """Chris's Lava Surge (Floor 4): make adjacent squares impassable for 2 turns."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Chris":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Chris", ability="Lava Surge",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        r, c = pawn_pos
        # Chris's square is lava (but he stays on it)
        self.chris_stuck.add((r, c))
        # 4 orthogonal adjacent squares become lava
        ortho = [(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
        lava_squares = []
        for nr, nc in ortho:
            if self.board.in_bounds(nr, nc):
                self.lava_zones[(nr, nc)] = 2
                lava_squares.append((nr, nc))
                # Any piece on an adjacent square must move or be captured
                target = self.board.get(nr, nc)
                if target and (nr, nc) != pawn_pos:
                    # Try to find adjacent open square for the displaced piece
                    escaped = False
                    for dr2 in [-1, 0, 1]:
                        for dc2 in [-1, 0, 1]:
                            if dr2 == 0 and dc2 == 0:
                                continue
                            er, ec = nr + dr2, nc + dc2
                            if (self.board.in_bounds(er, ec)
                                    and self.board.get(er, ec) is None
                                    and not self.is_square_blocked(er, ec)):
                                self.board.set(nr, nc, None)
                                self.board.set(er, ec, target)
                                self.log_event("lava_surge_displace", piece=repr(target),
                                               from_pos=(nr, nc), to_pos=(er, ec))
                                escaped = True
                                break
                        if escaped:
                            break
                    if not escaped:
                        # Piece is captured
                        self.board.set(nr, nc, None)
                        self.board.captured[target.color].append(target)
                        self.log_event("lava_surge_capture", captured=repr(target), pos=(nr, nc))
        self.log_event("lava_surge_activated", chris_pos=pawn_pos, lava=lava_squares)
        return True

    def try_shapeshift(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                       die_index: int) -> bool:
        """Juice Box's Shapeshift (Floor 3): copy any friendly pawn's ability and fire it."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Juice Box":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        # Find ANY friendly pawn with floor_roll ability (no adjacency required)
        friendly_pawns = [
            (r, c, p) for r, c, p in self.board.all_pieces(piece.color)
            if p.is_pawn and p.pawn_name and p.pawn_name != "Juice Box"
            and PAWN_CHARACTERS.get(p.pawn_name)
            and PAWN_CHARACTERS[p.pawn_name].ability.trigger == AbilityTrigger.FLOOR_ROLL
        ]
        if not friendly_pawns:
            return False

        success = dice.spend_die(die_index, 3)
        self.log_event("ability_roll", piece="Juice Box", ability="Shapeshift",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if not success:
            return False

        # Pick a random pawn to copy — fire the copied ability from Juice Box's position
        _, _, copied_pawn = random.choice(friendly_pawns)
        copied_name = copied_pawn.pawn_name
        self.log_event("shapeshift_copy", copied_from=copied_name)
        # We just log the copy — the actual effect is simplified as a success
        return True

    def try_enthrall(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                     die_index: int) -> bool:
        """Signet's Enthrall (Floor 4): force adjacent enemy major piece toward Signet."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Signet":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Signet", ability="Enthrall",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        r, c = pawn_pos
        targets = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    t = self.board.get(nr, nc)
                    if t and t.color != piece.color and not t.is_pawn:
                        targets.append((nr, nc))
        if targets:
            target_pos = random.choice(targets)
            self.enthralled_pending[target_pos] = pawn_pos
            self.log_event("enthrall_applied", target_pos=target_pos, signet_pos=pawn_pos)
            return True
        return False

    def try_meditative_strike(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                              die_index: int) -> bool:
        """Raul the Crab's Meditative Strike (Floor 3): guarantee next die is 6."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Raul the Crab":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False
        # Raul must not have moved this turn
        if pawn_pos in self.raul_moved_this_turn:
            return False

        success = dice.spend_die(die_index, 3)
        self.log_event("ability_roll", piece="Raul the Crab", ability="Meditative Strike",
                       die_value=dice.dice[die_index], floor=3, result="success" if success else "fail")
        if not success:
            return False

        # Set the meditative strike flag — next die spent this turn counts as 6
        self.meditative_strike_active[piece.color] = True
        self.log_event("meditative_strike_active", detail="Next die treated as 6")
        return True

    def try_lava_spit(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                      die_index: int) -> bool:
        """Bad Llama's Lava Spit (Floor 4): force piece off a square or capture it."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name != "Bad Llama":
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Bad Llama", ability="Lava Spit",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        r, c = pawn_pos
        # Find target squares within 2 that have a piece
        targets = []
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                if dr == 0 and dc == 0:
                    continue
                if abs(dr) + abs(dc) > 2:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    t = self.board.get(nr, nc)
                    if t and not self.is_piece_invulnerable(nr, nc):
                        targets.append((nr, nc, t))

        if not targets:
            return False

        tr, tc, target = random.choice(targets)
        # Try to find adjacent open square for the displaced piece
        escaped = False
        adj_squares = []
        for dr2 in [-1, 0, 1]:
            for dc2 in [-1, 0, 1]:
                if dr2 == 0 and dc2 == 0:
                    continue
                er, ec = tr + dr2, tc + dc2
                if (self.board.in_bounds(er, ec) and self.board.get(er, ec) is None
                        and not self.is_square_blocked(er, ec)):
                    adj_squares.append((er, ec))

        if adj_squares:
            dest = random.choice(adj_squares)
            self.board.set(tr, tc, None)
            self.board.set(dest[0], dest[1], target)
            self.log_event("lava_spit_displace", target=repr(target),
                           from_pos=(tr, tc), to_pos=dest)
        else:
            # Can't move — captured
            self.board.set(tr, tc, None)
            self.board.captured[target.color].append(target)
            self.log_event("lava_spit_capture", captured=repr(target), pos=(tr, tc))
        return True

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
        self.log_event("sic_em", target_pos=target_pos, detail="Restrained for next turn")
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
        self.log_event("frozen", target_pos=chosen, detail="Frozen for next turn")
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
        self.log_event("suppress", target_pos=target_pos, detail="Suppressed for next turn")
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

    def try_special_boy(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                        die_index: int) -> Optional[List[Tuple[int, int]]]:
        """Prepotente's Special Boy (Floor 4): Move 2 squares forward."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Prepotente", "Juice Box"):
            return None
        if self.is_piece_suppressed(*pawn_pos):
            return None

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Prepotente", ability="Special Boy",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return None

        r, c = pawn_pos
        forward = piece.color.direction
        moves = []
        
        # Check if Carl is in check
        from .movement import is_in_check
        carl_in_check = is_in_check(self.board, piece.color)
        
        if carl_in_check:
            # Can move 2 squares in any direction
            for dr in [-2, -1, 0, 1, 2]:
                for dc in [-2, -1, 0, 1, 2]:
                    if dr == 0 and dc == 0:
                        continue
                    if abs(dr) > 2 or abs(dc) > 2:
                        continue
                    nr, nc = r + dr, c + dc
                    if self.board.in_bounds(nr, nc) and not self.is_square_blocked(nr, nc):
                        target = self.board.get(nr, nc)
                        if target is None or target.color != piece.color:
                            moves.append((nr, nc))
        else:
            # Move 2 squares forward
            nr = r + (2 * forward)
            if self.board.in_bounds(nr, c) and not self.is_square_blocked(nr, c):
                target = self.board.get(nr, c)
                if target is None or target.color != piece.color:
                    moves.append((nr, c))
            # Can also capture diagonally 2 forward
            for dc in [-2, -1, 1, 2]:
                nc = c + dc
                nr = r + (2 * forward)
                if self.board.in_bounds(nr, nc) and not self.is_square_blocked(nr, nc):
                    target = self.board.get(nr, nc)
                    if target and target.color != piece.color:
                        moves.append((nr, nc))
        
        return moves if moves else None

    def try_suppressing_fire(self, pawn_pos: Tuple[int, int], dice: DungeonDice,
                             die_index: int) -> bool:
        """Florin's Suppressing Fire (Floor 6): Push enemy piece 2 squares away."""
        piece = self.board.get(*pawn_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Florin", "Juice Box"):
            return False
        if self.is_piece_suppressed(*pawn_pos):
            return False

        success = dice.spend_die(die_index, 6)
        self.log_event("ability_roll", piece="Florin", ability="Suppressing Fire",
                       die_value=dice.dice[die_index], floor=6, result="success" if success else "fail")
        if not success:
            return False

        r, c = pawn_pos
        # Find enemy pieces
        targets = []
        for dr in range(-5, 6):
            for dc in range(-5, 6):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    target = self.board.get(nr, nc)
                    # Orthrus is a 2-square body; a single-square push would corrupt it
                    if target and target.color != piece.color and target.pawn_name != "Orthrus":
                        targets.append((nr, nc, target))

        if not targets:
            return False

        # Pick random target
        tr, tc, target = random.choice(targets)

        # Calculate push direction (away from Florin)
        dr = tr - r
        dc = tc - c
        # Normalize to direction
        if dr != 0:
            dr = dr // abs(dr)
        if dc != 0:
            dc = dc // abs(dc)
        
        # Try to push 2 squares
        pushed = 0
        final_r, final_c = tr, tc
        for i in range(1, 3):
            nr = tr + (dr * i)
            nc = tc + (dc * i)
            if self.board.in_bounds(nr, nc) and not self.is_square_blocked(nr, nc):
                if self.board.get(nr, nc) is None:
                    final_r, final_c = nr, nc
                    pushed = i
                else:
                    break
            else:
                break
        
        if pushed > 0:
            self.board.set(tr, tc, None)
            self.board.set(final_r, final_c, target)
            self.log_event("suppressing_fire", target=repr(target),
                           from_pos=(tr, tc), to_pos=(final_r, final_c), pushed=pushed)
            return True
        
        return False

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
        """Bad Llama's Lava Spit (Floor 4): Create 2x2 zone that forces movement.

        `target_pos`, if given, is the top-left corner of the 2x2 zone.
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

        def zone_valid(zone_r, zone_c):
            return self.board.in_bounds(zone_r, zone_c) and self.board.in_bounds(zone_r + 1, zone_c + 1)

        r, c = pawn_pos
        # Find valid 2x2 zones within 4 squares
        valid_zones = []
        for dr in range(-4, 5):
            for dc in range(-4, 5):
                zone_r, zone_c = r + dr, c + dc
                if zone_valid(zone_r, zone_c):
                    valid_zones.append((zone_r, zone_c))

        if target_pos is not None and zone_valid(target_pos[0], target_pos[1]):
            zone_pos = tuple(target_pos)
        elif valid_zones:
            zone_pos = random.choice(valid_zones)
        else:
            return False

        self.lava_spit_zones.append({"pos": zone_pos, "turns": 1})
        self.log_event("lava_spit_chunk2", zone_pos=zone_pos, detail="2x2 zone forces movement")
        return True

    # ── Chunk 2 Abilities: Priority Group 4 (Auto Triggers) ──

    def process_mordecai_capture(self, mordecai_pos: Tuple[int, int], mordecai_piece: Piece):
        """Mordecai's Manager Benefit: Auto-trigger on capture.
        Creates a single-square ghost zone on his captured square and
        schedules respawn after 3 turns.
        """
        # Single ghost square on exactly the square where Mordecai was captured
        self.ghost_tokens[mordecai_pos] = 3

        # Schedule Mordecai respawn after 3 turns
        self.mordecai_respawn_pending.append({
            "piece": mordecai_piece,
            "turns_left": 3,
            "color": mordecai_piece.color
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

    def check_garret_special_capture(self, attacker_pos: Tuple[int, int], 
                                     garret_pos: Tuple[int, int]) -> bool:
        """Check if Garret can be captured by this attacker.
        Garret can only be captured by enemy Carl moving onto his square or by Blood Magic.
        Returns True if capture is allowed, False otherwise.
        """
        attacker = self.board.get(*attacker_pos)
        if attacker is None:
            return False
        
        # Only enemy Carl can capture Garret by moving onto his square
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

        # Add captured pawn to Juice Box's list
        if key not in self.juice_box_captured:
            self.juice_box_captured[key] = []

        if captured_pawn.pawn_name not in self.juice_box_captured[key]:
            self.juice_box_captured[key].append(captured_pawn.pawn_name)

        # Mark that Juice Box can't use ability this turn
        self.juice_box_used_this_turn.add(juice_box_pos)

        self.log_event("juice_box_shapeshift", pos=juice_box_pos,
                       captured=captured_pawn.pawn_name,
                       detail="Gained ability, cannot use this turn")

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
        try:
            if name == "Zev":
                success = self.try_biggest_fan(juice_box_pos, dice, die_index)
            elif name == "Elle McGib":
                success = self.try_frozen(juice_box_pos, dice, die_index, target_pos=target_pos)
            elif name == "Imani":
                success = self.try_suppress(juice_box_pos, dice, die_index)
            elif name == "Slugalo":
                success = self.try_one_of_us(juice_box_pos, dice, target_pos=target_pos)
            elif name == "Louie":
                success = self.try_air_strike(juice_box_pos, dice, die_index, target_pos=target_pos)
            elif name == "Sledge":
                success = self.try_body_guard(juice_box_pos, dice, die_index)
            elif name == "Stripper Anaconda":
                success = self.try_gun_show(juice_box_pos, dice, die_index)
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
                success = self.try_succubus(juice_box_pos, dice, die_index)
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
                    self.board.set(juice_box_pos[0], juice_box_pos[1], None)
                    self.board.set(dest[0], dest[1], piece)
                    piece.has_moved = True
                    success = True
            elif name == "Garret":
                # Indestructible is passive and has no active effect to fire.
                success = False
        finally:
            dice.floor_modifier -= 1

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
        occupied square, and can never land on Carl's own square.
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

    def try_puddle_jump(self, donut_pos: Tuple[int, int], dice: DungeonDice,
                        die_index: int) -> Optional[List[Tuple[int, int]]]:
        """Donut's Puddle Jump (Floor 5): Move like Queen but can pass through pieces."""
        piece = self.board.get(*donut_pos)
        if piece is None or piece.piece_type != PieceType.DONUT:
            return None
        if self.is_piece_suppressed(*donut_pos):
            return None

        success = dice.spend_die(die_index, 5)
        self.log_event("ability_roll", piece="Donut", ability="Puddle Jump",
                       die_value=dice.dice[die_index], floor=5, result="success" if success else "fail")
        if not success:
            return None

        r, c = donut_pos
        moves = []
        # Queen moves in 8 directions (orthogonal + diagonal)
        directions = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
        
        for dr, dc in directions:
            # Check all squares in this direction
            for distance in range(1, BOARD_SIZE):
                nr, nc = r + (dr * distance), c + (dc * distance)
                if not self.board.in_bounds(nr, nc):
                    break
                if self.is_square_blocked(nr, nc):
                    break
                
                target = self.board.get(nr, nc)
                if target is None:
                    # Empty square - can move here
                    moves.append((nr, nc))
                elif target.color != piece.color:
                    # Enemy piece - can capture here but can't pass through
                    moves.append((nr, nc))
                    break
                else:
                    # Friendly piece - can pass through but can't land here
                    continue
        
        return moves if moves else None

    def try_pet_carrier(self, mongo_pos: Tuple[int, int], dice: DungeonDice,
                        die_index: int) -> bool:
        """Mongo's Pet Carrier (Floor 4): Store Mongo or release stored Mongo."""
        piece = self.board.get(*mongo_pos)
        if piece is None or piece.piece_type != PieceType.MONGO:
            return False
        if self.is_piece_suppressed(*mongo_pos):
            return False

        success = dice.spend_die(die_index, 4)
        self.log_event("ability_roll", piece="Mongo", ability="Pet Carrier",
                       die_value=dice.dice[die_index], floor=4, result="success" if success else "fail")
        if not success:
            return False

        key = (piece.color, id(piece))
        
        # Check if this Mongo is already stored
        if self.mongo_stored.get(key, False):
            # Release Mongo - must spawn within 2 squares of Donut
            donut_pos = None
            for row in range(BOARD_SIZE):
                for col in range(BOARD_SIZE):
                    p = self.board.get(row, col)
                    if p and p.piece_type == PieceType.DONUT and p.color == piece.color:
                        donut_pos = (row, col)
                        break
                if donut_pos:
                    break
            
            if not donut_pos:
                # Donut not found - cannot release
                return False
            
            # Find valid spawn positions within 2 squares of Donut
            dr, dc = donut_pos
            valid_spawns = []
            for r_offset in range(-2, 3):
                for c_offset in range(-2, 3):
                    nr, nc = dr + r_offset, dc + c_offset
                    if self.board.in_bounds(nr, nc) and not self.is_square_blocked(nr, nc):
                        if self.board.get(nr, nc) is None:
                            valid_spawns.append((nr, nc))
            
            if not valid_spawns:
                return False
            
            # Release Mongo at random valid position
            spawn_pos = random.choice(valid_spawns)
            self.board.set(spawn_pos[0], spawn_pos[1], piece)
            self.mongo_stored[key] = False
            del self.mongo_stored_pos[key]
            self.log_event("pet_carrier_release", pos=spawn_pos, detail="Mongo released")
            return True
        else:
            # Store Mongo
            self.board.set(*mongo_pos, None)
            self.mongo_stored[key] = True
            self.mongo_stored_pos[key] = mongo_pos
            self.log_event("pet_carrier_store", pos=mongo_pos, detail="Mongo stored")
            return True

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
        self.log_event("blitzed", target_pos=target_pos, detail="Can skip movement this turn")
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
            # Normal use on own turn - need to find a die with value >= 6
            die_index = -1
            for i in range(len(dice.dice)):
                if not dice.used[i] and dice.dice[i] >= 6:
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
        
        self.log_event("she_tank", target_pos=target_pos, 
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

    def try_cockroach(self, donut_pos: Tuple[int, int], dice: DungeonDice) -> Optional[Piece]:
        """Donut's Cockroach (Floor 7, requires combined, once per game):
        Resurrect one captured friendly piece and place on any open square adjacent to Donut.
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
        
        dice.spend_combined(7)
        self.log_event("ability_roll", piece="Donut", ability="Cockroach",
                       detail="Combined dice for cost 7", result="success")
        
        # Mark as used
        self.resurrection_used[piece.color] = True
        
        # Find captured pieces for this color (Orthrus can never be resurrected)
        source = self.captured_pieces.get(piece.color, [])
        captured = [p for p in source if not p.permanently_dead and not (p.is_pawn and p.pawn_name == "Orthrus")]
        if not captured:
            return None

        # Pick random captured piece to resurrect
        resurrected = random.choice(captured)
        source.remove(resurrected)

        # Find adjacent empty squares to Donut
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

        if not adjacent:
            # No space to resurrect - put piece back in captured
            source.append(resurrected)
            return None
        
        # Place at random adjacent position
        spawn_pos = random.choice(adjacent)
        self.board.set(spawn_pos[0], spawn_pos[1], resurrected)
        if resurrected.is_pawn and resurrected.pawn_name:
            self._juice_box_lose_ability(resurrected.pawn_name)

        self.log_event("cockroach", piece_resurrected=repr(resurrected), pos=spawn_pos)
        return resurrected

    def try_rampage(self, mongo_pos: Tuple[int, int], dice: DungeonDice) -> Optional[List[Tuple[int, int]]]:
        """Mongo's Rampage (Floor 8, requires combined, once per game):
        Mongo captures any piece within his L-shaped movement path, not just final destination.
        """
        piece = self.board.get(*mongo_pos)
        if piece is None or piece.piece_type != PieceType.MONGO:
            return None
        if self.is_piece_suppressed(*mongo_pos):
            return None
        
        # Check if already used
        key = (piece.color, id(piece))
        if self.rampaging_charge_used.get(key, False):
            return None
        
        # Requires combined dice (total >= 8)
        if not dice.can_combine_for_cost(8):
            return None
        
        dice.spend_combined(8)
        self.log_event("ability_roll", piece="Mongo", ability="Rampage",
                       detail="Combined dice for cost 8", result="success")
        
        # Mark as used
        self.rampaging_charge_used[key] = True
        
        # Get all knight moves from current position
        r, c = mongo_pos
        knight_moves = [
            (r+2, c+1), (r+2, c-1), (r-2, c+1), (r-2, c-1),
            (r+1, c+2), (r+1, c-2), (r-1, c+2), (r-1, c-2)
        ]
        
        valid_moves = []
        captured_pieces = []
        
        for nr, nc in knight_moves:
            if not self.board.in_bounds(nr, nc):
                continue
            if self.is_square_blocked(nr, nc):
                continue
            
            target = self.board.get(nr, nc)
            if target is None:
                valid_moves.append((nr, nc))
            elif target.color != piece.color:
                # Enemy piece - can capture
                valid_moves.append((nr, nc))
                captured_pieces.append((nr, nc))
        
        # Capture all enemy pieces in the path
        for cap_pos in captured_pieces:
            cap_piece = self.board.get(*cap_pos)
            if cap_piece:
                self.board.set(cap_pos[0], cap_pos[1], None)
                if cap_piece.color not in self.captured_pieces:
                    self.captured_pieces[cap_piece.color] = []
                self.captured_pieces[cap_piece.color].append(cap_piece)
                self.log_event("rampage_capture", pos=cap_pos, piece=repr(cap_piece))
        
        return valid_moves if valid_moves else None

    def try_slut_shame(self, samantha_pos: Tuple[int, int], dice: DungeonDice) -> bool:
        """Samantha's Slut Shame (Floor 8, requires combined, once per game):
        Swallow any pawn within 3 squares, temporarily removing it. Respawns within 1 square of Samantha within 5 turns.
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
        
        dice.spend_combined(8)
        self.log_event("ability_roll", piece="Samantha", ability="Slut Shame",
                       detail="Combined dice for cost 8", result="success")
        
        # Mark as used
        self.slut_shame_used[key] = True
        
        # Find pawns within 3 squares
        r, c = samantha_pos
        target_pawns = []
        for dr in range(-3, 4):
            for dc in range(-3, 4):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    target = self.board.get(nr, nc)
                    # Orthrus is a 2-square body; swallowing one square would corrupt it
                    if target and target.is_pawn and target.color != piece.color and target.pawn_name != "Orthrus":
                        target_pawns.append((nr, nc))

        if not target_pawns:
            return False
        
        # Pick random pawn to swallow
        target_pos = random.choice(target_pawns)
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

    def try_one_of_us(self, slugalo_pos: Tuple[int, int], dice: DungeonDice,
                      target_pos: Optional[Tuple[int, int]] = None) -> bool:
        """Slugalo's One Of Us (Floor 10, requires combined):
        Convert enemy pawn within 2 squares to friendly side.
        """
        piece = self.board.get(*slugalo_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Slugalo", "Juice Box"):
            return False
        if self.is_piece_suppressed(*slugalo_pos):
            return False

        # Requires combined dice (total >= 10)
        if not dice.can_combine_for_cost(10):
            return False

        dice.spend_combined(10)
        self.log_event("ability_roll", piece="Slugalo", ability="One Of Us",
                       detail="Combined dice for cost 10", result="success")

        # Find enemy pawns within 2 squares
        r, c = slugalo_pos
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
        
        self.log_event("one_of_us", converted=repr(converted_pawn), pos=target_pos,
                       detail="Enemy pawn converted to friendly")
        return True

    def try_blood_magic(self, miriam_pos: Tuple[int, int], dice: DungeonDice,
                        target_pos: Optional[Tuple[int, int]] = None) -> bool:
        """Miriam Dom's Blood Magic (Floor 8, requires combined):
        Sacrifice one adjacent friendly pawn, then resurrect any previously captured friendly pawn on back rank.

        `target_pos`, if given, is the adjacent friendly pawn to sacrifice.
        """
        piece = self.board.get(*miriam_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Miriam Dom", "Juice Box"):
            return False
        if self.is_piece_suppressed(*miriam_pos):
            return False

        # Requires combined dice (total >= 8)
        if not dice.can_combine_for_cost(8):
            return False

        dice.spend_combined(8)
        self.log_event("ability_roll", piece="Miriam Dom", ability="Blood Magic",
                       detail="Combined dice for cost 8", result="success")

        # Find adjacent friendly pawns to sacrifice (only adjacent, not within 2 squares)
        r, c = miriam_pos
        adjacent_pawns = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    target = self.board.get(nr, nc)
                    if target and target.is_pawn and target.color == piece.color:
                        adjacent_pawns.append((nr, nc))

        # Check for captured friendly pieces to resurrect (Orthrus can never be resurrected)
        source = self.captured_pieces.get(piece.color, [])
        captured = [p for p in source if not p.permanently_dead and not (p.is_pawn and p.pawn_name == "Orthrus")]

        if not adjacent_pawns or not captured:
            return False

        # Use the requested sacrifice if valid, otherwise pick randomly
        if target_pos is not None and tuple(target_pos) in adjacent_pawns:
            sacrifice_pos = tuple(target_pos)
        else:
            sacrifice_pos = random.choice(adjacent_pawns)
        sacrificed = self.board.get(*sacrifice_pos)

        # Remove sacrificed pawn without triggering on-capture effects
        self.board.set(sacrifice_pos[0], sacrifice_pos[1], None)
        # Do NOT add to captured_pieces - it's sacrificed, not captured

        # Pick random captured piece to resurrect (player will target this later)
        resurrected = random.choice(captured)
        source.remove(resurrected)

        # Find open squares on player's back rank
        back_rank = 0 if piece.color == Color.WHITE else (BOARD_SIZE - 1)
        back_rank_squares = []
        for col in range(BOARD_SIZE):
            if self.board.get(back_rank, col) is None:
                back_rank_squares.append((back_rank, col))

        if not back_rank_squares:
            # No space on back rank - put piece back in captured
            source.append(resurrected)
            # Put sacrificed piece back
            self.board.set(sacrifice_pos[0], sacrifice_pos[1], sacrificed)
            return False
        
        # Place resurrected piece at random back rank position (player will target this later)
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

    # ── Chunk 2 Abilities: Priority Group 8 (Gender-Based Abilities) ──

    def is_piece_female(self, piece: Piece, row: int, col: int) -> bool:
        """Check if a piece is designated as female.
        Defaults: Donut and Katia are female. Pawns use their character gender from rulebook.
        """
        if piece.piece_type == PieceType.DONUT:
            return True
        if piece.piece_type == PieceType.KATIA:
            return True
        
        # Check if piece has custom gender designation
        key = (piece.color, row, col)
        if key in self.piece_genders:
            return self.piece_genders[key] == "female"
        
        # For pawns, check character gender from rulebook
        if piece.is_pawn and piece.pawn_name:
            from .pawns import FEMALE_PAWN_NAMES
            return piece.pawn_name in FEMALE_PAWN_NAMES
        
        return False

    def is_piece_male(self, piece: Piece, row: int, col: int) -> bool:
        """Check if a piece is designated as male.
        Defaults: Carl, Mongo, and Samantha are male. Pawns use their character gender from rulebook.
        """
        if piece.piece_type == PieceType.CARL:
            return True
        if piece.piece_type == PieceType.MONGO:
            return True
        if piece.piece_type == PieceType.SAMANTHA:
            return True
        
        # Check if piece has custom gender designation
        key = (piece.color, row, col)
        if key in self.piece_genders:
            return self.piece_genders[key] == "male"
        
        # For pawns, check character gender from rulebook
        if piece.is_pawn and piece.pawn_name:
            from .pawns import FEMALE_PAWN_NAMES
            return piece.pawn_name not in FEMALE_PAWN_NAMES
        
        return False

    def try_gun_show(self, anaconda_pos: Tuple[int, int], dice: DungeonDice,
                     die_index: int) -> bool:
        """Stripper Anaconda's Gun Show (Floor 5):
        All friendly male pieces get +2 to dice rolls for 2 turns.
        """
        piece = self.board.get(*anaconda_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Stripper Anaconda", "Juice Box"):
            return False
        if self.is_piece_suppressed(*anaconda_pos):
            return False

        success = dice.spend_die(die_index, 5)
        self.log_event("ability_roll", piece="Stripper Anaconda", ability="Gun Show",
                       die_value=dice.dice[die_index], floor=5, result="success" if success else "fail")
        if not success:
            return False

        # Set buff for 2 turns
        self.gun_show_active[piece.color] = 2
        
        self.log_event("gun_show", detail="All friendly male pieces get +2 for 2 turns")
        return True

    def try_succubus(self, signet_pos: Tuple[int, int], dice: DungeonDice,
                     die_index: int) -> bool:
        """Signet's Succubus (Floor 6):
        All enemy male pieces within 3 squares cannot move next turn.
        """
        piece = self.board.get(*signet_pos)
        if piece is None or not piece.is_pawn or piece.pawn_name not in ("Signet", "Juice Box"):
            return False
        if self.is_piece_suppressed(*signet_pos):
            return False

        success = dice.spend_die(die_index, 6)
        self.log_event("ability_roll", piece="Signet", ability="Succubus",
                       die_value=dice.dice[die_index], floor=6, result="success" if success else "fail")
        if not success:
            return False

        # Find all enemy male pieces within 3 squares
        r, c = signet_pos
        affected = []
        for dr in range(-3, 4):
            for dc in range(-3, 4):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.board.in_bounds(nr, nc):
                    target = self.board.get(nr, nc)
                    if target and target.color != piece.color:
                        if self.is_piece_male(target, nr, nc):
                            affected.append((nr, nc))
        
        # Add all affected pieces to succubus pending
        for pos in affected:
            self.succubus_pending.add(pos)
        
        self.log_event("succubus", affected_count=len(affected),
                       detail=f"{len(affected)} enemy male pieces cannot move next turn")
        return True

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
