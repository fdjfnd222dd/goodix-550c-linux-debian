"""The five pages. Each is a plain container the App routes keys to (like ctop's pages)."""
from __future__ import annotations

import asyncio

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from goodix550c_tui import art
from goodix550c_tui.art import BLUE, CYAN, DIM, FG, GREEN, ORANGE, RED
from goodix550c_tui.parsers import FINGERS, THRESHOLD, Attempt, Status, pretty, validate_settings
from goodix550c_tui.widgets import ConfirmScreen, FingerprintView, HandsPicker, selection_line


def kv(label: str, value, style: str = FG, lw: int = 15) -> Text:
    t = Text(no_wrap=True)
    t.append(f"{label:<{lw}}", DIM)
    t.append_text(value if isinstance(value, Text) else Text(str(value), style=style))
    return t


def yes_no(ok: bool | None, good: str, bad: str, unknown: str = "not checked") -> Text:
    if ok is None:
        return Text(f"? {unknown}", style=DIM)
    return Text(f"✔ {good}", style=f"bold {GREEN}") if ok else Text(f"✘ {bad}", style=f"bold {RED}")


class Page(Vertical):
    """Base class: the App calls these. Defaults do nothing."""

    DEFAULT_CSS = "Page { height: 1fr; width: 100%; }"
    busy = False            # a long operation is running (blocks page switches & refreshes)

    def on_show(self) -> None: ...
    def refresh_view(self) -> None: ...
    def move(self, dx: int, dy: int) -> None: ...
    def activate(self) -> None: ...
    def cancel(self) -> None: ...
    def delete(self) -> None: ...
    def apply(self) -> None: ...
    def hint(self) -> str:
        return ""

    @property
    def fa(self):           # the App
        return self.app


# --------------------------------------------------------------------------
# 1 Home
# --------------------------------------------------------------------------
BAR_W = 36


def score_bar(score: int, threshold: int, ok: bool, scale: int) -> Text:
    """Bar of `score` on a 0..scale line with a marker at the threshold."""
    mark = min(BAR_W - 1, round(threshold / scale * BAR_W))
    on = min(BAR_W, round(score / scale * BAR_W))
    colour = GREEN if ok else RED
    t = Text(no_wrap=True)
    for i in range(BAR_W):
        if i == mark:
            t.append("│", f"bold {art.FG}")
        elif i < on:
            t.append("█", colour)
        else:
            t.append("·", art.TRACK)
    return t


def attempt_line(a: Attempt, scale: int) -> Text:
    t = Text(no_wrap=True)
    t.append(f"{a.time or '--:--:--':<9} ", DIM)
    t.append(f"{a.action[:8] or '?':<9}", FG)
    if a.retry:
        t.append_text(score_bar(0, a.threshold, False, scale))
        t.append(f"  {'-':>4}  ", DIM)
        t.append(f"retry ({a.result.split(':', 1)[-1]})", ORANGE)
    else:
        t.append_text(score_bar(a.best_score, a.threshold, a.matched, scale))
        t.append(f"  {a.best_score:>4}  ", f"bold {FG}")
        t.append("match" if a.matched else "no match", f"bold {GREEN}" if a.matched else f"bold {RED}")
    return t


