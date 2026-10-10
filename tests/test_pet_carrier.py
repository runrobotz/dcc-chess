"""v0.81: Mongo's Pet Carrier -- store (cost 4) and a free release on a later
turn within 2 of Donut; Mongo can't move or capture the turn he comes out; a
stored Mongo is lost with Donut; the AI stores and releases him."""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dcc_chess.pieces import Piece, PieceType, Color
from dcc_chess.board import Board
from dcc_chess.dice import DungeonDice
from dcc_chess.abilities import GameState
from dcc_chess import ai


def place(board, pos, piece_type, color, pawn_name=None):
    piece = Piece(piece_type, color, pawn_name=pawn_name)
    board.set(pos[0], pos[1], piece)
    return piece


def sixes():
    dice = DungeonDice()
    dice.dice, dice.used = [6, 6], [False, False]
    return dice


def setup(donut=(3, 3), mongo=(5, 5), color=Color.WHITE):
    board = Board()
    place(board, (0, 0), PieceType.CARL, Color.WHITE)
    place(board, (10, 10), PieceType.CARL, Color.BLACK)
    gs = GameState(board)
    gs.current_player = color
    d = place(board, donut, PieceType.DONUT, color) if donut else None
    m = place(board, mongo, PieceType.MONGO, color)
    return gs, d, m


def next_own_turn(gs):
    gs.end_turn()
    gs.start_turn()
    gs.end_turn()
    gs.start_turn()


def store(gs, pos=(5, 5)):
    dice = sixes()
    assert gs.try_pet_carrier(pos, dice, 0)
    return dice


# ── Store / release cycle ────────────────────────────────────────────

def test_store_then_release_full_cycle():
    gs, _, mongo = setup()
    dice = store(gs)
    assert gs.board.get(5, 5) is None
    assert gs.stored_mongo[Color.WHITE]["piece"] is mongo
    assert dice.used == [True, False]
    assert gs.mongo_release_squares(Color.WHITE) == []      # not the turn he went in

    next_own_turn(gs)
    squares = gs.mongo_release_squares(Color.WHITE)
    assert squares and all(max(abs(r - 3), abs(c - 3)) <= 2 for r, c in squares)
    assert gs.try_release_mongo(Color.WHITE, (4, 4))
    assert gs.board.get(4, 4) is mongo and gs.stored_mongo[Color.WHITE] is None

    # He can't move (or capture) the turn he comes out...
    assert not [m for m in gs.get_legal_moves_with_status(Color.WHITE) if m[0] == (4, 4)]
    # ...but can on his side's next turn.
    next_own_turn(gs)
    assert [m for m in gs.get_legal_moves_with_status(Color.WHITE) if m[0] == (4, 4)]


def test_release_squares_skip_occupied_zones_and_boss():
    gs, _, _ = setup(donut=(5, 5), mongo=(8, 8))
    place(gs.board, (5, 6), PieceType.PAWN, Color.WHITE, "Zev")
    store(gs, (8, 8))
    next_own_turn(gs)
    gs.lava_zones[(4, 4)] = 2
    gs.boss_active, gs.boss_squares = True, [(7, 7)]
    squares = set(gs.mongo_release_squares(Color.WHITE))
    assert (5, 6) not in squares and (4, 4) not in squares and (7, 7) not in squares
    assert (5, 5) not in squares                              # Donut's own square
    assert (6, 6) in squares and (3, 3) in squares
    assert not gs.try_release_mongo(Color.WHITE, (4, 4))
    assert not gs.try_release_mongo(Color.WHITE, (9, 9))      # more than 2 from Donut


def test_release_never_leaves_carl_in_check():
    """With Carl in check along row 0, the only legal release squares block it."""
    gs, _, _ = setup(donut=(2, 4), mongo=(5, 5))
    store(gs)
    next_own_turn(gs)
    place(gs.board, (0, 9), PieceType.SAMANTHA, Color.BLACK)
    assert set(gs.mongo_release_squares(Color.WHITE)) == {(0, c) for c in range(2, 7)}


def test_store_needs_donut_and_only_one_at_a_time():
    gs, _, _ = setup(donut=None)
    dice = sixes()
    assert gs.pet_carrier_store_blocker((5, 5)) == "Needs Donut on the board"
    assert not gs.try_pet_carrier((5, 5), dice, 0) and dice.used == [False, False]

    gs, _, _ = setup()
    place(gs.board, (6, 8), PieceType.MONGO, Color.WHITE)
    store(gs)
    dice = sixes()
    assert gs.pet_carrier_store_blocker((6, 8)) == "A Mongo is already stored"
    assert not gs.try_pet_carrier((6, 8), dice, 0) and dice.used == [False, False]


# ── Losing Donut ─────────────────────────────────────────────────────

