"""Pure parsers for fprintd / journal / goodix550c-ctl output. No I/O here."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

FINGERS_LEFT = ["left-little-finger", "left-ring-finger", "left-middle-finger",
                "left-index-finger", "left-thumb"]
FINGERS_RIGHT = ["right-thumb", "right-index-finger", "right-middle-finger",
                 "right-ring-finger", "right-little-finger"]
FINGERS = FINGERS_LEFT + FINGERS_RIGHT      # screen order, left to right
THRESHOLD = 150                             # matcher threshold in the driver (never lowered)


def pretty(finger: str) -> str:
    """right-index-finger -> 'right index finger'."""
    return finger.replace("-", " ")


# ---------------------------------------------------------------------------
# fprintd-enroll / fprintd-verify
# ---------------------------------------------------------------------------
RESULT_RE = re.compile(r"(?P<verb>Enroll|Verify) result:\s*(?P<name>[\w-]+)(?:\s*\((?P<done>not done|done)\))?")
ERROR_RE = re.compile(r"(?i)\b(error|failed|impossible|claimed|denied|no devices|not available)\b")

ENROLL_KINDS = {
    "enroll-stage-passed": "stage",
    "enroll-retry-scan": "retry",
    "enroll-swipe-too-short": "short",
    "enroll-finger-not-centered": "not-centered",
    "enroll-remove-and-retry": "remove",
    "enroll-completed": "completed",
    "enroll-failed": "failed",
    "enroll-disconnected": "disconnected",
    "enroll-data-full": "full",
    "enroll-duplicate": "duplicate",
    "enroll-unknown-error": "error",
}
VERIFY_KINDS = {
    "verify-match": "match",
    "verify-no-match": "no-match",
    "verify-disconnected": "disconnected",
    "verify-unknown-error": "error",
}


@dataclass
class Event:
    """One thing that happened in an enroll or verify run."""
    kind: str
    raw: str = ""
    message: str = ""
    done: bool | None = None        # the "(done)" / "(not done)" flag when fprintd printed one


def parse_enroll_line(line: str) -> Event | None:
    line = line.strip()
    if not line:
        return None
    m = RESULT_RE.search(line)
    if m and m.group("verb") == "Enroll":
        kind = ENROLL_KINDS.get(m.group("name"))
        if kind is None:
            kind = "retry" if m.group("name").startswith("enroll-retry") else "error"
        return Event(kind, line, m.group("name"))
    if line.startswith("Enrolling "):
        return Event("started", line)
    if ERROR_RE.search(line):
        return Event("error", line, line)
    return None


def parse_verify_line(line: str) -> Event | None:
    line = line.strip()
    if not line:
        return None
    m = RESULT_RE.search(line)
    if m and m.group("verb") == "Verify":
        name = m.group("name")
        done = None if m.group("done") is None else m.group("done") == "done"
        kind = VERIFY_KINDS.get(name)
        if kind is None:
            kind = "retry" if name.startswith("verify-retry") or name == "verify-swipe-too-short" \
                or name == "verify-finger-not-centered" or name == "verify-remove-and-retry" else "error"
        # fprintd says "(not done)" for everything that is only a retry
        if kind == "no-match" and done is False:
            kind = "retry"
        return Event(kind, line, name, done)
    if line.startswith("Verify started"):
        return Event("started", line)
    if ERROR_RE.search(line):
        return Event("error", line, line)
    return None


FINGER_LIST_RE = re.compile(r"^\s*-\s*(?:#\d+:\s*)?(?P<finger>[a-z]+-[a-z-]+)\s*$", re.M)


def parse_list(text: str) -> list[str]:
    """fprintd-list output -> enrolled finger names (only known fingers)."""
    return [f for f in FINGER_LIST_RE.findall(text) if f in FINGERS]


STAGES_RE = re.compile(r"(\d+)")


def parse_stages(text: str, default: int = 5) -> int:
    """gdbus '(<5>,)' or '(<uint32 5>,)' -> 5; anything odd -> default."""
    found = STAGES_RE.findall(text or "")
    if not found:
        return default
    n = int(found[-1])
    return n if 1 <= n <= 100 else default


OBJPATH_RE = re.compile(r"'(/net/reactivated/Fprint/Device/\d+)'")


def parse_device_path(text: str, default: str = "/net/reactivated/Fprint/Device/0") -> str:
    m = OBJPATH_RE.search(text or "")
    return m.group(1) if m else default


# ---------------------------------------------------------------------------
# journal: goodix550c open: / attempt:
# ---------------------------------------------------------------------------
LOG_RE = re.compile(r"goodix550c (?P<what>open|attempt):\s*(?P<fields>.*)$")
FIELD_RE = re.compile(r"(\w+)=(\S+)")
TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})")


@dataclass
class Attempt:
    """One `goodix550c attempt:` journal line."""
    action: str = ""
    best_score: int = 0
    threshold: int = THRESHOLD
    result: str = ""
    time: str = ""              # HH:MM:SS when the journal line carried a timestamp
    fields: dict = field(default_factory=dict)

    @property
    def matched(self) -> bool:
        return self.result == "match"

    @property
    def retry(self) -> bool:
        return self.result.startswith("retry")


@dataclass
class OpenInfo:
    result: str = ""
    ms: int = 0
    phase: str = ""
    time: str = ""


def _fields(text: str) -> dict:
    return {k: (int(v) if re.fullmatch(r"-?\d+", v) else v) for k, v in FIELD_RE.findall(text)}


def parse_journal(text: str) -> tuple[list[Attempt], list[OpenInfo]]:
    attempts: list[Attempt] = []
    opens: list[OpenInfo] = []
    for line in text.splitlines():
        m = LOG_RE.search(line)
        if not m:
            continue
        t = TIME_RE.match(line)
        stamp = t.group(2) if t else ""
        f = _fields(m.group("fields"))
        if m.group("what") == "attempt":
            attempts.append(Attempt(
                action=str(f.get("action", "")),
                best_score=int(f.get("best_score", 0) or 0),
                threshold=int(f.get("threshold", THRESHOLD) or THRESHOLD),
                result=str(f.get("result", "")), time=stamp, fields=f))
        else:
            opens.append(OpenInfo(str(f.get("result", "")), int(f.get("ms", 0) or 0),
                                  str(f.get("phase", "")), stamp))
    return attempts, opens


# ---------------------------------------------------------------------------
# goodix550c-ctl status --json
# ---------------------------------------------------------------------------
@dataclass
class Status:
    sensor_present: bool | None = None
    libfprint_version: str = ""
    patched: bool | None = None
    held: bool | None = None
    apt_pin: bool | None = None
    package_version: str = ""
    dropin_present: bool | None = None
    psk_present: bool | None = None      # None = cannot tell without root
    store_ok: bool | None = None
    pam_enabled: bool | None = None
    pam_tries: int = 3
    pam_timeout: int = 15
    usb_power: str = ""
    last_log: str = ""
    error: str = ""                      # set when the status could not be read at all


def parse_status_json(text: str) -> Status:
    try:
        d = json.loads(text)
        if not isinstance(d, dict):
            raise ValueError("not an object")
    except ValueError as e:
        return Status(error=f"could not read status ({e})")

    def b(key):
        v = d.get(key)
        return v if isinstance(v, bool) else None

    def n(key, default):
        v = d.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else default

    return Status(
        sensor_present=b("sensor_present"), libfprint_version=str(d.get("libfprint_version") or ""),
        patched=b("patched"), held=b("held"), apt_pin=b("apt_pin"),
        package_version=str(d.get("package_version") or ""), dropin_present=b("dropin_present"),
        psk_present=b("psk_present"), store_ok=b("store_ok"), pam_enabled=b("pam_enabled"),
        pam_tries=n("pam_tries", 3), pam_timeout=n("pam_timeout", 15),
        usb_power=str(d.get("usb_power") or ""), last_log=str(d.get("last_log") or ""))


def validate_settings(tries: int, timeout: int) -> str:
    """'' when fine, else a plain-English problem."""
    if not 1 <= tries <= 5:
        return "Tries must be between 1 and 5."
    if not 5 <= timeout <= 30:
        return "Timeout must be between 5 and 30 seconds."
    return ""
