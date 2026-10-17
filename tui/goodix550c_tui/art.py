"""All the drawing: the fingerprint, the giant status word and the two hands. Pure functions
returning rich Text lines, so they are easy to test and to screenshot."""
from __future__ import annotations

import math

from rich.text import Text

from goodix550c_tui.parsers import FINGERS_LEFT, FINGERS_RIGHT

# --------------------------------------------------------------------------
# Colours (same family as ctop: dark panel, soft accents)
# --------------------------------------------------------------------------
BG = "#0c0e12"
FG = "#d0d4da"
DIM = "#7d8590"
TRACK = "#262a31"
GREEN = "#56d364"
ORANGE = "#ff9f1c"
RED = "#ff5c5c"
CYAN = "#39c5cf"
BLUE = "#4ea1ff"
GREY = "#8b93a0"

# state -> (bright colour, word colour)
STATE_COLOUR = {
    "idle": GREY,
    "press": GREEN,
    "lift": ORANGE,
    "retry": RED,
    "nomatch": RED,
    "error": RED,
    "done": CYAN,
    "match": CYAN,
}
FLASHING = {"lift", "retry", "nomatch"}


def _rgb(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def blend(a: str, b: str, t: float) -> str:
    """Colour a -> b by t (0..1)."""
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(ra[i] + (rb[i] - ra[i]) * t) for i in range(3))


# --------------------------------------------------------------------------
# The fingerprint: braille dots, 30 columns x 16 rows (60 x 64 dots)
# --------------------------------------------------------------------------
COLS, ROWS = 30, 16
_DOT_BITS = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (1, 0): 0x40,
             (1, 1): 0x08, (1, 2): 0x10, (1, 3): 0x80, (0, 3): 0x40}
# braille: left column dots 1,2,3,7 ; right column dots 4,5,6,8
_BITS = [[0x01, 0x02, 0x04, 0x40], [0x08, 0x10, 0x20, 0x80]]


