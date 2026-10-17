# PLAN.md — Goodix 27c6:550c on Debian 13 / KDE: reliability → packaging → GitHub release

> First action on approval: save this file as `~/src/goodix-550c-linux-driver/PLAN.md` on new branch `debian-reliability`. Opus (main session) orchestrates + reviews; Sonnet subagents implement one work package (WP) each; human runs every `sudo` command as ONE line pasted into Konsole (no `!`, no heredocs).

## 1. Context
- Goodix 27c6:550c, fw `GF5288_GM168SEC_APP_13021`, Lenovo Yoga 9 14IAP7, Debian 13 trixie, kernel 6.12, KDE/SDDM. Replacement lib `libfprint-2-2 1:1.94.10+goodix550c1` (held; Debian candidate `1:1.94.9-1`), fprintd/libpam-fprintd `1.94.5-2`. TOD not available on trixie → keep full replacement lib.
- Working-but-fragile today: hand-edited `/etc/pam.d/common-auth`, local `/etc/pam.d/kde` override, `/etc/systemd/system/fprintd.service.d/{10,20}-*.conf` (env + ExecStartPre unstick probe in `/opt`), `/usr/lib/systemd/system-sleep/goodix550c`, TLP denylist, `~/*.sh` scripts, single known-good deb that the repackage script overwrites.
- Symptoms: (P1) stale TLS on open (sensor stuck); (P2) "Remove your finger" loops / reference captured with finger on pad; (P3) false rejects; (P4) PAM retries amplify P2/P3 (no-match reported before finger-up wait → next try starts with finger down), every sudo/polkit waits 22–30 s, lock screen "Device was already claimed" (common-auth + kde-fingerprint both claim).
- Goal order (user-decided): real logins reliable → no stuck sensor → packaging that survives restores/updates → opt-in GitHub Release `.deb`s for other Debian users (needs their original Windows install for the PSK). **All in one session today.**
- Repo: clean `main @04c67f1`, **public** remote `the-great-king-bart/goodix-550c-linux-driver`; `build/`, `research/`, `.venv` git-ignored.

## 2. Guiding rules (every WP)
1. **Safety invariants untouched**: A4/E0/E2/F0/F4 always denied (`goodix53x5-safety.h:41-49`); volatile ops need build flag + runtime env; manual FDT double-gated; firmware 13021 only; self-heal (`session.c:813-1385`) stays `#if 0`; PSK external only + wiped; never log keys/images/templates; all waits bounded; suspend refused while polling; blank reference never stored; PAM `default=ignore` (password always works); matcher threshold 150 (`private.h:80`) **never lowered**.
2. **Patch-series discipline**: `build/` is generated. Every driver change = new `patches/goodix-550c/00NN-*.patch` appended to `driver-series` + matching assertions in `tests/test_goodix550c_patch_policy.py`. Rebuild: `scripts/fetch_upstream_sources.sh --offline && scripts/build_goodix550c_libfprint.sh --allow-volatile-init --allow-manual-fdt-poll --stage-dir build/rebuild-vi-mfp` (runs native tests), then `.venv/bin/pytest`.
3. **Versioned debs only**: each build gets new `+goodix550cN`; builder refuses to overwrite; all debs in `~/goodix550c-debs/{stock,patched}/` (home is excluded from Timeshift → survives restores).
4. **Measure then fix**: baseline from WP1 build; a later change is accepted only if the same protocol shows it beats baseline (§5 targets).
5. **Human commands**: one physical line, `&&`-chained; each preceded by "what it does" and followed by "what you should see".
6. **PAM safety**: before any PAM change the human keeps `sudo -i` open in a second Konsole tab; verify TTY password login (Ctrl+Alt+F3) before closing it.
7. **Git**: branch `debian-reliability`, one commit per WP after Opus review. Secret scan (WP8) mandatory before any push; push/publish only on the user's explicit go-ahead.
8. **Sonnet scope**: edits only its WP's files; never sudo; never touches the device; returns diff + test output + exact human commands.

## 3. Today's execution schedule (parallel lanes)
Agent work runs in parallel; human check-ins (H1–H6) are the only serial bottleneck. Rough wall-clock ≈ 7–10 h.

