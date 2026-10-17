from __future__ import annotations

import gzip
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_goodix550c_debs.sh"
REAL_STOCK = Path.home() / "goodix550c-debs" / "stock" / "libfprint-2-2_1%3a1.94.9-1_amd64.deb"

pytestmark = pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="dpkg-deb not available")

HWDB = """\
# SPDX-License-Identifier: LGPL-2.1-or-later
# generated

# Supported by libfprint driver aes1610
usb:v08FFp1600*
 ID_AUTOSUSPEND=1
 ID_PERSIST=0

# Supported by libfprint driver goodixmoc
usb:v27C6p5395*
usb:v27C6p550A*
usb:v27C6p550C*
usb:v27C6p5584*
 ID_AUTOSUSPEND=1
 ID_PERSIST=0

# Supported by libfprint driver other
usb:v3538p0930*
 ID_AUTOSUSPEND=1
 ID_PERSIST=0
"""


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)


def make_fake_stock(tmp: Path, hwdb: str = HWDB) -> Path:
    tree = tmp / "faketree"
    (tree / "DEBIAN").mkdir(parents=True)
    (tree / "DEBIAN" / "control").write_text(
        "Package: libfprint-2-2\nVersion: 1:1.94.9-1\nArchitecture: amd64\n"
        "Maintainer: x <x@example.com>\nDescription: fake\n fake stock\n"
    )
    (tree / "DEBIAN" / "shlibs").write_text("libfprint-2 2 libfprint-2-2 (>= 1:1.94.9)\n")
    (tree / "DEBIAN" / "triggers").write_text("activate-noawait ldconfig\n")
    lib = tree / "usr/lib/x86_64-linux-gnu"
    lib.mkdir(parents=True)
    (lib / "libfprint-2.so.2.0.0").write_bytes(b"stock-so")
    (lib / "libfprint-2.so.2").symlink_to("libfprint-2.so.2.0.0")
    hw = tree / "usr/lib/udev/hwdb.d"
    hw.mkdir(parents=True)
    (hw / "60-autosuspend-libfprint-2.hwdb").write_text(hwdb)
    doc = tree / "usr/share/doc/libfprint-2-2"
    doc.mkdir(parents=True)
    (doc / "changelog.Debian.gz").write_bytes(
        gzip.compress(b"libfprint (1:1.94.9-1) unstable; urgency=medium\n\n  * x\n\n -- A <a@b>  Thu, 20 Feb 2025 12:00:00 +0000\n")
    )
    deb = tmp / "stock.deb"
    r = run(["dpkg-deb", "--root-owner-group", "--build", tree, deb])
    assert r.returncode == 0, r.stderr
    return deb


@pytest.fixture()
def env(tmp_path: Path):
    stock = make_fake_stock(tmp_path)
    so = tmp_path / "libfprint-2.so.2.0.0"
    so.write_bytes(b"\x7fELF fake patched library")
    series = tmp_path / "driver-series"
    series.write_text("0001-x.patch\n")
    out = tmp_path / "out"
    work = tmp_path / "work"

    def build(*extra, stock_deb=stock):
        return run(
            [SCRIPT, "--so", so, "--out", out, "--stock-deb", stock_deb, "--series", series, "--work", work, *extra]
        )

    return build, out, work, so, series


def field(deb: Path, name: str) -> str:
    r = run(["dpkg-deb", "-f", deb, name])
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def contents(deb: Path, member: str) -> bytes:
    p = subprocess.run(
        f"dpkg-deb --fsys-tarfile '{deb}' | tar -xO '{member}'", shell=True, capture_output=True, check=True
    )
    return p.stdout


def test_help():
    r = run([SCRIPT, "--help"])
    assert r.returncode == 0 and "--so" in r.stdout


