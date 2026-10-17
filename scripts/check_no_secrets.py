#!/usr/bin/env python3
"""Secret scanner gating any push of this (public) repository.

Exit codes: 0 clean, 1 findings, 2 usage error.
Never prints secret values or derived forms: only location and pattern KIND.
"""
from __future__ import annotations

import argparse
import base64
import fnmatch
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_DEFAULT = Path(__file__).resolve().parent.parent
BAD_EXT = {".psk", ".bin", ".pgm", ".bmp", ".raw", ".npy", ".der", ".key"}
HEX64 = re.compile(rb"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")
PRIVKEY = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
# Built from pieces so this file does not contain the address itself.
EMAIL = (b"richfern48" + b"@" + b"gmail.com")
EMAIL_RE = re.compile(re.escape(EMAIL), re.I)
STORE_PATH_MARKERS = ("var/lib/fprint", "research/secrets/")
# Build provenance file shipped in our libfprint debs: the only 64-hex values accepted
# in it are the two public sha256 lines the build script writes.
PROVENANCE_FILE = "GOODIX550C-BUILD"
PROVENANCE_LINE = re.compile(
    r"^(driver-series sha256|libfprint-2\.so\.2\.0\.0 sha256): [0-9a-f]{64}$")
BOUND_HASH = re.compile(r"^(?P<glob>.+):(?P<hash>[0-9a-fA-F]{64})$")


class Usage(Exception):
    pass


