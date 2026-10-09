"""Tests for the pull abilities: Stripper Anaconda's Gun Show and Signet's
Succubus, cast by their own pawn and by Juice Box (Shapeshift copy).

Every scenario runs for all four casters. The board is 11x11 with rows
counted from White's back rank (row 0); the caster always stands on (5, 5).
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from dcc_chess.pieces import Piece, PieceType, Color
from dcc_chess.board import Board
from dcc_chess.dice import DungeonDice
from dcc_chess.abilities import GameState

CASTER_POS = (5, 5)

# (caster pawn, ability, is Juice Box copy)
CASTERS = [
    ("Signet", "Succubus", False),
    ("Stripper Anaconda", "Gun Show", False),
    ("Juice Box", "Succubus", True),
    ("Juice Box", "Gun Show", True),
]
CASTER_IDS = ["Signet", "Anaconda", "JuiceBox-Succubus", "JuiceBox-GunShow"]

# A piece of the gender each ability pulls, plus a gendered pawn for blocker tests.
TARGET_TYPE = {"Succubus": PieceType.MONGO, "Gun Show": PieceType.DONUT}
GENDERED_PAWN = {"Succubus": "Florin", "Gun Show": "Zev"}
SOURCE_PAWN = {"Succubus": "Signet", "Gun Show": "Stripper Anaconda"}


def place(board, pos, piece_type, color, pawn_name=None):
    piece = Piece(piece_type, color, pawn_name=pawn_name)
    board.set(pos[0], pos[1], piece)
    return piece


def setup(caster_name, ability, juice_box, white_carl=(0, 0), black_carl=(10, 10)):
    """Both Carls plus a White caster on CASTER_POS. Juice Box gets the source
    pawn's ability as if she had captured it."""
    board = Board()
    place(board, white_carl, PieceType.CARL, Color.WHITE)
    place(board, black_carl, PieceType.CARL, Color.BLACK)
    caster = place(board, CASTER_POS, PieceType.PAWN, Color.WHITE, caster_name)
    gs = GameState(board)
    if juice_box:
        gs.juice_box_captured[gs.juice_box_key(caster)] = [SOURCE_PAWN[ability]]
    return gs


def fresh_dice(ability, juice_box):
    """Dice that always pay the cost. Juice Box pays +1, so her Succubus costs 7
    -- more than one d6, so (like the /ability route does when it combines
    both dice) die 0 carries the combined total."""
    dice = DungeonDice()
    cost = GameState.PULL_ABILITIES[ability][1] + (1 if juice_box else 0)
    dice.dice = [cost, 1]
    dice.used = [False, False]
    return dice


def cast(gs, dice, ability, juice_box, target):
    if juice_box:
        return gs.try_juice_box_use_captured_ability(CASTER_POS, ability, dice, 0, target_pos=target)
    if ability == "Succubus":
        return gs.try_succubus(CASTER_POS, dice, 0, target_pos=target)
    return gs.try_gun_show(CASTER_POS, dice, 0, target_pos=target)


def assert_no_dice_spent(gs, dice):
    assert dice.used == [False, False]
    assert not any(e["type"] == "ability_roll" for e in gs.events)


all_casters = pytest.mark.parametrize("caster_name,ability,juice_box", CASTERS, ids=CASTER_IDS)


@all_casters
def test_straight_pull(caster_name, ability, juice_box):
    """Target 3 squares right of the caster moves 1 square left, enemy or friendly."""
    gs = setup(caster_name, ability, juice_box)
    enemy = place(gs.board, (5, 8), TARGET_TYPE[ability], Color.BLACK)
    friend = place(gs.board, (2, 5), TARGET_TYPE[ability], Color.WHITE)
    assert gs.pull_targets(CASTER_POS, ability) == {(5, 8): (5, 7), (2, 5): (3, 5)}

    dice = fresh_dice(ability, juice_box)
    assert cast(gs, dice, ability, juice_box, (5, 8))
    assert gs.board.get(5, 8) is None and gs.board.get(5, 7) is enemy
    assert enemy.has_moved
    assert dice.used[0]

    pull = gs.events[-2] if juice_box else gs.events[-1]  # Juice Box logs her use after the pull
    assert pull["type"] == "pull"
    assert pull["ability"] == ability
    assert pull["target"] == repr(enemy)
    assert pull["to_pos"] == [5, 7]
    assert pull["piece"] == (f"Juice Box ({SOURCE_PAWN[ability]})" if juice_box else caster_name)

    # A friendly piece can be pulled too (fresh caster state for Juice Box's cooldown).
    gs.juice_box_cooldown[Color.WHITE] = False
    assert cast(gs, fresh_dice(ability, juice_box), ability, juice_box, (2, 5))
    assert gs.board.get(3, 5) is friend


