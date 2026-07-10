"""Legal move generation and check detection for DCC Chess."""

from typing import List, Tuple, Optional

from .pieces import Piece, PieceType, Color
from .board import Board, BOARD_SIZE


Move = Tuple[Tuple[int, int], Tuple[int, int]]  # (from_pos, to_pos)


def pseudo_legal_moves_for_piece(
    board: Board, row: int, col: int
) -> List[Tuple[int, int]]:
    """Generate pseudo-legal destination squares for a piece (ignores check)."""
    piece = board.get(row, col)
    if piece is None:
        return []

    generators = {
        PieceType.CARL: _king_moves,
        PieceType.DONUT: _queen_moves,
        PieceType.MONGO: _knight_moves,  # Mongo now moves in L-shape like Knight
        PieceType.KATIA: _bishop_moves,  # Katia now moves diagonally like Bishop
        PieceType.SAMANTHA: _rook_moves,
        PieceType.PAWN: _pawn_moves,
        PieceType.DUNGEON_BOSS: _queen_moves,  # Dungeon Boss moves like Queen
    }

    gen = generators.get(piece.piece_type)
    if gen is None:
        return []
    return gen(board, row, col, piece)


def _sliding_moves(
    board: Board, row: int, col: int, piece: Piece,
    directions: List[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """Generate moves for sliding pieces (rook, bishop, queen)."""
    moves = []
    for dr, dc in directions:
        r, c = row + dr, col + dc
        while board.in_bounds(r, c):
            target = board.get(r, c)
            if target is None:
                moves.append((r, c))
            elif target.color != piece.color:
                moves.append((r, c))
                break
            else:
                break
            r += dr
            c += dc
    return moves


def _king_moves(
    board: Board, row: int, col: int, piece: Piece
) -> List[Tuple[int, int]]:
    moves = []
    for dr in [-1, 0, 1]:
        for dc in [-1, 0, 1]:
            if dr == 0 and dc == 0:
                continue
            r, c = row + dr, col + dc
            if board.in_bounds(r, c):
                target = board.get(r, c)
                if target is None or target.color != piece.color:
                    moves.append((r, c))
    return moves


def _queen_moves(
    board: Board, row: int, col: int, piece: Piece
) -> List[Tuple[int, int]]:
    directions = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    ]
    return _sliding_moves(board, row, col, piece, directions)


def _bishop_moves(
    board: Board, row: int, col: int, piece: Piece
) -> List[Tuple[int, int]]:
    directions = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    return _sliding_moves(board, row, col, piece, directions)


def _knight_moves(
    board: Board, row: int, col: int, piece: Piece
) -> List[Tuple[int, int]]:
    moves = []
    jumps = [
        (-2, -1), (-2, 1), (-1, -2), (-1, 2),
        (1, -2), (1, 2), (2, -1), (2, 1),
    ]
    for dr, dc in jumps:
        r, c = row + dr, col + dc
        if board.in_bounds(r, c):
            target = board.get(r, c)
            if target is None or target.color != piece.color:
                moves.append((r, c))
    return moves


def _rook_moves(
    board: Board, row: int, col: int, piece: Piece
) -> List[Tuple[int, int]]:
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    return _sliding_moves(board, row, col, piece, directions)


def _pawn_moves(
    board: Board, row: int, col: int, piece: Piece
) -> List[Tuple[int, int]]:
    """Standard pawn moves: forward 1, forward 2 on first move, diagonal capture, en passant."""
    moves = []
    direction = piece.color.direction  # +1 for white, -1 for black

    # Forward 1
    r1 = row + direction
    if board.in_bounds(r1, col) and board.get(r1, col) is None:
        moves.append((r1, col))

        # Forward 2 (only if first move and forward-1 is clear)
        if not piece.has_moved:
            r2 = row + 2 * direction
            if board.in_bounds(r2, col) and board.get(r2, col) is None:
                moves.append((r2, col))

    # Diagonal captures
    for dc in [-1, 1]:
        r, c = row + direction, col + dc
        if board.in_bounds(r, c):
            target = board.get(r, c)
            if target is not None and target.color != piece.color:
                moves.append((r, c))

    # En passant
    if board.en_passant_target:
        ep_r, ep_c = board.en_passant_target
        if ep_r == row + direction and abs(ep_c - col) == 1:
            moves.append((ep_r, ep_c))

    return moves


def is_square_attacked(board: Board, row: int, col: int, by_color: Color) -> bool:
    """Check if a square is attacked by any piece of the given color."""
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            p = board.get(r, c)
            if p is None or p.color != by_color:
                continue

            # For pawns, only check diagonal attack squares (not forward moves).
            # White pawns advance toward row 10 (+1) and attack the row ABOVE them.
            # Black pawns advance toward row 0 (-1) and attack the row BELOW them.
            if p.is_pawn:
                if p.color == Color.WHITE:
                    attacked_row = r + 1   # white attacks upward
                else:
                    attacked_row = r - 1   # black attacks downward
                if attacked_row == row and abs(c - col) == 1:
                    return True
                continue

            # For other pieces, check if (row, col) is in their pseudo-legal moves
            targets = pseudo_legal_moves_for_piece(board, r, c)
            if (row, col) in targets:
                return True

    return False


def is_in_check(board: Board, color: Color) -> bool:
    """Check if the given color's King (Carl) is in check."""
    king_pos = board.find_king(color)
    if king_pos is None:
        return True  # King captured = in check (shouldn't happen in legal game)
    return is_square_attacked(board, king_pos[0], king_pos[1], color.opponent)


def legal_moves_for_piece(
    board: Board, row: int, col: int
) -> List[Tuple[int, int]]:
    """Generate fully legal moves for a piece (filters out moves that leave king in check)."""
    piece = board.get(row, col)
    if piece is None:
        return []

    pseudo_moves = pseudo_legal_moves_for_piece(board, row, col)
    legal = []

    for tr, tc in pseudo_moves:
        if _is_move_legal(board, (row, col), (tr, tc), piece):
            legal.append((tr, tc))

    return legal


def _is_move_legal(
    board: Board, from_pos: Tuple[int, int], to_pos: Tuple[int, int], piece: Piece
) -> bool:
    """Test if a move is legal by making it, checking for check, and undoing it."""
    fr, fc = from_pos
    tr, tc = to_pos

    # Save state for undo
    old_en_passant = board.en_passant_target
    old_has_moved = piece.has_moved
    target_piece = board.get(tr, tc)

    # Detect en passant
    is_ep = (
        piece.is_pawn
        and (tr, tc) == board.en_passant_target
        and target_piece is None
    )

    # Detect if this will be a promotion
    promotion_rank = BOARD_SIZE - 1 if piece.color == Color.WHITE else 0
    is_promotion = piece.is_pawn and tr == promotion_rank

    # Make the move
    captured = board.make_move(from_pos, to_pos)

    # Check if our king is in check after the move
    in_check = is_in_check(board, piece.color)

    # Undo the move
    board.undo_move(
        from_pos, to_pos, captured, is_ep, old_en_passant,
        old_has_moved, is_promotion, piece if is_promotion else None
    )

    return not in_check


def all_legal_moves(board: Board, color: Color) -> List[Move]:
    """Generate all legal moves for a player."""
    moves = []
    for r, c, piece in board.all_pieces(color):
        for tr, tc in legal_moves_for_piece(board, r, c):
            moves.append(((r, c), (tr, tc)))
    return moves


def is_checkmate(board: Board, color: Color) -> bool:
    """Check if the given color is in checkmate."""
    if not is_in_check(board, color):
        return False
    return len(all_legal_moves(board, color)) == 0


def is_stalemate(board: Board, color: Color) -> bool:
    """Check if the given color is in stalemate (no legal moves, not in check)."""
    if is_in_check(board, color):
        return False
    return len(all_legal_moves(board, color)) == 0
