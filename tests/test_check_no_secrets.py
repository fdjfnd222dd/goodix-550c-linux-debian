import base64
import hashlib
import shutil
import subprocess
import sys

import pytest
from _helpers import ROOT
from _helpers import run as _run

SCRIPT = ROOT / "scripts" / "check_no_secrets.py"
SECRET = bytes(range(0x41, 0x41 + 32)) + b"\x00\xfe"  # fake, generated for tests
SECRET_HEX = SECRET.hex()


def run(*args, cwd=None):
    p = _run([sys.executable, SCRIPT, *args], cwd=cwd)
    return p.returncode, p.stdout, p.stderr


def git(repo, *a):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    *a], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    git(r, "init", "-q")
    (r / "README.md").write_text("hello\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    return r


@pytest.fixture
def secret_file(tmp_path):
    f = tmp_path / "psk.bin.secret"
    f.write_bytes(SECRET)
    return f


def no_leak(*streams):
    forms = [SECRET_HEX, SECRET_HEX.upper(), base64.b64encode(SECRET).decode(),
             hashlib.sha256(SECRET).hexdigest(), SECRET_HEX[:16], SECRET_HEX[8:24]]
    for s in streams:
        for f in forms:
            assert f not in s


def test_clean_repo(repo, secret_file):
    rc, out, err = run("--repo", repo, "--secret", secret_file)
    assert rc == 0 and "CLEAN" in out
    no_leak(out, err)


def test_detect_in_worktree_each_form(repo, secret_file):
    for name, content in {
        "a.txt": SECRET_HEX, "b.txt": SECRET_HEX.upper(),
        "c.txt": base64.b64encode(SECRET).decode(),
        "d.txt": hashlib.sha256(SECRET).hexdigest(),
        "e.txt": "x " + SECRET_HEX[10:26] + " y",
    }.items():
        (repo / name).write_text(content + "\n")
    (repo / "raw.dat").write_bytes(b"junk" + SECRET + b"junk")
    git(repo, "add", "-A")
    rc, out, err = run("--repo", repo, "--secret", secret_file, "--no-history")
    assert rc == 1
    for name in "a.txt b.txt c.txt d.txt e.txt raw.dat".split():
        assert f"tree:{name}" in out
    assert "SECRET-MATCH" in out
    no_leak(out, err)


def test_detect_in_history_after_deletion(repo, secret_file):
    (repo / "leak.txt").write_text(SECRET_HEX + "\n")
    (repo / "leak.dat").write_bytes(b"\0\0" + SECRET)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "oops")
    git(repo, "rm", "-q", "leak.txt", "leak.dat")
    git(repo, "commit", "-qm", "remove")
    rc, out, err = run("--repo", repo, "--secret", secret_file)
    assert rc == 1
    assert "history:" in out and "leak.txt" in out
    assert "history-blob:" in out
    assert "tree:leak" not in out
    no_leak(out, err)


def test_secret_hash_option(repo):
    h = hashlib.sha256(b"fake psk").hexdigest()
    (repo / "x.txt").write_text(h + "\n")
    git(repo, "add", "-A")
    rc, out, err = run("--repo", repo, "--secret-hash", h, "--no-history")
    assert rc == 1 and "secret-hash#1" in out
    assert h not in out and h not in err


@pytest.mark.skipif(not shutil.which("dpkg-deb"), reason="dpkg-deb missing")
def test_detect_in_deb(repo, secret_file, tmp_path):
    root = tmp_path / "pkg"
    (root / "DEBIAN").mkdir(parents=True)
    (root / "DEBIAN" / "control").write_text(
        "Package: t\nVersion: 1\nArchitecture: all\nMaintainer: t <t@example.invalid>\nDescription: t\n")
    (root / "usr/share/t").mkdir(parents=True)
    (root / "usr/share/t/blob").write_bytes(b"\0" + SECRET)
    (root / "var/lib/fprint/x").mkdir(parents=True)
    deb = tmp_path / "t.deb"
    subprocess.run(["dpkg-deb", "--root-owner-group", "-b", str(root), str(deb)],
                   check=True, capture_output=True)
    rc, out, err = run("--repo", repo, "--secret", secret_file, "--deb", deb, "--no-history")
    assert rc == 1 and "deb:t.deb:usr/share/t/blob" in out
    no_leak(out, err)


def make_deb(tmp_path, files):
    """Build a throwaway .deb holding {relative path: text}."""
    root = tmp_path / "pkg"
    (root / "DEBIAN").mkdir(parents=True)
    (root / "DEBIAN" / "control").write_text(
        "Package: t\nVersion: 1\nArchitecture: all\nMaintainer: t <t@example.invalid>\nDescription: t\n")
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    deb = tmp_path / "t.deb"
    subprocess.run(["dpkg-deb", "--root-owner-group", "-b", str(root), str(deb)],
                   check=True, capture_output=True)
    return deb


BUILD_REL = "usr/share/doc/libfprint-2-2/GOODIX550C-BUILD"
PROVENANCE = ("package: libfprint-2-2 1:1.94.10+goodix550c5\n"
              "driver-series sha256: " + "ab" * 32 + "\n"
              "git rev: 0123456789abcdef0123456789abcdef01234567\n"
              "libfprint-2.so.2.0.0 sha256: " + "cd" * 32 + "\n")


