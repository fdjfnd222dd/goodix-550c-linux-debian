"""Widgets: the panel base, the live fingerprint view and the modal dialogs."""
from __future__ import annotations

import math
import time
from typing import NamedTuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from goodix550c_tui import art
from goodix550c_tui.art import BG, DIM, FAINT, FG, GREEN, RED, TRACK, WHITE
from goodix550c_tui.parsers import pretty


def _cropped(t: Text, width: int) -> Text:
    t = t.copy()
    t.truncate(width, overflow="crop")
    return t


class Panel(Static):
    """A bordered box that redraws its lines to fit its size (like ctop's panels).
    Subclasses implement build(width, height) -> list[Text]."""

    DEFAULT_CSS = """
    Panel { height: 1fr; padding: 0 1; overflow: hidden; border-title-style: bold;
            border-subtitle-color: #7d8590; }
    """

    def __init__(self, title: str = "", colour: str = art.B_BLUE, **kw):
        super().__init__(**kw)
        self.border_title = title
        self.styles.border = ("round", colour)
        self.styles.border_title_color = colour

    def build(self, width: int, height: int) -> list[Text]:
        return []

    def draw(self) -> None:
        if not self.is_attached:
            return
        size = self.content_size
        if size.width < 4 or size.height < 1:
            return
        try:
            lines = self.build(size.width, size.height)
        except Exception as e:          # a bad frame must never kill the app
            lines = [Text(f"draw error: {e!r}", style=RED)]
        lines = [ln if ln.cell_len <= size.width else _cropped(ln, size.width) for ln in lines[: size.height]]
        self.update(Text("\n", no_wrap=True).join(lines))

    def on_resize(self, event) -> None:
        self.draw()

    def on_mount(self) -> None:
        self.draw()


# --------------------------------------------------------------------------
# The live fingerprint
# --------------------------------------------------------------------------
GROW_SECONDS = 0.8          # one passed scan grows the print over this long
SWEEP_SECONDS = 0.7         # Test page: the result colour sweeps over the whole print
FRAME = 1 / 24
FLASH_SECONDS = 0.4         # lift / retry / nomatch blink: on for this long, off for this long
PULSE_SECONDS = 1.6         # press: one breath
PULSE_STEPS = 32            # the breath is quantised to this many levels; redraw only when one changes


class _Column(NamedTuple):
    """The parts of the text column that only change with the key in FingerprintView._column."""
    word_rows: tuple[str, ...]          # block letters (or one plain line); coloured per frame
    wrapped: tuple[Text, ...]           # hint, sub and next_hint, wrapped and styled


