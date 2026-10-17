# Measurements (Debian reliability work)

Status: the protocol and the report tool exist; **no numbers have been collected yet**.
Results below were measured with
`research/baseline/<date>-<build>.json` (git-ignored; only the non-identifying
summary below is committed). Do not paste journal excerpts, finger names beyond
"index"/"thumb", scores tied to a person, or anything from the PSK, OTP, frames or
templates.

## Method

Each build is judged with the same protocol, run by
`scripts/goodix550c_session.sh` as the logged-in user (it needs no sudo except B5's
own `sudo` prompt). The driver must log per-attempt summaries, which the
`goodix550c-fingerprint` drop-in turns on with `GOODIX550C_LOG_SUMMARY=1`. Those
lines are written with `g_message`, so no debug logging is needed; debug logging
switches the matcher to exhaustive scoring and changes the timing being measured.

| Block | Command | What the human does | Count |
|---|---|---|---|
| B1 genuine | `goodix550c_session.sh b1` | Lift the finger fully, press Enter, touch the enrolled finger after the prompt | 20 |
| B2 present-at-start | `... b2` | Rest the finger on the pad before the verify starts and keep it there | 10 |
| B3 impostor | `... b3` | Use a finger that is not enrolled (default `left-index`) | 10 |
| B4 opens | `... b4` | Nothing: 50 `timeout -s INT 5 fprintd-verify` runs with no touch (about 4 min) | 50 |
| B5 sudo | `... b5` | `sudo -k && sudo true`; touch, or type the password | 10 |
| B6 suspend | `... b6` | Suspend, wake, unlock the lock screen with the finger; enter `pass` or `fail` (within 2 tries) | 5 |

`all` runs B1 to B6 in order and saves a report. Environment: `FINGER`
(default `right-index`), `IMPOSTOR_FINGER`, `VERIFY_TIMEOUT` (30 s), `SINCE`.
The script ships B6 as 5 rounds; the PLAN's acceptance table asks for 10, so run
`b6` twice (or edit the loop) when validating a final build.

### Journal markers

Each touch is bracketed by `logger -t goodix550c-session` lines:

```
label=<genuine|impostor|present-at-start|opens|sudo|suspend> finger=<name> run=<id>
end run=<id> [result=pass|fail]
```

Everything logged between a marker and the next belongs to that label and run.

### Driver summary lines (fprintd journal)

One per open and one per attempt, integers only:

```
goodix550c open: result=<ok|fail> ms=N phase=<claim|ping|fw|otp|psk|tls|done> drain_bytes=N tls_retry=N
goodix550c attempt: action=<verify|identify> ready_to_down_ms=N down_polls=N settle_ms=N
  ref_mean=N ref_retries=N noncontact_x1000=N keypoints=N best_score=N early_exit=<0|1>
  threshold=N result=<match|no-match|retry:<reason>> dmax_pos=N dmax_neg=N
  [clear_ms=N clear_dev_polls=N clear_rejects=N up_wait_ms=N up_first=N]   (patch 0017 and later)
```

`result` retry reasons: `remove-finger`, `data-invalid`, `finger-present` (0017),
`too-short` (0018), `error`. `best_score` is only meaningful when the matcher ran
(`match`/`no-match`); `early_exit=1` means it stopped at the first sample that
passed. `dmax_pos`/`dmax_neg` are log-only. `drain_bytes` and `tls_retry` are
filled from patch 0016 (they are 0 in a 0015-only build). The threshold is 150 and is
never lowered.

### Report tool

```
.venv/bin/python scripts/goodix550c_score_report.py --log LOGFILE [--json]
```

`goodix550c_session.sh report [name]` extracts the right journal slice
(`journalctl --since <first block> _SYSTEMD_UNIT=fprintd.service + SYSLOG_IDENTIFIER=goodix550c-session`),
prints the text report and writes `research/baseline/<date>-<name>.json`.
Per label it gives: runs and attempts, first-try match rate, match-within-2 rate,
retry-reason histogram, score min/median/max (only where the matcher ran), opens and
open failures by phase, median open ms, manual pass/fail counts, and for `impostor`
the maximum score and the number of accepts. `--json` output is for diffing builds.
Old logs without summary lines fall back to the `Verify/Identify best SIGFM score`
lines.

## Targets (PLAN section 5)

