"""Flask server for DCC Chess browser game."""

import copy
import json
import random
from flask import Flask, render_template, jsonify, request

from dcc_chess.pieces import Piece, PieceType, Color
from dcc_chess.board import Board, BOARD_SIZE, CENTER_SQUARE, PAWN_ROSTER, MAJOR_PIECE_ORDER
from dcc_chess.dice import DungeonDice
from dcc_chess.abilities import GameState
from dcc_chess.movement import all_legal_moves, is_checkmate, is_stalemate, is_in_check, resolve_orthrus_action
from dcc_chess.pawns import PAWN_CHARACTERS, AbilityTrigger
from dcc_chess.ai import smart_move, smart_abilities, random_draft, random_back_rank
from dcc_chess.ai_cards import resolve_custard_choice, resolve_too_boring_choice, draw_ai_card
from dcc_chess.boss import resolve_boss_movement

app = Flask(__name__)

# ── In-memory game store (single game at a time) ─────────────────
game_data = {}

# ── Dev Game "Undo Last Move" history (Dev Game mode only) ───────
# Each entry is a deep copy of game_data taken just before a move-completing
# action mutates the board/dice/turn state, so undo can restore it wholesale.
move_history = []
MAX_UNDO_HISTORY = 50  # cap to bound memory in long dev sessions


def _snapshot_for_undo():
    """Push a deep copy of the current game_data onto the undo history stack."""
    if game_data.get("mode") != "dev":
        return
    move_history.append(copy.deepcopy(game_data))
    if len(move_history) > MAX_UNDO_HISTORY:
        move_history.pop(0)


# ── Short display names for pieces ───────────────────────────────
PAWN_SHORT_NAMES = {
    "Zev": "ZEV",
    "The AI": "AI",
    "Mordecai": "MORD",
    "Prepotente": "PREP",
    "Elle McGib": "ELLE",
    "Imani": "IMANI",
    "Slugalo": "SLUG",
    "Louie": "LOUIE",
    "Sledge": "SLEDGE",
    "Stripper Anaconda": "ANACONDA",
    "Quasar": "QUASAR",
    "Lucia Mar": "LUCIA",
    "Chris": "CHRIS",
    "Juice Box": "JUICE",
    "Florin": "FLORIN",
    "Garret": "GARRET",
    "Signet": "SIGNET",
    "Miriam Dom": "MIRIAM",
    "Orthrus": "ORTH",
    "Raul the Crab": "RAUL",
    "Bad Llama": "LLAMA",
}

MAJOR_SHORT_NAMES = {
    PieceType.CARL: "CARL",
    PieceType.DONUT: "DONUT",
    PieceType.MONGO: "MONGO",
    PieceType.KATIA: "KATIA",
    PieceType.SAMANTHA: "SAM",
    PieceType.DUNGEON_BOSS: "BOSS",
}

# ── Major piece ability definitions (for sidebar display) ────────
MAJOR_ABILITIES = {
    "Carl": [
        {"name": "Leader", "floor": 0, "description": "Combine all available dice this turn (both rolled dice, or your banked die plus your rolled die) into a pull distance. Choose one friendly back line major piece (Donut, Katia, or Samantha) and pull it toward Carl by up to that many squares, along that piece's own normal movement path. Carl still makes his normal move this turn.", "uses_per_game": 2, "requires_combined": True},
        {"name": "Plot Armor", "floor": 8, "description": "Carl moves up to 3 squares in any direction a King can normally move (player chooses 1, 2, or 3 squares). Cannot pass through occupied squares, but can capture the piece he lands on. The destination must not leave Carl in check.", "uses_per_game": 1, "requires_combined": True},
        {"name": "Jug-o-Boom", "floor": 4, "description": "Carl tosses a bomb up to 3 squares in any direction to attack a summoned boss.", "is_boss_only": True},
    ],
    "Donut": [
        {"name": "Puddle Jump", "floor": 5, "description": "Donut moves like a Queen but can pass through or jump past any pieces in her path to reach her destination. She cannot harm pieces she passes through."},
        {"name": "Cockroach", "floor": 7, "description": "Resurrect one captured friendly piece and place it on any open square adjacent to Donut.", "uses_per_game": 1, "requires_combined": True},
        {"name": "Magic Missile", "floor": 5, "description": "Shoots a magic missile 5 squares in any direction to damage a summoned boss.", "is_boss_only": True},
    ],
    "Mongo": [
        {"name": "Pet Carrier", "floor": 4, "description": "Remove Mongo from the board and store him. He can be released at any time on your turn at no cost and must spawn within 2 squares of Donut. If Donut is captured while Mongo is stored, Mongo is also captured. Only 1 Mongo can be stored at a time."},
        {"name": "Rampage", "floor": 8, "description": "Mongo captures any piece within his L-shaped movement path, not just the final destination.", "uses_per_game": 1, "requires_combined": True},
        {"name": "Gorefest", "floor": 4, "description": "Mongo attacks 2 squares from his current location in any direction to damage a summoned boss.", "is_boss_only": True},
    ],
    "Katia": [
        {"name": "She Tank", "floor": 6, "description": "Prevent one enemy piece from moving on its next turn. Can be used as a reaction with a banked die before the enemy moves, or at the start of your own turn.", "uses_per_game": 2, "is_reaction": True},
        {"name": "Blitzed", "floor": 5, "description": "Any one piece on your side skips its movement requirement this turn. That piece can still use an ability."},
        {"name": "I Need My Space", "floor": 3, "description": "Pushes the boss 2 squares directly away from Katia. If the boss is pushed into a piece that piece is permanently killed.", "is_boss_only": True},
    ],
    "Samantha": [
        {"name": "Slut Shame", "floor": 8, "description": "Samantha swallows any pawn within 3 squares, temporarily removing it from the board. It respawns within 1 square of Samantha within 5 turns.", "uses_per_game": 1, "requires_combined": True},
        {"name": "Miss Me?", "floor": 5, "description": "Force a reroll of any dice currently in play. Can be used at the start of your turn to reroll your own dice, or as a reaction using a banked die to counter an enemy roll.", "is_reaction": True},
        {"name": "IWKYM", "floor": 6, "description": "When adjacent to the boss Samantha holds it still for 2 full turns. Boss cannot move but can still take damage. After 2 turns Samantha releases and respawns on her back rank.", "is_boss_only": True},
    ],
}


def serialize_board(board):
    """Convert board to JSON-friendly 11x11 grid."""
    grid = []
    for r in range(BOARD_SIZE):
        row = []
        for c in range(BOARD_SIZE):
            p = board.get(r, c)
            if p is None:
                row.append(None)
            else:
                short = PAWN_SHORT_NAMES.get(p.pawn_name, "") if p.is_pawn else MAJOR_SHORT_NAMES.get(p.piece_type, "?")
                full_name = p.pawn_name if p.pawn_name else p.piece_type.value
                piece_data = {
                    "type": p.piece_type.value,
                    "color": p.color.value,
                    "name": full_name,
                    "short": short,
                    "is_pawn": p.is_pawn,
                }
                if p.pawn_name == "Orthrus":
                    is_head = (r, c) == p.orthrus_head_pos
                    piece_data["is_orthrus_head"] = is_head
                    piece_data["orthrus_direction"] = p.orthrus_direction if is_head else None
                    piece_data["orthrus_head_pos"] = list(p.orthrus_head_pos) if p.orthrus_head_pos else None
                row.append(piece_data)
            row_data = row
        grid.append(row_data)
    return grid


def serialize_dice(dice):
    """Serialize dice state with banking info."""
    if not dice.dice:
        return None
    return {
        "values": dice.dice[:],
        "used": dice.used[:],
        "banked_die": dice.banked_die,
        "pulled_from_bank": dice.pulled_from_bank,
        # This turn's ability-cost modifier (AI's Pet -1, Dirty Tootsies +1,
        # Raul's Group Climax -2; additive). The frontend applies it when
        # showing/checking ability costs so the UI matches the server's checks.
        "floor_modifier": dice.floor_modifier,
    }


def get_piece_abilities(piece, game_state, row, col):
    """Get ability info for a piece for the sidebar."""
    abilities = []
    color = piece.color

    if piece.is_pawn and piece.pawn_name == "Juice Box":
        # Juice Box has no ability of her own — she shows one entry per pawn
        # ability she has captured (instead of a generic Shapeshift button).
        captured_list = game_state.juice_box_captured.get(game_state.juice_box_key((row, col)), [])
        for captured_name in captured_list:
            cchar = PAWN_CHARACTERS.get(captured_name)
            if not cchar:
                continue
            cab = cchar.ability
            abilities.append({
                "name": cab.name,
                "floor": cab.floor_number,
                "description": cab.description,
                "trigger": cab.trigger.value,
                "uses_left": None,
                "uses_per_game": None,
                "requires_combined": getattr(cab, 'requires_combined', False),
                "juice_box_source_pawn": captured_name,
            })
    elif piece.is_pawn and piece.pawn_name:
        char = PAWN_CHARACTERS.get(piece.pawn_name)
        if char:
            ab = char.ability
            key = f"{color.value}_{piece.pawn_name}"
            uses_left = None
            if ab.uses_per_game is not None:
                uses_left = game_state.pawn_ability_uses.get(key, {}).get(ab.name, ab.uses_per_game)
            abilities.append({
                "name": ab.name,
                "floor": ab.floor_number,
                "description": ab.description,
                "trigger": ab.trigger.value,
                "uses_left": uses_left,
                "uses_per_game": ab.uses_per_game,
                "requires_combined": getattr(ab, 'requires_combined', False),
            })
    else:
        type_name = piece.piece_type.value
        major_abs = MAJOR_ABILITIES.get(type_name, [])
        for mab in major_abs:
            uses_left = None
            if mab.get("uses_per_game"):
                # Track uses for new abilities
                if type_name == "Carl" and mab["name"] == "Plot Armor":
                    uses_left = 0 if game_state.plot_armor_used.get(color, False) else 1
                elif type_name == "Carl" and mab["name"] == "Leader":
                    uses_left = game_state.leader_uses.get(color, 2)
                elif type_name == "Donut" and mab["name"] == "Cockroach":
                    uses_left = 0 if game_state.cockroach_used.get(color, False) else 1
                elif type_name == "Mongo" and mab["name"] == "Rampage":
                    k = (color, id(piece))
                    uses_left = 0 if game_state.rampage_used.get(k, False) else 1
                elif type_name == "Katia" and mab["name"] == "She Tank":
                    uses_left = game_state.she_tank_uses.get(color, 2)
                elif type_name == "Samantha" and mab["name"] == "Slut Shame":
                    k = (color, id(piece))
                    uses_left = 0 if game_state.slut_shame_used.get(k, False) else 1

            abilities.append({
                "name": mab["name"],
                "floor": mab["floor"],
                "description": mab["description"],
                "trigger": "floor_roll",
                "uses_left": uses_left,
                "uses_per_game": mab.get("uses_per_game"),
                "is_boss_only": mab.get("is_boss_only", False),
                "is_reaction": mab.get("is_reaction", False),
                "requires_combined": mab.get("requires_combined", False),
            })
    return abilities


