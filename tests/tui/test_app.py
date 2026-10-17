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
        assert "All good" in t and "3 tries · 15 s" in t
        assert "LEFT HAND" in t and "RIGHT HAND" in t
        assert "right index finger" in t and "saved" in t
        assert "Recent tries" in t and "no match" in t and "log scale" in t
        assert "Today" in t and "1ST TRY" in t and "MEDIAN" in t
        assert "q quit" in t
    run(sc)


def test_home_uses_plain_english_not_driver_codes():
    async def sc(app, pilot, be):
        t = screen_text(app)
        for jargon in ("identify", "retry (", "retry:", "finger-present", "too-short", "remove-finger"):
            assert jargon not in t, jargon
        assert "lifted too fast" in t and "cancelled / timed out" in t
        assert "1st" in t and "2nd" in t                    # which try of that prompt
    run(sc)


def test_home_status_shows_fix_for_a_problem():
    async def sc(app, pilot, be):
        be.held = False
        await app.refresh_data()
        await pilot.pause(0.05)
        t = screen_text(app)
        assert "1 thing to fix" in t and "not held" in t
        assert "sudo apt-mark hold libfprint-2-2" in t
    run(sc)


def test_letter_keys_jump_to_pages():
    async def sc(app, pilot, be):
        await pilot.press("t")
        assert app.page == 3
        await pilot.press("s")
        assert app.page == 4
        await pilot.press("e")
        assert app.page == 2
        await pilot.press("1")
        assert app.page == 1
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
        await until(pilot, lambda: fv.shown == 1.0)         # the fill animation ends full
        assert not fv.animating and fv.stage == fv.stages == 6
        await pilot.pause(0.1)
        assert "100%" in screen_text(app) and "Scan 6 of 6" in screen_text(app)
        assert "right-middle-finger" in be.enrolled
        await until(pilot, lambda: "right-middle-finger" in app.enrolled)
        await pilot.press("enter")                          # save another -> back to the hands
        assert enroll.mode == "pick"
    run(sc, stages=6, step=0.05)


def test_enroll_stage_grows_smoothly_not_in_a_jump():
    async def sc(app, pilot, be):
        be.enroll_script = ["stage", "wait"]
        await pilot.press("2", "right", "enter")
        enroll = app.query_one("#page2")
        fv = view(app, "#enr-view")
        await until(pilot, lambda: enroll.stage == 1)
        assert fv.fill == 0.25                              # the target: 1 of 4
        assert fv.animating and fv.shown < fv.fill          # still growing towards it
        samples = []
        while fv.animating:
            samples.append(fv.shown)
            await pilot.pause(0.03)
        assert fv.shown == 0.25
        assert len(set(samples)) >= 4                       # several in-between frames
        assert samples == sorted(samples)
        await pilot.press("escape")
    run(sc, step=0.05, stages=4)


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
        states = []
        orig = fv.set

        def spy(state, word, *a, **kw):
            orig(state, word, *a, **kw)
            states.append((state, word))
        fv.set = spy
        await pilot.press("enter")
        await until(pilot, lambda: page.mode == "end")
        assert ("press", "PRESS") in states and ("retry", "TRY AGAIN") in states
        assert (fv.state, fv.word) == ("match", "MATCH")
        await until(pilot, lambda: fv.shown == 1.0)        # the result sweep ends full
        await pilot.pause(0.05)
        assert "Score 318" in screen_text(app) and "150" in screen_text(app)
        await pilot.press("enter")                         # second run: no-match
        await until(pilot, lambda: page.mode == "end" and fv.word == "NO MATCH")
        await pilot.pause(0.05)
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


def test_refresh_skips_hidden_pages_and_redraws_them_when_shown():
    async def sc(app, pilot, be):
        await pilot.press("3")
        await pilot.pause(0.1)
        home = app.query_one("#page1")
        calls = []
        orig = home.refresh_view
        home.refresh_view = lambda: (calls.append(1), orig())
        be.held = False
        await app.refresh_data()
        assert calls == [] and home.stale                  # hidden: only marked
        await pilot.press("1")
        await until(pilot, lambda: "1 thing to fix" in screen_text(app))
        assert calls and not home.stale                    # redrawn when shown
    run(sc)


def test_refresh_does_nothing_when_data_is_unchanged():
    async def sc(app, pilot, be):
        await pilot.pause(0.1)
        calls = []
        app.refresh_pages = lambda: calls.append(1)
        await app.refresh_data()
        await app.refresh_data(with_status=False)
        assert calls == []
        be.tries = 4
        await app.refresh_data()
        assert calls == [1]
    run(sc)


def test_background_tick_reads_status_only_every_30_seconds():
    async def sc(app, pilot, be):
        before = be.status_calls
        app._status_at = time.monotonic()                  # status was just read
        app._tick()
        await pilot.pause(0.1)
        assert be.status_calls == before and be.journal_sizes
        app._status_at = time.monotonic() - 31
        app._tick()
        await until(pilot, lambda: be.status_calls == before + 1)
    run(sc)


