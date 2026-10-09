"""Game loop and turn flow for DCC Chess.

Turn sequence:
1. Start turn (clear per-turn state)
2. Player moves a piece (standard chess movement with status effect filters)
3. Roll 3 Dungeon Dice
4. Player may spend dice on abilities (up to 3)
5. End turn (tick durations, swap player)
"""

import random
from typing import Optional, Tuple, List

from .pieces import Piece, PieceType, Color
from .board import Board, BOARD_SIZE
from .dice import DungeonDice
from .movement import all_legal_moves, is_checkmate, is_stalemate, is_in_check
from .abilities import GameState


class Game:
    """Manages a full game of DCC Chess."""

    MAX_TURNS = 300  # Safety limit to prevent infinite games

    def __init__(self, white_pawns=None, black_pawns=None,
                 white_back_rank=None, black_back_rank=None):
        self.board = Board()
        self.board.setup_initial_position(
            white_pawns=white_pawns,
            black_pawns=black_pawns,
            white_back_rank=white_back_rank,
            black_back_rank=black_back_rank,
        )
        self.state = GameState(self.board)
        self.state.init_pawn_ability_tracking()
        self.dice = DungeonDice()
        self.game_over = False
        self.winner = None  # Color or None (draw)
        self.result_reason = ""

    def play_turn(self, move_fn, ability_fn=None):
        """Play a single turn, in the same order as a human turn: roll the
        dice, use abilities, then move.

        Args:
            move_fn: callable(game_state, legal_moves) -> (from_pos, to_pos)
                     Picks a move for the current player.
            ability_fn: callable(game_state, dice, color) -> None
                        Spends dice on abilities. If None, no abilities used.
        """
        if self.game_over:
            return

        color = self.state.current_player
        self.state.start_turn()

        # 1. No legal move at all ends the game before any dice are rolled
        if not self.state.get_legal_moves_with_status(color):
            self._end_without_a_move(color)
            return

        # 2. Roll Dungeon Dice and use abilities
        self.dice.roll()
        self.state.log_event("dice_roll", values=self.dice.dice[:])
        if ability_fn:
            ability_fn(self.state, self.dice, color)

        # 3. Player picks a move from what's legal after the abilities
        legal = self.state.get_legal_moves_with_status(color)
        if not legal:
            self._end_without_a_move(color)
            return
        from_pos, to_pos = move_fn(self.state, legal)

        # 4. Execute the move (with capture interception)
        target = self.board.get(*to_pos)
        captured = None

        if target is not None:
            cap_result = self.state.attempt_capture(from_pos, to_pos)
            if cap_result == "captured":
                captured = self.board.make_move(from_pos, to_pos)
                if captured:
                    attacker = self.board.get(*to_pos)
                    self.state.process_post_capture(captured, to_pos, attacker, from_pos)
            elif cap_result == "defended_quasar":
                # Quasar mediation — attacker is captured instead!
                attacker = self.board.get(*from_pos)
                self.board.set(from_pos[0], from_pos[1], None)
                if attacker:
                    self.board.captured[attacker.color].append(attacker)
                    self.state.log_event("mediation_capture", captured=repr(attacker))
            else:
                captured = self.board.make_move(from_pos, to_pos)
        else:
            captured = self.board.make_move(from_pos, to_pos)

        self.state.log_event("move", piece=repr(self.board.get(*to_pos) if self.board.get(*to_pos) else "?"),
                             from_pos=from_pos, to_pos=to_pos,
                             captured=repr(captured) if captured else None)

        # 5. Check for game end after move
        opponent = color.opponent
        if is_checkmate(self.board, opponent):
            self.game_over = True
            self.winner = color
            self.result_reason = "checkmate"
            self.state.log_event("game_over", result="checkmate", winner=color.value)
            self.state.end_turn()
            return

        if is_stalemate(self.board, opponent):
            self.game_over = True
            self.winner = None
            self.result_reason = "stalemate"
            self.state.log_event("game_over", result="stalemate")
            self.state.end_turn()
            return

        # Check if king was captured (shouldn't happen with legal moves, but safety)
        if self.board.find_king(opponent) is None:
            self.game_over = True
            self.winner = color
            self.result_reason = "king_captured"
            self.state.log_event("game_over", result="king_captured", winner=color.value)
            self.state.end_turn()
            return

        # 6. End turn
        self.state.end_turn()

        # Safety: max turns
        if self.state.turn_number >= self.MAX_TURNS:
            self.game_over = True
            self.winner = None
            self.result_reason = "max_turns"
            self.state.log_event("game_over", result="max_turns")

    def _end_without_a_move(self, color):
        """`color` has no legal move: checkmate if in check, otherwise stalemate."""
        self.game_over = True
        if is_in_check(self.board, color):
            self.winner = color.opponent
            self.result_reason = "checkmate"
            self.state.log_event("game_over", result="checkmate", winner=self.winner.value)
        else:
            self.winner = None
            self.result_reason = "stalemate"
            self.state.log_event("game_over", result="stalemate")

    def play_full_game(self, move_fn, ability_fn=None):
        """Play a complete game until game over."""
        while not self.game_over:
            self.play_turn(move_fn, ability_fn)
        return self.winner, self.result_reason