def _build_print() -> tuple[list[list[int]], list[list[float]]]:
    w, h = COLS * 2, ROWS * 4
    cx, cy = (w - 1) / 2, (h - 1) / 2
    a, b = w / 2 - 1, h / 2 - 1
    masks = [[0] * COLS for _ in range(ROWS)]
    keys = [[0.0] * COLS for _ in range(ROWS)]
    for y in range(h):
        for x in range(w):
            dx, dy = (x - cx) / a, (y - cy) / b
            if dx * dx + dy * dy > 1.0:
                continue                                   # outside the oval
            # ridge centre sits a little above the middle: a loop-style print
            ex, ey = dx, dy + 0.18
            r = math.hypot(ex, ey * 0.95)
            th = math.atan2(ey, ex)
            rr = r + 0.035 * math.sin(3 * th) + 0.05 * (dx * dx)
            if (rr * 9.0) % 1.0 < 0.52 and rr > 0.06:
                masks[y // 4][x // 2] |= _BITS[x % 2][y % 4]
    for row in range(ROWS):
        for col in range(COLS):
            ex = ((col + 0.5) * 2 - cx - 0.5) / a
            ey = (((row + 0.5) * 4 - cy - 0.5) / b) + 0.18
            keys[row][col] = math.hypot(ex, ey * 0.95)
    top = max(max(r) for r in keys)
    keys = [[k / top for k in r] for r in keys]
    return masks, keys


_MASKS, _KEYS = _build_print()


def fingerprint_lines(fill: float, state: str = "idle", phase: int = 0) -> list[Text]:
    """The print, `fill` (0..1) of it lit from the core outward, in the colour of `state`.
    `phase` (0/1) is the flash phase for the flashing states."""
    fill = min(max(fill, 0.0), 1.0)
    bright = STATE_COLOUR.get(state, GREY)
    if state in FLASHING and phase:
        bright = blend(bright, BG, 0.55)
    if state == "idle":
        lit, unlit = blend(GREY, BG, 0.45), blend(GREY, BG, 0.72)
    else:
        lit, unlit = bright, blend(bright, BG, 0.78)
    lines = []
    for row in range(ROWS):
        t = Text(no_wrap=True)
        run, run_style = "", ""
        for col in range(COLS):
            m = _MASKS[row][col]
            ch = chr(0x2800 + m) if m else " "
            style = lit if _KEYS[row][col] <= fill + 1e-9 else unlit
            if style == run_style:
                run += ch
            else:
                if run:
                    t.append(run, run_style)
                run, run_style = ch, style
        t.append(run, run_style)
        lines.append(t)
    return lines


# --------------------------------------------------------------------------
# Giant status word: 5x5 block font
# --------------------------------------------------------------------------
_FONT_SRC = {
    "A": "01110 10001 11111 10001 10001", "B": "11110 10001 11110 10001 11110",
    "C": "01111 10000 10000 10000 01111", "D": "11110 10001 10001 10001 11110",
    "E": "11111 10000 11110 10000 11111", "F": "11111 10000 11110 10000 10000",
    "G": "01111 10000 10011 10001 01111", "H": "10001 10001 11111 10001 10001",
    "I": "11111 00100 00100 00100 11111", "J": "00111 00010 00010 10010 01100",
    "K": "10001 10010 11100 10010 10001", "L": "10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10001 10001", "N": "10001 11001 10101 10011 10001",
    "O": "01110 10001 10001 10001 01110", "P": "11110 10001 11110 10000 10000",
    "Q": "01110 10001 10101 10010 01101", "R": "11110 10001 11110 10010 10001",
    "S": "01111 10000 01110 00001 11110", "T": "11111 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 01110", "V": "10001 10001 10001 01010 00100",
    "W": "10001 10001 10101 11011 10001", "X": "10001 01010 00100 01010 10001",
    "Y": "10001 01010 00100 00100 00100", "Z": "11111 00010 00100 01000 11111",
    "!": "00100 00100 00100 00000 00100", " ": "00000 00000 00000 00000 00000",
}
FONT = {k: v.split() for k, v in _FONT_SRC.items()}


def big_word(word: str, colour: str) -> list[Text]:
    """5 rows of block letters. Unknown characters are skipped."""
    letters = [FONT[c] for c in word.upper() if c in FONT]
    rows = []
    for r in range(5):
        s = "  ".join("".join("█" if px == "1" else " " for px in g[r]) for g in letters)
        rows.append(Text(s, style=f"bold {colour}", no_wrap=True))
    return rows


def big_word_width(word: str) -> int:
    n = sum(1 for c in word.upper() if c in FONT)
    return max(0, n * 7 - 2)


# --------------------------------------------------------------------------
# Hands
# --------------------------------------------------------------------------
FW = 7              # finger box width (5 inside)
HAND_W = 5 * FW + 4
HAND_GAP = 3
HANDS_W = HAND_W * 2 + HAND_GAP
HAND_H = 11
SHORT = {"thumb": "thumb", "index": "index", "middle": "mid", "ring": "ring", "little": "pinky"}
# top row of each finger, in left-to-right order of the LEFT hand (little ... thumb)
TOPS_LEFT = [3, 1, 0, 1, 4]
FINGER_BOTTOM = 8        # first row below the finger boxes


def _short(finger: str) -> str:
    return SHORT[finger.replace("-finger", "").split("-", 1)[1]]


def hands_lines(enrolled: set[str] | frozenset[str], selected: str | None,
                accent: str = BLUE) -> list[Text]:
    """Two hands side by side with finger names and an enrolled marker, selected finger highlighted."""
    width = HANDS_W
    grid = [[" "] * width for _ in range(HAND_H + 1)]
    styles = [[DIM] * width for _ in range(HAND_H + 1)]

    def put(y, x, s, st):
        for i, ch in enumerate(s):
            grid[y][x + i] = ch
            styles[y][x + i] = st

    hands = [(0, FINGERS_LEFT, TOPS_LEFT, "LEFT HAND"),
             (HAND_W + HAND_GAP, FINGERS_RIGHT, TOPS_LEFT[::-1], "RIGHT HAND")]
    for x0, fingers, tops, label in hands:
        put(0, x0 + (HAND_W - len(label)) // 2, label, f"bold {DIM}")
        for i, (f, top) in enumerate(zip(fingers, tops)):
            x = x0 + i * (FW + 1)
            sel = f == selected
            wall = f"bold {accent}" if sel else GREY
            fill = f"bold {BG} on {accent}" if sel else ""
            top += 1
            put(top, x, "╭" + "─" * (FW - 2) + "╮", wall)
            for y in range(top + 1, FINGER_BOTTOM + 2):
                put(y, x, "│", wall)
                put(y, x + FW - 1, "│", wall)
                if sel and y < FINGER_BOTTOM:
                    put(y, x + 1, " " * (FW - 2), fill)
            name = _short(f)
            put(top + 1, x + 1 + (FW - 2 - len(name)) // 2, name,
                fill or f"bold {FG}")
            on = f in enrolled
            mark = "●" if on else "○"
            mst = (f"bold {BG} on {accent}" if sel else (f"bold {GREEN}" if on else DIM))
            put(top + 2, x + 1 + (FW - 2) // 2, mark, mst)
        base = FINGER_BOTTOM + 2
        put(base, x0, "╰" + "─" * (HAND_W - 2) + "╯", GREY)
        for i in range(1, 5):
            wx = x0 + i * (FW + 1)
            put(base, wx - 1, "┴", GREY)
            put(base, wx, "┴", GREY)
    lines = []
    for y in range(HAND_H + 1):
        t = Text(no_wrap=True)
        run, rs = "", None
        for x in range(width):
            st = styles[y][x]
            if st == rs:
                run += grid[y][x]
            else:
                if run:
                    t.append(run, rs)
                run, rs = grid[y][x], st
        t.append(run, rs)
        lines.append(t)
    return lines
