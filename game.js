class ChessRPG {
    constructor() {
        this.board = [];
        this.currentPlayer = 'white';
        this.selectedPiece = null;
        this.selectedSquare = null;
        this.diceValue = 0;
        this.hasRolledDice = false;
        this.gameState = 'playing';
        this.battleLog = [];
        
        this.initializeBoard();
        this.setupEventListeners();
        this.renderBoard();
        this.updateUI();
    }
    
    initializeBoard() {
        for (let row = 0; row < 8; row++) {
            this.board[row] = [];
            for (let col = 0; col < 8; col++) {
                this.board[row][col] = null;
            }
        }
        
        this.setupInitialPieces();
    }
    
    setupInitialPieces() {
        const pieceSetup = {
            0: ['♜', '♞', '♝', '♛', '♚', '♝', '♞', '♜'],
            1: ['♟', '♟', '♟', '♟', '♟', '♟', '♟', '♟'],
            6: ['♙', '♙', '♙', '♙', '♙', '♙', '♙', '♙'],
            7: ['♖', '♘', '♗', '♕', '♔', '♗', '♘', '♖']
        };
        
        for (let row in pieceSetup) {
            for (let col = 0; col < 8; col++) {
                const piece = pieceSetup[row][col];
                const color = row < 2 ? 'black' : 'white';
                this.board[row][col] = this.createPiece(piece, color, row, col);
            }
        }
    }
    
    createPiece(symbol, color, row, col) {
        const pieceTypes = {
            '♔': 'King', '♚': 'King',
            '♕': 'Queen', '♛': 'Queen',
            '♖': 'Rook', '♜': 'Rook',
            '♗': 'Bishop', '♝': 'Bishop',
            '♘': 'Knight', '♞': 'Knight',
            '♙': 'Pawn', '♟': 'Pawn'
        };
        
        return {
            symbol: symbol,
            color: color,
            type: pieceTypes[symbol],
            row: row,
            col: col,
            health: 100,
            maxHealth: 100,
            attackPower: 20,
            hasMoved: false,
            abilities: this.getAbilitiesForPiece(pieceTypes[symbol])
        };
    }
    
    getAbilitiesForPiece(pieceType) {
        const abilities = {
            'King': [
                { name: 'Royal Command', description: 'Boost adjacent allies for 1 turn', cooldown: 3, usesLeft: 1 },
                { name: 'Divine Shield', description: 'Block next attack', cooldown: 4, usesLeft: 1 }
            ],
            'Queen': [
                { name: 'Meteor Strike', description: 'Attack all enemies in 3x3 area', cooldown: 3, usesLeft: 2 },
                { name: 'Teleport', description: 'Move to any empty square', cooldown: 4, usesLeft: 1 }
            ],
            'Rook': [
                { name: 'Castle Wall', description: 'Create defensive barrier', cooldown: 3, usesLeft: 2 },
                { name: 'Battering Ram', description: 'Double damage next attack', cooldown: 2, usesLeft: 3 }
            ],
            'Bishop': [
                { name: 'Holy Light', description: 'Heal self or adjacent ally', cooldown: 2, usesLeft: 3 },
                { name: 'Blessing', description: 'Increase movement range', cooldown: 3, usesLeft: 2 }
            ],
            'Knight': [
                { name: 'Cavalry Charge', description: 'Move and attack in same turn', cooldown: 2, usesLeft: 3 },
                { name: 'Lance Strike', description: 'Attack from 2 squares away', cooldown: 3, usesLeft: 2 }
            ],
            'Pawn': [
                { name: 'Enrage', description: 'Double attack power when health < 50%', cooldown: 1, usesLeft: 999 },
                { name: 'Promote', description: 'Transform to Queen at end of board', cooldown: 0, usesLeft: 1 }
            ]
        };
        
        return abilities[pieceType] || [];
    }
    
    setupEventListeners() {
        document.getElementById('roll-dice-btn').addEventListener('click', () => this.rollDice());
        document.getElementById('chess-board').addEventListener('click', (e) => this.handleBoardClick(e));
    }
    
    renderBoard() {
        const boardElement = document.getElementById('chess-board');
        boardElement.innerHTML = '';
        
        for (let row = 0; row < 8; row++) {
            for (let col = 0; col < 8; col++) {
                const square = document.createElement('div');
                square.className = `square ${(row + col) % 2 === 0 ? 'light' : 'dark'}`;
                square.dataset.row = row;
                square.dataset.col = col;
                
                const piece = this.board[row][col];
                if (piece) {
                    const pieceElement = document.createElement('div');
                    pieceElement.className = `piece ${piece.color}`;
                    pieceElement.textContent = piece.symbol;
                    square.appendChild(pieceElement);
                }
                
                boardElement.appendChild(square);
            }
        }
    }
    
    handleBoardClick(event) {
        const square = event.target.closest('.square');
        if (!square) return;
        
        const row = parseInt(square.dataset.row);
        const col = parseInt(square.dataset.col);
        const piece = this.board[row][col];
        
        if (this.selectedPiece) {
            if (this.isValidMove(this.selectedPiece, row, col)) {
                this.movePiece(this.selectedPiece, row, col);
            } else {
                this.clearSelection();
                if (piece && piece.color === this.currentPlayer) {
                    this.selectPiece(piece, row, col);
                }
            }
        } else if (piece && piece.color === this.currentPlayer) {
            this.selectPiece(piece, row, col);
        }
    }
    
    selectPiece(piece, row, col) {
        this.selectedPiece = piece;
        this.selectedSquare = { row, col };
        
        this.highlightSquare(row, col, 'selected');
        this.showPossibleMoves(piece);
        this.updatePieceInfo(piece);
        this.showAbilities(piece);
    }
    
    clearSelection() {
        this.selectedPiece = null;
        this.selectedSquare = null;
        
        document.querySelectorAll('.square').forEach(square => {
            square.classList.remove('selected', 'possible-move', 'possible-attack');
        });
        
        document.getElementById('selected-piece-info').innerHTML = '';
        document.getElementById('abilities-container').innerHTML = '';
    }
    
    highlightSquare(row, col, className) {
        const square = document.querySelector(`[data-row="${row}"][data-col="${col}"]`);
        if (square) {
            square.classList.add(className);
        }
    }
    
    showPossibleMoves(piece) {
        const moves = this.getPossibleMoves(piece);
        moves.forEach(move => {
            const targetPiece = this.board[move.row][move.col];
            const className = targetPiece ? 'possible-attack' : 'possible-move';
            this.highlightSquare(move.row, move.col, className);
        });
    }
    
    getPossibleMoves(piece) {
        const moves = [];
        const { row, col, type } = piece;
        
        switch (type) {
            case 'Pawn':
                moves.push(...this.getPawnMoves(piece));
                break;
            case 'Rook':
                moves.push(...this.getRookMoves(piece));
                break;
            case 'Knight':
                moves.push(...this.getKnightMoves(piece));
                break;
            case 'Bishop':
                moves.push(...this.getBishopMoves(piece));
                break;
            case 'Queen':
                moves.push(...this.getQueenMoves(piece));
                break;
            case 'King':
                moves.push(...this.getKingMoves(piece));
                break;
        }
        
        return moves.filter(move => this.isInBounds(move.row, move.col));
    }
    
    getPawnMoves(piece) {
        const moves = [];
        const direction = piece.color === 'white' ? -1 : 1;
        const startRow = piece.color === 'white' ? 6 : 1;
        
        const moveOne = { row: piece.row + direction, col: piece.col };
        if (!this.board[moveOne.row][moveOne.col]) {
            moves.push(moveOne);
            
            if (!piece.hasMoved) {
                const moveTwo = { row: piece.row + (2 * direction), col: piece.col };
                if (!this.board[moveTwo.row][moveTwo.col]) {
                    moves.push(moveTwo);
                }
            }
        }
        
        for (let dcol of [-1, 1]) {
            const attack = { row: piece.row + direction, col: piece.col + dcol };
            const target = this.board[attack.row][attack.col];
            if (target && target.color !== piece.color) {
                moves.push(attack);
            }
        }
        
        return moves;
    }
    
    getRookMoves(piece) {
        const moves = [];
        const directions = [[0, 1], [0, -1], [1, 0], [-1, 0]];
        
        for (let [dr, dc] of directions) {
            for (let i = 1; i < 8; i++) {
                const newRow = piece.row + dr * i;
                const newCol = piece.col + dc * i;
                
                if (!this.isInBounds(newRow, newCol)) break;
                
                const target = this.board[newRow][newCol];
                if (!target) {
                    moves.push({ row: newRow, col: newCol });
                } else {
                    if (target.color !== piece.color) {
                        moves.push({ row: newRow, col: newCol });
                    }
                    break;
                }
            }
        }
        
        return moves;
    }
    
    getKnightMoves(piece) {
        const moves = [];
        const jumps = [
            [-2, -1], [-2, 1], [-1, -2], [-1, 2],
            [1, -2], [1, 2], [2, -1], [2, 1]
        ];
        
        for (let [dr, dc] of jumps) {
            const newRow = piece.row + dr;
            const newCol = piece.col + dc;
            
            if (this.isInBounds(newRow, newCol)) {
                const target = this.board[newRow][newCol];
                if (!target || target.color !== piece.color) {
                    moves.push({ row: newRow, col: newCol });
                }
            }
        }
        
        return moves;
    }
    
    getBishopMoves(piece) {
        const moves = [];
        const directions = [[1, 1], [1, -1], [-1, 1], [-1, -1]];
        
        for (let [dr, dc] of directions) {
            for (let i = 1; i < 8; i++) {
                const newRow = piece.row + dr * i;
                const newCol = piece.col + dc * i;
                
                if (!this.isInBounds(newRow, newCol)) break;
                
                const target = this.board[newRow][newCol];
                if (!target) {
                    moves.push({ row: newRow, col: newCol });
                } else {
                    if (target.color !== piece.color) {
                        moves.push({ row: newRow, col: newCol });
                    }
                    break;
                }
            }
        }
        
        return moves;
    }
    
    getQueenMoves(piece) {
        return [...this.getRookMoves(piece), ...this.getBishopMoves(piece)];
    }
    
    getKingMoves(piece) {
        const moves = [];
        const directions = [
            [0, 1], [0, -1], [1, 0], [-1, 0],
            [1, 1], [1, -1], [-1, 1], [-1, -1]
        ];
        
        for (let [dr, dc] of directions) {
            const newRow = piece.row + dr;
            const newCol = piece.col + dc;
            
            if (this.isInBounds(newRow, newCol)) {
                const target = this.board[newRow][newCol];
                if (!target || target.color !== piece.color) {
                    moves.push({ row: newRow, col: newCol });
                }
            }
        }
        
        return moves;
    }
    
    isInBounds(row, col) {
        return row >= 0 && row < 8 && col >= 0 && col < 8;
    }
    
    isValidMove(piece, toRow, toCol) {
        const possibleMoves = this.getPossibleMoves(piece);
        return possibleMoves.some(move => move.row === toRow && move.col === toCol);
    }
    
    movePiece(piece, toRow, toCol) {
        const targetPiece = this.board[toRow][toCol];
        
        if (targetPiece) {
            this.combat(piece, targetPiece);
        }
        
        this.board[piece.row][piece.col] = null;
        piece.row = toRow;
        piece.col = toCol;
        piece.hasMoved = true;
        this.board[toRow][toCol] = piece;
        
        this.addToLog(`${piece.color} ${piece.type} moved to ${String.fromCharCode(65 + toCol)}${8 - toRow}`, 'movement');
        
        this.clearSelection();
        this.renderBoard();
        this.checkWinCondition();
        this.endTurn();
    }
    
    combat(attacker, defender) {
        const attackRoll = this.diceValue || Math.floor(Math.random() * 6) + 1;
        const damage = attacker.attackPower + (attackRoll * 5);
        
        defender.health -= damage;
        
        this.addToLog(
            `${attacker.color} ${attacker.type} attacks ${defender.color} ${defender.type} for ${damage} damage!`,
            'combat'
        );
        
        if (defender.health <= 0) {
            this.addToLog(`${defender.color} ${defender.type} has been defeated!`, 'combat');
            this.board[defender.row][defender.col] = null;
        }
    }
    
    rollDice() {
        if (this.hasRolledDice) return;
        
        this.diceValue = Math.floor(Math.random() * 6) + 1;
        this.hasRolledDice = true;
        
        document.getElementById('dice-result').textContent = this.diceValue;
        document.getElementById('roll-dice-btn').disabled = true;
        
        this.addToLog(`${this.currentPlayer} rolled a ${this.diceValue}!`, 'ability');
    }
    
    useAbility(piece, abilityIndex) {
        const ability = piece.abilities[abilityIndex];
        if (!ability || ability.usesLeft <= 0) return;
        
        ability.usesLeft--;
        this.addToLog(`${piece.color} ${piece.type} used ${ability.name}!`, 'ability');
        
        this.showAbilities(piece);
        this.renderBoard();
    }
    
    updatePieceInfo(piece) {
        const infoDiv = document.getElementById('selected-piece-info');
        infoDiv.innerHTML = `
            <div><strong>${piece.color} ${piece.type}</strong></div>
            <div>Health: ${piece.health}/${piece.maxHealth}</div>
            <div>Attack: ${piece.attackPower}</div>
            <div>Position: ${String.fromCharCode(65 + piece.col)}${8 - piece.row}</div>
        `;
    }
    
    showAbilities(piece) {
        const abilitiesDiv = document.getElementById('abilities-container');
        abilitiesDiv.innerHTML = '';
        
        piece.abilities.forEach((ability, index) => {
            const button = document.createElement('button');
            button.className = 'ability-btn';
            button.textContent = `${ability.name} (${ability.usesLeft})`;
            button.title = ability.description;
            button.disabled = ability.usesLeft <= 0;
            
            button.addEventListener('click', () => this.useAbility(piece, index));
            abilitiesDiv.appendChild(button);
        });
    }
    
    endTurn() {
        this.currentPlayer = this.currentPlayer === 'white' ? 'black' : 'white';
        this.hasRolledDice = false;
        this.diceValue = 0;
        
        document.getElementById('roll-dice-btn').disabled = false;
        document.getElementById('dice-result').textContent = '';
        
        this.updateUI();
    }
    
    updateUI() {
        document.getElementById('current-turn').textContent = `${this.currentPlayer.charAt(0).toUpperCase() + this.currentPlayer.slice(1)}'s Turn`;
    }
    
    addToLog(message, type = 'normal') {
        const logDiv = document.getElementById('battle-log');
        const entry = document.createElement('div');
        entry.className = `log-entry ${type}`;
        entry.textContent = message;
        
        logDiv.insertBefore(entry, logDiv.firstChild);
        
        if (logDiv.children.length > 50) {
            logDiv.removeChild(logDiv.lastChild);
        }
    }
    
    checkWinCondition() {
        const whiteKing = this.findKing('white');
        const blackKing = this.findKing('black');
        
        if (!whiteKing) {
            this.gameState = 'black_wins';
            this.addToLog('Black wins! White King has been defeated!', 'combat');
        } else if (!blackKing) {
            this.gameState = 'white_wins';
            this.addToLog('White wins! Black King has been defeated!', 'combat');
        }
    }
    
    findKing(color) {
        for (let row = 0; row < 8; row++) {
            for (let col = 0; col < 8; col++) {
                const piece = this.board[row][col];
                if (piece && piece.type === 'King' && piece.color === color) {
                    return piece;
                }
            }
        }
        return null;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const game = new ChessRPG();
});
