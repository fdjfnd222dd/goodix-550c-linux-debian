"""Demo / test backend: `finger --demo` runs the whole app on this, so it can be tried (and
screenshotted, and tested) without the sensor. It never touches the system.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from goodix550c_tui.parsers import Attempt, Event, OpenInfo, Status


def _attempts() -> list[Attempt]:
    rows = [("12:01:14", 345, "match"), ("12:01:52", 0, "retry:error"), ("12:03:09", 288, "match"),
            ("12:08:40", 97, "no-match"), ("12:08:47", 412, "match"), ("12:15:02", 176, "match"),
            ("12:15:30", 131, "no-match"), ("12:22:18", 260, "match"), ("12:31:44", 0, "retry:short"),
            ("12:31:50", 301, "match"), ("12:40:05", 207, "match")]
    return [Attempt("identify", s, 150, r, t, {}) for t, s, r in rows]


class FakeBackend:
    """Same interface as backend.Backend. `step` is the pause between simulated events."""

    needs_terminal = False
    demo = True

    def __init__(self, step: float = 0.9, stages: int = 8, enrolled: list[str] | None = None,
                 verify_script: list[list[str]] | None = None, user: str = "demo"):
        self.user = user
        self.step = step
        self.stages = stages
        self.enrolled = list(["right-index-finger", "right-thumb"] if enrolled is None else enrolled)
        # each verify run plays one list; cycles
        self.verify_script = verify_script or [["retry", "match"], ["no-match"], ["match"]]
        self._verify_runs = 0
        self.attempts = _attempts()
        self.pam_enabled = True
        self.tries = 3
        self.timeout = 15
        self.privileged: list[list[list[str]]] = []     # what the UI asked to run as root
        self.fail_delete = False
        self.enroll_script: list[str] | None = None     # override the event kinds of the next enroll

    # ---- reads
    async def status(self) -> Status:
        return Status(sensor_present=True, libfprint_version="1:1.94.10+goodix550c4", patched=True,
                      held=True, apt_pin=True, package_version="1.1.0", dropin_present=True,
                      psk_present=None, store_ok=True, pam_enabled=self.pam_enabled,
                      pam_tries=self.tries, pam_timeout=self.timeout, usb_power="on")

    async def list_fingers(self) -> list[str]:
        return list(self.enrolled)

    async def journal(self):
        return list(self.attempts), [OpenInfo("ok", 533, "done", "12:40:04")]

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
        yield Event("started", "Verify started!")
        for kind in script:
            await asyncio.sleep(self.step)
            if kind == "match":
                self.attempts.append(Attempt("identify", 318, 150, "match", "12:50:00", {}))
            elif kind == "no-match":
                self.attempts.append(Attempt("identify", 88, 150, "no-match", "12:50:00", {}))
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
