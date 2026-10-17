"""All the drawing: the fingerprint, block-letter words and digits, the two hands, log-scale score
bars and small graphs. Pure functions returning rich Text lines, so they are easy to test and to
screenshot."""
from __future__ import annotations

import math
import textwrap
from functools import lru_cache
from typing import NamedTuple

from rich.text import Text

from goodix550c_tui.parsers import FINGERS_LEFT, FINGERS_RIGHT, THRESHOLD

# --------------------------------------------------------------------------
# Colours (same family as ctop: dark panel, soft accents)
# --------------------------------------------------------------------------
BG = "#0c0e12"
PANEL = "#131820"
FG = "#d0d4da"
WHITE = "#eef1f5"
DIM = "#7d8590"
FAINT = "#4a515c"
TRACK = "#262a31"
GREEN = "#56d364"
ORANGE = "#ff9f1c"
RED = "#ff5c5c"
CYAN = "#39c5cf"
BLUE = "#4ea1ff"
GREY = "#8b93a0"

# panel border colours (ctop uses the same ones)
B_BLUE, B_GREEN, B_GOLD, B_PURPLE, B_CYAN = ("#4f8fd6", "#5fa86b", "#d9a441", "#bc8cff", "#39c5cf")

STATE_COLOUR = {
    "idle": FG,
    "press": GREEN,
    "lift": ORANGE,
    "retry": RED,
    "nomatch": RED,
    "error": RED,
    "done": CYAN,
    "match": CYAN,
}
FLASHING = {"lift", "retry", "nomatch"}     # blink on and off
PULSING = {"press"}                         # breathe gently
KIND_COLOUR = {"match": GREEN, "nomatch": RED, "retry": ORANGE}


def _rgb(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


@lru_cache(maxsize=4096)
def blend(a: str, b: str, t: float) -> str:
    """Colour a -> b by t (0..1)."""
    t = min(max(t, 0.0), 1.0)
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(ra[i] + (rb[i] - ra[i]) * t) for i in range(3))


def runs(pairs) -> Text:
    """Text from (char, style) pairs, merging same-style neighbours (far fewer spans)."""
    t = Text(no_wrap=True)
    buf, cur = "", None
    for ch, st in pairs:
        if st == cur:
            buf += ch
        else:
            if buf:
                t.append(buf, cur or "")
            buf, cur = ch, st
    if buf:
        t.append(buf, cur or "")
    return t


def fit(t: Text, width: int) -> Text:
    """Copy of `t` cropped or padded to exactly `width` cells."""
    t = t.copy()
    t.truncate(max(width, 0), overflow="crop", pad=True)
    return t


