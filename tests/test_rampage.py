"""v0.81: Mongo's Rampage runs each victim through the normal capture rules --
Ren's Indestructible and Body Guard (Sledge's or Juice Box's) are skipped, and
Quasar's Mediation can save a victim, which is then simply left alone."""

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


def setup(mongo=(5, 5)):
    board = Board()
    place(board, (0, 0), PieceType.CARL, Color.WHITE)
    place(board, (10, 10), PieceType.CARL, Color.BLACK)
    gs = GameState(board)
    m = place(board, mongo, PieceType.MONGO, Color.WHITE)
    return gs, m


def protected_board():
    """Mongo on (5, 5) with Ren, a Body Guard Sledge, a Body Guard Juice Box,
    and a plain Zev on his knight squares."""
    gs, mongo = setup()
    ren = place(gs.board, (7, 6), PieceType.PAWN, Color.BLACK, "Ren")
    sledge = place(gs.board, (7, 4), PieceType.PAWN, Color.BLACK, "Sledge")
    juice = place(gs.board, (3, 6), PieceType.PAWN, Color.BLACK, "Juice Box")
    zev = place(gs.board, (3, 4), PieceType.PAWN, Color.BLACK, "Zev")
    gs.iron_wall_pieces[(7, 4)] = 2
    gs.iron_wall_pieces[(3, 6)] = 2
    return gs, mongo, ren, sledge, juice, zev


def test_plan_skips_ren_and_body_guard():
    gs, *_ = protected_board()
    victims, dests = gs.rampage_plan((5, 5))
    assert victims == [(3, 4)]
    assert not {(7, 6), (7, 4), (3, 6)} & set(dests)
    assert (3, 4) in dests


def test_rampage_only_captures_unprotected_pieces():
    gs, mongo, ren, sledge, juice, zev = protected_board()
    result = gs.try_rampage((5, 5), sixes())
    assert result and (3, 4) in result
    assert gs.board.get(7, 6) is ren and gs.board.get(7, 4) is sledge and gs.board.get(3, 6) is juice
    assert gs.board.get(3, 4) is None and zev in gs.board.captured[Color.BLACK]
    assert ren not in gs.board.captured[Color.BLACK]


def test_ren_is_capturable_when_pawn_abilities_are_off():
    gs, mongo, ren, *_ = protected_board()
    gs.pawns_enabled = False
    assert (7, 6) in gs.rampage_plan((5, 5))[0]


def test_mediation_save_leaves_the_victim_and_mongo_alone(monkeypatch):
    gs, mongo = setup()
    place(gs.board, (9, 0), PieceType.PAWN, Color.BLACK, "Quasar")
    zev = place(gs.board, (3, 4), PieceType.PAWN, Color.BLACK, "Zev")
    imani = place(gs.board, (6, 7), PieceType.PAWN, Color.BLACK, "Imani")
    monkeypatch.setattr(gs, "_mediation_rolloff", lambda *a, **k: (True, 4, 10))

    result = gs.try_rampage((5, 5), sixes())
    assert gs.board.get(3, 4) is zev and gs.board.get(6, 7) is imani
    assert gs.board.get(5, 5) is mongo and mongo not in gs.board.captured[Color.WHITE]
    assert gs.board.captured[Color.BLACK] == []
    assert gs.quasar_uses[Color.BLACK] == 2
    assert [e["reason"] for e in gs.events if e["type"] == "rampage_skip"] == ["defended_quasar"] * 2
    assert (3, 4) not in result and (6, 7) not in result


def test_mediation_loss_still_captures(monkeypatch):
    gs, mongo = setup()
    place(gs.board, (9, 0), PieceType.PAWN, Color.BLACK, "Quasar")
    zev = place(gs.board, (3, 4), PieceType.PAWN, Color.BLACK, "Zev")
    monkeypatch.setattr(gs, "_mediation_rolloff", lambda *a, **k: (False, 10, 4))
    gs.try_rampage((5, 5), sixes())
    assert zev in gs.board.captured[Color.BLACK] and gs.board.get(3, 4) is None


def test_mongo_stays_put_when_a_save_leaves_nowhere_to_land(monkeypatch):
    """Mongo on B1: his only landing squares are a friendly-blocked A3 and D2,
    and C3, where the saved victim still stands."""
    gs, mongo = setup(mongo=(0, 1))
    place(gs.board, (2, 0), PieceType.KATIA, Color.WHITE)
    place(gs.board, (1, 3), PieceType.PAWN, Color.WHITE, "Zev")
    place(gs.board, (9, 0), PieceType.PAWN, Color.BLACK, "Quasar")
    place(gs.board, (2, 2), PieceType.PAWN, Color.BLACK, "Imani")
    monkeypatch.setattr(gs, "_mediation_rolloff", lambda *a, **k: (True, 4, 10))
    assert gs.try_rampage((0, 1), sixes()) == [(0, 1)]


def test_get_targets_never_offers_a_protected_square():
    import app as A
    gs, *_ = protected_board()
    A.game_data.clear()
    A.game_data.update({"game_state": gs, "dice": sixes(), "mode": "pvp", "phase": "ability",
                        "white_pawns": [], "black_pawns": []})
    resp = A.app.test_client().post("/ability/get_targets", json={
        "piece_row": 5, "piece_col": 5, "ability_name": "Rampage", "die_index": 0})
    targets = resp.get_json()["valid_targets"]
    assert [3, 4] in targets
    assert not [t for t in targets if t in ([7, 6], [7, 4], [3, 6])]


def test_ai_doesnt_rampage_at_protected_pieces_only():
    gs, mongo = setup()
    place(gs.board, (7, 6), PieceType.PAWN, Color.BLACK, "Ren")
    ai.smart_abilities(gs, sixes(), Color.WHITE)
    assert not gs.rampaging_charge_used.get((Color.WHITE, id(mongo)))
    assert gs.board.get(7, 6) is not None
