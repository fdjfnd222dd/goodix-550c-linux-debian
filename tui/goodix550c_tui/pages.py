"""The five pages. Each is a plain container the App routes keys to (like ctop's pages)."""
from __future__ import annotations

import asyncio
import datetime as _dt
from collections import Counter
from typing import NamedTuple

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from goodix550c_tui import art
from goodix550c_tui.art import (BG, BLUE, CYAN, DIM, FAINT, FG, GREEN, KIND_COLOUR, ORANGE, RED, WHITE,
                                hcat, wrap)
from goodix550c_tui.parsers import (FINGERS, RESULT_HELP, Attempt, Stats, Status, display_threshold,
                                    plain_result, pretty, summarise, validate_settings)
from goodix550c_tui.widgets import ConfirmScreen, FingerprintView, Panel, keys_line, selection_line

Keys = list[tuple[str, str]]


def kv(label: str, value, style: str = FG, lw: int = 15) -> Text:
    t = Text(no_wrap=True)
    t.append(f"{label:<{lw}}", DIM)
    t.append_text(value if isinstance(value, Text) else Text(str(value), style=style))
    return t


def today() -> str:
    return _dt.date.today().isoformat()


class Page(Vertical):
    """Base class: the App calls these. Defaults do nothing, except that a page redraws its panels."""

    DEFAULT_CSS = "Page { height: 1fr; width: 100%; }"
    busy = False            # a long operation is running (blocks page switches & refreshes)
    stale = True            # data or size changed while the page was hidden: redraw when shown

    def sync(self, visible: bool) -> None:
        """New data arrived: redraw now if this page is showing, otherwise just remember to."""
        if visible:
            self.stale = False
            self.refresh_view()
        else:
            self.stale = True

    def on_show(self) -> None:
        if self.stale:
            self.sync(True)

    def refresh_view(self) -> None:
        for p in self.query(Panel):
            p.draw()

    def move(self, dx: int, dy: int) -> None: ...
    def activate(self) -> None: ...
    def cancel(self) -> None: ...
    def delete(self) -> None: ...
    def apply(self) -> None: ...
    def hint(self) -> Keys:
        return []


NAV: Keys = [("Tab", "next page"), ("?", "help"), ("q", "quit")]