def get_all_player_pieces(game_state, color):
    """Get all pieces for a player with their abilities."""
    pieces = []
    board = game_state.board
    color_enum = Color.WHITE if color == "white" else Color.BLACK
    for r, c, p in board.all_pieces(color_enum):
        short = PAWN_SHORT_NAMES.get(p.pawn_name, "") if p.is_pawn else MAJOR_SHORT_NAMES.get(p.piece_type, "?")
        full_name = p.pawn_name if p.pawn_name else p.piece_type.value
        pieces.append({
            "row": r,
            "col": c,
            "type": p.piece_type.value,
            "name": full_name,
            "short": short,
            "is_pawn": p.is_pawn,
            "abilities": get_piece_abilities(p, game_state, r, c),
            "suppressed": game_state.is_piece_suppressed(r, c),
        })
    return pieces


def _piece_label(piece):
    return piece.pawn_name if (piece.is_pawn and piece.pawn_name) else piece.piece_type.value


def _roster_color_for(pawn_name, game_data):
    if pawn_name in game_data.get("white_pawns", []):
        return Color.WHITE
    if pawn_name in game_data.get("black_pawns", []):
        return Color.BLACK
    return None


def get_status_effects_summary(gs, game_data):
    """Summarize all currently active status effects, grouped by side, for the sidebar panel."""
    board = gs.board
    result = {"white": [], "black": []}

    def add(color, piece_name, effect_name, turns):
        if color is None:
            return
        result[color.value].append({"piece": piece_name, "effect": effect_name, "turns": turns})

    for pos in gs.frozen_pieces:
        piece = board.get(*pos)
        if piece:
            add(piece.color, _piece_label(piece), "Frozen", 1)

    for pos in gs.suppressed_pieces:
        piece = board.get(*pos)
        if piece:
            add(piece.color, _piece_label(piece), "Suppressed", 1)

    for pos in gs.restrained_pieces:
        piece = board.get(*pos)
        if piece:
            add(piece.color, _piece_label(piece), "Restrained", 1)

    for pos in gs.she_tank_targets:
        piece = board.get(*pos)
        if piece:
            add(piece.color, _piece_label(piece), "She Tank", 1)

    for pos, turns in gs.iron_wall_pieces.items():
        if turns <= 0:
            continue
        piece = board.get(*pos)
        if piece and piece.is_pawn and piece.pawn_name == "Sledge":
            add(piece.color, "Sledge", "Body Guard", turns)

    for entry in gs.mordecai_respawn_pending:
        add(entry["color"], "Mordecai", "Ghost Zone (awaiting respawn)", entry["turns_left"])

    if gs.air_strike_zones:
        owner = _roster_color_for("Louie", game_data)
        add(owner, "Louie", "Air Strike Zone", max(gs.air_strike_zones.values()))

    if gs.lava_zones:
        chris_color = _roster_color_for("Chris", game_data) if gs.chris_stuck else None
        if chris_color is not None:
            add(chris_color, "Chris", "Lava Surge", max(gs.lava_zones.values()))
        else:
            owner = _roster_color_for("Bad Llama", game_data)
            add(owner, "Bad Llama", "Lava Zone", max(gs.lava_zones.values()))

    for color, active in gs.zev_buff_active.items():
        if active:
            add(color, "Zev", "Biggest Fan (buff)", None)

    for color, active in gs.group_climax_active.items():
        if active:
            add(color, "Raul the Crab", "Group Climax (buff)", None)

    return result


def serialize_captured(board):
    """Serialize each side's captured pieces for the sidebar panel."""
    def entry(p):
        return {
            "name": _piece_label(p),
            "permanently_dead": bool(p.permanently_dead or (p.is_pawn and p.pawn_name == "Orthrus")),
        }
    return {
        "white": [entry(p) for p in board.captured[Color.WHITE]],
        "black": [entry(p) for p in board.captured[Color.BLACK]],
    }


def build_game_state_response():
    """Build the full game state JSON response."""
    gs = game_data.get("game_state")
    board = gs.board
    dice = game_data.get("dice")
    game = game_data

    current = gs.current_player.value
    opponent = gs.current_player.opponent

    # Check game end
    game_over = False
    winner = None
    reason = ""
    if game_data.get("game_over"):
        game_over = True
        winner = game_data.get("winner")
        reason = game_data.get("result_reason", "")

    # Matt's Drunk Again: each side's sidebar panel shows whichever army that seat
    # currently controls, so "White"'s panel displays Black's pieces (with Black's
    # abilities) while the swap is active, and vice versa.
    white_panel_color = "black" if gs.swap_active else "white"
    black_panel_color = "white" if gs.swap_active else "black"

    resp = {
        "board": serialize_board(board),
        "current_player": current,
        "turn_number": gs.turn_number,
        "dice": serialize_dice(dice) if dice else None,
        "phase": game_data.get("phase", "move"),  # "placement", "move", "ability", "game_over"
        "game_over": game_over,
        "winner": winner,
        "result_reason": reason,
        "player_pieces": get_all_player_pieces(gs, gs.controlled_color(gs.current_player).value),
        "white_player_pieces": get_all_player_pieces(gs, white_panel_color),
        "black_player_pieces": get_all_player_pieces(gs, black_panel_color),
        "mode": game_data.get("mode", "pvp"),
        "events": gs.events[-20:] if gs.events else [],  # Last 20 events
        "white_pawns": game_data.get("white_pawns", []),
        "black_pawns": game_data.get("black_pawns", []),
        "placement_player": game_data.get("placement_player"),
        "white_pieces_to_place": game_data.get("white_pieces_to_place"),
        "black_pieces_to_place": game_data.get("black_pieces_to_place"),
        "air_strike_zones": [[r, c] for r, c in gs.air_strike_zones.keys()],
        "lava_zones": [[r, c] for r, c in gs.lava_zones.keys()],
        "frozen_pieces": [[r, c] for r, c in gs.frozen_pieces],
        "suppressed_pieces": [[r, c] for r, c in gs.suppressed_pieces],
        "restrained_pieces": [[r, c] for r, c in gs.restrained_pieces],
        "she_tank_targets": [[r, c] for r, c in gs.she_tank_targets],
        "iron_wall_pieces": {f"{r},{c}": t for (r, c), t in gs.iron_wall_pieces.items() if t > 0},
        "ghost_tokens": {f"{r},{c}": t for (r, c), t in gs.ghost_tokens.items() if t > 0},
        # Meaningless before both Carls are even on the board, and meaningless again
        # for a boss-co-op "fallen" player who no longer has a king at all -- in both
        # cases is_in_check() treats a missing king as "in check" (for the legitimate
        # mid-game king-captured case), which would otherwise show a false check banner.
        "carl_in_check": (
            is_in_check(board, gs.current_player)
            if game_data.get("phase") != "placement" and board.find_king(gs.current_player) is not None
            else False
        ),
        "status_effects": get_status_effects_summary(gs, game_data),
        "captured_pieces": serialize_captured(board),
        "can_undo": game_data.get("mode") == "dev" and len(move_history) > 0,
        "ai_card_active": gs.ai_card_active,
        "ai_deck_remaining": gs.ai_deck_remaining,
        "system_reset_active": gs.system_reset_active,
        "main_character_syndrome_active": gs.main_character_syndrome_active,
        "juice_box_cooldown": {c.value: v for c, v in gs.juice_box_cooldown.items()},
        "insta_kill_card": {c.value: has for c, has in gs.insta_kill_card.items()},
        "pending_ai_card_decision": gs.pending_ai_card_decision,
        "swap_active": gs.swap_active,
        "swap_turns_remaining": gs.swap_turns_remaining,
        "boss_active": gs.boss_active,
        "active_boss": gs.active_boss,
        "boss_hp": gs.boss_hp,
        "boss_max_hp": gs.boss_max_hp,
        "boss_position": list(gs.boss_position) if gs.boss_position else None,
        "boss_squares": [list(s) for s in gs.boss_squares],
        "boss_turn_active": gs.boss_turn_active,
        "boss_turn_rolls": dict(gs.boss_turn_rolls),
        "fallen_players": [c.value for c in gs.fallen_players],
        # True when the current player has no legal move available. During a Boss
        # Event the game no longer ends by checkmate/stalemate (Bug 3), so the
        # frontend uses this to auto-pass a stuck player's turn instead of
        # soft-locking (there is no manual End Turn button).
        "current_player_stuck": (
            game_data.get("phase") not in ("placement", "boss_turn", "game_over")
            and not gs.get_legal_moves_with_status(gs.controlled_color(gs.current_player))
        ),
    }
    return resp


def _end_game_if_no_legal_moves(gs) -> bool:
    """Check whether the player about to move has any legal move available.

    If not, end the game immediately as checkmate (if they're in check) or
    stalemate, mirroring the check already done for the AI's turn. Returns
    True if the game was ended, False if the player has at least one legal
    move and can proceed normally (e.g. roll dice).

    During a Matt's Drunk Again control swap, "has a legal move" is checked
    against whichever army gs.current_player actually controls this turn --
    otherwise a swap could falsely end the game while the player still has
    moves available with the pieces they're currently allowed to use. Whether
    it's checkmate vs. stalemate still reads gs.current_player's own true
    king, per the original-colors rule for game-end conditions.
    """
    if gs.get_legal_moves_with_status(gs.controlled_color(gs.current_player)):
        return False
    # During a Boss Event the fight takes priority: the game never ends by
    # checkmate/stalemate while a boss is active (Bug 3). This covers both a
    # fallen (kingless) boss co-op player and a player whose whole army happens
    # to have no legal non-capture move. They simply have nothing to move this
    # turn; the frontend auto-passes the turn (see runTurnTransition).
    if gs.boss_active:
        return False
    if is_in_check(gs.board, gs.current_player):
        game_data["winner"] = gs.current_player.opponent.value
        game_data["result_reason"] = "checkmate"
    else:
        game_data["winner"] = None
        game_data["result_reason"] = "stalemate"
    game_data["game_over"] = True
    game_data["phase"] = "game_over"
    return True


def _begin_next_phase_after_turn(gs, ended_color):
    """Decide the phase that follows gs.end_turn() having just ended `ended_color`'s
    turn. If Black just finished and a boss is active, a Boss Turn round happens
    first -- both players roll 1 die each to move the boss -- before it becomes
    White's move phase again. In PvAI mode Black is AI-controlled, so its boss
    roll is submitted automatically so the flow doesn't stall waiting on it.
    """
    if ended_color == Color.BLACK and gs.boss_active:
        game_data["phase"] = "boss_turn"
        gs.boss_turn_active = True
        gs.boss_turn_rolls = {"white": None, "black": None}
        gs.log_event("boss_turn_begin", boss=gs.active_boss)
        if game_data.get("mode") == "pvai":
            _submit_boss_roll(gs, "black")
    else:
        game_data["phase"] = "move"


def _submit_boss_roll(gs, color):
    """Roll one die for `color`'s side of the Boss Turn compass roll. If both
    sides have now rolled, resolves the boss's movement immediately and returns
    to the move phase.
    """
    roll = random.randint(1, 6)
    gs.boss_turn_rolls[color] = roll
    gs.log_event("boss_turn_roll", color=color, value=roll)

    if gs.boss_turn_rolls["white"] is not None and gs.boss_turn_rolls["black"] is not None:
        resolve_boss_movement(gs)
        game_data["phase"] = "move"


