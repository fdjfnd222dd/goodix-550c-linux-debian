"""Pilot tests: the whole app on the fake backend (no sensor, no fprintd, no sudo)."""
import asyncio
import time

from goodix550c_tui.app import FingerApp
from goodix550c_tui.demo import FakeBackend
from goodix550c_tui.parsers import FINGERS

SIZE = (130, 40)


def screen_text(app) -> str:
    return "\n".join(s.text.rstrip() for s in app.screen._compositor.render_strips())


async def until(pilot, cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        await pilot.pause(0.02)
    raise AssertionError("condition not reached in time")


def run(scenario, **be_kw):
    be_kw.setdefault("step", 0.01)

    async def go():
        be = FakeBackend(**be_kw)
        app = FingerApp(backend=be, score_poll=0.01)
        async with app.run_test(size=SIZE) as pilot:
            await until(pilot, lambda: app.status is not None)
            await scenario(app, pilot, be)

    asyncio.run(go())


def view(app, vid):
    return app.query_one(vid)


def test_home_shows_status_hands_and_attempts():
    async def sc(app, pilot, be):
        t = screen_text(app)
        assert "1 Home" in t and "5 Help" in t and "DEMO" in t
        assert "Sensor" in t and "found" in t and "held" in t
        assert "3 tries, 15s" in t
        assert "LEFT HAND" in t and "RIGHT HAND" in t
        assert t.count("●") == 3 and "2 of 10" in t        # two enrolled fingers + the "● saved" legend
        assert "right index finger" in t and "saved" in t
        assert "match" in t and "(│ = needed)" in t
        assert t.count("identify") == 10                    # last 10 only
        assert "q quit" in t
    run(sc)


def test_page_navigation_keys():
    async def sc(app, pilot, be):
        for key, name in (("2", "Save a fingerprint"), ("3", "Test a fingerprint"),
                          ("4", "Settings (for sudo"), ("5", "how to use it"), ("1", "Your fingers")):
            await pilot.press(key)
            assert name in screen_text(app), key
        await pilot.press("tab")
        assert app.page == 2
        for _ in range(4):
            await pilot.press("tab")
        assert app.page == 1                               # wraps
        await pilot.press("question_mark")
        assert app.page == 5
        await pilot.press("question_mark")
        assert app.page == 1
    run(sc)


def test_quit_key():
    async def go():
        app = FingerApp(backend=FakeBackend(step=0.01))
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("q")
            await pilot.pause(0.1)
        assert app.return_code in (0, None)
    asyncio.run(go())


def test_hands_picker_moves_and_mirrors():
    async def sc(app, pilot, be):
        assert app.sel_finger == "right-index-finger"
        await pilot.press("right")
        assert app.sel_finger == "right-middle-finger"
        await pilot.press("l")
        assert app.sel_finger == "right-ring-finger"
        await pilot.press("h")
        await pilot.press("left")
        assert app.sel_finger == "right-index-finger"
        await pilot.press("up")                             # same finger, other hand
        assert app.sel_finger == "left-index-finger"
        await pilot.press("j")
        assert app.sel_finger == "right-index-finger"
        for _ in range(15):
            await pilot.press("right")
        assert app.sel_finger == FINGERS[-1]               # clamps at the right edge
        for _ in range(15):
            await pilot.press("h")
        assert app.sel_finger == FINGERS[0]                # and at the left edge
    run(sc)


def test_selection_is_highlighted_in_markup():
    async def sc(app, pilot, be):
        svg = app.export_screenshot()
        assert "#4ea1ff" in svg
        assert "Chosen finger" in screen_text(app)
    run(sc)


def test_home_enter_goes_to_enroll_with_that_finger():
    async def sc(app, pilot, be):
        await pilot.press("right", "enter")                 # right middle finger, not saved
        assert app.page == 2 and app.sel_finger == "right-middle-finger"
    run(sc)


def test_enroll_fills_to_100_and_shows_done():
    async def sc(app, pilot, be):
        fv = view(app, "#enr-view")
        seen_states, seen_fill = [], []
        orig = fv.set

        def spy(state, word, *a, **kw):
            orig(state, word, *a, **kw)
            seen_states.append((state, word))
            seen_fill.append(fv.fill)
        fv.set = spy
        await pilot.press("2", "right", "enter")           # right middle finger
        enroll = app.query_one("#page2")
        await until(pilot, lambda: enroll.mode == "end")
        assert enroll.outcome == "completed"
        assert fv.fill == 1.0 and (fv.state, fv.word) == ("done", "DONE")
        assert seen_fill == sorted(seen_fill)               # only ever fills up
        assert ("press", "PRESS") in seen_states and ("lift", "LIFT") in seen_states
        assert ("retry", "TRY AGAIN") in seen_states        # the demo script includes a retry
        assert seen_states[-1] == ("done", "DONE")
        assert "100%" in screen_text(app)
        assert "right-middle-finger" in be.enrolled
        await until(pilot, lambda: "right-middle-finger" in app.enrolled)
        await pilot.press("enter")                          # save another -> back to the hands
        assert enroll.mode == "pick"
    run(sc, stages=6, step=0.05)


def test_enroll_progress_is_stage_over_total():
    async def sc(app, pilot, be):
        be.enroll_script = ["stage", "stage"]
        await pilot.press("2", "right", "enter")
        enroll = app.query_one("#page2")
        await until(pilot, lambda: enroll.stage == 2)
        assert abs(view(app, "#enr-view").fill - 0.25) < 1e-9     # 2 of 8
        be.enroll_script = None
        await pilot.press("escape")
    run(sc, step=0.05, stages=8)


def test_enroll_failure_states():
    cases = {"failed": "FAILED", "full": "FULL", "duplicate": "ALREADY SAVED", "disconnected": "NO SENSOR"}

    async def sc(app, pilot, be):
        for kind, word in cases.items():
            be.enroll_script = ["stage", kind]
            await pilot.press("2")
            enroll = app.query_one("#page2")
            if enroll.mode == "pick":
                await pilot.press("right", "enter")
            else:
                await pilot.press("enter")
            await until(pilot, lambda: enroll.mode == "end")
            fv = view(app, "#enr-view")
            assert (fv.state, fv.word) == ("error", word), kind
            assert fv.fill < 1.0
            await pilot.press("escape")
            assert enroll.mode == "pick"
            await pilot.press("1")
    run(sc)


def test_enroll_replace_existing_asks_first_and_escape_cancels():
    async def sc(app, pilot, be):
        await pilot.press("2", "enter")                     # right index finger is saved already
        assert "Replace this fingerprint?" in screen_text(app)
        await pilot.press("n")
        assert app.query_one("#page2").mode == "pick"
        await pilot.press("enter")
        await pilot.press("left", "enter")                  # choose "Replace", confirm
        await until(pilot, lambda: app.query_one("#page2").mode == "run")
        await pilot.press("escape")
        assert app.query_one("#page2").mode == "pick"
        assert "Stopped" in screen_text(app)
    run(sc, step=0.2)


def test_cannot_leave_page_while_enrolling():
    async def sc(app, pilot, be):
        await pilot.press("2", "right", "enter")
        await until(pilot, lambda: app.query_one("#page2").mode == "run")
        await pilot.press("1")
        assert app.page == 2
        assert "Finish or stop" in screen_text(app)
        await pilot.press("escape")
        await pilot.press("1")
        assert app.page == 1
    run(sc, step=0.2)


def test_verify_match_and_no_match_states():
    async def sc(app, pilot, be):
        await pilot.press("3")
        page = app.query_one("#page3")
        fv = view(app, "#tst-view")
        assert (fv.state, fv.word) == ("idle", "READY")
        await pilot.press("enter")
        states = set()
        end = time.monotonic() + 8
        while page.mode != "end" and time.monotonic() < end:
            states.add((fv.state, fv.word))
            await pilot.pause(0.005)
        await until(pilot, lambda: page.mode == "end")
        assert ("press", "PRESS") in states and ("retry", "TRY AGAIN") in states
        assert (fv.state, fv.word) == ("match", "MATCH")
        assert "Score 318" in screen_text(app) and "150" in screen_text(app)
        await pilot.press("enter")                         # second run: no-match
        await until(pilot, lambda: page.mode == "end" and fv.word == "NO MATCH")
        assert fv.state == "nomatch" and "Score 88" in screen_text(app)
    run(sc, step=0.08)


def test_verify_needs_a_saved_finger():
    async def sc(app, pilot, be):
        await pilot.press("3", "enter")
        fv = view(app, "#tst-view")
        assert fv.word == "NO FINGERS" and app.query_one("#page3").mode == "idle"
    run(sc, enrolled=[])


def test_verify_escape_stops():
    async def sc(app, pilot, be):
        await pilot.press("3", "enter")
        page = app.query_one("#page3")
        await until(pilot, lambda: page.mode == "run")
        await pilot.press("escape")
        assert page.mode == "idle" and view(app, "#tst-view").word == "READY"
    run(sc, step=0.3)


def test_settings_clamp_and_validate():
    async def sc(app, pilot, be):
        await pilot.press("4")
        st = app.query_one("#page4")
        assert (st.tries, st.timeout, st.pam) == (3, 15, True)
        for _ in range(10):
            await pilot.press("right")
        assert st.tries == 5
        for _ in range(10):
            await pilot.press("left")
        assert st.tries == 1
        await pilot.press("down")
        for _ in range(40):
            await pilot.press("right")
        assert st.timeout == 30
        for _ in range(40):
            await pilot.press("left")
        assert st.timeout == 5
        from goodix550c_tui.parsers import validate_settings
        assert validate_settings(st.tries, st.timeout) == ""
    run(sc)


def test_settings_nothing_to_apply():
    async def sc(app, pilot, be):
        await pilot.press("4", "a")
        assert "Nothing to apply" in screen_text(app)
        assert be.privileged == []
    run(sc)


def test_settings_apply_shows_exact_command_then_runs():
    async def sc(app, pilot, be):
        await pilot.press("4", "right", "right", "down", "left", "left", "left")   # tries 5, timeout 12
        t = screen_text(app)
        assert "sudo goodix550c-ctl pam set --tries 5 --timeout 12" in t
        await pilot.press("down", "down", "enter")                                  # Apply button
        t = screen_text(app)
        assert "Apply settings?" in t and "sudo goodix550c-ctl pam set --tries 5 --timeout 12" in t
        assert be.privileged == []                                                  # nothing ran yet
        await pilot.press("enter")                                                  # default answer: Run
        await until(pilot, lambda: be.privileged)
        assert be.privileged == [[["sudo", "goodix550c-ctl", "pam", "set", "--tries", "5", "--timeout", "12"]]]
        await until(pilot, lambda: app.status.pam_tries == 5)
        assert (app.status.pam_tries, app.status.pam_timeout) == (5, 12)
        assert "Settings applied" in screen_text(app)
    run(sc)


def test_settings_toggle_off_runs_disable_and_cancel_runs_nothing():
    async def sc(app, pilot, be):
        await pilot.press("4", "down", "down", "enter")    # toggle sudo/polkit
        st = app.query_one("#page4")
        assert st.pam is False
        await pilot.press("a")
        assert "sudo goodix550c-ctl pam disable" in screen_text(app)
        await pilot.press("escape")                         # cancel
        assert be.privileged == []
        await pilot.press("a", "y")
        await until(pilot, lambda: be.privileged)
        assert be.privileged[0] == [["sudo", "goodix550c-ctl", "pam", "disable"]]
        await until(pilot, lambda: app.status.pam_enabled is False)
    run(sc)


def test_delete_needs_confirmation():
    async def sc(app, pilot, be):
        assert "right-index-finger" in be.enrolled
        await pilot.press("d")
        assert "Delete this fingerprint?" in screen_text(app)
        await pilot.press("n")
        assert "right-index-finger" in be.enrolled
        await pilot.press("d", "left", "enter")             # choose "Delete it"
        await until(pilot, lambda: "right-index-finger" not in be.enrolled)
        await until(pilot, lambda: "right-index-finger" not in app.enrolled)
        assert "Deleted your right index finger" in screen_text(app)
        await pilot.press("d")                              # nothing saved there now
        assert "nothing to delete" in screen_text(app)
    run(sc)


def test_delete_from_enroll_page_and_failure():
    async def sc(app, pilot, be):
        be.fail_delete = True
        await pilot.press("2", "d", "y")
        await until(pilot, lambda: "Could not delete" in screen_text(app))
        assert "right-index-finger" in be.enrolled
    run(sc, )


def test_modal_blocks_page_keys():
    async def sc(app, pilot, be):
        await pilot.press("d")
        await pilot.press("3", "tab", "q")
        assert app.page == 1 and "Delete this fingerprint?" in screen_text(app)
    run(sc)


def test_small_terminal_still_renders():
    async def go():
        app = FingerApp(backend=FakeBackend(step=0.4), score_poll=0.01)
        async with app.run_test(size=(100, 28)) as pilot:
            await until(pilot, lambda: app.status is not None)
            await pilot.press("2", "right", "enter")
            await pilot.pause(0.6)
            t = screen_text(app)
            assert "Saving your right middle finger" in t and ("PRESS" in t or "LIFT" in t or "█" in t)
            await pilot.press("escape")
    asyncio.run(go())