def test_tick_is_skipped_for_help_and_dialogs():
    async def sc(app, pilot, be):
        await pilot.press("5")
        await pilot.pause(0.1)
        n = len(be.journal_sizes)
        app._tick()
        await pilot.pause(0.1)
        assert len(be.journal_sizes) == n                  # Help is showing
        await pilot.press("1", "d")                        # dialog open
        n = len(be.journal_sizes)
        app._tick()
        await pilot.pause(0.1)
        assert len(be.journal_sizes) == n
    run(sc)


def test_settings_edits_survive_a_background_refresh():
    async def sc(app, pilot, be):
        await pilot.press("4", "right")                    # tries 3 -> 4, not applied
        st = app.query_one("#page4")
        assert st.tries == 4 and st.edited
        be.timeout = 20                                    # the system changes underneath
        await app.refresh_data()
        assert app.status.pam_timeout == 20
        assert st.tries == 4 and st.timeout == 15          # edits kept, nothing clobbered
        await pilot.press("r")                             # reload: now the system values win
        await until(pilot, lambda: st.timeout == 20)
        assert st.tries == 3 and not st.edited
        be.tries = 2                                       # untouched controls follow the system
        await app.refresh_data()
        assert st.tries == 2
    run(sc)


def test_threshold_comes_from_the_latest_attempt():
    async def sc(app, pilot, be):
        assert "│ = 150" in screen_text(app) and "needs 150" in screen_text(app)
        be.lines.append(be.lines[-1].replace("threshold=150", "threshold=200"))
        await app.refresh_data()
        await pilot.pause(0.05)
        t = screen_text(app)
        assert "│ = 200" in t and "needs 200" in t and "│ = 150" not in t
        await pilot.press("5")
        assert "score of 200 or more" in screen_text(app)
    run(sc)


def test_home_says_when_ctl_is_not_installed():
    async def sc(app, pilot, be):
        be.ctl_missing = True
        await app.refresh_data()
        await pilot.pause(0.05)
        t = screen_text(app)
        assert "goodix550c-ctl not installed" in t and "apt install goodix550c-fingerprint" in t
    run(sc)


def test_enroll_end_states_table():
    from goodix550c_tui.pages import END_STATES
    assert {k: w for k, (w, _) in END_STATES.items()} == {
        "failed": "FAILED", "disconnected": "NO SENSOR", "full": "FULL", "duplicate": "ALREADY SAVED"}
    assert all(h.endswith(".") or h.endswith(")") for _, h in END_STATES.values())


def test_enroll_uses_the_cached_stage_count_and_pauses_before_press():
    from goodix550c_tui.pages import LIFT_TO_PRESS, REMOVE_TO_PRESS, RETRY_TO_PRESS

    async def sc(app, pilot, be):
        await until(pilot, lambda: app.stages_hint == 4)
        calls = []
        orig = be.num_stages

        async def counting():
            calls.append(1)
            return await orig()
        be.num_stages = counting
        be.enroll_script = ["stage", "wait"]
        await pilot.press("2", "right", "enter")
        enroll = app.query_one("#page2")
        await until(pilot, lambda: enroll.stage == 1)
        assert calls == [] and enroll.stages == 4          # not asked again
        await pilot.press("escape")
    run(sc, step=0.05, stages=4)
    assert min(LIFT_TO_PRESS, RETRY_TO_PRESS, REMOVE_TO_PRESS) >= 1.5   # driver's finger-up wait


def test_test_page_polls_a_small_journal_window():
    async def sc(app, pilot, be):
        await pilot.press("3", "enter")
        await until(pilot, lambda: app.query_one("#page3").mode == "end")
        small = [n for n in be.journal_sizes if n != 200]
        assert small and max(small) <= 20
    run(sc, step=0.02)


def test_fingerprint_view_caches_text_and_redraws_blink_only_on_phase_change():
    async def sc(app, pilot, be):
        await pilot.press("3")
        fv = view(app, "#tst-view")
        fv.set("lift", "LIFT", "Lift your finger.")
        assert fv._column(60, 30) is fv._column(60, 30)            # static text built once
        first = fv._column(60, 30)
        fv.set("lift", "LIFT", "Lift your finger now.")
        assert fv._column(60, 30) is not first                      # a changed key rebuilds it
        draws = []
        orig = fv.redraw
        fv.redraw = lambda: (draws.append(1), orig())
        fv._state_t = time.monotonic()
        orig()
        for _ in range(5):
            fv._frame()
        assert draws == []                                          # same 0.4 s phase: no redraw
        fv._state_t -= 0.45
        fv._frame()
        assert draws == [1]
    run(sc)