def test_control_rendering(env):
    build, out, _, _, series = env
    r = build()
    assert r.returncode == 0, r.stderr
    deb = out / "libfprint-2-2_1.94.10+goodix550c1_amd64.deb"
    assert deb.exists()
    assert field(deb, "Package") == "libfprint-2-2"
    assert field(deb, "Version") == "1:1.94.10+goodix550c1"
    prov = field(deb, "Provides")
    assert "libfprint-goodix550c (= 1)" in prov and "libfprint-2-2 (= 1:1.94.10)" in prov
    assert "Local goodix550c build" in field(deb, "Maintainer")
    assert "libopencv-core410" in field(deb, "Depends")
    sha = subprocess.run(["sha256sum", series], capture_output=True, text=True).stdout.split()[0]
    assert sha in field(deb, "Description")
    assert "@" not in field(deb, "Installed-Size")
    shlibs = run(["dpkg-deb", "-I", deb, "shlibs"]).stdout
    assert "(>= 1:1.94.10)" in shlibs


def test_so_swapped_and_symlink(env):
    build, out, _, so, _ = env
    assert build().returncode == 0
    deb = out / "libfprint-2-2_1.94.10+goodix550c1_amd64.deb"
    assert contents(deb, "./usr/lib/x86_64-linux-gnu/libfprint-2.so.2.0.0") == so.read_bytes()
    listing = run(["dpkg-deb", "-c", deb]).stdout
    assert "libfprint-2.so.2 -> libfprint-2.so.2.0.0" in listing


def test_hwdb_550c_removed_others_intact(env):
    build, out, _, _, _ = env
    assert build().returncode == 0
    deb = out / "libfprint-2-2_1.94.10+goodix550c1_amd64.deb"
    text = contents(deb, "./usr/lib/udev/hwdb.d/60-autosuspend-libfprint-2.hwdb").decode()
    assert "550C" not in text.upper().replace("55A", "")
    assert "usb:v27C6p550C" not in text
    assert text == HWDB.replace("usb:v27C6p550C*\n", "")


def test_hwdb_unchanged_when_no_550c(tmp_path):
    hw = HWDB.replace("usb:v27C6p550C*\n", "")
    stock = make_fake_stock(tmp_path, hw)
    so = tmp_path / "so"
    so.write_bytes(b"x")
    series = tmp_path / "s"
    series.write_text("a\n")
    r = run([SCRIPT, "--so", so, "--out", tmp_path / "o", "--stock-deb", stock, "--series", series, "--work", tmp_path / "w"])
    assert r.returncode == 0, r.stderr
    deb = tmp_path / "o" / "libfprint-2-2_1.94.10+goodix550c1_amd64.deb"
    assert contents(deb, "./usr/lib/udev/hwdb.d/60-autosuspend-libfprint-2.hwdb").decode() == hw


def test_hwdb_block_dropped_if_550c_was_alone(tmp_path):
    hw = HWDB.replace("usb:v27C6p5395*\nusb:v27C6p550A*\nusb:v27C6p550C*\nusb:v27C6p5584*\n", "usb:v27C6p550C*\n")
    stock = make_fake_stock(tmp_path, hw)
    so = tmp_path / "so"
    so.write_bytes(b"x")
    series = tmp_path / "s"
    series.write_text("a\n")
    r = run([SCRIPT, "--so", so, "--out", tmp_path / "o", "--stock-deb", stock, "--series", series, "--work", tmp_path / "w"])
    assert r.returncode == 0, r.stderr
    deb = tmp_path / "o" / "libfprint-2-2_1.94.10+goodix550c1_amd64.deb"
    text = contents(deb, "./usr/lib/udev/hwdb.d/60-autosuspend-libfprint-2.hwdb").decode()
    assert "550C" not in text and "goodixmoc" not in text
    assert "usb:v08FFp1600*" in text and "usb:v3538p0930*" in text
    # no orphaned property lines: every property line follows a match or property line
    prev = None
    for line in text.splitlines():
        if line.startswith(" "):
            assert prev is not None and (prev.startswith("usb:") or prev.startswith(" "))
        prev = line