# ── Routes ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/roster", methods=["GET"])
def get_roster():
    """Return the full pawn roster with ability info."""
    roster = []
    for name in PAWN_ROSTER:
        char = PAWN_CHARACTERS[name]
        roster.append({
            "name": name,
            "short": PAWN_SHORT_NAMES.get(name, name),
            "ability_name": char.ability.name,
            "ability_description": char.ability.description,
            "floor_number": char.ability.floor_number,
            "trigger": char.ability.trigger.value,
            "uses_per_game": char.ability.uses_per_game,
            "requires_combined": getattr(char.ability, "requires_combined", False),
            "is_female": char.is_female,
        })
    return jsonify(roster)


@app.route("/new_game", methods=["POST"])
def new_game():
    """Start a new game with placement phase or instant start for dev mode.

    Body: {mode: "pvp"|"pvai"|"dev", white_pawns: [...], black_pawns: [...]}
    """
    data = request.get_json(force=True)
    mode = data.get("mode", "pvp")
    white_pawns = data.get("white_pawns")
    black_pawns = data.get("black_pawns")

    if not white_pawns or len(white_pawns) != 8:
        return jsonify({"error": "white_pawns must be a list of 8 pawn names"}), 400
    if not black_pawns or len(black_pawns) != 8:
        return jsonify({"error": "black_pawns must be a list of 8 pawn names"}), 400

    board = Board()
    gs = GameState(board)
    gs.init_pawn_ability_tracking()

    dice = DungeonDice()

    # Order pieces for placement: Samantha, Katia, Mongo, Donut, Carl, Samantha, Katia, Mongo
    placement_order = [
        PieceType.SAMANTHA.value,
        PieceType.KATIA.value,
        PieceType.MONGO.value,
        PieceType.DONUT.value,
        PieceType.CARL.value,
        PieceType.SAMANTHA.value,
        PieceType.KATIA.value,
        PieceType.MONGO.value,
    ]
    
    game_data.clear()
    move_history.clear()
    game_data.update({
        "game_state": gs,
        "dice": dice,
        "mode": mode,
        "phase": "placement" if mode != "dev" else "move",
        "placement_player": "white",  # white places first
        "game_over": False,
        "winner": None,
        "result_reason": "",
        "white_pawns": white_pawns,
        "black_pawns": black_pawns,
        "moved_from": None,
        "moved_to": None,
        "white_pieces_to_place": placement_order + white_pawns,  # Majors then pawns
        "black_pieces_to_place": placement_order + black_pawns,
    })
    
    # Dev mode: auto-place all pieces immediately
    if mode == "dev":
        board_layout = data.get("board_layout")
        if board_layout:
            # Custom layout from Dev Settings staging board (11×11 grid of piece objects or nulls)
            for r in range(11):
                row_data = board_layout[r] if r < len(board_layout) else []
                for c in range(11):
                    cell = row_data[c] if c < len(row_data) else None
                    if cell:
                        color = Color(cell["color"])
                        if cell.get("is_pawn"):
                            piece = Piece(PieceType.PAWN, color, pawn_name=cell["name"])
                            if cell["name"] == "Orthrus":
                                # The staging board sends both his squares (butt and head,
                                # distinguished by is_orthrus_head) so it can render his 1×2
                                # body -- only place him once, anchored at the butt cell.
                                # If his head square collides with another staged piece,
                                # he's silently skipped (dev-tool limitation).
                                if not cell.get("is_orthrus_head"):
                                    board.place_orthrus_body(piece, r, c)
                                continue
                        else:
                            piece = Piece(PieceType(cell["type"]), color)
                        board.set(r, c, piece)
        else:
            # Default: random auto-placement
            for col, piece_name in enumerate(placement_order):
                piece_type_enum = PieceType(piece_name)
                piece = Piece(piece_type_enum, Color.WHITE)
                board.set(0, col, piece)

            shuffled_white = white_pawns[:]
            random.shuffle(shuffled_white)
            for i, pawn_name in enumerate(shuffled_white):
                piece = Piece(PieceType.PAWN, Color.WHITE, pawn_name=pawn_name)
                board.place_piece(1, i + 1, piece, False)

            for col, piece_name in enumerate(placement_order):
                piece_type_enum = PieceType(piece_name)
                piece = Piece(piece_type_enum, Color.BLACK)
                board.set(10, col, piece)

            shuffled_black = black_pawns[:]
            random.shuffle(shuffled_black)
            for i, pawn_name in enumerate(shuffled_black):
                piece = Piece(PieceType.PAWN, Color.BLACK, pawn_name=pawn_name)
                board.place_piece(9, i + 1, piece, False)

        # Start the first turn immediately: roll dice and enter ability phase
        gs.current_player = Color.WHITE
        gs.start_turn()
        gs.update_katia_threats()
        if not _end_game_if_no_legal_moves(gs):
            dice.roll()
            gs.log_event("dice_roll", values=dice.dice[:])
            gs.promote_group_climax(dice)
            gs.draw_ai_card_if_triggered(dice.dice[0], dice.dice[1], gs.current_player, dice=dice)
            game_data["phase"] = "ability"

    return jsonify(build_game_state_response())


@app.route("/place_piece", methods=["POST"])
def place_piece():
    """Place a piece during placement phase.
    
    Body: {row, col}
    The first piece in the pieces_to_place list is automatically selected.
    """
    if game_data.get("phase") != "placement":
        return jsonify({"error": "Not in placement phase"}), 400
    
    data = request.get_json(force=True)
    row = data.get("row")
    col = data.get("col")
    
    if None in (row, col):
        return jsonify({"error": "Missing placement data"}), 400
    
    gs = game_data["game_state"]
    placement_player = game_data["placement_player"]
    color = Color.WHITE if placement_player == "white" else Color.BLACK
    
    pieces_key = f"{placement_player}_pieces_to_place"
    pieces_to_place = game_data[pieces_key]
    
    if not pieces_to_place or len(pieces_to_place) == 0:
        return jsonify({"error": "No pieces left to place"}), 400
    
    # Get the first piece in the list (auto-selected)
    piece_name = pieces_to_place[0]
    
    # Determine if it's a major piece or pawn
    major_piece_names = [PieceType.CARL.value, PieceType.DONUT.value, PieceType.MONGO.value, 
                         PieceType.KATIA.value, PieceType.SAMANTHA.value]
    
    if piece_name in major_piece_names:
        # It's a major piece
        piece_type_enum = PieceType(piece_name)
        piece = Piece(piece_type_enum, color)
        is_major = True
    else:
        # It's a pawn
        piece = Piece(PieceType.PAWN, color, pawn_name=piece_name)
        is_major = False
    
    # Try to place the piece
    if not gs.board.place_piece(row, col, piece, is_major):
        return jsonify({"error": "Invalid placement position"}), 400
    
    # Remove the placed piece from the list
    pieces_to_place.pop(0)
    
    # Check if player finished placing
    if len(pieces_to_place) == 0:
        if placement_player == "white":
            # Switch to black
            game_data["placement_player"] = "black"
            
            # If vs AI, auto-place AI pieces
            if game_data.get("mode") == "pvai":
                _ai_auto_place_pieces(gs, game_data)
        else:
            # Both done, start game
            game_data["phase"] = "move"
            game_data["placement_player"] = None
    
    return jsonify(build_game_state_response())


def _ai_auto_place_pieces(gs, game_data):
    """Auto-place all AI pieces using random valid placement."""
    pieces_to_place = game_data["black_pieces_to_place"]
    major_piece_names = [PieceType.CARL.value, PieceType.DONUT.value, PieceType.MONGO.value, 
                         PieceType.KATIA.value, PieceType.SAMANTHA.value]
    
    for piece_name in pieces_to_place[:]:  # Copy list to iterate
        is_major = piece_name in major_piece_names
        
        if is_major:
            piece_type_enum = PieceType(piece_name)
            piece = Piece(piece_type_enum, Color.BLACK)
            valid_row = 10
        else:
            piece = Piece(PieceType.PAWN, Color.BLACK, pawn_name=piece_name)
            valid_row = 9
        
        # Find random valid column
        available_cols = [c for c in range(BOARD_SIZE) if gs.board.get(valid_row, c) is None]
        if available_cols:
            col = random.choice(available_cols)
            gs.board.place_piece(valid_row, col, piece, is_major)
    
    # Clear the AI's placement list
    game_data["black_pieces_to_place"] = []
    game_data["placement_player"] = None
    game_data["phase"] = "move"


@app.route("/start_turn", methods=["POST"])
def start_turn_route():
    """Start a new turn by rolling dice.
    
    New turn flow: Roll Dice → Abilities → Move → End Turn
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    if gs.pending_ai_card_decision:
        return jsonify({"error": "Resolve the pending AI Card decision first"}), 400
    if game_data.get("game_over"):
        return jsonify({"error": "Game is over"}), 400
    if game_data.get("phase") != "move":
        return jsonify({"error": "Not in move phase"}), 400

    # Start turn
    gs.start_turn()
    gs.update_katia_threats()

    if _end_game_if_no_legal_moves(gs):
        return jsonify(build_game_state_response())

    # Roll dice - only 1 die if current player has banked die, otherwise 2 dice
    dice = game_data["dice"]
    player = gs.current_player.value
    if dice.banked_die[player] is not None:
        # Player has a banked die, only roll 1 die
        dice.dice = [random.randint(1, 6)]
        dice.used = [False]
        dice.floor_modifier = 0
    else:
        # No banked die, roll 2 dice normally
        dice.roll()
    
    gs.log_event("dice_roll", values=dice.dice[:])
    gs.promote_group_climax(dice)

    # Check for AI summon trigger
    if len(dice.dice) == 2:
        gs.draw_ai_card_if_triggered(dice.dice[0], dice.dice[1], gs.current_player, dice=dice)

    game_data["phase"] = "ability"
    return jsonify(build_game_state_response())


@app.route("/legal_moves", methods=["GET"])
def legal_moves():
    """Get legal moves for a piece at (row, col).

    Query: ?row=N&col=N
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400

    row = int(request.args.get("row", -1))
    col = int(request.args.get("col", -1))

    piece = gs.board.get(row, col)
    if piece is None:
        return jsonify({"moves": []})
    if piece.color != gs.controlled_color(gs.current_player):
        return jsonify({"moves": []})

    # Get status-filtered legal moves for this piece
    all_moves = gs.get_legal_moves_with_status(gs.controlled_color(gs.current_player))
    piece_moves = [list(to) for (fr, _), to in all_moves if (fr, _) == (row, col)]
    # Actually need to match from_pos properly
    piece_moves = []
    for (fr, fc), (tr, tc) in all_moves:
        if fr == row and fc == col:
            piece_moves.append([tr, tc])

    return jsonify({"moves": piece_moves})