@all_casters
def test_diagonal_pull(caster_name, ability, juice_box):
    """Off the caster's lines, the pull steps diagonally (most direct route)."""
    gs = setup(caster_name, ability, juice_box)
    place(gs.board, (8, 6), TARGET_TYPE[ability], Color.BLACK)   # 3 up, 1 right
    place(gs.board, (2, 8), TARGET_TYPE[ability], Color.BLACK)   # true diagonal
    targets = gs.pull_targets(CASTER_POS, ability)
    assert targets[(8, 6)] == (7, 5)
    assert targets[(2, 8)] == (3, 7)

    assert cast(gs, fresh_dice(ability, juice_box), ability, juice_box, (8, 6))
    assert gs.board.get(7, 5) is not None and gs.board.get(8, 6) is None


@all_casters
def test_blocked_pull_square(caster_name, ability, juice_box):
    """Occupied, lava, Air Strike, ghost, and Lava Spit pull squares all block a pull."""
    gs = setup(caster_name, ability, juice_box)
    place(gs.board, (5, 8), TARGET_TYPE[ability], Color.BLACK)  # pulls to (5, 7)
    place(gs.board, (5, 7), PieceType.PAWN, Color.BLACK, "Ren")  # ...which is occupied
    place(gs.board, (8, 5), TARGET_TYPE[ability], Color.BLACK)  # pulls to (7, 5)
    place(gs.board, (2, 5), TARGET_TYPE[ability], Color.BLACK)  # pulls to (3, 5)
    place(gs.board, (5, 2), TARGET_TYPE[ability], Color.BLACK)  # pulls to (5, 3)
    place(gs.board, (8, 8), TARGET_TYPE[ability], Color.BLACK)  # pulls to (7, 7)
    gs.lava_zones[(7, 5)] = 2
    gs.air_strike_zones[(3, 5)] = 2
    gs.ghost_tokens[(5, 3)] = 3
    gs.lava_spit_zones.append({"pos": [(7, 7), (7, 8)], "turns": 3})

    targets = gs.pull_targets(CASTER_POS, ability)
    for blocked in [(5, 8), (8, 5), (2, 5), (5, 2), (8, 8)]:
        assert blocked not in targets

    dice = fresh_dice(ability, juice_box)
    assert not cast(gs, dice, ability, juice_box, (5, 8))
    assert_no_dice_spent(gs, dice)
    assert gs.board.get(5, 8) is not None


@all_casters
def test_adjacent_target(caster_name, ability, juice_box):
    """A piece already next to the caster can't be pulled any closer."""
    gs = setup(caster_name, ability, juice_box)
    place(gs.board, (6, 6), TARGET_TYPE[ability], Color.BLACK)
    place(gs.board, (5, 4), TARGET_TYPE[ability], Color.BLACK)
    assert gs.pull_targets(CASTER_POS, ability) == {}

    dice = fresh_dice(ability, juice_box)
    assert not cast(gs, dice, ability, juice_box, (6, 6))
    assert_no_dice_spent(gs, dice)


@all_casters
def test_carl_and_orthrus_untargetable(caster_name, ability, juice_box):
    """Carl (either side) and Orthrus (2-square body) are never pull targets,
    even though both are male and otherwise in a pullable spot."""
    gs = setup(caster_name, ability, juice_box, white_carl=(2, 2), black_carl=(8, 8))
    orthrus = Piece(PieceType.PAWN, Color.BLACK, pawn_name="Orthrus")
    assert gs.board.place_orthrus_body(orthrus, 5, 9)  # butt (5, 9), head (4, 9)
    targets = gs.pull_targets(CASTER_POS, ability)
    for pos in [(2, 2), (8, 8), (5, 9), (4, 9)]:
        assert pos not in targets

    # Sanity check: a regular male piece in the same kind of spot is pullable by Succubus.
    if ability == "Succubus":
        place(gs.board, (5, 1), PieceType.MONGO, Color.BLACK)
        assert gs.pull_targets(CASTER_POS, ability) == {(5, 1): (5, 2)}

    dice = fresh_dice(ability, juice_box)
    assert not cast(gs, dice, ability, juice_box, (8, 8))
    assert not cast(gs, dice, ability, juice_box, (5, 9))
    assert dice.used == [False, False]


