import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "packaging/goodix550c-fingerprint/usr/bin/finger"


def test_module_version_and_not_a_tty():
    env = {"PYTHONPATH": str(ROOT / "tui"), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-m", "goodix550c_tui", "--version"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout.startswith("finger ")
    r = subprocess.run([sys.executable, "-m", "goodix550c_tui", "--demo"], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    assert r.returncode == 1 and "real terminal" in r.stderr


def test_wrappers_are_identical_and_exec_the_module():
    a = WRAPPER.read_text()
    assert a == WRAPPER.with_name("goodix550c-tui").read_text()
    assert "exec /usr/bin/python3 -m goodix550c_tui" in a
