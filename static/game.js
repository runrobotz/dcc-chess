/* ═══ DCC Chess — Frontend Game Logic ═══ */

const Game = {
    mode: null,           // "pvp" or "pvai"
    state: null,          // Current game state from server
    roster: [],           // Full pawn roster
    draftSelection: [],   // Currently selected pawns in draft
    draftPlayer: 1,       // Which player is drafting (1 or 2)
    whitePawns: [],
    blackPawns: [],
    selectedSquare: null, // {row, col} of selected piece
    legalMoves: [],       // Array of [row, col] legal destinations
    lastMoveFrom: null,
    lastMoveTo: null,
    lastEventCount: 0,    // Track events to detect new auto-ability triggers
    
    // Targeting system
    targetingMode: false,      // Whether we're in targeting mode
    targetingAbility: null,    // {pieceRow, pieceCol, abilityName, dieIndex, type}
    validTargets: [],          // Array of valid target positions [[row, col], ...]
    targetingMessage: null,    // Message to display during targeting
    zoneHoverTopLeft: null,    // [row, col] top-left of current 2×2 hover preview
    _boardZoneLeaveHandler: null, // Cached mouseleave handler for zone mode cleanup
    
    // Dev Game Mode
    DEFAULT_DEV_ROSTER: {
        whitePawns: ['Zev', 'Mordecai', 'Prepotente', 'Elle McGib', 'Sledge', 'Quasar', 'Lucia Mar', 'Louie'],
        blackPawns: ['Imani', 'Slugalo', 'Stripper Anaconda', 'Chris', 'Juice Box', 'Florin', 'Signet', 'Miriam Dom'],
    },
    devSettings: null,         // {whitePawns: [...], blackPawns: [...], boardLayout?: ...} or null to use DEFAULT_DEV_ROSTER
    devStagingGrid: null,      // 11×11 array of piece objects (or null) for the staging board
    devStagingSelected: null,  // [row, col] of currently selected staging piece, or null

    STAGING_MAJOR_ORDER: ['Samantha', 'Katia', 'Mongo', 'Donut', 'Carl', 'Samantha', 'Katia', 'Mongo'],
    STAGING_MAJOR_INFO: {
        'Samantha': { type: 'Samantha', short: 'SAM' },
        'Katia':    { type: 'Katia',    short: 'KATIA' },
        'Mongo':    { type: 'Mongo',    short: 'MONGO' },
        'Donut':    { type: 'Donut',    short: 'DONUT' },
        'Carl':     { type: 'Carl',     short: 'CARL' },
    },

    // ═══ INITIALIZATION ═══

    async init() {
        // Fetch roster on load
        try {
            const resp = await fetch('/roster');
            this.roster = await resp.json();
        } catch (e) {
            console.error('Failed to load roster:', e);
        }
        
        // Load dev settings from localStorage
        this.loadDevSettings();
        this.updateDevStatus();
    },

    // ═══ SCREEN MANAGEMENT ═══

    showScreen(id) {
        document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
        document.getElementById(id).classList.add('active');
    },

    // ═══ MODE SELECT ═══

    selectMode(mode) {
        this.mode = mode;
        this.draftPlayer = 1;
        this.draftSelection = [];
        this.whitePawns = [];
        this.blackPawns = [];
        
        if (mode === 'dev') {
            // Dev Game mode - instant start with no draft/placement
            this.startDevGame();
        } else {
            // Normal modes - show draft screen
            this.showScreen('draft-screen');
            this.renderDraft();
        }
    },

    // ═══ DRAFT ═══

    renderDraft() {
        const grid = document.getElementById('draft-grid');
        const title = document.getElementById('draft-title');
        const subtitle = document.getElementById('draft-subtitle');
        const counter = document.getElementById('draft-count');
        const confirmBtn = document.getElementById('draft-confirm');

        if (this.mode === 'pvai') {
            title.textContent = 'Draft Your Pawns (White)';
            subtitle.textContent = 'Select exactly 8 pawns — AI will draft randomly';
        } else {
            if (this.draftPlayer === 1) {
                title.textContent = 'Player 1 (White) — Draft Your Pawns';
                subtitle.textContent = 'Select exactly 8 pawns';
            } else {
                title.textContent = 'Player 2 (Black) — Draft Your Pawns';
                subtitle.textContent = 'Select 8 from the remaining pawns';
            }
        }

        counter.textContent = this.draftSelection.length;
        confirmBtn.disabled = this.draftSelection.length !== 8;

        grid.innerHTML = '';
        for (const pawn of this.roster) {
            const card = document.createElement('div');
            card.className = 'draft-card';

            const taken = this.whitePawns.includes(pawn.name);
            if (taken) {
                card.classList.add('taken');
            }
            if (this.draftSelection.includes(pawn.name)) {
                card.classList.add('selected');
            }

            const floorText = pawn.floor_number > 0 ? `${pawn.floor_number} Mana` : pawn.trigger === 'auto_capture' ? 'Auto' : pawn.trigger === 'auto_defense' ? 'Auto' : 'Passive';
            const usesText = pawn.uses_per_game ? ` (${pawn.uses_per_game}/game)` : '';

            card.innerHTML = `
                <div class="pawn-name">${pawn.name}</div>
                <div>
                    <span class="ability-name">${pawn.ability_name}</span>
                    <span class="floor-badge">${floorText}${usesText}</span>
                </div>
                <div class="ability-desc">${pawn.ability_description}</div>
            `;

            if (!taken) {
                card.addEventListener('click', () => this.toggleDraftPawn(pawn.name));
            }

            grid.appendChild(card);
        }
    },

    toggleDraftPawn(name) {
        const idx = this.draftSelection.indexOf(name);
        if (idx >= 0) {
            this.draftSelection.splice(idx, 1);
        } else {
            if (this.draftSelection.length >= 8) return;
            this.draftSelection.push(name);
        }
        this.renderDraft();
    },

    async confirmDraft() {
        if (this.draftSelection.length !== 8) return;

        if (this.draftPlayer === 1) {
            this.whitePawns = [...this.draftSelection];
            this.draftSelection = [];

            if (this.mode === 'pvai') {
                // AI drafts from remaining
                const remaining = this.roster
                    .map(p => p.name)
                    .filter(n => !this.whitePawns.includes(n));
                this.blackPawns = this.shuffleArray(remaining).slice(0, 8);
                await this.startGame();
            } else {
                // PvP: Player 2 drafts
                this.draftPlayer = 2;
                this.renderDraft();
            }
        } else {
            // Player 2 done
            this.blackPawns = [...this.draftSelection];
            this.draftSelection = [];
            await this.startGame();
        }
    },

    // ═══ START GAME ═══

    async startGame() {
        try {
            const resp = await fetch('/new_game', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    mode: this.mode,
                    white_pawns: this.whitePawns,
                    black_pawns: this.blackPawns,
                }),
            });
            this.state = await resp.json();
            if (this.state.error) {
                this.showToast(this.state.error, 'fail');
                return;
            }
            this.selectedSquare = null;
            this.legalMoves = [];
            this.lastMoveFrom = null;
            this.lastMoveTo = null;
            this.selectedPieceToPlace = null;  // For placement phase
            this.showScreen('game-screen');
            this.render();
        } catch (e) {
            console.error('Failed to start game:', e);
            this.showToast('Failed to start game', 'fail');
        }
    },

    // ═══ RENDER ═══

    render() {
        if (!this.state) return;
        this.renderBoard();
        this.renderHeader();
        this.renderCheckBanner();
        if (this.state.phase === 'placement') {
            this.renderPlacementPanel();
        } else {
            this.renderDicePanel();
        }
        if (this.state.game_over) {
            this.showGameOver();
        }
        this.checkForAutoAbilityEvents();
        this.checkGameOver();
    },

    renderCheckBanner() {
        const banner = document.getElementById('check-banner');
        if (!banner) return;
        if (this.state.carl_in_check && !this.state.game_over) {
            banner.classList.remove('hidden');
        } else {
            banner.classList.add('hidden');
        }
    },

    renderHeader() {
        const s = this.state;
        const label = document.getElementById('turn-label');
        const turnNum = document.getElementById('turn-number');
        const phase = document.getElementById('phase-label');

        const playerName = s.current_player === 'white' ? "White's Turn" : "Black's Turn";
        label.textContent = playerName;
        label.className = 'turn-label ' + (s.current_player === 'white' ? 'white-turn' : 'black-turn');
        turnNum.textContent = `Turn ${s.turn_number}`;

        const phaseNames = { 
            move: 'Ready to Start Turn', 
            ability: 'Ability & Move Phase', 
            placement: 'Placement Phase',
            game_over: 'Game Over' 
        };
        phase.textContent = phaseNames[s.phase] || s.phase;
        
        // Add Start Turn button if in move phase
        const existingBtn = document.getElementById('start-turn-btn');
        if (existingBtn) existingBtn.remove();
        
        if (s.phase === 'move' && !s.game_over) {
            const startBtn = document.createElement('button');
            startBtn.id = 'start-turn-btn';
            startBtn.className = 'btn-primary';
            startBtn.textContent = 'Start Turn (Roll Dice)';
            startBtn.style.cssText = 'margin-left: 12px; padding: 8px 16px; font-size: 0.9rem;';
            startBtn.addEventListener('click', () => this.startTurn());
            phase.parentElement.appendChild(startBtn);
        }
    },

    renderBoard() {
        const board = document.getElementById('board');
        board.innerHTML = '';
        const grid = this.state.board;
        const isZoneAbility = this.targetingMode && this.targetingAbility &&
            (this.targetingAbility.abilityName === 'Air Strike' ||
             this.targetingAbility.abilityName === 'Lava Spit');
        const zoneRegionSquares = isZoneAbility ? this.getZoneRegionSquares() : null;

        // Persistent zone overlay sets
        const airStrikeSet = new Set((this.state.air_strike_zones || []).map(z => `${z[0]},${z[1]}`));
        const lavaZoneSet = new Set((this.state.lava_zones || []).map(z => `${z[0]},${z[1]}`));

        // Status effect maps/sets
        const frozenSet = new Set((this.state.frozen_pieces || []).map(z => `${z[0]},${z[1]}`));
        const suppressedSet = new Set((this.state.suppressed_pieces || []).map(z => `${z[0]},${z[1]}`));
        const restrainedSet = new Set((this.state.restrained_pieces || []).map(z => `${z[0]},${z[1]}`));
        const sheTankSet = new Set((this.state.she_tank_targets || []).map(z => `${z[0]},${z[1]}`));
        const ironWallMap = this.state.iron_wall_pieces || {};
        const plotArmorMap = this.state.plot_armor_active || {};
        const ghostMap = this.state.ghost_tokens || {};
        const ghostSet = new Set(Object.keys(ghostMap));

        // Tooltip element: persists across renders (appended to body once)
        let ttEl = document.getElementById('piece-tooltip');
        if (!ttEl) {
            ttEl = document.createElement('div');
            ttEl.id = 'piece-tooltip';
            ttEl.className = 'piece-tooltip';
            document.body.appendChild(ttEl);
        }

        // Render top-down: row 10 at top, row 0 at bottom (11x11 board)
        for (let displayRow = 0; displayRow < 11; displayRow++) {
            const row = 10 - displayRow;
            for (let col = 0; col < 11; col++) {
                const sq = document.createElement('div');
                const isLight = (row + col) % 2 === 0;
                sq.className = `square ${isLight ? 'light' : 'dark'}`;
                sq.dataset.row = row;
                sq.dataset.col = col;

                // Highlight center square (5,5) - boss spawn point
                if (row === 5 && col === 5) {
                    sq.classList.add('center-square');
                }

                // Last move highlights
                if (this.lastMoveFrom && this.lastMoveFrom[0] === row && this.lastMoveFrom[1] === col) {
                    sq.classList.add('last-move');
                }
                if (this.lastMoveTo && this.lastMoveTo[0] === row && this.lastMoveTo[1] === col) {
                    sq.classList.add('last-move');
                }

                // Selected square
                if (this.selectedSquare && this.selectedSquare.row === row && this.selectedSquare.col === col) {
                    sq.classList.add('selected');
                }

                // Targeting mode highlights (takes priority)
                if (this.targetingMode) {
                    if (isZoneAbility) {
                        if (zoneRegionSquares.has(`${row},${col}`)) {
                            const shadows = [];

                            // Detect hover footprint membership first
                            let inFootprint = false;
                            let footprintValid = true;
                            if (this.zoneHoverTopLeft) {
                                const [hr, hc] = this.zoneHoverTopLeft;
                                const footprint = this.getZoneFootprintSquares(hr, hc);
                                inFootprint = footprint.some(([fr, fc]) => fr === row && fc === col);
                                if (inFootprint) {
                                    const isAirStrike = this.targetingAbility.abilityName === 'Air Strike';
                                    footprintValid = !isAirStrike || this.isZoneEmpty(hr, hc);
                                }
                            }

                            if (inFootprint) {
                                // Hover preview: bright border + fill, all via inset box-shadows
                                // so the light/dark square background remains visible underneath
                                const borderC = footprintValid ? 'rgba(255,165,0,0.95)' : 'rgba(220,50,50,0.95)';
                                const fillC   = footprintValid ? 'rgba(255,140,0,0.45)' : 'rgba(200,40,40,0.45)';
                                shadows.push(`inset 0 0 0 2px ${borderC}`);
                                shadows.push(`inset 0 0 0 999px ${fillC}`);
                            } else {
                                // Region boundary borders at edges of the valid area
                                if (!zoneRegionSquares.has(`${row - 1},${col}`)) shadows.push('inset 0 2px 0 0 rgba(255,165,0,0.60)');
                                if (!zoneRegionSquares.has(`${row + 1},${col}`)) shadows.push('inset 0 -2px 0 0 rgba(255,165,0,0.60)');
                                if (!zoneRegionSquares.has(`${row},${col - 1}`)) shadows.push('inset 2px 0 0 0 rgba(255,165,0,0.60)');
                                if (!zoneRegionSquares.has(`${row},${col + 1}`)) shadows.push('inset -2px 0 0 0 rgba(255,165,0,0.60)');
                                // Light tint via large inset shadow — overlays the existing square color
                                // without replacing it, keeping the checkered pattern visible
                                shadows.push('inset 0 0 0 999px rgba(255,165,0,0.09)');
                            }

                            sq.style.boxShadow = shadows.join(', ');
                            sq.style.cursor = 'crosshair';
                            // sq.style.background is intentionally NOT set here so the
                            // .square.light / .square.dark background color shows through
                        }
                        sq.addEventListener('mouseover', () => this.handleZoneHover(row, col));
                    } else {
                        const isValidTarget = this.validTargets.some(t => t[0] === row && t[1] === col);
                        if (isValidTarget) {
                            sq.classList.add('valid-target');
                        }
                    }
                } else {
                    // Legal move dots / capture highlights
                    const isLegal = this.legalMoves.some(m => m[0] === row && m[1] === col);
                    if (isLegal) {
                        const target = grid[row][col];
                        if (target && target.color !== this.state.current_player) {
                            sq.classList.add('legal-capture');
                        } else {
                            sq.classList.add('legal-move');
                        }
                    }
                }

                // Piece + status effects
                const piece = grid[row][col];
                const sqKey = `${row},${col}`;
                const tooltipLines = [];

                if (piece) {
                    const pieceEl = document.createElement('div');
                    pieceEl.className = `piece ${piece.color}`;

                    const effectSymbols = [];
                    let primaryEffect = null;
                    if (frozenSet.has(sqKey)) {
                        effectSymbols.push('❄');
                        tooltipLines.push('Frozen — 1 turn remaining');
                        primaryEffect = primaryEffect || 'piece-frozen';
                    }
                    if (suppressedSet.has(sqKey)) {
                        effectSymbols.push('🔇');
                        tooltipLines.push('Suppressed — 1 turn remaining');
                        primaryEffect = primaryEffect || 'piece-suppressed';
                    }
                    if (restrainedSet.has(sqKey)) {
                        effectSymbols.push('⛓');
                        tooltipLines.push('Restrained — 1 turn remaining');
                        primaryEffect = primaryEffect || 'piece-restrained';
                    }
                    if (sheTankSet.has(sqKey)) {
                        effectSymbols.push('🚫');
                        tooltipLines.push('She Tank — 1 turn remaining');
                        primaryEffect = primaryEffect || 'piece-she-tank';
                    }
                    if (primaryEffect) pieceEl.classList.add(primaryEffect);

                    if (effectSymbols.length > 0) {
                        pieceEl.style.position = 'relative';
                        const labelSpan = document.createElement('span');
                        labelSpan.textContent = piece.short;
                        pieceEl.appendChild(labelSpan);
                        const badge = document.createElement('span');
                        badge.className = 'effect-badge';
                        badge.textContent = effectSymbols.join('');
                        pieceEl.appendChild(badge);
                    } else {
                        pieceEl.textContent = piece.short;
                    }

                    sq.appendChild(pieceEl);
                }

                // Zone overlays (rendered above pieces via z-index)
                if (airStrikeSet.has(sqKey)) {
                    const overlay = document.createElement('div');
                    overlay.className = 'zone-overlay air-strike-overlay';
                    overlay.textContent = '✕';
                    sq.appendChild(overlay);
                }
                if (lavaZoneSet.has(sqKey)) {
                    const overlay = document.createElement('div');
                    overlay.className = 'zone-overlay lava-zone-overlay';
                    overlay.textContent = '🔥';
                    sq.appendChild(overlay);
                }
                if (ghostSet.has(sqKey)) {
                    const gTurns = ghostMap[sqKey];
                    const overlay = document.createElement('div');
                    overlay.className = 'zone-overlay ghost-overlay';
                    overlay.textContent = '👻';
                    sq.appendChild(overlay);
                    tooltipLines.push(`Ghost Zone — ${gTurns} turn${gTurns !== 1 ? 's' : ''} remaining`);
                }

                // Square-level persistent effects: Iron Wall (gold border) and Plot Armor (white glow)
                if (piece) {
                    const iwTurns = ironWallMap[sqKey];
                    if (iwTurns > 0) {
                        const ironShadow = 'inset 0 0 0 3px rgba(201,168,76,0.95)';
                        sq.style.boxShadow = sq.style.boxShadow ? `${sq.style.boxShadow}, ${ironShadow}` : ironShadow;
                        tooltipLines.push(`Iron Wall — ${iwTurns} turn${iwTurns !== 1 ? 's' : ''} remaining`);
                    }
                    const paTurns = plotArmorMap[piece.color];
                    if (piece.type === 'Carl' && paTurns > 0) {
                        const armorShadow = '0 0 12px 5px rgba(255,255,255,0.55), inset 0 0 0 2px rgba(255,255,255,0.5)';
                        sq.style.boxShadow = sq.style.boxShadow ? `${sq.style.boxShadow}, ${armorShadow}` : armorShadow;
                        tooltipLines.push(`Plot Armor — ${paTurns} turn${paTurns !== 1 ? 's' : ''} remaining`);
                    }
                }

                // Tooltip: single mousemove handler on the square covers all effects above
                if (tooltipLines.length > 0) {
                    const ttText = tooltipLines.join('\n');
                    sq.addEventListener('mousemove', (e) => {
                        ttEl.textContent = ttText;
                        ttEl.style.left = (e.clientX + 14) + 'px';
                        ttEl.style.top = (e.clientY - 44) + 'px';
                        ttEl.classList.add('visible');
                    });
                    sq.addEventListener('mouseleave', () => ttEl.classList.remove('visible'));
                }

                sq.addEventListener('click', () => this.handleSquareClick(row, col));
                board.appendChild(sq);
            }
        }

        // Zone mode: manage board-level mouseleave listener to clear hover preview
        if (isZoneAbility) {
            if (!this._boardZoneLeaveHandler) {
                this._boardZoneLeaveHandler = () => {
                    if (this.zoneHoverTopLeft !== null) {
                        this.zoneHoverTopLeft = null;
                        this.renderBoard();
                    }
                };
                board.addEventListener('mouseleave', this._boardZoneLeaveHandler);
            }
        } else if (this._boardZoneLeaveHandler) {
            board.removeEventListener('mouseleave', this._boardZoneLeaveHandler);
            this._boardZoneLeaveHandler = null;
        }
    },

    checkForAutoAbilityEvents() {
        if (!this.state || !this.state.events) return;
        
        const events = this.state.events;
        const newEvents = events.slice(this.lastEventCount);
        this.lastEventCount = events.length;
        
        // Check for auto-ability events
        for (const event of newEvents) {
            if (event.type === 'ability_auto') {
                this.showAutoAbilityNotification(event);
            } else if (event.type === 'mediation_reversal') {
                this.showMediationReversalNotification(event);
            } else if (event.type === 'move_blocked') {
                if (event.reason === 'Elle McGib Frozen Immunity') {
                    this.showAutoAbilityNotification({
                        piece: 'Elle McGib',
                        ability: 'Frozen Immunity',
                        result: 'success',
                        detail: 'Capture negated'
                    });
                }
            }
        }
    },

    showAutoAbilityNotification(event) {
        const { piece, ability, attacker_roll, defender_roll, result, detail } = event;
        
        let message = `⚡ ${piece}'s ${ability} activated!\n`;
        
        if (attacker_roll !== undefined && defender_roll !== undefined) {
            message += `Attacker rolled: ${attacker_roll}\n`;
            message += `Defender rolled: ${defender_roll}\n`;
            if (defender_roll > attacker_roll) {
                message += `Defender wins! Capture reversed!`;
            } else {
                message += `Attacker wins. Capture proceeds.`;
            }
        } else if (detail) {
            message += detail;
        } else if (result) {
            message += `Result: ${result}`;
        }
        
        this.showAbilityPopup(message);
    },

    showMediationReversalNotification(event) {
        const message = `🔄 Quasar's Mediation!\n${event.detail || 'Capture reversed!'}`;
        this.showAbilityPopup(message);
    },

    showAbilityPopup(message) {
        // Remove any existing popup
        const existing = document.getElementById('ability-popup');
        if (existing) existing.remove();

        const popup = document.createElement('div');
        popup.id = 'ability-popup';
        popup.style.cssText = `
            position: fixed;
            top: 20%;
            left: 50%;
            transform: translate(-50%, 0);
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #ffd700;
            padding: 24px 32px;
            border-radius: 12px;
            border: 3px solid #ffd700;
            font-size: 1.1rem;
            font-weight: bold;
            text-align: center;
            z-index: 10000;
            box-shadow: 0 8px 32px rgba(255, 215, 0, 0.4);
            white-space: pre-line;
            min-width: 300px;
            animation: slideDown 0.3s ease-out;
        `;
        popup.textContent = message;

        // Auto-dismiss after 3 seconds
        setTimeout(() => {
            if (popup.parentNode) {
                popup.style.animation = 'slideUp 0.3s ease-out';
                setTimeout(() => popup.remove(), 300);
            }
        }, 3000);

        document.body.appendChild(popup);
        
        // Add CSS animation if not already present
        if (!document.getElementById('ability-popup-styles')) {
            const style = document.createElement('style');
            style.id = 'ability-popup-styles';
            style.textContent = `
                @keyframes slideDown {
                    from { transform: translate(-50%, -100px); opacity: 0; }
                    to { transform: translate(-50%, 0); opacity: 1; }
                }
                @keyframes slideUp {
                    from { transform: translate(-50%, 0); opacity: 1; }
                    to { transform: translate(-50%, -100px); opacity: 0; }
                }
            `;
            document.head.appendChild(style);
        }
    },

    renderPlacementPanel() {
        const panel = document.getElementById('dice-panel');
        panel.classList.remove('hidden');
        
        const diceDisplay = document.getElementById('dice-display');
        const abilityBtns = document.getElementById('ability-buttons');
        const endTurnBtn = document.getElementById('end-turn-btn');
        
        endTurnBtn.classList.add('hidden');
        
        const placementPlayer = this.state.placement_player;
        const piecesKey = `${placementPlayer}_pieces_to_place`;
        const piecesToPlace = this.state[piecesKey];
        
        if (!piecesToPlace || piecesToPlace.length === 0) {
            panel.classList.add('hidden');
            return;
        }
        
        const playerColor = placementPlayer === 'white' ? 'White' : 'Black';
        diceDisplay.innerHTML = `<h3 style="color: var(--accent-gold); margin-bottom: 10px;">${playerColor} - Place Your Pieces</h3>`;
        
        abilityBtns.innerHTML = '';
        
        // Determine major piece names for validation
        const majorPieceNames = ['Carl', 'Donut', 'Mongo', 'Katia', 'Samantha'];
        
        // Show all pieces in order with first one highlighted
        piecesToPlace.forEach((pieceName, idx) => {
            const isMajor = majorPieceNames.includes(pieceName);
            const validRow = isMajor 
                ? (placementPlayer === 'white' ? '0' : '10')
                : (placementPlayer === 'white' ? '1' : '9');
            
            const pieceDiv = document.createElement('div');
            pieceDiv.className = idx === 0 ? 'ability-btn can-activate' : 'ability-btn cannot-activate';
            pieceDiv.style.cssText = idx === 0 
                ? 'border: 2px solid var(--accent-gold); background: rgba(201, 168, 76, 0.15);'
                : 'opacity: 0.6;';
            
            pieceDiv.innerHTML = `
                <span style="font-weight: 700;">${idx === 0 ? '→ ' : ''}${pieceName}</span>
                <span style="font-size: 0.7rem; color: var(--text-secondary);">Row ${validRow}</span>
            `;
            
            abilityBtns.appendChild(pieceDiv);
        });
        
        // Show instruction
        if (piecesToPlace.length > 0) {
            const instruction = document.createElement('div');
            instruction.style.cssText = 'color: var(--accent-gold); font-size: 0.8rem; text-align: center; padding: 8px; margin-top: 8px;';
            const firstPiece = piecesToPlace[0];
            const isMajor = majorPieceNames.includes(firstPiece);
            const validRow = isMajor 
                ? (placementPlayer === 'white' ? '0' : '10')
                : (placementPlayer === 'white' ? '1' : '9');
            instruction.textContent = `Click any square on row ${validRow} to place ${firstPiece}`;
            abilityBtns.appendChild(instruction);
        }
    },

    renderDicePanel() {
        const panel = document.getElementById('dice-panel');
        const diceDisplay = document.getElementById('dice-display');
        const abilityBtns = document.getElementById('ability-buttons');
        const endTurnBtn = document.getElementById('end-turn-btn');

        // Show panel for ability phase only
        if (this.state.phase !== 'ability') {
            panel.classList.add('hidden');
            return;
        }
        panel.classList.remove('hidden');

        // Render dice (2 dice system)
        const dice = this.state.dice;
        diceDisplay.innerHTML = '';
        
        // Show current player's banked die if exists
        const currentPlayer = this.state.current_player;
        if (dice && dice.banked_die && dice.banked_die[currentPlayer] !== null) {
            const bankDisplay = document.createElement('div');
            bankDisplay.style.cssText = 'margin-bottom: 8px; text-align: center;';
            bankDisplay.innerHTML = `
                <div style="color: var(--accent-gold); font-size: 0.85rem; margin-bottom: 4px;">🔒 Banked Die</div>
                <div class="die die-banked" style="display: inline-flex; margin: 0 auto;">${dice.banked_die[currentPlayer]}</div>
            `;
            diceDisplay.appendChild(bankDisplay);
        }

        // Show current dice
        if (dice && dice.values && dice.values.length > 0) {
            const currentDice = document.createElement('div');
            currentDice.style.cssText = 'display: flex; gap: 12px; justify-content: center; margin-bottom: 12px;';
            const numDice = dice.values.length;
            for (let i = 0; i < 2; i++) {
                if (i >= numDice) continue;

                const isUsed = !!dice.used[i];
                // A die is "reserved" when targeting mode is active and this die is the pending one
                const isReserved = this.targetingMode &&
                                   this.targetingAbility &&
                                   this.targetingAbility.dieIndex === i;

                const dieEl = document.createElement('div');
                dieEl.style.position = 'relative';

                if (isUsed) {
                    dieEl.className = 'die used';
                    dieEl.textContent = dice.values[i];
                    const xMark = document.createElement('span');
                    xMark.className = 'die-x';
                    xMark.textContent = '✕';
                    dieEl.appendChild(xMark);
                } else if (isReserved) {
                    dieEl.className = 'die die-reserved';
                    dieEl.textContent = dice.values[i];
                    dieEl.title = 'Reserved — confirm target to spend';
                } else {
                    dieEl.className = 'die available';
                    dieEl.textContent = dice.values[i];
                }

                // Bank button only for unused, non-reserved dice
                const hasBank = dice.banked_die && dice.banked_die[currentPlayer] !== null;
                if (!isUsed && !isReserved && !hasBank && this.state.phase === 'ability') {
                    const bankBtn = document.createElement('button');
                    bankBtn.textContent = 'Bank';
                    bankBtn.className = 'btn-secondary';
                    bankBtn.style.cssText = 'font-size: 0.7rem; padding: 2px 6px; margin-top: 4px;';
                    bankBtn.addEventListener('click', () => this.bankDie(i));

                    const wrapper = document.createElement('div');
                    wrapper.style.cssText = 'display: flex; flex-direction: column; align-items: center;';
                    wrapper.appendChild(dieEl);
                    wrapper.appendChild(bankBtn);
                    currentDice.appendChild(wrapper);
                } else {
                    currentDice.appendChild(dieEl);
                }
            }
            diceDisplay.appendChild(currentDice);
        }

        // Available dice values — exclude spent and reserved dice
        const availableDice = [];
        if (dice && dice.values) {
            const numDice = dice.values.length;
            for (let i = 0; i < 2; i++) {
                if (i >= numDice) continue;
                const isReserved = this.targetingMode &&
                                   this.targetingAbility &&
                                   this.targetingAbility.dieIndex === i;
                if (!dice.used[i] && !isReserved) {
                    availableDice.push({ index: i, value: dice.values[i] });
                }
            }
        }

        // Render ability buttons from current player's pieces
        abilityBtns.innerHTML = '';
        
        if (this.state.phase === 'ability') {
            if (availableDice.length === 0) {
                const msg = document.createElement('div');
                msg.style.cssText = 'color: var(--text-secondary); font-size: 0.8rem; text-align: center; padding: 8px;';
                msg.textContent = 'Make your move, then End Turn';
                abilityBtns.appendChild(msg);
                return;
            }

            const pieces = this.state.player_pieces || [];
            for (const pc of pieces) {
                if (pc.suppressed) continue;
                for (const ab of pc.abilities) {
                    // Skip auto/passive abilities
                    if (ab.trigger !== 'floor_roll') continue;
                    // Skip used-up abilities
                    if (ab.uses_per_game && ab.uses_left !== null && ab.uses_left <= 0) continue;

                    // Boss-only abilities are blocked outside boss events
                    if (ab.is_boss_only && !this.state.boss_active) {
                        const btn = document.createElement('button');
                        btn.className = 'ability-btn boss-event-only';
                        btn.disabled = true;
                        btn.innerHTML = `
                            <span>
                                <span class="ab-piece">${pc.short || pc.name}</span>
                                <span class="ab-name">${ab.name}</span>
                            </span>
                            <span class="ab-floor" style="font-style: italic; color: #9a60c0;">🔒 Boss Event Only</span>
                        `;
                        abilityBtns.appendChild(btn);
                        continue;
                    }

                    let bestDie = null;
                    let canActivate = false;
                    let useCombined = false;

                    if (ab.requires_combined) {
                        // Always needs both dice combined
                        const diceSum = availableDice.reduce((s, d) => s + d.value, 0);
                        canActivate = availableDice.length >= 2 && diceSum >= ab.floor;
                        if (canActivate) bestDie = availableDice[0];
                        useCombined = true;
                    } else {
                        // Prefer a single qualifying die; fall back to combined sum
                        const single = this.findBestDie(availableDice, ab.floor);
                        if (single !== null && single.value >= ab.floor) {
                            bestDie = single;
                            canActivate = true;
                        } else if (availableDice.length >= 2) {
                            const diceSum = availableDice.reduce((s, d) => s + d.value, 0);
                            if (diceSum >= ab.floor) {
                                canActivate = true;
                                useCombined = true;
                                bestDie = availableDice[0];
                            }
                        }
                    }

                    const btn = document.createElement('button');
                    btn.className = `ability-btn ${canActivate ? 'can-activate' : 'cannot-activate'}`;

                    btn.innerHTML = `
                        <span>
                            <span class="ab-piece">${pc.short || pc.name}</span>
                            <span class="ab-name">${ab.name}</span>
                        </span>
                        <span class="ab-floor">${(ab.requires_combined || useCombined) ? '⚄+⚄' : ''} ${ab.floor} Mana</span>
                    `;

                    if (canActivate) {
                        btn.addEventListener('click', () => this.useAbility(pc.row, pc.col, ab.name, bestDie.index, useCombined));
                    }

                    abilityBtns.appendChild(btn);
                }
            }

            if (abilityBtns.children.length === 0) {
                const msg = document.createElement('div');
                msg.style.cssText = 'color: var(--text-secondary); font-size: 0.8rem; text-align: center; padding: 8px;';
                msg.textContent = 'No abilities available — make your move';
                abilityBtns.appendChild(msg);
            }
        }
    },

    findBestDie(availableDice, floor) {
        // Find lowest die that meets floor, or lowest overall if none meet
        const sorted = [...availableDice].sort((a, b) => a.value - b.value);
        for (const d of sorted) {
            if (d.value >= floor) return d;
        }
        return sorted.length > 0 ? sorted[0] : null;
    },

    renderSidebar() {
        const label = document.getElementById('sidebar-player-label');
        const list = document.getElementById('piece-list');

        const current = this.state.current_player;
        label.textContent = `${current === 'white' ? "White" : "Black"}'s Pieces`;

        const pieces = this.state.player_pieces || [];
        list.innerHTML = '';

        // Sort: major pieces first, then pawns
        const sorted = [...pieces].sort((a, b) => {
            if (a.is_pawn && !b.is_pawn) return 1;
            if (!a.is_pawn && b.is_pawn) return -1;
            return 0;
        });

        for (const pc of sorted) {
            const card = document.createElement('div');
            card.className = `piece-card ${pc.suppressed ? 'suppressed' : ''}`;

            let abHtml = '';
            for (const ab of pc.abilities) {
                let usedTag = '';
                if (ab.uses_per_game && ab.uses_left !== null && ab.uses_left <= 0) {
                    usedTag = '<span class="used-label">USED</span>';
                }
                const floorText = ab.floor > 0 ? `${ab.floor} Mana` : (ab.trigger === 'floor_roll' ? '0 Mana' : 'Auto');
                abHtml += `
                    <div class="pc-ability">
                        <span class="ab-label">${ab.name}</span>
                        <span class="floor-num">${floorText}</span>
                        ${usedTag}
                        <br><span>${ab.description}</span>
                    </div>
                `;
            }

            card.innerHTML = `
                <div class="pc-header">
                    <span class="pc-name">${pc.name}</span>
                    <span class="pc-type">${pc.type}${pc.suppressed ? ' (Suppressed)' : ''}</span>
                </div>
                ${abHtml}
            `;

            card.addEventListener('click', () => {
                // Clicking a sidebar piece selects it on the board
                this.handleSquareClick(pc.row, pc.col);
            });

            list.appendChild(card);
        }
    },

    renderBattleLog() {
        const log = document.getElementById('battle-log');
        const events = this.state.events || [];

        log.innerHTML = '';
        // Show last 30 events in reverse
        const recent = events.slice(-30).reverse();
        for (const ev of recent) {
            const entry = document.createElement('div');
            entry.className = 'log-entry';

            let text = '';
            if (ev.type === 'move' || ev.type === 'ai_move') {
                const from = ev.from_pos ? `(${ev.from_pos[0]},${ev.from_pos[1]})` : '?';
                const to = ev.to_pos ? `(${ev.to_pos[0]},${ev.to_pos[1]})` : '?';
                text = `${ev.piece || '?'} ${from}→${to}`;
                if (ev.captured) text += ` captures ${ev.captured}`;
            } else if (ev.type === 'ability_roll') {
                entry.className += ev.result === 'success' ? ' success' : ' fail';
                text = `${ev.piece} ${ev.ability}: ${ev.result} (rolled ${ev.die_value}, floor ${ev.floor})`;
            } else if (ev.type === 'dice_roll') {
                text = `Dice: [${ev.values}]`;
            } else if (ev.type === 'ability_auto') {
                text = `${ev.piece} ${ev.ability}: ${ev.result || ''}`;
            } else if (ev.type === 'game_over') {
                text = `Game Over: ${ev.result}${ev.winner ? ' — ' + ev.winner + ' wins' : ''}`;
            } else {
                text = `${ev.type}: ${JSON.stringify(ev).substring(0, 80)}`;
            }

            entry.innerHTML = `<span class="log-turn">T${ev.turn}</span>${text}`;
            log.appendChild(entry);
        }
    },

    checkGameOver() {
        if (!this.state.game_over) {
            document.getElementById('game-over-overlay').classList.add('hidden');
            return;
        }
        const overlay = document.getElementById('game-over-overlay');
        const title = document.getElementById('game-over-title');
        const msg = document.getElementById('game-over-message');

        overlay.classList.remove('hidden');
        if (this.state.winner) {
            title.textContent = `${this.state.winner === 'white' ? 'White' : 'Black'} Wins!`;
            msg.textContent = `Victory by ${this.state.result_reason}`;
        } else {
            title.textContent = 'Draw';
            msg.textContent = this.state.result_reason === 'stalemate' ? 'Stalemate — no legal moves' : `Draw: ${this.state.result_reason}`;
        }
    },

    // ═══ BOARD INTERACTION ═══

    async handleSquareClick(row, col) {
        if (!this.state || this.state.game_over) return;
        
        // Handle targeting mode - player is selecting a target
        if (this.targetingMode) {
            const abilityName = this.targetingAbility ? this.targetingAbility.abilityName : null;
            if (abilityName === 'Air Strike' || abilityName === 'Lava Spit') {
                await this.handleZoneClick(row, col);
            } else {
                await this.handleTargetSelection(row, col);
            }
            return;
        }
        
        // Handle placement phase - auto-place first piece in list
        if (this.state.phase === 'placement') {
            await this.placePiece(row, col);
            return;
        }
        
        // Can only move during ability phase (after dice rolled)
        if (this.state.phase !== 'ability') return;

        const piece = this.state.board[row][col];

        // If clicking own piece, select it (even if another piece is already selected)
        if (piece && piece.color === this.state.current_player) {
            this.selectedSquare = { row, col };
            await this.fetchLegalMoves(row, col);
            this.renderBoard();
            return;
        }

        // If clicking a legal move destination, execute the move
        if (this.selectedSquare && this.legalMoves.some(m => m[0] === row && m[1] === col)) {
            await this.executeMove(this.selectedSquare.row, this.selectedSquare.col, row, col);
            return;
        }

        // Check if player is trying to make an illegal capture with Garret or Orthrus
        if (this.selectedSquare) {
            const selectedPiece = this.state.board[this.selectedSquare.row][this.selectedSquare.col];
            const targetPiece = this.state.board[row][col];
            
            // Only show notification for capture rule violations (Garret/Orthrus trying to capture)
            if (selectedPiece && selectedPiece.is_pawn && targetPiece && targetPiece.color !== selectedPiece.color) {
                if (selectedPiece.name === 'Garret') {
                    this.showMoveBlockedNotification('Garret cannot capture enemy pieces');
                    return;
                } else if (selectedPiece.name === 'Orthrus') {
                    this.showMoveBlockedNotification('Orthrus cannot capture pieces');
                    return;
                }
            }
            
            // For all other illegal moves (out of range, etc.), just do nothing - no notification
            return;
        }

        // Deselect
        this.selectedSquare = null;
        this.legalMoves = [];
        this.renderBoard();
    },

    async placePiece(row, col) {
        try {
            const resp = await fetch('/place_piece', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    row: row,
                    col: col,
                }),
            });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.render();
        } catch (e) {
            this.showToast('Placement failed', 'fail');
        }
    },

    async fetchLegalMoves(row, col) {
        try {
            const resp = await fetch(`/legal_moves?row=${row}&col=${col}`);
            const data = await resp.json();
            this.legalMoves = data.moves || [];
        } catch (e) {
            this.legalMoves = [];
        }
    },

    async executeMove(fromRow, fromCol, toRow, toCol) {
        try {
            const resp = await fetch('/move', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    from_row: fromRow,
                    from_col: fromCol,
                    to_row: toRow,
                    to_col: toCol,
                }),
            });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.selectedSquare = null;
            this.legalMoves = [];
            this.lastMoveFrom = [fromRow, fromCol];
            this.lastMoveTo = [toRow, toCol];
            this.render();
        } catch (e) {
            this.showToast('Move failed', 'fail');
        }
    },

    async executeAITurn() {
        try {
            this.showToast('AI is thinking...', '');
            const resp = await fetch('/ai_turn', { method: 'POST' });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.render();
        } catch (e) {
            this.showToast('AI turn failed', 'fail');
        }
    },

    // ═══ ABILITIES ═══

    async bankDie(dieIndex) {
        try {
            const resp = await fetch('/bank_die', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ die_index: dieIndex }),
            });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.showToast('Die banked for later use', 'success');
            this.render();
        } catch (e) {
            this.showToast('Banking failed', 'fail');
        }
    },

    async useAbility(pieceRow, pieceCol, abilityName, dieIndex, useCombined = false) {
        // Check if this ability requires targeting
        const targetingAbilities = {
            // Zone abilities
            'Air Strike': 'zone',
            'Lava Spit': 'zone',
            // Movement abilities
            'Leader': 'movement',
            'Puddle Jump': 'movement',
            'Blitzed': 'target_piece',
            'She Tank': 'target_piece',
            'Pet Carrier': 'movement',
            // Capture/resurrection abilities
            'Cockroach': 'resurrection',
            'Rampage': 'movement',
            'Slut Shame': 'target_piece',
            'One Of Us': 'target_piece',
            'Blood Magic': 'sacrifice',
            // Freeze abilities
            'Frozen': 'target_piece',
        };
        
        const targetingType = targetingAbilities[abilityName];
        
        if (targetingType) {
            // Enter targeting mode - fetch valid targets from backend
            await this.enterTargetingMode(pieceRow, pieceCol, abilityName, dieIndex, targetingType, useCombined);
        } else {
            // Execute ability directly (no targeting needed)
            await this.executeAbility(pieceRow, pieceCol, abilityName, dieIndex, null, useCombined);
        }
    },

    async enterTargetingMode(pieceRow, pieceCol, abilityName, dieIndex, targetingType, useCombined = false) {
        try {
            // Fetch valid targets from backend
            const resp = await fetch('/ability/get_targets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    piece_row: pieceRow,
                    piece_col: pieceCol,
                    ability_name: abilityName,
                    die_index: dieIndex,
                    use_combined: useCombined,
                }),
            });
            const data = await resp.json();
            
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            
            if (!data.valid_targets || data.valid_targets.length === 0) {
                this.showToast('No valid targets available', 'fail');
                return;
            }
            
            // Enter targeting mode
            this.targetingMode = true;
            this.targetingAbility = {
                pieceRow,
                pieceCol,
                abilityName,
                dieIndex,
                targetingType,
                useCombined,
            };
            this.validTargets = data.valid_targets;
            this.targetingMessage = data.message || `Select a target for ${abilityName}`;
            
            // Show targeting UI
            this.showTargetingUI();
            this.renderBoard();
            
        } catch (e) {
            console.error('Failed to enter targeting mode:', e);
            this.showToast('Failed to get valid targets', 'fail');
        }
    },

    showTargetingUI() {
        const existing = document.getElementById('targeting-ui');
        if (existing) existing.remove();

        const ui = document.createElement('div');
        ui.id = 'targeting-ui';
        ui.className = 'targeting-ui-docked';

        const title = document.createElement('div');
        title.className = 'targeting-ui-title';
        title.textContent = this.targetingAbility.abilityName;

        const message = document.createElement('div');
        message.className = 'targeting-ui-msg';
        message.textContent = this.targetingMessage;

        const cancelBtn = document.createElement('button');
        cancelBtn.textContent = 'Cancel';
        cancelBtn.className = 'btn btn-secondary';
        cancelBtn.style.cssText = 'padding: 5px 12px; font-size: 0.78rem; width: 100%;';
        cancelBtn.addEventListener('click', () => this.cancelTargeting());

        ui.appendChild(title);
        ui.appendChild(message);
        ui.appendChild(cancelBtn);

        // Dock inside the dice panel (below the board) so it never overlaps board squares
        const dicePanel = document.getElementById('dice-panel');
        if (dicePanel) {
            dicePanel.classList.remove('hidden');
            dicePanel.prepend(ui);
        } else {
            document.body.appendChild(ui);
        }
    },

    async handleTargetSelection(row, col) {
        // Check if clicked square is a valid target
        const isValid = this.validTargets.some(t => t[0] === row && t[1] === col);
        
        if (!isValid) {
            this.showToast('Invalid target - click a highlighted square', 'fail');
            return;
        }
        
        // Execute ability with selected target
        await this.executeAbility(
            this.targetingAbility.pieceRow,
            this.targetingAbility.pieceCol,
            this.targetingAbility.abilityName,
            this.targetingAbility.dieIndex,
            { row, col },
            this.targetingAbility.useCombined,
        );
        
        // Exit targeting mode
        this.exitTargetingMode();
    },

    cancelTargeting() {
        this.exitTargetingMode();
        this.showToast('Ability cancelled - die returned', '');
    },

    exitTargetingMode() {
        this.targetingMode = false;
        this.targetingAbility = null;
        this.validTargets = [];
        this.targetingMessage = null;
        this.zoneHoverTopLeft = null;

        // Remove board zone-leave listener
        if (this._boardZoneLeaveHandler) {
            const board = document.getElementById('board');
            if (board) board.removeEventListener('mouseleave', this._boardZoneLeaveHandler);
            this._boardZoneLeaveHandler = null;
        }

        // Remove targeting UI
        const ui = document.getElementById('targeting-ui');
        if (ui) ui.remove();

        this.render();
    },

    async executeAbility(pieceRow, pieceCol, abilityName, dieIndex, target, useCombined = false) {
        try {
            const payload = {
                piece_row: pieceRow,
                piece_col: pieceCol,
                ability_name: abilityName,
                die_index: dieIndex,
                use_combined: useCombined,
            };
            
            if (target) {
                payload.target_row = target.row;
                payload.target_col = target.col;
            }
            
            const resp = await fetch('/ability', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            const result = data.ability_result;
            if (result) {
                this.showToast(
                    `${abilityName}: ${result.message}`,
                    result.success ? 'success' : 'fail'
                );
            }
            this.render();
        } catch (e) {
            this.showToast('Ability failed', 'fail');
        }
    },

    // ═══ TURN MANAGEMENT ═══

    async startTurn() {
        // Check if current player has a banked die
        const currentPlayer = this.state.current_player;
        if (this.state.dice && this.state.dice.banked_die && this.state.dice.banked_die[currentPlayer] !== null) {
            // Show bank die choice prompt
            this.showBankDieChoicePrompt();
        } else {
            // No banked die, proceed with normal start turn
            await this.executeStartTurn();
        }
    },

    showBankDieChoicePrompt() {
        const overlay = document.createElement('div');
        overlay.className = 'overlay';
        overlay.style.cssText = 'display: flex; align-items: center; justify-content: center; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 1000;';
        
        const content = document.createElement('div');
        content.style.cssText = 'background: var(--bg-dark); padding: 32px; border-radius: 8px; border: 2px solid var(--accent-gold); max-width: 400px; text-align: center;';
        
        const title = document.createElement('h2');
        title.textContent = 'You Have a Banked Die';
        title.style.cssText = 'color: var(--accent-gold); margin-bottom: 16px;';
        
        const currentPlayer = this.state.current_player;
        const message = document.createElement('p');
        message.textContent = `Banked Die Value: ${this.state.dice.banked_die[currentPlayer]}`;
        message.style.cssText = 'color: var(--text-primary); margin-bottom: 24px; font-size: 1.1rem;';
        
        const keepBtn = document.createElement('button');
        keepBtn.className = 'btn btn-primary';
        keepBtn.textContent = 'Keep Bank Die (Roll 1 Die)';
        keepBtn.style.cssText = 'margin: 8px; padding: 12px 24px; width: 100%;';
        keepBtn.addEventListener('click', async () => {
            overlay.remove();
            await this.executeStartTurn();
        });
        
        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn btn-secondary';
        removeBtn.textContent = 'Remove Bank Die (Roll 2 Fresh Dice)';
        removeBtn.style.cssText = 'margin: 8px; padding: 12px 24px; width: 100%;';
        removeBtn.addEventListener('click', async () => {
            overlay.remove();
            await this.removeBankAndStartTurn();
        });
        
        content.appendChild(title);
        content.appendChild(message);
        content.appendChild(keepBtn);
        content.appendChild(removeBtn);
        overlay.appendChild(content);
        document.body.appendChild(overlay);
    },

    async executeStartTurn() {
        try {
            const resp = await fetch('/start_turn', { method: 'POST' });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.render();
        } catch (e) {
            this.showToast('Failed to start turn', 'fail');
        }
    },

    async removeBankAndStartTurn() {
        try {
            // First remove the banked die
            const pullResp = await fetch('/pull_from_bank', { method: 'POST' });
            const pullData = await pullResp.json();
            if (pullData.error) {
                this.showToast(pullData.error, 'fail');
                return;
            }
            this.state = pullData;
            
            // Then start turn (which will roll 2 fresh dice)
            await this.executeStartTurn();
        } catch (e) {
            this.showToast('Failed to remove bank die', 'fail');
        }
    },

    async endTurn() {
        try {
            const resp = await fetch('/end_turn', { method: 'POST' });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.selectedSquare = null;
            this.legalMoves = [];

            // If AI just played, show its move info
            if (this.mode === 'pvai' && data.events && data.events.length > 0) {
                const aiMoves = data.events.filter(e => e.type === 'ai_move');
                if (aiMoves.length > 0) {
                    const last = aiMoves[aiMoves.length - 1];
                    if (last.from_pos && last.to_pos) {
                        this.lastMoveFrom = last.from_pos;
                        this.lastMoveTo = last.to_pos;
                    }
                }
            }

            this.render();
        } catch (e) {
            this.showToast('End turn failed', 'fail');
        }
    },

    // ═══ NAVIGATION ═══

    backToStart() {
        document.getElementById('game-over-overlay').classList.add('hidden');
        this.state = null;
        this.showScreen('start-screen');
    },

    // ═══ UTILITIES ═══

    showToast(message, type) {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        toast.className = 'toast show';
        if (type === 'fail') toast.classList.add('toast-fail');
        setTimeout(() => {
            toast.className = 'toast';
        }, 2000);
    },

    showMoveBlockedNotification(message) {
        // Remove any existing notification
        const existing = document.getElementById('move-blocked-notification');
        if (existing) existing.remove();

        // Create notification overlay
        const notification = document.createElement('div');
        notification.id = 'move-blocked-notification';
        notification.style.cssText = `
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(0, 0, 0, 0.95);
            color: #ff4444;
            padding: 32px 48px;
            border-radius: 8px;
            border: 3px solid #ff4444;
            font-size: 1.5rem;
            font-weight: bold;
            text-align: center;
            z-index: 10000;
            box-shadow: 0 8px 32px rgba(255, 68, 68, 0.5);
            cursor: pointer;
        `;
        notification.textContent = message;

        // Auto-dismiss after 2 seconds
        const timeoutId = setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 2000);

        // Dismiss on click
        notification.addEventListener('click', () => {
            clearTimeout(timeoutId);
            notification.remove();
        });

        // Dismiss on any click anywhere
        const dismissOnClick = (e) => {
            if (e.target !== notification) {
                clearTimeout(timeoutId);
                notification.remove();
                document.removeEventListener('click', dismissOnClick);
            }
        };
        setTimeout(() => {
            document.addEventListener('click', dismissOnClick);
        }, 100);

        document.body.appendChild(notification);
    },

    shuffleArray(arr) {
        const a = [...arr];
        for (let i = a.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [a[i], a[j]] = [a[j], a[i]];
        }
        return a;
    },

    // ═══ DEV GAME MODE ═══

    async startDevGame() {
        // Determine pawn rosters
        let whitePawns, blackPawns;
        
        const roster = this.devSettings || this.DEFAULT_DEV_ROSTER;
        whitePawns = roster.whitePawns;
        blackPawns = roster.blackPawns;
        
        this.whitePawns = whitePawns;
        this.blackPawns = blackPawns;
        
        // Start game with dev mode flag
        try {
            const resp = await fetch('/new_game', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    mode: 'dev',
                    white_pawns: whitePawns,
                    black_pawns: blackPawns,
                    ...(this.devSettings && this.devSettings.boardLayout
                        ? { board_layout: this.devSettings.boardLayout }
                        : {}),
                }),
            });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.selectedSquare = null;
            this.legalMoves = [];
            this.lastMoveFrom = null;
            this.lastMoveTo = null;
            this.showScreen('game-screen');
            this.render();
        } catch (e) {
            console.error('Failed to start dev game:', e);
            this.showToast('Failed to start dev game', 'fail');
        }
    },

    openDevSettings() {
        const modal = document.getElementById('dev-settings-modal');
        modal.classList.remove('hidden');
        this.devStagingGrid = (this.devSettings && this.devSettings.boardLayout)
            ? this.devSettings.boardLayout
            : this.getDefaultDevLayout();
        this.devStagingSelected = null;
        this.renderDevSettings();
    },

    closeDevSettings() {
        const modal = document.getElementById('dev-settings-modal');
        modal.classList.add('hidden');
    },

    renderDevSettings() {
        const whiteRoster = document.getElementById('white-roster');
        const blackRoster = document.getElementById('black-roster');
        
        // Get current selections or empty arrays
        const whiteSelected = this.devSettings ? this.devSettings.whitePawns : [];
        const blackSelected = this.devSettings ? this.devSettings.blackPawns : [];
        
        // Render white roster
        whiteRoster.innerHTML = '';
        for (const pawn of this.roster) {
            const item = document.createElement('div');
            const isChecked = whiteSelected.includes(pawn.name);
            const isDisabled = whiteSelected.length >= 8 && !isChecked;
            
            item.className = `roster-item ${isChecked ? 'selected' : ''} ${isDisabled ? 'disabled' : ''}`;
            item.innerHTML = `
                <input type="checkbox" 
                       id="white-${pawn.name}" 
                       ${isChecked ? 'checked' : ''} 
                       ${isDisabled ? 'disabled' : ''}
                       onchange="Game.toggleDevPawn('white', '${pawn.name}')">
                <label for="white-${pawn.name}">${pawn.name}</label>
            `;
            whiteRoster.appendChild(item);
        }
        
        // Render black roster
        blackRoster.innerHTML = '';
        for (const pawn of this.roster) {
            const item = document.createElement('div');
            const isChecked = blackSelected.includes(pawn.name);
            const isDisabled = blackSelected.length >= 8 && !isChecked;
            
            item.className = `roster-item ${isChecked ? 'selected' : ''} ${isDisabled ? 'disabled' : ''}`;
            item.innerHTML = `
                <input type="checkbox" 
                       id="black-${pawn.name}" 
                       ${isChecked ? 'checked' : ''} 
                       ${isDisabled ? 'disabled' : ''}
                       onchange="Game.toggleDevPawn('black', '${pawn.name}')">
                <label for="black-${pawn.name}">${pawn.name}</label>
            `;
            blackRoster.appendChild(item);
        }
        
        // Update counters
        document.getElementById('white-count').textContent = `${whiteSelected.length} / 8`;
        document.getElementById('black-count').textContent = `${blackSelected.length} / 8`;

        // Render the interactive staging board below the roster lists
        this.renderDevStagingBoard();
    },

    toggleDevPawn(color, pawnName) {
        // Initialize devSettings if not exists
        if (!this.devSettings) {
            this.devSettings = { whitePawns: [], blackPawns: [] };
        }

        const key = color === 'white' ? 'whitePawns' : 'blackPawns';
        const selected = this.devSettings[key];
        const idx = selected.indexOf(pawnName);

        if (idx >= 0) {
            // Uncheck — remove from list and clear from staging grid
            selected.splice(idx, 1);
            if (this.devStagingGrid) {
                for (let r = 0; r < 11; r++) {
                    for (let c = 0; c < 11; c++) {
                        const cell = this.devStagingGrid[r][c];
                        if (cell && cell.is_pawn && cell.name === pawnName && cell.color === color) {
                            this.devStagingGrid[r][c] = null;
                        }
                    }
                }
            }
        } else {
            // Check (if not at limit) — add to list and place in staging grid
            if (selected.length < 8) {
                selected.push(pawnName);
                if (this.devStagingGrid) {
                    const pawnRow = color === 'white' ? 1 : 9;
                    const pawnData = this.roster.find(p => p.name === pawnName);
                    const short = pawnData ? pawnData.short : pawnName.substring(0, 5).toUpperCase();
                    const newCell = { type: 'Pawn', color, name: pawnName, is_pawn: true, short };
                    // Place in first open slot in the pawn row (cols 1–8)
                    let placed = false;
                    for (let c = 1; c <= 8; c++) {
                        if (!this.devStagingGrid[pawnRow][c]) {
                            this.devStagingGrid[pawnRow][c] = newCell;
                            placed = true;
                            break;
                        }
                    }
                    // Fallback: find any empty square on the board
                    if (!placed) {
                        outer: for (let r = 0; r < 11; r++) {
                            for (let c = 0; c < 11; c++) {
                                if (!this.devStagingGrid[r][c]) {
                                    this.devStagingGrid[r][c] = newCell;
                                    break outer;
                                }
                            }
                        }
                    }
                }
            }
        }

        this.renderDevSettings();
    },

    saveDevSettings() {
        if (!this.devSettings) {
            this.showToast('No settings to save', 'fail');
            return;
        }
        
        if (this.devSettings.whitePawns.length !== 8 || this.devSettings.blackPawns.length !== 8) {
            this.showToast('Both rosters must have exactly 8 pawns', 'fail');
            return;
        }
        
        // Save to localStorage
        localStorage.setItem('dcc_dev_settings', JSON.stringify(this.devSettings));
        this.updateDevStatus();
        this.showToast('Dev settings saved!', 'success');
        this.closeDevSettings();
    },

    clearDevSettings() {
        this.devSettings = null;
        localStorage.removeItem('dcc_dev_settings');
        this.devStagingGrid = this.getDefaultDevLayout();
        this.devStagingSelected = null;
        this.updateDevStatus();
        this.renderDevSettings();
        this.showToast('Dev settings cleared - using random rosters', '');
    },

    loadDevSettings() {
        const saved = localStorage.getItem('dcc_dev_settings');
        if (saved) {
            try {
                this.devSettings = JSON.parse(saved);
            } catch (e) {
                console.error('Failed to load dev settings:', e);
                this.devSettings = null;
            }
        }
    },

    updateDevStatus() {
        const statusEl = document.getElementById('dev-status');
        if (statusEl) {
            if (this.devSettings) {
                statusEl.textContent = 'Dev: Custom Roster';
                statusEl.style.color = 'var(--accent-gold)';
            } else {
                statusEl.textContent = 'Dev: Default Roster';
                statusEl.style.color = 'var(--text-secondary)';
            }
        }
    },

    // ═══ DEV STAGING BOARD ═══

    getDefaultDevLayout() {
        const grid = Array.from({ length: 11 }, () => Array(11).fill(null));

        // White major pieces on row 0, cols 0-7 only — no pawns
        this.STAGING_MAJOR_ORDER.forEach((name, col) => {
            const info = this.STAGING_MAJOR_INFO[name];
            grid[0][col] = { type: info.type, color: 'white', name, is_pawn: false, short: info.short };
        });

        // Black major pieces on row 10, cols 0-7 only — no pawns
        this.STAGING_MAJOR_ORDER.forEach((name, col) => {
            const info = this.STAGING_MAJOR_INFO[name];
            grid[10][col] = { type: info.type, color: 'black', name, is_pawn: false, short: info.short };
        });

        return grid;
    },

    renderDevStagingBoard() {
        const container = document.getElementById('dev-staging-board');
        if (!container) return;

        if (!this.devStagingGrid) {
            this.devStagingGrid = this.getDefaultDevLayout();
        }

        container.innerHTML = '';
        const gridEl = document.createElement('div');
        gridEl.className = 'dev-staging-grid';

        // Render row 10 at top (black back rank), row 0 at bottom (white back rank)
        for (let displayRow = 0; displayRow < 11; displayRow++) {
            const row = 10 - displayRow;
            for (let col = 0; col < 11; col++) {
                const sq = document.createElement('div');
                const isLight = (row + col) % 2 === 0;
                sq.className = `dev-sq ${isLight ? 'dev-sq-light' : 'dev-sq-dark'}`;

                if (this.devStagingSelected &&
                    this.devStagingSelected[0] === row &&
                    this.devStagingSelected[1] === col) {
                    sq.classList.add('dev-sq-selected');
                }

                const piece = this.devStagingGrid[row][col];
                if (piece) {
                    const pieceEl = document.createElement('div');
                    pieceEl.className = `dev-piece dev-piece-${piece.color}`;
                    pieceEl.textContent = piece.short;
                    sq.appendChild(pieceEl);
                }

                sq.addEventListener('click', () => this.devStagingClick(row, col));
                gridEl.appendChild(sq);
            }
        }

        container.appendChild(gridEl);
    },

    devStagingClick(row, col) {
        if (this.devStagingSelected) {
            const [selRow, selCol] = this.devStagingSelected;
            if (selRow === row && selCol === col) {
                // Click same square: deselect
                this.devStagingSelected = null;
            } else {
                // Swap selected piece with target square (so no piece is lost)
                const selPiece = this.devStagingGrid[selRow][selCol];
                const targetPiece = this.devStagingGrid[row][col];
                this.devStagingGrid[row][col] = selPiece;
                this.devStagingGrid[selRow][selCol] = targetPiece;
                this.devStagingSelected = null;
            }
            this.renderDevStagingBoard();
        } else {
            if (this.devStagingGrid[row][col]) {
                this.devStagingSelected = [row, col];
                this.renderDevStagingBoard();
            }
        }
    },

    saveDevBoardLayout() {
        if (!this.devSettings) {
            this.devSettings = {
                whitePawns: [...this.DEFAULT_DEV_ROSTER.whitePawns],
                blackPawns: [...this.DEFAULT_DEV_ROSTER.blackPawns],
            };
        }
        this.devSettings.boardLayout = this.devStagingGrid;
        localStorage.setItem('dcc_dev_settings', JSON.stringify(this.devSettings));
        this.showToast('Board layout saved!', 'success');
    },

    resetDevBoardLayout() {
        this.devStagingGrid = this.getDefaultDevLayout();
        this.devStagingSelected = null;
        this.renderDevStagingBoard();
    },

    clearDevBoard() {
        if (!this.devStagingGrid) return;
        for (let r = 0; r < 11; r++) {
            for (let c = 0; c < 11; c++) {
                const cell = this.devStagingGrid[r][c];
                if (cell && cell.is_pawn) {
                    this.devStagingGrid[r][c] = null;
                }
            }
        }
        this.devStagingSelected = null;
        this.renderDevStagingBoard();
    },

    // ═══ ZONE TARGETING (Air Strike / Lava Spit) ═══

    getZoneRegionSquares() {
        const name = this.targetingAbility ? this.targetingAbility.abilityName : null;
        const regionSet = new Set();
        for (const [r, c] of this.validTargets) {
            regionSet.add(`${r},${c}`);
            if (name === 'Lava Spit') {
                // 1×2 horizontal: add the partner square to the region
                const c2 = c < 10 ? c + 1 : c - 1;
                if (c2 >= 0 && c2 < 11) regionSet.add(`${r},${c2}`);
            } else {
                // Air Strike: 2×2 footprint
                if (r + 1 < 11 && c + 1 < 11) {
                    regionSet.add(`${r + 1},${c}`);
                    regionSet.add(`${r},${c + 1}`);
                    regionSet.add(`${r + 1},${c + 1}`);
                }
            }
        }
        return regionSet;
    },

    findZoneTopLeft(row, col) {
        const name = this.targetingAbility ? this.targetingAbility.abilityName : null;
        if (name === 'Lava Spit') {
            // Anchor = hovered square if it's a valid target
            if (this.validTargets.some(t => t[0] === row && t[1] === col)) {
                return [row, col];
            }
            // Check if hovered square is the right-side partner (anchor = col-1)
            if (col > 0 && this.validTargets.some(t => t[0] === row && t[1] === col - 1)) {
                return [row, col - 1];
            }
            return null;
        }
        // Air Strike 2×2: prefer TL corner, then step left/up/diagonal
        const offsets = [[0, 0], [0, -1], [-1, 0], [-1, -1]];
        for (const [dr, dc] of offsets) {
            const r = row + dr, c = col + dc;
            if (this.validTargets.some(t => t[0] === r && t[1] === c)) {
                return [r, c];
            }
        }
        return null;
    },

    getZoneFootprintSquares(anchorRow, anchorCol) {
        const name = this.targetingAbility ? this.targetingAbility.abilityName : null;
        if (name === 'Lava Spit') {
            const col2 = anchorCol < 10 ? anchorCol + 1 : anchorCol - 1;
            return [[anchorRow, anchorCol], [anchorRow, col2]];
        }
        return [
            [anchorRow, anchorCol], [anchorRow, anchorCol + 1],
            [anchorRow + 1, anchorCol], [anchorRow + 1, anchorCol + 1],
        ];
    },

    isZoneEmpty(topLeftRow, topLeftCol) {
        const board = this.state.board;
        for (let dr = 0; dr <= 1; dr++) {
            for (let dc = 0; dc <= 1; dc++) {
                const r = topLeftRow + dr, c = topLeftCol + dc;
                if (r < 11 && c < 11 && board[r] && board[r][c] !== null) {
                    return false;
                }
            }
        }
        return true;
    },

    handleZoneHover(row, col) {
        const topLeft = this.findZoneTopLeft(row, col);
        const old = this.zoneHoverTopLeft;
        const changed = (!old && topLeft) ||
                        (old && !topLeft) ||
                        (old && topLeft && (old[0] !== topLeft[0] || old[1] !== topLeft[1]));
        if (changed) {
            this.zoneHoverTopLeft = topLeft;
            this.renderBoard();
        }
    },

    async handleZoneClick(row, col) {
        const topLeft = this.zoneHoverTopLeft || this.findZoneTopLeft(row, col);
        if (!topLeft) return;

        const abilityName = this.targetingAbility.abilityName;

        // Air Strike: zone must be fully empty; red preview = silent reject
        if (abilityName === 'Air Strike' && !this.isZoneEmpty(topLeft[0], topLeft[1])) {
            return;
        }

        await this.executeAbility(
            this.targetingAbility.pieceRow,
            this.targetingAbility.pieceCol,
            abilityName,
            this.targetingAbility.dieIndex,
            { row: topLeft[0], col: topLeft[1] },
            this.targetingAbility.useCombined,
        );
        this.zoneHoverTopLeft = null;
        this.exitTargetingMode();
    },
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => Game.init());