def _resolve_capture_result(gs, cap_result, from_pos, to_pos):
    """Execute the outcome of an attempt_capture() call for a human-initiated move.

    Returns the captured Piece (or None).
    """
    captured = None
    if cap_result == "captured":
        captured = gs.board.make_move(from_pos, to_pos)
        if captured:
            attacker = gs.board.get(*to_pos)
            gs.process_post_capture(captured, to_pos, attacker, from_pos)
    elif cap_result == "defended_elle":
        gs.log_event("move_blocked", reason="Elle McGib Frozen Immunity")
    elif cap_result == "defended_orthrus":
        gs.log_event("move_blocked", reason="Orthrus can only be captured by major pieces")
    elif cap_result == "defended_quasar":
        attacker = gs.board.get(*from_pos)
        gs.board.set(from_pos[0], from_pos[1], None)
        if attacker:
            gs.board.captured[attacker.color].append(attacker)
            gs.log_event("mediation_capture", captured=repr(attacker))
    else:
        captured = gs.board.make_move(from_pos, to_pos)
    return captured


def _finish_move_and_check_game_over(gs, color, from_pos, to_pos, captured):
    """Shared tail of move resolution: log the move, check for game end, end the turn."""
    moved_piece = gs.board.get(*to_pos)
    gs.log_event("move", piece=repr(moved_piece) if moved_piece else "?",
                 from_pos=from_pos, to_pos=to_pos,
                 captured=repr(captured) if captured else None)

    game_data["moved_from"] = from_pos
    game_data["moved_to"] = to_pos

    if captured is not None and captured.is_king:
        # Carl never comes back through any resurrection path in this codebase,
        # but mark it explicitly so that stays true even if one is added later.
        captured.permanently_dead = True

    # During a Matt's Drunk Again swap, `color` (the acting player) may have just
    # moved a piece of the OPPOSITE true color -- whoever's king could have just
    # been threatened is the opponent of the piece that actually moved, not
    # necessarily color.opponent. `color` itself still correctly identifies who
    # gets credit for the win.
    opponent = moved_piece.color.opponent if moved_piece else color.opponent

    # A missing king takes priority over checkmate/stalemate -- those only mean
    # anything while a king is still on the board. During an active boss battle
    # a missing king doesn't end the whole game; see _handle_carl_fallen.
    if gs.board.find_king(opponent) is None:
        if _handle_carl_fallen(gs, color, opponent):
            return
    elif not gs.boss_active:
        # During a Boss Event the fight takes priority -- the game does not end by
        # checkmate/stalemate until the boss is defeated (Bug 3).
        if is_checkmate(gs.board, opponent):
            game_data["game_over"] = True
            game_data["winner"] = color.value
            game_data["result_reason"] = "checkmate"
            game_data["phase"] = "game_over"
            gs.end_turn()
            return

        if is_stalemate(gs.board, opponent):
            game_data["game_over"] = True
            game_data["winner"] = None
            game_data["result_reason"] = "stalemate"
            game_data["phase"] = "game_over"
            gs.end_turn()
            return

    # Move complete - automatically end turn
    gs.end_turn()
    _begin_next_phase_after_turn(gs, color)


def _handle_carl_fallen(gs, color: Color, opponent: Color) -> bool:
    """`opponent`'s Carl is gone (just captured this move, or already gone).

    Outside a boss battle this ends the game immediately as before (normal
    PvP king-capture rules). During an active boss battle it doesn't end the
    game: `opponent` is marked fallen and the surviving player keeps playing
    both armies against the boss -- opponent's remaining pieces stay on the
    board as extra resources -- until either the boss is defeated or both
    Carls are gone (draw).

    Returns True if this call set game_data['game_over'] (caller should stop
    without also calling gs.end_turn()/advancing phase itself).
    """
    if not gs.boss_active:
        game_data["game_over"] = True
        game_data["winner"] = color.value
        game_data["result_reason"] = "king_captured"
        game_data["phase"] = "game_over"
        gs.end_turn()
        return True

    if opponent in gs.fallen_players:
        return False

    gs.fallen_players.add(opponent)
    gs.log_event("player_fallen", color=opponent.value, surviving_color=color.value)

    if len(gs.fallen_players) >= 2:
        game_data["game_over"] = True
        game_data["winner"] = None
        game_data["result_reason"] = "both_fallen"
        game_data["phase"] = "game_over"
        gs.end_turn()
        return True

    return False


@app.route("/move", methods=["POST"])
def make_move():
    """Execute a move.

    Body: {from_row, from_col, to_row, to_col}
    New flow: abilities happen BEFORE movement, so this is called after ability phase.
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    if gs.pending_ai_card_decision:
        return jsonify({"error": "Resolve the pending AI Card decision first"}), 400
    if game_data.get("game_over"):
        return jsonify({"error": "Game is over"}), 400
    if game_data.get("phase") != "ability":
        return jsonify({"error": "Not in ability phase - must roll dice first"}), 400
    if game_data.get("pending_elle_decision"):
        return jsonify({"error": "Resolve the Elle McGib Frozen Immunity decision first"}), 400

    data = request.get_json(force=True)
    fr = data.get("from_row")
    fc = data.get("from_col")
    tr = data.get("to_row")
    tc = data.get("to_col")

    if None in (fr, fc, tr, tc):
        return jsonify({"error": "Missing position data"}), 400

    from_pos = (fr, fc)
    to_pos = (tr, tc)

    # During a Boss Event, regular PvP captures are disabled. Pieces may move for
    # positioning, but any move that would land on an occupied square (friendly or
    # enemy) is rejected -- only Special Event Attacks can deal damage, and only to
    # the boss. (get_legal_moves_with_status already excludes these; this is an
    # explicit, clearer guard. An Orthrus body-shift onto its own second square is
    # not a capture.)
    if gs.boss_active:
        _mover = gs.board.get(*from_pos)
        _target = gs.board.get(*to_pos)
        if _target is not None and _target is not _mover:
            return jsonify({"error": "Captures are disabled during a Boss Event — only Special Event Attacks can damage the boss"}), 400

    # Validate move (Matt's Drunk Again: validate against the army gs.current_player
    # actually controls this turn, not necessarily their own true color)
    all_moves = gs.get_legal_moves_with_status(gs.controlled_color(gs.current_player))
    if (from_pos, to_pos) not in all_moves:
        return jsonify({"error": "Illegal move"}), 400

    color = gs.current_player

    # Execute move with capture interception
    target = gs.board.get(*to_pos)
    captured = None

    piece_at_from = gs.board.get(*from_pos)
    is_orthrus_move = (
        piece_at_from is not None and piece_at_from.is_pawn
        and piece_at_from.pawn_name == "Orthrus"
        and from_pos == piece_at_from.orthrus_head_pos
    )

    if (not is_orthrus_move and target is not None and target.is_pawn
            and target.pawn_name == "Elle McGib" and gs.elle_immunity_available(to_pos)):
        # Pause and let Elle's owner decide whether to spend her once-per-game
        # immunity, instead of it auto-triggering at the first opportunity.
        # Nothing has mutated yet, so no undo snapshot is taken here.
        game_data["pending_elle_decision"] = {"from_pos": list(from_pos), "to_pos": list(to_pos)}
        resp = build_game_state_response()
        resp["pending_elle_decision"] = game_data["pending_elle_decision"]
        return jsonify(resp)

    if is_orthrus_move:
        # Orthrus never captures -- his own moves (forward or rotate) always
        # land on an empty square, and shift/pivot his 2-square body.
        action = resolve_orthrus_action(piece_at_from, to_pos)
        if action is None:
            return jsonify({"error": "Illegal Orthrus move"}), 400
        _snapshot_for_undo()
        new_head, new_butt, new_direction = action
        gs.board.move_orthrus_body(piece_at_from, new_head, new_butt, new_direction)
    elif target is not None:
        _snapshot_for_undo()
        cap_result = gs.attempt_capture(from_pos, to_pos)
        captured = _resolve_capture_result(gs, cap_result, from_pos, to_pos)
    else:
        _snapshot_for_undo()
        captured = gs.board.make_move(from_pos, to_pos)

    _finish_move_and_check_game_over(gs, color, from_pos, to_pos, captured)
    return jsonify(build_game_state_response())


@app.route("/resolve_elle_decision", methods=["POST"])
def resolve_elle_decision():
    """Resolve a paused Elle McGib Frozen Immunity decision.

    Body: {use_immunity: bool}
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    pending = game_data.get("pending_elle_decision")
    if not pending:
        return jsonify({"error": "No pending Elle McGib decision"}), 400

    data = request.get_json(force=True)
    use_immunity = bool(data.get("use_immunity"))

    from_pos = tuple(pending["from_pos"])
    to_pos = tuple(pending["to_pos"])
    _snapshot_for_undo()
    game_data["pending_elle_decision"] = None
    color = gs.current_player

    if use_immunity:
        gs.consume_elle_immunity(to_pos)
        gs.log_event("move_blocked", reason="Elle McGib Frozen Immunity")
        captured = None
    else:
        # Player declined -- let this one capture attempt through without
        # re-triggering the immunity, but leave it available for next time.
        defender = gs.board.get(*to_pos)
        key = f"{defender.color.value}_{to_pos[0]}_{to_pos[1]}"
        gs.elle_immunity_skip_once.add(key)
        cap_result = gs.attempt_capture(from_pos, to_pos)
        captured = _resolve_capture_result(gs, cap_result, from_pos, to_pos)

    _finish_move_and_check_game_over(gs, color, from_pos, to_pos, captured)
    return jsonify(build_game_state_response())


@app.route("/ai_card/custard_choice", methods=["POST"])
def ai_card_custard_choice():
    """Resolve a pending Lottery Ticket (Custard) decision.

    Body: {index}  -- index into pending_ai_card_decision["options"]
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400

    data = request.get_json(force=True)
    index = data.get("index")

    ok, message = resolve_custard_choice(gs, index)
    if not ok:
        return jsonify({"error": message}), 400
    return jsonify(build_game_state_response())


@app.route("/ai_card/too_boring_choice", methods=["POST"])
def ai_card_too_boring_choice():
    """Resolve one step of a pending Too Boring decision.

    Body: {row, col} -- position of the pawn to eliminate
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400

    data = request.get_json(force=True)
    row = data.get("row")
    col = data.get("col")

    ok, message = resolve_too_boring_choice(gs, row, col)
    if not ok:
        return jsonify({"error": message}), 400
    return jsonify(build_game_state_response())


@app.route("/undo_move", methods=["POST"])
def undo_move():
    """Revert to the state just before the last completed move. Dev Game mode only."""
    if game_data.get("mode") != "dev":
        return jsonify({"error": "Undo is only available in Dev Game mode"}), 400
    if not move_history:
        return jsonify({"error": "Nothing to undo"}), 400

    snapshot = move_history.pop()
    game_data.clear()
    game_data.update(snapshot)
    return jsonify(build_game_state_response())


@app.route("/dev/cycle_die", methods=["POST"])
def dev_cycle_die():
    """Cycle one of this turn's rolled dice through 1-6. Dev Game mode only.

    Body: {die_index}
    The new value is a full stand-in for a real roll: it's checked against the
    AI summon trigger exactly like a fresh roll would be, so devs can dial in
    double-1s/double-3s/6+2 to test that path on demand.
    """
    if game_data.get("mode") != "dev":
        return jsonify({"error": "Dev tools are only available in Dev Game mode"}), 400
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    if gs.pending_ai_card_decision:
        return jsonify({"error": "Resolve the pending AI Card decision first"}), 400

    data = request.get_json(force=True)
    die_index = data.get("die_index")

    dice = game_data.get("dice")
    if dice is None or not dice.dice:
        return jsonify({"error": "No dice rolled this turn"}), 400
    if not isinstance(die_index, int) or die_index < 0 or die_index >= len(dice.dice):
        return jsonify({"error": "Invalid die index"}), 400
    if dice.used[die_index]:
        return jsonify({"error": "That die has already been spent"}), 400

    dice.dice[die_index] = dice.dice[die_index] % 6 + 1
    gs.log_event("dev_die_override", die_index=die_index, value=dice.dice[die_index])

    if len(dice.dice) == 2:
        gs.draw_ai_card_if_triggered(dice.dice[0], dice.dice[1], gs.current_player, dice=dice)

    return jsonify(build_game_state_response())


