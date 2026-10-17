"""The real backend: runs fprintd tools and goodix550c-ctl. Everything the UI needs from the
system goes through this one class, so tests and demo mode swap in FakeBackend (demo.py).

Never runs sudo by itself: root actions are only built as argv lists (`root_commands`) and
executed by the app in the real terminal, where the user types their own password.
"""
from __future__ import annotations

import asyncio
import getpass
import os
import shutil
import subprocess
from collections.abc import AsyncIterator, Callable

from goodix550c_tui import parsers
from goodix550c_tui.parsers import Attempt, Event, Status

JOURNAL_CMD = ["journalctl", "-u", "fprintd", "-o", "short-iso", "-n", "200", "--no-pager"]
CTL = "goodix550c-ctl"


def ctl_path() -> str:
    """goodix550c-ctl lives in /usr/sbin, which is not always in a normal user's PATH."""
    return shutil.which(CTL) or ("/usr/sbin/" + CTL if os.access("/usr/sbin/" + CTL, os.X_OK) else CTL)


async def run_cmd(argv: list[str], timeout: float = 10.0) -> tuple[int, str]:
    """Run a command, return (returncode, stdout+stderr). 127 when the program is missing, 124 on timeout."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL)
    except (FileNotFoundError, PermissionError) as e:
        return 127, str(e)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "timed out"
    return proc.returncode or 0, out.decode("utf-8", "replace")


class Backend:
    needs_terminal = True       # root actions must drop to the real terminal (App.suspend)
    demo = False

    def __init__(self, user: str | None = None):
        self.user = user or os.environ.get("USER") or getpass.getuser()

    # ---- reads
    async def status(self) -> Status:
        rc, out = await run_cmd([ctl_path(), "status", "--json"], 15)
        if rc != 0 and not out.lstrip().startswith("{"):
            return Status(error=f"{CTL} status failed: {out.strip()[:120] or rc}")
        return parsers.parse_status_json(out)

    async def list_fingers(self) -> list[str]:
        rc, out = await run_cmd(["fprintd-list", self.user], 10)
        return parsers.parse_list(out) if rc == 0 else []

    async def journal(self) -> tuple[list[Attempt], list[parsers.OpenInfo]]:
        rc, out = await run_cmd(JOURNAL_CMD, 10)
        return parsers.parse_journal(out) if rc == 0 else ([], [])

    async def num_stages(self) -> int:
        base = ["gdbus", "call", "--system", "--dest", "net.reactivated.Fprint"]
        rc, out = await run_cmd(base + ["--object-path", "/net/reactivated/Fprint/Manager", "--method",
                                        "net.reactivated.Fprint.Manager.GetDefaultDevice"], 5)
        path = parsers.parse_device_path(out if rc == 0 else "")
        rc, out = await run_cmd(base + ["--object-path", path, "--method",
                                        "org.freedesktop.DBus.Properties.Get",
                                        "net.reactivated.Fprint.Device", "num-enroll-stages"], 5)
        return parsers.parse_stages(out) if rc == 0 else 5

    # ---- long-running operations (async generators of Event)
    def _lines_cmd(self, argv: list[str]) -> list[str]:
        return (["stdbuf", "-oL"] if shutil.which("stdbuf") else []) + argv

    async def _stream(self, argv: list[str], parse: Callable[[str], Event | None]) -> AsyncIterator[Event]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL)
        except (FileNotFoundError, PermissionError) as e:
            yield Event("error", str(e), f"could not start {argv[0]}: {e}")
            return
        try:
            assert proc.stdout is not None
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                ev = parse(raw.decode("utf-8", "replace"))
                if ev is not None:
                    yield ev
            await proc.wait()
            yield Event("ended", "", f"exit {proc.returncode}")
        finally:
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), 3)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass

    def enroll(self, finger: str) -> AsyncIterator[Event]:
        return self._stream(self._lines_cmd(["fprintd-enroll", "-f", finger, self.user]),
                            parsers.parse_enroll_line)

    def verify(self) -> AsyncIterator[Event]:
        return self._stream(self._lines_cmd(["fprintd-verify", "-f", "any", self.user]),
                            parsers.parse_verify_line)

    async def delete(self, finger: str) -> tuple[bool, str]:
        rc, out = await run_cmd(["fprintd-delete", self.user, "-f", finger], 15)
        return rc == 0, out.strip().splitlines()[-1] if out.strip() else ""

    # ---- root actions
    def root_commands(self, tries: int | None, timeout: int | None, pam_enabled: bool | None) -> list[list[str]]:
        """argv lists (with sudo) for the settings the user changed; None = leave alone."""
        cmds: list[list[str]] = []
        if tries is not None and timeout is not None:
            cmds.append(["sudo", CTL, "pam", "set", "--tries", str(tries), "--timeout", str(timeout)])
        if pam_enabled is not None:
            cmds.append(["sudo", CTL, "pam", "enable" if pam_enabled else "disable"])
        return cmds

    def run_privileged(self, cmds: list[list[str]]) -> int:
        """Run in the real terminal (the app has suspended itself). Returns the first failure code or 0."""
        for argv in cmds:
            print("\n$ " + " ".join(argv), flush=True)
            rc = subprocess.call(argv)
            if rc != 0:
                print(f"\nThat command failed (exit {rc}).", flush=True)
                return rc
        return 0
