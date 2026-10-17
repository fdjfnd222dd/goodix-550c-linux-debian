"""The Textual app: tabs, keys, shared data (status / saved fingers / journal) and root actions.

Keys follow ctop: numbers jump to a page, Tab goes to the next one, arrows or h j k l move,
? is help, q quits. Pages live in pages.py; the system is reached only through a backend
object (backend.Backend for real, demo.FakeBackend for --demo and the tests).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from goodix550c_tui import __version__
from goodix550c_tui.art import BG, BLUE, DIM, FAINT, FG, GREEN, ORANGE, PANEL, RED
from goodix550c_tui.pages import EnrollPage, HelpPage, HomePage, SettingsPage, TestPage
from goodix550c_tui.parsers import FINGERS, Attempt, OpenInfo, Status, pretty
from goodix550c_tui.widgets import ConfirmScreen, keys_line

PAGE_NAMES = {1: "Home", 2: "Enroll", 3: "Test", 4: "Settings", 5: "Help"}
REFRESH_SECONDS = 8.0          # journal + saved fingers
STATUS_SECONDS = 30.0          # goodix550c-ctl status is slower, so it is asked less often


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
        Binding("e", "page(2)", "Enroll", show=False),
        Binding("t", "page(3)", "Test", show=False),
        Binding("s", "page(4)", "Settings", show=False),
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
    #tabs {{ height: 1; background: {PANEL}; padding: 0 1; }}
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
        self._status_at = 0.0                   # when status was last read (monotonic)
        self.stages_hint: int | None = None     # num-enroll-stages, asked once (read-only D-Bus)

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
        self._refresh()
        self.run_worker(self.fetch_stages(), group="stages")
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
    async def fetch_stages(self) -> None:
        if self.stages_hint is None:
            try:
                self.stages_hint = await self.backend.num_stages()
            except Exception:
                self.stages_hint = 0
            self.query_one("#page2").sync(self.page == 2)

    async def refresh_data(self, with_status: bool = True) -> None:
        """Read the system and redraw what changed. The journal and saved fingers are cheap; the status
        is only read when asked for (with_status) or when it has never been read."""
        be = self.backend
        reads = [be.list_fingers(), be.journal()]
        if with_status or self.status is None:
            reads.append(be.status())
        fingers, (attempts, opens), *status = await asyncio.gather(*reads)
        old = (self.status, self.enrolled, self.attempts, self.opens)
        if status:
            self.status, self._status_at = status[0], time.monotonic()
        self.enrolled, self.attempts, self.opens = set(fingers), attempts, opens
        loaded = self.query_one("#page4", SettingsPage).load_from_status()
        if not loaded and old == (self.status, self.enrolled, self.attempts, self.opens):
            return                                      # nothing new: no redraw at all
        self.refresh_pages()

    def _refresh(self, with_status: bool = True) -> None:
        self.run_worker(self.refresh_data(with_status), group="refresh")

    def _tick(self) -> None:
        if self.page == 5 or self._modal() or self._any_busy():
            return                                      # nothing on screen would change
        self._refresh(time.monotonic() - self._status_at >= STATUS_SECONDS)

    def refresh_pages(self) -> None:
        """Redraw the page on screen; the others redraw when they are shown."""
        for i in (1, 2, 3, 4):
            self.query_one(f"#page{i}").sync(i == self.page)
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
        right = self._summary()
        width = self.size.width - 2
        if right.cell_len and t.cell_len + right.cell_len + 2 <= width:
            t.append(" " * (width - t.cell_len - right.cell_len))
            t.append_text(right)
        self.query_one("#tabs", Static).update(t)
        self.query_one("#hint", Static).update(keys_line(self.page_widget().hint()))

    def _summary(self) -> Text:
        """Right end of the tab bar: the state of things in one glance."""
        s = self.status
        t = Text(no_wrap=True)
        if s is None or s.error:
            return t
        ok = s.sensor_present
        t.append("● " if ok else "✗ ", GREEN if ok else RED)
        t.append("sensor  " if ok else "no sensor  ", DIM)
        t.append(f"{len(self.enrolled)}", f"bold {FG}")
        t.append(" saved  ", DIM)
        t.append("sudo ", DIM)
        t.append("on" if s.pam_enabled else "off", f"bold {GREEN}" if s.pam_enabled else FAINT)
        return t

    def on_resize(self, event) -> None:
        if self.query("#tabs") and self.query("#hint"):
            for i in PAGE_NAMES:
                if i != self.page:
                    self.query_one(f"#page{i}").stale = True      # sized for the old screen
            self.update_chrome()

    def say(self, text: str, colour: str = GREEN, seconds: float = 6.0) -> None:
        self.query_one("#msg", Static).update(Text(text, style=colour, no_wrap=True))
        if self._msg_timer is not None:
            self._msg_timer.stop()
        self._msg_timer = self.set_timer(seconds, lambda: self.query_one("#msg", Static).update(""))

    # ---- pages
    def set_page(self, n: int) -> None:
        if n != self.page:
            self._prev_page = self.page
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

    def _goto(self, n: int) -> None:
        """Show page n and, unless it is Help, read the system afresh (status included)."""
        self.set_page(n)
        if n != 5:
            self._refresh()

    def action_page(self, n: int) -> None:
        if self._switch_ok() and n != self.page:
            self._goto(n)

    def action_next_page(self) -> None:
        if self._switch_ok():
            self._goto(self.page % len(PAGE_NAMES) + 1)

    def action_help(self) -> None:
        if self._switch_ok():
            self._goto(self._prev_page if self.page == 5 else 5)

    def go_enroll(self, finger: str) -> None:
        self.sel = FINGERS.index(finger)
        self.action_page(2)

    # ---- key routing
    def _to_page(self, name: str, *args) -> None:
        """Hand a key to the page on screen (not while a dialog is open)."""
        if not self._modal():
            getattr(self.page_widget(), name)(*args)

    def action_move(self, dx: int, dy: int) -> None:
        self._to_page("move", dx, dy)

    def action_activate(self) -> None:
        self._to_page("activate")

    def action_cancel(self) -> None:
        if self.page == 5 and not self._modal():
            self._goto(self._prev_page)
        else:
            self._to_page("cancel")

    def action_delete(self) -> None:
        self._to_page("delete")

    def action_apply(self) -> None:
        self._to_page("apply")

    def action_reload(self) -> None:
        if self._modal() or self._any_busy():
            return
        if self.page == 4:
            self.page_widget().reload()
        self._refresh()
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
        self.query_one("#page4", SettingsPage).invalidate()
        self._refresh()


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
