"""Piece definitions for Dungeon Crawler Carl Chess."""

from enum import Enum


class Color(Enum):
    WHITE = "white"
    BLACK = "black"

    @property
    def opponent(self):
        return Color.BLACK if self == Color.WHITE else Color.WHITE

    @property
    def direction(self):
        """Pawn forward direction: +1 for white (up the board), -1 for black."""
        return 1 if self == Color.WHITE else -1


class PieceType(Enum):
    CARL = "Carl"           # King
    DONUT = "Donut"         # Queen
    MONGO = "Mongo"         # Knight (moves in L-shape)
    KATIA = "Katia"         # Bishop (moves diagonally)
    SAMANTHA = "Samantha"   # Rook
    PAWN = "Pawn"
    DUNGEON_BOSS = "DungeonBoss"


# Display symbols for pieces
PIECE_SYMBOLS = {
    (PieceType.CARL, Color.WHITE): "K",
    (PieceType.CARL, Color.BLACK): "k",
    (PieceType.DONUT, Color.WHITE): "Q",
    (PieceType.DONUT, Color.BLACK): "q",
    (PieceType.MONGO, Color.WHITE): "B",
    (PieceType.MONGO, Color.BLACK): "b",
    (PieceType.KATIA, Color.WHITE): "N",
    (PieceType.KATIA, Color.BLACK): "n",
    (PieceType.SAMANTHA, Color.WHITE): "R",
    (PieceType.SAMANTHA, Color.BLACK): "r",
    (PieceType.PAWN, Color.WHITE): "P",
    (PieceType.PAWN, Color.BLACK): "p",
    (PieceType.DUNGEON_BOSS, Color.WHITE): "D",
    (PieceType.DUNGEON_BOSS, Color.BLACK): "d",
}


class Piece:
    """Represents a single piece on the board."""

    def __init__(self, piece_type: PieceType, color: Color, pawn_name: str = None):
        self.piece_type = piece_type
        self.color = color
        self.pawn_name = pawn_name  # e.g. "Zev", "Mordecai", etc. Only for pawns.
        self.has_moved = False

        # Orthrus is a 1x2 piece: the same Piece instance occupies both his
        # head and butt squares on the board. orthrus_head_pos is the head's
        # current square; orthrus_direction is the way his head currently
        # faces. The butt square is always orthrus_head_pos minus the
        # direction vector (see ORTHRUS_DIRECTIONS below).
        self.orthrus_head_pos = None
        self.orthrus_direction = None

    @property
    def symbol(self) -> str:
        return PIECE_SYMBOLS.get((self.piece_type, self.color), "?")

    @property
    def is_pawn(self) -> bool:
        return self.piece_type == PieceType.PAWN

    @property
    def is_king(self) -> bool:
        return self.piece_type == PieceType.CARL

    def __repr__(self):
        name = self.pawn_name if self.pawn_name else self.piece_type.value
        return f"{self.color.value}_{name}"


# Orthrus movement/rotation direction vectors, keyed by facing direction.
# 'up'/'down' move along rows (board-absolute, matching the board's own
# up/down orientation), 'left'/'right' move along columns.
ORTHRUS_DIRECTIONS = {
    "up": (1, 0),
    "down": (-1, 0),
    "left": (0, -1),
    "right": (0, 1),
}
ORTHRUS_LEFT_TURN = {"up": "left", "left": "down", "down": "right", "right": "up"}
ORTHRUS_RIGHT_TURN = {"up": "right", "right": "down", "down": "left", "left": "up"}
