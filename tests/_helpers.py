"""Shared helpers for the test-suite (import with `from _helpers import ...`).

pytest puts tests/ on sys.path (rootdir-relative "prepend" import mode, no
__init__.py), so no conftest.py is needed and tests/tui/conftest.py is unaffected.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def run(cmd, **kw) -> subprocess.CompletedProcess:
    """subprocess.run with text capture; every argument is stringified (Paths are fine)."""
    env = kw.pop("env", None)
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env, **kw)


def deb_field(deb: Path, name: str) -> str:
    """One control field of a .deb (dpkg-deb -f)."""
    return run(["dpkg-deb", "-f", deb, name]).stdout.strip()


def deb_member(deb: Path, member: str) -> str:
    """Text of one file inside a .deb, e.g. "./usr/sbin/goodix550c-ctl"."""
    tar = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(deb)], capture_output=True, check=True)
    out = subprocess.run(["tar", "-xO", member], input=tar.stdout, capture_output=True, check=True)
    return out.stdout.decode()


def load_script(name: str, module_name: str | None = None) -> ModuleType:
    """Import scripts/<name> (a .py file) as a module without needing it on sys.path."""
    path = ROOT / "scripts" / name
    if path.suffix != ".py":
        path = path.with_suffix(".py")
    spec = importlib.util.spec_from_file_location(module_name or path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_exe(directory: Path, name: str, body: str) -> Path:
    """Write an executable /bin/sh stub `name` into directory (for PATH-shadowing)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n" + body.rstrip("\n") + "\n")
    path.chmod(0o755)
    return path
