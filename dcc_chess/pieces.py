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
