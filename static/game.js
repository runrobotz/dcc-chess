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
    lastEventSeq: 0,      // Highest event `seq` already shown, to detect new auto-ability triggers

    // AI Event Panel (Stage F): persistent record of the last-drawn AI Card,
    // shown below the End Turn / Undo buttons until dismissed or replaced.
    aiEventPanel: null,          // {card, cardType, triggeredBy, affects, effect} or null
    aiEventPanelDismissed: false,
    
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

    ORTHRUS_ARROWS: { up: '▲', down: '▼', left: '◀', right: '▶' },

    pieceLabel(piece) {
        if (piece.name === 'Orthrus' && piece.is_orthrus_head && piece.orthrus_direction) {
            return `${piece.short}${this.ORTHRUS_ARROWS[piece.orthrus_direction] || ''}`;
        }
        return piece.short;
    },

    // ═══ AI CARD SYSTEM (Stage C display) ═══

    AI_CARD_ICONS: {
        "Lottery Ticket": '🎫',
        "You a Bitch": '😤',
        "AI's Pet": '🐕',
        "Dirty Tootsies": '🦶',
        "System Reset": '⚡',
        "Too Boring": '😴',
        "Main Character Syndrome": '🎭',
        "Matt's Drunk Again": '🍺',
        "Mana Toast": '🍞',
        "What a Bitch": '💀',
        "Summon Rage Elemental": '🔥',
        "Summon Feral Goose": '🦢',
        "Summon Emberus": '🌋',
        "Summon Goblin Murder Dozer": '🚜',
    },

    // Buff/debuff/chaos/summon per the card's overall flavor. "Lottery Ticket" isn't
    // listed here -- its Custard (buff) vs Fireball (debuff) split isn't known until
    // resolution, so aiCardTypeFor() below resolves it dynamically from the
    // `lottery_ticket_roll` event logged in the same batch as the draw.
    AI_CARD_TYPES: {
        "AI's Pet": 'buff',
        "What a Bitch": 'buff',
        "You a Bitch": 'buff',
        "Mana Toast": 'buff',
        "Dirty Tootsies": 'debuff',
        "System Reset": 'debuff',
        "Too Boring": 'debuff',
        "Main Character Syndrome": 'debuff',
        "Matt's Drunk Again": 'chaos',
        "Summon Rage Elemental": 'summon',
        "Summon Feral Goose": 'summon',
        "Summon Emberus": 'summon',
        "Summon Goblin Murder Dozer": 'summon',
    },

    aiCardTypeFor(cardName, batchEvents) {
        if (cardName === 'Lottery Ticket') {
            const rollEvent = (batchEvents || []).find(e => e.type === 'lottery_ticket_roll');
            if (rollEvent) return rollEvent.roll <= 3 ? 'buff' : 'debuff';
            return 'buff';
        }
        return this.AI_CARD_TYPES[cardName] || 'buff';
    },

    // Plain-English "who this affects" for the AI Event Panel. Lottery Ticket
    // isn't listed -- its Custard/Fireball split is resolved dynamically in
    // aiCardAffectsFor(), same pattern as aiCardTypeFor() above.
    AI_CARD_AFFECTS: {
        "You a Bitch": "You — if you're behind on piece count",
        "AI's Pet": "You — all your ability costs this turn",
        "Dirty Tootsies": "You — all your ability costs this turn",
        "System Reset": "Both players — no abilities this turn",
        "Too Boring": "Both players — one pawn each, chosen by the opponent",
        "Main Character Syndrome": "Both players — no pawn movement this turn",
        "Matt's Drunk Again": "Both players — control of pieces is swapped",
        "Mana Toast": "You — your dice this turn",
        "What a Bitch": "You — gain an Insta-Kill Boss Card",
        "Summon Rage Elemental": "Both players — a boss is summoned",
        "Summon Feral Goose": "Both players — a boss is summoned",
        "Summon Emberus": "Both players — a boss is summoned",
        "Summon Goblin Murder Dozer": "Both players — a boss is summoned",
    },

    aiCardAffectsFor(cardName, batchEvents) {
        if (cardName === 'Lottery Ticket') {
            const rollEvent = (batchEvents || []).find(e => e.type === 'lottery_ticket_roll');
            if (rollEvent) {
                return rollEvent.roll <= 3
                    ? 'You — Custard resets one of your spent abilities'
                    : 'A random square — Fireball may permanently kill whatever piece is there';
            }
            return 'You, or a random square, depending on the roll';
        }
        return this.AI_CARD_AFFECTS[cardName] || 'You';
    },

    renderAiDeckCounter() {
        const el = document.getElementById('ai-deck-counter');
        const devBtn = document.getElementById('dev-draw-ai-card-btn');
        if (!this.state) return;

        // DEV: Draw AI Card -- Dev Game mode only, regardless of deck state (an
        // empty-deck click is a valid thing to test: the trigger fires, nothing happens).
        if (devBtn) {
            devBtn.classList.toggle('hidden', this.state.mode !== 'dev');
        }

        if (!el) return;
        const remaining = this.state.ai_deck_remaining;
        if (remaining === undefined || remaining === null) {
            el.classList.add('hidden');
            return;
        }
        el.classList.remove('hidden');
        if (remaining <= 0) {
            el.classList.add('empty');
            el.innerHTML = `<span class="ai-deck-icon">🚫🎴</span> 0 left`;
        } else {
            el.classList.remove('empty');
            el.innerHTML = `<span class="ai-deck-icon">🎴</span> ${remaining} left`;
        }
    },

    // Brief border-flash on the dice panel + "THE AI HAS ARRIVED" banner text,
    // shown the instant a roll triggers the AI summon -- before the card itself
    // is revealed. Returns a Promise that resolves once the ~1s flash is done.
    showAiTriggerFlash() {
        return new Promise((resolve) => {
            const dicePanel = document.getElementById('dice-panel');
            if (dicePanel) {
                dicePanel.classList.remove('ai-trigger-flash');
                // Force reflow so re-adding the class restarts the animation.
                void dicePanel.offsetWidth;
                dicePanel.classList.add('ai-trigger-flash');
            }

            document.getElementById('ai-trigger-banner')?.remove();
            const banner = document.createElement('div');
            banner.id = 'ai-trigger-banner';
            banner.className = 'ai-trigger-banner';
            banner.textContent = '☠️ THE AI HAS ARRIVED ☠️';
            document.body.appendChild(banner);

            setTimeout(() => {
                dicePanel?.classList.remove('ai-trigger-flash');
                banner.remove();
                resolve();
            }, 1000);
        });
    },

    // Full-screen dramatic card reveal: dungeon-themed card, fades/scales in, stays
    // for 2s (or until clicked), then fades out. Returns a Promise that resolves
    // once it's fully dismissed. `meta` optionally carries {bossName, hp, maxHp}
    // for Summon cards' extra HP readout.
    showAiCardOverlay(cardName, description, cardType, meta) {
        return new Promise((resolve) => {
            document.getElementById('ai-card-overlay')?.remove();

            const backdrop = document.createElement('div');
            backdrop.id = 'ai-card-overlay';
            backdrop.className = 'ai-card-overlay-backdrop';

            const card = document.createElement('div');
            card.className = `ai-card ${cardType}`;

            const icon = this.AI_CARD_ICONS[cardName] || '🎴';
            let bossMetaHtml = '';
            if (meta && meta.bossName) {
                bossMetaHtml = `<div class="ai-card-boss-meta">👹 ${meta.bossName} — ${meta.hp} / ${meta.maxHp} HP</div>`;
            }

            card.innerHTML = `
                <div class="ai-card-name">${cardName}</div>
                <div class="ai-card-icon">${icon}</div>
                <div class="ai-card-desc">${description || ''}</div>
                ${bossMetaHtml}
            `;

            backdrop.appendChild(card);
            document.body.appendChild(backdrop);

            let dismissed = false;
            const dismiss = () => {
                if (dismissed) return;
                dismissed = true;
                clearTimeout(autoTimer);
                backdrop.classList.add('exiting');
                backdrop.classList.remove('visible');
                setTimeout(() => {
                    backdrop.remove();
                    resolve();
                }, 300);
            };

            backdrop.addEventListener('click', dismiss);

            // Animate in shortly after insertion so the initial (pre-.visible) styles
            // apply first. Deliberately setTimeout, not requestAnimationFrame -- rAF is
            // suspended entirely in backgrounded/hidden tabs (e.g. a PvP player alt-tabbed
            // away when their opponent's roll triggers a card), which would otherwise leave
            // the overlay stuck invisible until they tab back in.
            setTimeout(() => backdrop.classList.add('visible'), 20);

            const autoTimer = setTimeout(dismiss, 2000);
        });
    },

    // Boss-encounter-style announcement over the board itself: a red flash sweeps
    // the board while the boss's name appears huge and centered, then fades. Used
    // only for Summon cards, right after their card overlay dismisses.
    showBossSummonAnnouncement(bossName) {
        return new Promise((resolve) => {
            const overlay = document.getElementById('boss-announcement-overlay');
            if (!overlay) { resolve(); return; }

            overlay.innerHTML = `<div class="boss-announcement-text">${bossName}<br>HAS ARRIVED</div>`;
            overlay.classList.remove('hidden');
            overlay.classList.remove('flashing');
            void overlay.offsetWidth;
            overlay.classList.add('flashing');

            setTimeout(() => {
                overlay.classList.add('hidden');
                overlay.classList.remove('flashing');
                overlay.innerHTML = '';
                resolve();
            }, 1800);
        });
    },

    // Victory overlay shown when a boss's HP reaches 0. Reuses the AI Card
    // overlay's backdrop/card shell with its own celebratory styling.
    showBossVictoryOverlay(bossName) {
        return new Promise((resolve) => {
            document.getElementById('boss-victory-overlay')?.remove();

            const backdrop = document.createElement('div');
            backdrop.id = 'boss-victory-overlay';
            backdrop.className = 'ai-card-overlay-backdrop';

            const card = document.createElement('div');
            card.className = 'ai-card victory';
            card.innerHTML = `
                <div class="ai-card-name">${bossName}</div>
                <div class="ai-card-icon">🏆</div>
                <div class="ai-card-desc">Defeated! Normal combat resumes.</div>
            `;

            backdrop.appendChild(card);
            document.body.appendChild(backdrop);

            let dismissed = false;
            const dismiss = () => {
                if (dismissed) return;
                dismissed = true;
                clearTimeout(autoTimer);
                backdrop.classList.add('exiting');
                backdrop.classList.remove('visible');
                setTimeout(() => {
                    backdrop.remove();
                    resolve();
                }, 300);
            };

            backdrop.addEventListener('click', dismiss);
            setTimeout(() => backdrop.classList.add('visible'), 20);
            const autoTimer = setTimeout(dismiss, 2500);
        });
    },

    // Populate the AI Event Panel from a freshly-drawn card. `batchEvents` is
    // the same poll's event batch (may already include this card's
    // resolution, e.g. instant-resolving cards), so the effect text is filled
    // in immediately when available.
    setAiEventPanel(drawnEvent, batchEvents) {
        const resolvedEvent = (batchEvents || []).find(
            e => e.type === 'ai_card_resolved' && e.card === drawnEvent.card);
        this.aiEventPanel = {
            card: drawnEvent.card,
            cardType: this.aiCardTypeFor(drawnEvent.card, batchEvents),
            triggeredBy: drawnEvent.player,
            affects: this.aiCardAffectsFor(drawnEvent.card, batchEvents),
            effect: resolvedEvent ? resolvedEvent.outcome : drawnEvent.description,
        };
        this.aiEventPanelDismissed = false;
        this.renderAiEventPanel();
    },

    renderAiEventPanel() {
        const panel = document.getElementById('ai-event-panel');
        if (!panel) return;
        const ev = this.aiEventPanel;
        if (!ev || this.aiEventPanelDismissed) {
            panel.classList.add('hidden');
            panel.innerHTML = '';
            return;
        }

        let statusLine = '';
        if (ev.card === "Matt's Drunk Again" && this.state.swap_active) {
            const n = this.state.swap_turns_remaining;
            statusLine = `🔄 Swap active — ${n} turn${n === 1 ? '' : 's'} remaining`;
        } else if (ev.card === 'System Reset' && this.state.system_reset_active) {
            statusLine = '🔒 No abilities this turn.';
        } else if (ev.card === 'Main Character Syndrome' && this.state.main_character_syndrome_active) {
            statusLine = '🚫 Pawns cannot move this turn.';
        } else if (ev.card.startsWith('Summon ') && this.state.boss_active && this.state.active_boss === 'Feral Goose') {
            statusLine = '⚠️ The Feral Goose cannot be harmed by any attack. To defeat it: simultaneously place a ' +
                'piece on all 4 corner squares AND the center square (5,5). The green highlighted squares show ' +
                'where pieces must go.';
        } else if (ev.card.startsWith('Summon ') && this.state.boss_active) {
            statusLine = `👹 ${this.state.active_boss} — ${this.state.boss_hp} / ${this.state.boss_max_hp} HP. ` +
                `Use Special Event Attacks to damage the boss. Regular PvP combat is paused.`;
        }

        const icon = this.AI_CARD_ICONS[ev.card] || '🎴';
        const triggeredByLabel = ev.triggeredBy === 'white' ? 'White' : 'Black';

        panel.classList.remove('hidden');
        panel.className = `ai-event-panel ${ev.cardType}`;
        panel.innerHTML = `
            <button class="ai-event-panel-dismiss" title="Dismiss">✕</button>
            <div class="ai-event-panel-header ${ev.cardType}">
                <span class="ai-event-panel-icon">${icon}</span>
                <span class="ai-event-panel-name">${ev.card}</span>
            </div>
            <div class="ai-event-panel-row"><span class="aep-label">Triggered by:</span>${triggeredByLabel}</div>
            <div class="ai-event-panel-row"><span class="aep-label">Affects:</span>${ev.affects}</div>
            <div class="ai-event-panel-row"><span class="aep-label">Effect:</span>${ev.effect || '—'}</div>
            ${statusLine ? `<div class="ai-event-panel-status">${statusLine}</div>` : ''}
        `;
        panel.querySelector('.ai-event-panel-dismiss').addEventListener('click', () => {
            this.aiEventPanelDismissed = true;
            this.renderAiEventPanel();
        });
    },

    // The color whose pieces the current player may click/move right now -- equal to
    // current_player normally, flipped to the opponent's color during a Matt's Drunk
    // Again control swap. Board-level piece.color is always the TRUE color, so any
    // "is this my piece" check on raw board data must go through this, not current_player.
    controlledColor() {
        if (!this.state) return null;
        if (this.state.swap_active) {
            return this.state.current_player === 'white' ? 'black' : 'white';
        }
        return this.state.current_player;
    },

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
                // Both players draft from the same full roster -- picking a pawn
                // White already took is allowed, each side gets their own copy.
                subtitle.textContent = 'Select exactly 8 pawns';
            }
        }

        counter.textContent = this.draftSelection.length;
        confirmBtn.disabled = this.draftSelection.length !== 8;

        grid.innerHTML = '';
        // "The AI" is a real pawn character (used elsewhere, e.g. Dev Mode staging)
        // but isn't meant to be a draftable pick, so it's filtered out of this grid
        // only -- this.roster itself stays untouched for other screens.
        const draftablePawns = this.roster.filter(pawn => pawn.name !== 'The AI');
        for (const pawn of draftablePawns) {
            const card = document.createElement('div');
            card.className = 'draft-card';

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

            card.addEventListener('click', () => this.toggleDraftPawn(pawn.name));

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
        this.hideAbilityTooltip();
        this.renderBoard();
        this.renderHeader();
        this.renderCheckBanner();
        this.renderSwapBanner();
        this.renderFallenBanner();
        this.renderBossHealthBar();
        this.renderAiDeckCounter();
        this.renderAiEventPanel();
        this.updateActivePanelHighlight();
        this.renderInstaKillBadges();
        for (const color of ['white', 'black']) {
            this.renderSidebar(color);
            this.renderStatusEffectsForColor(color);
            this.renderCapturedPiecesForColor(color);
            this.renderAbilityGridForColor(color);
        }
        this.hidePlacementUiIfNotPlacementPhase();
        if (this.state.phase === 'placement') {
            this.renderPlacementPanel();
        } else if (this.state.phase === 'boss_turn') {
            this.renderBossTurnPanel();
        } else {
            this.renderDicePanel();
        }
        if (this.state.game_over) {
            this.checkGameOver();
        }
        this.checkForAutoAbilityEvents();
        this.checkGameOver();
        this.handlePendingAiCardDecision();
    },

    handlePendingAiCardDecision() {
        const pending = this.state.pending_ai_card_decision;
        const existing = document.getElementById('ai-card-decision-prompt');
        if (!pending) {
            if (existing) existing.remove();
            this._shownPendingDecisionKey = null;
            return;
        }
        const key = JSON.stringify(pending);
        if (existing && this._shownPendingDecisionKey === key) return; // already showing this exact decision
        if (existing) existing.remove();
        this._shownPendingDecisionKey = key;
        if (pending.type === 'custard') {
            this.showCustardPrompt(pending);
        } else if (pending.type === 'too_boring') {
            this.showTooBoringPrompt(pending);
        }
    },

    showCustardPrompt(pending) {
        const overlay = document.createElement('div');
        overlay.id = 'ai-card-decision-prompt';
        overlay.className = 'overlay';

        const content = document.createElement('div');
        content.className = 'overlay-content';

        const title = document.createElement('h2');
        title.textContent = '🍮 Lottery Ticket — Custard';

        const msg = document.createElement('p');
        const colorLabel = pending.color === 'white' ? 'White' : 'Black';
        msg.textContent = `${colorLabel}, choose one spent ability to reset:`;

        const list = document.createElement('div');
        list.style.cssText = 'display: flex; flex-direction: column; gap: 8px; margin-top: 12px;';
        for (const opt of pending.options) {
            const btn = document.createElement('button');
            btn.className = 'btn btn-secondary';
            btn.textContent = opt.label;
            btn.addEventListener('click', () => this.resolveCustardChoice(opt.index));
            list.appendChild(btn);
        }

        content.appendChild(title);
        content.appendChild(msg);
        content.appendChild(list);
        overlay.appendChild(content);
        document.body.appendChild(overlay);
    },

    async resolveCustardChoice(index) {
        try {
            const resp = await fetch('/ai_card/custard_choice', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ index }),
            });
            const data = await resp.json();
            const overlay = document.getElementById('ai-card-decision-prompt');
            if (overlay) overlay.remove();
            this._shownPendingDecisionKey = null;
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.render();
        } catch (e) {
            this.showToast('Failed to resolve Custard choice', 'fail');
        }
    },

    showTooBoringPrompt(pending) {
        const overlay = document.createElement('div');
        overlay.id = 'ai-card-decision-prompt';
        overlay.className = 'overlay';

        const content = document.createElement('div');
        content.className = 'overlay-content';

        const title = document.createElement('h2');
        title.textContent = '😴 Too Boring';

        const chooserLabel = pending.chooser_color === 'white' ? 'White' : 'Black';
        const eliminateLabel = pending.eliminate_color === 'white' ? "White's" : "Black's";
        const msg = document.createElement('p');
        msg.textContent = `${chooserLabel}, choose one of ${eliminateLabel} pawns to permanently eliminate.`;

        const list = document.createElement('div');
        list.style.cssText = 'display: flex; flex-direction: column; gap: 8px; margin-top: 12px; max-height: 300px; overflow-y: auto;';
        for (const [r, c] of pending.valid_targets) {
            const piece = this.state.board[r][c];
            const btn = document.createElement('button');
            btn.className = 'btn btn-secondary';
            btn.textContent = piece ? `${piece.name} (${this.squareLabel(r, c)})` : this.squareLabel(r, c);
            btn.addEventListener('click', () => this.resolveTooBoringChoice(r, c));
            list.appendChild(btn);
        }

        content.appendChild(title);
        content.appendChild(msg);
        content.appendChild(list);
        overlay.appendChild(content);
        document.body.appendChild(overlay);
    },

    async resolveTooBoringChoice(row, col) {
        try {
            const resp = await fetch('/ai_card/too_boring_choice', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ row, col }),
            });
            const data = await resp.json();
            const overlay = document.getElementById('ai-card-decision-prompt');
            if (overlay) overlay.remove();
            this._shownPendingDecisionKey = null;
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.render();
        } catch (e) {
            this.showToast('Failed to resolve Too Boring choice', 'fail');
        }
    },

    updateActivePanelHighlight() {
        const whitePanel = document.getElementById('white-player-panel');
        const blackPanel = document.getElementById('black-player-panel');
        if (whitePanel) whitePanel.classList.toggle('active-panel', this.state.current_player === 'white');
        if (blackPanel) blackPanel.classList.toggle('active-panel', this.state.current_player === 'black');
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

    renderSwapBanner() {
        const banner = document.getElementById('swap-banner');
        if (!banner) return;
        if (this.state.swap_active && !this.state.game_over) {
            const n = this.state.swap_turns_remaining;
            banner.textContent = `🔄 Matt's Drunk Again — control is swapped! ${n} turn${n === 1 ? '' : 's'} remaining`;
            banner.classList.remove('hidden');
        } else {
            banner.classList.add('hidden');
        }
    },

    renderFallenBanner() {
        const banner = document.getElementById('fallen-banner');
        if (!banner) return;
        const fallen = this.state.fallen_players || [];
        if (fallen.length === 0 || this.state.game_over) {
            banner.classList.add('hidden');
            return;
        }
        if (fallen.length >= 2) {
            banner.textContent = '💀 Both players have fallen.';
        } else {
            const fallenLabel = fallen[0] === 'white' ? 'White' : 'Black';
            const survivorLabel = fallen[0] === 'white' ? 'Black' : 'White';
            banner.textContent = `💀 ${fallenLabel} has fallen — ${survivorLabel} must defeat the boss alone.`;
        }
        banner.classList.remove('hidden');
    },

    showPlayerFallenOverlay(fallenColor, survivorColor) {
        return new Promise((resolve) => {
            document.getElementById('player-fallen-overlay')?.remove();

            const backdrop = document.createElement('div');
            backdrop.id = 'player-fallen-overlay';
            backdrop.className = 'ai-card-overlay-backdrop';

            const card = document.createElement('div');
            card.className = 'ai-card debuff';

            const fallenLabel = fallenColor === 'white' ? 'White' : 'Black';
            const survivorLabel = survivorColor === 'white' ? 'White' : 'Black';
            card.innerHTML = `
                <div class="ai-card-name">${fallenLabel} Has Fallen</div>
                <div class="ai-card-icon">💀</div>
                <div class="ai-card-desc">${survivorLabel} must defeat the boss alone. ${fallenLabel}'s remaining pieces stay on the board and can still be used as resources in the fight.</div>
            `;

            backdrop.appendChild(card);
            document.body.appendChild(backdrop);

            let dismissed = false;
            const dismiss = () => {
                if (dismissed) return;
                dismissed = true;
                clearTimeout(autoTimer);
                backdrop.classList.add('exiting');
                backdrop.classList.remove('visible');
                setTimeout(() => { backdrop.remove(); resolve(); }, 300);
            };
            backdrop.addEventListener('click', dismiss);
            setTimeout(() => backdrop.classList.add('visible'), 20);
            const autoTimer = setTimeout(dismiss, 3000);
        });
    },

    renderBossHealthBar() {
        const bar = document.getElementById('boss-health-bar');
        if (!bar) return;
        if (!this.state.boss_active || !this.state.active_boss) {
            bar.classList.add('hidden');
            return;
        }
        bar.classList.remove('hidden');
        if (this.state.active_boss === 'Feral Goose') {
            // She can't be damaged at all -- an HP readout (permanently 0/0)
            // would misleadingly read as already-defeated. Show the puzzle
            // objective in its place instead.
            bar.innerHTML = `
                <span class="boss-name">👹 ${this.state.active_boss}</span>
                <span class="boss-hp-label">🧩 Puzzle — Place pieces on all corners + center</span>
            `;
            return;
        }
        const hp = this.state.boss_hp || 0;
        const maxHp = this.state.boss_max_hp || 0;
        const pct = maxHp > 0 ? Math.max(0, Math.min(100, (hp / maxHp) * 100)) : 0;
        bar.innerHTML = `
            <span class="boss-name">👹 ${this.state.active_boss}</span>
            <div class="boss-hp-track"><div class="boss-hp-fill" style="width: ${pct}%;"></div></div>
            <span class="boss-hp-label">${hp} / ${maxHp} HP</span>
        `;
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
            move: 'Starting Turn…',
            ability: 'Ability & Move Phase',
            placement: 'Placement Phase',
            boss_turn: 'Boss Turn',
            game_over: 'Game Over'
        };
        phase.textContent = phaseNames[s.phase] || s.phase;

        // The manual "Start Turn" button was removed in Chunk 4 — turn
        // transitions (banner → auto-roll → ability phase) are automatic now.
        // Clean up any stale button just in case one is still in the DOM.
        const existingBtn = document.getElementById('start-turn-btn');
        if (existingBtn) existingBtn.remove();
    },

    renderInstaKillBadges() {
        const card = this.state.insta_kill_card || {};
        for (const color of ['white', 'black']) {
            const header = document.querySelector(`.${color}-panel-header`);
            if (!header) continue;
            let badge = header.querySelector('.insta-kill-badge');
            if (card[color]) {
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'insta-kill-badge';
                    badge.title = 'Holds an Insta-Kill Boss Card';
                    badge.textContent = ' 💀';
                    header.appendChild(badge);
                }
            } else if (badge) {
                badge.remove();
            }
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
        const isDirectionAbility = this.targetingMode && this.targetingAbility &&
            this.targetingAbility.abilityName === 'Lava Surge';
        const directionPreviewSet = isDirectionAbility
            ? new Set(this.getDirectionPreviewSquares().map(([r, c]) => `${r},${c}`))
            : null;

        // Persistent zone overlay sets
        const airStrikeSet = new Set((this.state.air_strike_zones || []).map(z => `${z[0]},${z[1]}`));
        const lavaZoneSet = new Set((this.state.lava_zones || []).map(z => `${z[0]},${z[1]}`));
        const bossSquareSet = new Set((this.state.boss_squares || []).map(z => `${z[0]},${z[1]}`));
        const feralGoosePuzzleActive = this.state.boss_active && this.state.active_boss === 'Feral Goose';
        const feralGooseSquareSet = feralGoosePuzzleActive
            ? new Set(['0,0', '0,10', '10,0', '10,10', '5,5'])
            : null;

        // Status effect maps/sets
        const frozenSet = new Set((this.state.frozen_pieces || []).map(z => `${z[0]},${z[1]}`));
        const suppressedSet = new Set((this.state.suppressed_pieces || []).map(z => `${z[0]},${z[1]}`));
        const restrainedSet = new Set((this.state.restrained_pieces || []).map(z => `${z[0]},${z[1]}`));
        const sheTankSet = new Set((this.state.she_tank_targets || []).map(z => `${z[0]},${z[1]}`));
        const ironWallMap = this.state.iron_wall_pieces || {};
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
                if (this.state.boss_active && bossSquareSet.has(`${row},${col}`)) {
                    sq.classList.add('boss-square');
                }
                if (feralGooseSquareSet && feralGooseSquareSet.has(`${row},${col}`)) {
                    sq.classList.add('feral-goose-square');
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
                    } else if (isDirectionAbility) {
                        if (directionPreviewSet.has(`${row},${col}`)) {
                            sq.style.boxShadow = 'inset 0 0 0 2px rgba(255,120,40,0.95), inset 0 0 0 999px rgba(255,90,0,0.35)';
                        }
                    } else if (this.targetingAbility && this.targetingAbility.abilityName === 'Plot Armor') {
                        // Plot Armor is a movement ability -- its destinations should look
                        // exactly like normal legal-move squares (green dot / red capture
                        // outline), not the generic gold "valid-target" tint used by
                        // non-movement targeting abilities (Blitzed, She Tank, etc).
                        const isValidTarget = this.validTargets.some(t => t[0] === row && t[1] === col);
                        if (isValidTarget) {
                            const target = grid[row][col];
                            if (target && target.color !== this.controlledColor()) {
                                sq.classList.add('legal-capture');
                            } else {
                                sq.classList.add('legal-move');
                            }
                        }
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
                        if (target && target.color !== this.controlledColor()) {
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
                        labelSpan.textContent = this.pieceLabel(piece);
                        pieceEl.appendChild(labelSpan);
                        const badge = document.createElement('span');
                        badge.className = 'effect-badge';
                        badge.textContent = effectSymbols.join('');
                        pieceEl.appendChild(badge);
                    } else {
                        pieceEl.textContent = this.pieceLabel(piece);
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

                // Square-level persistent effects: Iron Wall (gold border)
                if (piece) {
                    const iwTurns = ironWallMap[sqKey];
                    if (iwTurns > 0) {
                        const ironShadow = 'inset 0 0 0 3px rgba(201,168,76,0.95)';
                        sq.style.boxShadow = sq.style.boxShadow ? `${sq.style.boxShadow}, ${ironShadow}` : ironShadow;
                        tooltipLines.push(`Iron Wall — ${iwTurns} turn${iwTurns !== 1 ? 's' : ''} remaining`);
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

        // The backend only ever returns the last 20 events, so a plain
        // length-based cursor breaks (permanently pins to 20) once the log
        // fills up. `seq` is a stable, ever-increasing id per event, so it
        // survives the array being truncated on the server.
        const events = this.state.events;
        const newEvents = events.filter(e => (e.seq || 0) > this.lastEventSeq);
        for (const e of events) {
            if ((e.seq || 0) > this.lastEventSeq) this.lastEventSeq = e.seq;
        }

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
            } else if (event.type === 'ai_summon_trigger') {
                // Kick off the full dramatic sequence (trigger flash -> card reveal ->
                // boss announcement if applicable). Fire-and-forget: render() isn't
                // async, and this shouldn't block subsequent renders.
                this.runAiCardSequence(newEvents);
            } else if (event.type === 'ai_card_drawn') {
                this.setAiEventPanel(event, newEvents);
            } else if (event.type === 'ai_card_resolved') {
                console.log(`[AI Card] ${event.card} (${event.player}): ${event.outcome}`);
                this.showToast(`🎴 ${event.card}: ${event.outcome}`, '');
                // Custard / Too Boring pause for a player decision, so their real
                // outcome can arrive in a later batch than the draw itself.
                if (this.aiEventPanel && this.aiEventPanel.card === event.card) {
                    this.aiEventPanel.effect = event.outcome;
                    this.renderAiEventPanel();
                }
            } else if (event.type === 'ai_card_deck_empty') {
                console.log(`[AI Card] Summon triggered but the deck is empty (${event.player})`);
            } else if (event.type === 'boss_moved') {
                this.showToast(`🧭 ${event.boss} moves ${event.direction}!`, '');
                this.flashBossMovement();
            } else if (event.type === 'boss_no_movement') {
                const reason = event.reason === 'rolled_10_to_12' ? 'no movement this turn (rolled 10-12)'
                    : event.reason === 'would_leave_board' ? `blocked at the board's edge (rolled ${event.direction})`
                    : event.reason === 'samantha_iwkym_hold' ? `held by Samantha's IWKYM (${event.iwkym_turns_remaining} turn(s) left)`
                    : 'no movement';
                this.showToast(`🧭 Boss compass roll: ${reason}`, '');
            } else if (event.type === 'boss_movement_kill') {
                console.log(`[Boss] ${event.piece} was crushed at ${event.pos}`);
            } else if (event.type === 'jug_o_boom') {
                this.showToast(event.hit ? '💥 Jug-o-Boom: Direct hit!' : '💥 Jug-o-Boom: Miss!', event.hit ? '' : 'fail');
            } else if (event.type === 'magic_missile') {
                this.showToast(event.hit ? '✨ Magic Missile: Direct hit!' : '✨ Magic Missile: Missed!', event.hit ? '' : 'fail');
            } else if (event.type === 'gorefest') {
                this.showToast(event.hit ? '🩸 Gorefest: Direct hit!' : '🩸 Gorefest: Miss!', event.hit ? '' : 'fail');
            } else if (event.type === 'i_need_my_space') {
                const moved = event.result && event.result.moved;
                this.showToast(moved ? `🤺 I Need My Space: boss shoved back ${event.result.distance} square(s)!` : '🤺 I Need My Space: the boss is already at the edge.', '');
            } else if (event.type === 'iwkym_activated') {
                this.showToast('🦈 IWKYM: Samantha clamps down on the boss!', '');
            } else if (event.type === 'iwkym_broken') {
                this.showToast("🤺 Katia's push broke Samantha's IWKYM hold!", '');
            } else if (event.type === 'iwkym_release') {
                this.showToast('🦈 Samantha releases her hold and returns to the back rank.', '');
            } else if (event.type === 'boss_damaged') {
                console.log(`[Boss] ${event.boss} takes ${event.amount} damage -- ${event.boss_hp} HP left`);
            } else if (event.type === 'boss_defeated') {
                this.showBossVictoryOverlay(event.boss);
            } else if (event.type === 'feral_goose_puzzle_solved') {
                this.showToast('🧩 Puzzle Solved — The Feral Goose has been defeated!', 'success');
            } else if (event.type === 'boss_damage_blocked') {
                this.showToast('🪿 The Feral Goose is immune to all attacks — solve the puzzle to defeat it.', 'fail');
            } else if (event.type === 'player_fallen') {
                this.showPlayerFallenOverlay(event.color, event.surviving_color);
            }
        }
    },

    // Runs the full AI Card reveal sequence for one summon trigger: border flash +
    // "THE AI HAS ARRIVED" -> full-screen card overlay -> (Summon cards that actually
    // spawned a boss, i.e. not queued behind an already-active one) board flash with
    // the boss's name. `batchEvents` is the set of new events from the same poll, so
    // the drawn card, its Lottery Ticket sub-roll, and its resolution are all visible.
    async runAiCardSequence(batchEvents) {
        await this.showAiTriggerFlash();

        const drawnEvent = batchEvents.find(e => e.type === 'ai_card_drawn');
        if (!drawnEvent) return; // trigger fired but the deck was empty

        const cardType = this.aiCardTypeFor(drawnEvent.card, batchEvents);
        const resolvedEvent = batchEvents.find(e => e.type === 'ai_card_resolved' && e.card === drawnEvent.card);
        const actuallySpawned = cardType === 'summon' && resolvedEvent &&
            /has been summoned/i.test(resolvedEvent.outcome || '');

        let meta = null;
        let bossName = null;
        if (actuallySpawned) {
            bossName = this.state.active_boss || drawnEvent.card.replace('Summon ', '');
            meta = { bossName, hp: this.state.boss_hp, maxHp: this.state.boss_max_hp };
        }

        await this.showAiCardOverlay(drawnEvent.card, drawnEvent.description, cardType, meta);

        if (actuallySpawned) {
            await this.showBossSummonAnnouncement(bossName);
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

    // The placement pieces list + "Click any square on row X to place Y"
    // instruction are both written into #placement-pieces by
    // renderPlacementPanel(). That element is shared with renderBossTurnPanel()
    // and renderDicePanel(), so it must be forcibly cleared here -- independent
    // of whatever any of those panel-render functions do or don't clean up --
    // whenever the phase is no longer 'placement'. Otherwise the last piece's
    // leftover instruction can persist (and stay visible) into the first turn.
    hidePlacementUiIfNotPlacementPhase() {
        if (this.state.phase === 'placement') return;
        const placementPieces = document.getElementById('placement-pieces');
        if (placementPieces) placementPieces.innerHTML = '';
    },

    renderPlacementPanel() {
        const panel = document.getElementById('dice-panel');
        panel.classList.remove('hidden');

        const diceDisplay = document.getElementById('dice-display');
        const abilityBtns = document.getElementById('placement-pieces');
        const undoBtn = document.getElementById('undo-move-btn');

        if (undoBtn) undoBtn.classList.add('hidden');

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

    renderBossTurnPanel() {
        const panel = document.getElementById('dice-panel');
        panel.classList.remove('hidden');

        const diceDisplay = document.getElementById('dice-display');
        const rollArea = document.getElementById('placement-pieces');
        const undoBtn = document.getElementById('undo-move-btn');

        if (undoBtn) undoBtn.classList.add('hidden');

        const rolls = this.state.boss_turn_rolls || { white: null, black: null };
        const bossName = this.state.active_boss || 'The Boss';

        diceDisplay.innerHTML = `
            <h3 style="color: var(--accent-red); margin-bottom: 6px;">⚔️ BOSS TURN — Roll for Direction</h3>
            <div style="font-size: 0.85rem; color: var(--text-secondary);">
                ${bossName} moves once both players have rolled.
            </div>
            <div style="font-size: 0.95rem; margin-top: 6px; font-weight: 600;">
                White: ${rolls.white ?? '—'} &nbsp;&nbsp; Black: ${rolls.black ?? '—'}
            </div>
        `;

        rollArea.innerHTML = '';
        const nextColor = rolls.white === null ? 'white' : (rolls.black === null ? 'black' : null);
        if (nextColor) {
            const btn = document.createElement('button');
            btn.className = 'btn btn-primary';
            btn.textContent = `🎲 Roll Die (${nextColor === 'white' ? 'White' : 'Black'})`;
            btn.style.cssText = 'width: 100%; margin-top: 8px;';
            btn.addEventListener('click', () => this.rollBossDie(nextColor));
            rollArea.appendChild(btn);
        }
    },

    async rollBossDie(color) {
        try {
            const resp = await fetch('/boss_roll', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ color }),
            });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.render();
            // Once both sides have rolled and the boss has moved, the phase
            // returns to 'move' for White — run the automatic turn transition.
            if (this.state.phase === 'move') {
                await this.runTurnTransition();
            }
        } catch (e) {
            this.showToast('Boss roll failed', 'fail');
        }
    },

    flashBossMovement() {
        const squares = document.querySelectorAll('.boss-square');
        squares.forEach(sq => {
            sq.classList.add('boss-square-move-flash');
            setTimeout(() => sq.classList.remove('boss-square-move-flash'), 900);
        });
    },

    renderDicePanel() {
        const panel = document.getElementById('dice-panel');
        const diceDisplay = document.getElementById('dice-display');
        const undoBtn = document.getElementById('undo-move-btn');

        // renderDicePanel() is only ever called when phase is NOT 'placement' and
        // NOT 'boss_turn' (see render()'s dispatch), so any leftover content
        // those panels wrote into the shared #placement-pieces element (e.g. a
        // Boss Turn "Roll Die" button) must be cleared here -- otherwise it
        // stays in the DOM and visible/clickable long after its phase ended.
        const rollArea = document.getElementById('placement-pieces');
        if (rollArea) rollArea.innerHTML = '';

        const isDevMode = this.state.mode === 'dev';

        // Undo Last Move — Dev Game mode only. Updated regardless of phase so
        // it's still available right after a move completes (phase becomes
        // 'move' until Start Turn is clicked), not just during the ability phase.
        if (undoBtn) {
            if (isDevMode) {
                undoBtn.classList.remove('hidden');
                undoBtn.disabled = !this.state.can_undo;
            } else {
                undoBtn.classList.add('hidden');
            }
        }

        // The panel is shown for the ability phase (dice), or -- in Dev Game
        // mode -- whenever there's a move to undo, so Undo isn't hidden along
        // with the rest of the panel between turns.
        const keepPanelForUndo = isDevMode && this.state.can_undo;
        if (this.state.phase !== 'ability' && !keepPanelForUndo) {
            panel.classList.add('hidden');
            return;
        }
        panel.classList.remove('hidden');

        if (this.state.phase !== 'ability') {
            // Nothing but Undo belongs on screen right now -- no dice rolled.
            diceDisplay.innerHTML = '';
            return;
        }

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

                // Dev Game mode only: click an unspent, non-reserved die to cycle its
                // value 1->2->...->6->1. Treated by the backend exactly like a real
                // roll (including AI summon trigger detection).
                if (isDevMode && !isUsed && !isReserved) {
                    dieEl.classList.add('die-dev-editable');
                    dieEl.title = 'DEV: click to change value';
                    dieEl.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.devCycleDie(i);
                    });
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

            if (isDevMode) {
                const devLabel = document.createElement('div');
                devLabel.className = 'dev-dice-label';
                devLabel.textContent = 'DEV: Click dice to change values';
                diceDisplay.appendChild(devLabel);
            }
        }

    },

    async devCycleDie(index) {
        try {
            const resp = await fetch('/dev/cycle_die', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ die_index: index }),
            });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.render();
        } catch (e) {
            this.showToast('Failed to override die', 'fail');
        }
    },

    async devDrawAiCard() {
        try {
            const resp = await fetch('/dev/draw_ai_card', { method: 'POST' });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.render();
        } catch (e) {
            this.showToast('Failed to draw AI card', 'fail');
        }
    },

    MAJOR_CARD_ORDER: ['Carl', 'Donut', 'Mongo', 'Katia', 'Samantha'],

    // Traditional chess piece names, shown in parentheses next to these three
    // majors wherever their name appears in the sidebars (display only).
    TRADITIONAL_MAJOR_NAMES: { Mongo: 'Knight', Katia: 'Bishop', Samantha: 'Rook' },

    majorDisplayName(name) {
        const traditional = this.TRADITIONAL_MAJOR_NAMES[name];
        return traditional ? `${name} (${traditional})` : name;
    },

    squareLabel(row, col) {
        return `${String.fromCharCode(65 + col)}${row + 1}`;
    },

    // Compute the dice a given color may currently spend on an ability: only
    // the active player has real dice to spend, and only during the ability phase.
    availableDiceForColor(color) {
        const dice = this.state.dice;
        const available = [];
        if (this.state.current_player !== color || this.state.phase !== 'ability' || !dice || !dice.values) {
            return available;
        }
        const numDice = dice.values.length;
        for (let i = 0; i < 2; i++) {
            if (i >= numDice) continue;
            const isReserved = this.targetingMode &&
                               this.targetingAbility &&
                               this.targetingAbility.dieIndex === i;
            if (!dice.used[i] && !isReserved) {
                available.push({ index: i, value: dice.values[i] });
            }
        }
        return available;
    },

    renderAbilityGridForColor(color) {
        const container = document.getElementById(`ability-grid-${color}`);
        if (!container) return;
        container.innerHTML = '';
        container.classList.add('ability-grid');
        this.renderAbilityCardGrid(container, this.availableDiceForColor(color), color);
    },

    showAbilityTooltip(anchorEl, ab, pieceLabel) {
        let tt = document.getElementById('ability-tooltip');
        if (!tt) {
            tt = document.createElement('div');
            tt.id = 'ability-tooltip';
            tt.className = 'ability-tooltip';
            document.body.appendChild(tt);
        }

        const limits = [];
        if (ab.uses_per_game) limits.push(`${ab.uses_per_game} use${ab.uses_per_game !== 1 ? 's' : ''} per game`);
        if (ab.requires_combined) limits.push('Requires combined dice');
        if (ab.is_reaction) limits.push('Reaction ability — usable on opponent\'s turn');
        if (ab.is_boss_only) limits.push('Boss Event only');

        // Juice Box acquired abilities cost +1 over the source pawn's base (Chunk 4).
        const jbTax = ab.juice_box_source_pawn ? 1 : 0;
        const baseFloor = (ab.floor || 0) + jbTax;
        const effFloor = this.effectiveFloor(baseFloor);
        const manaText = baseFloor > 0
            ? (effFloor < baseFloor ? `${effFloor} Mana (was ${baseFloor})` : `${baseFloor} Mana${jbTax ? ' (via Juice Box)' : ''}`)
            : (ab.trigger === 'floor_roll' ? '0 Mana' : 'Passive / Automatic');

        tt.innerHTML = `
            <div class="at-title">${pieceLabel} — ${ab.name}</div>
            <div class="at-mana">${manaText}</div>
            <div class="at-desc">${ab.description || ''}</div>
            ${limits.length ? `<div class="at-limits">${limits.join(' • ')}</div>` : ''}
        `;
        tt.classList.add('visible');

        const anchorRect = anchorEl.getBoundingClientRect();
        const ttRect = tt.getBoundingClientRect();
        const margin = 8;
        const boardEl = document.getElementById('board');
        const boardRect = boardEl ? boardEl.getBoundingClientRect() : null;

        const overlapsBoard = (top, left) => {
            if (!boardRect) return false;
            return left < boardRect.right && (left + ttRect.width) > boardRect.left &&
                   top < boardRect.bottom && (top + ttRect.height) > boardRect.top;
        };

        let left = anchorRect.left + (anchorRect.width / 2) - (ttRect.width / 2);
        if (left < margin) left = margin;
        if (left + ttRect.width > window.innerWidth - margin) left = window.innerWidth - ttRect.width - margin;
        left = Math.max(margin, left);

        // Prefer above the card; flip below if that would overlap the viewport top or
        // the board. Ability cards live in the side panels (beside the board) or the
        // center dice panel (below the board), so the board can sit above, below, or
        // beside the anchor depending on which panel the card is in.
        const above = anchorRect.top - ttRect.height - margin;
        const below = anchorRect.bottom + margin;

        let top;
        if (above >= margin && !overlapsBoard(above, left)) {
            top = above;
        } else if (below + ttRect.height <= window.innerHeight - margin && !overlapsBoard(below, left)) {
            top = below;
        } else if (!overlapsBoard(above, left)) {
            top = Math.max(margin, above);
        } else if (!overlapsBoard(below, left)) {
            top = Math.min(below, window.innerHeight - ttRect.height - margin);
        } else if (boardRect) {
            // Both vertical placements still overlap the board — nudge horizontally
            // fully outside it instead, keeping the tooltip near the anchor's row.
            top = Math.max(margin, Math.min(above, window.innerHeight - ttRect.height - margin));
            if (anchorRect.left < boardRect.left) {
                left = Math.max(margin, boardRect.left - ttRect.width - margin);
            } else {
                left = Math.min(window.innerWidth - ttRect.width - margin, boardRect.right + margin);
            }
        } else {
            top = Math.max(margin, above);
        }

        tt.style.top = `${top}px`;
        tt.style.left = `${left}px`;
    },

    hideAbilityTooltip() {
        const tt = document.getElementById('ability-tooltip');
        if (tt) tt.classList.remove('visible');
    },

    renderAbilityCardGrid(container, availableDice, color) {
        const pieces = this.state[`${color}_player_pieces`] || [];
        const majors = pieces.filter(pc => !pc.is_pawn);
        const pawns = pieces.filter(pc => pc.is_pawn);

        // Group majors by type name so duplicate copies (Mongo/Katia/Samantha) merge into one card
        const majorGroups = {};
        for (const pc of majors) {
            if (!majorGroups[pc.name]) majorGroups[pc.name] = [];
            majorGroups[pc.name].push(pc);
        }
        const orderedMajorNames = this.MAJOR_CARD_ORDER.filter(n => majorGroups[n]);

        const draftOrder = color === 'white' ? (this.state.white_pawns || []) : (this.state.black_pawns || []);
        const orderedPawns = [...pawns].sort((a, b) => draftOrder.indexOf(a.name) - draftOrder.indexOf(b.name));

        if (orderedMajorNames.length > 0) {
            const divider = document.createElement('div');
            divider.className = 'ability-section-divider';
            divider.textContent = 'Major Pieces';
            container.appendChild(divider);

            for (const name of orderedMajorNames) {
                const instances = majorGroups[name];
                const abilityNames = instances[0].abilities
                    .filter(ab => ab.trigger === 'floor_roll')
                    .map(ab => ab.name);
                for (const abName of abilityNames) {
                    if (name === 'Carl' && abName === 'Leader') {
                        // Leader can combine a banked die with the rolled die, which the
                        // generic combined-dice card logic below doesn't account for.
                        this.appendLeaderCard(container, instances, color);
                        continue;
                    }
                    const perInst = instances
                        .map(inst => ({ row: inst.row, col: inst.col, suppressed: inst.suppressed, ab: inst.abilities.find(a => a.name === abName) }))
                        .filter(x => x.ab);
                    if (perInst.length === 0) continue;
                    this.appendAbilityCard(container, {
                        pieceLabel: this.majorDisplayName(name),
                        allInstances: perInst,
                        ab: perInst[0].ab,
                        availableDice,
                    });
                }
            }
        }

        if (orderedPawns.length > 0) {
            const divider = document.createElement('div');
            divider.className = 'ability-section-divider';
            divider.textContent = 'Pawns';
            container.appendChild(divider);

            for (const pc of orderedPawns) {
                if (pc.name === 'Juice Box') {
                    this.appendJuiceBoxCard(container, pc, availableDice, color);
                    continue;
                }
                for (const ab of pc.abilities) {
                    if (ab.trigger !== 'floor_roll') continue;
                    this.appendAbilityCard(container, {
                        pieceLabel: pc.short || pc.name,
                        allInstances: [{ row: pc.row, col: pc.col, suppressed: pc.suppressed, ab }],
                        ab,
                        availableDice,
                    });
                }
            }
        }

        if (container.children.length === 0) {
            const msg = document.createElement('div');
            msg.style.cssText = 'color: var(--text-secondary); font-size: 0.8rem; text-align: center; padding: 8px; grid-column: 1 / -1;';
            msg.textContent = 'No pieces available';
            container.appendChild(msg);
        }
    },

    // Leader's cost isn't a fixed floor -- it's whatever dice are available
    // this turn (both rolled dice, or the banked die plus the rolled die), so
    // it needs its own eligibility check instead of the generic combined-dice path.
    appendLeaderCard(container, carlInstances, color) {
        const inst = carlInstances[0];
        const leaderAb = inst.abilities.find(ab => ab.name === 'Leader');
        if (!leaderAb) return;

        const dice = this.state.dice;
        const isActingColor = this.state.current_player === color && this.state.phase === 'ability';
        let combinedTotal = 0;
        if (isActingColor && dice && dice.values) {
            const bankedVal = dice.banked_die ? dice.banked_die[color] : null;
            const availIdx = [];
            for (let i = 0; i < dice.values.length; i++) {
                if (!dice.used[i]) availIdx.push(i);
            }
            const rolledSum = availIdx.reduce((s, i) => s + dice.values[i], 0);
            if (bankedVal !== null) {
                if (availIdx.length >= 1) combinedTotal = bankedVal + rolledSum;
            } else if (availIdx.length >= 2) {
                combinedTotal = rolledSum;
            }
        }

        const usesLeft = leaderAb.uses_left;
        const hasUses = usesLeft === null || usesLeft === undefined || usesLeft > 0;
        const eligible = !inst.suppressed && hasUses && !this.state.system_reset_active;
        const clickable = isActingColor && eligible && combinedTotal > 0;

        const card = document.createElement('div');
        card.className = `ability-card status-${clickable ? 'green' : (eligible ? 'red' : 'grey')}`;
        card.innerHTML = `
            <span class="ac-piece-name">Carl</span>
            <span class="ac-ability-name">${leaderAb.name}</span>
            <span class="ac-mana">${this.state.system_reset_active ? '🔒 System Reset' : (combinedTotal > 0 ? `⚄+⚄ Pull ${combinedTotal}` : '⚄+⚄ Combine dice')}</span>
        `;

        if (clickable) {
            card.addEventListener('click', () => this.useAbility(inst.row, inst.col, 'Leader', 0, true));
        }
        card.addEventListener('mouseenter', () => this.showAbilityTooltip(card, leaderAb, 'Carl'));
        card.addEventListener('mouseleave', () => this.hideAbilityTooltip());

        container.appendChild(card);
    },

    // This turn's ability floor cost after AI-Card / Group Climax modifiers
    // (DungeonDice.floor_modifier on the server), clamped at 0. Keeps the
    // sidebar affordability checks and "X Mana" labels in sync with the
    // server's spend_die() / can_combine_for_cost() checks.
    effectiveFloor(rawFloor) {
        const mod = (this.state && this.state.dice && typeof this.state.dice.floor_modifier === 'number')
            ? this.state.dice.floor_modifier : 0;
        return Math.max(0, (rawFloor || 0) + mod);
    },

    appendAbilityCard(container, { pieceLabel, allInstances, ab, availableDice }) {
        let status = 'red';
        let clickable = false;
        let bestDie = null;
        let useCombined = false;

        const floor = this.effectiveFloor(ab.floor);

        if (this.state.system_reset_active) {
            status = 'grey';
        } else if (ab.is_boss_only && !this.state.boss_active) {
            status = 'purple';
        } else {
            const eligible = allInstances.filter(inst =>
                !inst.suppressed && (ab.uses_per_game == null || inst.ab.uses_left === null || inst.ab.uses_left === undefined || inst.ab.uses_left > 0)
            );
            if (eligible.length === 0) {
                status = 'grey';
            } else if (availableDice.length === 0) {
                status = 'grey';
            } else if (ab.requires_combined) {
                const diceSum = availableDice.reduce((s, d) => s + d.value, 0);
                if (availableDice.length >= 2 && diceSum >= floor) {
                    status = 'green'; clickable = true; bestDie = availableDice[0]; useCombined = true;
                }
            } else {
                const single = this.findBestDie(availableDice, floor);
                if (single !== null && single.value >= floor) {
                    status = 'green'; clickable = true; bestDie = single;
                } else if (availableDice.length >= 2) {
                    const diceSum = availableDice.reduce((s, d) => s + d.value, 0);
                    if (diceSum >= floor) {
                        status = 'green'; clickable = true; bestDie = availableDice[0]; useCombined = true;
                    }
                }
            }
        }

        const card = document.createElement('div');
        card.className = `ability-card status-${status}`;

        const abLabel = ab.juice_box_source_pawn ? `${ab.name} (${ab.juice_box_source_pawn})` : ab.name;
        const discounted = floor < (ab.floor || 0);
        const manaLabel = this.state.system_reset_active
            ? '🔒 System Reset'
            : (ab.is_boss_only && !this.state.boss_active)
                ? '🔒 Boss Event Only'
                : `${(ab.requires_combined || useCombined) ? '⚄+⚄ ' : ''}${floor} Mana${discounted ? ' ▼' : ''}`;

        card.innerHTML = `
            <span class="ac-piece-name">${pieceLabel}</span>
            <span class="ac-ability-name">${abLabel}</span>
            <span class="ac-mana">${manaLabel}</span>
        `;

        if (allInstances.length > 1) {
            const badge = document.createElement('span');
            badge.className = 'ac-x2-badge';
            badge.textContent = 'x2';
            card.appendChild(badge);
        }

        if (clickable) {
            card.addEventListener('click', () => {
                if (allInstances.length > 1) {
                    this.showCopySelectPopover(card, allInstances, ab.name, bestDie.index, useCombined);
                } else {
                    this.useAbility(allInstances[0].row, allInstances[0].col, ab.name, bestDie.index, useCombined);
                }
            });
        }

        card.addEventListener('mouseenter', () => this.showAbilityTooltip(card, ab, pieceLabel));
        card.addEventListener('mouseleave', () => this.hideAbilityTooltip());

        container.appendChild(card);
    },

    showCopySelectPopover(anchorEl, instances, abilityName, dieIndex, useCombined) {
        const existing = document.getElementById('copy-select-popover');
        if (existing) existing.remove();

        const popover = document.createElement('div');
        popover.id = 'copy-select-popover';
        popover.className = 'copy-select-popover';

        const title = document.createElement('div');
        title.className = 'csp-title';
        title.textContent = 'Choose which copy';
        popover.appendChild(title);

        for (const inst of instances) {
            const btn = document.createElement('button');
            btn.textContent = `Copy at ${this.squareLabel(inst.row, inst.col)}`;
            btn.addEventListener('click', () => {
                popover.remove();
                this.useAbility(inst.row, inst.col, abilityName, dieIndex, useCombined);
            });
            popover.appendChild(btn);
        }

        const cancelBtn = document.createElement('button');
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => popover.remove());
        popover.appendChild(cancelBtn);

        document.body.appendChild(popover);

        const rect = anchorEl.getBoundingClientRect();
        const popRect = popover.getBoundingClientRect();
        let top = rect.bottom + 6;
        let left = rect.left;
        if (left + popRect.width > window.innerWidth - 8) left = window.innerWidth - popRect.width - 8;
        if (top + popRect.height > window.innerHeight - 8) top = rect.top - popRect.height - 6;
        popover.style.top = `${Math.max(8, top)}px`;
        popover.style.left = `${Math.max(8, left)}px`;

        const dismiss = (e) => {
            if (!popover.contains(e.target) && e.target !== anchorEl) {
                popover.remove();
                document.removeEventListener('click', dismiss);
            }
        };
        setTimeout(() => document.addEventListener('click', dismiss), 0);
    },

    appendJuiceBoxCard(container, pc, availableDice, color) {
        const onCooldown = !!(this.state.juice_box_cooldown || {})[color];

        const card = document.createElement('div');
        card.className = 'ability-card status-grey';
        card.style.cursor = 'default';

        card.innerHTML = `
            <span class="ac-piece-name">${pc.short || pc.name}</span>
            <span class="ac-ability-name">Shapeshift</span>
            <span class="ac-mana">${onCooldown ? 'Cooldown — 1 turn' : 'Select an acquired ability below'}</span>
        `;

        const jbBaseAbility = this.roster.find(p => p.name === 'Juice Box');
        if (jbBaseAbility) {
            const shapeshiftAb = {
                name: jbBaseAbility.ability_name,
                floor: jbBaseAbility.floor_number,
                description: jbBaseAbility.ability_description,
                trigger: jbBaseAbility.trigger,
                uses_per_game: jbBaseAbility.uses_per_game,
                requires_combined: false,
                is_reaction: false,
                is_boss_only: false,
            };
            card.addEventListener('mouseenter', () => this.showAbilityTooltip(card, shapeshiftAb, pc.name));
            card.addEventListener('mouseleave', () => this.hideAbilityTooltip());
        }

        const subpanel = document.createElement('details');
        subpanel.className = 'juice-box-subpanel';

        const summary = document.createElement('summary');
        summary.textContent = `Acquired Abilities (${pc.abilities.length})`;
        subpanel.appendChild(summary);

        if (pc.abilities.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'jb-empty';
            empty.textContent = 'No abilities acquired yet.';
            subpanel.appendChild(empty);
        } else {
            for (const ab of pc.abilities) {
                const entry = document.createElement('div');
                entry.className = 'jb-entry';

                // Chunk 4 balance: acquired abilities cost Juice Box 1 more than
                // the source pawn's base cost, then AI-Card / Group Climax
                // modifiers apply on top (matches the server-side +1 bump).
                const jbFloor = this.effectiveFloor(ab.floor + 1);

                let status = 'grey';
                let bestDie = null;
                let useCombined = false;
                if (!onCooldown && !this.state.system_reset_active && !pc.suppressed && availableDice.length > 0) {
                    const single = this.findBestDie(availableDice, jbFloor);
                    if (single !== null && single.value >= jbFloor) {
                        status = 'green'; bestDie = single;
                    } else if (availableDice.length >= 2) {
                        const diceSum = availableDice.reduce((s, d) => s + d.value, 0);
                        if (diceSum >= jbFloor) {
                            status = 'green'; bestDie = availableDice[0]; useCombined = true;
                        } else {
                            status = 'red';
                        }
                    } else {
                        status = 'red';
                    }
                }

                const manaCell = this.state.system_reset_active
                    ? '🔒 System Reset'
                    : onCooldown
                        ? 'Cooldown — 1 turn'
                        : `${jbFloor} Mana (via Juice Box)`;
                entry.innerHTML = `
                    <span>${ab.juice_box_source_pawn} — ${ab.name}</span>
                    <span>${manaCell}</span>
                `;
                entry.style.borderLeft = `3px solid var(--${status === 'green' ? 'success' : status === 'red' ? 'danger' : 'text-dim'})`;

                if (status === 'green') {
                    entry.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.useAbility(pc.row, pc.col, ab.name, bestDie.index, useCombined);
                    });
                }

                entry.addEventListener('mouseenter', (e) => {
                    e.stopPropagation();
                    this.showAbilityTooltip(entry, ab, ab.juice_box_source_pawn);
                });
                entry.addEventListener('mouseleave', (e) => {
                    e.stopPropagation();
                    this.hideAbilityTooltip();
                });

                subpanel.appendChild(entry);
            }
        }

        card.appendChild(subpanel);
        container.appendChild(card);
    },

    findBestDie(availableDice, floor) {
        // Find lowest die that meets floor, or lowest overall if none meet
        const sorted = [...availableDice].sort((a, b) => a.value - b.value);
        for (const d of sorted) {
            if (d.value >= floor) return d;
        }
        return sorted.length > 0 ? sorted[0] : null;
    },

    DUPLICABLE_MAJORS: new Set(['Mongo', 'Katia', 'Samantha']),

    renderSidebar(color) {
        const list = document.getElementById(`piece-list-${color}`);
        if (!list) return;

        const pieces = this.state[`${color}_player_pieces`] || [];
        list.innerHTML = '';

        // Merge duplicate major-piece copies (Mongo/Katia/Samantha) into one entry
        const grouped = [];
        const seenMajorNames = new Set();
        for (const pc of pieces) {
            if (!pc.is_pawn && this.DUPLICABLE_MAJORS.has(pc.name)) {
                if (seenMajorNames.has(pc.name)) continue;
                seenMajorNames.add(pc.name);
                const copies = pieces.filter(p => !p.is_pawn && p.name === pc.name);
                grouped.push({ ...pc, _copyCount: copies.length, _instances: copies });
            } else {
                grouped.push({ ...pc, _copyCount: 1, _instances: [pc] });
            }
        }

        // Sort: major pieces first, then pawns
        const sorted = [...grouped].sort((a, b) => {
            if (a.is_pawn && !b.is_pawn) return 1;
            if (!a.is_pawn && b.is_pawn) return -1;
            return 0;
        });

        for (const pc of sorted) {
            const card = document.createElement('div');
            card.className = `piece-card ${pc.suppressed ? 'suppressed' : ''}`;

            let abHtml = '';
            if (pc.name === 'Juice Box') {
                const count = pc.abilities.length;
                let entries = '';
                if (count === 0) {
                    entries = `<div class="pc-ability">No abilities acquired yet.</div>`;
                } else {
                    for (const ab of pc.abilities) {
                        // Juice Box pays +1 over the source pawn's base cost (Chunk 4).
                        const floorText = ab.floor > 0 ? `${ab.floor + 1} Mana (via Juice Box)` : 'Auto';
                        entries += `
                            <div class="pc-ability">
                                <span class="ab-label">${ab.juice_box_source_pawn} — ${ab.name}</span>
                                <span class="floor-num">${floorText}</span>
                                <br><span>${ab.description}</span>
                            </div>
                        `;
                    }
                }
                abHtml = `
                    <details class="juice-box-abilities" ${count > 0 ? 'open' : ''}>
                        <summary>Acquired Abilities (${count})</summary>
                        ${entries}
                    </details>
                `;
            } else {
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
            }

            const x2Badge = pc._copyCount > 1 ? '<span class="pc-x2-badge">x2</span>' : '';
            card.innerHTML = `
                <div class="pc-header">
                    <span class="pc-name">${this.majorDisplayName(pc.name)}${x2Badge}</span>
                    <span class="pc-type">${pc.type}${pc.suppressed ? ' (Suppressed)' : ''}</span>
                </div>
                ${abHtml}
            `;

            card.addEventListener('click', () => {
                // Clicking a sidebar piece selects it on the board (first copy, if merged)
                const target = pc._instances[0];
                this.handleSquareClick(target.row, target.col);
            });

            list.appendChild(card);
        }
    },

    renderStatusEffectsForColor(color) {
        const container = document.getElementById(`status-effects-${color}`);
        if (!container) return;
        container.innerHTML = '';

        const effects = this.state.status_effects || { white: [], black: [] };
        const entries = effects[color] || [];

        if (entries.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'status-effects-empty';
            empty.textContent = 'No active effects';
            container.appendChild(empty);
        } else {
            for (const eff of entries) {
                const row = document.createElement('div');
                row.className = 'status-effect-entry';
                const turnsText = eff.turns === null || eff.turns === undefined
                    ? ''
                    : `${eff.turns} turn${eff.turns !== 1 ? 's' : ''} left`;
                row.innerHTML = `
                    <span class="se-label"><span class="se-piece">${this.majorDisplayName(eff.piece)}</span> — ${eff.effect}</span>
                    <span class="se-turns">${turnsText}</span>
                `;
                container.appendChild(row);
            }
        }
    },

    renderCapturedPiecesForColor(color) {
        const container = document.getElementById(`captured-pieces-${color}`);
        if (!container) return;
        container.innerHTML = '';

        const captured = this.state.captured_pieces || { white: [], black: [] };
        const entries = captured[color] || [];

        if (entries.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'captured-empty';
            empty.textContent = 'No captured pieces';
            container.appendChild(empty);
        } else {
            const tagsDiv = document.createElement('div');
            tagsDiv.className = 'captured-tags';
            for (const piece of entries) {
                const tag = document.createElement('span');
                tag.className = 'captured-tag' + (piece.permanently_dead ? ' permanently-dead' : '');
                const label = this.majorDisplayName(piece.name);
                tag.textContent = piece.permanently_dead ? `${label} ☠` : label;
                tagsDiv.appendChild(tag);
            }
            container.appendChild(tagsDiv);
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
            if (this.state.result_reason === 'stalemate') {
                msg.textContent = 'Stalemate — no legal moves';
            } else if (this.state.result_reason === 'both_fallen') {
                msg.textContent = 'Both players have fallen — the boss remains undefeated.';
            } else {
                msg.textContent = `Draw: ${this.state.result_reason}`;
            }
        }
    },

    // ═══ BOARD INTERACTION ═══

    async handleSquareClick(row, col) {
        if (!this.state || this.state.game_over) return;
        // Ignore board clicks while an automatic turn transition is running.
        if (this._transitioning) return;

        // Handle targeting mode - player is selecting a target
        if (this.targetingMode) {
            const abilityName = this.targetingAbility ? this.targetingAbility.abilityName : null;
            if (abilityName === 'Air Strike' || abilityName === 'Lava Spit') {
                await this.handleZoneClick(row, col);
            } else if (abilityName === 'Lava Surge') {
                // Direction is chosen via the Horizontal/Vertical panel buttons, not board clicks
            } else if (abilityName === 'Leader') {
                await this.handleLeaderClick(row, col);
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

        // If clicking a piece you currently control, select it (even if another
        // piece is already selected). During a Matt's Drunk Again swap this is the
        // OPPONENT's true color, not current_player -- see controlledColor().
        if (piece && piece.color === this.controlledColor()) {
            // Orthrus is one logical piece across 2 squares -- clicking either
            // his head or butt square always selects him via his head, since
            // that's the only square his moves/rotations are generated from.
            let selRow = row, selCol = col;
            if (piece.name === 'Orthrus' && !piece.is_orthrus_head && piece.orthrus_head_pos) {
                [selRow, selCol] = piece.orthrus_head_pos;
            }
            this.selectedSquare = { row: selRow, col: selCol };
            await this.fetchLegalMoves(selRow, selCol);
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
            // When the last piece is placed the game enters the move phase for
            // White — kick off the automatic first-turn transition.
            if (this.state.phase === 'move' && !this.state.game_over) {
                await this.runTurnTransition();
            }
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

            if (data.pending_elle_decision) {
                // Capture is paused -- Elle's owner must decide whether to spend
                // her once-per-game Frozen Immunity before the move completes.
                this._pendingElleMove = { fromRow, fromCol, toRow, toCol };
                this.render();
                this.showElleDecisionPrompt();
                return;
            }

            this.lastMoveFrom = [fromRow, fromCol];
            this.lastMoveTo = [toRow, toCol];
            this.render();
            // The move ended the turn on the backend — run the automatic transition.
            await this.runTurnTransition();
        } catch (e) {
            this.showToast('Move failed', 'fail');
        }
    },

    showElleDecisionPrompt() {
        const existing = document.getElementById('elle-decision-prompt');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'elle-decision-prompt';
        overlay.className = 'overlay';

        const content = document.createElement('div');
        content.className = 'overlay-content';

        const title = document.createElement('h2');
        title.textContent = '⚡ Elle McGib — Frozen Immunity';

        const msg = document.createElement('p');
        msg.textContent = 'Automatically prevent this capture attempt?';

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'display: flex; gap: 12px; justify-content: center;';

        const yesBtn = document.createElement('button');
        yesBtn.className = 'btn btn-primary';
        yesBtn.textContent = 'YES';
        yesBtn.addEventListener('click', () => this.resolveElleDecision(true));

        const noBtn = document.createElement('button');
        noBtn.className = 'btn btn-secondary';
        noBtn.textContent = 'NO';
        noBtn.addEventListener('click', () => this.resolveElleDecision(false));

        btnRow.appendChild(yesBtn);
        btnRow.appendChild(noBtn);

        content.appendChild(title);
        content.appendChild(msg);
        content.appendChild(btnRow);
        overlay.appendChild(content);
        document.body.appendChild(overlay);
    },

    async resolveElleDecision(useImmunity) {
        const prompt = document.getElementById('elle-decision-prompt');
        if (prompt) prompt.remove();

        const pendingMove = this._pendingElleMove;
        this._pendingElleMove = null;

        try {
            const resp = await fetch('/resolve_elle_decision', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ use_immunity: useImmunity }),
            });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            this.selectedSquare = null;
            this.legalMoves = [];
            if (pendingMove) {
                this.lastMoveFrom = [pendingMove.fromRow, pendingMove.fromCol];
                this.lastMoveTo = [pendingMove.toRow, pendingMove.toCol];
            }
            this.render();
            this.showToast(
                useImmunity ? "Frozen Immunity negated the capture!" : 'Capture proceeds — immunity held in reserve',
                useImmunity ? 'success' : ''
            );
            // Resolving the Elle decision completes the move, which ended the turn.
            await this.runTurnTransition();
        } catch (e) {
            this.showToast('Failed to resolve decision', 'fail');
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
            'Plot Armor': 'movement',
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
            // Direction-toggle abilities
            'Lava Surge': 'direction',
            // Two-stage pull ability (select piece, then destination)
            'Leader': 'leader_pull',
            // Special Event Attacks (boss battles only) -- click any square in range
            'Jug-o-Boom': 'movement',
            'Magic Missile': 'movement',
            'Gorefest': 'movement',
            // 'I Need My Space' and 'IWKYM' fire immediately, no targeting
        };

        const targetingType = targetingAbilities[abilityName];

        if (targetingType === 'direction') {
            await this.enterDirectionTargeting(pieceRow, pieceCol, abilityName, dieIndex, useCombined);
        } else if (targetingType === 'leader_pull') {
            await this.enterLeaderTargeting(pieceRow, pieceCol, dieIndex, useCombined);
        } else if (targetingType) {
            // Enter targeting mode - fetch valid targets from backend
            await this.enterTargetingMode(pieceRow, pieceCol, abilityName, dieIndex, targetingType, useCombined);
        } else {
            // Execute ability directly (no targeting needed)
            await this.executeAbility(pieceRow, pieceCol, abilityName, dieIndex, null, useCombined);
        }
    },

    async enterDirectionTargeting(pieceRow, pieceCol, abilityName, dieIndex, useCombined = false) {
        try {
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

            this.targetingMode = true;
            this.targetingAbility = {
                pieceRow,
                pieceCol,
                abilityName,
                dieIndex,
                targetingType: 'direction',
                useCombined,
                directionOptions: data.direction_options || {},
                selectedDirection: null,
            };

            this.showDirectionTargetingUI();
            this.renderBoard();
        } catch (e) {
            console.error('Failed to enter direction targeting:', e);
            this.showToast('Failed to get valid directions', 'fail');
        }
    },

    showDirectionTargetingUI() {
        const existing = document.getElementById('targeting-ui');
        if (existing) existing.remove();

        const ta = this.targetingAbility;
        const opts = ta.directionOptions || {};

        const ui = document.createElement('div');
        ui.id = 'targeting-ui';
        ui.className = 'targeting-ui-docked';

        const title = document.createElement('div');
        title.className = 'targeting-ui-title';
        title.textContent = ta.abilityName;

        const message = document.createElement('div');
        message.className = 'targeting-ui-msg';
        message.textContent = 'Choose lava direction';

        ui.appendChild(title);
        ui.appendChild(message);

        const dirRow = document.createElement('div');
        dirRow.style.cssText = 'display: flex; gap: 8px; margin: 8px 0;';

        [['horizontal', 'Horizontal'], ['vertical', 'Vertical']].forEach(([dir, label]) => {
            const opt = opts[dir];
            const btn = document.createElement('button');
            btn.textContent = label;
            btn.className = 'btn btn-secondary';
            btn.style.cssText = 'flex: 1; padding: 6px 10px; font-size: 0.78rem;';
            if (!opt || !opt.valid) {
                btn.disabled = true;
                btn.style.opacity = '0.4';
                btn.style.cursor = 'not-allowed';
            } else {
                if (ta.selectedDirection === dir) {
                    btn.style.border = '2px solid var(--accent-gold)';
                }
                btn.addEventListener('click', () => {
                    this.targetingAbility.selectedDirection = dir;
                    this.showDirectionTargetingUI();
                    this.renderBoard();
                });
            }
            dirRow.appendChild(btn);
        });
        ui.appendChild(dirRow);

        const actionRow = document.createElement('div');
        actionRow.style.cssText = 'display: flex; gap: 8px;';

        const confirmBtn = document.createElement('button');
        confirmBtn.textContent = 'Confirm';
        confirmBtn.className = 'btn btn-primary';
        confirmBtn.style.cssText = 'flex: 1; padding: 6px 10px; font-size: 0.78rem;';
        confirmBtn.disabled = !ta.selectedDirection;
        confirmBtn.addEventListener('click', () => this.confirmDirectionTargeting());

        const cancelBtn = document.createElement('button');
        cancelBtn.textContent = 'Cancel';
        cancelBtn.className = 'btn btn-secondary';
        cancelBtn.style.cssText = 'flex: 1; padding: 6px 10px; font-size: 0.78rem;';
        cancelBtn.addEventListener('click', () => this.cancelTargeting());

        actionRow.appendChild(confirmBtn);
        actionRow.appendChild(cancelBtn);
        ui.appendChild(actionRow);

        const dicePanel = document.getElementById('dice-panel');
        if (dicePanel) {
            dicePanel.classList.remove('hidden');
            dicePanel.prepend(ui);
        } else {
            document.body.appendChild(ui);
        }
    },

    async confirmDirectionTargeting() {
        const ta = this.targetingAbility;
        if (!ta || !ta.selectedDirection) return;
        await this.executeAbility(
            ta.pieceRow, ta.pieceCol, ta.abilityName, ta.dieIndex,
            null, ta.useCombined, ta.selectedDirection
        );
        this.exitTargetingMode();
    },

    getDirectionPreviewSquares() {
        const ta = this.targetingAbility;
        if (!ta || !ta.selectedDirection) return [];
        const opt = ta.directionOptions && ta.directionOptions[ta.selectedDirection];
        return opt ? opt.squares : [];
    },

    // ═══ LEADER (two-stage: pick piece to pull, then destination) ═══

    async enterLeaderTargeting(carlRow, carlCol, dieIndex, useCombined) {
        try {
            const resp = await fetch('/ability/get_targets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    piece_row: carlRow,
                    piece_col: carlCol,
                    ability_name: 'Leader',
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
                this.showToast('No eligible piece can be pulled right now', 'fail');
                return;
            }

            this.targetingMode = true;
            this.targetingAbility = {
                pieceRow: carlRow,
                pieceCol: carlCol,
                abilityName: 'Leader',
                dieIndex,
                useCombined,
                targetingType: 'leader_pull',
                stage: 'piece',
                pulledPiece: null,
                combinedTotal: data.combined_total,
            };
            this.validTargets = data.valid_targets;
            this.targetingMessage = data.message || `Combined total: ${data.combined_total}. Select a friendly piece to pull.`;

            this.showTargetingUI();
            this.renderBoard();
        } catch (e) {
            console.error('Failed to enter Leader targeting:', e);
            this.showToast('Failed to get Leader targets', 'fail');
        }
    },

    async handleLeaderClick(row, col) {
        const ta = this.targetingAbility;
        const isValid = this.validTargets.some(t => t[0] === row && t[1] === col);
        if (!isValid) {
            this.showToast('Invalid target - click a highlighted square', 'fail');
            return;
        }

        if (ta.stage === 'piece') {
            try {
                const resp = await fetch('/ability/get_targets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        piece_row: ta.pieceRow,
                        piece_col: ta.pieceCol,
                        ability_name: 'Leader',
                        die_index: ta.dieIndex,
                        use_combined: ta.useCombined,
                        pulled_piece: [row, col],
                    }),
                });
                const data = await resp.json();
                if (data.error) {
                    this.showToast(data.error, 'fail');
                    return;
                }
                if (!data.valid_targets || data.valid_targets.length === 0) {
                    this.showToast('That piece has no valid path toward Carl', 'fail');
                    return;
                }
                ta.stage = 'destination';
                ta.pulledPiece = [row, col];
                this.validTargets = data.valid_targets;
                this.targetingMessage = data.message || 'Select destination';
                this.showTargetingUI();
                this.renderBoard();
            } catch (e) {
                this.showToast('Failed to get Leader destinations', 'fail');
            }
            return;
        }

        // stage === 'destination'
        await this.executeLeaderAbility(row, col);
        this.exitTargetingMode();
    },

    async executeLeaderAbility(destRow, destCol) {
        const ta = this.targetingAbility;
        try {
            const resp = await fetch('/ability', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    piece_row: ta.pieceRow,
                    piece_col: ta.pieceCol,
                    ability_name: 'Leader',
                    die_index: ta.dieIndex,
                    use_combined: ta.useCombined,
                    pulled_piece: ta.pulledPiece,
                    target_row: destRow,
                    target_col: destCol,
                }),
            });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return;
            }
            this.state = data;
            const result = data.ability_result;
            if (result) {
                this.showToast(`Leader: ${result.message}`, result.success ? 'success' : 'fail');
            }
            this.render();
        } catch (e) {
            this.showToast('Leader ability failed', 'fail');
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

    async executeAbility(pieceRow, pieceCol, abilityName, dieIndex, target, useCombined = false, direction = null) {
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
            if (direction) {
                payload.direction = direction;
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

    // Brief centered banner announcing whose turn it is (or "Boss Turn").
    // `cls` is 'white' | 'black' | 'boss'. Resolves after ~1s.
    showTurnBanner(text, cls) {
        return new Promise((resolve) => {
            document.getElementById('turn-transition-banner')?.remove();
            const b = document.createElement('div');
            b.id = 'turn-transition-banner';
            b.className = `turn-transition-banner ${cls}`;
            b.textContent = text;
            document.body.appendChild(b);
            setTimeout(() => { b.remove(); resolve(); }, 1000);
        });
    },

    // Automatic turn transition. Invoked after a move ends the turn (the
    // backend has already advanced current_player and set phase to 'move',
    // or 'boss_turn' when a boss is active). Shows the transition banner,
    // then either plays the AI's turn (PvAI) or auto-rolls the dice for the
    // next human player and drops straight into their ability phase.
    async runTurnTransition() {
        if (this._transitioning) return;
        this._transitioning = true;
        try {
            while (true) {
                if (!this.state || this.state.game_over) return;
                const phase = this.state.phase;

                if (phase === 'boss_turn') {
                    // Boss Turn happens between Black ending and White starting.
                    // Show the red banner; the compass-roll prompts live in the
                    // boss turn panel. rollBossDie() re-enters this transition
                    // once both sides have rolled and phase flips back to 'move'.
                    await this.showTurnBanner('Boss Turn', 'boss');
                    this.render();
                    return;
                }

                if (phase !== 'move') return;  // already in ability/placement — nothing to do

                const cur = this.state.current_player;

                if (this.mode === 'pvai' && cur === 'black') {
                    await this.showTurnBanner('AI is thinking…', 'black');
                    const ok = await this.playAiTurn();
                    if (!ok) return;
                    continue;  // AI turn done → loop: White's move phase, or another boss turn
                }

                await this.showTurnBanner(cur === 'white' ? "White's Turn" : "Black's Turn", cur);
                await this.startTurn();  // banked-die prompt (if any) → /start_turn → ability phase

                // Boss co-op safety net: a fallen player with no pieces left cannot
                // move and there is no longer an End Turn button — auto-pass so the
                // game does not soft-lock.
                if (this.state && !this.state.game_over && this.state.phase === 'ability'
                    && this.state.boss_active
                    && (this.state.fallen_players || []).includes(this.state.current_player)
                    && (this.state.player_pieces || []).length === 0) {
                    try {
                        const resp = await fetch('/end_turn', { method: 'POST' });
                        const data = await resp.json();
                        if (!data.error) { this.state = data; this.render(); continue; }
                    } catch (e) { /* leave as-is */ }
                }
                return;
            }
        } finally {
            this._transitioning = false;
        }
    },

    async playAiTurn() {
        try {
            const resp = await fetch('/ai_turn', { method: 'POST' });
            const data = await resp.json();
            if (data.error) {
                this.showToast(data.error, 'fail');
                return false;
            }
            this.state = data;
            const aiMoves = (data.events || []).filter(e => e.type === 'ai_move');
            if (aiMoves.length) {
                const last = aiMoves[aiMoves.length - 1];
                if (last.from_pos && last.to_pos) {
                    this.lastMoveFrom = last.from_pos;
                    this.lastMoveTo = last.to_pos;
                }
            }
            this.render();
            return true;
        } catch (e) {
            this.showToast('AI turn failed', 'fail');
            return false;
        }
    },

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

    async undoMove() {
        try {
            const resp = await fetch('/undo_move', { method: 'POST' });
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
            this._pendingElleMove = null;
            const ellePrompt = document.getElementById('elle-decision-prompt');
            if (ellePrompt) ellePrompt.remove();
            this.render();
            this.showToast('Move undone', 'success');
        } catch (e) {
            this.showToast('Undo failed', 'fail');
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
            ? this.normalizeOrthrusInGrid(this.devSettings.boardLayout)
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

                    if (pawnName === 'Orthrus') {
                        const spot = this.findOrthrusPlacement(color, pawnRow);
                        if (spot) {
                            const [br, bc] = spot;
                            const cells = this.makeOrthrusCells(color, br, bc, short);
                            this.devStagingGrid[cells.buttRow][cells.buttCol] = cells.buttCell;
                            this.devStagingGrid[cells.headRow][cells.headCol] = cells.headCell;
                        }
                        this.renderDevSettings();
                        return;
                    }

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

    // Orthrus is a 1×2 piece: his head sits one square from his butt, in the
    // direction his side normally faces (matching Board.place_orthrus_body).
    ORTHRUS_HEAD_DELTA: { white: [1, 0], black: [-1, 0] },

    findOrthrusPlacement(color, preferRow) {
        const [dr, dc] = this.ORTHRUS_HEAD_DELTA[color];
        const tryRow = (r, cols) => {
            for (const c of cols) {
                const hr = r + dr, hc = c + dc;
                if (hr < 0 || hr > 10 || hc < 0 || hc > 10) continue;
                if (!this.devStagingGrid[r][c] && !this.devStagingGrid[hr][hc]) {
                    return [r, c];
                }
            }
            return null;
        };
        const preferredCols = Array.from({ length: 8 }, (_, i) => i + 1);
        let spot = tryRow(preferRow, preferredCols);
        if (spot) return spot;
        const allCols = Array.from({ length: 11 }, (_, i) => i);
        for (let r = 0; r < 11; r++) {
            spot = tryRow(r, allCols);
            if (spot) return spot;
        }
        return null;
    },

    makeOrthrusCells(color, buttRow, buttCol, short) {
        const [dr, dc] = this.ORTHRUS_HEAD_DELTA[color];
        const headRow = buttRow + dr, headCol = buttCol + dc;
        const direction = color === 'white' ? 'up' : 'down';
        const buttCell = {
            type: 'Pawn', color, name: 'Orthrus', is_pawn: true, short,
            is_orthrus_head: false, orthrus_direction: null, orthrus_head_pos: [headRow, headCol],
        };
        const headCell = {
            type: 'Pawn', color, name: 'Orthrus', is_pawn: true, short,
            is_orthrus_head: true, orthrus_direction: direction, orthrus_head_pos: [headRow, headCol],
        };
        return { buttRow, buttCol, headRow, headCol, buttCell, headCell };
    },

    // Repair any Orthrus cell saved before the 2-cell head/butt staging format
    // existed (a lone flat pawn with no orthrus_head_pos) into a proper 1x2
    // body. Without this, a board layout saved by an older version of this
    // page stays a permanent 1x1 Orthrus forever, since openDevSettings()
    // otherwise loads a saved layout as-is.
    normalizeOrthrusInGrid(grid) {
        if (!grid) return grid;
        for (let r = 0; r < 11; r++) {
            for (let c = 0; c < 11; c++) {
                const cell = grid[r][c];
                if (!(cell && cell.is_pawn && cell.name === 'Orthrus' && !cell.orthrus_head_pos)) continue;

                const [dr, dc] = this.ORTHRUS_HEAD_DELTA[cell.color];
                const hr = r + dr, hc = c + dc;
                let buttRow = r, buttCol = c;
                if (hr < 0 || hr > 10 || hc < 0 || hc > 10 || grid[hr][hc]) {
                    // No room for his head next to the saved square -- search for any valid spot.
                    grid[r][c] = null;
                    const savedGrid = this.devStagingGrid;
                    this.devStagingGrid = grid;
                    const spot = this.findOrthrusPlacement(cell.color, r);
                    this.devStagingGrid = savedGrid;
                    if (!spot) continue; // nowhere to place him -- leave as-is (rare edge case)
                    [buttRow, buttCol] = spot;
                }
                const cells = this.makeOrthrusCells(cell.color, buttRow, buttCol, cell.short || 'ORTH');
                grid[cells.buttRow][cells.buttCol] = cells.buttCell;
                grid[cells.headRow][cells.headCol] = cells.headCell;
            }
        }
        return grid;
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
                if (this.devSettings && this.devSettings.boardLayout) {
                    this.normalizeOrthrusInGrid(this.devSettings.boardLayout);
                }
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
                    pieceEl.textContent = this.pieceLabel(piece);
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
                const selPiece = this.devStagingGrid[selRow][selCol];
                if (selPiece && selPiece.is_pawn && selPiece.name === 'Orthrus') {
                    // Move his whole 1×2 body together so his head stays attached
                    this.moveOrthrusInStaging(selRow, selCol, row, col);
                } else {
                    const targetPiece = this.devStagingGrid[row][col];
                    // Don't drop a different piece onto one of Orthrus's squares --
                    // that would split his body without moving the other half.
                    if (!targetPiece || targetPiece.name !== 'Orthrus' || !targetPiece.is_pawn) {
                        this.devStagingGrid[row][col] = selPiece;
                        this.devStagingGrid[selRow][selCol] = targetPiece;
                    }
                }
                this.devStagingSelected = null;
            }
            this.renderDevStagingBoard();
        } else {
            const piece = this.devStagingGrid[row][col];
            if (piece) {
                // Either half of Orthrus always selects/anchors on his butt square
                let selRow = row, selCol = col;
                if (piece.is_pawn && piece.name === 'Orthrus' && piece.is_orthrus_head) {
                    const [dr, dc] = this.ORTHRUS_HEAD_DELTA[piece.color];
                    selRow = row - dr;
                    selCol = col - dc;
                }
                this.devStagingSelected = [selRow, selCol];
                this.renderDevStagingBoard();
            }
        }
    },

    moveOrthrusInStaging(buttRow, buttCol, destRow, destCol) {
        const buttCell = this.devStagingGrid[buttRow][buttCol];
        const [dr, dc] = this.ORTHRUS_HEAD_DELTA[buttCell.color];
        const oldHeadRow = buttRow + dr, oldHeadCol = buttCol + dc;
        const newHeadRow = destRow + dr, newHeadCol = destCol + dc;

        if (newHeadRow < 0 || newHeadRow > 10 || newHeadCol < 0 || newHeadCol > 10) return;

        // Only move if both destination squares are empty (or are his own
        // current squares) -- keeps his 2-square body from overlapping others.
        const isOwnSquare = (r, c) => (r === buttRow && c === buttCol) || (r === oldHeadRow && c === oldHeadCol);
        const destButtFree = !this.devStagingGrid[destRow][destCol] || isOwnSquare(destRow, destCol);
        const destHeadFree = !this.devStagingGrid[newHeadRow][newHeadCol] || isOwnSquare(newHeadRow, newHeadCol);
        if (!destButtFree || !destHeadFree) return;

        const cells = this.makeOrthrusCells(buttCell.color, destRow, destCol, buttCell.short);
        this.devStagingGrid[buttRow][buttCol] = null;
        this.devStagingGrid[oldHeadRow][oldHeadCol] = null;
        this.devStagingGrid[cells.buttRow][cells.buttCol] = cells.buttCell;
        this.devStagingGrid[cells.headRow][cells.headCol] = cells.headCell;
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