def load_allowlist(path: Path):
    """-> (hashes valid anywhere, path globs for extension/path/FP3 exceptions,
    [(glob, hash)] hashes valid only in files matching the glob)."""
    hashes, globs, bound = set(), [], []
    if not path.is_file():
        return hashes, globs, bound
    for line in path.read_text(errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("path:"):
            spec = line[5:].strip()
            m = BOUND_HASH.match(spec)
            if m:
                bound.append((m.group("glob"), m.group("hash").lower().encode()))
            else:
                globs.append(spec)
        elif re.fullmatch(r"[0-9a-fA-F]{64}", line):
            hashes.add(line.lower().encode())
        else:
            raise Usage(f"bad allowlist line in {path.name}")
    return hashes, globs, bound


class Patterns:
    """Derived literal byte patterns for known secrets: [(kind, bytes)]."""

    def __init__(self):
        self.items: list[tuple[str, bytes]] = []

    def add(self, kind: str, pat: bytes):
        if pat and (kind, pat) not in self.items:
            self.items.append((kind, pat))

    def add_hex_windows(self, label: str, hx: str):
        for case, h in (("", hx.lower()), ("-upper", hx.upper())):
            self.add(f"{label}:hex{case}", h.encode())
            for i in range(0, max(len(h) - 16, 0) + 1):
                self.add(f"{label}:hex16{case}", h[i:i + 16].encode())

    def add_b64(self, label: str, raw: bytes):
        for name, enc in (("base64", base64.b64encode), ("base64url", base64.urlsafe_b64encode)):
            s = enc(raw)
            self.add(f"{label}:{name}", s)
            self.add(f"{label}:{name}", s.rstrip(b"="))

    def add_secret_bytes(self, label: str, raw: bytes):
        self.add(f"{label}:raw", raw)
        self.add_hex_windows(label, raw.hex())
        self.add_b64(label, raw)
        digest = hashlib.sha256(raw).digest()
        self.add_hex_windows(f"{label}:sha256", digest.hex())
        self.add_b64(f"{label}:sha256", digest)

    def compile(self):
        by_pat: dict[bytes, str] = {}
        for kind, pat in self.items:
            by_pat.setdefault(pat, kind)
        self.by_pat = by_pat
        if by_pat:
            alts = sorted(by_pat, key=len, reverse=True)
            self.rx = re.compile(b"|".join(re.escape(p) for p in alts))
        else:
            self.rx = None

    def kinds_in(self, data: bytes):
        if not self.rx:
            return set()
        return {self.by_pat[m.group(0)] for m in self.rx.finditer(data)}


class Scanner:
    def __init__(self, patterns, allow_hashes, allow_globs, allow_bound=()):
        self.p = patterns
        self.allow_hashes = allow_hashes
        self.allow_globs = allow_globs
        self.allow_bound = list(allow_bound)
        self.findings: dict[tuple[str, str], int] = {}

    def add(self, where: str, kind: str):
        self.findings[(where, kind)] = self.findings.get((where, kind), 0) + 1

    def path_allowed(self, path: str) -> bool:
        return any(fnmatch.fnmatch(path, g) for g in self.allow_globs)

    def check_path(self, where: str, path: str):
        if self.path_allowed(path):
            return
        if Path(path).suffix.lower() in BAD_EXT:
            self.add(where, "forbidden-extension")
        if any(m in path for m in STORE_PATH_MARKERS):
            self.add(where, "fprint-store-or-secrets-path")

    def hex_allowed(self, h: bytes, path: str) -> bool:
        h = h.lower()
        # A bound hash must also be readable in the allowlist file that declares it.
        in_allowlist = Path(path).name == "secret_scan_allowlist.txt"
        return h in self.allow_hashes or any(
            h == bh and (in_allowlist or fnmatch.fnmatch(path, g)) for g, bh in self.allow_bound)

    def check_hex64(self, where: str, data: bytes, path: str, diff: bool):
        if Path(path).name != PROVENANCE_FILE:
            chunks = [data]
        else:
            # Structural rule: hex is accepted only on the exact provenance lines.
            chunks = []
            for raw in data.decode(errors="replace").splitlines():
                line = raw[1:] if diff and raw[:1] in "+- " else raw
                if not PROVENANCE_LINE.match(line):
                    chunks.append(raw.encode())
        for chunk in chunks:
            for m in HEX64.finditer(chunk):
                if not self.hex_allowed(m.group(0), path):
                    self.add(where, "hex64-not-allowlisted")

    def check_content(self, where: str, data: bytes, path: str = "", diff: bool = False):
        for kind in sorted(self.p.kinds_in(data)):
            self.add(where, f"SECRET-MATCH {kind}")
        if data.startswith(b"FP3") and not self.path_allowed(path):
            self.add(where, "fprint-print-content (FP3 magic)")
        if PRIVKEY.search(data):
            self.add(where, "private-key-block")
        if EMAIL_RE.search(data):
            self.add(where, "personal-email-in-content")
        self.check_hex64(where, data, path, diff)

    # -- targets -----------------------------------------------------------
    def scan_tree(self, root: Path, files, label: str):
        for rel in files:
            p = root / rel
            where = f"{label}:{rel}"
            self.check_path(where, rel)
            if p.is_symlink() or not p.is_file():
                continue
            try:
                data = p.read_bytes()
            except OSError:
                self.add(where, "unreadable")
                continue
            self.check_content(where, data, rel)

    def scan_history(self, repo: Path):
        # 1) text patches, attributed per commit
        proc = subprocess.Popen(
            ["git", "-C", str(repo), "log", "-p", "--all", "--no-color", "--no-ext-diff",
             "--format=commit %h"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        commit, cur = "?", ""
        for line in proc.stdout:
            if line.startswith(b"commit ") and len(line) < 40 and line[7:].strip().isalnum():
                commit = line[7:].strip().decode()
                continue
            if line.startswith(b"diff --git "):
                cur = line.split(b" b/", 1)[-1].strip().decode(errors="replace")
            if line.startswith((b"Author:", b"Commit:", b"Date:")):
                continue
            where = f"history:{commit}:{cur}" if cur else f"history:{commit}"
            self.check_content(where, line, cur, diff=True)
        proc.wait()
        # 2) every path ever touched, attributed to a commit
        out = subprocess.run(
            ["git", "-C", str(repo), "log", "--all", "--name-only", "--no-renames",
             "--format=C %h"], capture_output=True, check=False).stdout
        commit = "?"
        for raw in out.decode(errors="replace").splitlines():
            if raw.startswith("C "):
                commit = raw[2:]
            elif raw:
                self.check_path(f"history:{commit}:{raw}", raw)
        # 3) binary blobs (patches do not show them)
        objs = subprocess.run(["git", "-C", str(repo), "rev-list", "--objects", "--all"],
                              capture_output=True, check=False).stdout.decode(errors="replace")
        paths = {}
        for ln in objs.splitlines():
            sha, _, name = ln.partition(" ")
            paths.setdefault(sha, name)
        if not paths:
            return
        cat = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)

        def feed():
            cat.stdin.write(("\n".join(paths) + "\n").encode())
            cat.stdin.close()
        import threading
        t = threading.Thread(target=feed, daemon=True)
        t.start()
        while True:
            hdr = cat.stdout.readline()
            if not hdr:
                break
            parts = hdr.split()
            if len(parts) != 3:
                continue
            sha, typ, size = parts[0].decode(), parts[1], int(parts[2])
            data = cat.stdout.read(size)
            cat.stdout.read(1)
            if typ != b"blob" or b"\0" not in data:
                continue
            name = paths.get(sha, "")
            kinds = self.p.kinds_in(data)
            if data.startswith(b"FP3"):
                kinds.add("fprint-print-content (FP3 magic)")
            if kinds:
                commits = subprocess.run(
                    ["git", "-C", str(repo), "log", "--all", "--format=%h", f"--find-object={sha}"],
                    capture_output=True).stdout.decode().split()[:3]
                for k in sorted(kinds):
                    kind = k if k.startswith("fprint") else f"SECRET-MATCH {k}"
                    self.add(f"history-blob:{','.join(commits) or sha[:7]}:{name}", kind)
        cat.wait()


def git_files(repo: Path):
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
    if r.returncode != 0:
        raise Usage("not a git repository (or git failed): " + str(repo))
    return [f for f in r.stdout.decode(errors="replace").split("\0") if f]


def hex_arg(s: str) -> str:
    s = s.strip()
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2})+", s):
        raise Usage("--secret-hash must be hex")
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=REPO_DEFAULT)
    ap.add_argument("--secret", action="append", default=[], metavar="FILE")
    ap.add_argument("--secret-hash", action="append", default=[], metavar="HEX")
    ap.add_argument("--deb", action="append", default=[], metavar="FILE")
    ap.add_argument("--path", action="append", default=[], metavar="DIR")
    ap.add_argument("--allowlist", type=Path, default=None)
    ap.add_argument("--no-history", action="store_true", help="skip git log -p --all")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        repo = args.repo.resolve()
        allow_h, allow_g, allow_b = load_allowlist(args.allowlist or repo / "scripts" / "secret_scan_allowlist.txt")
        pats = Patterns()
        secret_files = [Path(s) for s in args.secret]
        explicit = bool(secret_files)
        if not explicit:
            sd = repo / "research" / "secrets"
            try:
                secret_files = sorted(p for p in sd.iterdir() if p.is_file())
            except OSError:
                print("note: research/secrets not readable; use --secret/--secret-hash", file=sys.stderr)
        n_secret = 0
        for i, f in enumerate(secret_files, 1):
            try:
                raw = f.read_bytes()
            except OSError:
                if explicit:
                    raise Usage(f"cannot read --secret file #{i}")
                print(f"note: secret file #{i} unreadable; skipped", file=sys.stderr)
                continue
            label = f"secret#{i}({f.name})"
            forms = {raw, raw.strip()}
            txt = raw.strip()
            if re.fullmatch(rb"(?:[0-9a-fA-F]{2})+", txt):
                forms.add(bytes.fromhex(txt.decode()))
            for form in forms:
                if len(form) >= 8:
                    pats.add_secret_bytes(label, form)
                    n_secret += 1
        for i, h in enumerate(args.secret_hash, 1):
            hx = hex_arg(h)
            label = f"secret-hash#{i}"
            pats.add_hex_windows(label, hx)
            pats.add_b64(label, bytes.fromhex(hx))
            n_secret += 1
        for d in args.deb:
            if not Path(d).is_file():
                raise Usage("--deb file not found: " + d)
        for d in args.path:
            if not Path(d).is_dir():
                raise Usage("--path not a directory: " + d)
        pats.compile()
        sc = Scanner(pats, allow_h, allow_g, allow_b)
        files = git_files(repo)
        sc.scan_tree(repo, files, "tree")
        if not args.no_history:
            sc.scan_history(repo)
        for deb in args.deb:
            with tempfile.TemporaryDirectory(prefix="nosecrets-") as td:
                r = subprocess.run(["dpkg-deb", "-x", deb, td], capture_output=True)
                if r.returncode != 0:
                    raise Usage("dpkg-deb failed on " + os.path.basename(deb))
                rels = [str(p.relative_to(td)) for p in Path(td).rglob("*") if p.is_file() or p.is_symlink()]
                sc.scan_tree(Path(td), rels, f"deb:{os.path.basename(deb)}")
        for d in args.path:
            dp = Path(d)
            rels = [str(p.relative_to(dp)) for p in dp.rglob("*") if p.is_file() or p.is_symlink()]
            sc.scan_tree(dp, rels, f"path:{d}")
    except Usage as e:
        print(f"usage error: {e}", file=sys.stderr)
        return 2

    print(f"scanned: {len(files)} tracked files, history={'no' if args.no_history else 'yes'}, "
          f"debs={len(args.deb)}, paths={len(args.path)}, secret-patterns-sources={n_secret}")
    if not n_secret:
        print("WARNING: no secret material loaded; only heuristics ran", file=sys.stderr)
    if not sc.findings:
        print("CLEAN")
        return 0
    for (where, kind), n in sorted(sc.findings.items()):
        print(f"FINDING {where} :: {kind}" + (f" (x{n})" if n > 1 else ""))
    print(f"{len(sc.findings)} finding(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