def centre(t: Text, width: int) -> Text:
    pad = max(0, (width - t.cell_len) // 2)
    out = Text(" " * pad, no_wrap=True)
    out.append_text(t)
    return fit(out, width)


def hcat(cols: list[list[Text]], widths: list[int], gap: int = 2) -> list[Text]:
    """Glue blocks of lines side by side."""
    n = max((len(c) for c in cols), default=0)
    out = []
    for i in range(n):
        line = Text(no_wrap=True)
        for j, (c, w) in enumerate(zip(cols, widths)):
            line.append_text(fit(c[i] if i < len(c) else Text(), w))
            if j < len(cols) - 1:
                line.append(" " * gap)
        out.append(line)
    return out


def wrap(text: str, width: int, style: str = FG) -> list[Text]:
    return [Text(s, style=style, no_wrap=True) for s in textwrap.wrap(text, max(width, 10))] or [Text()]


# --------------------------------------------------------------------------
# The fingerprint: braille dots (a cell is 2 x 4 dots), any size
# --------------------------------------------------------------------------
_BITS = [[0x01, 0x02, 0x04, 0x40], [0x08, 0x10, 0x20, 0x80]]


def _smooth(e0: float, e1: float, x: float) -> float:
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


@lru_cache(maxsize=16)
def print_model(cols: int, rows: int) -> tuple[tuple[tuple[int, ...], ...], tuple[tuple[float, ...], ...]]:
    """(masks, keys) for a cols x rows print.

    masks[r][c] = braille bits of the ridges in that cell.
    keys[r][c]  = 0..1, the order in which the cell lights up: ridge by ridge from the core
                  outward, each ridge swept round clockwise from the top. A fill of f lights every
                  cell whose key <= f.
    """
    w, h = cols * 2, rows * 4
    cx, cy = (w - 1) / 2, (h - 1) / 2
    a, b = w / 2 - 0.6, h / 2 - 0.6
    freq = 0.5 * rows + 1.0                 # ridges per unit radius: ~3.5 dots apart at any size
    dots: list[tuple[int, int, float]] = []
    for y in range(h):
        for x in range(w):
            dx, dy = (x - cx) / a, (y - cy) / b
            # a slightly egg-shaped outline: narrower towards the tip (top)
            sx = dx / (0.90 + 0.10 * dy)
            if sx * sx + dy * dy > 1.0:
                continue
            # loop pattern: rings round a short core line, flattening into arches at the bottom
            ex, ey = dx * 1.05, dy + 0.12
            seg = min(max(ey, -0.09), 0.0)
            d = math.hypot(ex, (ey - seg) * 0.92)
            arch = (ey + 0.5) - 0.55 * ex * ex + 0.32
            wgt = _smooth(0.05, 0.75, ey)
            v = (1 - wgt) * d + wgt * max(d, arch * 0.85)
            v += 0.018 * math.sin(5 * math.atan2(ey, ex) + 3 * d)
            if v < 0.6 / freq:
                continue
            if (v * freq) % 1.0 < 0.5:
                ang = (math.atan2(ex, -(ey - seg)) / (2 * math.pi)) % 1.0
                dots.append((x, y, math.floor(v * freq) + ang))
    top = max((k for _, _, k in dots), default=1.0) or 1.0
    masks = [[0] * cols for _ in range(rows)]
    cell_keys: list[list[list[float]]] = [[[] for _ in range(cols)] for _ in range(rows)]
    for x, y, k in dots:
        masks[y // 4][x // 2] |= _BITS[x % 2][y % 4]
        cell_keys[y // 4][x // 2].append(k / top)
    keys = [[(sorted(ks)[len(ks) // 2] if ks else 1.0) for ks in row] for row in cell_keys]
    return tuple(tuple(r) for r in masks), tuple(tuple(r) for r in keys)


def print_size(max_cols: int, max_rows: int) -> tuple[int, int]:
    """Largest print that fits; a print is a little taller than wide (cells are 1:2)."""
    rows = max(6, min(max_rows, int(max_cols / 1.75)))
    return max(10, round(rows * 1.75)), rows


def fingerprint_lines(fill: float, lit: str, unlit: str, cols: int = 30, rows: int = 16,
                      edge: str | None = None, band: float = 0.0) -> list[Text]:
    """The print with cells up to `fill` (0..1) in `lit`, the rest in `unlit`. When `edge` is
    given, cells within `band` behind the fill front glow in that colour (the growing edge)."""
    masks, keys = print_model(cols, rows)
    fill = min(max(fill, 0.0), 1.0)
    out = []
    for r in range(rows):
        pairs = []
        for c in range(cols):
            m = masks[r][c]
            if not m:
                pairs.append((" ", None))
                continue
            k = keys[r][c]
            if k <= fill + 1e-9:
                st = edge if edge and k > fill - band else lit
            else:
                st = unlit
            pairs.append((chr(0x2800 + m), st))
        out.append(runs(pairs))
    return out


# --------------------------------------------------------------------------
# Block letters: 5x5 pixels, drawn full size (5 rows) or with half blocks (3 rows)
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

# 3x5 digits for the big numbers on Home
_DIGITS_SRC = {
    "0": "111 101 101 101 111", "1": "110 010 010 010 111", "2": "111 001 111 100 111",
    "3": "111 001 111 001 111", "4": "101 101 111 001 001", "5": "111 100 111 001 111",
    "6": "111 100 111 101 111", "7": "111 001 001 010 010", "8": "111 101 111 101 111",
    "9": "111 101 111 001 111", "%": "101 001 010 100 101", "-": "000 000 111 000 000",
    ".": "0 0 0 0 1", " ": "0 0 0 0 0", "/": "001 001 010 100 100",
}
DIGITS = {k: v.split() for k, v in _DIGITS_SRC.items()}


def _glyph_rows(glyphs: list[list[str]], gap: int) -> list[str]:
    return [(" " * gap).join("".join("█" if px == "1" else " " for px in g[r]) for g in glyphs)
            for r in range(5)]


def _halve(rows5: list[str]) -> list[str]:
    """5 rows of '█'/' ' -> 3 rows of half blocks."""
    rows5 = rows5 + [" " * len(rows5[0])]
    out = []
    for top, bot in zip(rows5[0::2], rows5[1::2]):
        out.append("".join("█" if a != " " and b != " " else "▀" if a != " " else "▄" if b != " " else " "
                           for a, b in zip(top, bot)))
    return out


def big_word(word: str, colour: str, half: bool = False) -> list[Text]:
    """Block letters, 5 rows (or 3 rows with half=True). Unknown characters are skipped."""
    letters = [FONT[c] for c in word.upper() if c in FONT]
    if not letters:
        return [Text(word, style=f"bold {colour}")]
    rows = _glyph_rows(letters, 2 if not half else 1)
    if half:
        rows = _halve(rows)
    return [Text(s, style=f"bold {colour}", no_wrap=True) for s in rows]


def big_word_width(word: str, half: bool = False) -> int:
    n = sum(1 for c in word.upper() if c in FONT)
    return max(0, n * (6 if half else 7) - (1 if half else 2))


def big_number(text: str, colour: str) -> list[Text]:
    """3 rows of half-block digits (0-9 - . /); a trailing % is drawn small."""
    pct = text.endswith("%")
    glyphs = [DIGITS[c] for c in text.rstrip("%") if c in DIGITS]
    if not glyphs:
        return [Text(text, style=f"bold {colour}")]
    rows = [Text(s, style=f"bold {colour}", no_wrap=True) for s in _halve(_glyph_rows(glyphs, 1))]
    if pct:
        rows[0].append("  ")
        rows[1].append("  ")
        rows[2].append(" %", f"bold {colour}")
    return rows


def big_number_width(text: str) -> int:
    ws = [len(DIGITS[c][0]) for c in text.rstrip("%") if c in DIGITS]
    return sum(ws) + max(0, len(ws) - 1) + (2 if text.endswith("%") else 0)


# --------------------------------------------------------------------------
# Scores: log scale, because they run from ~50 to 30000+ and the line that matters is 150
# --------------------------------------------------------------------------
SCORE_LO, SCORE_HI = 50, 50000
EIGHTHS = " ▏▎▍▌▋▊▉█"


def score_pos(score: float, lo: float = SCORE_LO, hi: float = SCORE_HI) -> float:
    """0..1 position of `score` on a log10 axis from lo to hi (clamped)."""
    if score <= lo:
        return 0.0
    return min(1.0, math.log10(score / lo) / math.log10(hi / lo))


def score_bar(score: int | None, width: int, colour: str, threshold: int = THRESHOLD) -> Text:
    """Horizontal log-scale bar with a marker at the threshold. score None = no score (retry).
    For a passing score the part below the line is dimmer, so the margin above it stands out."""
    width = max(width, 4)
    mark = min(width - 1, int(score_pos(threshold) * width))
    filled = 0.0 if score is None else score_pos(score) * width
    low = blend(colour, BG, 0.5) if score is not None and score >= threshold else colour
    pairs = []
    for i in range(width):
        part = min(max(filled - i, 0.0), 1.0)
        c = low if i < mark else colour
        if i == mark:
            pairs.append(("┃" if part >= 1 else "│", f"bold {WHITE}" if part >= 1 else DIM))
        elif part >= 1:
            pairs.append(("█", c))
        elif part > 0:
            pairs.append((EIGHTHS[max(1, round(part * 8))], c))
        else:
            pairs.append(("·", TRACK))
    return runs(pairs)


def score_axis(width: int, threshold: int = THRESHOLD) -> Text:
    """Tick labels under a score_bar of the same width."""
    cells = [" "] * width
    styles = [FAINT] * width
    for val, label in ((100, "100"), (threshold, str(threshold)), (1000, "1k"), (10000, "10k")):
        x = int(score_pos(val) * width)
        if val != threshold and abs(x - int(score_pos(threshold) * width)) < 4:
            continue
        x = min(max(0, x - (0 if val == threshold else len(label) // 2)), width - len(label))
        if any(c != " " for c in cells[max(0, x - 1):x + len(label) + 1]):
            continue
        for i, ch in enumerate(label):
            cells[x + i] = ch
            styles[x + i] = f"bold {FG}" if val == threshold else FAINT
    return runs(zip(cells, styles))


BLOCKS = " ▁▂▃▄▅▆▇█"


def score_columns(items: list[tuple[int | None, str]], width: int, rows: int,
                  threshold: int = THRESHOLD) -> list[Text]:
    """Vertical log-scale bars, newest on the right; items = (score or None, colour).
    A dashed line marks the threshold, a left gutter labels it; tries without a score show as a
    dot on the floor."""
    rows = max(rows, 2)
    gut = 5
    width -= gut
    n = len(items)
    if n == 0 or width < 4:
        return [Text() for _ in range(rows)]
    colw = max(1, min(3, (width + 1) // n - 1))
    step = colw + 1
    keep = max(1, (width + 1) // step)
    items = items[-keep:]
    grid = [[(" ", None)] * width for _ in range(rows)]
    labels = [" " * gut] * rows

    def row_of(v):
        return rows - 1 - int(score_pos(v) * rows)

    for v, lab in ((10000, "10k"), (1000, "1k"), (threshold, str(threshold))):
        r = row_of(v)
        if 0 <= r < rows:
            labels[r] = f"{lab:>{gut - 1}} "
            if v == threshold:
                for x in range(width):
                    grid[r][x] = ("╌", FAINT)
    x0 = width - len(items) * step + 1
    for i, (score, colour) in enumerate(items):
        x = x0 + i * step
        if score is None:
            for dx in range(colw):
                if 0 <= x + dx < width:
                    grid[rows - 1][x + dx] = ("•" if dx == colw // 2 else " ", colour)
            continue
        level = max(1, round(score_pos(score) * rows * 8))
        for r in range(rows):
            lv = level - (rows - 1 - r) * 8
            if lv <= 0:
                continue
            for dx in range(colw):
                if 0 <= x + dx < width:
                    grid[r][x + dx] = (BLOCKS[min(lv, 8)], colour)
    out = []
    for r in range(rows):
        t = Text(labels[r], style=f"bold {FG}" if labels[r].strip() == str(threshold) else FAINT, no_wrap=True)
        t.append_text(runs(grid[r]))
        out.append(t)
    return out


# --------------------------------------------------------------------------
# Hands: solid rounded fingers on a palm, the chosen one lit
# --------------------------------------------------------------------------
class HandSpec(NamedTuple):
    """Geometry of the two hands: finger width, gap, first row of each finger (left hand, little ...
    thumb), last finger row, palm rows, gap between the hands."""
    fw: int
    gap: int
    tops: tuple[int, ...]
    bottom: int
    palm: int
    hand_gap: int

    @property
    def hand_w(self) -> int:
        return 5 * self.fw + 4 * self.gap

    @property
    def width(self) -> int:
        return self.hand_w * 2 + self.hand_gap

    @property
    def height(self) -> int:
        return self.bottom + 1 + self.palm


HANDS_SMALL = HandSpec(fw=6, gap=1, tops=(3, 1, 0, 1, 4), bottom=7, palm=2, hand_gap=4)
HANDS_BIG = HandSpec(fw=9, gap=1, tops=(5, 2, 0, 2, 8), bottom=13, palm=3, hand_gap=6)   # roomy screens
SHORT = {"thumb": "thumb", "index": "index", "middle": "mid", "ring": "ring", "little": "pinky"}
FINGER_BG = "#1d2430"
SAVED_BG = "#173a24"
PALM_BG = "#161c25"


def _short(finger: str) -> str:
    return SHORT[finger.replace("-finger", "").split("-", 1)[1]]


def hands_size(big: bool = False) -> tuple[int, int]:
    spec = HANDS_BIG if big else HANDS_SMALL
    return spec.width, spec.height


def hands_lines(enrolled: set[str] | frozenset[str], selected: str | None,
                accent: str = BLUE, big: bool = False) -> list[Text]:
    """Two hands side by side, saved fingers green with a dot, the selected finger lit."""
    spec = HANDS_BIG if big else HANDS_SMALL
    fw, gap, bottom, palm, hgap = spec.fw, spec.gap, spec.bottom, spec.palm, spec.hand_gap
    hand_w, width, height = spec.hand_w, spec.width, spec.height
    grid = [[" "] * width for _ in range(height)]
    styles: list[list[str | None]] = [[None] * width for _ in range(height)]

    def put(y, x, s, st):
        for i, ch in enumerate(s):
            if 0 <= x + i < width:
                grid[y][x + i] = ch
                styles[y][x + i] = st

    hands = [(0, FINGERS_LEFT, spec.tops, "LEFT HAND"),
             (hand_w + hgap, FINGERS_RIGHT, spec.tops[::-1], "RIGHT HAND")]
    for x0, fingers, tops, label in hands:
        for i, (f, top) in enumerate(zip(fingers, tops)):
            x = x0 + i * (fw + gap)
            sel, on = f == selected, f in enrolled
            bg = accent if sel else (SAVED_BG if on else FINGER_BG)
            put(top, x, "▗" + "▄" * (fw - 2) + "▖", bg)            # rounded tip
            for y in range(top + 1, bottom + 1):
                put(y, x, " " * fw, f"on {bg}")
            name = _short(f)
            put(top + 1 + big, x + (fw - len(name)) // 2, name,
                f"bold {BG} on {bg}" if sel else f"bold {FG} on {bg}")
            mark = "●" if on else "○"
            mst = f"bold {BG} on {bg}" if sel else (f"bold {GREEN} on {bg}" if on else f"{FAINT} on {bg}")
            put(top + 2 + 2 * big, x + (fw - 1) // 2, mark, mst)
            if big and on:
                put(top + 3 + 2 * big, x + (fw - 5) // 2, "saved",
                    f"{BG} on {bg}" if sel else f"{GREEN} on {bg}")
        for y in range(bottom + 1, height):
            put(y, x0, " " * hand_w, f"on {PALM_BG}")
        put(height - 1 - (palm > 2), x0 + (hand_w - len(label)) // 2, label, f"bold {DIM} on {PALM_BG}")
    return [runs(zip(grid[y], styles[y])) for y in range(height)]
