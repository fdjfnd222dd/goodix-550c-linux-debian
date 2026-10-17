from goodix550c_tui import parsers as p


def test_enroll_lines():
    cases = {
        "Enroll result: enroll-stage-passed": "stage",
        "Enroll result: enroll-retry-scan": "retry",
        "Enroll result: enroll-swipe-too-short": "short",
        "Enroll result: enroll-finger-not-centered": "not-centered",
        "Enroll result: enroll-remove-and-retry": "remove",
        "Enroll result: enroll-completed": "completed",
        "Enroll result: enroll-failed": "failed",
        "Enroll result: enroll-disconnected": "disconnected",
        "Enroll result: enroll-data-full": "full",
        "Enroll result: enroll-duplicate": "duplicate",
        "Enroll result: enroll-unknown-error": "error",
    }
    for line, kind in cases.items():
        assert p.parse_enroll_line(line + "\n").kind == kind, line
    assert p.parse_enroll_line("Enrolling right-index-finger finger.").kind == "started"
    assert p.parse_enroll_line("Using device /net/reactivated/Fprint/Device/0") is None
    assert p.parse_enroll_line("") is None
    e = p.parse_enroll_line("Impossible to enroll: GDBus.Error:net.reactivated.Fprint.Error.AlreadyInUse: Device was already claimed")
    assert e.kind == "error" and "claimed" in e.message
    # an unknown retry flavour is still just a retry
    assert p.parse_enroll_line("Enroll result: enroll-retry-whatever").kind == "retry"


def test_verify_lines():
    assert p.parse_verify_line("Verify started!").kind == "started"
    assert p.parse_verify_line("Verify result: verify-match (done)").kind == "match"
    assert p.parse_verify_line("Verify result: verify-no-match (done)").kind == "no-match"
    # "(not done)" is only a retry, never a final answer
    assert p.parse_verify_line("Verify result: verify-no-match (not done)").kind == "retry"
    ev = p.parse_verify_line("Verify result: verify-retry-scan (not done)")
    assert ev.kind == "retry" and ev.done is False
    assert p.parse_verify_line("Verify result: verify-swipe-too-short (not done)").kind == "retry"
    assert p.parse_verify_line("Verify result: verify-disconnected (done)").kind == "disconnected"
    assert p.parse_verify_line("Verify result: verify-unknown-error (done)").kind == "error"
    assert p.parse_verify_line("Listing enrolled fingers:") is None
    assert p.parse_verify_line("VerifyStart failed: Device was already claimed").kind == "error"


def test_list_and_helpers():
    text = """found 1 devices
Device at /net/reactivated/Fprint/Device/0
Using device /net/reactivated/Fprint/Device/0
Fingerprints for user pumpkin on Goodix HTK32 Fingerprint Sensor (press):
 - #0: right-index-finger
 - #1: right-thumb
"""
    assert p.parse_list(text) == ["right-index-finger", "right-thumb"]
    assert p.parse_list("User pumpkin has no fingers enrolled for Goodix.") == []
    assert p.parse_stages("(<17>,)") == 17
    assert p.parse_stages("(<uint32 5>,)") == 5
    assert p.parse_stages("garbage", 7) == 7
    assert p.parse_stages("(<0>,)", 6) == 6
    assert p.parse_device_path("(objectpath '/net/reactivated/Fprint/Device/3',)") == "/net/reactivated/Fprint/Device/3"
    assert p.parse_device_path("") == "/net/reactivated/Fprint/Device/0"
    assert p.pretty("right-index-finger") == "right index finger"
    assert len(p.FINGERS) == 10 and len(set(p.FINGERS)) == 10


JOURNAL = """\
2026-10-17T12:00:01+00:00 yoga fprintd[812]: goodix550c open: result=ok ms=533 phase=done drain_bytes=0 tls_retry=0
2026-10-17T12:00:09+00:00 yoga fprintd[812]: unrelated line best_score=9
2026-10-17T12:00:11+00:00 yoga fprintd[812]: goodix550c attempt: action=identify ready_to_down_ms=856 down_polls=8 settle_ms=300 ref_mean=2266 best_score=345 early_exit=1 threshold=150 result=match dmax_pos=0
goodix550c attempt: action=identify best_score=0 threshold=150 result=retry:error
goodix550c attempt: action=verify best_score=97 threshold=150 result=no-match
"""