| Block | Agents (parallel Sonnet) | Human check-in | Est. |
|---|---|---|---|
| A | WP0 (file prep) · WP0b deb builder · WP1 patch 0015 + score_report + session script | **H1**: WP0 backup line | 1–1.5 h |
| B | WP3 patch 0016 · WP4 patches 0017/0018 · WP8 secret scanner (drafted while baseline runs) | **H2**: install `+c2`, baseline B1–B5 (~20 min), WP2 PAM switch + tests (~10 min) | 1.5–2 h |
| C | WP6 package + `goodix550c-ctl` (drafting) | **H3**: A/B stale-TLS (workarounds off) then install `+c3` + repeat (~20 min) | 1–1.5 h |
| D | iterate on WP4 based on numbers | **H4**: install 0017 deb → B1/B2/B3 (~15 min); then 0018 deb → same (2–3 rounds possible) | 1.5–2 h |
| E | WP7 recovery docs · WP8 docs | **H5**: re-enroll + full validation B1–B6 (~40 min), WP6 migration line | 1–1.5 h |
| F | WP9 release assets, install guide, VM smoke test | **H6**: WP7 rollback + Timeshift drills (~20 min); approve push + release | 1 h |

Optional `0019 settle-trim` only if D finishes early. If time runs out, cut order: WP9 → 0019 → WP7 drill 2; never cut WP0, WP2, WP3, WP6.

## 4. Work packages
Dependency: `WP0 → WP0b → WP1 → {WP2, WP3} → WP4 → WP5 → WP6 → WP7 → WP8 → WP9` (code for WP3/WP4/WP6/WP8 is drafted early in parallel; installed/measured in order).

### WP0 — Safety net (no driver change)
- Agent: create `~/goodix550c-debs/{stock,patched,legacy}`; copy `build/deb/libfprint-2-2_1.94.10+goodix550c1_amd64.deb` → `patched/`; in `stock/` run `apt-get download libfprint-2-2=1:1.94.9-1 fprintd=1.94.5-2 libpam-fprintd=1.94.5-2`; `SHA256SUMS` in both; copy `~/fp-autofix-install.sh ~/restore-fp-runtime.sh ~/enroll-finger.sh ~/repackage-and-install-fp.sh` + drop-in texts into `legacy/`; `git switch -c debian-reliability`; commit PLAN.md.
- Human (H1): `sudo install -d -m700 /var/backups/goodix550c && sudo cp -a /etc/pam.d/common-auth /etc/pam.d/kde /etc/pam.d/sudo /etc/pam.d/sddm /etc/systemd/system/fprintd.service.d /usr/lib/systemd/system-sleep/goodix550c /usr/local/sbin/goodix550c-unstick /var/backups/goodix550c/ && sudo cp -a /var/lib/fprint /var/backups/goodix550c/fprint-$(date +%F)`
- Accept: `sha256sum -c` OK; `dpkg-deb -I` versions right; backup dir populated.

### WP0b — Versioned, non-overwriting library deb builder
- Files: `packaging/libfprint-2-2/{control.in,changelog-entry}`, `scripts/build_goodix550c_debs.sh`, `tests/test_packaging.py`.
- Approach: `dpkg-deb -R` stock `1:1.94.9-1` into `build/pkg/libfprint-2-2/` (keeps shlibs/symbols/triggers); swap in built `libfprint-2.so.2.0.0` from `build/rebuild-vi-mfp/builddir` (+ symlink); **delete `usb:v27C6p550C*` from staged `60-autosuspend-libfprint-2.hwdb`**; control `Version: 1:1.94.10+goodix550c$N`, `Provides: libfprint-goodix550c (= $N)`; regenerate md5sums; record `driver-series` sha256 + git rev in `/usr/share/doc/libfprint-2-2/GOODIX550C-BUILD`; `dpkg-deb --root-owner-group --build` into `~/goodix550c-debs/patched/`; exit non-zero if target exists; N defaults to max+1.
- Accept: pytest (control rendering, hwdb no longer lists 550c, refuse-overwrite, bump); `dpkg-deb -c` sane; lintian logged (non-blocking).