@pytest.mark.skipif(not shutil.which("dpkg-deb"), reason="dpkg-deb missing")
def test_deb_build_provenance_hashes_are_accepted(repo, secret_file, tmp_path):
    deb = make_deb(tmp_path, {BUILD_REL: PROVENANCE})
    rc, out, _ = run("--repo", repo, "--secret", secret_file, "--deb", deb, "--no-history")
    assert rc == 0 and "CLEAN" in out, out


@pytest.mark.skipif(not shutil.which("dpkg-deb"), reason="dpkg-deb missing")
def test_stray_hex64_in_build_provenance_is_flagged(repo, secret_file, tmp_path):
    deb = make_deb(tmp_path, {BUILD_REL: PROVENANCE + "note: " + "ef" * 32 + "\n"})
    rc, out, _ = run("--repo", repo, "--secret", secret_file, "--deb", deb, "--no-history")
    assert rc == 1 and "hex64-not-allowlisted" in out and BUILD_REL in out
    # Same value under a provenance key but with the wrong key name is flagged too.
    deb2 = make_deb(tmp_path / "b", {BUILD_REL: "psk sha256: " + "ef" * 32 + "\n"})
    rc, out, _ = run("--repo", repo, "--secret", secret_file, "--deb", deb2, "--no-history")
    assert rc == 1 and "hex64-not-allowlisted" in out


@pytest.mark.skipif(not shutil.which("dpkg-deb"), reason="dpkg-deb missing")
def test_secret_pattern_in_build_provenance_is_still_flagged(repo, secret_file, tmp_path):
    line = "driver-series sha256: " + hashlib.sha256(SECRET).hexdigest() + "\n"
    deb = make_deb(tmp_path, {BUILD_REL: line})
    rc, out, err = run("--repo", repo, "--secret", secret_file, "--deb", deb, "--no-history")
    assert rc == 1 and "SECRET-MATCH" in out
    no_leak(out, err)


def test_path_bound_allowlist_hash_only_applies_to_matching_files(repo, secret_file):
    h = "12" * 32
    (repo / "scripts" / "secret_scan_allowlist.txt").write_text(f"path:docs/*:{h}\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.txt").write_text(h + "\n")
    git(repo, "add", "-A")
    rc, out, _ = run("--repo", repo, "--secret", secret_file, "--no-history")
    assert rc == 0, out
    (repo / "other.txt").write_text(h + "\n")
    git(repo, "add", "-A")
    rc, out, _ = run("--repo", repo, "--secret", secret_file, "--no-history")
    assert rc == 1 and "tree:other.txt" in out and "tree:docs/a.txt" not in out


def test_path_glob_does_not_exempt_hex64(repo, secret_file):
    (repo / "scripts" / "secret_scan_allowlist.txt").write_text("path:docs/*\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.txt").write_text("34" * 32 + "\n")
    git(repo, "add", "-A")
    rc, out, _ = run("--repo", repo, "--secret", secret_file, "--no-history")
    assert rc == 1 and "hex64-not-allowlisted" in out


def test_hex64_and_allowlist(repo, secret_file):
    h = "ab" * 32
    (repo / "h.txt").write_text(h + "\n")
    git(repo, "add", "-A")
    rc, out, _ = run("--repo", repo, "--secret", secret_file)
    assert rc == 1 and "hex64-not-allowlisted" in out
    (repo / "scripts" / "secret_scan_allowlist.txt").write_text(f"{h}  # test vector\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "allow")
    # history still has the hex in the allowlisted form only
    rc, out, _ = run("--repo", repo, "--secret", secret_file)
    assert rc == 0, out


def test_extension_path_email_and_print_heuristics(repo, secret_file):
    (repo / "k.der").write_bytes(b"x")
    (repo / "n.txt").write_text("mail " + "richfern48" + "@gmail.com\n")
    (repo / "p.dat").write_bytes(b"FP3\x00\x01")
    d = repo / "var/lib/fprint"
    d.mkdir(parents=True)
    (d / "f").write_text("x")
    git(repo, "add", "-A")
    rc, out, _ = run("--repo", repo, "--secret", secret_file, "--no-history")
    assert rc == 1
    for k in ("forbidden-extension", "personal-email-in-content",
              "fprint-print-content", "fprint-store-or-secrets-path"):
        assert k in out


def test_email_in_author_metadata_not_flagged(repo, secret_file):
    (repo / "z.txt").write_text("z\n")
    git(repo, "add", "-A")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t",
                    "-c", "user.email=" + "richfern48" + "@gmail.com", "commit", "-qm", "m"],
                   check=True, capture_output=True)
    rc, out, _ = run("--repo", repo, "--secret", secret_file)
    assert rc == 0, out


def test_usage_errors(repo, tmp_path):
    assert run("--repo", repo, "--secret-hash", "zz")[0] == 2
    assert run("--repo", repo, "--deb", tmp_path / "nope.deb")[0] == 2
    assert run("--repo", repo, "--secret", tmp_path / "nope")[0] == 2
    assert run("--repo", tmp_path)[0] == 2
    assert run("--bogus")[0] == 2