@app.route("/dev/draw_ai_card", methods=["POST"])
def dev_draw_ai_card():
    """Force-draw the top AI Card, bypassing the dice trigger entirely. Dev Game mode only."""
    if game_data.get("mode") != "dev":
        return jsonify({"error": "Dev tools are only available in Dev Game mode"}), 400
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    if gs.pending_ai_card_decision:
        return jsonify({"error": "Resolve the pending AI Card decision first"}), 400

    dice = game_data.get("dice")
    draw_ai_card(gs, gs.current_player, dice=dice)
    return jsonify(build_game_state_response())


@app.route("/ability/get_targets", methods=["POST"])
def get_ability_targets():
    """Get valid targets for an ability before execution.
    
    Body: {piece_row, piece_col, ability_name, die_index}
    Returns: {valid_targets: [[row, col], ...], message: str}
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    if gs.pending_ai_card_decision:
        return jsonify({"error": "Resolve the pending AI Card decision first"}), 400
    if game_data.get("phase") != "ability":
        return jsonify({"error": "Not in ability phase"}), 400

    data = request.get_json(force=True)
    piece_row = data.get("piece_row")
    piece_col = data.get("piece_col")
    ability_name = data.get("ability_name")
    die_index = data.get("die_index")
    use_combined = data.get("use_combined", False)

    if None in (piece_row, piece_col, ability_name, die_index):
        return jsonify({"error": "Missing data"}), 400

    piece = gs.board.get(piece_row, piece_col)
    if piece is None:
        return jsonify({"error": "No piece at that position"}), 400
    if piece.color != gs.controlled_color(gs.current_player):
        return jsonify({"error": "Not your piece to control this turn"}), 400

    dice = game_data["dice"]
    if die_index < 0 or die_index >= 2 or dice.used[die_index]:
        return jsonify({"error": "Invalid or already used die"}), 400

    valid_targets = []
    message = f"Select a target for {ability_name}"
    direction_options = None
    combined_total = None

    # For non-combined abilities paid via combined dice, compute the effective die value
    def effective_die_value(idx):
        if use_combined:
            other = 1 - idx
            if 0 <= other < len(dice.dice) and not dice.used[other]:
                return dice.dice[0] + dice.dice[1]
        return dice.dice[idx] if idx < len(dice.dice) else 0

    # Get valid targets based on ability type
    try:
        # Zone abilities - within 4 squares
        if ability_name == "Air Strike":
            for dr in range(-4, 5):
                for dc in range(-4, 5):
                    nr, nc = piece_row + dr, piece_col + dc
                    if gs.board.in_bounds(nr, nc) and gs.board.in_bounds(nr + 1, nc + 1):
                        valid_targets.append([nr, nc])
            message = "Select top-left corner for 2×2 empty zone"

        elif ability_name == "Lava Spit":
            for dr in range(-4, 5):
                for dc in range(-4, 5):
                    nr, nc = piece_row + dr, piece_col + dc
                    if gs.board.in_bounds(nr, nc):
                        valid_targets.append([nr, nc])
            message = "Click a square — lava strip extends right"

        # Movement abilities — compute destinations WITHOUT spending the die.
        # The die is only spent when the player confirms a target at /ability.
        elif ability_name == "Leader":
            # Banking is tied to whichever seat is taking this turn, not to Carl's color.
            player = gs.current_player.value
            combined_total = gs.leader_available_total(dice, player)
            pulled_piece = data.get("pulled_piece")
            if combined_total <= 0:
                message = "Not enough dice available for Leader"
            elif pulled_piece:
                pr, pc = pulled_piece
                valid_targets = [
                    list(pos) for pos in
                    gs.leader_pull_destinations((pr, pc), (piece_row, piece_col), combined_total)
                ]
                message = f"Select destination (up to {combined_total} squares)"
            else:
                eligible = gs.leader_eligible_pieces(piece.color)
                valid_targets = [
                    [r, c] for (r, c) in eligible
                    if gs.leader_pull_destinations((r, c), (piece_row, piece_col), combined_total)
                ]
                message = f"Combined total: {combined_total}. Select a friendly piece to pull (Donut, Katia, or Samantha)"

        elif ability_name == "Plot Armor" and piece.piece_type == PieceType.CARL:
            if dice.can_combine_for_cost(8):
                valid_targets = [list(pos) for pos in gs.plot_armor_destinations((piece_row, piece_col))]
            message = "Select destination (up to 3 squares, any King direction)"

        elif ability_name == "Puddle Jump":
            if effective_die_value(die_index) >= 5:
                r, c = piece_row, piece_col
                directions = [(-1, 0), (1, 0), (0, -1), (0, 1),
                              (-1, -1), (-1, 1), (1, -1), (1, 1)]
                for dr, dc in directions:
                    for dist in range(1, BOARD_SIZE):
                        nr, nc = r + dr * dist, c + dc * dist
                        if not gs.board.in_bounds(nr, nc):
                            break
                        if gs.is_square_blocked(nr, nc):
                            break
                        t = gs.board.get(nr, nc)
                        if t is None:
                            valid_targets.append([nr, nc])
                        elif t.color != piece.color:
                            valid_targets.append([nr, nc])
                            break
                        # friendly piece — pass through, continue scanning
            message = "Select destination (queen movement, pass through friendlies)"
        
        elif ability_name == "Pet Carrier":
            # Check if Mongo is stored
            key = (piece.color, id(piece))
            if gs.mongo_stored.get(key, False):
                # Find Donut, get squares within 2
                donut_pos = None
                for r in range(11):
                    for c in range(11):
                        p = gs.board.get(r, c)
                        if p and p.piece_type == PieceType.DONUT and p.color == piece.color:
                            donut_pos = (r, c)
                            break
                    if donut_pos:
                        break
                
                if donut_pos:
                    for dr in range(-2, 3):
                        for dc in range(-2, 3):
                            nr, nc = donut_pos[0] + dr, donut_pos[1] + dc
                            if gs.board.in_bounds(nr, nc) and gs.board.get(nr, nc) is None:
                                valid_targets.append([nr, nc])
                    message = "Select where to spawn Mongo (within 2 of Donut)"
            else:
                # Storing Mongo - no target needed, but return empty to trigger normal flow
                return jsonify({"error": "Pet Carrier store doesn't need targeting"}), 400
        
        elif ability_name == "Rampage":
            # Combined dice check only — do NOT call try_rampage (would spend dice)
            if dice.can_combine_for_cost(8):
                r, c = piece_row, piece_col
                for dr, dc in [(2,1),(2,-1),(-2,1),(-2,-1),(1,2),(1,-2),(-1,2),(-1,-2)]:
                    nr, nc = r + dr, c + dc
                    if gs.board.in_bounds(nr, nc) and not gs.is_square_blocked(nr, nc):
                        t = gs.board.get(nr, nc)
                        if t is None or t.color != piece.color:
                            valid_targets.append([nr, nc])
            message = "Select destination after capturing all in path"
        
        # Target piece abilities
        elif ability_name == "Blitzed":
            # All friendly pieces
            for r in range(11):
                for c in range(11):
                    p = gs.board.get(r, c)
                    if p and p.color == piece.color:
                        valid_targets.append([r, c])
            message = "Select friendly piece to skip movement requirement"
        
        elif ability_name == "She Tank":
            # All enemy pieces
            for r in range(11):
                for c in range(11):
                    p = gs.board.get(r, c)
                    if p and p.color != piece.color:
                        valid_targets.append([r, c])
            message = "Select enemy piece to prevent from moving"
        
        elif ability_name == "Slut Shame":
            # Enemy pawns within 3 squares (Orthrus is a 2-square body and can't be swallowed)
            for dr in range(-3, 4):
                for dc in range(-3, 4):
                    nr, nc = piece_row + dr, piece_col + dc
                    if gs.board.in_bounds(nr, nc):
                        p = gs.board.get(nr, nc)
                        if p and p.is_pawn and p.color != piece.color and p.pawn_name != "Orthrus":
                            valid_targets.append([nr, nc])
            message = "Select enemy pawn to swallow (within 3 squares)"
        
        elif ability_name == "One Of Us":
            # Enemy pawns within 2 squares
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    nr, nc = piece_row + dr, piece_col + dc
                    if gs.board.in_bounds(nr, nc):
                        p = gs.board.get(nr, nc)
                        if p and p.is_pawn and p.color != piece.color:
                            valid_targets.append([nr, nc])
            message = "Select enemy pawn to convert (within 2 squares)"
        
        # Resurrection/sacrifice abilities
        elif ability_name == "Cockroach":
            # Show captured pieces as targets (we'll handle selection differently)
            # For now, show adjacent squares where piece can spawn
            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = piece_row + dr, piece_col + dc
                    if gs.board.in_bounds(nr, nc) and gs.board.get(nr, nc) is None:
                        valid_targets.append([nr, nc])
            message = "Select adjacent square to resurrect piece"
        
        elif ability_name == "Blood Magic":
            # Adjacent friendly pawns to sacrifice
            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = piece_row + dr, piece_col + dc
                    if gs.board.in_bounds(nr, nc):
                        p = gs.board.get(nr, nc)
                        if p and p.is_pawn and p.color == piece.color:
                            valid_targets.append([nr, nc])
            message = "Select adjacent friendly pawn to sacrifice"

        elif ability_name == "Frozen":
            # Enemy pieces within 5 squares
            for dr in range(-5, 6):
                for dc in range(-5, 6):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = piece_row + dr, piece_col + dc
                    if gs.board.in_bounds(nr, nc):
                        p = gs.board.get(nr, nc)
                        if p and p.color != piece.color:
                            valid_targets.append([nr, nc])
            message = "Select enemy piece to freeze (within 5 squares)"

        elif ability_name == "Lava Surge":
            if gs.chris_lava_surge_adjacent_enemy((piece_row, piece_col)):
                return jsonify({"error": "Chris cannot cast while enemies are adjacent"}), 400
            direction_options = {}
            for d in ("horizontal", "vertical"):
                squares = gs.chris_lava_surge_direction_squares((piece_row, piece_col), d)
                direction_options[d] = {
                    "valid": gs.chris_lava_surge_direction_valid((piece_row, piece_col), d),
                    "squares": [[sr, sc] for sr, sc in squares],
                }
            message = "Choose a direction for Lava Surge"

        # Special Event Attacks (boss battles only)
        elif ability_name == "Jug-o-Boom" and piece.piece_type == PieceType.CARL:
            for dr in range(-3, 4):
                for dc in range(-3, 4):
                    nr, nc = piece_row + dr, piece_col + dc
                    if gs.board.in_bounds(nr, nc):
                        valid_targets.append([nr, nc])
            message = "Select a square within 3 to bomb (hits the boss if it's there or adjacent)"

        elif ability_name == "Magic Missile" and piece.piece_type == PieceType.DONUT:
            r, c = piece_row, piece_col
            directions = [(-1, 0), (1, 0), (0, -1), (0, 1),
                          (-1, -1), (-1, 1), (1, -1), (1, 1)]
            for dr, dc in directions:
                for dist in range(1, 6):
                    nr, nc = r + dr * dist, c + dc * dist
                    if not gs.board.in_bounds(nr, nc):
                        break
                    valid_targets.append([nr, nc])
            message = "Select a target up to 5 squares away (hits the boss if it's on the path)"

        elif ability_name == "Gorefest" and piece.piece_type == PieceType.MONGO:
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    nr, nc = piece_row + dr, piece_col + dc
                    if gs.board.in_bounds(nr, nc):
                        valid_targets.append([nr, nc])
            message = "Select a square within 2 to attack (hits the boss if it's there)"

        resp_data = {
            "valid_targets": valid_targets,
            "message": message
        }
        if direction_options is not None:
            resp_data["direction_options"] = direction_options
        if combined_total is not None:
            resp_data["combined_total"] = combined_total
        return jsonify(resp_data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


BOSS_ONLY_ABILITIES = {"Jug-o-Boom", "Magic Missile", "Gorefest", "I Need My Space", "IWKYM"}


@app.route("/ability", methods=["POST"])
def use_ability():
    """Use an ability with a die.

    Body: {piece_row, piece_col, ability_name, die_index, target_row?, target_col?}
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    if gs.pending_ai_card_decision:
        return jsonify({"error": "Resolve the pending AI Card decision first"}), 400
    if game_data.get("phase") != "ability":
        return jsonify({"error": "Not in ability phase"}), 400
    if gs.system_reset_active:
        return jsonify({"error": "System Reset is active -- no abilities can be used this turn"}), 400

    data = request.get_json(force=True)
    piece_row = data.get("piece_row")
    piece_col = data.get("piece_col")
    ability_name = data.get("ability_name")
    die_index = data.get("die_index")
    target_row = data.get("target_row")
    target_col = data.get("target_col")
    use_combined = data.get("use_combined", False)
    direction = data.get("direction")

    if None in (piece_row, piece_col, ability_name, die_index):
        return jsonify({"error": "Missing data"}), 400

    # Block boss-only abilities when no boss is active
    if ability_name in BOSS_ONLY_ABILITIES and not gs.boss_active:
        return jsonify({"error": "This ability can only be used during a Boss Event"}), 400

    piece = gs.board.get(piece_row, piece_col)
    if piece is None:
        return jsonify({"error": "No piece at that position"}), 400
    if piece.color != gs.controlled_color(gs.current_player):
        return jsonify({"error": "Not your piece to control this turn"}), 400

    dice = game_data["dice"]
    if die_index < 0 or die_index >= 2 or dice.used[die_index]:
        return jsonify({"error": "Invalid or already used die"}), 400

    # Determine whether this ability is designed as requires_combined
    # (those abilities handle their own combined dice internally)
    _requires_combined_by_design = False
    if piece.is_pawn and piece.pawn_name == "Juice Box" and ability_name != "Shapeshift":
        _copied_char = gs.find_captured_ability((piece_row, piece_col), ability_name)
        if _copied_char:
            _requires_combined_by_design = getattr(_copied_char.ability, 'requires_combined', False)
    elif piece.is_pawn and piece.pawn_name:
        _char = PAWN_CHARACTERS.get(piece.pawn_name)
        if _char:
            _requires_combined_by_design = getattr(_char.ability, 'requires_combined', False)
    else:
        for _mab in MAJOR_ABILITIES.get(piece.piece_type.value, []):
            if _mab["name"] == ability_name:
                _requires_combined_by_design = _mab.get("requires_combined", False)
                break

    # For non-requires_combined abilities paid via combined dice:
    # merge both dice values into die_index so try_* methods work without modification.
    # The other die is pre-marked used; die_index gets the combined sum as its value.
    if use_combined and not _requires_combined_by_design:
        _other = 1 - die_index
        if (0 <= _other < len(dice.dice) and not dice.used[_other]):
            dice.dice[die_index] = dice.dice[0] + dice.dice[1]
            dice.used[_other] = True

    # The piece's own true color, not gs.current_player -- during a Matt's Drunk
    # Again swap the acting player may be using a piece of the opposite color, and
    # per-side tracking (uses-per-game, captured lists, etc.) belongs to the piece.
    color = piece.color
    success = False
    result_msg = ""

    # Target position if provided
    target_pos = (target_row, target_col) if target_row is not None and target_col is not None else None

    # Route to correct ability
    try:
        # Carl abilities
        if ability_name == "Plot Armor" and piece.piece_type == PieceType.CARL:
            result = gs.try_plot_armor((piece_row, piece_col), dice)
            success = result is not None
            if success and result:
                if target_pos and target_pos in result:
                    dest = target_pos
                else:
                    dest = random.choice(result) if result else None
                if dest:
                    captured = gs.board.make_move((piece_row, piece_col), dest)
                    if captured:
                        gs.process_post_capture(captured, dest, piece, (piece_row, piece_col))
                else:
                    success = False
            result_msg = "Plot Armor activated!" if success else "Failed"

        elif ability_name == "Leader" and piece.piece_type == PieceType.CARL:
            pulled_piece = data.get("pulled_piece")
            if not pulled_piece:
                return jsonify({"error": "Missing pulled_piece for Leader"}), 400
            pr, pc = pulled_piece
            pulled = gs.board.get(pr, pc)
            if (pulled is None or pulled.color != color
                    or pulled.piece_type not in (PieceType.DONUT, PieceType.KATIA, PieceType.SAMANTHA)):
                return jsonify({"error": "Invalid Leader target piece"}), 400

            # Leader's combined total can include a banked die -- banking is tied to
            # whichever seat is actually taking this turn, not to Carl's own color.
            total = gs.try_leader((piece_row, piece_col), dice, gs.current_player.value)
            success = total is not None
            if success:
                destinations = gs.leader_pull_destinations((pr, pc), (piece_row, piece_col), total)
                if target_pos and target_pos in destinations:
                    dest = target_pos
                else:
                    dest = random.choice(destinations) if destinations else None
                if dest:
                    gs.board.set(pr, pc, None)
                    gs.board.set(dest[0], dest[1], pulled)
                else:
                    success = False
            result_msg = "Leader activated!" if success else "Failed"

        elif ability_name == "Bulldozer" and piece.piece_type == PieceType.CARL:
            result = gs.try_bulldozer((piece_row, piece_col), dice, die_index)
            success = result is not None
            result_msg = "Extra moves available!" if success else "Failed"

        elif ability_name == "Jug-o-Boom" and piece.piece_type == PieceType.CARL:
            if target_pos is None:
                return jsonify({"error": "Jug-o-Boom needs a target square"}), 400
            hit = gs.try_jug_o_boom((piece_row, piece_col), dice, die_index, target_pos)
            success = hit is not None
            if success and hit and gs.active_boss == "Feral Goose":
                result_msg = "The Feral Goose is immune to all attacks — solve the puzzle to defeat it."
            else:
                result_msg = ("Direct hit on the boss!" if hit else "Miss -- no boss square in range.") if success else "Failed"

        # Donut abilities
        elif ability_name == "Puddle Jump" and piece.piece_type == PieceType.DONUT:
            result = gs.try_puddle_jump((piece_row, piece_col), dice, die_index)
            success = result is not None
            if success and result:
                if target_pos and target_pos in result:
                    dest = target_pos
                else:
                    dest = random.choice(result) if result else None
                if dest:
                    gs.board.set(piece_row, piece_col, None)
                    gs.board.set(dest[0], dest[1], piece)
            result_msg = "Puddle jump!" if success else "Failed"

        elif ability_name == "Diva's Entrance" and piece.piece_type == PieceType.DONUT:
            # Pick a random adjacent target square for simplicity
            r, c = piece_row, piece_col
            adj = [(r+dr, c+dc) for dr in [-1,0,1] for dc in [-1,0,1]
                   if (dr != 0 or dc != 0) and gs.board.in_bounds(r+dr, c+dc)]
            target = random.choice(adj) if adj else None
            if target:
                success = gs.try_divas_entrance((piece_row, piece_col), dice, die_index, target)
            result_msg = "Phantom threat placed!" if success else "Failed"

        elif ability_name == "Cockroach" and piece.piece_type == PieceType.DONUT:
            # Cockroach uses target_pos as spawn location
            result = gs.try_cockroach((piece_row, piece_col), dice)
            success = result is not None
            # If target provided, move resurrected piece there
            if success and result and target_pos:
                gs.board.set(target_pos[0], target_pos[1], result)
            result_msg = f"Resurrected {repr(result)}!" if success else "Failed"

        elif ability_name == "Resurrection" and piece.piece_type == PieceType.DONUT:
            result = gs.try_resurrection((piece_row, piece_col), dice, die_index, color)
            success = result is not None
            result_msg = f"Resurrected {repr(result)}!" if success else "Failed"

        elif ability_name == "Magic Missile" and piece.piece_type == PieceType.DONUT:
            if target_pos is None:
                return jsonify({"error": "Magic Missile needs a target square"}), 400
            hit = gs.try_magic_missile((piece_row, piece_col), dice, die_index, target_pos)
            success = hit is not None
            if success and hit and gs.active_boss == "Feral Goose":
                result_msg = "The Feral Goose is immune to all attacks — solve the puzzle to defeat it."
            else:
                result_msg = ("Direct hit on the boss!" if hit else "The missile flew past -- no boss square on its path.") if success else "Failed"

        # Mongo abilities
        elif ability_name == "Pet Carrier" and piece.piece_type == PieceType.MONGO:
            success = gs.try_pet_carrier((piece_row, piece_col), dice, die_index)
            result_msg = "Pet carrier activated!" if success else "Failed"

        elif ability_name == "Mongo Smash" and piece.piece_type == PieceType.MONGO:
            success = gs.try_mongo_smash((piece_row, piece_col), dice, die_index)
            result_msg = "Smash hit!" if success else "Failed"

        elif ability_name == "Rampage" and piece.piece_type == PieceType.MONGO:
            result = gs.try_rampage((piece_row, piece_col), dice)
            success = result is not None
            if success and result:
                if target_pos and target_pos in result:
                    dest = target_pos
                else:
                    dest = random.choice(result) if result else None
                if dest:
                    gs.board.set(piece_row, piece_col, None)
                    gs.board.set(dest[0], dest[1], piece)
            result_msg = "Rampage!" if success else "Failed"

        elif ability_name == "Rampaging Charge" and piece.piece_type == PieceType.MONGO:
            result = gs.try_rampaging_charge((piece_row, piece_col), dice, die_index)
            success = result is not None
            if success and result:
                dest = random.choice(result)
                gs.board.set(piece_row, piece_col, None)
                gs.board.set(dest[0], dest[1], piece)
            result_msg = "Charge!" if success else "Failed"

        elif ability_name == "Gorefest" and piece.piece_type == PieceType.MONGO:
            if target_pos is None:
                return jsonify({"error": "Gorefest needs a target square"}), 400
            hit = gs.try_gorefest((piece_row, piece_col), dice, die_index, target_pos)
            success = hit is not None
            if success and hit and gs.active_boss == "Feral Goose":
                result_msg = "The Feral Goose is immune to all attacks — solve the puzzle to defeat it."
            else:
                result_msg = ("Direct hit on the boss!" if hit else "Miss -- no boss square there.") if success else "Failed"

        # Katia abilities
        elif ability_name == "She Tank" and piece.piece_type == PieceType.KATIA:
            if target_pos:
                success = gs.try_she_tank((piece_row, piece_col), dice, target_pos, is_reaction=False)
            else:
                # Pick random enemy piece as fallback
                enemy_pieces = []
                for row in range(11):
                    for col in range(11):
                        p = gs.board.get(row, col)
                        if p and p.color != piece.color:
                            enemy_pieces.append((row, col))
                if enemy_pieces:
                    target_pos = random.choice(enemy_pieces)
                    success = gs.try_she_tank((piece_row, piece_col), dice, target_pos, is_reaction=False)
            result_msg = "She Tank activated!" if success else "Failed"

        elif ability_name == "Blitzed" and piece.piece_type == PieceType.KATIA:
            # Blitzed uses target_pos to select which piece to blitz
            if target_pos:
                target_piece = gs.board.get(target_pos[0], target_pos[1])
                if target_piece and target_piece.color == piece.color:
                    success = dice.spend_die(die_index, 5)
                    if success:
                        gs.blitzed_pieces.add(target_pos)
                        result_msg = "Blitzed activated!"
                    else:
                        result_msg = "Failed"
                else:
                    result_msg = "Invalid target"
                    success = False
            else:
                success = gs.try_blitzed((piece_row, piece_col), dice, die_index)
                result_msg = "Blitzed activated!" if success else "Failed"

        elif ability_name == "Combat Roll" and piece.piece_type == PieceType.KATIA:
            result = gs.try_combat_roll((piece_row, piece_col), dice, die_index)
            success = result is not None and len(result) > 0
            if success:
                dest = random.choice(result)
                gs.board.set(piece_row, piece_col, None)
                gs.board.set(dest[0], dest[1], piece)
            result_msg = "Rolled to safety!" if success else "Failed"

        elif ability_name == "Dual Threat" and piece.piece_type == PieceType.KATIA:
            r, c = piece_row, piece_col
            adj = [(r+dr, c+dc) for dr in [-2,-1,0,1,2] for dc in [-2,-1,0,1,2]
                   if (dr != 0 or dc != 0) and gs.board.in_bounds(r+dr, c+dc)]
            target = random.choice(adj) if adj else None
            if target:
                success = gs.try_dual_threat((piece_row, piece_col), dice, die_index, target)
            result_msg = "Dual threat!" if success else "Failed"

        elif ability_name == "I Need My Space" and piece.piece_type == PieceType.KATIA:
            result = gs.try_i_need_my_space((piece_row, piece_col), dice, die_index)
            success = result is not None
            result_msg = "The boss is shoved back!" if success else "Failed"

        # Samantha abilities
        elif ability_name == "Slut Shame" and piece.piece_type == PieceType.SAMANTHA:
            # Slut Shame uses target_pos to select which pawn to swallow
            if target_pos:
                target_piece = gs.board.get(target_pos[0], target_pos[1])
                if target_piece and target_piece.is_pawn and target_piece.color != piece.color and target_piece.pawn_name != "Orthrus":
                    # Manually execute slut shame with specific target
                    key = (piece.color, id(piece))
                    if not gs.slut_shame_used.get(key, False) and dice.can_combine_for_cost(8):
                        dice.spend_combined(8)
                        gs.slut_shame_used[key] = True
                        gs.board.set(target_pos[0], target_pos[1], None)
                        gs.swallowed_pawns.append({
                            "piece": target_piece,
                            "turns_left": 5,
                            "samantha_pos": (piece_row, piece_col)
                        })
                        success = True
                        result_msg = "Pawn swallowed!"
                    else:
                        success = False
                        result_msg = "Failed"
                else:
                    success = False
                    result_msg = "Invalid target"
            else:
                success = gs.try_slut_shame((piece_row, piece_col), dice)
                result_msg = "Pawn swallowed!" if success else "Failed"

        elif ability_name == "Miss Me?" and piece.piece_type == PieceType.SAMANTHA:
            result = gs.try_miss_me((piece_row, piece_col), dice, die_index, is_reaction=False)
            success = result is not None
            result_msg = f"Dice rerolled: {result}!" if success else "Failed"

        elif ability_name == "The Mouth" and piece.piece_type == PieceType.SAMANTHA:
            result = gs.try_the_mouth((piece_row, piece_col), dice, die_index)
            success = result is not None
            result_msg = f"Rerolled to {result}!" if success else "Failed"

        elif ability_name == "Portal Spike" and piece.piece_type == PieceType.SAMANTHA:
            result = gs.try_portal_spike((piece_row, piece_col), dice, die_index)
            success = result is not None
            result_msg = "Teleported!" if success else "Failed"

        elif ability_name == "IWKYM" and piece.piece_type == PieceType.SAMANTHA:
            success = gs.try_iwkym((piece_row, piece_col), dice, die_index)
            result_msg = "Samantha clamps down on the boss!" if success else "Failed"

        # Pawn abilities
        elif piece.is_pawn and piece.pawn_name:
            success, result_msg = _handle_pawn_ability(gs, dice, piece, piece_row, piece_col, ability_name, die_index, target_pos, direction=direction, use_combined=use_combined)

        else:
            return jsonify({"error": f"Unknown ability: {ability_name}"}), 400

    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # One ability per turn: lock all remaining dice regardless of which was spent
    for i in range(len(dice.used)):
        dice.used[i] = True

    resp = build_game_state_response()
    resp["ability_result"] = {"success": success, "message": result_msg}
    return jsonify(resp)


