# Experiment campaign — making the 550c "very very good"

Goal: maximise **genuine first-try match** and **sudo/lock-screen first-try success**, minimise time-to-result, with **0 impostor accepts** and **0 open failures**, without touching the safety invariants in `CLAUDE.md`.

## Where we are (2026-10-17, `+goodix550c5`, fresh enrollment, 16 samples)
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

## Planner findings (2026-10-17, from c4-reenrolled + c5 logs)
- SIGFM score ≈ C(C(M,2),2) for M geometrically consistent matches: 150 ≈ 6–7 matches, impostor max 3 ≈ 3 matches, median genuine ≈ 14.
- `GOODIX_ENROLL_SAMPLES` is **16** in code (`private.h:74`), not 17.
- Genuine misses (17/65): 7 score ≤ 3 (finger region never enrolled → coverage problem), 6 score 75–148 (near misses). Retries miss 43% vs first tries 18%: users re-place the same way.
- Capture timing is NOT the cause: noncontact 0 on every miss, ready_to_down and dmax_neg uncorrelated with score, lift_rebase attempts 6/6 matched.
- Time after the finger lands ≈ 0.6 s: finger-down detection 140–260 ms (2 polls × 119.5 ms) + settle 300 ms + capture/match ~100 ms. Matching is not the bottleneck. Before "ready": open ~600 ms + clear ~450 ms + reference ~350 ms.
- Matcher constants (ratio 0.85, length/angle 5%, SIFT/CLAHE) stay fixed: loosening them is equivalent to lowering the threshold, and SIFT changes invalidate stored templates. Keypoint positions are truncated to `Point2i` (precision loss) → candidate log-only `shadow_score` study, never decision-affecting without a separate review.

## Experiment cards (ranked)
1. **Second enrollment slot for the same finger** (right index enrolled again as `right-middle-finger`, coached placements: centre, tip, left, right, base). Metric: B1 first-try and count of misses ≤ 3; B3 impostor ×≥8 (now 3 slots × 16 templates). No build.
2. **SETTLE_MS 300 → 150** (tunable). Metric: down_to_result −150 ms, miss rate and noncontact unchanged.
3. **ENROLL_SAMPLES 16 → 24** (one coached slot; re-enroll). Compare with card 1.
4. **POLL_DELAY_MS 100 → 60**. Metric: time-to-ready and detection latency.
5. **Shadow score** (log-only) — only if impostor shadow max ≤ 15.
6. **UP_WAIT_MS 1500 → 800**. Metric: sudo retry latency.
UX: on retry say "shift your finger slightly" (retries currently miss 43%).

## Results log
| Round | Variable | Values | B1 first-try | B5 first-try | B2 ≤2 | Impostor | Decision |
|---|---|---|---|---|---|---|---|
| baseline c2 | — | — | 75% | 80% | 50% | 0 | — |
| c4 (0016–0018) | guards | — | 85% | 70% | 88% | 0 | kept |
| c4 + re-enroll | enrollment | 17 stages fresh | — | 40%* | 75% | 0 | kept (*too-short; fixed by 0019) |
| c5 (0019) | touch direction | ±20 | 85% | 80% | — | 0 | kept |
| c6 (0020, defaults) | — (timing instrumented) | — | 100% (12) | — | — | 0 (max 0) | kept. down→result 411 ms = settle 300 + capture ~100 + match 5; ready→match 1267 ms incl. reaction |
| r1 | SETTLE_MS / POLL_DELAY_MS | 300→150 / 100→60 | 92% (12; 1 miss score 6 = coverage, noncontact 0) | — | — | 0 (max 1) | provisional keep: down→result 411→258 ms, detection −80 ms; scores median 531→6598 |
| r2 | ENROLL_SAMPLES + wide coaching | 16→24, rolls/tips | 92% (12; miss 87) | — | — | 0 (max 9) | revert coaching: 11/12 matches hit one sample (#18 "roll RIGHT"); median score 765 vs 6598. Natural touch ≠ coached centre. Next: 24 natural |
