"""v0.80: the PvAI random draft, the AI's roll -> ability -> move turn order,
abilities that can't leave their own Carl in check or capture Carl directly,
and the random AI using only current abilities."""

import os
import random
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from dcc_chess.pieces import Piece, PieceType, Color
from dcc_chess.board import Board, PAWN_ROSTER
from dcc_chess.dice import DungeonDice
from dcc_chess.abilities import GameState
from dcc_chess import ai
from dcc_chess.game import Game
from dcc_chess.movement import is_in_check


def place(board, pos, piece_type, color, pawn_name=None):
    piece = Piece(piece_type, color, pawn_name=pawn_name)
    board.set(pos[0], pos[1], piece)
    return piece


def board_with_carls(white_carl=(0, 0), black_carl=(10, 10)):
    board = Board()
    place(board, white_carl, PieceType.CARL, Color.WHITE)
    place(board, black_carl, PieceType.CARL, Color.BLACK)
    return GameState(board)


def sixes():
    dice = DungeonDice()
    dice.dice, dice.used = [6, 6], [False, False]
    return dice


# ── PvAI draft ───────────────────────────────────────────────────────

def test_pvai_ai_drafts_random_roster():
    import app as A
    client = A.app.test_client()
    draftable = [n for n in PAWN_ROSTER if n != "The AI"]
    white = draftable[:8]
    rosters = []
    for _ in range(30):
        resp = client.post("/new_game", json={"mode": "pvai", "white_pawns": white,
                                              "black_pawns": ["ignored"]}).get_json()
        black = resp["black_pawns"]
        assert len(black) == 8 and len(set(black)) == 8
        assert "The AI" not in black and set(black) <= set(draftable)
        rosters.append(tuple(sorted(black)))
    assert len(set(rosters)) > 20                                # different every game
    assert any(set(r) & set(white) for r in rosters)             # independent of White's picks


# ── AI turn order ────────────────────────────────────────────────────

def test_ai_rolls_then_uses_ability_then_moves(monkeypatch):
    """Black's Signet pulls White's Mongo onto Black Samantha's file, before Black moves."""
    import app as A
    gs = board_with_carls()
    place(gs.board, (5, 5), PieceType.PAWN, Color.BLACK, "Signet")
    place(gs.board, (10, 7), PieceType.SAMANTHA, Color.BLACK)
    mongo = place(gs.board, (5, 8), PieceType.MONGO, Color.WHITE)
    gs.current_player = Color.BLACK
    gs.ai_summon_enabled = False
    dice = DungeonDice()
    monkeypatch.setattr(dice, "roll", lambda: (setattr(dice, "dice", [6, 6]),
                                               setattr(dice, "used", [False, False]))[0])
    A.game_data.clear()
    A.game_data.update({"game_state": gs, "dice": dice, "mode": "pvai", "phase": "move",
                        "white_pawns": [], "black_pawns": ["Signet"]})

    A._play_ai_turn()

    types = [e["type"] for e in gs.events]
    assert types.index("dice_roll") < types.index("ability_roll") < types.index("pull") < types.index("ai_move")
    assert sum(t == "ability_roll" for t in types) == 1
    assert gs.board.get(5, 7) is mongo or mongo in gs.board.captured[Color.WHITE]


# ── No ability can leave its own Carl in check ───────────────────────
# White Carl on A1 (0, 0); a Black bishop (Katia) on G7 (6, 6) is blocked only
# by the White piece under test on the a1-g7 diagonal.

def pinned(piece_type, pawn_name=None, pin_square=(2, 2)):
    gs = board_with_carls()
    piece = place(gs.board, pin_square, piece_type, Color.WHITE, pawn_name)
    place(gs.board, (6, 6), PieceType.KATIA, Color.BLACK)
    assert not is_in_check(gs.board, Color.WHITE)
    return gs, piece


def test_special_boy_pinned_spends_nothing():
    gs, _ = pinned(PieceType.PAWN, "Prepotente", pin_square=(3, 3))
    dice = sixes()
    assert gs.special_boy_destinations((3, 3)) == []
    assert gs.try_special_boy((3, 3), dice, 0) is None
    assert dice.used == [False, False]


def test_special_boy_never_captures_carl_and_captures_go_to_graveyard():
    gs = board_with_carls(black_carl=(5, 6))
    place(gs.board, (3, 5), PieceType.PAWN, Color.WHITE, "Prepotente")
    zev = place(gs.board, (5, 4), PieceType.PAWN, Color.BLACK, "Zev")
    dests = gs.special_boy_destinations((3, 5))
    assert (5, 6) not in dests and (5, 4) in dests
    gs.apply_ability_move((3, 5), (5, 4))
    assert zev in gs.board.captured[Color.BLACK]


