#!/usr/bin/env python3
"""Build the Dungeon Crawler Chess game overview PDF.

    python3 tools/build_overview_pdf.py                    # writes static/DCC-Chess-Overview.pdf
    python3 tools/build_overview_pdf.py ~/Desktop/x.pdf    # ...and also copies it to each extra path

Re-run this whenever the game changes. Names, costs, use limits, the AI card
list, boss HP and boss movement are read straight from the game code
(dcc_chess/ and app.py's MAJOR_ABILITIES), so they can't drift. The short
plain-English descriptions live in this file -- the code's own description
strings are player-facing flavor text and some are out of date (see
DESIGN.md) -- and the build stops with an error if a pawn, major-piece
ability, AI card, or boss exists in the code without one here.

Needs reportlab and Pillow.
"""

import io
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image as PILImage
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, Image, KeepTogether, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.flowables import HRFlowable

from app import MAJOR_ABILITIES
from dcc_chess.ai_cards import AI_CARD_NAMES, SUMMON_CARD_BOSS_TYPES, _BOSS_MAX_HP
from dcc_chess.board import BOARD_SIZE
from dcc_chess.boss import BOSS_MOVE_DISTANCE
from dcc_chess.dice import is_ai_summon_roll
from dcc_chess.pawns import PAWN_CHARACTERS, AbilityTrigger

OUTPUT = os.path.join(ROOT, "static", "DCC-Chess-Overview.pdf")
LOGO = os.path.join(ROOT, "static", "DCC-logo-realistic.webp")
SITE = "https://www.dungeoncrawlerchess.com"
SITE_LABEL = "www.dungeoncrawlerchess.com"
DISCLAIMER = ("A fan project. Not officially affiliated with or endorsed by Matt Dinniman "
              "or Dungeon Crawler Carl. Pending licensing.")

# "The AI" is in PAWN_CHARACTERS but can never be drafted (see /roster in app.py)
UNDRAFTABLE = {"The AI"}

# ═══ Short descriptions (keep these matching the code; DESIGN.md is the reference) ═══

PAWN_BLURBS = {
    "Zev": "All friendly dice rolls get +1 on your next turn.",
    "Mordecai": "When captured, leaves a ghost on his square for 3 full turns (nothing can enter), then "
                "respawns on your back rank. While within 1 square of Carl or Donut, their ability costs drop by 1.",
    "Prepotente": "Moves 2 squares forward this turn, including 2-square diagonal captures. While Carl is "
                  "in check, he can move 2 squares in any direction.",
    "Elle McGib": "Freezes one enemy piece within 5 squares for 1 full turn. It can't move or use abilities.",
    "Imani": "One enemy piece within 2 squares loses its abilities for its next turn.",
    "Candy Biggs": "Converts one enemy pawn to your side for the rest of the game.",
    "Louie": "Drops a 2×2 blocked zone within 4 squares (all 4 squares must be empty). "
             "No piece can enter it for 2 full turns.",
    "Sledge": "Becomes immovable and invulnerable for 2 full turns.",
    "Stripper Anaconda": "Pulls any one female piece, friendly or enemy, 1 square closer to Anaconda by the "
                         "shortest route. Donut always counts as female.",
    "Quasar": "When a friendly piece other than Carl is about to be captured, both players roll 2 dice. "
              "If the defender wins by 2 or more, the piece is saved and the attacker is captured instead. "
              "Not while your Carl is in check, and never for a piece giving check.",
    "Lucia Mar": "Restrains one enemy piece anywhere on the board for 1 full turn.",
    "Chris": "Lava covers Chris's square and one square on each side (horizontal or vertical) for 2 full "
             "turns. The squares must be empty and no enemy adjacent. Chris can't move while it burns.",
    "Juice Box": "Gains the ability of any dice-cost pawn she captures and can fire it at its cost +1, once "
                 "per turn cycle (not on the turn she captures). Loses it if that pawn is resurrected.",
    "Florin": "Pushes one enemy piece up to 2 squares directly away from Florin, stopping early if blocked.",
    "Ren": "Can't be captured normally. Only the enemy Carl moving onto him, or Blood Magic, removes him. "
           "He can't capture.",
    "Signet": "Pulls any one male piece, friendly or enemy, 1 square closer to Signet by the shortest route. "
              "Carl can never be targeted.",
    "Miriam Dom": "Sacrifice an adjacent friendly pawn to resurrect a captured friendly pawn onto your back rank.",
    "Orthrus": "A two-square piece. Moves 1 square head-first or rotates 90°, and can't capture. Only major "
               "pieces can capture him, and his death is permanent.",
    "Raul the Crab": "All friendly ability costs drop by 2 on your next turn.",
    "Bad Llama": "Spits a 1×2 lava strip within 4 squares for 3 full turns; no piece can enter it. "
                 "Bad Llama can't move that turn.",
}