class HomePage(Page):
    DEFAULT_CSS = """
    HomePage #home-top { height: auto; }
    HomePage #home-hands { width: 87; height: auto; border: round #4ea1ff; border-title-color: #4ea1ff; padding: 0 1; }
    HomePage #home-device { width: 1fr; height: 100%; min-width: 30; border: round #5fa86b; border-title-color: #5fa86b; padding: 0 1; }
    HomePage #home-attempts { height: 1fr; border: round #d9a441; border-title-color: #d9a441; padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="home-top"):
            with Vertical(id="home-hands"):
                yield HandsPicker(id="home-picker")
                yield Static(id="home-sel")
            yield Static(id="home-device")
        yield Static(id="home-attempts")

    def on_mount(self) -> None:
        self.query_one("#home-hands").border_title = "Your fingers"
        self.query_one("#home-device").border_title = "This computer"
        self.query_one("#home-attempts").border_title = f"Last 10 tries (a match needs {THRESHOLD}+)"
        self.refresh_view()

    def hint(self) -> str:
        return "←→↑↓ choose finger   Enter save it   d delete it   r refresh   Tab next page   ? help   q quit"

    def move(self, dx, dy):
        self.fa.move_selection(dx, dy)

    def activate(self):
        self.fa.go_enroll(self.fa.sel_finger)

    def delete(self):
        self.fa.ask_delete()

    def refresh_view(self) -> None:
        a = self.fa
        self.query_one("#home-picker", HandsPicker).set(a.enrolled, a.sel_finger)
        self.query_one("#home-sel", Static).update(selection_line(a.sel_finger, a.enrolled))
        self.query_one("#home-device", Static).update(Text("\n").join(self._device_lines(a.status)))
        self.query_one("#home-attempts", Static).update(Text("\n").join(self._attempt_lines(a.attempts)))

    def _device_lines(self, s: Status | None) -> list[Text]:
        if s is None:
            return [Text("looking...", style=DIM)]
        if s.error:
            return [Text(s.error, style=RED)]
        lib = s.libfprint_version or "not installed"
        driver = Text(no_wrap=True)
        if s.patched:
            driver.append("✔ ", f"bold {GREEN}")
            driver.append(lib.replace("1:1.94.10+", ""), FG)
            driver.append("  held" if s.held else "  NOT held", GREEN if s.held else f"bold {RED}")
        else:
            driver.append("✘ stock library (sensor not supported)", f"bold {RED}")
        pam = Text(no_wrap=True)
        if s.pam_enabled:
            pam.append("✔ ON", f"bold {GREEN}")
            pam.append(f"  {s.pam_tries} tries, {s.pam_timeout}s", FG)
        else:
            pam.append("○ off", DIM)
            pam.append(f"  ({s.pam_tries} tries, {s.pam_timeout}s)", DIM)
        a = self.fa
        lines = [
            kv("Sensor", yes_no(s.sensor_present, "found", "NOT FOUND")),
            kv("Driver", driver),
            kv("Secret key", yes_no(s.psk_present, "installed", "MISSING", "needs admin to check")),
            kv("Print store", yes_no(s.store_ok, "private", "too open (run recover)")),
            kv("Sudo/polkit", pam),
            kv("Saved fingers", f"{len(a.enrolled)} of 10", FG),
        ]
        if a.opens:
            o = a.opens[-1]
            ok = o.result == "ok"
            lines.append(kv("Sensor start", Text(f"{'✔' if ok else '✘'} {o.result}, {o.ms} ms",
                                                 style=GREEN if ok else RED)))
        return lines

    def _attempt_lines(self, attempts: list[Attempt]) -> list[Text]:
        if not attempts:
            return [Text("No tries logged yet. Use the Test page (3) to try a finger.", style=DIM)]
        last = attempts[-10:][::-1]
        scale = max(300, max((a.best_score for a in last), default=0) + 20)
        head = Text(f"{'time':<10}{'what':<9}{'score  (│ = needed)':<{BAR_W + 2}}{'':>4}  result", style=DIM)
        return [head] + [attempt_line(x, scale) for x in last]


# --------------------------------------------------------------------------
# shared run logic for Enroll / Test
# --------------------------------------------------------------------------
class RunPage(Page):
    """A page with a FingerprintView driven by an event stream."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._timer = None
        self._worker = None
        self.running = False

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _later(self, seconds: float, fn):
        self._cancel_timer()
        self._timer = self.set_timer(seconds, fn)

    def stop_worker(self):
        self._cancel_timer()
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        self.running = False
        self.busy = False

    def on_unmount(self) -> None:
        self.stop_worker()