def test_puddle_jump_stays_on_the_pin_line():
    gs, _ = pinned(PieceType.DONUT)
    assert set(gs.puddle_jump_destinations((2, 2))) == {(1, 1), (3, 3), (4, 4), (5, 5)}


def test_pet_carrier_cannot_store_a_pinned_mongo():
    gs, mongo = pinned(PieceType.MONGO)
    dice = sixes()
    assert not gs.try_pet_carrier((2, 2), dice, 0)
    assert gs.board.get(2, 2) is mongo and dice.used == [False, False]


def test_rampage_needs_a_safe_landing_square():
    gs, mongo = pinned(PieceType.MONGO)
    place(gs.board, (4, 3), PieceType.PAWN, Color.BLACK, "Zev")  # a victim on his knight square
    dice = sixes()
    assert gs.rampage_plan((2, 2))[1] == []
    assert gs.try_rampage((2, 2), dice) is None
    assert dice.used == [False, False] and gs.board.get(4, 3) is not None


def test_slut_shame_skips_a_pawn_that_shields_carl():
    gs = board_with_carls()
    place(gs.board, (5, 2), PieceType.SAMANTHA, Color.WHITE)
    place(gs.board, (3, 3), PieceType.PAWN, Color.BLACK, "Zev")     # shields Carl from Katia
    place(gs.board, (5, 3), PieceType.PAWN, Color.BLACK, "Imani")
    place(gs.board, (6, 6), PieceType.KATIA, Color.BLACK)
    assert gs.slut_shame_targets((5, 2)) == [(5, 3)]
    dice = sixes()
    assert not gs.try_slut_shame((5, 2), dice, target_pos=(3, 3))
    assert dice.used == [False, False]


def test_suppressing_fire_never_pushes_a_piece_into_check():
    gs = board_with_carls()
    place(gs.board, (1, 2), PieceType.PAWN, Color.WHITE, "Florin")
    place(gs.board, (2, 1), PieceType.SAMANTHA, Color.BLACK)   # would be pushed to A4, onto Carl's file
    place(gs.board, (1, 5), PieceType.PAWN, Color.BLACK, "Zev")
    assert gs.suppressing_fire_pushes((1, 2)) == {(1, 5): (1, 7)}


def test_blood_magic_skips_a_sacrifice_that_shields_carl():
    gs, _ = pinned(PieceType.PAWN, "Zev")
    place(gs.board, (2, 3), PieceType.PAWN, Color.WHITE, "Miriam Dom")
    place(gs.board, (3, 4), PieceType.PAWN, Color.WHITE, "Imani")
    assert gs.blood_magic_sacrifices((2, 3)) == [(3, 4)]


def test_retired_abilities_rejected_by_route():
    import app as A
    gs = board_with_carls()
    place(gs.board, (4, 4), PieceType.MONGO, Color.WHITE)
    A.game_data.clear()
    A.game_data.update({"game_state": gs, "dice": sixes(), "mode": "pvp", "phase": "ability",
                        "white_pawns": [], "black_pawns": []})
    client = A.app.test_client()
    for name in ["Mongo Smash", "Rampaging Charge", "Bulldozer"]:
        r = client.post("/ability", json={"piece_row": 4, "piece_col": 4,
                                          "ability_name": name, "die_index": 0})
        assert r.status_code == 400 and "Unknown ability" in r.get_json()["error"]


# ── Random AI: current abilities only, one per turn ──────────────────

LEGACY = ["try_bulldozer", "try_divas_entrance", "try_resurrection", "try_rampaging_charge",
          "try_mongo_smash", "try_combat_roll", "try_dual_threat", "try_the_mouth",
          "try_portal_spike", "try_pack_rally", "try_glitch", "try_titan_stride",
          "try_suppression", "try_recruit", "try_smoke_bomb", "try_iron_wall", "try_sicced",
          "try_lava_surge", "try_shapeshift", "try_meditative_strike"]


def _server_game(A, client, seed, max_turns=120):
    """Play one AI-vs-AI game through the real routes: White via /start_turn,
    random_abilities and /move; Black via /ai_turn. Both move randomly."""
    random.seed(seed)
    client.post("/new_game", json={"mode": "dev", "white_pawns": ai.random_draft(),
                                   "black_pawns": ai.random_draft(), "ai_enabled": False})
    A.game_data["mode"] = "pvai"
    gs = A.game_data["game_state"]
    while not A.game_data.get("game_over") and gs.turn_number < max_turns:
        if gs.current_player == Color.BLACK:
            assert client.post("/ai_turn").status_code == 200
        elif A.game_data["phase"] == "move":
            assert client.post("/start_turn").status_code == 200
        else:
            ai.random_abilities(gs, A.game_data["dice"], Color.WHITE)
            legal = gs.get_legal_moves_with_status(Color.WHITE)
            if not legal:
                client.post("/end_turn")
                continue
            (fr, fc), (tr, tc) = random.choice(legal)
            assert client.post("/move", json={"from_row": fr, "from_col": fc,
                                              "to_row": tr, "to_col": tc}).status_code == 200
    return gs


