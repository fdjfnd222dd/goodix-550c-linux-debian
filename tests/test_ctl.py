from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build_goodix550c_debs.sh"
PKGDIR = ROOT / "packaging" / "goodix550c-fingerprint"
CTL = PKGDIR / "usr" / "sbin" / "goodix550c-ctl"
SCRIPTS = ["preinst", "postinst", "prerm", "postrm"]

pytestmark = pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="dpkg-deb not available")


def run(cmd, **kw):
    env = kw.pop("env", None)
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env, **kw)


@pytest.fixture(scope="module")
def deb(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    r = run([BUILD, "--pkg", "goodix550c-fingerprint", "--out", out, "--work", out / "w"])
    assert r.returncode == 0, r.stderr
    d = out / "goodix550c-fingerprint_1.1.1_all.deb"
    assert d.exists()
    return d


def field(deb, name):
    return run(["dpkg-deb", "-f", deb, name]).stdout.strip()


def test_control(deb):
    assert field(deb, "Package") == "goodix550c-fingerprint"
    assert field(deb, "Architecture") == "all"
    assert field(deb, "Version") == "1.1.1"
    assert field(deb, "Depends") == (
        "libfprint-goodix550c (>= 3), fprintd, libpam-fprintd, udev, python3, python3-textual (>= 2.1), python3-rich"
    )
    assert field(deb, "Conflicts") == "finger"
    assert field(deb, "Recommends") == "tlp"
    assert "@" not in field(deb, "Installed-Size")


def test_contents(deb):
    listing = run(["dpkg-deb", "-c", deb]).stdout
    for path in [
        "./usr/lib/systemd/system/fprintd.service.d/50-goodix550c.conf",
        "./usr/lib/udev/rules.d/60-goodix550c-power.rules",
        "./etc/tlp.d/50-goodix550c.conf",
        "./etc/apt/preferences.d/goodix550c-libfprint",
        "./usr/share/pam-configs/goodix550c-fingerprint",
        "./usr/sbin/goodix550c-ctl",
        "./usr/bin/finger",
        "./usr/bin/goodix550c-tui",
        "./usr/lib/python3/dist-packages/goodix550c_tui/app.py",
        "./usr/lib/python3/dist-packages/goodix550c_tui/pages.py",
        "./usr/lib/python3/dist-packages/goodix550c_tui/backend.py",
        "./usr/lib/python3/dist-packages/goodix550c_tui/demo.py",
        "./usr/lib/python3/dist-packages/goodix550c_tui/__main__.py",
    ]:
        assert path in listing, path
    for forbidden in ["system-sleep", "unstick", "/opt/", ".psk"]:
        assert forbidden not in listing
    for exe in ("usr/sbin/goodix550c-ctl", "usr/bin/finger", "usr/bin/goodix550c-tui"):
        line = [l for l in listing.splitlines() if l.endswith(exe)][0]
        assert line.startswith("-rwxr-xr-x root/root"), line
    assert "__pycache__" not in listing and ".pyc" not in listing
    mod = [l for l in listing.splitlines() if l.endswith("goodix550c_tui/app.py")][0]
    assert mod.startswith("-rw-r--r-- root/root")


def test_conffiles(deb):
    cf = run(["dpkg-deb", "-I", deb, "conffiles"]).stdout.split()
    assert cf == ["/etc/tlp.d/50-goodix550c.conf", "/etc/apt/preferences.d/goodix550c-libfprint"]


def test_file_texts(deb):
    def get(m):
        return subprocess.run(
            f"dpkg-deb --fsys-tarfile '{deb}' | tar -xO '{m}'", shell=True, capture_output=True, text=True, check=True
        ).stdout

    d = get("./usr/lib/systemd/system/fprintd.service.d/50-goodix550c.conf")
    assert d.splitlines()[0] == "[Service]"
    for line in [
        "Environment=FP_DRIVERS_ALLOWLIST=goodix53x5",
        "Environment=GOODIX550C_ALLOW_VOLATILE_INIT=1",
        "Environment=GOODIX550C_ALLOW_MANUAL_FDT_POLL=1",
        "Environment=GOODIX550C_PSK_FILE=/etc/goodix550c/goodix550c.psk",
        "Environment=GOODIX550C_LOG_SUMMARY=1",
        "UMask=0077",
    ]:
        assert line in d.splitlines()
    assert "ExecStartPre" not in d
    assert get("./etc/tlp.d/50-goodix550c.conf") == 'USB_DENYLIST="27c6:550c"\n'
    pin = get("./etc/apt/preferences.d/goodix550c-libfprint")
    assert "Package: libfprint-2-2" in pin and "Pin: version 1:1.94.10+goodix550c*" in pin and "Pin-Priority: 1001" in pin
    assert get("./usr/lib/udev/rules.d/60-goodix550c-power.rules").strip() == (
        'ACTION=="add|bind", SUBSYSTEM=="usb", ATTR{idVendor}=="27c6", ATTR{idProduct}=="550c", '
        'TEST=="power/control", ATTR{power/control}="on"'
    )


def test_tlp_identical_to_legacy_file():
    legacy = Path.home() / "goodix550c-debs" / "legacy" / "50-goodix550c.conf"
    if not legacy.exists():
        pytest.skip("no legacy copy")
    assert legacy.read_bytes() == (PKGDIR / "etc/tlp.d/50-goodix550c.conf").read_bytes()


def test_refuse_overwrite(tmp_path):
    args = [BUILD, "--pkg", "goodix550c-fingerprint", "--out", tmp_path, "--work", tmp_path / "w"]
    assert run(args).returncode == 0
    r = run(args)
    assert r.returncode != 0 and "refusing to overwrite" in r.stderr
    assert "goodix550c-fingerprint_1.1.1_all.deb" in (tmp_path / "SHA256SUMS").read_text()


@pytest.mark.parametrize("name", SCRIPTS)
def test_maintainer_scripts_syntax(name):
    p = PKGDIR / "DEBIAN" / name
    assert os.access(p, os.X_OK)
    assert run(["sh", "-n", p]).returncode == 0


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck():
    files = [PKGDIR / "DEBIAN" / n for n in SCRIPTS] + [CTL]
    r = run(["shellcheck", "-x", *files])
    assert r.returncode == 0, r.stdout


def test_ctl_syntax():
    assert run(["bash", "-n", CTL]).returncode == 0


def fake_root(tmp_path: Path) -> Path:
    r = tmp_path / "root"
    (r / "etc/goodix550c").mkdir(parents=True)
    (r / "etc/pam.d").mkdir(parents=True)
    (r / "etc/pam.d/common-auth").write_text("auth [success=2 default=ignore] pam_fprintd.so max-tries=3 timeout=10\n")
    (r / "var/lib/fprint").mkdir(parents=True)
    usb = r / "sys/bus/usb/devices/1-3/power"
    usb.mkdir(parents=True)
    (usb.parent / "idVendor").write_text("27c6\n")
    (usb.parent / "idProduct").write_text("550c\n")
    (usb / "control").write_text("on\n")
    return r


def ctl_env(tmp_path, root=True, extra_path=None):
    env = dict(os.environ)
    if root:
        env["GOODIX550C_ROOT"] = str(fake_root(tmp_path))
    if extra_path:
        env["PATH"] = f"{extra_path}:{env['PATH']}"
    return env


def test_ctl_help():
    r = run([CTL, "--help"])
    assert r.returncode == 0 and "status" in r.stdout and "rollback-stock" in r.stdout


def test_ctl_status_fake_root(tmp_path):
    r = run([CTL, "status"], env=ctl_env(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "sudo apt install" in r.stdout and "goodix550c-ctl recover" in r.stdout
    assert "1-3=on" in r.stdout
    assert "PSK: MISSING" in r.stdout


def test_ctl_status_non_root_real_system_does_not_fail():
    r = run([CTL, "status"])
    assert r.returncode == 0, r.stderr


def test_ctl_requires_root_without_fake_root():
    if os.geteuid() == 0:
        pytest.skip("running as root")
    for cmd in (["recover"], ["harden-store"], ["install-psk", "/dev/null"], ["psk-backup", "/x"], ["pam", "enable"], ["rollback-stock"]):
        r = run([CTL, *cmd])
        assert r.returncode != 0 and "needs root" in r.stderr, cmd


def shim(tmp_path):
    d = tmp_path / "shim"
    d.mkdir()
    log = tmp_path / "enroll.log"
    f = d / "fprintd-enroll"
    f.write_text(f'#!/bin/sh\necho "$@" > "{log}"\n')
    f.chmod(0o755)
    return d, log


def test_enroll_uses_dash_f(tmp_path):
    d, log = shim(tmp_path)
    env = ctl_env(tmp_path, root=False, extra_path=d)
    env["SUDO_USER"] = "alice"
    r = run([CTL, "enroll", "right-index-finger"], env=env)
    assert r.returncode == 0, r.stderr
    assert log.read_text().split() == ["-f", "right-index-finger", "alice"]


def test_enroll_rejects_bad_finger_and_missing(tmp_path):
    d, log = shim(tmp_path)
    env = ctl_env(tmp_path, root=False, extra_path=d)
    assert run([CTL, "enroll", "bogus"], env=env).returncode != 0
    assert run([CTL, "enroll"], env=env).returncode != 0
    assert not log.exists()


def test_psk_backup_refuses_repo_and_tmp(tmp_path):
    env = ctl_env(tmp_path)
    root = Path(env["GOODIX550C_ROOT"])
    (root / "etc/goodix550c/goodix550c.psk").write_text("a" * 64 + "\n")
    r = run([CTL, "psk-backup", ROOT / "psk.bak"], env=env)
    assert r.returncode != 0 and "git repository" in r.stderr
    assert not (ROOT / "psk.bak").exists()
    r = run([CTL, "psk-backup", tmp_path / "psk.bak"], env=env)
    assert r.returncode != 0 and "temporary" in r.stderr
    env["GOODIX550C_TEST_ALLOW_TMP"] = "1"
    r = run([CTL, "psk-backup", tmp_path / "psk.bak"], env=env)
    assert r.returncode == 0, r.stderr
    assert oct((tmp_path / "psk.bak").stat().st_mode & 0o777) == "0o600"
    assert ("a" * 64) not in r.stdout
    assert run([CTL, "psk-backup", tmp_path / "psk.bak"], env=env).returncode != 0


def test_install_psk_validation(tmp_path):
    env = ctl_env(tmp_path)
    root = Path(env["GOODIX550C_ROOT"])
    good_hex = tmp_path / "hex"
    good_hex.write_text("0123456789abcdef" * 4 + "\n")
    r = run([CTL, "install-psk", good_hex], env=env)
    assert r.returncode == 0 and r.stdout.strip() == "installed"
    psk = root / "etc/goodix550c/goodix550c.psk"
    assert oct(psk.stat().st_mode & 0o777) == "0o600"
    assert oct((root / "etc/goodix550c").stat().st_mode & 0o777) == "0o700"
    raw = tmp_path / "raw"
    raw.write_bytes(bytes(range(32)))
    assert run([CTL, "install-psk", raw], env=env).returncode == 0
    assert psk.read_text().strip() == bytes(range(32)).hex()
    for bad in (b"short", b"z" * 64, b"x" * 33):
        f = tmp_path / "bad"
        f.write_bytes(bad)
        assert run([CTL, "install-psk", f], env=env).returncode != 0


def test_pam_enable_normalizes_max_tries(tmp_path):
    env = ctl_env(tmp_path)
    shimdir = tmp_path / "pshim"
    shimdir.mkdir()
    pau = shimdir / "pam-auth-update"
    pau.write_text('#!/bin/sh\necho "$@" > "$GOODIX550C_ROOT/pau.args"\n')
    pau.chmod(0o755)
    env["PATH"] = f"{shimdir}:{env['PATH']}"
    root = Path(env["GOODIX550C_ROOT"])
    ca = root / "etc/pam.d/common-auth"
    ca.write_text(ca.read_text().replace("max-tries=3", "max-tries=7"))
    r = run([CTL, "pam", "enable"], env=env)
    assert r.returncode == 0, r.stderr
    assert "max-tries=3" in (root / "etc/pam.d/common-auth").read_text()
    assert "--enable goodix550c-fingerprint" in (root / "pau.args").read_text()


# ---- status --json and pam set (finger TUI support) ----

PROFILE_TEXT = (
    "Name: Goodix 550c fingerprint\nDefault: no\nPriority: 260\nConflicts: fprintd\nAuth-Type: Primary\nAuth:\n"
    "\t[success=1 default=ignore]\tpam_succeed_if.so service in kde:kde-fingerprint:sddm:sddm-greeter:login quiet\n"
    "\t[success=end default=ignore]\tpam_fprintd.so max-tries=3 timeout=15\n"
)
GENERATED_AUTH = (
    "auth\t[success=2 default=ignore]\tpam_succeed_if.so service in kde:kde-fingerprint:sddm:sddm-greeter:login quiet\n"
    "auth\t[success=end default=ignore]\tpam_fprintd.so max-tries=3 timeout=15\n"
)


def pam_root(tmp_path, enabled=True):
    env = ctl_env(tmp_path)
    root = Path(env["GOODIX550C_ROOT"])
    prof = root / "usr/share/pam-configs/goodix550c-fingerprint"
    prof.parent.mkdir(parents=True)
    prof.write_text(PROFILE_TEXT)
    (root / "etc/pam.d/common-auth").write_text(GENERATED_AUTH if enabled else "auth sufficient pam_unix.so\n")
    shimdir = tmp_path / "pshim"
    shimdir.mkdir()
    pau = shimdir / "pam-auth-update"
    pau.write_text('#!/bin/sh\necho "$@" >> "$GOODIX550C_ROOT/pau.args"\n')
    pau.chmod(0o755)
    env["PATH"] = f"{shimdir}:{env['PATH']}"
    return env, root


def test_status_json_fake_root(tmp_path):
    import json

    env, root = pam_root(tmp_path)
    r = run([CTL, "status", "--json"], env=env)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["sensor_present"] is True and d["usb_power"] == "on"
    assert d["pam_enabled"] is True and d["pam_tries"] == 3 and d["pam_timeout"] == 15
    assert d["psk_present"] is False and isinstance(d["held"], bool) and isinstance(d["patched"], bool)
    (root / "etc/goodix550c/goodix550c.psk").write_text("a" * 64)
    assert json.loads(run([CTL, "status", "--json"], env=env).stdout)["psk_present"] is True
    assert r.stdout.count("\n") == 1                       # one object, one line
    assert "a" * 64 not in r.stdout


def test_status_json_real_system_non_root_is_valid_json():
    import json

    r = run([CTL, "status", "--json"])
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    if os.geteuid() != 0:
        assert d["psk_present"] is None                   # cannot be checked without root
    for key in ("sensor_present", "patched", "held", "pam_enabled", "pam_tries", "pam_timeout", "store_ok"):
        assert key in d


def test_status_rejects_unknown_option(tmp_path):
    assert run([CTL, "status", "--bogus"], env=ctl_env(tmp_path)).returncode != 0


def test_pam_set_writes_conf_profile_and_common_auth(tmp_path):
    env, root = pam_root(tmp_path)
    r = run([CTL, "pam", "set", "--tries", "5", "--timeout", "22"], env=env)
    assert r.returncode == 0, r.stderr
    conf = root / "etc/goodix550c/pam.conf"
    assert conf.read_text() == "TRIES=5\nTIMEOUT=22\n"
    assert oct(conf.stat().st_mode & 0o777) == "0o600"
    assert "pam_fprintd.so max-tries=5 timeout=22" in (root / "usr/share/pam-configs/goodix550c-fingerprint").read_text()
    assert "pam_fprintd.so max-tries=5 timeout=22" in (root / "etc/pam.d/common-auth").read_text()
    assert "--force --enable goodix550c-fingerprint" in (root / "pau.args").read_text()
    assert "pam_succeed_if.so service in kde" in (root / "etc/pam.d/common-auth").read_text()   # rest untouched
    # status reflects it
    import json
    d = json.loads(run([CTL, "status", "--json"], env=env).stdout)
    assert (d["pam_tries"], d["pam_timeout"]) == (5, 22)


def test_pam_set_single_value_keeps_the_other(tmp_path):
    env, root = pam_root(tmp_path)
    assert run([CTL, "pam", "set", "--timeout", "9"], env=env).returncode == 0
    assert (root / "etc/goodix550c/pam.conf").read_text() == "TRIES=3\nTIMEOUT=9\n"


def test_pam_set_validates_before_touching_anything(tmp_path):
    env, root = pam_root(tmp_path)
    for args in (["--tries", "0", "--timeout", "15"], ["--tries", "6", "--timeout", "15"],
                 ["--tries", "3", "--timeout", "4"], ["--tries", "3", "--timeout", "31"],
                 ["--tries", "x", "--timeout", "15"], ["--tries", "3", "--timeout", "1e1"],
                 ["--tries", "03", "--timeout", "15"], ["--tries"], [], ["--what", "1"]):
        r = run([CTL, "pam", "set", *args], env=env)
        assert r.returncode != 0, args
    assert not (root / "etc/goodix550c/pam.conf").exists()
    assert (root / "usr/share/pam-configs/goodix550c-fingerprint").read_text() == PROFILE_TEXT
    assert not (root / "pau.args").exists()


def test_pam_set_when_profile_not_enabled_only_saves(tmp_path):
    env, root = pam_root(tmp_path, enabled=False)
    r = run([CTL, "pam", "set", "--tries", "2", "--timeout", "10"], env=env)
    assert r.returncode == 0, r.stderr
    assert "not enabled" in r.stdout
    assert "max-tries=2 timeout=10" in (root / "usr/share/pam-configs/goodix550c-fingerprint").read_text()
    assert not (root / "pau.args").exists()
    assert run([CTL, "pam", "enable"], env=env).returncode == 0
    assert "--enable goodix550c-fingerprint" in (root / "pau.args").read_text()


def test_pam_set_requires_root_without_fake_root():
    if os.geteuid() == 0:
        pytest.skip("running as root")
    r = run([CTL, "pam", "set", "--tries", "3", "--timeout", "15"])
    assert r.returncode != 0 and "needs root" in r.stderr


def test_pam_enable_normalizes_timeout_too(tmp_path):
    env, root = pam_root(tmp_path)
    ca = root / "etc/pam.d/common-auth"
    ca.write_text(GENERATED_AUTH.replace("max-tries=3 timeout=15", "max-tries=7 timeout=99"))
    assert run([CTL, "pam", "enable"], env=env).returncode == 0
    assert "pam_fprintd.so max-tries=3 timeout=15" in ca.read_text()


def test_postinst_reapplies_saved_pam_values(tmp_path):
    """The package ships default values in the profile; postinst must put the saved ones back."""
    script = (PKGDIR / "DEBIAN" / "postinst").read_text()
    # run only the re-apply block, against a temp profile and conf
    start = script.index("    PAMCONF=")
    end = script.index("    # Registers the profile only")
    block = script[start:end]
    prof = tmp_path / "profile"
    prof.write_text(PROFILE_TEXT)
    conf = tmp_path / "pam.conf"
    conf.write_text("TRIES=4\nTIMEOUT=25\n")
    block = block.replace("/etc/goodix550c/pam.conf", str(conf)).replace(
        "/usr/share/pam-configs/goodix550c-fingerprint", str(prof))
    r = subprocess.run(["sh", "-c", block], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "pam_fprintd.so max-tries=4 timeout=25" in prof.read_text()
    # garbage in the conf is ignored
    prof.write_text(PROFILE_TEXT)
    conf.write_text("TRIES=99\nTIMEOUT=-1\n")
    assert subprocess.run(["sh", "-c", block]).returncode == 0
    assert prof.read_text() == PROFILE_TEXT
