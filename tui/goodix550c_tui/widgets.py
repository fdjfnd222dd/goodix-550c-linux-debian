"""Widgets: the live fingerprint view, the hands picker and the small modal dialogs."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from goodix550c_tui import art
from goodix550c_tui.art import BG, DIM, FG, GREEN, RED
from goodix550c_tui.parsers import pretty


class FingerprintView(Static):
    """Big fingerprint + progress bar + giant status word + one plain-English hint.

    state: idle | press | lift | retry | nomatch | error | done | match
    """

    DEFAULT_CSS = """
    FingerprintView { width: 100%; height: 1fr; content-align: center middle; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.state = "idle"
        self.fill = 0.0
        self.word = "READY"
        self.hint = ""
        self.title = ""
        self.sub = ""           # extra line under the hint (e.g. the score)
        self.show_bar = True
        self._phase = 0

    def on_mount(self) -> None:
        self.set_interval(0.45, self._flash)
        self.redraw()

    def _flash(self) -> None:
        if self.state in art.FLASHING:
            self._phase ^= 1
            self.redraw()

    def set(self, state: str, word: str, hint: str = "", fill: float | None = None,
            title: str | None = None, sub: str = "") -> None:
        self.state, self.word, self.hint, self.sub = state, word, hint, sub
        if fill is not None:
            self.fill = fill
        if title is not None:
            self.title = title
        self._phase = 0
        self.redraw()

    def on_resize(self, event) -> None:
        self.redraw()

    def lines(self) -> list[Text]:
        colour = art.STATE_COLOUR.get(self.state, art.GREY)
        out: list[Text] = []
        if self.title:
            out.append(Text(self.title, style=f"bold {FG}"))
        out += art.fingerprint_lines(self.fill, self.state, self._phase)
        if self.show_bar:
            n = 24
            on = round(self.fill * n)
            bar = Text(no_wrap=True)
            bar.append("▰" * on, colour if self.state != "idle" else art.GREY)
            bar.append("▱" * (n - on), art.TRACK)
            bar.append(f"  {round(self.fill * 100):>3}%", DIM)
            out.append(bar)
        height = self.size.height or 99
        word_colour = colour
        if self.state in art.FLASHING and self._phase:
            word_colour = art.blend(colour, BG, 0.55)
        if height >= len(out) + 5 + 3:
            out += art.big_word(self.word, word_colour)
        else:
            out.append(Text(self.word, style=f"bold {word_colour}"))
        out.append(Text(self.hint, style=FG))
        if self.sub:
            out.append(Text(self.sub, style=DIM))
        return out

    def redraw(self) -> None:
        if not self.is_attached:
            return
        t = Text("\n", justify="center", no_wrap=True).join(self.lines())
        t.justify = "center"
        self.update(t)


class HandsPicker(Static):
    """Both hands, arrow-key selectable (selection lives in `app.sel`)."""

    DEFAULT_CSS = "HandsPicker { width: auto; height: auto; }"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.enrolled: set[str] = set()
        self.selected: str | None = None

    def set(self, enrolled, selected) -> None:
        self.enrolled, self.selected = set(enrolled), selected
        self.update(Text("\n").join(art.hands_lines(self.enrolled, self.selected)))


def selection_line(finger: str, enrolled: set[str]) -> Text:
    t = Text(no_wrap=True)
    t.append("Chosen finger: ", DIM)
    t.append(pretty(finger), f"bold {FG}")
    if finger in enrolled:
        t.append("   ● saved", f"bold {GREEN}")
    else:
        t.append("   ○ not saved yet", DIM)
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


