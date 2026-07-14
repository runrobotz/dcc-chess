"""Board representation for Dungeon Crawler Carl Chess (10x10)."""

import random
from typing import Optional, List, Tuple

from .pieces import Piece, PieceType, Color, PIECE_SYMBOLS, ORTHRUS_DIRECTIONS


BOARD_SIZE = 11
CENTER_SQUARE = (5, 5)  # Boss spawn point

# The 21 pawn character names in the roster
PAWN_ROSTER = [
    "Zev", "The AI", "Mordecai", "Prepotente", "Elle McGib",
    "Imani", "Slugalo", "Louie", "Sledge", "Stripper Anaconda", "Quasar",
    "Lucia Mar", "Chris", "Juice Box", "Florin", "Garret",
    "Signet", "Miriam Dom", "Orthrus", "Raul the Crab", "Bad Llama",
]

# Standard 8 major pieces per side (mirrors like chess)
MAJOR_PIECE_ORDER = [
    PieceType.SAMANTHA,  # Rook
    PieceType.MONGO,     # Knight (L-shape movement)
    PieceType.KATIA,     # Bishop (diagonal movement)
    PieceType.DONUT,     # Queen
    PieceType.CARL,      # King
    PieceType.KATIA,     # Bishop (diagonal movement)
    PieceType.MONGO,     # Knight (L-shape movement)
    PieceType.SAMANTHA,  # Rook
]