| Check | Method | Target |
|---|---|---|
| Open reliability | B4 x2 + 10 suspend/resume + 10 fprintd kills + 3 cold boots | 0 failed opens out of at least 120 |
| Genuine first try | B1 x20 (index + thumb) | at least 90% first try, at least 97% within 2 |
| Finger present at start | B2 x10 | 0 references taken with a finger on; at least 90% within 2; at most 1 "remove finger" per run |
| Impostor | B3, at least 30 total | 0 accepts; report max impostor score vs 150 |
| sudo | B5 x10 | median at most 3 s; no-touch fallback at most 16 s |
| polkit | 5x `pkexec true` | finger and password fallback both work |
| Lock screen after suspend | B6 x10 | 10/10 within 2 attempts; 0 "already claimed" |
| Cold boot | 3 reboots, SDDM password, lock, finger unlock | 3/3 |
| Updates | `apt update && apt full-upgrade -s` | libfprint not offered; nothing removes goodix550c-fingerprint |
| Timeshift drill | RECOVERY.md one-liner | working within 10 min, at most 2 commands |
| Rollback drill | `goodix550c-ctl rollback-stock` | stock restored, password intact, reinstall passes B1 |
| Secrets | `scripts/check_no_secrets.py` | clean before every push |

Per-patch acceptance used while iterating (PLAN WP4), judged against the baseline
with B1+B2+B3: B2 stores no reference with mean below the finger threshold, at most
1 "remove finger" per run, at least 90% success within 2; B1 first-try at least 85%
before re-enrolling and not worse than baseline; B3 0 accepts.

## Builds

| Build | Package | Content (patches) | Role |
|---|---|---|---|
| c2 | `1.94.10+goodix550c2` | through 0015 (summary logging, no behaviour change) | baseline |
| c3 | `1.94.10+goodix550c3` | adds 0016 (drain, PSK-hash check, one TLS retry) | stale-TLS fix |
| c4 | `1.94.10+goodix550c4` | TODO: confirm patch set (0017 and/or 0018) | capture guards |
| post-re-enroll | TODO: final build | all patches; prints re-enrolled | final validation |

## Results (2026-10-17, one person, one Yoga 9 14IAP7)

`c3` (0016 alone) was not measured separately; the stale-TLS fix was validated as part of `c4`
with the old ExecStartPre/sleep-hook workarounds removed. Small samples: 20 runs ≈ ±10 points.

| Build | Prints | B1 genuine first try | B2 finger-already-down ≤2 tries | B3 impostor accepts (max score) | B5 sudo first try | Opens failed |
|---|---|---|---|---|---|---|
| c2 baseline (0015 logging only, workarounds on) | old | 75% (≤2: 80%) | 50% | 0 / 8 (2) | 80% (old PAM, 3 tries) | 0 / 59 |
| c4 (0015–0018, workarounds off) | old | 85% | 88% | 0 / 8 (3) | 70% (≤2: 80%) | 0 / 58 |
| c4 | re-enrolled (17 stages) | — | 75% | 0 / 8 (2) | 40% (≤2: 80%)* | 0 / 56 |
| c5 (+0019 touch direction) | re-enrolled | 85% | — | — | **80%** | 0 / 30 |

\* the `retry:too-short` misses that 0019 targets: every one had a lift-direction trigger
(`dmax_pos` +45…+50, `dmax_neg` 0) while every real touch had `dmax_neg` −42…−49.

Other observations:
- Reference means: empty pad 2247–2267; finger-on-pad references 200–1232 → `GOODIX_REF_FINGER_MEAN_MAX` 2000 keeps ≥ 247 margin on the empty side.
- Median genuine score rose from ~640 (old prints) to ~4,500 (re-enrolled with c4/c5).
- Lock screen after suspend (c4, re-enrolled): 2 / 3 first try, 3 / 3 within 2 tries, 0 "Device was already claimed" after the PAM profile change.
- Remaining genuine misses have a good reference, 140–200 keypoints and best score 0–40: partial overlap between probe and templates, not capture faults — the target of the tuning campaign in [EXPERIMENTS.md](EXPERIMENTS.md).
- Secret scan (`check_no_secrets.py`, full mode with the real PSK, history + release deb): clean.
- Not yet run: Timeshift restore drill, 3 cold boots, polkit ×5, 30+ impostor touches.

## Notes for the next revision

- `timeout=15` in the PAM profile covers the roughly 11 s post-sleep blank-reference
  window; revisit to 10 after the capture guards are measured.
- `max-tries=1` avoids retrying with the finger still down; revisit to 2 only if the
  B1/B5 data say so.
- `GOODIX_REF_FINGER_MEAN_MAX` ships as 2000 (empty pad about 2350, finger 1490-1600
  in earlier observations). The plan intended to derive it from the baseline
  `ref_mean` split of B1 vs B2 (midpoint, at least 150 margin each side). TODO: do
  that from the c2 data and record the chosen value.