# Cost labels that can't be derived from a single number
PAWN_COST_OVERRIDES = {
    "Mordecai": "Auto",
    "Juice Box": "Copied cost +1",
    "Ren": "Passive",
    "Orthrus": "—",
}

MAJOR_INFO = {
    "Carl": ("King", "1 square in any direction"),
    "Donut": ("Queen", "any distance in any direction"),
    "Mongo": ("Knight", "L-shaped jump that leaps over pieces"),
    "Katia": ("Bishop", "any distance diagonally"),
    "Samantha": ("Rook", "any distance horizontally or vertically"),
}

MAJOR_BLURBS = {
    "Leader": "Add your dice together into a pull distance and pull Donut, Katia, or Samantha toward Carl "
              "along that piece's own movement path. Carl still makes his normal move.",
    "Plot Armor": "Carl moves up to 3 squares in any King direction and can capture where he lands. "
                  "He can't pass through pieces or end in check.",
    "Jug-o-Boom": "Throws a bomb up to 3 squares. Hits if the boss is on or next to the target square.",
    "Puddle Jump": "Hops any distance in a Queen direction, passing over every piece. Must land on an "
                   "empty square, so it never captures.",
    "Cockroach": "Resurrects a random captured friendly piece onto an open square next to Donut.",
    "Magic Missile": "Fires up to 5 squares in a straight line. Hits if the boss is in its path.",
    "Pet Carrier": "Takes Mongo off the board. Release him later for free within 2 squares of Donut. "
                   "If Donut is captured while he's stored, Mongo goes too.",
    "Rampage": "Captures every enemy piece along his L-shaped paths, not just where he lands "
               "(never the enemy Carl).",
    "Gorefest": "Attacks up to 2 squares from Mongo in any direction.",
    "She Tank": "Stops one enemy piece from moving on its next turn. Use it on your turn, or as a "
                "reaction with a banked die.",
    "Blitzed": "One friendly piece skips its movement requirement this turn and can still use its ability.",
    "I Need My Space": "Pushes the boss 2 squares directly away from Katia. Any piece it's shoved into "
                       "is permanently killed.",
    "Slut Shame": "Swallows an enemy pawn within 3 squares. It respawns next to Samantha after 5 turns. "
                  "Orthrus is too big to swallow.",
    "Miss Me?": "Forces a reroll of dice in play: your own at the start of your turn, or your "
                "opponent's as a reaction with a banked die.",
    "IWKYM": "While next to the boss, holds it in place for 2 full turns (it can still take damage). "
             "Then Samantha returns to her back rank.",
}

# Extra cost notes that live only in an ability's description text
MAJOR_COST_NOTES = {"Puddle Jump": "10-turn cooldown"}