# --------------------------------------------------------------------------
# shared panels
# --------------------------------------------------------------------------
class FingersPanel(Panel):
    """The two hands with the chosen finger, plus the saved list when there is room."""

    def __init__(self, title: str, action: str = "save it", cta: bool = False, **kw):
        super().__init__(title, art.B_BLUE, **kw)
        self.action = action
        self.cta = cta

    def build(self, w, h):
        a = self.app
        f = a.sel_finger
        big_w, big_h = art.hands_size(big=True)
        big = w >= big_w + 4 and h >= big_h + (8 if self.cta else 4)
        hands = art.hands_lines(a.enrolled, f, big=big)
        hands_w = art.hands_size(big)[0]
        foot = [Text(), selection_line(f, a.enrolled)]
        if self.cta:
            b = Text(no_wrap=True)
            b.append(" Enter ", f"bold {BG} on {GREEN}")
            b.append(f"  {'save it again' if f in a.enrolled else 'save this finger'}", f"bold {GREEN}")
            foot += [Text(), b, Text(),
                     keys_line([("←→", "finger"), ("↑↓", "other hand"), ("d", "delete")])]
        else:
            foot.append(keys_line([("←→", "finger"), ("↑↓", "other hand"), ("Enter", self.action),
                                   ("d", "delete")]))
        side_w = min(34, w - hands_w - 6)
        if side_w >= 24:
            saved = [x for x in FINGERS if x in a.enrolled]
            side = [Text(f"Saved  {len(saved)} of 10", style=f"bold {FG}"), Text()]
            for x in saved:
                t = Text("● ", style=f"bold {GREEN}")
                t.append(pretty(x), FG)
                side.append(t)
            if not saved:
                side += wrap("None yet. Pick a finger and press Enter to save it.", side_w, DIM)
            elif len(saved) < 2:
                side += [Text()] + wrap("Tip: save a second finger in case one is sore or wet.", side_w, DIM)
            block_w = hands_w + 6 + side_w
            body = hcat([hands, side], [hands_w, side_w], gap=6)
            pad = Text(" " * max(0, (w - block_w) // 2))
            lines = [pad + ln for ln in body] + [pad + ln for ln in foot]
        else:
            lines = [art.centre(ln, w) for ln in hands] + [art.centre(ln, w) for ln in foot]
        top = max(0, (h - len(lines)) // 2)
        return [Text()] * top + lines


# --------------------------------------------------------------------------
# 1 Home
# --------------------------------------------------------------------------
def ordinal(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def try_numbers(attempts: list[Attempt]) -> list[int]:
    """1 for the first attempt of a session, 2 for the second... 0 = unknown session."""
    out, count = [], Counter()
    for a in attempts:
        if a.session < 0:
            out.append(0)
            continue
        count[a.session] += 1
        out.append(count[a.session])
    return out


def attempt_line(a: Attempt, nth: int, bar_w: int, time_w: int, wide_help: int = 0, day: str = "") -> Text:
    words, kind = plain_result(a.result)
    colour = KIND_COLOUR[kind]
    t = Text(no_wrap=True)
    when = a.time or "--:--:--"
    if time_w > 8:
        when = (a.date[5:] + " " + a.time[:5]) if a.date and a.date != day else when
    t.append(f"{when:<{time_w}} ", DIM)
    t.append(f"{ordinal(nth) if nth else '':<4} ", FG if nth == 1 else DIM)
    t.append_text(art.score_bar(a.best_score if a.scored else None, bar_w, colour, a.threshold))
    t.append(f" {a.best_score if a.scored else '':>6}  ", f"bold {FG}")
    t.append("✓ " if kind == "match" else "✗ " if kind == "nomatch" else "↻ ", f"bold {colour}")
    t.append(f"{words:<26}" if wide_help else words, f"bold {colour}" if kind != "retry" else colour)
    if wide_help and kind != "match":
        t.append(RESULT_HELP.get(a.result, ""), FAINT)
    return t


class TriesPanel(Panel):
    def build(self, w, h):
        atts = self.app.attempts
        if not atts:
            return [Text("No tries logged yet.", style=FG), Text(),
                    *wrap("Every fingerprint check (sudo, a password pop-up or the Test page) is logged by "
                          "the driver and shows up here with its score.", w, DIM), Text(),
                    keys_line([("t", "test a finger now")])]
        day = today()
        thr = display_threshold(atts)
        nths = try_numbers(atts)
        rows = max(1, h - 2)
        pairs = list(zip(atts, nths))[-rows:][::-1]
        time_w = 11 if any(a.date and a.date != day for a, _ in pairs) else 8
        fixed = time_w + 1 + 5 + 7 + 2 + 2          # time, try, score, gaps, mark
        result_w = 25
        bar_w = max(12, min(48, w - fixed - result_w))
        wide = w - fixed - bar_w - 28 >= 30
        head = Text(no_wrap=True)
        head.append(f"{'time':<{time_w}} {'try':<5}", DIM)
        head.append(f"{f'score (log scale, │ = {thr})':<{bar_w}}", DIM)
        head.append(f" {'':>6}    result", DIM)
        lines = [head]
        lines += [attempt_line(a, n, bar_w, time_w, wide, day) for a, n in pairs]
        for i in range(1, len(lines)):                 # long help text: end with an ellipsis
            if lines[i].cell_len > w:
                lines[i] = art.fit(lines[i], w - 1) + Text("…", style=FAINT)
        axis = Text(" " * (time_w + 6), no_wrap=True)
        axis.append_text(art.score_axis(bar_w, thr))
        if w - axis.cell_len >= 40:
            axis.append(f"         │ {thr} = the score a match needs", FAINT)
        lines.append(axis)
        self.border_subtitle = f"newest first · {len(atts)} in the log"
        return lines


TIPS = [
    "touch with the flat middle of the pad.",
    "cold or dry fingers score lower.",
    "lift your finger before sudo asks.",
    "save one finger as two for better odds.",
    "your password always works too.",
]


def _stat(label: str, value: str, caption: str, colour: str, big: bool) -> list[Text]:
    out = [Text(label, style=f"bold {DIM}", no_wrap=True)]
    if big:
        out += art.big_number(value, colour)
    else:
        out.append(Text(value, style=f"bold {colour}"))
    out.append(Text(caption, style=DIM, no_wrap=True))
    return out


class TodayPanel(Panel):
    tip_index = 0

    def build(self, w, h):
        st: Stats = summarise(self.app.attempts, today())
        thr = display_threshold(self.app.attempts)
        self.border_title = "Today" if st.scope == "today" else "Recent tries"
        self.border_subtitle = "" if st.scope == "today" else "none today"
        ft = st.first_try_pct
        stats = [
            ("1ST TRY", "-" if ft is None else f"{ft}%",
             f"{st.first_try} of {st.sessions}" if st.sessions else "no prompts",
             DIM if ft is None else (GREEN if ft >= 80 else ORANGE if ft >= 50 else RED)),
            ("MEDIAN", "-" if st.median_score is None else str(st.median_score),
             f"needs {thr}",
             DIM if st.median_score is None else (GREEN if st.median_score >= thr else RED)),
            ("TRIES", str(st.tries), f"{st.matches}✓ {st.nomatches}✗ {st.retries}↻", CYAN),
        ]
        colw = (w - 2) // 3
        big = all(art.big_number_width(v) <= colw for _, v, _, _ in stats) and h >= 9
        blocks = [_stat(lbl, v, cap, col, big) for lbl, v, cap, col in stats]
        lines = hcat(blocks, [colw] * 3, gap=1)
        if w >= 56 and st.sessions:
            lines.append(Text(f"first touch matched in {st.first_try} of {st.sessions} prompts"
                              + (f" · best score {st.best_score}" if st.best_score else ""), style=FAINT))
        actions = [keys_line([("e", "save a finger"), ("t", "test"), ("s", "settings"), ("?", "help")])]
        tip = [art.fit(Text("Tip: " + TIPS[self.tip_index % len(TIPS)], style=FAINT, no_wrap=True), w)]
        # what went wrong, in plain words, most common first
        why = Counter(plain_result(a.result) for a in st.attempts)
        wrong = [(words, n, kind) for (words, kind), n in why.most_common() if kind != "match"]
        room = h - len(lines) - len(actions) - len(tip)
        wrong_rows = min(len(wrong), max(0, room - 9)) if wrong else 0
        graph_rows = min(14, room - (wrong_rows + 2 if wrong_rows else 0) - 3)
        if st.attempts and graph_rows >= 3:
            items = []
            for a in st.attempts:
                _, kind = plain_result(a.result)
                items.append((a.best_score if a.scored else None, KIND_COLOUR[kind]))
            lines += [Text(), Text("score of each try, oldest → newest", style=DIM)]
            lines += art.score_columns(items, w, graph_rows, thr)
        if wrong_rows:
            lines += [Text(), Text("Missed tries", style=DIM)]
            for words, n, kind in wrong[:wrong_rows]:
                t = Text(f"{n:>3}× ", style=f"bold {KIND_COLOUR[kind]}")
                t.append(words, FG)
                lines.append(t)
        lines += [Text()] * max(0, h - len(lines) - len(actions) - len(tip))
        return lines + actions + tip


class Check(NamedTuple):
    """One row of the "This computer" panel. ok: True fine, False broken (shows `fix`), None unknown/off."""
    ok: bool | None
    label: str
    value: str
    fix: str = ""
    why: str = ""


def status_checks(s: Status, enrolled: set[str], opens) -> list[Check]:
    out = []
    out.append(Check(s.sensor_present, "Sensor", "found" if s.sensor_present else "not found",
                      "enable it in the BIOS, then: sudo goodix550c-ctl recover", "Goodix 27c6:550c on USB"))
    lib = (s.libfprint_version or "").split("+")[-1] if s.patched else "stock (no 550c support)"
    out.append(Check(s.patched, "Driver", lib or "patched",
                      "install the patched libfprint (see docs/RECOVERY.md)", "patched libfprint is installed"))
    out.append(Check(s.held, "Kept on update", "held" if s.held else "not held",
                      "sudo apt-mark hold libfprint-2-2", "apt keeps the patched one"))
    out.append(Check(s.psk_present, "Sensor key", {True: "installed", False: "missing",
                                                     None: "needs admin to check"}[s.psk_present],
                      "sudo goodix550c-ctl install-psk FILE", "pairing key, root only"))
    out.append(Check(s.store_ok, "Saved prints", "private" if s.store_ok else "readable by others",
                      "sudo goodix550c-ctl harden-store", "only root can read /var/lib/fprint"))
    if s.sensor_present and s.usb_power:
        out.append(Check(s.usb_power == "on", "USB power", "always on" if s.usb_power == "on" else
                          f"{s.usb_power} (may sleep)", "sudo goodix550c-ctl recover",
                          "no autosuspend, no missed touches"))
    if opens:
        o = opens[-1]
        good = o.result == "ok"
        out.append(Check(good, "Last start", f"ok in {o.ms} ms" if good else f"failed at {o.phase}",
                          "sudo goodix550c-ctl recover", f"sensor handshake at {o.time[:5]}" if o.time else
                          "sensor handshake"))
    pam = f"on · {s.pam_tries} tries · {s.pam_timeout} s" if s.pam_enabled else "off"
    out.append(Check(True if s.pam_enabled else None, "sudo & pop-ups", pam, "press s to turn it on",
                      "password still works"))
    out.append(Check(bool(enrolled), "Saved fingers", f"{len(enrolled)} of 10" if enrolled else "none",
                      "press e to save one", "see the hands"))
    return out


class StatusPanel(Panel):
    def build(self, w, h):
        a = self.app
        s = a.status
        if s is None:
            return [Text("looking...", style=DIM)]
        if s.ctl_missing:
            return [Text("✗ goodix550c-ctl not installed", style=f"bold {RED}"), Text(),
                    *wrap("The helper that reads the sensor state is missing, so nothing here can be checked.",
                          w, FG), Text(),
                    Text("→ sudo apt install goodix550c-fingerprint", style=ORANGE, no_wrap=True)]
        if s.error:
            return [Text("✗ Could not read the status", style=f"bold {RED}"), Text()] + wrap(s.error, w, RED) + \
                   [Text()] + wrap("Is goodix550c-fingerprint installed? Try: goodix550c-ctl status", w, DIM)
        checks = status_checks(s, a.enrolled, a.opens)
        bad = [c for c in checks if c.ok is False]
        head = Text(no_wrap=True)
        if not bad:
            head.append("✓ All good", f"bold {GREEN}")
            head.append("  - the fingerprint is ready to use" if s.pam_enabled else
                        "  - sudo is not using it yet (s)", DIM)
        else:
            head.append(f"✗ {len(bad)} thing{'s' if len(bad) > 1 else ''} to fix", f"bold {RED}")
            head.append("  - how, in orange", DIM)
        ncol = 2 if w >= 2 * 60 + 3 else 1
        colw = (w - 3 * (ncol - 1)) // ncol
        lw = 16
        vw = max(len(c.value) for c in checks) + 3
        show_why = colw >= 2 + lw + vw + max(len(c.why) for c in checks if c.ok is not False)

        def render(c: Check):
            ok, label, value, fix, why = c
            mark, ms = ("✓", f"bold {GREEN}") if ok else (("✗", f"bold {RED}") if ok is False else ("○", DIM))
            t = Text(no_wrap=True)
            t.append(mark + " ", ms)
            t.append(f"{label:<{lw}}", DIM)
            t.append(f"{value:<{vw}}" if show_why else value, (FG if ok else RED if ok is False else DIM))
            if show_why and ok is not False:
                t.append(why, FAINT)
            out = [t]
            if ok is False:
                out.append(Text("  → " + fix, style=ORANGE, no_wrap=True))
            return out

        rendered = [render(c) for c in checks]
        need = sum(len(r) for r in rendered)
        room = h - 2
        if ncol == 1 and need > room:                  # squeeze: fold the fine ones into one line
            fine = [c.label.lower() for c in checks if c.ok]
            rendered = [render(c) for c in checks if not c.ok]
            t = Text("✓ ", style=f"bold {GREEN}")
            t.append("fine: " + ", ".join(fine), DIM)
            rendered.append([t])
        flat = [ln for r in rendered for ln in r]
        if ncol == 2:
            half = (len(rendered) + 1) // 2
            left = [ln for r in rendered[:half] for ln in r]
            right = [ln for r in rendered[half:] for ln in r]
            flat = hcat([left, right], [colw, colw], gap=3)
        lines = [head, Text()] + flat
        extra = []
        if s.package_version or s.libfprint_version:
            ver = f"libfprint {s.libfprint_version.split(':')[-1] or '?'}"
            if len(ver) + 16 <= w:
                ver += f" · package {s.package_version or '?'}"
            extra.append(Text(ver, style=FAINT, no_wrap=True))
        if len(lines) + len(extra) + 1 <= h:
            lines += [Text()] * (h - len(lines) - len(extra)) + extra
        return lines


class HomePage(Page):
    DEFAULT_CSS = """
    HomePage .row { height: 1fr; }
    HomePage #home-r1 { height: 15; }
    HomePage .left { width: 3fr; min-width: 78; }
    HomePage .right { width: 2fr; min-width: 36; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="home-r1", classes="row"):
            yield FingersPanel("Your fingers", id="home-hands", classes="left")
            yield StatusPanel("This computer", art.B_GREEN, id="home-device", classes="right")
        with Horizontal(id="home-r2", classes="row"):
            yield TriesPanel("Recent tries", art.B_GOLD, id="home-attempts", classes="left")
            yield TodayPanel("Today", art.B_PURPLE, id="home-today", classes="right")

    def hint(self) -> Keys:
        return [("←→↑↓", "choose finger"), ("Enter", "save it"), ("d", "delete it"), ("e t s", "pages"),
                ("r", "refresh")] + NAV

    def move(self, dx, dy):
        self.app.move_selection(dx, dy)

    def activate(self):
        self.app.go_enroll(self.app.sel_finger)

    def delete(self):
        self.app.ask_delete()

    def on_show(self) -> None:
        TodayPanel.tip_index += 1
        self.sync(True)


# --------------------------------------------------------------------------
# shared run logic for Enroll / Test
# --------------------------------------------------------------------------
class RunPage(Page):
    """A page with a FingerprintView driven by an event stream."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._timer = None
        self._worker = None

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
        self.busy = False

    def on_unmount(self) -> None:
        self.stop_worker()


# How long the screen shows LIFT / TRY AGAIN before it asks for the next PRESS. The driver waits up to
# 1.5 s for the finger to leave the sensor (GOODIX_RESULT_FINGER_UP_WAIT_MS), so asking sooner would be
# refused as "finger already on sensor". fprintd-enroll prints no "finger is up" line, so time it is.
LIFT_TO_PRESS = 1.6         # after a good scan
RETRY_TO_PRESS = 1.6        # after a scan that did not count
REMOVE_TO_PRESS = 1.6       # after "remove and retry"

LEGEND = [("●", art.GREEN, "press"), ("●", art.ORANGE, "lift"), ("●", art.RED, "try again"),
          ("●", art.CYAN, "done")]


def legend_line() -> Text:
    t = Text(no_wrap=True)
    for i, (dot, col, word) in enumerate(LEGEND):
        if i:
            t.append("   ")
        t.append(dot + " ", col)
        t.append(word, DIM)
    return t


def steps_line(step: int, width: int, labels: list[str]) -> Text:
    """'1 Pick a finger ─── 2 Touch the sensor ─── 3 Saved' with the current step lit."""
    t = Text(no_wrap=True)
    for i, lab in enumerate(labels, 1):
        if i > 1:
            t.append("  ───  ", FAINT)
        if i < step:
            t.append(f" ✓ {lab} ", GREEN)
        elif i == step:
            t.append(f" {i} {lab} ", f"bold {BG} on {BLUE}")
        else:
            t.append(f" {i} {lab} ", DIM)
    return art.centre(t, width)


# --------------------------------------------------------------------------
# 2 Enroll
# --------------------------------------------------------------------------
class PreviewPanel(Panel):
    """Enroll page, step 1: what will happen, with a dim fingerprint."""

    def build(self, w, h):
        a = self.app
        stages = a.stages_hint
        many = f"~{stages}" if stages else "10-20"
        steps = [
            ("Touch when the print is", "green", GREEN),
            ("Lift when it turns", "orange", ORANGE),
            (f"Repeat {many}× until it is", "full", CYAN),
        ]
        text: list[Text] = []
        for i, (main, word, col) in enumerate(steps, 1):
            t = Text(no_wrap=True)
            t.append(f" {i} ", f"bold {BG} on {DIM}")
            t.append(f"  {main} ", FG)
            t.append(word, f"bold {col}")
            text.append(t)
            text.append(Text())
        text += wrap("Move your finger a little between touches.", w - 2, DIM)
        room = h - len(text) - 2
        fp: list[Text] = []
        if room >= 8:
            cols, rows = art.print_size(min(w - 4, 60), min(room, 28))
            fp = [art.centre(ln, w) for ln in art.fingerprint_lines(
                0.0, art.blend(FG, BG, 0.5), art.blend(FG, BG, 0.78), cols, rows)] + [Text(), Text()]
        tw = max((t.cell_len for t in text), default=0)
        pad = " " * max(0, (w - tw) // 2)
        body = fp + [Text(pad) + t for t in text]
        top = max(0, (h - len(body)) // 2)
        return [Text()] * top + body


# enroll events that end the run in an error screen: kind -> (big word, plain-English hint)
END_STATES = {
    "failed": ("FAILED", "Could not save this finger. Press Enter to try again."),
    "disconnected": ("NO SENSOR", "The sensor went away. Check it is plugged in, then press Enter to retry."),
    "full": ("FULL", "There is no room for another print. Delete one first (Esc, then d)."),
    "duplicate": ("ALREADY SAVED", "This fingerprint is already saved, maybe as another finger."),
}


class EnrollPage(RunPage):
    DEFAULT_CSS = """
    EnrollPage #enr-steps { height: 1; }
    EnrollPage #enr-pick { height: 1fr; }
    EnrollPage #enr-picker { width: 3fr; min-width: 78; }
    EnrollPage #enr-preview { width: 2fr; min-width: 36; }
    EnrollPage #enr-run { height: 1fr; border: round #4f8fd6; border-title-color: #4f8fd6;
                          border-title-style: bold; padding: 0 1; }
    """
    STEPS = ["Pick a finger", "Touch the sensor", "Saved"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.mode = "pick"          # pick | run | end
        self.finger = ""
        self.outcome = ""           # completed | failed | ...

    # progress lives in the view (it draws the pips); the page reads and writes it there
    @property
    def stage(self) -> int:
        return self._view().stage

    @stage.setter
    def stage(self, n: int) -> None:
        self._view().stage = n

    @property
    def stages(self) -> int:
        return self._view().stages

    def compose(self) -> ComposeResult:
        yield Static(id="enr-steps")
        with Horizontal(id="enr-pick"):
            yield FingersPanel("Save a fingerprint - which finger?", "start", cta=True, id="enr-picker")
            yield PreviewPanel("What will happen", art.B_GREEN, id="enr-preview")
        with Vertical(id="enr-run"):
            yield FingerprintView(id="enr-view")

    def on_mount(self) -> None:
        self._show_mode()
        self.refresh_view()

    def _show_mode(self):
        self.query_one("#enr-pick").display = self.mode == "pick"
        self.query_one("#enr-run").display = self.mode != "pick"
        self._steps()

    def _steps(self):
        step = 1 if self.mode == "pick" else (3 if self.outcome == "completed" else 2)
        w = self.size.width or 120
        self.query_one("#enr-steps", Static).update(steps_line(step, w, self.STEPS))
        run = self.query_one("#enr-run")
        if self.mode != "pick":
            run.border_title = (f"Saved your {pretty(self.finger)}" if self.outcome == "completed"
                                else f"Saving your {pretty(self.finger)}")
            colour = art.B_CYAN if self.outcome == "completed" else (RED if self.outcome else art.B_BLUE)
            run.styles.border = ("round", colour)
            run.styles.border_title_color = colour

    def on_resize(self, event) -> None:
        self._steps()

    def hint(self) -> Keys:
        if self.mode == "pick":
            return [("←→↑↓", "choose finger"), ("Enter", "start saving it"), ("d", "delete it")] + NAV
        if self.mode == "run":
            return [("", "Do what the big word says."), ("Esc", "stop")]
        if self.outcome == "completed":
            return [("Enter", "save another finger"), ("t", "test it"), ("Esc", "back"), ("q", "quit")]
        return [("Enter", "try again"), ("Esc", "back"), ("q", "quit")]

    def refresh_view(self) -> None:
        super().refresh_view()
        self._steps()

    # ---- keys
    def move(self, dx, dy):
        if self.mode == "pick":
            self.app.move_selection(dx, dy)

    def delete(self):
        if self.mode == "pick":
            self.app.ask_delete()

    def cancel(self):
        if self.mode == "run":
            self.stop_worker()
            self.mode = "pick"
            self.app.say("Stopped. Nothing was saved.")
        elif self.mode == "end":
            self.mode = "pick"
        self._show_mode()
        self.app.update_chrome()

    def activate(self):
        if self.mode == "pick":
            f = self.app.sel_finger
            if f in self.app.enrolled:
                self.app.push_screen(
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
                self.app.update_chrome()
            else:
                self.begin(self.finger)

    # ---- the run
    def begin(self, finger: str) -> None:
        self.finger = finger
        self.mode = "run"
        self.busy = True
        self.outcome = ""
        self._show_mode()
        v = self._view()
        v.grow_to(0.0)
        v.stage = v.stages = 0
        v.extra = [legend_line()]
        v.set("idle", "WAIT", "Getting the sensor ready...", 0.0, title="")
        self.app.update_chrome()
        self._worker = self.app.run_worker(self._run(finger), group="op", exclusive=True)

    def _view(self) -> FingerprintView:
        return self.query_one("#enr-view", FingerprintView)

    def _press(self, hint: str = "Press your finger flat on the sensor and hold still.") -> None:
        nxt = "Then lift it when the print turns orange." if self.stage == 0 else \
            "Shift it a little from last time, so the sensor sees new parts."
        self._view().set("press", "PRESS", hint, next_hint=nxt)

    async def _run(self, finger: str) -> None:
        be = self.app.backend
        try:
            n = self.app.stages_hint
            if not n:                       # not asked yet (or the ask failed)
                n = self.app.stages_hint = await be.num_stages()
            v = self._view()
            v.stages, v.stage = max(1, n), 0
            v.redraw()
            async for ev in be.enroll(finger):
                self._handle(ev)
                if self.outcome:
                    break
        finally:
            self.busy = False
        if not self.outcome:
            self._finish("failed", "ERROR", "The fingerprint program stopped unexpectedly. Press Enter to try again.", "error")
        await self.app.refresh_data()

    def _finish(self, outcome: str, word: str, hint: str, state: str, sub: str = "") -> None:
        self._cancel_timer()
        self.outcome = outcome
        self.mode = "end"
        self.busy = False
        v = self._view()
        if outcome == "completed":
            v.stage = v.stages
        v.set(state, word, hint, 1.0 if outcome == "completed" else None, sub=sub)
        self._steps()
        self.app.update_chrome()

    def _handle(self, ev) -> None:
        v = self._view()
        k = ev.kind
        if k == "started":
            self._press()
        elif k == "stage":
            self.stage += 1
            v.stage = self.stage
            v.set("lift", "LIFT", "Good. Lift your finger off the sensor.",
                  fill=min(1.0, self.stage / self.stages),
                  next_hint=f"{self.stages - self.stage} more touch{'es' if self.stages - self.stage != 1 else ''} to go.")
            self._later(LIFT_TO_PRESS, lambda: self._press() if self.mode == "run" else None)
        elif k in ("retry", "short", "not-centered"):
            msg = {"retry": "That touch was not clear. Press flat and keep still.",
                   "short": "That touch was too short. Hold your finger down a little longer.",
                   "not-centered": "Put the middle of your fingertip on the sensor."}[k]
            v.set("retry", "TRY AGAIN", msg, next_hint="This one did not count; nothing is lost.")
            self._later(RETRY_TO_PRESS,
                        lambda: self._press("Press your finger flat on the sensor again.") if self.mode == "run" else None)
        elif k == "remove":
            v.set("lift", "LIFT", "Lift your finger all the way off, then press again.")
            self._later(REMOVE_TO_PRESS, lambda: self._press() if self.mode == "run" else None)
        elif k == "completed":
            self._finish("completed", "DONE", "Saved! This finger is ready to use.",
                         "done", sub="Press t to test it, Enter to save another, or Esc to go back.")
            self.app.say(f"Saved your {pretty(self.finger)}.")
        elif k in END_STATES:
            word, hint = END_STATES[k]
            self._finish(k, word, hint, "error")
        elif k == "error":
            self._finish("error", "ERROR", (ev.message or "Something went wrong.")[:100] + "  Press Enter to retry.", "error")


# --------------------------------------------------------------------------
# 3 Test
# --------------------------------------------------------------------------
SCORE_POLLS = 4             # how often the Test page looks for the new attempt line
SCORE_TAIL = 20             # journal lines read per look (the new line is among the last few)


def _key(a: Attempt | None):
    return None if a is None else (a.time, tuple(sorted(a.fields.items())), a.best_score, a.result)


def score_block(a: Attempt, width: int) -> list[Text]:
    colour = KIND_COLOUR[plain_result(a.result)[1]]
    bw = max(16, min(48, width - 10))
    t = Text(no_wrap=True)
    t.append_text(art.score_bar(a.best_score if a.scored else None, bw, colour, a.threshold))
    t.append(f"  {a.best_score}" if a.scored else "", f"bold {colour}")
    return [t, art.score_axis(bw, a.threshold)]


class TestPage(RunPage):
    __test__ = False            # not a pytest class

    DEFAULT_CSS = """
    TestPage #tst-box { height: 1fr; border: round #39c5cf; border-title-color: #39c5cf;
                        border-title-style: bold; padding: 0 1; }
    TestPage #tst-view { height: 1fr; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.mode = "idle"          # idle | run | end
        self.result = ""            # match | no-match once a run has finished

    def compose(self) -> ComposeResult:
        with Vertical(id="tst-box"):
            yield FingerprintView(id="tst-view")

    def on_mount(self) -> None:
        self.query_one("#tst-box").border_title = "Test a fingerprint"
        self._view().show_bar = False
        self._idle()

    def _view(self) -> FingerprintView:
        return self.query_one("#tst-view", FingerprintView)

    def _recent(self) -> list[Text]:
        atts = self.app.attempts[-6:][::-1]
        if not atts:
            return []
        out = [Text("Last tries", style=f"bold {DIM}")]
        for a in atts:
            words, kind = plain_result(a.result)
            t = Text(no_wrap=True)
            t.append(f"{a.time[:5] or '--:--'}  ", FAINT)
            t.append(f"{a.best_score if a.scored else '':>6}  ", FG)
            t.append(words, KIND_COLOUR[kind])
            out.append(t)
        return out

    def _idle(self) -> None:
        self.mode = "idle"
        v = self._view()
        saved = [pretty(f).replace(" finger", "") for f in FINGERS if f in self.app.enrolled]
        sub = ("Saved: " + ", ".join(saved)) if saved else "No fingers saved yet - press e to save one."
        v.extra = self._recent()
        v.set("idle", "READY", "Press Enter, then touch the sensor with any saved finger.",
              0.0, title="Test a fingerprint", sub=sub)

    def on_show(self) -> None:
        self.stale = False
        if self.mode == "idle":
            self._idle()

    def refresh_view(self) -> None:
        if self.mode == "idle":
            self._view().extra = self._recent()
            self._view().redraw()

    def hint(self) -> Keys:
        if self.mode == "run":
            return [("", "Do what the big word says."), ("Esc", "stop")]
        return [("Enter", "start the test")] + NAV

    def cancel(self):
        if self.mode == "run":
            self.stop_worker()
            self._idle()
            self.app.say("Test stopped.")
            self.app.update_chrome()

    def activate(self):
        if self.mode == "run":
            return
        if not self.app.enrolled:
            self._view().set("error", "NO FINGERS", "No fingerprints are saved yet. Press e (Enroll) to save one first.", 0.0)
            return
        self.mode = "run"
        self.busy = True
        v = self._view()
        v.extra = []
        v.set("idle", "WAIT", "Getting the sensor ready...", 0.0, title="Testing", sub="")
        self.app.update_chrome()
        self._worker = self.app.run_worker(self._run(), group="op", exclusive=True)

    async def _score_after(self, before) -> Attempt | None:
        """The attempt line the driver logged for the touch that just finished (it lands a moment
        after fprintd reports the result), looked for in a short tail of the journal."""
        for _ in range(SCORE_POLLS):
            await asyncio.sleep(self.app.score_poll)
            attempts, _opens = await self.app.backend.journal(SCORE_TAIL)
            if attempts and _key(attempts[-1]) != before:
                return attempts[-1]
        return None

    async def _run(self) -> None:
        be = self.app.backend
        v = self._view()
        before_list, _ = await be.journal(SCORE_TAIL)
        before = _key(before_list[-1]) if before_list else None
        final = False
        press = "Touch the sensor with a saved finger and hold still."
        try:
            async for ev in be.verify():
                k = ev.kind
                if k == "started":
                    v.set("press", "PRESS", press, 1.0, title="Testing", sweep=True)
                elif k == "retry":
                    v.set("retry", "TRY AGAIN", "The sensor did not get a good read. Lift, then press again.",
                          title="Testing")
                    self._later(1.5, lambda: v.set("press", "PRESS", "Press your finger flat on the sensor again.",
                                                   title="Testing") if self.mode == "run" else None)
                elif k in ("match", "no-match"):
                    final = True
                    self._cancel_timer()
                    self.result = k
                    at = await self._score_after(before)
                    await self.app.refresh_data(with_status=False)     # Last tries / Home include this one
                    sub = ""
                    v.extra = []
                    if at is not None:
                        sub = f"Score {at.best_score}  (a match needs {at.threshold} or more)"
                        v.extra = score_block(at, 60)
                    recent = self._recent()
                    if recent:
                        v.extra = v.extra + [Text()] + recent
                    if k == "match":
                        v.set("match", "MATCH", "That finger is recognised. Press Enter to test again.", 1.0,
                              title="Result", sub=sub, sweep=True)
                    else:
                        v.set("nomatch", "NO MATCH", "That finger is not recognised. Press Enter to test again.",
                              1.0, title="Result", sub=sub, sweep=True,
                              next_hint="Wrong finger, or a different part of it? Try the flat middle of the pad.")
                    break
                elif k in ("disconnected", "error"):
                    final = True
                    self._cancel_timer()
                    word = "NO SENSOR" if k == "disconnected" else "ERROR"
                    v.set("error", word, (ev.message or "The sensor is not available.")[:100] + "  Press Enter to retry.",
                          0.0, title="Testing")
                    break
        finally:
            self.busy = False
        self.mode = "end" if final else "idle"
        if not final:
            self._idle()
        self.app.update_chrome()
        await self.app.refresh_data(with_status=False)


# --------------------------------------------------------------------------
# 4 Settings
# --------------------------------------------------------------------------
class FnPanel(Panel):
    """A panel whose lines come from a function (the Settings page draws both of its panels this way)."""

    def __init__(self, title: str, colour: str, fn, **kw):
        super().__init__(title, colour, **kw)
        self._fn = fn

    def build(self, w, h):
        return self._fn(w, h)


def sudo_timeline(tries: int, timeout: int, on: bool, width: int) -> list[Text]:
    """A picture of what sudo does with these settings."""
    top, bot = Text(no_wrap=True), Text(no_wrap=True)

    def box(label, style, under=""):
        top.append(f" {label} ", style)
        bot.append(f"{under:^{len(label) + 2}}", DIM)

    def arrow():
        top.append(" ─▶ ", FAINT)
        bot.append("    ")

    box("$ sudo", f"bold {BG} on {FAINT}")
    if on:
        for i in range(tries):
            arrow()
            box(f"touch {i + 1}" if tries <= 3 else f"{i + 1}", f"bold {BG} on {GREEN}", f"{timeout}s")
    arrow()
    box("password", f"bold {BG} on {BLUE}")
    if top.cell_len > width:
        top = Text(f"sudo → up to {tries} touches, {timeout} s each → password", style=FG)
        bot = Text()
    lines = [top, bot, Text()]
    if not on:
        return lines + wrap("Fingerprint is off: sudo asks for your password straight away.", width, DIM)
    return lines + wrap(f"Each touch waits up to {timeout} s. A match lets you in at once; after {tries} "
                        f"miss{'es' if tries > 1 else ''} or {tries * timeout} s at most, it asks for your "
                        "password instead.", width, DIM)


def settings_advice(attempts: list[Attempt], width: int, tries: int = 3, timeout: int = 15) -> list[Text]:
    """Honest hints from today's log: did prompts time out, or need many touches?"""
    st = summarise(attempts, today())
    if not st.attempts:
        return []
    timed = sum(1 for a in st.attempts if a.result == "retry:error")
    out = [Text("From your " + ("tries today" if st.scope == "today" else "recent tries"), style=f"bold {FG}"),
           Text()]
    t = Text(no_wrap=True)
    t.append(f"{timed}", f"bold {ORANGE if timed else GREEN}")
    t.append(" prompt" + ("s" if timed != 1 else "") + " cancelled or timed out", FG)
    out.append(t)
    if st.sessions:
        t = Text(no_wrap=True)
        t.append(f"{st.first_try} of {st.sessions}", f"bold {FG}")
        t.append(" matched on the first touch", FG)
        out.append(t)
    out.append(Text())
    if timed >= 2 and timeout < 20:
        out += wrap("Prompts often time out: a longer wait gives you more time to reach the sensor.", width, DIM)
    elif st.sessions and st.first_try < st.sessions * 0.6 and tries < 3:
        out += wrap("Many prompts need more than one touch: 3 or more tries is a good setting.", width, DIM)
    else:
        out += wrap("Looks fine: the current values suit how you use it.", width, DIM)
    return out


class SettingsPage(Page):
    DEFAULT_CSS = """
    SettingsPage { align: center top; }
    SettingsPage #set-row { height: 1fr; max-width: 170; }
    SettingsPage #set-form { width: 3fr; min-width: 70; }
    SettingsPage #set-side { width: 2fr; min-width: 36; }
    """
    ROW_TRIES, ROW_TIMEOUT, ROW_PAM, ROW_APPLY = range(4)
    TRIES_RANGE, TIMEOUT_RANGE = (1, 5), (5, 30)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.row = self.ROW_TRIES
        self.tries = 3
        self.timeout = 15
        self.pam = False
        self._loaded = False
        self._base: tuple[int, int, bool] | None = None     # what the last load put in the controls
        self._cmds: list[list[str]] = []                    # pending commands, worked out once per redraw
        self.message = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="set-row"):
            yield FnPanel("Settings (for sudo and system password pop-ups)", art.B_PURPLE, self.form_lines,
                          id="set-form")
            yield FnPanel("What will change", art.B_GOLD, self.side_lines, id="set-side")

    def on_mount(self) -> None:
        self.refresh_view()

    def hint(self) -> Keys:
        return [("↑↓", "choose"), ("←→", "change"), ("Enter/a", "apply"), ("r", "reload")] + NAV

    # ---- current system values (what Apply compares against)
    @property
    def edited(self) -> bool:
        """The user has moved a control since the last load: a background refresh must not undo that."""
        return self._base is not None and (self.tries, self.timeout, self.pam) != self._base

    def invalidate(self) -> None:
        """Forget the edits: the next status replaces the controls (after Apply, or on reload)."""
        self._loaded = False

    def load_from_status(self) -> bool:
        """Copy the system values into the controls unless the user is editing. True when it did."""
        s = self.app.status
        if s is None or s.error or (self._loaded and self.edited):
            return False
        values = (s.pam_tries, s.pam_timeout, bool(s.pam_enabled))
        changed = not self._loaded or values != self._base
        self.tries, self.timeout, self.pam = values
        self._base, self._loaded = values, True
        return changed

    def reload(self) -> None:
        self.invalidate()
        self.load_from_status()
        self.refresh_view()

    def pending_commands(self) -> list[list[str]]:
        s = self.app.status
        if s is None or s.error:
            return []
        values = (self.tries, self.timeout) != (s.pam_tries, s.pam_timeout)
        pam = self.pam != bool(s.pam_enabled)
        return self.app.backend.root_commands(self.tries if values else None, self.timeout if values else None,
                                              self.pam if pam else None)

    def move(self, dx, dy):
        if dy:
            self.row = (self.row + dy) % (self.ROW_APPLY + 1)
        elif dx:
            if self.row == self.ROW_TRIES:
                self.tries = min(self.TRIES_RANGE[1], max(self.TRIES_RANGE[0], self.tries + dx))
            elif self.row == self.ROW_TIMEOUT:
                self.timeout = min(self.TIMEOUT_RANGE[1], max(self.TIMEOUT_RANGE[0], self.timeout + dx))
            elif self.row == self.ROW_PAM:
                self.pam = not self.pam
        self.message = ""
        self.refresh_view()

    def activate(self):
        if self.row == self.ROW_PAM:
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
        self.app.push_screen(ConfirmScreen("Apply settings?", lines, yes="Run", no="Cancel", default_yes=True),
                             lambda ok: self.app.run_root(cmds) if ok else None)

    def refresh_view(self) -> None:
        self._cmds = self.pending_commands()
        super().refresh_view()

    def form_lines(self, w: int, h: int) -> list[Text]:
        t: list[Text] = []
        s = self.app.status
        lw = 36

        def row(i, label, value: Text, note: str):
            line = Text(no_wrap=True)
            cur = i == self.row
            line.append("▶ " if cur else "  ", f"bold {BLUE}")
            line.append(f"{label:<{lw}}", f"bold {WHITE}" if cur else FG)
            line.append_text(value)
            line.append(f"   {note}", DIM)
            t.append(line)

        def num(v, unit=""):
            x = Text(no_wrap=True)
            x.append(" ◀ ", DIM)
            x.append(f"{str(v) + unit:^6}", f"bold {CYAN}")
            x.append(" ▶ ", DIM)
            return x

        t += wrap("Fingerprint checks happen when sudo or a system pop-up asks for your password. "
                  "Your password always still works. The login screen and lock screen are not affected.", w, DIM)
        t.append(Text())
        on = Text("  ON  " if self.pam else " OFF  ",
                  style=f"bold {BG} on {GREEN}" if self.pam else f"bold {BG} on {art.GREY}")
        row(self.ROW_TRIES, "Fingerprint tries before password", num(self.tries), "1 - 5")
        t.append(Text())
        row(self.ROW_TIMEOUT, "Wait for a finger (seconds)", num(self.timeout, " s"), "5 - 30")
        t.append(Text())
        row(self.ROW_PAM, "Use fingerprint for sudo / pop-ups", on, "Enter or ←→ switches")
        t.append(Text())
        cmds = self._cmds
        line = Text(no_wrap=True)
        line.append("▶ " if self.row == self.ROW_APPLY else "  ", f"bold {BLUE}")
        line.append(" Apply ", f"bold {BG} on {BLUE}" if cmds else f"bold {DIM} on {art.TRACK}")
        line.append("   needs your admin password" if cmds else "   nothing changed yet", DIM)
        t.append(line)
        for c in cmds:
            t.append(Text("    $ " + " ".join(c), style=f"bold {ORANGE}", no_wrap=True))
        if self.message:
            t += [Text()] + wrap(self.message, w, f"bold {ORANGE}")
        if s is None or s.error:
            t += [Text(), Text("Could not read the current settings.", style=RED)]
        t += [Text(), Text("What happens when you type sudo", style=f"bold {FG}"), Text()]
        t += sudo_timeline(self.tries, self.timeout, self.pam, w)
        adv = settings_advice(self.app.attempts, w, self.tries, self.timeout)
        if adv and len(t) + len(adv) + 2 <= h:
            t += [Text(), Text()] + adv
        return t

    def side_lines(self, w: int, h: int) -> list[Text]:
        s = self.app.status
        t: list[Text] = []
        if s is None or s.error:
            return [Text("Could not read the current settings.", style=RED)]
        t.append(Text("Now on this computer", style=f"bold {FG}"))
        t.append(kv("sudo & pop-ups", "on" if s.pam_enabled else "off", GREEN if s.pam_enabled else DIM))
        t.append(kv("tries", s.pam_tries))
        t.append(kv("wait", f"{s.pam_timeout} s"))
        t.append(Text())
        if self._cmds:
            t.append(Text("Pending", style=f"bold {ORANGE}"))
            t += wrap("Apply runs the orange command on the left. The screen switches to the normal terminal "
                      "so sudo can ask for your password, then comes straight back.", w, DIM)
        else:
            t.append(Text("Nothing changed.", style=DIM))
            t.append(Text())
            t += wrap("Change a value on the left; the exact command that Apply runs appears under the "
                      "button first.", w, DIM)
        t.append(Text())
        t += wrap("Settings are kept in /etc/goodix550c/pam.conf and survive package upgrades.", w, FAINT)
        return t


# --------------------------------------------------------------------------
# 5 Help
# --------------------------------------------------------------------------
HELP_LEFT = """\
The big picture
  The fingerprint shows what the sensor wants:
    GREEN   PRESS        touch and hold still
    ORANGE  LIFT         take your finger off
    RED     TRY AGAIN    did not count, touch again
    CYAN    DONE/MATCH   all good
  Do what the big word says; it never asks for two
  things at once. While saving, the print fills up
  ridge by ridge, one step per good touch.

Pages (press the number or letter)
  1      Home       status, fingers, recent tries
  2  e   Enroll     pick a finger, touch until DONE
  3  t   Test       touch, see MATCH and the score
  4  s   Settings   tries and wait time for sudo
  5  ?   Help       this page
"""
HELP_RIGHT = """\
Keys
  arrows / h j k l   hands: left/right = next finger,
                     up/down = same finger, other hand
  Enter              choose / start
  Esc                stop what is running, or go back
  d                  delete the chosen finger (asks)
  r                  reload        Tab  next page
  q                  quit

Good to know
  A match needs a score of {threshold} or more. Scores use a
  log scale: {threshold}-{normal_top} is a normal match, 1000+ great.
  System settings ask for your admin password in the
  normal terminal; the app comes back afterwards.
  Nothing here can lock you out: your password
  always works.   Try it without a sensor:
  finger --demo
"""


class HelpPanel(Panel):
    WORDS = {"GREEN": GREEN, "ORANGE": ORANGE, "RED": RED, "CYAN": CYAN}

    def build(self, w, h):
        def style(block: str) -> list[Text]:
            out = []
            for ln in block.splitlines():
                if ln and not ln.startswith(" "):
                    out.append(Text(ln, style=f"bold {CYAN}"))
                    continue
                t = Text(ln, style=FG)
                for word, col in self.WORDS.items():
                    i = ln.find("    " + word)
                    if i >= 0:
                        t.stylize(f"bold {col}", i + 4, i + 4 + 21)
                out.append(t)
            return out
        thr = display_threshold(self.app.attempts)
        left = style(HELP_LEFT)
        right = style(HELP_RIGHT.format(threshold=thr, normal_top=2 * thr))
        head = [Text("finger - how to use it", style=f"bold {WHITE}"), Text()]
        foot = [Text(), Text("Press 1 to go back.", style=DIM)]
        if w >= 112:
            body = hcat([head + left + foot, [Text()] * 2 + right], [54, 54], gap=4)
            bw = 112
        else:
            body = head + left + [Text()] + right + foot
            bw = 54
        pad = Text(" " * max(0, (w - bw) // 2))
        lines = [pad + ln for ln in body]
        top = max(0, (h - len(lines)) // 3)
        return [Text()] * top + lines


class HelpPage(Page):
    def compose(self) -> ComposeResult:
        yield HelpPanel("Help", art.B_BLUE, id="help-box")

    def hint(self) -> Keys:
        return [("1-4", "pages"), ("Tab", "next page"), ("q", "quit")]

    def on_show(self) -> None:
        self.query_one(HelpPanel).draw()
