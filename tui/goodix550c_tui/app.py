"""The Textual app: tabs, keys, shared data (status / saved fingers / journal) and root actions.

Keys follow ctop: numbers jump to a page, Tab goes to the next one, arrows or h j k l move,
? is help, q quits. Pages live in pages.py; the system is reached only through a backend
object (backend.Backend for real, demo.FakeBackend for --demo and the tests).
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from goodix550c_tui import __version__
from goodix550c_tui.art import BG, BLUE, DIM, FG, GREEN, ORANGE, RED
from goodix550c_tui.pages import EnrollPage, HelpPage, HomePage, SettingsPage, TestPage
from goodix550c_tui.parsers import FINGERS, Attempt, OpenInfo, Status, pretty
from goodix550c_tui.widgets import ConfirmScreen

PAGE_NAMES = {1: "Home", 2: "Enroll", 3: "Test", 4: "Settings", 5: "Help"}
REFRESH_SECONDS = 8.0


class FingerApp(App):
    TITLE = "finger"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("tab", "next_page", "Page", show=False, priority=True),
        Binding("1", "page(1)", "Home", show=False),
        Binding("2", "page(2)", "Enroll", show=False),
        Binding("3", "page(3)", "Test", show=False),
        Binding("4", "page(4)", "Settings", show=False),
        Binding("5", "page(5)", "Help", show=False),
        Binding("left,h", "move(-1,0)", "Left", show=False),
        Binding("right,l", "move(1,0)", "Right", show=False),
        Binding("up,k", "move(0,-1)", "Up", show=False),
        Binding("down,j", "move(0,1)", "Down", show=False),
        Binding("enter", "activate", "Choose", show=False),
        Binding("escape", "cancel", "Back", show=False),
        Binding("d", "delete", "Delete", show=False),
        Binding("a", "apply", "Apply", show=False),
        Binding("r", "reload", "Reload", show=False),
        Binding("question_mark", "help", "Help", show=False),
    ]
    CSS = f"""
    Screen {{ background: {BG}; color: {FG}; }}
    #tabs {{ height: 1; background: #131820; padding: 0 1; }}
    #pages {{ height: 1fr; }}
    #msg {{ height: 1; padding: 0 1; }}
    #hint {{ height: 1; padding: 0 1; background: #161b26; color: {DIM}; }}
    """

    def __init__(self, backend=None, demo: bool = False, score_poll: float = 0.5):
        super().__init__()
        if backend is None:
            if demo:
                from goodix550c_tui.demo import FakeBackend
                backend = FakeBackend()
            else:
                from goodix550c_tui.backend import Backend
                backend = Backend()
        self.backend = backend
        self.demo = demo or getattr(backend, "demo", False)
        self.score_poll = score_poll
        self.page = 1
        self.sel = FINGERS.index("right-index-finger")
        self.status: Status | None = None
        self.enrolled: set[str] = set()
        self.attempts: list[Attempt] = []
        self.opens: list[OpenInfo] = []
        self._msg_timer = None
        self._prev_page = 1

    # ---- layout
    def compose(self) -> ComposeResult:
        yield Static(id="tabs")
        with Vertical(id="pages"):
            yield HomePage(id="page1")
            yield EnrollPage(id="page2")
            yield TestPage(id="page3")
            yield SettingsPage(id="page4")
            yield HelpPage(id="page5")
        yield Static(id="msg")
        yield Static(id="hint")

    def on_mount(self) -> None:
        self.set_page(1)
        self.run_worker(self.refresh_data(), group="refresh")
        self.set_interval(REFRESH_SECONDS, self._tick)

    # ---- properties
    @property
    def sel_finger(self) -> str:
        return FINGERS[self.sel]

    def page_widget(self):
        return self.query_one(f"#page{self.page}")

    def _modal(self) -> bool:
        return isinstance(self.screen, ModalScreen)

    def _any_busy(self) -> bool:
        return any(self.query_one(f"#page{i}").busy for i in (2, 3))

    # ---- data
    async def refresh_data(self) -> None:
        be = self.backend
        status, fingers, (attempts, opens) = await asyncio.gather(
            be.status(), be.list_fingers(), be.journal())
        self.status, self.enrolled = status, set(fingers)
        self.attempts, self.opens = attempts, opens
        self.query_one("#page4", SettingsPage).load_from_status()
        self.refresh_pages()

    def _tick(self) -> None:
        if not self._any_busy() and not self._modal():
            self.run_worker(self.refresh_data(), group="refresh")

    def refresh_pages(self) -> None:
        for i in (1, 2, 4):
            self.query_one(f"#page{i}").refresh_view()
        self.update_chrome()

    # ---- chrome
    def update_chrome(self) -> None:
        t = Text(no_wrap=True)
        t.append("finger ", f"bold {BLUE}")
        t.append("│ ", DIM)
        for n, name in PAGE_NAMES.items():
            if n == self.page:
                t.append(f" {n} {name} ", f"bold {BG} on {BLUE}")
            else:
                t.append(f" {n} {name} ", FG)
            t.append(" ")
        if self.demo:
            t.append("  DEMO - nothing is real", f"bold {ORANGE}")
        self.query_one("#tabs", Static).update(t)
        self.query_one("#hint", Static).update(Text(self.page_widget().hint(), no_wrap=True))

    def say(self, text: str, colour: str = GREEN, seconds: float = 6.0) -> None:
        self.query_one("#msg", Static).update(Text(text, style=colour, no_wrap=True))
        if self._msg_timer is not None:
            self._msg_timer.stop()
        self._msg_timer = self.set_timer(seconds, lambda: self.query_one("#msg", Static).update(""))

    # ---- pages
    def set_page(self, n: int) -> None:
        self.page = n
        for i in PAGE_NAMES:
            self.query_one(f"#page{i}").display = i == n
        self.page_widget().on_show()
        self.update_chrome()

    def _switch_ok(self) -> bool:
        if self._modal():
            return False
        if self._any_busy():
            self.say("Finish or stop (Esc) what is running first.", ORANGE)
            return False
        return True

    def action_page(self, n: int) -> None:
        if self._switch_ok() and n != self.page:
            self._prev_page = self.page
            self.set_page(n)
            self.run_worker(self.refresh_data(), group="refresh")

    def action_next_page(self) -> None:
        if self._switch_ok():
            self._prev_page = self.page
            self.set_page(self.page % len(PAGE_NAMES) + 1)

    def action_help(self) -> None:
        if not self._switch_ok():
            return
        if self.page == 5:
            self.set_page(self._prev_page)
        else:
            self._prev_page = self.page
            self.set_page(5)

    def go_enroll(self, finger: str) -> None:
        self.sel = FINGERS.index(finger)
        self.action_page(2)

    # ---- key routing
    def action_move(self, dx: int, dy: int) -> None:
        if not self._modal():
            self.page_widget().move(dx, dy)

    def action_activate(self) -> None:
        if not self._modal():
            self.page_widget().activate()

    def action_cancel(self) -> None:
        if self._modal():
            return
        if self.page == 5:
            self.set_page(self._prev_page)
        else:
            self.page_widget().cancel()

    def action_delete(self) -> None:
        if not self._modal():
            self.page_widget().delete()

    def action_apply(self) -> None:
        if not self._modal():
            self.page_widget().apply()

    def action_reload(self) -> None:
        if self._modal() or self._any_busy():
            return
        if self.page == 4:
            self.page_widget().reload()
        self.run_worker(self.refresh_data(), group="refresh")
        self.say("Reloaded.", DIM, 2.0)

    def move_selection(self, dx: int, dy: int) -> None:
        if dx:
            self.sel = min(9, max(0, self.sel + dx))
        if dy:
            self.sel = 9 - self.sel          # same finger on the other hand
        self.refresh_pages()

    # ---- delete
    def ask_delete(self) -> None:
        f = self.sel_finger
        if f not in self.enrolled:
            self.say(f"Your {pretty(f)} is not saved, so there is nothing to delete.", ORANGE)
            return
        self.push_screen(
            ConfirmScreen("Delete this fingerprint?",
                          [f"Delete the saved print of your {pretty(f)}?", "",
                           "You will have to save it again to use it."],
                          yes="Delete it", no="Keep it", danger=True),
            lambda ok: self.run_worker(self._delete(f), group="op") if ok else None)

    async def _delete(self, finger: str) -> None:
        ok, msg = await self.backend.delete(finger)
        if ok:
            self.say(f"Deleted your {pretty(finger)}.")
        else:
            self.say(f"Could not delete: {msg}", RED)
        await self.refresh_data()

    # ---- root actions: drop to the real terminal so sudo can ask for the password
    def run_root(self, cmds: list[list[str]]) -> None:
        rc = 0
        if self.backend.needs_terminal:
            from textual.app import SuspendNotSupported
            try:
                with self.suspend():
                    print("\nfinger: running as administrator. Type your password if asked.\n", flush=True)
                    rc = self.backend.run_privileged(cmds)
                    try:
                        input("\nPress Enter to go back to finger... ")
                    except EOFError:
                        pass
            except SuspendNotSupported:
                self.say("This terminal cannot be paused; run the command shown on the Settings page yourself.", RED)
                return
        else:
            rc = self.backend.run_privileged(cmds)
        if rc == 0:
            self.say("Settings applied.")
        else:
            self.say(f"The change did not work (exit {rc}). Nothing else was touched.", RED)
        settings = self.query_one("#page4", SettingsPage)
        settings._loaded = False
        self.run_worker(self.refresh_data(), group="refresh")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="finger", description="Full-screen fingerprint helper for the Goodix 550c.")
    p.add_argument("--demo", action="store_true", help="run on made-up data (no sensor needed)")
    p.add_argument("--version", action="version", version=f"finger {__version__}")
    args = p.parse_args(argv)
    if not sys.stdout.isatty():
        print("finger needs a real terminal window.", file=sys.stderr)
        return 1
    FingerApp(demo=args.demo).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