CARD_BLURBS = {
    "Lottery Ticket": "Roll a die. 1–3, <b>Custard</b>: reset one of your spent limited-use abilities. "
                      "4–6, <b>Fireball</b>: a random square is struck and its piece is permanently killed.",
    "You a Bitch": "If you have fewer pieces than your opponent, roll for a chance to resurrect one of "
                   "your captured major pieces.",
    "AI's Pet": "All your ability costs drop by 1 this turn.",
    "Dirty Tootsies": "All your ability costs rise by 1 this turn.",
    "System Reset": "No abilities can be used by either player this turn.",
    "Too Boring": "Each player permanently loses one pawn, chosen by their opponent.",
    "Main Character Syndrome": "No pawns can move this turn, for either player.",
    "Matt's Drunk Again": "The players swap control of each other's pieces for 1 to 6 turns (one die roll).",
    "Mana Toast": "You must immediately reroll both of your dice.",
    "What a Bitch": "You receive an Insta-Kill Boss Card, usable during any boss battle.",
}

BOSS_BLURBS = {
    "Rage Elemental": "A straight fight: wear it down with Boss Event attacks.",
    "Emberus": "A 5-square cross. All five squares move together, and anything under them dies.",
    "Goblin Murder Dozer": "Plows 2 squares per move and kills everything it passes through.",
    "Feral Goose": "Immune to all attacks. Defeated only when pieces stand on all 4 corners and the "
                   "center square at the same time.",
}

# ═══ Look: dark dungeon theme, gold headings, off-white text ═══

BG = HexColor("#0c0a11")
GOLD = HexColor("#d4af5a")
GOLD_DEEP = HexColor("#8f7233")
TEXT = HexColor("#ece5d6")
TEXT_SOFT = HexColor("#b9b0a2")
TEXT_DIM = HexColor("#7f776c")
BOSS_TAG = HexColor("#b897ff")
TABLE_HEAD = HexColor("#2a2140")
TABLE_ROW = HexColor("#16131f")
TABLE_ALT = HexColor("#1c1828")
TABLE_LINE = HexColor("#3a3150")

PAGE_W, PAGE_H = letter
MARGIN_X = 0.75 * inch
MARGIN_TOP = 0.85 * inch
MARGIN_BOTTOM = 0.95 * inch
CONTENT_W = PAGE_W - 2 * MARGIN_X

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.3, leading=12.6, textColor=TEXT, spaceAfter=4.5)
BODY_SOFT = ParagraphStyle("soft", parent=BODY, textColor=TEXT_SOFT)
H1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=27, leading=29, textColor=GOLD)
TAGLINE = ParagraphStyle("tag", fontName="Helvetica-Oblique", fontSize=13, leading=17, textColor=TEXT, spaceBefore=6)
H2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13.5, leading=16, textColor=GOLD, spaceBefore=8)
H3 = ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10.8, leading=14, textColor=GOLD, spaceBefore=6, spaceAfter=3, keepWithNext=1)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=14, bulletIndent=3, spaceAfter=2)
CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=8.1, leading=10.1, textColor=TEXT)
CELL_NAME = ParagraphStyle("cellname", parent=CELL, fontName="Helvetica-Bold", textColor=GOLD)
CELL_HEAD = ParagraphStyle("cellhead", parent=CELL, fontName="Helvetica-Bold", textColor=GOLD)
NOTICE = ParagraphStyle("notice", fontName="Helvetica-Oblique", fontSize=9, leading=12.5, textColor=TEXT_SOFT,
                        alignment=TA_CENTER)
CLOSING = ParagraphStyle("closing", fontName="Helvetica-Bold", fontSize=13, leading=18, textColor=TEXT,
                         alignment=TA_CENTER)


def link(label=SITE_LABEL):
    return f'<a href="{SITE}" color="#d4af5a"><u>{label}</u></a>'


def section(title):
    """A gold section heading with a rule under it. Starts a new page if there's
    too little room left, so a heading is never stranded at the bottom of a page
    (but long tables can still split across pages)."""
    return [CondPageBreak(1.2 * inch), Paragraph(title.upper(), H2),
            HRFlowable(width="100%", thickness=0.8, color=GOLD_DEEP, spaceBefore=3, spaceAfter=7)]


def bullets(items):
    return [Paragraph(text, BULLET, bulletText="•") for text in items]