### WP1 — Timing-neutral instrumentation + baseline
- Why: `G_MESSAGES_DEBUG` switches on exhaustive scoring (`auth.c:32-36,224-226,332-333`) and changes timing.
- **Patch 0015 `log-attempt-summary`** (logging only), gated on `GOODIX550C_LOG_SUMMARY=1`, `g_message` in domain `libfprint-goodix53x5`:
  - `goodix550c open:` result, total ms, phase reached (claim/ping/fw/otp/tls), `drain_bytes` (0 for now), `tls_retry` (0).
  - `goodix550c attempt:` action, ms ready→finger-down, finger-down polls, settle ms, reference mean, reference retries, non-contact ×1000, keypoints, best score (non-exhaustive, `early_exit` flag), threshold, result (`match`/`no-match`/`retry:<reason>`), signed-delta stats (log-only).
  - Integers only. Policy test: env-gated, integer specifiers only, no exhaustive-path calls, no PSK/OTP/frame/template data.
- **`scripts/goodix550c_score_report.py`**: extend `SAMPLE_RE` to `identify: gallery\[(\d+)\] sample (\d+) sigfm_score (\d+)`; parse the two summary lines; split on markers from `logger -t goodix550c-session "label=<genuine|impostor|present-at-start|opens|sudo> finger=<name> run=<id>"`; per-label n, first-try rate, ≤2-try rate, retry-reason histogram, score min/median/max, impostor max, open failures by phase, median open ms; `--json` for build diffs.
- **`scripts/goodix550c_session.sh`** (user-level): prompts each touch, writes markers, runs report over `journalctl --since`.
- Baseline blocks: **B1** genuine ×20 (lift fully, touch after prompt) · **B2** present-at-start ×10 · **B3** impostor ×10 (left index) · **B4** opens ×50 no touch (`timeout -s INT 5 fprintd-verify` loop) · **B5** sudo ×10 (`sudo -k && time sudo true`) · **B6** suspend→resume→lock-screen finger unlock ×5 (human enters pass/fail).
- Human (H2): `sudo apt-mark unhold libfprint-2-2 && sudo dpkg -i ~/goodix550c-debs/patched/libfprint-2-2_1.94.10+goodix550c2_amd64.deb && sudo apt-mark hold libfprint-2-2 && echo 'Environment=GOODIX550C_LOG_SUMMARY=1' | sudo tee -a /etc/systemd/system/fprintd.service.d/10-goodix550c.conf && sudo systemctl daemon-reload && sudo systemctl restart fprintd` then run session script.
- Accept: tests green; `research/baseline/<date>-goodix550c2.json` saved; non-identifying summary committed to `docs/measurements.md`. Rollback: reinstall `+goodix550c1` with same pattern.

### WP2 — PAM/UX configuration (quick win)
- Goal: sudo/polkit try the finger once, then fast password fallback; KDE lock screen fingerprint only via vendor `kde-fingerprint` (no double claim); survives `pam-auth-update`.
- File: `packaging/goodix550c-fingerprint/usr/share/pam-configs/goodix550c-fingerprint`:
  ```
  Name: Goodix 550c fingerprint (sudo/polkit; skips KDE lock screen/SDDM/login)
  Default: no
  Priority: 260
  Conflicts: fprintd
  Auth-Type: Primary
  Auth:
  	[success=1 default=ignore]	pam_succeed_if.so service in kde:sddm:sddm-greeter:login quiet
  	[success=end default=ignore]	pam_fprintd.so max-tries=1 timeout=15
  ```
  `timeout=15` covers the ~11 s post-sleep blank-reference window (revisit to 10 after WP4); `max-tries=1` avoids the P4 retry-with-finger-down (revisit to 2 only if WP5 data says so).
- Human (H2, root tab open): `sudo install -m644 ~/src/goodix-550c-linux-driver/packaging/goodix550c-fingerprint/usr/share/pam-configs/goodix550c-fingerprint /usr/share/pam-configs/ && sudo pam-auth-update --force --disable fprintd --enable goodix550c-fingerprint` → Opus checks generated `common-auth` jump counts (restore from backup if wrong) → `sudo mv /etc/pam.d/kde /var/backups/goodix550c/kde.local && sudo mv /etc/pam.d/sddm.bak-2026-10-16 /var/backups/goodix550c/` → test TTY password, `sudo -k && sudo true` (finger; and no-touch → password ≤16 s), `pkexec true`, lock screen password + finger; no "already claimed" in `journalctl -u fprintd -b`; rerun B5 (+B6 later).
- Accept: B5 median touch→success ≤ 3 s; no-touch fallback ≤ 16 s; 0 "already claimed"; password works everywhere. Rollback: `sudo cp -a /var/backups/goodix550c/common-auth /etc/pam.d/common-auth && sudo cp -a /var/backups/goodix550c/kde.local /etc/pam.d/kde`.