def test_captured_donut_takes_stored_mongo():
    gs, donut, mongo = setup()
    store(gs)
    sam = place(gs.board, (3, 9), PieceType.SAMANTHA, Color.BLACK)
    captured = gs.board.make_move((3, 9), (3, 3))
    gs.process_post_capture(captured, (3, 3), sam, (3, 9))
    assert gs.stored_mongo[Color.WHITE] is None
    assert mongo in gs.board.captured[Color.WHITE] and not mongo.permanently_dead


def test_fireball_on_donut_takes_stored_mongo():
    gs, donut, mongo = setup()
    store(gs)
    gs.eliminate_piece_permanently(3, 3)
    assert donut.permanently_dead
    assert mongo in gs.board.captured[Color.WHITE] and not mongo.permanently_dead
    assert gs.stored_mongo[Color.WHITE] is None


def test_any_other_way_donut_leaves_is_caught_at_end_of_turn():
    gs, _, mongo = setup()
    store(gs)
    gs.board.set(3, 3, None)
    gs.end_turn()
    assert mongo in gs.board.captured[Color.WHITE] and gs.stored_mongo[Color.WHITE] is None


def test_released_mongo_cannot_rampage_that_turn():
    gs, _, mongo = setup()
    store(gs)
    next_own_turn(gs)
    gs.try_release_mongo(Color.WHITE, (4, 4))
    place(gs.board, (6, 5), PieceType.PAWN, Color.BLACK, "Zev")   # a knight's jump away
    dice = sixes()
    assert gs.try_rampage((4, 4), dice) is None and dice.used == [False, False]


# ── Routes ───────────────────────────────────────────────────────────

def _route_game(A, gs):
    dice = sixes()
    A.game_data.clear()
    A.game_data.update({"game_state": gs, "dice": dice, "mode": "pvp", "phase": "ability",
                        "white_pawns": [], "black_pawns": []})
    return dice


def test_release_route_is_free_and_mongo_cannot_move_that_turn():
    import app as A
    client = A.app.test_client()
    gs, _, mongo = setup()
    store(gs)
    next_own_turn(gs)
    dice = _route_game(A, gs)

    state = A.build_game_state_response()
    assert state["stored_mongo"]["white"] == 0
    assert [4, 4] in state["mongo_release_squares"]
    assert {"piece": "Mongo", "effect": "Stored in Pet Carrier", "turns": None} in state["status_effects"]["white"]

    assert client.post("/release_mongo", json={"row": 9, "col": 9}).status_code == 400
    resp = client.post("/release_mongo", json={"row": 4, "col": 4})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["stored_mongo"]["white"] is None and data["board"][4][4]["name"] == "Mongo"
    assert dice.used == [False, False]                        # no dice spent

    # Moving Mongo is illegal this turn; another piece still makes the move.
    assert client.post("/move", json={"from_row": 4, "from_col": 4,
                                      "to_row": 6, "to_col": 5}).status_code == 400
    assert client.post("/move", json={"from_row": 3, "from_col": 3,
                                      "to_row": 3, "to_col": 4}).status_code == 200


def test_pet_carrier_card_says_why_it_cannot_store():
    import app as A
    gs, _, mongo = setup(donut=None)
    cards = {ab["name"]: ab for ab in A.get_piece_abilities(mongo, gs, 5, 5)}
    assert cards["Pet Carrier"]["unavailable"] == "Needs Donut on the board"


# ── AI ───────────────────────────────────────────────────────────────

def test_ai_stores_an_attacked_mongo():
    gs, _, mongo = setup(donut=(9, 9), mongo=(5, 5), color=Color.BLACK)
    place(gs.board, (5, 0), PieceType.SAMANTHA, Color.WHITE)   # attacks Mongo along row 5
    ai.smart_abilities(gs, sixes(), Color.BLACK)
    assert gs.stored_mongo[Color.BLACK]["piece"] is mongo


def test_ai_releases_onto_a_safe_square():
    gs, _, mongo = setup(donut=(8, 5), mongo=(5, 5), color=Color.BLACK)
    store(gs)
    next_own_turn(gs)
    place(gs.board, (6, 0), PieceType.SAMANTHA, Color.WHITE)   # attacks row 6
    ai.release_stored_mongo(gs, Color.BLACK)
    pos = next((r, c) for r, c, p in gs.board.all_pieces(Color.BLACK) if p is mongo)
    assert pos[0] != 6 and gs.stored_mongo[Color.BLACK] is None


def test_ai_never_leaves_mongo_stored_forever(monkeypatch):
    """Every release square is attacked: the AI waits, then releases anyway."""
    gs, _, mongo = setup(donut=(8, 5), mongo=(5, 5), color=Color.BLACK)
    store(gs)
    monkeypatch.setattr(ai, "_attacked_squares",
                        lambda board, color: {(r, c) for r in range(11) for c in range(11)})
    next_own_turn(gs)
    ai.release_stored_mongo(gs, Color.BLACK)
    assert gs.stored_mongo[Color.BLACK] is not None             # no safe square yet
    next_own_turn(gs)                                           # 4 turns stored
    ai.release_stored_mongo(gs, Color.BLACK)
    assert gs.stored_mongo[Color.BLACK] is None