def test_journal():
    attempts, opens = p.parse_journal(JOURNAL)
    assert [a.best_score for a in attempts] == [345, 0, 97]
    assert [a.result for a in attempts] == ["match", "retry:error", "no-match"]
    assert attempts[0].matched and attempts[0].time == "12:00:11" and attempts[0].threshold == 150
    assert not attempts[1].matched and not attempts[1].scored
    assert attempts[1].time == ""            # `-o cat` lines carry no timestamp
    assert attempts[2].action == "verify"
    assert len(opens) == 1 and opens[0].result == "ok" and opens[0].ms == 533 and opens[0].phase == "done"
    assert p.parse_journal("nothing here\n") == ([], [])


def test_status_json():
    s = p.parse_status_json('{"sensor_present": true, "patched": true, "held": false, "psk_present": null, '
                            '"pam_enabled": true, "pam_tries": 4, "pam_timeout": 20, "libfprint_version": "1:1.94.10+goodix550c4"}')
    assert s.sensor_present is True and s.held is False and s.psk_present is None
    assert (s.pam_tries, s.pam_timeout) == (4, 20) and not s.error
    bad = p.parse_status_json("not json")
    assert bad.error
    assert p.parse_status_json("[1]").error


def test_validate_settings():
    assert p.validate_settings(3, 15) == ""
    assert p.validate_settings(1, 5) == "" and p.validate_settings(5, 30) == ""
    assert p.validate_settings(0, 15) and p.validate_settings(6, 15)
    assert p.validate_settings(3, 4) and p.validate_settings(3, 31)


def test_plain_result_has_no_jargon():
    assert p.plain_result("match") == ("match", "match")
    assert p.plain_result("no-match") == ("no match", "nomatch")
    assert p.plain_result("retry:finger-present") == ("finger already on sensor", "retry")
    assert p.plain_result("retry:too-short") == ("lifted too fast", "retry")
    assert p.plain_result("retry:error") == ("cancelled / timed out", "retry")
    assert p.plain_result("retry:remove-finger")[0] == "unclear touch"
    assert p.plain_result("retry:data-invalid")[0] == "saved print unreadable"
    assert p.plain_result("retry:something-new") == ("had to try again", "retry")
    for code in list(p.RESULT_TEXT) + ["retry:x", ""]:
        words, kind = p.plain_result(code)
        assert ":" not in words and "-" not in words.replace(" / ", "") and kind in ("match", "nomatch", "retry")
    assert set(p.RESULT_HELP) == set(p.RESULT_TEXT)


SESSIONS = """\
2026-10-17T09:00:00+00:00 h fprintd[1]: goodix550c attempt: best_score=300 threshold=150 result=match
2026-10-17T10:00:00+00:00 h fprintd[1]: goodix550c open: result=ok ms=500 phase=done
2026-10-17T10:00:05+00:00 h fprintd[1]: goodix550c attempt: best_score=0 threshold=150 result=retry:too-short
2026-10-17T10:00:09+00:00 h fprintd[1]: goodix550c attempt: best_score=250 threshold=150 result=match
2026-10-17T11:00:00+00:00 h fprintd[1]: goodix550c open: result=ok ms=510 phase=done
2026-10-17T11:00:04+00:00 h fprintd[1]: goodix550c attempt: best_score=33915 threshold=150 result=match
2026-10-17T12:00:00+00:00 h fprintd[1]: goodix550c open: result=ok ms=505 phase=done
2026-10-17T12:00:03+00:00 h fprintd[1]: goodix550c attempt: best_score=90 threshold=150 result=no-match
2026-10-16T12:00:03+00:00 h fprintd[1]: goodix550c attempt: best_score=500 threshold=150 result=match
"""


def test_journal_sessions_dates_and_stats():
    attempts, opens = p.parse_journal(SESSIONS)
    assert [a.session for a in attempts] == [-1, 0, 0, 1, 2, 2]
    assert attempts[0].date == "2026-10-17" and opens[0].date == "2026-10-17"
    st = p.summarise(attempts, "2026-10-17")
    assert st.scope == "today" and st.tries == 5
    assert (st.matches, st.nomatches, st.retries) == (3, 1, 1)
    assert st.sessions == 3 and st.first_try == 1 and st.first_try_pct == 33   # -1 (start unseen) is left out
    assert st.median_score == 275 and st.best_score == 33915                 # retries carry no score
    old = p.summarise(attempts, "2030-01-01")
    assert old.scope == "recent" and old.tries == 6
    assert p.summarise([], "2026-10-17").first_try_pct is None


def test_sessions_by_time_gap_without_open_lines():
    text = "\n".join(l for l in SESSIONS.splitlines() if "open:" not in l)
    attempts, opens = p.parse_journal(text)
    assert opens == []
    assert [a.session for a in attempts][:4] == [0, 1, 1, 2]
