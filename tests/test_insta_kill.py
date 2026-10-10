"""v0.81: What a Bitch's Insta-Kill Boss Card -- the holder plays it on their
own turn during any boss battle, free, to defeat the active boss (Feral Goose
included); it's consumed, and the normal boss-defeat flow runs."""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dcc_chess.pieces import Piece, PieceType, Color
from dcc_chess.board import Board
from dcc_chess.dice import DungeonDice
from dcc_chess.abilities import GameState
from dcc_chess import ai, ai_cards


def setup(boss="Rage Elemental", holder=Color.WHITE):
    board = Board()
    board.set(0, 0, Piece(PieceType.CARL, Color.WHITE))
    board.set(10, 10, Piece(PieceType.CARL, Color.BLACK))
    board.set(1, 1, Piece(PieceType.PAWN, Color.WHITE, pawn_name="Zev"))
    gs = GameState(board)
    gs.current_player = holder
    if boss:
        ai_cards.spawn_boss(gs, boss)
    if holder:
        gs.insta_kill_card[holder] = True
    return gs


def sixes():
    dice = DungeonDice()
    dice.dice, dice.used = [6, 6], [False, False]
    return dice


def test_insta_kill_defeats_the_boss_and_consumes_the_card():
    gs = setup()
    assert gs.try_insta_kill(Color.WHITE)
    assert not gs.boss_active and gs.active_boss is None
    assert gs.insta_kill_card[Color.WHITE] is False
    types = [e["type"] for e in gs.events]
    assert types.index("insta_kill") < types.index("boss_defeated")
    assert not gs.try_insta_kill(Color.WHITE)                  # card is gone


def test_insta_kill_works_on_the_feral_goose():
    gs = setup(boss="Feral Goose")
    assert gs.try_insta_kill(Color.WHITE)
    assert not gs.boss_active


def test_insta_kill_needs_a_boss_and_the_card():
    gs = setup(boss=None)
    assert not gs.try_insta_kill(Color.WHITE)
    assert gs.insta_kill_card[Color.WHITE]                     # kept for a real boss
    gs = setup()
    assert not gs.try_insta_kill(Color.BLACK)                  # Black doesn't hold one


def test_insta_kill_spawns_a_queued_boss():
    gs = setup()
    gs.pending_boss_summon = "Emberus"
    assert gs.try_insta_kill(Color.WHITE)
    assert gs.boss_active and gs.active_boss == "Emberus"


def _route_game(A, gs, phase="ability", mode="pvp"):
    A.game_data.clear()
    A.game_data.update({"game_state": gs, "dice": sixes(), "mode": mode, "phase": phase,
                        "white_pawns": [], "black_pawns": []})


def test_insta_kill_route():
    import app as A
    client = A.app.test_client()

    gs = setup()
    _route_game(A, gs, phase="move")                           # not before rolling
    assert client.post("/insta_kill").status_code == 400

    _route_game(A, gs)
    dice = A.game_data["dice"]
    resp = client.post("/insta_kill")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["boss_active"] is False and data["insta_kill_card"]["white"] is False
    assert dice.used == [False, False]                         # free
    assert client.post("/insta_kill").status_code == 400       # already used

    gs = setup(holder=Color.BLACK)
    gs.current_player = Color.WHITE
    _route_game(A, gs)
    assert client.post("/insta_kill").status_code == 400       # not the holder's turn
    assert gs.boss_active


def test_ai_uses_its_card_when_a_boss_is_active():
    gs = setup(holder=Color.BLACK)
    ai.smart_abilities(gs, sixes(), Color.BLACK)
    assert not gs.boss_active and gs.insta_kill_card[Color.BLACK] is False

    gs = setup(holder=Color.BLACK)
    ai.random_abilities(gs, sixes(), Color.BLACK)
    assert not gs.boss_active


def test_ai_keeps_its_card_without_a_boss():
    gs = setup(boss=None, holder=Color.BLACK)
    ai.smart_abilities(gs, sixes(), Color.BLACK)
    assert gs.insta_kill_card[Color.BLACK]
