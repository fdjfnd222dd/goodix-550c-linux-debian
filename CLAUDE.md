# CLAUDE.md — working on this repo

Reverse-engineered, fail-closed Linux driver + Debian packaging for the **Goodix 27c6:550c** fingerprint sensor (Lenovo Yoga 9 14IAP7, firmware `GF5288_GM168SEC_APP_13021`). Read `PLAN.md` (what was built and why), `docs/EXPERIMENTS.md` (the tuning campaign), `docs/measurements.md` and `DOCUMENTATION.md` (engineering record) before changing anything.

## Hard rules
1. **Safety invariants are untouchable**: persistent sensor commands (A4/E0/E2/F0/F4) stay denied; never reflash, re-provision or write the sensor PSK; firmware gate stays 13021-only unless a new firmware is validated end-to-end; self-heal block stays `#if 0`; PSK only from `/etc/goodix550c/goodix550c.psk`, wiped after use; never log keys, OTP, frames or templates; every wait bounded; blank or finger-covered references never stored; PAM keeps `default=ignore` (password always works).
2. **Never lower the match threshold** (`GOODIX_SIGFM_BEST_MIN 150`) to buy a better acceptance rate. Impostor accepts must stay 0.
3. **Driver changes are patches**: `build/` is generated and git-ignored. Every change = a new `patches/goodix-550c/00NN-*.patch` appended to `patches/goodix-550c/driver-series` + assertions in `tests/test_goodix550c_patch_policy.py`. Direct edits under `build/` are lost.
4. **Versioned debs only**: `scripts/build_goodix550c_debs.sh` refuses to overwrite; artifacts live in `~/goodix550c-debs/patched/` (outside Timeshift). Stock debs for rollback are in `~/goodix550c-debs/stock/`.
5. **The human runs every sudo command**, pasted as ONE physical line into Konsole (no `!` prefix, no heredocs, no `\` continuations). Agents never run sudo and never touch the device except read-only `fprintd-list`/journal reads, or measurement sessions the human starts.
6. **Before any `git push`**: `python3 scripts/check_no_secrets.py --secret-hash <sensor psk-hash>` must print CLEAN (full mode needs root: `sudo python3 -I scripts/check_no_secrets.py --secret /etc/goodix550c/goodix550c.psk --deb <debs>`). `research/` is git-ignored and holds secrets — never add it.
7. Keep instructions to the human short and literal ("touch when it says TOUCH NOW"). Long prompts confuse; measurement scripts must auto-advance and show one instruction at a time.

## Build / test / install
```
scripts/fetch_upstream_sources.sh --offline
scripts/build_goodix550c_libfprint.sh --allow-volatile-init --allow-manual-fdt-poll --stage-dir build/<name>   # runs native tests
.venv/bin/python -m pytest -q          # one known env failure: test_dpapi_recovery (root-only research/secrets)
build/tui-venv/bin/python -m pytest tests/tui tests/test_ctl.py -q
scripts/build_goodix550c_debs.sh --so build/<name>/builddir/libfprint/libfprint-2.so.2.0.0 --out ~/goodix550c-debs/patched   # lib deb, auto +goodix550cN
scripts/build_goodix550c_debs.sh --pkg goodix550c-fingerprint --out ~/goodix550c-debs/patched                              # config/ctl/TUI deb
```
Human install (one line): `sudo apt install --allow-change-held-packages ~/goodix550c-debs/patched/libfprint-2-2_1.94.10+goodix550cN_amd64.deb && sudo apt-mark hold libfprint-2-2`
Rollback: install the previous `+goodix550cN`, or `sudo goodix550c-ctl rollback-stock`.

## Measure
- Driver writes one `goodix550c open:` and one `goodix550c attempt:` journal line per open/attempt (`GOODIX550C_LOG_SUMMARY=1`, set by the package drop-in). Fields: ref_mean, ref_retries, noncontact_x1000, keypoints, best_score, result, dmax_pos/dmax_neg, clear_*, up_wait_ms, lift_rebase, drain_bytes, tls_retry.
- `scripts/goodix550c_session.sh b1|b2|b3|b4|b5|b6|test|final|rest|quick|qsudo|report <name>` — guided blocks (genuine ×20, finger-already-down ×8, impostor ×8, hands-off opens ×30, sudo ×10, suspend ×3; `quick` = genuine ×12 + impostor ×4 in ~90 s, `qsudo` = sudo ×6). JSON lands in `~/goodix550c-debs/measurements/`; the report ends with a `--compare` table against `BASELINE=<json>`.
- Runtime tunables (patch 0020): `GOODIX550C_TUNE_<NAME>=<int>` in a `60-*.conf` fprintd drop-in + `systemctl restart fprintd`; effective values logged as `goodix550c tune:` at open. Attempt lines also carry `down_to_result_ms`, `capture_ms`, `match_ms`, `templates_scored`, `best_idx`, `second_best`.
- `scripts/goodix550c_enroll_coached.sh` (`REPLACE=1` to replace a slot) — one placement prompt per stage. Back up `/var/lib/fprint` first.
- `scripts/goodix550c_score_report.py --log <journal export> [--json]` — per-label rates, retry reasons, score stats.
- The user is in `systemd-journal`, so `journalctl -u fprintd` is readable without sudo.

## Layout
- `patches/goodix-550c/` driver series (0015 logging, 0016 stale-TLS fix, 0017/0018 finger-present + non-contact guards, 0019 touch-direction finger-down, 0020 runtime tunables + timing fields, 0021 enroll lift prompt + 20 s finger-up bound)
- `packaging/libfprint-2-2/`, `packaging/goodix550c-fingerprint/` (drop-in, udev rule, TLP + apt-pin conffiles, PAM profile, `goodix550c-ctl`, `finger` wrappers)
- `tui/goodix550c_tui/` the `finger` Textual TUI (must run on Debian's python3-textual 2.1)
- `scripts/` build, session, report, secret scan; `tests/` pytest + `tests/native/` C tests
- `src/goodix550c/` read-only Python USB probe (manual diagnostics only)