@all_casters
def test_body_guard_target(caster_name, ability, juice_box):
    """A piece under Body Guard is immovable, so it can't be pulled."""
    gs = setup(caster_name, ability, juice_box)
    place(gs.board, (5, 8), PieceType.PAWN, Color.BLACK, GENDERED_PAWN[ability])
    assert (5, 8) in gs.pull_targets(CASTER_POS, ability)
    gs.iron_wall_pieces[(5, 8)] = 2
    assert (5, 8) not in gs.pull_targets(CASTER_POS, ability)

    dice = fresh_dice(ability, juice_box)
    assert not cast(gs, dice, ability, juice_box, (5, 8))
    assert_no_dice_spent(gs, dice)


@all_casters
def test_self_check_rejected(caster_name, ability, juice_box):
    """Pulling a friendly blocker off the line between the caster's Carl and
    an enemy Samantha (Rook) would leave Carl in check, so it's rejected."""
    gs = setup(caster_name, ability, juice_box, white_carl=(2, 1))
    blocker = place(gs.board, (2, 5), PieceType.PAWN, Color.WHITE, GENDERED_PAWN[ability])
    assert (2, 5) in gs.pull_targets(CASTER_POS, ability)  # fine while nothing is behind it

    place(gs.board, (2, 9), PieceType.SAMANTHA, Color.BLACK)
    assert (2, 5) not in gs.pull_targets(CASTER_POS, ability)

    dice = fresh_dice(ability, juice_box)
    assert not cast(gs, dice, ability, juice_box, (2, 5))
    assert_no_dice_spent(gs, dice)
    assert gs.board.get(2, 5) is blocker


@all_casters
def test_no_target_spends_no_dice(caster_name, ability, juice_box):
    """With nothing pullable on the board the ability can't be activated: no
    die is spent, with or without an explicit target."""
    gs = setup(caster_name, ability, juice_box)
    place(gs.board, (5, 8), PieceType.PAWN, Color.BLACK,
          GENDERED_PAWN["Gun Show" if ability == "Succubus" else "Succubus"])  # wrong gender
    assert gs.pull_targets(CASTER_POS, ability) == {}

    dice = fresh_dice(ability, juice_box)
    assert not cast(gs, dice, ability, juice_box, None)
    assert not cast(gs, dice, ability, juice_box, (5, 8))
    assert_no_dice_spent(gs, dice)


@all_casters
def test_pulled_piece_keeps_its_statuses(caster_name, ability, juice_box):
    """A Frozen piece is still Frozen on its new square."""
    gs = setup(caster_name, ability, juice_box)
    place(gs.board, (5, 8), TARGET_TYPE[ability], Color.BLACK)
    gs.frozen_pieces.add((5, 8))
    assert cast(gs, fresh_dice(ability, juice_box), ability, juice_box, (5, 8))
    assert gs.frozen_pieces == {(5, 7)}


@pytest.mark.parametrize("ability", ["Succubus", "Gun Show"])
def test_juice_box_cost_and_cooldown(ability):
    """Juice Box pays the source pawn's cost + 1, and after a pull she's on
    cooldown until her side's next turn."""
    gs = setup("Juice Box", ability, True)
    place(gs.board, (5, 8), TARGET_TYPE[ability], Color.BLACK)
    place(gs.board, (8, 5), TARGET_TYPE[ability], Color.BLACK)

    base_cost = GameState.PULL_ABILITIES[ability][1]
    dice = DungeonDice()
    dice.dice, dice.used = [base_cost, 1], [False, False]
    assert not cast(gs, dice, ability, True, (5, 8))     # base cost isn't enough for her
    assert dice.used[0] and gs.board.get(5, 8) is not None

    assert cast(gs, fresh_dice(ability, True), ability, True, (5, 8))
    assert gs.juice_box_cooldown[Color.WHITE]
    dice = fresh_dice(ability, True)
    assert not cast(gs, dice, ability, True, (8, 5))     # on cooldown
    assert dice.used == [False, False]


def test_gender_rules():
    """Donut, Katia, Samantha and the female pawns are female; Carl, Mongo and
    the other pawns are male."""
    gs = GameState(Board())
    female = [Piece(PieceType.DONUT, Color.WHITE), Piece(PieceType.KATIA, Color.WHITE),
              Piece(PieceType.SAMANTHA, Color.WHITE), Piece(PieceType.PAWN, Color.WHITE, "Signet")]
    male = [Piece(PieceType.CARL, Color.WHITE), Piece(PieceType.MONGO, Color.WHITE),
            Piece(PieceType.PAWN, Color.WHITE, "Stripper Anaconda")]
    assert all(gs.is_piece_female(p) for p in female)
    assert not any(gs.is_piece_female(p) for p in male)