def data_table(header, rows, widths):
    """A clean dark table: gold header row, alternating row shading."""
    data = [[Paragraph(h, CELL_HEAD) for h in header]]
    for row in rows:
        data.append([Paragraph(row[0], CELL_NAME)] + [Paragraph(c, CELL) for c in row[1:]])
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEAD),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, GOLD_DEEP),
        ("BOX", (0, 0), (-1, -1), 0.6, TABLE_LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.7),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(1, len(data)):
        style.append(("BACKGROUND", (0, i), (-1, i), TABLE_ROW if i % 2 else TABLE_ALT))
        style.append(("LINEBELOW", (0, i), (-1, i), 0.3, TABLE_LINE))
    t.setStyle(TableStyle(style))
    return t


# ═══ Data pulled from the game code ═══

def pawn_cost(name, ability):
    if name in PAWN_COST_OVERRIDES:
        return PAWN_COST_OVERRIDES[name]
    parts = [str(ability.floor_number) + (" combined" if ability.requires_combined else "")]
    if ability.trigger == AbilityTrigger.NO_ROLL:
        parts.append("banked die, reaction")
    if ability.uses_per_game:
        parts.append(f"{ability.uses_per_game}/game")
    return ", ".join(parts)


def pawn_rows():
    names = [n for n in PAWN_CHARACTERS if n not in UNDRAFTABLE]
    missing = [n for n in names if n not in PAWN_BLURBS]
    if missing:
        sys.exit(f"Add a PAWN_BLURBS entry for: {', '.join(missing)}")
    rows = []
    for name in names:
        ab = PAWN_CHARACTERS[name].ability
        ability_name = "No ability" if name == "Orthrus" else ab.name
        rows.append([name, ability_name, pawn_cost(name, ab), PAWN_BLURBS[name]])
    return rows


def major_cost(ab):
    if ab["name"] == "Leader":
        cost = "all dice combined"
    else:
        cost = str(ab["floor"]) + (" combined" if ab.get("requires_combined") else "")
    notes = [cost]
    if ab.get("uses_per_game"):
        notes.append(f"{ab['uses_per_game']}/game")
    if ab["name"] in MAJOR_COST_NOTES:
        notes.append(MAJOR_COST_NOTES[ab["name"]])
    if ab.get("is_reaction"):
        notes.append("reaction")
    return ", ".join(notes)


def major_section():
    flow = []
    for piece, abilities in MAJOR_ABILITIES.items():
        role = MAJOR_INFO[piece][0]
        items = []
        for ab in abilities:
            if ab["name"] not in MAJOR_BLURBS:
                sys.exit(f"Add a MAJOR_BLURBS entry for: {ab['name']}")
            tag = (' <font color="#b897ff" size="7.6">BOSS EVENT ONLY</font>'
                   if ab.get("is_boss_only") else "")
            items.append(f'<b>{ab["name"]}</b> <font color="#9a9184">({major_cost(ab)})</font>{tag} '
                         f'— {MAJOR_BLURBS[ab["name"]]}')
        flow.append(KeepTogether([Paragraph(f"{piece} ({role})", H3)] + bullets(items)))
    return flow


def card_rows():
    rows = []
    for card in AI_CARD_NAMES:
        if card in SUMMON_CARD_BOSS_TYPES:
            rows.append([card, f"Summons the {SUMMON_CARD_BOSS_TYPES[card]} boss onto the center square."])
        elif card in CARD_BLURBS:
            rows.append([card, CARD_BLURBS[card]])
        else:
            sys.exit(f"Add a CARD_BLURBS entry for: {card}")
    return rows


def boss_rows():
    rows = []
    for boss in SUMMON_CARD_BOSS_TYPES.values():
        if boss not in BOSS_BLURBS:
            sys.exit(f"Add a BOSS_BLURBS entry for: {boss}")
        hp = _BOSS_MAX_HP.get(boss, 0)
        moves = BOSS_MOVE_DISTANCE.get(boss, 1)
        rows.append([boss, str(hp) if hp else "Immune",
                     f"{moves} square{'s' if moves > 1 else ''}", BOSS_BLURBS[boss]])
    return rows