def test_build_record_and_md5sums(env):
    build, out, _, so, series = env
    assert build().returncode == 0
    deb = out / "libfprint-2-2_1.94.10+goodix550c1_amd64.deb"
    rec = contents(deb, "./usr/share/doc/libfprint-2-2/GOODIX550C-BUILD").decode()
    sha = lambda p: subprocess.run(["sha256sum", p], capture_output=True, text=True).stdout.split()[0]
    assert sha(series) in rec and sha(so) in rec
    assert "git rev:" in rec and "git dirty:" in rec and "build date:" in rec
    md5 = run(["dpkg-deb", "-I", deb, "md5sums"]).stdout
    assert "usr/share/doc/libfprint-2-2/GOODIX550C-BUILD" in md5
    assert "libfprint-2.so.2.0.0" in md5
    cl = gzip.decompress(contents(deb, "./usr/share/doc/libfprint-2-2/changelog.Debian.gz")).decode()
    assert cl.startswith("libfprint (1:1.94.10+goodix550c1)")
    assert "1:1.94.9-1" in cl


def test_refuse_overwrite(env):
    build, out, _, _, _ = env
    assert build("--n", "3").returncode == 0
    deb = out / "libfprint-2-2_1.94.10+goodix550c3_amd64.deb"
    before = deb.read_bytes()
    r = build("--n", "3")
    assert r.returncode != 0
    assert "refusing to overwrite" in r.stderr
    assert deb.read_bytes() == before


def test_n_auto_bump_and_sha256sums(env):
    build, out, _, _, _ = env
    for expected in (1, 2):
        assert build().returncode == 0
        assert (out / f"libfprint-2-2_1.94.10+goodix550c{expected}_amd64.deb").exists()
    (out / "libfprint-2-2_1.94.10+goodix550c7_amd64.deb").write_bytes(b"placeholder")
    assert build().returncode == 0
    deb = out / "libfprint-2-2_1.94.10+goodix550c8_amd64.deb"
    assert field(deb, "Version") == "1:1.94.10+goodix550c8"
    sums = (out / "SHA256SUMS").read_text()
    for n in (1, 2, 7, 8):
        assert f"libfprint-2-2_1.94.10+goodix550c{n}_amd64.deb" in sums
    r = run("sha256sum -c SHA256SUMS".split(), cwd=out)
    assert r.returncode == 0, r.stdout + r.stderr


def test_missing_so_is_error(env, tmp_path):
    _, out, work, _, series = env
    (tmp_path / "x").mkdir()
    stock = make_fake_stock(tmp_path / "x")
    r = run([SCRIPT, "--so", tmp_path / "nope", "--out", out, "--stock-deb", stock, "--series", series, "--work", work])
    assert r.returncode != 0 and "not a non-empty file" in r.stderr


@pytest.mark.skipif(not REAL_STOCK.exists(), reason="real stock deb not present")
def test_real_stock_deb(tmp_path):
    so = tmp_path / "so"
    so.write_bytes(b"fake")
    series = tmp_path / "s"
    series.write_text("a\n")
    r = run([SCRIPT, "--so", so, "--out", tmp_path / "o", "--stock-deb", REAL_STOCK, "--series", series, "--work", tmp_path / "w"])
    assert r.returncode == 0, r.stderr
    deb = tmp_path / "o" / "libfprint-2-2_1.94.10+goodix550c1_amd64.deb"
    text = contents(deb, "./usr/lib/udev/hwdb.d/60-autosuspend-libfprint-2.hwdb").decode()
    assert "p550C" not in text and "p550A*" in text and "p5584*" in text
    stock_text = subprocess.run(
        f"dpkg-deb --fsys-tarfile '{REAL_STOCK}' | tar -xO ./usr/lib/udev/hwdb.d/60-autosuspend-libfprint-2.hwdb",
        shell=True, capture_output=True, text=True, check=True,
    ).stdout
    assert text == stock_text.replace("usb:v27C6p550C*\n", "")
    ctrl = run(["dpkg-deb", "-I", deb, "triggers"]).stdout
    assert "ldconfig" in ctrl