def _handle_pawn_ability(gs, dice, piece, row, col, ability_name, die_index, target_pos=None, direction=None, use_combined=False):
    """Handle pawn ability usage. Returns (success, message)."""
    name = piece.pawn_name
    pos = (row, col)
    success = False
    msg = "Failed"

    if name == "Zev" and ability_name == "Biggest Fan":
        success = gs.try_biggest_fan(pos, dice, die_index)
        msg = "Biggest fan activated!" if success else "Failed"
    elif name == "The AI" and ability_name == "Glitch":
        success = gs.try_glitch(pos, dice, die_index)
        msg = "Glitched!" if success else "Failed"
    elif name == "Prepotente" and ability_name == "Special Boy":
        result = gs.try_special_boy(pos, dice, die_index)
        success = result is not None
        if success and result:
            # Let player pick destination from result list
            dest = random.choice(result)
            gs.board.set(row, col, None)
            gs.board.set(dest[0], dest[1], piece)
            piece.has_moved = True
        msg = "Special boy!" if success else "Failed"
    elif name == "Slugalo" and ability_name == "One Of Us":
        # One Of Us uses target_pos from request data if available
        # target_pos is passed in as parameter
        if target_pos:
            target_piece = gs.board.get(target_pos[0], target_pos[1])
            if target_piece and target_piece.is_pawn and target_piece.color != piece.color:
                if dice.can_combine_for_cost(10):
                    dice.spend_combined(10)
                    from dcc_chess.pieces import Color
                    target_piece.color = piece.color
                    success = True
                    msg = "Converted!"
                else:
                    success = False
                    msg = "Failed"
            else:
                success = False
                msg = "Invalid target"
        else:
            success = gs.try_one_of_us(pos, dice)
            msg = "Converted!" if success else "Failed"
    elif name == "Louie" and ability_name == "Air Strike":
        # Air Strike uses target_pos for zone placement
        # target_pos is passed in as parameter
        if target_pos:
            # Validate: zone must be completely empty
            for dr in range(2):
                for dc in range(2):
                    nr, nc = target_pos[0] + dr, target_pos[1] + dc
                    if gs.board.in_bounds(nr, nc) and gs.board.get(nr, nc) is not None:
                        return False, "Air Strike requires an empty 2×2 zone"
            # Place 2x2 zone at target_pos (top-left corner) — combined dice floor 6
            if dice.can_combine_for_cost(6):
                dice.spend_combined(6)
                gs.air_strike_zones.clear()  # Replace any existing zone
                for dr in range(2):
                    for dc in range(2):
                        nr, nc = target_pos[0] + dr, target_pos[1] + dc
                        if gs.board.in_bounds(nr, nc):
                            gs.air_strike_zones[(nr, nc)] = 2  # 2 turns duration
                gs.louie_cant_move = set(gs.air_strike_zones.keys())
                success = True
                msg = "Air strike!"
            else:
                success = False
                msg = "Failed"
        else:
            success = gs.try_air_strike(pos, dice, die_index)
            msg = "Air strike!" if success else "Failed"
    elif name == "Stripper Anaconda" and ability_name == "Gun Show":
        success = gs.try_gun_show(pos, dice, die_index)
        msg = "Gun show!" if success else "Failed"
    elif name == "Lucia Mar" and ability_name == "Sic Em":
        success = gs.try_sic_em(pos, dice, die_index)
        msg = "Restrained!" if success else "Failed"
    elif name == "Elle McGib" and ability_name == "Frozen":
        success = gs.try_frozen(pos, dice, die_index, target_pos=target_pos)
        msg = "Frozen!" if success else "Failed"
    elif name == "Imani" and ability_name == "Suppress":
        success = gs.try_suppress(pos, dice, die_index)
        msg = "Suppressed!" if success else "Failed"
    elif name == "Sledge" and ability_name == "Body Guard":
        success = gs.try_body_guard(pos, dice, die_index)
        msg = "Body guard activated!" if success else "Failed"
    elif name == "Chris" and ability_name == "Lava Surge":
        if gs.chris_lava_surge_adjacent_enemy(pos):
            return False, "Chris cannot cast while enemies are adjacent"
        if direction not in ("horizontal", "vertical"):
            return False, "Select a direction for Lava Surge"
        if not gs.chris_lava_surge_direction_valid(pos, direction):
            return False, "Lava Surge zone must be completely empty"
        success = gs.try_lava_surge_chunk2(pos, dice, die_index, direction=direction)
        msg = "Lava surge!" if success else "Failed"
    elif name == "Juice Box" and ability_name == "Shapeshift":
        success = False
        msg = "Select a captured ability to use instead of Shapeshift"
    elif name == "Juice Box":
        success = gs.try_juice_box_use_captured_ability(
            pos, ability_name, dice, die_index, use_combined=use_combined,
            target_pos=target_pos, direction=direction)
        msg = f"Used {ability_name}!" if success else "Failed"
    elif name == "Florin" and ability_name == "Suppressing Fire":
        success = gs.try_suppressing_fire(pos, dice, die_index)
        msg = "Suppressing fire!" if success else "Failed"
    elif name == "Signet" and ability_name == "Succubus":
        success = gs.try_succubus(pos, dice, die_index)
        msg = "Succubus!" if success else "Failed"
    elif name == "Miriam Dom" and ability_name == "Blood Magic":
        # Blood Magic uses target_pos to select sacrifice pawn
        # target_pos is passed in as parameter
        if target_pos:
            sacrifice_piece = gs.board.get(target_pos[0], target_pos[1])
            if sacrifice_piece and sacrifice_piece.is_pawn and sacrifice_piece.color == piece.color:
                # Execute blood magic with specific sacrifice
                if dice.can_combine_for_cost(8):
                    dice.spend_combined(8)
                    gs.board.set(target_pos[0], target_pos[1], None)
                    # Resurrect captured pawn on back rank (Orthrus can never be resurrected)
                    source = gs.captured_pieces.get(piece.color, [])
                    captured = [p for p in source if not p.permanently_dead and not (p.is_pawn and p.pawn_name == "Orthrus")]
                    if captured:
                        resurrected = random.choice(captured)
                        source.remove(resurrected)
                        from dcc_chess.pieces import Color, BOARD_SIZE
                        back_rank = 0 if piece.color == Color.WHITE else (BOARD_SIZE - 1)
                        spawn_squares = [(back_rank, c) for c in range(BOARD_SIZE) if gs.board.get(back_rank, c) is None]
                        if spawn_squares:
                            spawn_pos = random.choice(spawn_squares)
                            gs.board.set(spawn_pos[0], spawn_pos[1], resurrected)
                            if resurrected.is_pawn and resurrected.pawn_name:
                                gs._juice_box_lose_ability(resurrected.pawn_name)
                            success = True
                            msg = "Blood magic!"
                        else:
                            captured.append(resurrected)
                            gs.board.set(target_pos[0], target_pos[1], sacrifice_piece)
                            success = False
                            msg = "No space on back rank"
                    else:
                        gs.board.set(target_pos[0], target_pos[1], sacrifice_piece)
                        success = False
                        msg = "No captured pieces"
                else:
                    success = False
                    msg = "Failed"
            else:
                success = False
                msg = "Invalid target"
        else:
            success = gs.try_blood_magic(pos, dice)
            msg = "Blood magic!" if success else "Failed"
    elif name == "Raul the Crab" and ability_name == "Group Climax":
        success = gs.try_group_climax(pos, dice)
        msg = "Group climax activated!" if success else "Failed"
    elif name == "Bad Llama" and ability_name == "Lava Spit":
        if target_pos:
            r, c = target_pos[0], target_pos[1]
            # 1×2 horizontal: extend right, or left if at board edge
            c2 = c + 1 if c < 10 else c - 1
            if dice.spend_die(die_index, 5):
                for nc in (c, c2):
                    if gs.board.in_bounds(r, nc):
                        gs.lava_zones[(r, nc)] = 3  # 3 turns duration
                success = True
                msg = "Lava spit!"
            else:
                success = False
                msg = "Failed"
        else:
            success = gs.try_lava_spit_chunk2(pos, dice, die_index)
            msg = "Lava spit!" if success else "Failed"
    else:
        msg = f"Unknown pawn ability: {ability_name}"

    return success, msg