def test_random_ai_uses_only_current_abilities(monkeypatch):
    import app as A

    def retired(*_args, **_kwargs):
        raise AssertionError("random AI used a retired ability")
    for name in LEGACY:
        monkeypatch.setattr(GameState, name, retired)
    monkeypatch.setattr(A, "smart_abilities", ai.random_abilities)  # Black's /ai_turn
    monkeypatch.setattr(A, "smart_move", lambda gs, legal: random.choice(legal))
    A.app.testing = True
    client = A.app.test_client()

    rolls = 0
    for seed in range(6):
        gs = _server_game(A, client, seed)
        assert A.game_data.get("result_reason") != "king_captured"
        per_turn = {}
        for e in gs.events:
            if e["type"] == "ability_roll":
                per_turn[e["turn"]] = per_turn.get(e["turn"], 0) + 1
                rolls += 1
        assert all(n == 1 for n in per_turn.values()), "more than one ability in a turn"
    assert rolls > 0


# ── Carl is never captured outright (seed 5005) ─────────────────────

def test_swallowed_pawn_respawns_once_and_never_into_check():
    """Black's Samantha swallowed White's Louie. When he respawns at the end
    of Black's turn he must appear exactly once, and never on a square
    attacking Black's Carl (White would move next and take him)."""
    gs = board_with_carls(black_carl=(10, 4))
    louie = Piece(PieceType.PAWN, Color.WHITE, pawn_name="Louie")
    gs.swallowed_pawns.append({"piece": louie, "turns_left": 1, "samantha_pos": (10, 6)})
    gs.current_player = Color.BLACK
    gs.end_turn()
    spots = [(r, c) for r in range(11) for c in range(11) if gs.board.get(r, c) is louie]
    assert len(spots) == 1
    assert spots[0] != (9, 5) and not is_in_check(gs.board, Color.BLACK)


def test_swallowed_pawn_waits_when_no_safe_square():
    gs = board_with_carls()
    for sq in [(4, 4), (4, 5), (4, 6), (5, 4), (5, 6), (6, 4), (6, 5), (6, 6)]:
        place(gs.board, sq, PieceType.PAWN, Color.BLACK, "Zev")
    zev = Piece(PieceType.PAWN, Color.WHITE, pawn_name="Zev")
    gs.swallowed_pawns.append({"piece": zev, "turns_left": 1, "samantha_pos": (5, 5)})
    gs.end_turn()
    assert gs.swallowed_pawns and gs.swallowed_pawns[0]["piece"] is zev  # kept, not lost
    gs.board.set(4, 4, None)
    gs.end_turn()
    assert gs.board.get(4, 4) is zev and not gs.swallowed_pawns


def test_mordecai_never_respawns_into_check():
    """White's Mordecai respawning on A1 at the end of Black's turn would
    attack Black's Carl on B2, so he takes another back-rank square."""
    gs = board_with_carls(white_carl=(0, 10), black_carl=(1, 1))
    mord = Piece(PieceType.PAWN, Color.WHITE, pawn_name="Mordecai")
    gs.mordecai_respawn_pending.append({"piece": mord, "turns_left": 1, "color": Color.WHITE})
    gs.current_player = Color.BLACK
    gs.end_turn()
    assert gs.board.get(0, 0) is None and gs.board.get(0, 2) is None
    assert not is_in_check(gs.board, Color.BLACK)
    assert any(gs.board.get(0, c) is mord for c in range(11))


def test_carl_capture_is_never_a_legal_move():
    gs = board_with_carls(black_carl=(5, 5))
    place(gs.board, (5, 0), PieceType.SAMANTHA, Color.WHITE)  # Black's Carl is in check
    moves = gs.get_legal_moves_with_status(Color.WHITE)
    assert all(to != (5, 5) for _, to in moves)


def test_fireball_fizzles_on_carl(monkeypatch):
    from dcc_chess import ai_cards
    gs = board_with_carls(white_carl=(1, 1))
    monkeypatch.setattr(ai_cards.random, "randint", lambda a, b: 1)  # Fireball hits (1, 1)
    ai_cards._resolve_fireball(gs, Color.BLACK)
    assert gs.board.get(1, 1) is not None and gs.board.get(1, 1).is_king
    place(gs.board, (1, 1), PieceType.MONGO, Color.WHITE)
    ai_cards._resolve_fireball(gs, Color.BLACK)
    assert gs.board.get(1, 1) is None  # any other piece is still killed