class FingerprintView(Static):
    """Big fingerprint on the left; on the right the giant status word, one plain-English
    instruction and progress. Narrow screens stack the two.

    state: idle | press | lift | retry | nomatch | error | done | match
    `fill` is the target (0..1); `shown` follows it smoothly, ridge by ridge from the core out.
    """

    DEFAULT_CSS = "FingerprintView { width: 100%; height: 1fr; }"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.state = "idle"
        self.fill = 0.0
        self.shown = 0.0
        self.word = "READY"
        self.hint = ""
        self.title = ""
        self.sub = ""               # extra line under the hint (e.g. the score)
        self.next_hint = ""         # dim "then ..." line
        self.stage = 0              # progress pips: stage of stages (stages 0 = no pips)
        self.stages = 0
        self.extra: list[Text] = []     # more lines at the bottom of the text column
        self.show_bar = True
        self._anim_from = 0.0
        self._anim_start = 0.0
        self._anim_len = GROW_SECONDS
        self._state_t = time.monotonic()
        self.animate = True
        self._column_key: tuple | None = None
        self._column_val = _Column((), ())
        self._drawn_phase: float | int | None = None    # flash / pulse phase of the last redraw

    # ---- driving it
    def on_mount(self) -> None:
        self.set_interval(FRAME, self._frame)
        self.redraw()

    def set(self, state: str, word: str, hint: str = "", fill: float | None = None,
            title: str | None = None, sub: str = "", sweep: bool = False, next_hint: str = "") -> None:
        """Change what is shown. A higher `fill` grows smoothly; a lower one jumps.
        sweep=True replays the fill from empty (the Test page result)."""
        if state != self.state:
            self._state_t = time.monotonic()
        self.state, self.word, self.hint, self.sub, self.next_hint = state, word, hint, sub, next_hint
        if title is not None:
            self.title = title
        if fill is not None:
            self.grow_to(fill, from_zero=sweep)
        self.redraw()

    def grow_to(self, fill: float, from_zero: bool = False) -> None:
        fill = min(max(fill, 0.0), 1.0)
        start = 0.0 if from_zero else self.shown
        if not self.animate or fill <= start:
            self.fill = self.shown = fill
            self._anim_start = 0.0
            return
        self.fill = fill
        self._anim_from = start
        self.shown = start
        self._anim_start = time.monotonic()
        self._anim_len = SWEEP_SECONDS if from_zero else GROW_SECONDS

    def settle(self) -> None:
        """Finish any animation now (tests / screenshots)."""
        self.shown = self.fill
        self._anim_start = 0.0
        self.redraw()

    @property
    def animating(self) -> bool:
        return self._anim_start > 0.0

    def _frame(self) -> None:
        if self.animating:
            t = (time.monotonic() - self._anim_start) / self._anim_len
            if t >= 1.0:
                self.shown = self.fill
                self._anim_start = 0.0
            else:
                e = 1 - (1 - t) ** 3                    # ease out
                self.shown = self._anim_from + (self.fill - self._anim_from) * e
            self.redraw()
        elif self._phase() != self._drawn_phase:        # blinking / breathing: only when it visibly changes
            self.redraw()

    def on_resize(self, event) -> None:
        self.redraw()

    # ---- colours
    def _age(self) -> float:
        return time.monotonic() - self._state_t

    def _phase(self) -> int | None:
        """Which step of the blink / breath we are in (None = steady); a redraw is due when it changes."""
        if self.state in art.FLASHING:
            return int(self._age() / FLASH_SECONDS)
        if self.state in art.PULSING:
            return round(self._pulse() * PULSE_STEPS)
        return None

    def _pulse(self) -> float:
        return 0.78 + 0.22 * (0.5 + 0.5 * math.cos(self._age() * 2 * math.pi / PULSE_SECONDS))

    def colours(self) -> tuple[str, str, str]:
        """(lit, unlit, word) colours for the current state and moment."""
        base = art.STATE_COLOUR.get(self.state, FG)
        if self.state == "idle":
            return art.blend(FG, BG, 0.35), art.blend(FG, BG, 0.80), art.blend(FG, BG, 0.2)
        k = 1.0
        if self.state in art.PULSING:                   # gentle breathing
            k = round(self._pulse() * PULSE_STEPS) / PULSE_STEPS
        elif self.state in art.FLASHING:                # on/off flash
            k = 1.0 if int(self._age() / FLASH_SECONDS) % 2 == 0 else 0.45
        lit = art.blend(BG, base, k)
        unlit = art.blend(art.blend(FG, base, 0.25), BG, 0.74 if k >= 0.9 else 0.80)
        return lit, unlit, art.blend(BG, base, max(k, 0.55))

    # ---- drawing
    def pips(self, colour: str, width: int) -> Text:
        t = Text(no_wrap=True)
        if self.stages <= 0:
            return t
        if self.stages * 2 <= width:
            for i in range(self.stages):
                t.append("● " if i < self.stage else "○ ", colour if i < self.stage else FAINT)
        else:
            n = max(4, width)
            on = round(n * self.stage / self.stages)
            t.append("▰" * on, colour)
            t.append("▱" * (n - on), TRACK)
        return t

    def _head_lines(self) -> int:
        """Rows used above the big word: title, progress, one blank."""
        n = 1 if self.title else 0
        if self.stages and self.show_bar:
            n += 2
        elif self.show_bar and self.state != "idle":
            n += 1
        return n + 1

    def _column(self, width: int, height: int) -> _Column:
        """Block letters and wrapped hint lines: expensive, and the same every frame of a state."""
        key = (self.state, self.word, self.hint, self.sub, self.next_hint, self.title, self.stage,
               self.stages, self.show_bar, width, height)
        if key != self._column_key:
            used = self._head_lines()
            if art.big_word_width(self.word) <= width and height >= used + 5 + 4:
                rows = [t.plain for t in art.big_word(self.word, "")]
            elif art.big_word_width(self.word, half=True) <= width and height >= used + 3 + 3:
                rows = [t.plain for t in art.big_word(self.word, "", half=True)]
            else:
                rows = [self.word]
            wrapped = art.wrap(self.hint, width, f"bold {WHITE}" if self.state != "idle" else FG)
            if self.sub:
                wrapped += art.wrap(self.sub, width, FG)
            if self.next_hint:
                wrapped += art.wrap(self.next_hint, width, DIM)
            self._column_key, self._column_val = key, _Column(tuple(rows), tuple(wrapped))
        return self._column_val

    def text_column(self, width: int, height: int, word_colour: str, colour: str) -> list[Text]:
        col = self._column(width, height)
        out: list[Text] = []
        if self.title:
            out.append(Text(self.title, style=f"bold {FG}", no_wrap=True))
        if self.stages and self.show_bar:
            head = Text(no_wrap=True)
            head.append(f"Scan {min(self.stage, self.stages)} of {self.stages}", DIM)
            head.append(f"   {round(self.shown * 100):>3}%", f"bold {colour}" if self.state != "idle" else DIM)
            out.append(head)
            out.append(self.pips(colour if self.state != "idle" else DIM, width))
        elif self.show_bar and self.state != "idle":
            out.append(Text(f"{round(self.shown * 100)}%", style=DIM))
        out.append(Text())
        out += [Text(r, style=f"bold {word_colour}", no_wrap=True) for r in col.word_rows]
        out.append(Text())
        out += col.wrapped
        if self.extra and len(out) + 2 <= height:
            out.append(Text())
            out += self.extra[: max(0, height - len(out))]
        return out

    def lines(self, width: int, height: int) -> list[Text]:
        lit, unlit, word_colour = self.colours()
        colour = art.STATE_COLOUR.get(self.state, FG)
        edge = WHITE if self.animating else None
        side = width >= 92
        if side:
            cols, rows = art.print_size(max(20, min(84, width - 80)), max(10, height - 2))
            fp = art.fingerprint_lines(self.shown, lit, unlit, cols, rows, edge=edge, band=0.05)
            text_w = min(72, width - cols - 10)
            text = self.text_column(text_w, height, word_colour, colour)
            left_w = cols + 4
            fp = [Text()] * max(0, (len(text) - len(fp)) // 2) + fp
            text = [Text()] * max(0, (len(fp) - len(text)) // 2) + text
            body = art.hcat([fp, text], [left_w, text_w], gap=4)
            pad = max(0, (width - left_w - 4 - text_w) // 2)
            body = [Text(" " * pad) + ln for ln in body]
        else:
            text = self.text_column(width - 2, height, word_colour, colour)
            room = height - len(text) - 1
            cols, rows = art.print_size(width - 4, min(18, room))
            fp = art.fingerprint_lines(self.shown, lit, unlit, cols, rows, edge=edge, band=0.05) if room >= 6 else []
            body = [art.centre(ln, width) for ln in fp] + [Text()] + [art.centre(ln, width) for ln in text]
        top = max(0, (height - len(body)) // 2)
        return [Text()] * top + body

    def redraw(self) -> None:
        if not self.is_attached:
            return
        self._drawn_phase = self._phase()
        w, h = self.content_size.width or 100, self.content_size.height or 30
        self.update(Text("\n", no_wrap=True).join(self.lines(w, h)[:h]))


def selection_line(finger: str, enrolled: set[str]) -> Text:
    t = Text(no_wrap=True)
    t.append("Chosen finger: ", DIM)
    t.append(pretty(finger), f"bold {FG}")
    if finger in enrolled:
        t.append("   ● saved", f"bold {GREEN}")
    else:
        t.append("   ○ not saved yet", DIM)
    return t


def keys_line(pairs: list[tuple[str, str]], gap: int = 3) -> Text:
    """'Enter save it   d delete' with the keys bright and the words dim."""
    t = Text(no_wrap=True)
    for i, (k, label) in enumerate(pairs):
        if i:
            t.append(" " * gap)
        t.append(k, f"bold {FG}")
        t.append(" " + label, DIM)
    return t


# --------------------------------------------------------------------------
# Modal dialogs
# --------------------------------------------------------------------------
class ConfirmScreen(ModalScreen):
    """Yes/No box. Returns True / False. Default answer is the safe one unless default_yes."""

    BINDINGS = [
        Binding("y", "answer(True)", "Yes", priority=True),
        Binding("n,escape", "answer(False)", "No", priority=True),
        Binding("left,right,h,l,tab", "toggle", "Switch", priority=True),
        Binding("enter", "accept", "Choose", priority=True),
    ]
    CSS = """
    ConfirmScreen { align: center middle; background: #000000 60%; }
    #cbox { width: 78; height: auto; padding: 1 2; background: #131820; border: round #d9a441;
            border-title-color: #d9a441; }
    #cbody { height: auto; }
    #cbtn { height: 1; margin-top: 1; }
    """

    def __init__(self, title: str, lines: list[str], yes: str = "Yes", no: str = "No",
                 default_yes: bool = False, danger: bool = False):
        super().__init__()
        self._title, self._lines = title, lines
        self._yes, self._no = yes, no
        self.choice = default_yes
        self._danger = danger

    def compose(self) -> ComposeResult:
        with Vertical(id="cbox"):
            yield Static(id="cbody")
            yield Static(id="cbtn")

    def on_mount(self) -> None:
        box = self.query_one("#cbox")
        box.border_title = self._title
        if self._danger:
            box.styles.border = ("round", RED)
            box.styles.border_title_color = RED
        self.query_one("#cbody", Static).update(Text("\n".join(self._lines), style=FG))
        self._paint()

    def _paint(self) -> None:
        t = Text(no_wrap=True)
        on = f"bold {BG} on {GREEN}"
        off = f"bold {BG} on {RED}"
        t.append(f" {self._yes} ", on if self.choice else DIM)
        t.append("   ")
        t.append(f" {self._no} ", off if not self.choice else DIM)
        t.append("     y = yes   n = no   Enter = choose", DIM)
        self.query_one("#cbtn", Static).update(t)

    def action_toggle(self) -> None:
        self.choice = not self.choice
        self._paint()

    def action_accept(self) -> None:
        self.dismiss(self.choice)

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)
