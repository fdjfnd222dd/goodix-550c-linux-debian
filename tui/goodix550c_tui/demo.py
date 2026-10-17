"""Demo / test backend: `finger --demo` runs the whole app on this, so it can be tried (and
screenshotted, and tested) without the sensor. It never touches the system.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from collections.abc import AsyncIterator

from goodix550c_tui.parsers import Event, Status, parse_journal

# (minutes before now, result, score) per line; "open" starts a session (one sudo prompt / test).
# Scores are typical of this sensor: matches 150-1300 with the odd huge one, misses well below.
_DEMO_LOG = [
    (1720, "open", 0), (1720, "match", 233), (1690, "open", 0), (1690, "match", 671),
    (1655, "open", 0), (1655, "no-match", 64), (1654, "match", 198),
    (1610, "open", 0), (1610, "match", 302), (1580, "open", 0), (1580, "retry:error", 0),
    (1560, "open", 0), (1560, "match", 455), (1530, "open", 0), (1530, "match", 2210),
    (1500, "open", 0), (1499, "match", 412),
    (1460, "open", 0), (1459, "retry:finger-present", 0), (1459, "match", 288),
    (300, "open", 0), (299, "match", 345),
    (262, "open", 0), (262, "retry:error", 0),
    (240, "open", 0), (240, "match", 1310),
    (205, "open", 0), (205, "no-match", 97), (204, "match", 288),
    (180, "open", 0), (180, "match", 176),
    (151, "open", 0), (151, "no-match", 131), (150, "match", 260),
    (122, "open", 0), (122, "retry:too-short", 0), (121, "match", 301),
    (96, "open", 0), (96, "match", 33915),
    (75, "open", 0), (75, "match", 207),
    (52, "open", 0), (52, "retry:remove-finger", 0), (51, "match", 523),
    (31, "open", 0), (31, "match", 243),
    (12, "open", 0), (12, "match", 389),
]


def _stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _attempt_line(t: datetime, result: str, score: int) -> str:
    return (f"{_stamp(t)} demo fprintd[812]: goodix550c attempt: action=identify ready_to_down_ms=850 "
            f"best_score={score} threshold=150 result={result}")


def _open_line(t: datetime, ms: int = 533) -> str:
    return f"{_stamp(t)} demo fprintd[812]: goodix550c open: result=ok ms={ms} phase=done drain_bytes=0 tls_retry=0"


def demo_journal(now: datetime | None = None) -> list[str]:
    now = now or datetime.now()
    out = []
    for i, (mins, what, score) in enumerate(_DEMO_LOG):
        t = now - timedelta(minutes=mins, seconds=(len(_DEMO_LOG) - i))
        out.append(_open_line(t, 480 + (i * 37) % 120) if what == "open" else _attempt_line(t, what, score))
    return out


class FakeBackend:
    """Same interface as backend.Backend. `step` is the pause between simulated events."""

    needs_terminal = False
    demo = True

    def __init__(self, step: float = 0.9, stages: int = 17, enrolled: list[str] | None = None,
                 verify_script: list[list[str]] | None = None, user: str = "demo"):
        self.user = user
        self.step = step
        self.stages = stages
        self.enrolled = list(["right-index-finger", "right-thumb"] if enrolled is None else enrolled)
        # each verify run plays one list; cycles
        self.verify_script = verify_script or [["retry", "match"], ["no-match"], ["match"]]
        self._verify_runs = 0
        self.lines = demo_journal()
        self.pam_enabled = True
        self.held = True
        self.tries = 3
        self.timeout = 15
        self.privileged: list[list[list[str]]] = []     # what the UI asked to run as root
        self.fail_delete = False
        self.enroll_script: list[str] | None = None     # override the event kinds of the next enroll
        self.match_score = 318

    # ---- reads
    async def status(self) -> Status:
        return Status(sensor_present=True, libfprint_version="1:1.94.10+goodix550c4", patched=True,
                      held=self.held, apt_pin=True, package_version="1.1.1", dropin_present=True,
                      psk_present=None, store_ok=True, pam_enabled=self.pam_enabled,
                      pam_tries=self.tries, pam_timeout=self.timeout, usb_power="on")

    async def list_fingers(self) -> list[str]:
        return list(self.enrolled)

    @property
    def attempts(self):
        return parse_journal("\n".join(self.lines))[0]

    async def journal(self):
        return parse_journal("\n".join(self.lines))

    async def num_stages(self) -> int:
        return self.stages

    # ---- operations
    async def enroll(self, finger: str) -> AsyncIterator[Event]:
        await asyncio.sleep(self.step / 2)
        yield Event("started", f"Enrolling {finger} finger.")
        script = self.enroll_script
        if script is None:
            script = []
            for i in range(self.stages):
                if i == 2:
                    script.append("retry")
                if i == 5:
                    script.append("remove")
                script.append("stage")
            script.append("completed")
        self.enroll_script = None
        for kind in script:
            if kind == "wait":              # hold here (for screenshots): the user "never" does the next thing
                await asyncio.sleep(3600)
                return
            await asyncio.sleep(self.step)
            if kind == "completed" and finger not in self.enrolled:
                self.enrolled.append(finger)
            yield Event(kind, f"Enroll result: enroll-{kind}")
            if kind in ("completed", "failed", "full", "duplicate", "disconnected"):
                break

    async def verify(self) -> AsyncIterator[Event]:
        script = self.verify_script[self._verify_runs % len(self.verify_script)]
        self._verify_runs += 1
        await asyncio.sleep(self.step / 2)
        self.lines.append(_open_line(datetime.now()))
        yield Event("started", "Verify started!")
        for kind in script:
            await asyncio.sleep(self.step)
            if kind == "match":
                self.lines.append(_attempt_line(datetime.now(), "match", self.match_score))
            elif kind == "no-match":
                self.lines.append(_attempt_line(datetime.now(), "no-match", 88))
            elif kind == "retry":
                self.lines.append(_attempt_line(datetime.now(), "retry:too-short", 0))
            yield Event(kind, f"Verify result: verify-{kind}")

    async def delete(self, finger: str) -> tuple[bool, str]:
        await asyncio.sleep(0)
        if self.fail_delete:
            return False, "could not delete"
        if finger in self.enrolled:
            self.enrolled.remove(finger)
        return True, "deleted"

    # ---- root actions
    def root_commands(self, tries, timeout, pam_enabled):
        cmds = []
        if tries is not None and timeout is not None:
            cmds.append(["sudo", "goodix550c-ctl", "pam", "set", "--tries", str(tries), "--timeout", str(timeout)])
        if pam_enabled is not None:
            cmds.append(["sudo", "goodix550c-ctl", "pam", "enable" if pam_enabled else "disable"])
        return cmds

    def run_privileged(self, cmds: list[list[str]]) -> int:
        self.privileged.append(cmds)
        for c in cmds:
            if c[2:4] == ["pam", "set"]:
                self.tries = int(c[c.index("--tries") + 1])
                self.timeout = int(c[c.index("--timeout") + 1])
            elif c[2:4] == ["pam", "enable"]:
                self.pam_enabled = True
            elif c[2:4] == ["pam", "disable"]:
                self.pam_enabled = False
        return 0