### WP3 — Stale-TLS open fix (patch 0016) → remove workarounds
- **Patch 0016 `drain-verify-psk-and-retry-tls-once`**, open SSM `goodix53x5-session.c:46-79`:
  1. `GOODIX_OPEN_DRAIN` after claim (≈295): bounded IN reads (≤16 × 30 ms), discard, count `drain_bytes` (mirror `src/goodix550c/usb_probe.py:327-332`).
  2. `GOODIX_OPEN_550C_PSK_HASH` after OTP, before TLS_INIT (≈423): send 0xE4 with exact payload from `src/goodix550c/protocol.py:28-37` (`len=32, off=0, flags=0xbb020001, 0`); constant-time compare reply vs sha256(loaded PSK); mismatch → fail closed "PSK mismatch", never log hashes; keep PSK load/wipe semantics (`session.c:428-436`).
  3. One-shot retry on TLS_PUMP failure/timeout (≈476 / `goodix53x5-tls.c:229-238`): free TLS ctx + rx, re-read PSK, → DRAIN→PING→PSK_HASH→TLS_INIT; second failure fails the open; no USB-reset loop.
  4. Fill `drain_bytes`/`tls_retry` in 0015 lines.
  - Policy tests: 0xE4 not denied and payload byte-identical to probe; retry constant = 1; drain bounded; PSK wiped on all paths; no hash/key in format strings.
- A/B (H3) on `+c2` with workarounds off: `sudo mv /etc/systemd/system/fprintd.service.d/20-goodix550c-unstick.conf /var/backups/goodix550c/ && sudo mv /usr/lib/systemd/system-sleep/goodix550c /var/backups/goodix550c/sleep-hook && sudo systemctl daemon-reload && sudo systemctl restart fprintd` → B4 ×50 + 10 suspend/resume + 10× `sudo systemctl kill -s KILL fprintd` mid-verify, each followed by a verify. If stuck: `sudo systemctl stop fprintd && sudo /usr/local/sbin/goodix550c-unstick && sudo systemctl start fprintd`. Then install `+c3` and repeat.
- Accept: 0 open failures over 100 opens + 10 resumes + 10 kills; `tls_retry>0` only in kill/resume cases and those succeed; PSK-mismatch fail-closed verified once with a temp wrong PSK via scratch drop-in override, then restored. Unstick script + `/opt` probe archived (manual tool only).
- Rollback: reinstall `+c2` and move the drop-in + sleep hook back from `/var/backups/goodix550c/`, daemon-reload, restart.

### WP4 — Capture / finger-present guards + PAM retry interplay
One patch per deb; each judged alone with B1+B2+B3 (~15 min, ~40 touches).
- **0017 `reference-must-be-empty`**: (a) clear-phase stable reading (`scan.c:~436-470`) compared to last confirmed-empty baseline; not adopted if it deviates. (c) upper check beside `goodix_reference_frame_has_signal` (`scan.c:145-154`): empty ≈2350 vs finger 1490–1600 → mean < 2000 (named constant in `private.h`) = finger present → retry within existing 60×250 ms budget. Plus at verify/identify start require a bounded clear window (2 consecutive clear polls, cap 3 s) before ready — fixes P4 for lock screen's `max-tries=3`.
- **0018 `verify-non-contact-gate`**: non-contact > 0.90 in verify → `FP_DEVICE_RETRY_TOO_SHORT` before scoring; skip finger-up wait for that attempt (`auth.c:192-209,407-428`); reuse 0010 pattern (`enroll.c:100-118`).
- **0019 `settle-trim`** (optional, last): settle 300 → 150–200 ms (`scan.c:791-845`) only if first-try rate doesn't drop and median latency improves.
- Signed deltas stay log-only.
- Policy tests: named bounded constants; no blank reference stored; clear-window bounded + suspend refused while polling; threshold still 150.
- Accept vs baseline: B2 no stored reference with mean < 2000, ≤1 "remove finger"/run, ≤2-try success ≥ 90%; B1 first-try ≥ 85% (pre-re-enroll) and not worse than baseline; B3 0 accepts. Rollback: previous `+cN`.

