# Experiment campaign — making the 550c "very very good"

Goal: maximise **genuine first-try match** and **sudo/lock-screen first-try success**, minimise time-to-result, with **0 impostor accepts** and **0 open failures**, without touching the safety invariants in `CLAUDE.md`.

## Where we are (2026-10-17, `+goodix550c5`, fresh enrollment, 17 stages)
| Metric | Value | Target |
|---|---|---|
| Genuine first try (B1) | 85% | ≥ 95% |
| sudo first try (B5, 3 tries) | 80% | ≥ 95% |
| Finger already down, ≤ 2 tries (B2) | 75–88% | ≥ 95% |
| Lock screen after suspend (B6) | 2/3 first try, 3/3 ≤ 2 | 10/10 first try |
| Impostor accepts | 0 (max score 3 vs 150) | 0 |
| Open failures | 0 / 100+ | 0 |
| Median score (genuine) | ~4,500 | — |
Remaining genuine misses: good reference (~2260), 140–200 keypoints, but best_score 0–40 → **partial overlap / placement** between probe and templates, not capture faults.

## Organisation
- **Opus planner** (main session): picks the next hypothesis from the backlog, writes a 1-page experiment card (hypothesis, variable, values, expected effect on which metric, risk), reviews results, decides keep/revert, updates this file.
- **Sonnet workers** (parallel, ≤ 3): implement a variant as a patch (or env-tunable, see below), build into `build/exp-<id>`, produce a versioned deb, write policy tests. Never sudo, never touch the device.
- **Human**: one install line + one guided session per round (≤ 5 min). Batch: a round may A/B two debs back-to-back.

## Make variables tunable without rebuilding (do this first)
Patch 0020 (`goodix550c-runtime-tunables`): read a small set of **bounded** overrides from env (`GOODIX550C_TUNE_<NAME>=<int>`, clamped to safe ranges, logged once at open as integers) so experiments only need a drop-in edit + `systemctl restart fprintd`, not a new deb. Never make safety constants tunable (threshold 150, deny list, firmware gate, PSK handling, wait upper bounds).

## Variable backlog (current value → range to explore)
| Variable | Where | Now | Explore | Expected effect |
|---|---|---|---|---|
| Finger-down settle | `GOODIX_MANUAL_FDT_DOWN_SETTLE_MS` (scan.c) | 300 ms | 120–400 | latency vs. partial-contact captures |
| Down confirmations / poll delay | `GOODIX_MANUAL_FDT_CONFIRMATIONS` / `_POLL_DELAY_MS` | 2 / 100 ms | 1–3 / 50–120 | faster detection vs. false triggers |
| Touch direction threshold | `GOODIX_FDT_TOUCH_MIN_NEG` / `_LIFT_MIN_POS` | 20 / 20 | 12–35 | touches measured −42…−49, lifts +45…+50 |
| Reference "finger present" cut | `GOODIX_REF_FINGER_MEAN_MAX` | 2000 | 1500–2150 | empty ≈2247–2267, finger-on 200–1232 |
| Clear window | `GOODIX_CLEAR_CONSECUTIVE_POLLS` / `_WINDOW_MAX_MS` | 2 / 3000 | 1–3 / 1500–4000 | readiness latency |
| No-match finger-up hold | `GOODIX_RESULT_FINGER_UP_WAIT_MS` | 1500 | 800–2500 | retry quality vs. latency |
| Non-contact gate | `GOODIX_VERIFY_NO_CONTACT_FRACTION` | 0.90 | 0.80–0.95 | too-short detection |
| Min keypoints | `GOODIX_MIN_CAPTURE_KEYPOINTS` | 20 | 15–40 | reject junk captures earlier |
| Enroll samples | `GOODIX_ENROLL_SAMPLES` | 17 | 12–30 | coverage of the finger → fewer partial-overlap misses |
| Enroll coaching | TUI / enroll flow | none | guided placements (centre, up, down, left, right, tip) | better template coverage |
| Templates per finger | enrollment strategy | 1 print | re-enroll same finger twice as separate slots | identify across more coverage |
| Image pre-processing before SIGFM | match.c | as-is | contrast normalisation / denoise (read-only math) | more stable keypoints |
| PAM tries / timeout | `goodix550c-ctl pam set` | 3 / 15 s | 2–5 / 8–20 | UX only |

Never in scope: lowering threshold 150, reflashing, writing PSK, disabling the firmware gate, unbounded waits.

## Protocol per round
1. Card written (hypothesis + single variable change; 2 values max per round).
2. Install variant (one line). Run `goodix550c_session.sh test <exp-id>` (B1 20, B2 8, B3 8, B4, B5 10) — or a shorter targeted block if the card says so.
3. Compare with the last accepted JSON in `~/goodix550c-debs/measurements/` using `goodix550c_score_report.py --json`.
4. **Keep** only if: target metric improves by ≥ 1 run out of 20 (or ≥ 5 pts) AND no other metric regresses beyond noise AND impostor accepts = 0 AND open failures = 0. Otherwise revert.
5. Log the result row in the table below; commit the patch (kept) or a note (reverted).

Small samples are noisy (20 runs → ±10 pts). Re-run a promising change once before keeping it.

## Results log
| Round | Variable | Values | B1 first-try | B5 first-try | B2 ≤2 | Impostor | Decision |
|---|---|---|---|---|---|---|---|
| baseline c2 | — | — | 75% | 80% | 50% | 0 | — |
| c4 (0016–0018) | guards | — | 85% | 70% | 88% | 0 | kept |
| c4 + re-enroll | enrollment | 17 stages fresh | — | 40%* | 75% | 0 | kept (*too-short; fixed by 0019) |
| c5 (0019) | touch direction | ±20 | 85% | 80% | — | 0 | kept |