class Board:
    """11x11 board for DCC Chess.

    Internal coordinates: (row, col) where row 0 is white's back rank,
    row 10 is black's back rank. Columns 0-10 map to A-K.
    """

    def __init__(self):
        self.grid: List[List[Optional[Piece]]] = [
            [None] * BOARD_SIZE for _ in range(BOARD_SIZE)
        ]
        # Track en passant target square: (row, col) or None
        self.en_passant_target: Optional[Tuple[int, int]] = None
        # Track captured pieces per color
        self.captured: dict = {Color.WHITE: [], Color.BLACK: []}

    def setup_initial_position(
        self,
        white_pawns: List[str] = None,
        black_pawns: List[str] = None,
        white_back_rank: List[int] = None,
        black_back_rank: List[int] = None,
    ):
        """Set up the starting position.

        Args:
            white_pawns: list of 8 pawn names for white (drafted)
            black_pawns: list of 8 pawn names for black (drafted)
            white_back_rank: list of 8 column indices (0-9) for white's majors
            black_back_rank: list of 8 column indices (0-9) for black's majors
        """
        # Draft pawns randomly if not provided
        if white_pawns is None:
            white_pawns = random.sample(PAWN_ROSTER, 8)
        if black_pawns is None:
            black_pawns = random.sample(PAWN_ROSTER, 8)

        # Default back-rank placement: columns 1-8 (leaving 0 and 9 empty)
        if white_back_rank is None:
            white_back_rank = random.sample(range(BOARD_SIZE), 8)
            white_back_rank.sort()
        if black_back_rank is None:
            black_back_rank = random.sample(range(BOARD_SIZE), 8)
            black_back_rank.sort()

        # Major pieces will be placed during placement phase - this is now a placeholder
        # Keeping this for backward compatibility during transition
        pass

        # Pawns will be placed during placement phase - this is now a placeholder
        # Keeping this for backward compatibility during transition
        pass

    def get(self, row: int, col: int) -> Optional[Piece]:
        """Get piece at position, or None."""
        if not self.in_bounds(row, col):
            return None
        return self.grid[row][col]

    def set(self, row: int, col: int, piece: Optional[Piece]):
        """Set piece at position."""
        self.grid[row][col] = piece

    def in_bounds(self, row: int, col: int) -> bool:
        return 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE

    def find_king(self, color: Color) -> Optional[Tuple[int, int]]:
        """Find the position of a player's Carl (King)."""
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                p = self.grid[r][c]
                if p and p.piece_type == PieceType.CARL and p.color == color:
                    return (r, c)
        return None

    def all_pieces(self, color: Color) -> List[Tuple[int, int, Piece]]:
        """Return all (row, col, piece) for a given color."""
        result = []
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                p = self.grid[r][c]
                if p and p.color == color:
                    result.append((r, c, p))
        return result

    def make_move(self, from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> Optional[Piece]:
        """Execute a move. Returns captured piece or None.

        Handles:
        - Normal moves and captures
        - Pawn double-move en passant tracking
        - En passant captures
        - Pawn promotion (to Dungeon Boss by default if no captured majors)
        """
        fr, fc = from_pos
        tr, tc = to_pos
        piece = self.grid[fr][fc]
        captured = self.grid[tr][tc]

        # En passant capture
        if piece.is_pawn and (tr, tc) == self.en_passant_target and captured is None:
            # The captured pawn is on the same row as the moving pawn, same col as target
            ep_row = fr  # the enemy pawn is on the row we came from
            captured = self.grid[ep_row][tc]
            self.grid[ep_row][tc] = None

        # Track captured piece
        if captured:
            self.captured[captured.color].append(captured)

        # Update en passant target
        self.en_passant_target = None
        if piece.is_pawn and abs(tr - fr) == 2:
            # Double pawn push: en passant target is the square behind
            ep_row = (fr + tr) // 2
            self.en_passant_target = (ep_row, fc)

        # Move the piece
        self.grid[tr][tc] = piece
        self.grid[fr][fc] = None
        piece.has_moved = True

        # Pawn promotion check (row 10 for white, row 0 for black)
        # Orthrus never promotes -- his 1x2 body doesn't fit the promotion model.
        promotion_rank = BOARD_SIZE - 1 if piece.color == Color.WHITE else 0
        if piece.is_pawn and tr == promotion_rank and piece.pawn_name != "Orthrus":
            self._promote_pawn(tr, tc, piece)

        return captured

    def undo_move(
        self,
        from_pos: Tuple[int, int],
        to_pos: Tuple[int, int],
        captured: Optional[Piece],
        was_en_passant: bool,
        old_en_passant_target: Optional[Tuple[int, int]],
        old_has_moved: bool,
        was_promotion: bool = False,
        original_piece: Optional[Piece] = None,
    ):
        """Undo a move (for move legality checking)."""
        fr, fc = from_pos
        tr, tc = to_pos

        if was_promotion and original_piece:
            piece = original_piece
        else:
            piece = self.grid[tr][tc]

        self.grid[fr][fc] = piece
        piece.has_moved = old_has_moved
        self.en_passant_target = old_en_passant_target

        if was_en_passant:
            self.grid[tr][tc] = None
            # Restore the en-passant captured pawn
            ep_pawn_row = fr
            self.grid[ep_pawn_row][tc] = captured
            if captured:
                self.captured[captured.color].pop()
        else:
            self.grid[tr][tc] = captured
            if captured:
                self.captured[captured.color].pop()

    def place_piece(self, row: int, col: int, piece: Piece, is_major: bool = False) -> bool:
        """Place a piece during setup phase. Returns True if valid placement.
        
        Rules:
        - Major pieces must be on back rank (row 0 for white, row 10 for black)
        - Pawns must be on second rank (row 1 for white, row 9 for black)
        - Square must be empty
        """
        if not self.in_bounds(row, col):
            return False
        
        if self.grid[row][col] is not None:
            return False
        
        if is_major:
            # Major pieces on back rank
            valid_row = 0 if piece.color == Color.WHITE else 10
            if row != valid_row:
                return False
        else:
            # Pawns on second rank
            valid_row = 1 if piece.color == Color.WHITE else 9
            if row != valid_row:
                return False

        if piece.is_pawn and piece.pawn_name == "Orthrus":
            return self.place_orthrus_body(piece, row, col)

        self.grid[row][col] = piece
        return True

    def orthrus_butt_pos(self, piece: Piece) -> Optional[Tuple[int, int]]:
        """Compute Orthrus's current butt square from his head square + facing direction."""
        if piece.orthrus_head_pos is None or piece.orthrus_direction is None:
            return None
        hr, hc = piece.orthrus_head_pos
        dr, dc = ORTHRUS_DIRECTIONS[piece.orthrus_direction]
        return (hr - dr, hc - dc)

    def place_orthrus_body(self, piece: Piece, anchor_row: int, anchor_col: int) -> bool:
        """Place Orthrus's 2-square body anchored at (anchor_row, anchor_col), which
        becomes his butt/pivot square. His head spawns one square further from his
        own back rank (default facing), and must also be empty and in bounds.
        Does not enforce back-rank/pawn-row restrictions -- callers that need those
        (e.g. place_piece) must check before calling this.
        """
        if not self.in_bounds(anchor_row, anchor_col) or self.grid[anchor_row][anchor_col] is not None:
            return False

        direction = "up" if piece.color == Color.WHITE else "down"
        dr, dc = ORTHRUS_DIRECTIONS[direction]
        head_row, head_col = anchor_row + dr, anchor_col + dc

        if not self.in_bounds(head_row, head_col) or self.grid[head_row][head_col] is not None:
            return False

        piece.orthrus_direction = direction
        piece.orthrus_head_pos = (head_row, head_col)
        self.grid[anchor_row][anchor_col] = piece
        self.grid[head_row][head_col] = piece
        return True

    def move_orthrus_body(self, piece: Piece, new_head: Tuple[int, int],
                           new_butt: Tuple[int, int], new_direction: str) -> None:
        """Execute a validated Orthrus move or rotation: relocate his head/butt
        squares and update his facing direction.
        """
        old_head = piece.orthrus_head_pos
        old_butt = self.orthrus_butt_pos(piece)

        for pos in (old_head, old_butt):
            if pos is not None and pos != new_head and pos != new_butt:
                self.grid[pos[0]][pos[1]] = None

        self.grid[new_head[0]][new_head[1]] = piece
        self.grid[new_butt[0]][new_butt[1]] = piece
        piece.orthrus_head_pos = new_head
        piece.orthrus_direction = new_direction
        piece.has_moved = True

    def _promote_pawn(self, row: int, col: int, pawn: Piece):
        """Promote a pawn. For Stage 1, always promote to Dungeon Boss."""
        # In later stages, check captured majors for promotion options
        promoted = Piece(PieceType.DUNGEON_BOSS, pawn.color)
        promoted.has_moved = True
        self.grid[row][col] = promoted

    def display(self) -> str:
        """Return a text representation of the board."""
        lines = []
        lines.append("    " + "  ".join(chr(ord('A') + c) for c in range(BOARD_SIZE)))
        lines.append("   " + "---" * BOARD_SIZE)
        for r in range(BOARD_SIZE - 1, -1, -1):
            rank_num = r + 1
            row_str = f"{rank_num:2d} |"
            for c in range(BOARD_SIZE):
                p = self.grid[r][c]
                if p:
                    row_str += f" {p.symbol} "
                else:
                    row_str += " . "
            row_str += f"| {rank_num}"
            lines.append(row_str)
        lines.append("   " + "---" * BOARD_SIZE)
        lines.append("    " + "  ".join(chr(ord('A') + c) for c in range(BOARD_SIZE)))
        return "\n".join(lines)