@app.route("/bank_die", methods=["POST"])
def bank_die():
    """Bank a die to save it for later turns.
    
    Body: {die_index}
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    if gs.pending_ai_card_decision:
        return jsonify({"error": "Resolve the pending AI Card decision first"}), 400
    if game_data.get("phase") != "ability":
        return jsonify({"error": "Can only bank during ability phase"}), 400
    
    data = request.get_json(force=True)
    die_index = data.get("die_index")
    
    if die_index is None:
        return jsonify({"error": "Missing die_index"}), 400
    
    dice = game_data["dice"]
    player = gs.current_player.value
    if not dice.bank_die(die_index, player):
        return jsonify({"error": "Cannot bank die"}), 400
    
    gs.log_event("bank_die", value=dice.banked_die[player])
    return jsonify(build_game_state_response())


@app.route("/pull_from_bank", methods=["POST"])
def pull_from_bank():
    """Pull the banked die before rolling (discards it and rolls fresh).
    
    Must be called at start of turn before rolling.
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    
    dice = game_data["dice"]
    player = gs.current_player.value
    if not dice.pull_from_bank(player):
        return jsonify({"error": "No banked die to pull"}), 400
    
    gs.log_event("pull_from_bank")
    return jsonify(build_game_state_response())


@app.route("/ai_turn", methods=["POST"])
def ai_turn():
    """Play the AI's (Black's) full turn.

    Called automatically by the frontend once a human move in PvAI mode has
    ended the turn and it is now Black's move phase. Delegates to
    _play_ai_turn -- the maintained AI turn implementation also used by
    /end_turn's PvAI chain (this route previously carried its own stale copy
    that used an out-of-date smart_move signature).
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    if game_data.get("game_over"):
        return jsonify({"error": "Game is over"}), 400
    if gs.pending_ai_card_decision:
        return jsonify({"error": "Resolve the pending AI Card decision first"}), 400
    if gs.current_player != Color.BLACK:
        return jsonify({"error": "Not AI's turn"}), 400
    if game_data.get("phase") != "move":
        return jsonify({"error": "Not in move phase"}), 400

    return jsonify(_play_ai_turn())


@app.route("/boss_roll", methods=["POST"])
def boss_roll():
    """Submit one player's die roll for the Boss Turn compass movement.

    Body: {color: "white"|"black"}
    Once both sides have rolled, the boss moves immediately and the phase
    returns to "move" for White's next turn.
    """
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    if game_data.get("phase") != "boss_turn":
        return jsonify({"error": "Not in the Boss Turn phase"}), 400

    data = request.get_json(force=True)
    color = data.get("color")
    if color not in ("white", "black"):
        return jsonify({"error": "color must be 'white' or 'black'"}), 400
    if gs.boss_turn_rolls.get(color) is not None:
        return jsonify({"error": f"{color} has already rolled this Boss Turn"}), 400

    _submit_boss_roll(gs, color)
    return jsonify(build_game_state_response())


@app.route("/end_turn", methods=["POST"])
def end_turn():
    """End the current turn. If vs AI and it's now AI's turn, play AI turn too."""
    gs = game_data.get("game_state")
    if gs is None:
        return jsonify({"error": "No game in progress"}), 400
    if gs.pending_ai_card_decision:
        return jsonify({"error": "Resolve the pending AI Card decision first"}), 400

    # End turn (ticks durations, swaps player)
    ended_color = gs.current_player
    gs.end_turn()
    _begin_next_phase_after_turn(gs, ended_color)

    # Safety max turns
    if gs.turn_number >= 300:
        game_data["game_over"] = True
        game_data["winner"] = None
        game_data["result_reason"] = "max_turns"
        game_data["phase"] = "game_over"
        return jsonify(build_game_state_response())

    # If vs AI and it's now black's turn, play AI turn
    mode = game_data.get("mode", "pvp")
    if mode == "pvai" and gs.current_player == Color.BLACK:
        ai_result = _play_ai_turn()
        if ai_result:
            return jsonify(ai_result)

    return jsonify(build_game_state_response())


def _play_ai_turn():
    """Play the AI's turn (black). Returns response dict or None."""
    gs = game_data["game_state"]
    dice = game_data["dice"]
    color = Color.BLACK

    gs.start_turn()
    gs.update_katia_threats()

    # Get legal moves
    legal = gs.get_legal_moves_with_status(color)
    if not legal:
        # During a Boss Event the fight takes priority -- an AI with no legal
        # (non-capture) move doesn't end the game by checkmate/stalemate; it just
        # rolls into the next phase with no move (Bug 3; also the boss co-op
        # fallen-AI case).
        if gs.boss_active:
            gs.end_turn()
            _begin_next_phase_after_turn(gs, color)
            return build_game_state_response()
        if is_in_check(gs.board, color):
            game_data["game_over"] = True
            game_data["winner"] = "white"
            game_data["result_reason"] = "checkmate"
            game_data["phase"] = "game_over"
        else:
            game_data["game_over"] = True
            game_data["winner"] = None
            game_data["result_reason"] = "stalemate"
            game_data["phase"] = "game_over"
        return build_game_state_response()

    # AI picks a move
    from_pos, to_pos = smart_move(gs, legal)

    # Execute move
    target = gs.board.get(*to_pos)
    captured = None

    piece_at_from = gs.board.get(*from_pos)
    is_orthrus_move = (
        piece_at_from is not None and piece_at_from.is_pawn
        and piece_at_from.pawn_name == "Orthrus"
        and from_pos == piece_at_from.orthrus_head_pos
    )

    if is_orthrus_move:
        action = resolve_orthrus_action(piece_at_from, to_pos)
        if action is not None:
            new_head, new_butt, new_direction = action
            gs.board.move_orthrus_body(piece_at_from, new_head, new_butt, new_direction)
    elif target is not None:
        cap_result = gs.attempt_capture(from_pos, to_pos)
        if cap_result == "captured":
            captured = gs.board.make_move(from_pos, to_pos)
            if captured:
                attacker = gs.board.get(*to_pos)
                gs.process_post_capture(captured, to_pos, attacker, from_pos)
        elif cap_result == "defended_elle":
            pass
        elif cap_result == "defended_orthrus":
            pass
        elif cap_result == "defended_quasar":
            attacker = gs.board.get(*from_pos)
            gs.board.set(from_pos[0], from_pos[1], None)
            if attacker:
                gs.board.captured[attacker.color].append(attacker)
        else:
            captured = gs.board.make_move(from_pos, to_pos)
    else:
        captured = gs.board.make_move(from_pos, to_pos)

    gs.log_event("ai_move", from_pos=from_pos, to_pos=to_pos,
                 captured=repr(captured) if captured else None)

    game_data["moved_from"] = from_pos
    game_data["moved_to"] = to_pos

    if captured is not None and captured.is_king:
        captured.permanently_dead = True

    # Check game end. A missing king takes priority over checkmate/stalemate --
    # see _finish_move_and_check_game_over for why.
    opponent = Color.WHITE
    if gs.board.find_king(opponent) is None:
        if _handle_carl_fallen(gs, color, opponent):
            return build_game_state_response()
    elif not gs.boss_active:
        # During a Boss Event the fight takes priority -- no checkmate/stalemate
        # game-end until the boss is defeated (Bug 3).
        if is_checkmate(gs.board, opponent):
            game_data["game_over"] = True
            game_data["winner"] = "black"
            game_data["result_reason"] = "checkmate"
            game_data["phase"] = "game_over"
            gs.end_turn()
            return build_game_state_response()

        if is_stalemate(gs.board, opponent):
            game_data["game_over"] = True
            game_data["winner"] = None
            game_data["result_reason"] = "stalemate"
            game_data["phase"] = "game_over"
            gs.end_turn()
            return build_game_state_response()

    # Roll dice and use abilities
    dice.roll()
    gs.log_event("dice_roll", values=dice.dice[:])
    gs.promote_group_climax(dice)
    gs.draw_ai_card_if_triggered(dice.dice[0], dice.dice[1], color, dice=dice)
    smart_abilities(gs, dice, color)

    # End AI turn
    gs.end_turn()
    _begin_next_phase_after_turn(gs, color)

    # Safety
    if gs.turn_number >= 300:
        game_data["game_over"] = True
        game_data["winner"] = None
        game_data["result_reason"] = "max_turns"
        game_data["phase"] = "game_over"

    return build_game_state_response()


if __name__ == "__main__":
    app.run(debug=True, port=5050)