def summon_triggers():
    """The AI summon combos, checked against the real trigger rule."""
    combos = [((1, 1), "Double 1s"), ((3, 3), "Double 3s"), ((6, 2), "A six and a two")]
    for (a, b), _ in combos:
        assert is_ai_summon_roll(a, b), f"{a}+{b} no longer summons the AI -- update the PDF"
    big = ParagraphStyle("trig", fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=GOLD,
                         alignment=TA_CENTER)
    small = ParagraphStyle("trigsub", fontName="Helvetica", fontSize=8.5, leading=11, textColor=TEXT_SOFT,
                           alignment=TA_CENTER)
    cells = [[Paragraph(f"{a} + {b}", big), Spacer(1, 3), Paragraph(label, small)] for (a, b), label in combos]
    t = Table([cells], colWidths=[1.55 * inch] * 3, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TABLE_ROW),
        ("BOX", (0, 0), (-1, -1), 0.8, GOLD_DEEP),
        ("INNERGRID", (0, 0), (-1, -1), 0.8, GOLD_DEEP),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def logo_image(width):
    """The homepage logo art, converted from WebP in memory at full resolution."""
    im = PILImage.open(LOGO).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    buf.seek(0)
    return Image(buf, width=width, height=width * im.height / im.width)


# ═══ Page decoration: background, top rule, footer with disclaimer and page number ═══

def decorate(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BG)
    canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    canvas.setStrokeColor(GOLD_DEEP)
    canvas.setLineWidth(1)
    canvas.line(MARGIN_X, PAGE_H - 0.5 * inch, PAGE_W - MARGIN_X, PAGE_H - 0.5 * inch)

    y = 0.62 * inch
    canvas.setStrokeColor(TABLE_LINE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_X, y + 14, PAGE_W - MARGIN_X, y + 14)
    canvas.setFont("Helvetica", 7.6)
    canvas.setFillColor(TEXT_DIM)
    canvas.drawString(MARGIN_X, y, "Dungeon Crawler Chess — Game Overview  ·  ")
    lx = MARGIN_X + canvas.stringWidth("Dungeon Crawler Chess — Game Overview  ·  ", "Helvetica", 7.6)
    canvas.setFillColor(GOLD)
    canvas.drawString(lx, y, SITE_LABEL)
    canvas.linkURL(SITE, (lx, y - 2, lx + canvas.stringWidth(SITE_LABEL, "Helvetica", 7.6), y + 8), relative=0)
    canvas.setFillColor(TEXT_DIM)
    canvas.drawRightString(PAGE_W - MARGIN_X, y, str(doc.page))
    canvas.setFont("Helvetica-Oblique", 7)
    canvas.drawCentredString(PAGE_W / 2, y - 13, DISCLAIMER)
    canvas.restoreState()


# ═══ The document ═══