# ── /ability route: an invalid pull must not touch the dice ──────────

@pytest.fixture
def client_game():
    import app as app_module
    gs = setup("Signet", "Succubus", False)
    place(gs.board, (5, 8), PieceType.MONGO, Color.BLACK)
    dice = DungeonDice()
    dice.dice, dice.used = [6, 5], [False, False]
    app_module.game_data.clear()
    app_module.game_data.update({"game_state": gs, "dice": dice, "mode": "pvp", "phase": "ability",
                                 "white_pawns": [], "black_pawns": []})
    return app_module.app.test_client(), gs, dice


def test_route_targets_and_pull(client_game):
    client, gs, dice = client_game
    body = {"piece_row": 5, "piece_col": 5, "ability_name": "Succubus", "die_index": 0}
    resp = client.post("/ability/get_targets", json=body).get_json()
    assert resp["valid_targets"] == [[5, 8]]
    assert resp["pull_squares"] == {"5,8": [5, 7]}

    resp = client.post("/ability", json={**body, "target_row": 5, "target_col": 8}).get_json()
    assert resp["ability_result"]["success"]
    assert resp["board"][5][7]["type"] == "Mongo"


def test_route_rejects_invalid_pull_without_spending(client_game):
    client, gs, dice = client_game
    body = {"piece_row": 5, "piece_col": 5, "ability_name": "Succubus", "die_index": 0,
            "use_combined": True}
    for target in [(5, 6), (10, 10), None]:  # empty square, Carl, no target at all
        payload = dict(body)
        if target:
            payload.update(target_row=target[0], target_col=target[1])
        r = client.post("/ability", json=payload)
        assert r.status_code == 400
    assert dice.dice == [6, 5] and dice.used == [False, False]  # not combined, not locked

    gs.board.set(5, 8, None)  # nothing left to pull
    r = client.post("/ability", json={**body, "target_row": 5, "target_col": 8})
    assert r.status_code == 400 and "No valid target" in r.get_json()["error"]
    assert dice.used == [False, False]


def test_route_sidebar_flags_missing_target(client_game):
    client, gs, dice = client_game
    import app as app_module
    signet = gs.board.get(*CASTER_POS)
    [ab] = app_module.get_piece_abilities(signet, gs, *CASTER_POS)
    assert ab["has_valid_target"] is True
    gs.board.set(5, 8, None)
    [ab] = app_module.get_piece_abilities(signet, gs, *CASTER_POS)
    assert ab["has_valid_target"] is False


# ── AI: only pulls that help ─────────────────────────────────────────

def test_ai_pulls_enemy_into_capture():
    """Black Mongo pulled from I6 to H6 lands on White Samantha's file."""
    from dcc_chess.ai import _best_pull, smart_abilities
    gs = setup("Signet", "Succubus", False)
    place(gs.board, (0, 7), PieceType.SAMANTHA, Color.WHITE)
    mongo = place(gs.board, (5, 8), PieceType.MONGO, Color.BLACK)
    assert _best_pull(gs, CASTER_POS, "Succubus", Color.WHITE) == (5, 8)

    dice = DungeonDice()
    dice.dice, dice.used = [6, 6], [False, False]
    smart_abilities(gs, dice, Color.WHITE)
    assert gs.board.get(5, 7) is mongo


def test_ai_pulls_friendly_out_of_danger():
    """White Mongo on Black Samantha's file is pulled off it."""
    from dcc_chess.ai import _best_pull
    gs = setup("Signet", "Succubus", False)
    place(gs.board, (10, 8), PieceType.SAMANTHA, Color.BLACK)
    place(gs.board, (5, 8), PieceType.MONGO, Color.WHITE)
    assert _best_pull(gs, CASTER_POS, "Succubus", Color.WHITE) == (5, 8)


def test_ai_skips_pointless_pull():
    """A legal pull that changes nothing isn't worth the dice."""
    from dcc_chess.ai import _best_pull, smart_abilities
    gs = setup("Signet", "Succubus", False)
    mongo = place(gs.board, (5, 8), PieceType.MONGO, Color.BLACK)
    assert gs.pull_targets(CASTER_POS, "Succubus")
    assert _best_pull(gs, CASTER_POS, "Succubus", Color.WHITE) is None

    dice = DungeonDice()
    dice.dice, dice.used = [6, 6], [False, False]
    smart_abilities(gs, dice, Color.WHITE)
    assert gs.board.get(5, 8) is mongo
    assert not any(e.get("ability") == "Succubus" for e in gs.events)
