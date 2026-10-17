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
    d = out / "goodix550c-fingerprint_1.0.1_all.deb"
    assert d.exists()
    return d


def field(deb, name):
    return run(["dpkg-deb", "-f", deb, name]).stdout.strip()


def test_control(deb):
    assert field(deb, "Package") == "goodix550c-fingerprint"
    assert field(deb, "Architecture") == "all"
    assert field(deb, "Version") == "1.0.1"
    assert field(deb, "Depends") == "libfprint-goodix550c (>= 3), fprintd, libpam-fprintd, udev"
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
    ]:
        assert path in listing, path
    for forbidden in ["system-sleep", "unstick", "/opt/", ".psk"]:
        assert forbidden not in listing
    ctl = [l for l in listing.splitlines() if l.endswith("usr/sbin/goodix550c-ctl")][0]
    assert ctl.startswith("-rwxr-xr-x root/root")


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
    assert "goodix550c-fingerprint_1.0.1_all.deb" in (tmp_path / "SHA256SUMS").read_text()


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
    r = run([CTL, "pam", "enable"], env=env)
    assert r.returncode == 0, r.stderr
    assert "max-tries=1" in (root / "etc/pam.d/common-auth").read_text()
    assert "--enable goodix550c-fingerprint" in (root / "pau.args").read_text()
