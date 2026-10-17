"""The real Backend against throw-away shell programs that print fprintd's output.
Nothing here touches fprintd, D-Bus, sudo or the sensor."""
import asyncio
import os
import stat

from goodix550c_tui.backend import Backend, journal_cmd, resolve_ctl, root_commands
from goodix550c_tui.demo import FakeBackend


def fake_bin(tmp_path, name, body):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text("#!/bin/sh\n" + body)
    f.chmod(f.stat().st_mode | stat.S_IXUSR)
    return d


def run(coro):
    return asyncio.run(coro)


async def collect(agen):
    return [e async for e in agen]


def test_enroll_stream_and_argv(tmp_path, monkeypatch):
    log = tmp_path / "argv"
    d = fake_bin(tmp_path, "fprintd-enroll", f'''echo "$@" > {log}
echo "Using device /net/reactivated/Fprint/Device/0"
echo "Enrolling right-thumb finger."
echo "Enroll result: enroll-stage-passed"
echo "Enroll result: enroll-retry-scan"
echo "Enroll result: enroll-completed"
''')
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    events = run(collect(Backend(user="alice").enroll("right-thumb")))
    assert [e.kind for e in events] == ["started", "stage", "retry", "completed", "ended"]
    assert log.read_text().split() == ["-f", "right-thumb", "alice"]


def test_verify_stream(tmp_path, monkeypatch):
    log = tmp_path / "argv"
    d = fake_bin(tmp_path, "fprintd-verify", f'''echo "$@" > {log}
echo "Verify started!"
echo "Verify result: verify-retry-scan (not done)"
echo "Verify result: verify-match (done)"
''')
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    events = run(collect(Backend(user="alice").verify()))
    assert [e.kind for e in events] == ["started", "retry", "match", "ended"]
    assert log.read_text().split() == ["-f", "any", "alice"]


def test_missing_program_is_an_error_event(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))      # no stdbuf, no fprintd-enroll
    events = run(collect(Backend(user="alice").enroll("right-thumb")))
    assert [e.kind for e in events] == ["error"]


def test_cancel_kills_the_process(tmp_path, monkeypatch):
    pidfile = tmp_path / "pid"
    d = fake_bin(tmp_path, "fprintd-verify", f'echo $$ > {pidfile}\necho "Verify started!"\nexec sleep 60\n')
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")

    async def go():
        gen = Backend(user="a").verify()
        first = await gen.__anext__()
        assert first.kind == "started"
        await gen.aclose()
        return int(pidfile.read_text())

    pid = run(go())
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive


def test_list_delete_status_journal(tmp_path, monkeypatch):
    dlog = tmp_path / "del"
    d = fake_bin(tmp_path, "fprintd-list", 'echo " - #0: right-thumb"\n')
    fake_bin(tmp_path, "fprintd-delete", f'echo "$@" > {dlog}\necho "Fingerprints deleted"\n')
    ctl = fake_bin(tmp_path, "goodix550c-ctl", 'echo \'{"sensor_present": true, "pam_tries": 2, "pam_timeout": 9}\'\n')
    fake_bin(tmp_path, "journalctl", 'echo "2026-10-17T12:00:11+00:00 h fprintd[1]: goodix550c attempt: action=identify best_score=200 threshold=150 result=match"\n')
    fake_bin(tmp_path, "gdbus", 'case "$*" in *GetDefaultDevice*) echo "(objectpath \'/net/reactivated/Fprint/Device/0\',)";; *) echo "(<8>,)";; esac\n')
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    monkeypatch.setenv("GOODIX550C_CTL", str(ctl / "goodix550c-ctl"))
    be = Backend(user="alice")
    assert run(be.list_fingers()) == ["right-thumb"]
    ok, msg = run(be.delete("right-thumb"))
    assert ok and dlog.read_text().split() == ["alice", "-f", "right-thumb"]
    st = run(be.status())
    assert st.sensor_present and (st.pam_tries, st.pam_timeout) == (2, 9)
    attempts, _ = run(be.journal(20))
    assert attempts[0].best_score == 200
    assert run(be.num_stages()) == 8


def test_root_commands_are_only_built_never_run():
    be = Backend(user="a")
    assert be.root_commands(2, 10, None) == [["sudo", "goodix550c-ctl", "pam", "set", "--tries", "2", "--timeout", "10"]]
    assert be.root_commands(None, None, True) == [["sudo", "goodix550c-ctl", "pam", "enable"]]
    assert be.root_commands(3, 15, False)[-1] == ["sudo", "goodix550c-ctl", "pam", "disable"]
    assert be.root_commands(None, None, None) == []


def test_fake_backend_shares_root_commands():
    assert FakeBackend().root_commands(2, 10, True) == root_commands(2, 10, True)
    assert Backend(user="a").root_commands(2, 10, True) == root_commands(2, 10, True)


def test_journal_window_size():
    assert journal_cmd(20)[journal_cmd(20).index("-n") + 1] == "20"
    assert journal_cmd()[journal_cmd().index("-n") + 1] == "200"


def test_ctl_path_override_and_missing(tmp_path, monkeypatch):
    d = fake_bin(tmp_path, "my-ctl", "echo '{}'\n")
    monkeypatch.setenv("GOODIX550C_CTL", str(d / "my-ctl"))
    assert resolve_ctl() == str(d / "my-ctl")
    monkeypatch.setenv("GOODIX550C_CTL", str(tmp_path / "nope"))
    assert resolve_ctl() is None
    st = run(Backend(user="a").status())
    assert st.ctl_missing and "not installed" in st.error