### WP5 — Re-enroll + validation
- Human (H5): `sudo cp -a /var/lib/fprint /var/backups/goodix550c/fprint-pre-reenroll-$(date +%F)` then `fprintd-delete pumpkin && fprintd-enroll -f right-index-finger && fprintd-enroll -f right-thumb` (vary placement, lift fully) then `goodix550c_session.sh all`.
- Accept: all §5 targets; summary into `docs/measurements.md`. Rollback: restore `/var/lib/fprint` from backup + restart fprintd.

### WP6 — Package `goodix550c-fingerprint` (arch: all)
- Files: `packaging/goodix550c-fingerprint/` (DEBIAN control/postinst/prerm/postrm/conffiles), builder extension, `tests/test_packaging.py`.
- Contents: `/usr/lib/systemd/system/fprintd.service.d/50-goodix550c.conf` (FP_DRIVERS_ALLOWLIST, GOODIX550C_ALLOW_VOLATILE_INIT=1, GOODIX550C_ALLOW_MANUAL_FDT_POLL=1, GOODIX550C_PSK_FILE, GOODIX550C_LOG_SUMMARY=1, `UMask=0077`); `/usr/lib/udev/rules.d/60-goodix550c-power.rules` (`ACTION=="add|bind", SUBSYSTEM=="usb", ATTR{idVendor}=="27c6", ATTR{idProduct}=="550c", TEST=="power/control", ATTR{power/control}="on"`); `/etc/tlp.d/50-goodix550c.conf` (conffile); `/usr/share/pam-configs/goodix550c-fingerprint`; no sleep hook if WP3 passed; `/usr/sbin/goodix550c-ctl` (`status` (non-root OK), `recover`, `enroll <finger>`, `install-psk <file>`, `psk-backup <dest>` (umask 077, refuses repo paths), `harden-store`, `rollback-stock`).
- Control: `Depends: libfprint-goodix550c (>= 3), fprintd, libpam-fprintd, udev`; `Recommends: tlp`. postinst: udev reload+trigger, daemon-reload, `pam-auth-update --package` (Default: no → not auto-enabled). prerm remove: `pam-auth-update --package --remove goodix550c-fingerprint`. Never touches PSK or `/etc/pam.d/*` directly.
- Migration (H5): `sudo apt install ~/goodix550c-debs/patched/goodix550c-fingerprint_1.0.0_all.deb && sudo mv /etc/systemd/system/fprintd.service.d/10-goodix550c.conf /var/backups/goodix550c/10-goodix550c.conf.migrated && sudo systemctl daemon-reload && sudo systemctl restart fprintd && sudo goodix550c-ctl harden-store && goodix550c-ctl status`
- Accept: status all green; `systemd-delta | grep fprintd` shows only the /usr/lib drop-in; `dpkg -S` owns every config path; templates 0600; `apt -s install libfprint-2-2=1:1.94.9-1` shows goodix550c-fingerprint would be removed; B1 ×10 + one suspend pass. Rollback: `apt remove` + restore migrated drop-in.

### WP7 — Timeshift + recovery/rollback drills
- Don't exclude `/usr` or `/var/lib/dpkg` (keep lib + dpkg db consistent); `~/goodix550c-debs` lives outside snapshots on purpose.
- `docs/RECOVERY.md` one-liner: `sudo apt install ~/goodix550c-debs/patched/libfprint-2-2_<latest>.deb ~/goodix550c-debs/patched/goodix550c-fingerprint_<latest>_all.deb && sudo apt-mark hold libfprint-2-2 && sudo goodix550c-ctl recover`. `status` flags missing hold / PSK / disabled profile.
- Drills (H6): (1) `sudo goodix550c-ctl rollback-stock` → password logins fine → reinstall via recovery line; (2) Timeshift snapshot → install older `+cN` → restore → reboot → `goodix550c-ctl status`; (3) `sudo apt update && apt list --upgradable` shows libfprint held. Each ends with B1 ×5 passing.

### WP8 — Docs + secret scan
- `README.md` Debian 13 section; `DOCUMENTATION.md` (open fix, guards, PAM design, measurement method); `docs/measurements.md`, `docs/RECOVERY.md`; legacy `~/*.sh` workflows marked superseded by `goodix550c-ctl`.
- `scripts/check_no_secrets.py` + test: derive hex/base64/sha256 forms of `research/secrets/*`, scan `git ls-files` content and `git log -p --all`, flag 64-hex/OTP-like blobs and tracked image/print files. Required before any push. Opus reviews docs against code.