def build_story():
    s = []

    # Header: title and tagline beside the logo art
    title_block = [
        Paragraph("DUNGEON CRAWLER<br/>CHESS", H1),
        Paragraph("RPG chess in the Dungeon Crawler Carl universe", TAGLINE),
        Spacer(1, 10),
        Paragraph(f"Play the demo: {link()}", BODY_SOFT),
    ]
    header = Table([[title_block, logo_image(1.95 * inch)]], colWidths=[CONTENT_W - 2.1 * inch, 2.1 * inch])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    s += [header, Spacer(1, 10)]

    notice = Table([[Paragraph(DISCLAIMER, NOTICE)]], colWidths=[CONTENT_W])
    notice.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, GOLD_DEEP),
        ("BACKGROUND", (0, 0), (-1, -1), TABLE_ROW),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    s += [notice, Spacer(1, 2)]

    # 1. What is it
    s += section("What is it?")
    s.append(Paragraph(
        "Dungeon Crawler Chess is RPG chess set in the Dungeon Crawler Carl universe. It keeps the bones of "
        "traditional chess and adds a bigger board, a drafted roster of characters with unique abilities, a "
        "dice-driven mana system, and a chaotic AI that can crash the game at any moment. Today it's a "
        "playable fan-made web demo. The vision is a full 3D cross-platform video game.", BODY))

    # 2. The board
    s += section("The board")
    s.append(Paragraph(
        f"Played on an {BOARD_SIZE}×{BOARD_SIZE} grid instead of the traditional 8×8. The bigger board makes "
        "room for more strategy and for the expanded ability system.", BODY))
    s.append(Paragraph(
        '<font color="#d4af5a"><b>Free placement.</b></font> There is no fixed starting formation. Before the '
        "first move, each player sets up their own back rank (the 8 major pieces) and pawn rank (their 8 "
        "drafted pawns) however they want, so strategy starts before the first move. Tuck Carl into a corner "
        "behind his pawns, spread out across the full width, or park a pawn right next to the major piece it "
        "combos with.", BODY))
    s.append(Paragraph(
        '<font color="#d4af5a"><b>The center square</b></font> (F6) is the boss spawn point. Any piece '
        "standing there when a boss is summoned is permanently destroyed.", BODY))

    # 3. The pieces
    s += section("The pieces")
    s.append(Paragraph("Back line: moves exactly like traditional chess", H3))
    s += bullets([f"<b>{p} ({role})</b> — {move}" for p, (role, move) in MAJOR_INFO.items()])
    s.append(Paragraph("Each side has 2 Mongos, 2 Katias, and 2 Samanthas. Carl and Donut are unique.", BODY))
    s.append(Paragraph("Pawns and the draft", H3))
    s.append(Paragraph(
        "Pawns move like chess pawns: one square forward (two on their first move), capturing diagonally. "
        f"But every pawn is a character with its own ability. Before each game, each player drafts "
        f"<b>8 of {len(pawn_rows())}</b> from the roster below.", BODY))

    # 4. Dice and mana
    s += section("Dice and mana")
    s += bullets([
        "<b>Roll.</b> At the start of each turn, the player rolls 2 dice. Each die is mana for that turn.",
        "<b>Spend.</b> To use an ability, spend a die that meets or beats its cost. Then make your chess move.",
        "<b>Combined costs.</b> Bigger abilities are marked <i>combined</i>: they need both dice added "
        "together to reach the cost.",
        "<b>Bank a die.</b> Save one unused die in your bank for a later turn, or for a reaction ability "
        "on your opponent's turn (Quasar's Mediation, Katia's She Tank, Samantha's Miss Me?).",
        "<b>Limited uses.</b> Some abilities work only once or twice per game, and Donut's Puddle Jump has a "
        "10-turn cooldown, so timing matters.",
        "<b>Modifiers.</b> Zev boosts dice rolls, Raul the Crab and Mordecai lower ability costs, and some "
        "AI cards push costs up or down.",
    ])

    # 5. The pawn roster
    s += section(f"The pawn roster: draft 8 of {len(pawn_rows())}")
    s.append(data_table(["Character", "Ability", "Cost", "What it does"], pawn_rows(),
                        [1.12 * inch, 1.05 * inch, 0.98 * inch, CONTENT_W - 3.15 * inch]))

    # 6. Major piece abilities
    s += section("Major piece abilities")
    s.append(Paragraph(
        "Each major piece has 3 abilities. The third is <font color=\"#b897ff\">Boss Event Only</font>: "
        "it can only be used during a boss fight, and its attacks deal 1 damage per hit.", BODY_SOFT))
    s += major_section()

    # 7. The AI
    s += section("The AI")
    s.append(Paragraph(
        "The AI is always watching. Three dice combinations summon it, on any roll. That includes versus "
        "rolls, when both players roll to settle an outcome (like Quasar's Mediation roll-off), because "
        "it's meant to be chaotic.", BODY))
    s += [summon_triggers(), Spacer(1, 8)]
    s.append(Paragraph(
        f"Each summon draws the top card of a shuffled {len(AI_CARD_NAMES)}-card deck, one copy of each card. "
        "Once the deck runs out, summons do nothing. A summon is ignored while another event is still "
        "playing out (a boss fight, a control swap, System Reset, or Main Character Syndrome).", BODY))

    # 8. The AI card deck
    s += section(f"The AI card deck: {len(AI_CARD_NAMES)} cards")
    s.append(data_table(["Card", "Effect"], card_rows(), [1.75 * inch, CONTENT_W - 1.75 * inch]))

    # 9. Boss events (kept on one page so the table stays with its rules)
    boss = section("Boss events")
    boss += bullets([
        "<b>Spawning.</b> A Summon card brings its boss onto the center square, permanently destroying any "
        "piece there. If a boss is already active, the new one waits and spawns the moment the first falls.",
        "<b>Cooperation.</b> While a boss is out, the war pauses: captures are disabled, pieces move only to "
        "get into position, and both players work together. Only Boss Event Only abilities can hurt it.",
        "<b>Movement.</b> After each full round, both players roll 1 die. The total picks a compass "
        "direction (2 N, 3 NE, 4 E, 5 SE, 6 S, 7 SW, 8 W, 9 NW); on 10 to 12 it stays put. The boss "
        "permanently kills any piece it lands on or passes through, Carl included.",
        "<b>Falling.</b> If a Carl dies during a boss fight, that player has fallen and the survivor fights "
        "on with both armies. If both Carls fall, the game is a draw. Checkmate can't end the game while a "
        "boss is out.",
    ])
    boss += [Spacer(1, 4), data_table(["Boss", "HP", "Moves", "Unique rule"], boss_rows(),
                                      [1.45 * inch, 0.6 * inch, 0.75 * inch, CONTENT_W - 2.8 * inch])]
    s.append(KeepTogether(boss))

    # 10. Game settings
    s += section("Game settings")
    s.append(Paragraph(
        "Before each game, players can switch <b>AI Summon</b>, <b>Pawn Abilities</b>, <b>Major Piece "
        "Abilities</b>, and <b>Boss Events</b> on or off, and pick a <b>light or dark theme</b>.", BODY))

    # 11. The vision
    s += section("The vision")
    s.append(Paragraph(
        "A cross-platform video game for PC and mobile, so you can play on your phone against someone on "
        "their computer. 3D isometric, with fully modeled characters, full animations including unique "
        "capture animations, and online multiplayer with casual and competitive modes. Later: more "
        "characters, skins, and a physical edition with collectible miniatures and themed boards.", BODY))

    # 12. About the creator
    s += section("About the creator")
    s.append(Paragraph(
        "<b>Joey Roberts</b>, Miami, FL. Small business owner and huge DCC fan. Built the demo and the website "
        "over roughly 300 hours using AI coding tools. Not a game developer by trade, just someone who got "
        "obsessed with an idea and wouldn't let it go.", BODY))

    # 13. Closing line
    s += [Spacer(1, 12), HRFlowable(width="40%", thickness=0.8, color=GOLD_DEEP, spaceAfter=10),
          Paragraph(f"Play the demo and see the full project at {link()}", CLOSING)]
    return s


def build(path=OUTPUT):
    doc = BaseDocTemplate(
        path, pagesize=letter,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        title="Dungeon Crawler Chess — Game Overview", author="Joey Roberts",
        subject="RPG chess in the Dungeon Crawler Carl universe. " + DISCLAIMER,
    )
    frame = Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W, PAGE_H - MARGIN_TOP - MARGIN_BOTTOM,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="body")
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=decorate)])
    doc.build(build_story())
    return path


if __name__ == "__main__":
    out = build()
    print(f"Wrote {os.path.relpath(out, ROOT)}")
    for extra in sys.argv[1:]:
        dest = os.path.expanduser(extra)
        shutil.copyfile(out, dest)
        print(f"Copied to {dest}")