# --------------------------------------------------------------------------
# 2 Enroll
# --------------------------------------------------------------------------
class EnrollPage(RunPage):
    DEFAULT_CSS = """
    EnrollPage #enr-pick { height: 1fr; align: center middle; }
    EnrollPage #enr-box { width: 87; height: auto; border: round #4ea1ff; border-title-color: #4ea1ff; padding: 0 1; }
    EnrollPage #enr-run { height: 1fr; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.mode = "pick"          # pick | run | end
        self.finger = ""
        self.stage = 0
        self.stages = 5
        self.outcome = ""           # completed | failed | ...

    def compose(self) -> ComposeResult:
        with Vertical(id="enr-pick"):
            with Vertical(id="enr-box"):
                yield Static(id="enr-title")
                yield HandsPicker(id="enr-picker")
                yield Static(id="enr-sel")
        with Vertical(id="enr-run"):
            yield FingerprintView(id="enr-view")

    def on_mount(self) -> None:
        self.query_one("#enr-box").border_title = "Save a fingerprint"
        self._show_mode()
        self.refresh_view()

    def _show_mode(self):
        self.query_one("#enr-pick").display = self.mode == "pick"
        self.query_one("#enr-run").display = self.mode != "pick"

    def on_show(self) -> None:
        self.refresh_view()

    def hint(self) -> str:
        if self.mode == "pick":
            return "←→↑↓ choose finger   Enter start saving it   d delete it   Tab next page   ? help   q quit"
        if self.mode == "run":
            return "Do what the big word says.   Esc = stop"
        if self.outcome == "completed":
            return "Enter = save another finger   Esc = back   q quit"
        return "Enter = try again   Esc = back   q quit"

    def refresh_view(self) -> None:
        a = self.fa
        self.query_one("#enr-picker", HandsPicker).set(a.enrolled, a.sel_finger)
        self.query_one("#enr-sel", Static).update(selection_line(a.sel_finger, a.enrolled))
        self.query_one("#enr-title", Static).update(Text(
            "Pick the finger you want to save, then press Enter.\n"
            "You will touch the sensor several times; the picture fills up as it learns your finger.\n", style=FG))

    # ---- keys
    def move(self, dx, dy):
        if self.mode == "pick":
            self.fa.move_selection(dx, dy)

    def delete(self):
        if self.mode == "pick":
            self.fa.ask_delete()

    def cancel(self):
        if self.mode == "run":
            self.stop_worker()
            self.mode = "pick"
            self.fa.say("Stopped. Nothing was saved.")
        elif self.mode == "end":
            self.mode = "pick"
        self._show_mode()
        self.fa.update_chrome()

    def activate(self):
        if self.mode == "pick":
            f = self.fa.sel_finger
            if f in self.fa.enrolled:
                self.fa.push_screen(
                    ConfirmScreen("Replace this fingerprint?",
                                  [f"Your {pretty(f)} is already saved.", "",
                                   "Saving it again replaces the old one."],
                                  yes="Replace it", no="Keep the old one"),
                    lambda ok: self.begin(f) if ok else None)
            else:
                self.begin(f)
        elif self.mode == "end":
            if self.outcome == "completed":
                self.mode = "pick"
                self._show_mode()
                self.fa.update_chrome()
            else:
                self.begin(self.finger)

    # ---- the run
    def begin(self, finger: str) -> None:
        self.finger = finger
        self.mode = "run"
        self.busy = True
        self.running = True
        self.stage = 0
        self.outcome = ""
        self._show_mode()
        v = self.query_one("#enr-view", FingerprintView)
        v.fill = 0.0
        v.set("idle", "WAIT", "Getting ready...", 0.0, title=f"Saving your {pretty(finger)}")
        self.fa.update_chrome()
        self._worker = self.fa.run_worker(self._run(finger), group="op", exclusive=True)

    def _view(self) -> FingerprintView:
        return self.query_one("#enr-view", FingerprintView)

    def _title(self) -> str:
        return f"Saving your {pretty(self.finger)}  -  scan {min(self.stage + 1, self.stages)} of {self.stages}" \
            if self.outcome == "" and self.stage < self.stages else f"Saving your {pretty(self.finger)}"

    def _press(self, hint: str = "Press your finger flat on the sensor and hold still.") -> None:
        self._view().set("press", "PRESS", hint, title=self._title())

    async def _run(self, finger: str) -> None:
        be = self.fa.backend
        try:
            self.stages = max(1, await be.num_stages())
            self.stage = 0
            self._view().title = self._title()
            async for ev in be.enroll(finger):
                self._handle(ev)
                if self.outcome:
                    break
        finally:
            self.running = False
            self.busy = False
        if not self.outcome:
            self._finish("failed", "ERROR", "The fingerprint program stopped unexpectedly. Press Enter to try again.", "error")
        await self.fa.refresh_data()

    def _finish(self, outcome: str, word: str, hint: str, state: str, sub: str = "") -> None:
        self._cancel_timer()
        self.outcome = outcome
        self.mode = "end"
        self.running = False
        self.busy = False
        fill = 1.0 if outcome == "completed" else self._view().fill
        self._view().set(state, word, hint, fill, title=f"Saving your {pretty(self.finger)}", sub=sub)
        self.fa.update_chrome()

    def _handle(self, ev) -> None:
        v = self._view()
        k = ev.kind
        if k == "started":
            self._press()
        elif k == "stage":
            self.stage += 1
            v.fill = min(1.0, self.stage / self.stages)
            v.title = self._title()
            v.set("lift", "LIFT", "Lift your finger off the sensor.", title=self._title())
            self._later(1.0, lambda: self._press() if self.mode == "run" else None)
        elif k in ("retry", "short", "not-centered"):
            msg = {"retry": "That scan was not clear. Keep your finger still.",
                   "short": "The touch was too short. Hold your finger down a little longer.",
                   "not-centered": "Put the middle of your fingertip on the sensor."}[k]
            v.set("retry", "TRY AGAIN", msg, title=self._title())
            self._later(1.5, lambda: self._press("Press your finger flat on the sensor again.") if self.mode == "run" else None)
        elif k == "remove":
            v.set("lift", "LIFT", "Lift your finger all the way off, then press again.", title=self._title())
            self._later(1.2, lambda: self._press() if self.mode == "run" else None)
        elif k == "completed":
            self._finish("completed", "DONE", "Saved! This finger is ready. Press Enter to save another, or Esc to go back.", "done")
            self.fa.say(f"Saved your {pretty(self.finger)}.")
        elif k == "failed":
            self._finish("failed", "FAILED", "Could not save this finger. Press Enter to try again.", "error")
        elif k == "disconnected":
            self._finish("disconnected", "NO SENSOR", "The sensor went away. Check it is plugged in, then press Enter to retry.", "error")
        elif k == "full":
            self._finish("full", "FULL", "There is no room for another print. Delete one first (Esc, then d).", "error")
        elif k == "duplicate":
            self._finish("duplicate", "ALREADY SAVED", "This fingerprint is already saved, maybe as another finger.", "error")
        elif k == "error":
            self._finish("error", "ERROR", (ev.message or "Something went wrong.")[:100] + "  Press Enter to retry.", "error")
        elif k == "ended":
            pass


# --------------------------------------------------------------------------
# 3 Test
# --------------------------------------------------------------------------
def _key(a: Attempt | None):
    return None if a is None else (a.time, tuple(sorted(a.fields.items())), a.best_score, a.result)


class TestPage(RunPage):
    __test__ = False            # not a pytest class

    DEFAULT_CSS = "TestPage #tst-view { height: 1fr; }"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.mode = "idle"          # idle | run | end
        self.result = ""

    def compose(self) -> ComposeResult:
        yield FingerprintView(id="tst-view")

    def on_mount(self) -> None:
        self._idle()

    def _view(self) -> FingerprintView:
        return self.query_one("#tst-view", FingerprintView)

    def _idle(self) -> None:
        self.mode = "idle"
        self._view().set("idle", "READY", "Press Enter to start. Then touch the sensor with any saved finger.",
                         0.0, title="Test a fingerprint")

    def on_show(self) -> None:
        pass

    def hint(self) -> str:
        if self.mode == "run":
            return "Do what the big word says.   Esc = stop"
        return "Enter = start the test   Tab next page   ? help   q quit"

    def cancel(self):
        if self.mode == "run":
            self.stop_worker()
            self._idle()
            self.fa.say("Test stopped.")
            self.fa.update_chrome()

    def activate(self):
        if self.mode == "run":
            return
        if not self.fa.enrolled:
            self._view().set("error", "NO FINGERS", "No fingerprints are saved yet. Go to page 2 (Enroll) first.", 0.0)
            return
        self.mode = "run"
        self.busy = True
        self.running = True
        self._view().set("idle", "WAIT", "Getting ready...", 0.0, title="Testing")
        self.fa.update_chrome()
        self._worker = self.fa.run_worker(self._run(), group="op", exclusive=True)

    async def _score_after(self, before) -> Attempt | None:
        for _ in range(4):
            await asyncio.sleep(self.fa.score_poll)
            attempts, _opens = await self.fa.backend.journal()
            if attempts and _key(attempts[-1]) != before:
                return attempts[-1]
        return None

    async def _run(self) -> None:
        be = self.fa.backend
        v = self._view()
        before_list, _ = await be.journal()
        before = _key(before_list[-1]) if before_list else None
        final = False
        try:
            async for ev in be.verify():
                k = ev.kind
                if k == "started":
                    v.set("press", "PRESS", "Touch the sensor with a saved finger and hold still.", 0.0, title="Testing")
                elif k == "retry":
                    v.set("retry", "TRY AGAIN", "The sensor did not get a good read. Press again.", title="Testing")
                    self._later(1.5, lambda: v.set("press", "PRESS", "Press your finger flat on the sensor again.", title="Testing")
                                if self.mode == "run" else None)
                elif k in ("match", "no-match"):
                    final = True
                    self._cancel_timer()
                    self.result = k
                    at = await self._score_after(before)
                    sub = ""
                    if at is not None:
                        sub = f"Score {at.best_score}  (a match needs {at.threshold} or more)"
                    if k == "match":
                        v.set("match", "MATCH", "That finger is recognised. Press Enter to test again.", 1.0, title="Testing", sub=sub)
                    else:
                        v.set("nomatch", "NO MATCH", "That finger is not recognised. Press Enter to test again.", 1.0, title="Testing", sub=sub)
                    break
                elif k in ("disconnected", "error"):
                    final = True
                    self._cancel_timer()
                    word = "NO SENSOR" if k == "disconnected" else "ERROR"
                    v.set("error", word, (ev.message or "The sensor is not available.")[:100] + "  Press Enter to retry.", 0.0, title="Testing")
                    break
        finally:
            self.running = False
            self.busy = False
        self.mode = "end" if final else "idle"
        if not final:
            self._idle()
        self.fa.update_chrome()
        await self.fa.refresh_data()


# --------------------------------------------------------------------------
# 4 Settings
# --------------------------------------------------------------------------
class SettingsPage(Page):
    DEFAULT_CSS = """
    SettingsPage { align: center top; }
    SettingsPage #set-box { width: 92; height: auto; border: round #bc8cff; border-title-color: #bc8cff; padding: 1 2; margin-top: 1; }
    """
    ROWS = ["tries", "timeout", "pam", "apply"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.row = 0
        self.tries = 3
        self.timeout = 15
        self.pam = False
        self._loaded = False
        self.message = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="set-box"):
            yield Static(id="set-body")

    def on_mount(self) -> None:
        self.query_one("#set-box").border_title = "Settings (for sudo and system password pop-ups)"
        self.refresh_view()

    def hint(self) -> str:
        return "↑↓ choose   ←→ change   Enter/a apply   r reload   Tab next page   ? help   q quit"

    # ---- current system values (what Apply compares against)
    def load_from_status(self) -> None:
        s = self.fa.status
        if s is not None and not s.error and not self._loaded:
            self.tries, self.timeout = s.pam_tries, s.pam_timeout
            self.pam = bool(s.pam_enabled)
            self._loaded = True

    def reload(self) -> None:
        self._loaded = False
        self.load_from_status()
        self.refresh_view()

    def _changes(self):
        s = self.fa.status
        if s is None or s.error:
            return None, None, None
        values = (self.tries, self.timeout) != (s.pam_tries, s.pam_timeout)
        pam = self.pam != bool(s.pam_enabled)
        return (values, pam, s)

    def pending_commands(self) -> list[list[str]]:
        values, pam, s = self._changes()
        if s is None:
            return []
        return self.fa.backend.root_commands(self.tries if values else None, self.timeout if values else None,
                                             self.pam if pam else None)

    def move(self, dx, dy):
        if dy:
            self.row = (self.row + dy) % len(self.ROWS)
        elif dx:
            r = self.ROWS[self.row]
            if r == "tries":
                self.tries = min(5, max(1, self.tries + dx))
            elif r == "timeout":
                self.timeout = min(30, max(5, self.timeout + dx))
            elif r == "pam":
                self.pam = not self.pam
        self.message = ""
        self.refresh_view()

    def activate(self):
        r = self.ROWS[self.row]
        if r == "pam":
            self.pam = not self.pam
            self.refresh_view()
        else:
            self.apply()

    def apply(self):
        problem = validate_settings(self.tries, self.timeout)
        if problem:
            self.message = problem
            self.refresh_view()
            return
        cmds = self.pending_commands()
        if not cmds:
            self.message = "Nothing to apply - the settings already match."
            self.refresh_view()
            return
        lines = ["These change system files, so they need your admin password.",
                 "The screen will switch to the normal terminal for a moment.", "",
                 "Commands that will run:"] + ["  " + " ".join(c) for c in cmds]
        self.fa.push_screen(ConfirmScreen("Apply settings?", lines, yes="Run", no="Cancel", default_yes=True),
                            lambda ok: self.fa.run_root(cmds) if ok else None)

    def refresh_view(self) -> None:
        self.load_from_status()
        s = self.fa.status
        t: list[Text] = []

        def row(i, label, value: Text, note: str):
            line = Text(no_wrap=True)
            cur = i == self.row
            line.append("▶ " if cur else "  ", f"bold {BLUE}")
            line.append(f"{label:<34}", f"bold {FG}" if cur else FG)
            line.append_text(value)
            line.append(f"   {note}", DIM)
            t.append(line)

        def num(v, lo, hi, unit=""):
            x = Text(no_wrap=True)
            x.append(" ◀ ", DIM)
            x.append(f"{str(v) + unit:^6}", f"bold {CYAN}")
            x.append(" ▶ ", DIM)
            return x

        t.append(Text("Fingerprint checks happen when sudo or a system pop-up asks for your password.\n"
                      "Your password always still works. The login screen and lock screen are not affected.\n", style=DIM))
        row(0, "Fingerprint tries before password", num(self.tries, 1, 5), "(1 - 5)")
        row(1, "Wait for finger (seconds)", num(self.timeout, 5, 30, " s"), "(5 - 30)")
        on = Text("  ON  " if self.pam else " OFF  ", style=f"bold {art.BG} on {GREEN}" if self.pam else f"bold {art.BG} on {art.GREY}")
        row(2, "Use fingerprint for sudo / pop-ups", on, "(Enter or ←→ switches)")
        t.append(Text())
        cmds = self.pending_commands()
        btn = Text(" Apply ", style=f"bold {art.BG} on {BLUE}" if cmds else f"bold {DIM}")
        line = Text(no_wrap=True)
        line.append("▶ " if self.row == 3 else "  ", f"bold {BLUE}")
        line.append_text(btn)
        t.append(line)
        t.append(Text())
        if s is None or s.error:
            t.append(Text("Could not read the current settings.", style=RED))
        elif cmds:
            t.append(Text("Press Apply to run:", style=DIM))
            for c in cmds:
                t.append(Text("  " + " ".join(c), style=f"bold {ORANGE}"))
        else:
            t.append(Text("Nothing changed.", style=DIM))
        if self.message:
            t.append(Text())
            t.append(Text(self.message, style=f"bold {ORANGE}"))
        self.query_one("#set-body", Static).update(Text("\n").join(t))


# --------------------------------------------------------------------------
# 5 Help
# --------------------------------------------------------------------------
HELP_TEXT = """\
 finger - how to use it

 The big picture
   The fingerprint in the middle shows what the sensor is doing:
     GREEN  PRESS      touch the sensor and hold still
     ORANGE LIFT       take your finger off
     RED    TRY AGAIN  that touch was not good enough, touch again
     CYAN   DONE / MATCH   all good
   Do exactly what the big word says. It never asks for two things at once.

 Pages (press the number)
   1 Home       the sensor and driver at a glance, your saved fingers, and your last 10 tries
   2 Enroll     choose a finger on the hands, press Enter, then touch the sensor until it says DONE
   3 Test       press Enter, touch the sensor, and see MATCH or NO MATCH with the score
   4 Settings   how many tries and how long sudo waits for a finger; turn it on or off
   5 Help       this page

 Keys
   arrows or h j k l   move (hands: left/right = next finger, up/down = other hand)
   Enter               choose / start
   Esc                 stop what is running, or go back
   d                   delete the chosen finger (asks first)
   r                   reload from the system
   Tab                 next page          ?   help          q   quit

 Good to know
   A match needs a score of 150 or more. The Home page shows your recent scores.
   Settings that change system files ask for your admin password in the normal terminal;
   the app comes back right after.
   Nothing here can lock you out: your password always works.
   Try the app without the sensor:   finger --demo

 Press 1 to go back.
"""


class HelpPage(Page):
    DEFAULT_CSS = """
    HelpPage #help-box { width: 100; height: auto; border: round #4f8fd6; border-title-color: #4f8fd6; padding: 0 1; }
    HelpPage { align: center top; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static(HELP_TEXT)

    def on_mount(self) -> None:
        self.query_one("#help-box").border_title = "Help"

    def hint(self) -> str:
        return "1-4 pages   Tab next page   q quit"