### WP9 — Opt-in distribution (GitHub Releases)
- Gates (owner decisions before publishing): (1) provenance — 256-byte `default_config` is byte-identical to Windows `Wbdi.dll` → preferred patch 0020 loads it from `/etc/goodix550c/default_config.bin` via `goodix550c-ctl install-config <Wbdi.dll>` (users need their Windows install anyway); (2) license review of SIGFM/OpenCV bits.
- Deliverables: GitHub Release with both debs + `SHA256SUMS` + detached signature (apt repo on GitHub Pages = stretch); `docs/DEBIAN-INSTALL.md` (trixie amd64, 27c6:550c, fw 13021 only (others fail closed), PSK extraction from original Windows via `scripts/recover_windows_dpapi_psk.py`, no reflashing, install/install-psk/enable profile/rollback); disclaimers (reverse-engineered, unaffiliated, never locks out the password, not in Debian).
- Opt-in: fails closed without PSK; PAM profile `Default: no`; `status` explains missing steps.
- Accept: clean trixie VM (no sensor) installs, `status` reports "no device / no PSK" cleanly, purge leaves no PAM changes. **Push + release only on user's explicit go-ahead.**

## 5. Verification (after WP6; repeat after WP7)
| Check | Method | Target |
|---|---|---|
| Open reliability | B4 ×2 + 10 suspend/resume + 10 fprintd kills + 3 cold boots | 0 failed opens / ≥120 |
| Genuine first try | B1 ×20 (index + thumb) | ≥ 90% first try, ≥ 97% within 2 |
| Finger present at start | B2 ×10 | 0 finger-on references; ≥ 90% within 2; ≤1 "remove finger"/run |
| Impostor | B3 ≥ 30 total | 0 accepts; report max impostor score vs 150 |
| sudo | B5 ×10 | median ≤ 3 s; no-touch fallback ≤ 16 s |
| polkit | 5× `pkexec true` | finger + password fallback work |
| Lock screen after suspend | B6 ×10 | 10/10 within 2 attempts; 0 "already claimed" |
| Cold boot | 3 reboots → SDDM password → lock → finger unlock | 3/3 |
| Updates | `apt update && apt full-upgrade -s` | libfprint not offered; nothing removes goodix550c-fingerprint |
| Timeshift drill | WP7 #2 | working ≤ 10 min, ≤ 2 commands |
| Rollback drill | WP7 #1 | stock restored, password intact, reinstall passes B1 |
| Secrets | `check_no_secrets.py` | clean before every push |

## 6. Risks
- pam-auth-update jump miscount → Opus checks generated `common-auth`; root tab open; backup in `/var/backups/goodix550c`.
- 0xE4 read alters sensor state unexpectedly → exact probe payload, read-only opcode, fail-closed, A/B with workarounds off.
- Fixed guard thresholds (mean < 2000) misfire on dry/cold fingers → named constants, data first, B1/B2 gates, per-patch debs.
- Debian ships libfprint ≥ 1.94.10 → hold + `libfprint-goodix550c` dependency block the swap; rebase series + WP0b rebuild.
- Instrumentation shifts timing → 0015 integer-only, env-gated, non-exhaustive; re-baseline if needed.
- Public repo leak (PSK/OTP/prints) → WP8 scan mandatory; `research/` stays ignored.
- Redistributing Windows-derived bytes (WP9) → resolve provenance before publishing binaries.
- Human fatigue → ≤ 5 min / ~20-touch sessions; scripts prompt, label, summarize.

## Critical files
- `patches/goodix-550c/driver-series` (+ new 0015–0019 patches)
- `tests/test_goodix550c_patch_policy.py`, `tests/native/`
- `scripts/goodix550c_score_report.py`, `scripts/build_goodix550c_libfprint.sh`, `scripts/fetch_upstream_sources.sh`
- `build/rebuild-vi-mfp/source/driver/drivers/goodix53x5/{goodix53x5-session.c,goodix53x5-scan.c,goodix53x5-auth.c,goodix53x5-tls.c,goodix53x5-private.h,goodix53x5-safety.h}` (reference only — changes go in as patches)
- `src/goodix550c/{usb_probe.py,protocol.py}` (probe behaviour to mirror)
- `scripts/goodix550c_install_system.sh` (model for packaging/ctl)
