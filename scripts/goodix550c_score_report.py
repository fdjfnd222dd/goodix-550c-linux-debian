#!/usr/bin/env python3
"""Summarise SIGFM match scores from a guarded fprintd session log.

fprintd reports only match or no-match, which is not enough to choose a
threshold: it hides how close a genuine attempt came to failing and how close an
impostor came to passing. The driver logs the score for every stored sample, so
this reads them back and reports the two distributions side by side.

Presentations are labelled from a plain-text file the operator writes as they
go, one line per attempt, so an attempt can be attributed without the log ever
containing anything about whose finger it was:

    genuine   right index, flat
    genuine   right index, rolled left
    impostor  left thumb

Attempts and labels are paired in order. Unlabelled attempts are reported
separately rather than guessed at.

Session mode.  scripts/goodix550c_session.sh brackets every touch with journal
markers written by `logger -t goodix550c-session`:

    label=<genuine|impostor|present-at-start|opens|sudo|suspend> finger=<name> run=<id> [t_ms=<epoch ms>]
    phase=ready run=<id> t_ms=<epoch ms>                 (fprintd-verify printed "Verify started")
    phase=result run=<id> result=<r> t_ms=<epoch ms>     (a verify result line arrived)
    end run=<id>

Everything between a marker and the next marker belongs to that label.  Each
marker is one run; within it the driver's `goodix550c open:` and
`goodix550c attempt:` summary lines (GOODIX550C_LOG_SUMMARY=1) give the
per-attempt facts.  Without summary lines the older score lines are used.
`--json` prints the per-label results as JSON, for build-to-build diffs.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

BEST_RE = re.compile(r"(?:Verify|Identify) best SIGFM score:\s*(\d+)\s*\(best_min:\s*(\d+)\)")
SAMPLE_RE = re.compile(
    r"(?:verify: sample (?P<vsample>\d+)|identify: gallery\[(?P<gallery>\d+)\] sample (?P<isample>\d+))"
    r" sigfm_score (?P<score>\d+)"
)
OPEN_RE = re.compile(r"goodix550c open: (?P<fields>.*)$")
ATTEMPT_RE = re.compile(r"goodix550c attempt: (?P<fields>.*)$")
SESSION_TAG_RE = re.compile(r"goodix550c-session(?:\[\d+\])?:\s*(?P<msg>.*)$")
MARKER_RE = re.compile(
    r"^label=(?P<label>[\w-]+)(?:\s+finger=(?P<finger>\S+))?(?:\s+run=(?P<run>\S+))?"
)
END_RE = re.compile(r"^end(?:\s+run=(?P<run>\S+))?(?:\s+result=(?P<result>\w+))?\s*$")
PHASE_RE = re.compile(r"^phase=(?P<phase>\w+)\b")
FIELD_RE = re.compile(r"(\w+)=(\S+)")


class Attempt:
    def __init__(self, best: int, threshold: int, samples: list[int]) -> None:
        self.best = best
        self.threshold = threshold
        self.samples = samples

    @property
    def accepted(self) -> bool:
        return self.best >= self.threshold


def parse_log(text: str) -> list[Attempt]:
    """Collect one Attempt per reported score, with the samples preceding it."""
    attempts: list[Attempt] = []
    pending: list[int] = []

    for line in text.splitlines():
        sample = SAMPLE_RE.search(line)
        if sample is not None:
            pending.append(int(sample.group("score")))
            continue

        best = BEST_RE.search(line)
        if best is not None:
            attempts.append(Attempt(int(best.group(1)), int(best.group(2)), pending))
            pending = []

    return attempts


# ---------------------------------------------------------------------------
# Session mode
# ---------------------------------------------------------------------------

def _fields(text: str) -> dict:
    out: dict = {}
    for key, value in FIELD_RE.findall(text):
        out[key] = int(value) if re.fullmatch(r"-?\d+", value) else value
    return out


class Section:
    """Everything logged under one session marker (one run of one label)."""

    def __init__(self, label: str, finger: str = "", run: str = "") -> None:
        self.label = label
        self.finger = finger
        self.run = run
        self.opens: list[dict] = []
        self.attempts: list[dict] = []
        self.legacy_scores: list[int] = []
        self.legacy_threshold = 0
        self.manual_result = ""
        self.start_ms: int | None = None
        self.ready_ms: int | None = None
        self.results: list[tuple[int, str]] = []   # (t_ms, result) in arrival order


def parse_sections(text: str) -> tuple[list[Section], bool]:
    """Split a journal excerpt on session markers; returns (sections, saw_markers)."""
    sections: list[Section] = []
    current = Section("unlabelled")
    saw_markers = False

    def close() -> None:
        nonlocal current
        if current.opens or current.attempts or current.legacy_scores or current.label != "unlabelled":
            sections.append(current)

    for line in text.splitlines():
        tag = SESSION_TAG_RE.search(line)
        msg = tag.group("msg").strip() if tag else line.strip()
        marker = MARKER_RE.match(msg) if (tag or msg.startswith("label=")) else None
        if marker is not None:
            saw_markers = True
            close()
            current = Section(marker.group("label").lower(), marker.group("finger") or "",
                              marker.group("run") or "")
            t = _fields(msg).get("t_ms")
            current.start_ms = t if isinstance(t, int) else None
            continue
        phase = PHASE_RE.match(msg) if tag is not None else None
        if phase is not None:
            f = _fields(msg)
            t = f.get("t_ms")
            if isinstance(t, int):
                if phase.group("phase") == "ready" and current.ready_ms is None:
                    current.ready_ms = t
                elif phase.group("phase") == "result":
                    current.results.append((t, str(f.get("result", "")).removeprefix("verify-")))
            continue
        end = END_RE.match(msg) if tag is not None else None
        if end is not None:
            saw_markers = True
            current.manual_result = (end.group("result") or "").lower()
            close()
            current = Section("unlabelled")
            continue

        m = OPEN_RE.search(line)
        if m:
            current.opens.append(_fields(m.group("fields")))
            continue
        m = ATTEMPT_RE.search(line)
        if m:
            current.attempts.append(_fields(m.group("fields")))
            continue
        if SAMPLE_RE.search(line):
            continue
        m = BEST_RE.search(line)
        if m:
            current.legacy_scores.append(int(m.group(1)))
            current.legacy_threshold = int(m.group(2))

    close()
    return sections, saw_markers


def _attempts_of(section: Section) -> list[dict]:
    if section.attempts:
        return section.attempts
    # No summary lines (older driver build): reconstruct what the score lines allow.
    return [
        {
            "best_score": score,
            "threshold": section.legacy_threshold,
            "result": "match" if score >= section.legacy_threshold else "no-match",
        }
        for score in section.legacy_scores
    ]


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def summarise_label(label: str, sections: list[Section]) -> dict:
    runs = len(sections)
    attempts_per_run = [_attempts_of(sec) for sec in sections]
    all_attempts = [a for run in attempts_per_run for a in run]
    scored_runs = [run for run in attempts_per_run if run]

    first_try = sum(1 for run in scored_runs if run[0].get("result") == "match")
    within_two = sum(1 for run in scored_runs
                     if any(a.get("result") == "match" for a in run[:2]))

    reasons = Counter(
        str(a.get("result", ""))[len("retry:"):]
        for a in all_attempts
        if str(a.get("result", "")).startswith("retry:")
    )

    # Scores only count where the matcher actually ran.
    scores = [int(a["best_score"]) for a in all_attempts
              if a.get("result") in ("match", "no-match") and "best_score" in a]
    opens = [o for sec in sections for o in sec.opens]
    open_failures = Counter(str(o.get("phase", "unknown")) for o in opens
                            if o.get("result") == "fail")
    open_ms = [int(o["ms"]) for o in opens if "ms" in o]

    out: dict = {
        "n": runs,
        "attempts": len(all_attempts),
        "runs_with_attempts": len(scored_runs),
        "first_try_match_rate": _rate(first_try, len(scored_runs)),
        "match_within_2_rate": _rate(within_two, len(scored_runs)),
        "retry_reasons": dict(sorted(reasons.items())),
        # Absent in logs from builds before patch 0019; counts as zero there.
        "lift_rebaselines": sum(int(a.get("lift_rebase", 0)) for a in all_attempts
                                if isinstance(a.get("lift_rebase", 0), int)),
        "score_min": min(scores) if scores else None,
        "score_median": int(statistics.median(scores)) if scores else None,
        "score_max": max(scores) if scores else None,
        "opens": len(opens),
        "open_failures_by_phase": dict(sorted(open_failures.items())),
        "median_open_ms": int(statistics.median(open_ms)) if open_ms else None,
        "near_misses": sum(1 for a in all_attempts
                           if a.get("result") == "no-match"
                           and isinstance(a.get("best_score"), int)
                           and 100 <= a["best_score"] < 150),
        **_timing(sections, all_attempts),
        "fingers": sorted({sec.finger for sec in sections if sec.finger}),
    }
    manual = [sec.manual_result for sec in sections if sec.manual_result]
    if manual:
        out["manual_results"] = {"pass": manual.count("pass"), "fail": manual.count("fail")}
    if label == "impostor":
        out["impostor_max_score"] = max(scores) if scores else None
        if scores and any(a.get("threshold") for a in all_attempts):
            out["impostor_accepts"] = sum(1 for a in all_attempts if a.get("result") == "match")
    return out


def _p90(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def _median(values: list[int]) -> int | None:
    return int(statistics.median(values)) if values else None


def _timing(sections: list[Section], all_attempts: list[dict]) -> dict:
    """Time-to-result metrics; every field is None when the log predates the markers."""
    ready_to_result: list[int] = []
    totals: list[int] = []
    for sec in sections:
        if not sec.results:
            continue
        if sec.start_ms is not None:
            totals.append(sec.results[-1][0] - sec.start_ms)
        matched = [t for t, r in sec.results if r == "match"]
        if matched and sec.ready_ms is not None:
            ready_to_result.append(matched[0] - sec.ready_ms)
    down = [int(a["down_to_result_ms"]) for a in all_attempts
            if isinstance(a.get("down_to_result_ms"), int)]
    return {
        "ready_to_result_median_ms": _median(ready_to_result),
        "ready_to_result_p90_ms": _p90(ready_to_result),
        "ready_to_result_n": len(ready_to_result),
        "run_total_median_ms": _median(totals),
        "down_to_result_median_ms": _median(down),
        "down_to_result_p90_ms": _p90(down),
        "down_to_result_n": len(down),
    }


def build_report(sections: list[Section]) -> dict:
    by_label: dict[str, list[Section]] = {}
    for sec in sections:
        by_label.setdefault(sec.label, []).append(sec)
    thresholds = [int(a["threshold"]) for sec in sections for a in sec.attempts if a.get("threshold")]
    thresholds += [sec.legacy_threshold for sec in sections if sec.legacy_threshold]
    return {
        "threshold": thresholds[0] if thresholds else None,
        "labels": {label: summarise_label(label, secs) for label, secs in sorted(by_label.items())},
    }


def render_report(report: dict) -> str:
    def pct(value) -> str:
        return "n/a" if value is None else f"{value * 100:.0f}%"

    lines = [f"threshold {report['threshold']}", ""]
    for label, info in report["labels"].items():
        lines.append(f"{label}: {info['n']} runs, {info['attempts']} attempts")
        if info["runs_with_attempts"]:
            lines.append(f"  first-try match {pct(info['first_try_match_rate'])}   "
                         f"match within 2 {pct(info['match_within_2_rate'])}")
        if info["retry_reasons"]:
            lines.append("  retry reasons: " + ", ".join(
                f"{k}={v}" for k, v in info["retry_reasons"].items()))
        if info.get("lift_rebaselines"):
            lines.append(f"  lift re-baselines: {info['lift_rebaselines']}")
        if info["score_min"] is not None:
            lines.append(f"  score min {info['score_min']}  median {info['score_median']}  "
                         f"max {info['score_max']}")
        if label == "impostor" and info.get("impostor_max_score") is not None:
            lines.append(f"  impostor max score {info['impostor_max_score']} "
                         f"(accepts: {info.get('impostor_accepts', 'n/a')})")
        if info.get("near_misses"):
            lines.append(f"  near misses (no-match, score 100-149): {info['near_misses']}")
        if info.get("ready_to_result_median_ms") is not None:
            lines.append(f"  ready->match ms: median {info['ready_to_result_median_ms']}  "
                         f"p90 {info['ready_to_result_p90_ms']}  (n={info['ready_to_result_n']})")
        if info.get("run_total_median_ms") is not None:
            lines.append(f"  verify run total ms: median {info['run_total_median_ms']}")
        if info.get("down_to_result_median_ms") is not None:
            lines.append(f"  down->result ms: median {info['down_to_result_median_ms']}  "
                         f"p90 {info['down_to_result_p90_ms']}  (n={info['down_to_result_n']})")
        if info.get("manual_results"):
            lines.append(f"  manual: {info['manual_results']['pass']} pass, "
                         f"{info['manual_results']['fail']} fail")
        if info["opens"]:
            fails = sum(info["open_failures_by_phase"].values())
            lines.append(f"  opens {info['opens']}, failures {fails}"
                         + (" (" + ", ".join(f"{k}={v}" for k, v in
                                             info["open_failures_by_phase"].items()) + ")"
                            if fails else "")
                         + f", median {info['median_open_ms']} ms")
        lines.append("")
    return "\n".join(lines)


COMPARE_ROWS = [
    ("first_try %", "first_try_match_rate", "pct", True),
    ("within_2 %", "match_within_2_rate", "pct", True),
    ("accepts", "impostor_accepts", "int", False),
    ("max score", "impostor_max_score", "int", False),
    ("near misses", "near_misses", "int", False),
    ("ready->match med ms", "ready_to_result_median_ms", "int", False),
    ("ready->match p90 ms", "ready_to_result_p90_ms", "int", False),
    ("run total med ms", "run_total_median_ms", "int", False),
    ("down->result med ms", "down_to_result_median_ms", "int", False),
]


def render_compare(current: dict, baseline: dict) -> str:
    def val(v, kind):
        if v is None:
            return "-"
        return f"{v * 100:.0f}" if kind == "pct" else str(v)

    def delta(a, b, kind):
        if a is None or b is None:
            return "-"
        d = (a - b) * 100 if kind == "pct" else a - b
        return f"{d:+.0f}"

    lines = [f"{'':<22}{'baseline':>10}{'current':>10}{'delta':>9}"]
    for label in ("genuine", "impostor"):
        cur = current.get("labels", {}).get(label)
        base = baseline.get("labels", {}).get(label)
        if cur is None and base is None:
            continue
        cur, base = cur or {}, base or {}
        lines.append(f"[{label}] n: baseline {base.get('n', '-')}, current {cur.get('n', '-')}")
        for name, key, kind, genuine_only in COMPARE_ROWS:
            if (label == "impostor") == genuine_only and key in ("first_try_match_rate", "match_within_2_rate"):
                continue
            if label == "genuine" and key in ("impostor_accepts", "impostor_max_score"):
                continue
            b, c = base.get(key), cur.get(key)
            lines.append(f"  {name:<20}{val(b, kind):>10}{val(c, kind):>10}{delta(c, b, kind):>9}")
    return "\n".join(lines)


def read_labels(path: Path | None) -> list[str]:
    if path is None:
        return []
    labels = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        labels.append(line.split(None, 1)[0].lower())
    return labels


def describe(name: str, scores: list[int], threshold: int) -> list[str]:
    if not scores:
        return [f"{name}: no attempts"]

    ordered = sorted(scores)
    lines = [
        f"{name}: {len(scores)} attempts",
        f"  min {ordered[0]}  median {int(statistics.median(ordered))}  max {ordered[-1]}",
    ]
    if name == "genuine":
        failed = [s for s in scores if s < threshold]
        lines.append(f"  below threshold ({threshold}): {len(failed)} -> false rejects")
        weakest = min((s for s in scores if s >= threshold), default=0)
        lines.append(f"  margin of the weakest accepted: {weakest}")
    else:
        passed = [s for s in scores if s >= threshold]
        lines.append(f"  at or above threshold ({threshold}): {len(passed)} -> FALSE ACCEPTS")
        lines.append(f"  closest impostor came to the threshold: {ordered[-1]}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument(
        "--labels",
        type=Path,
        help="one label per attempt in order: 'genuine' or 'impostor'",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the per-label summary as JSON instead of text",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        metavar="BASELINE.json",
        help="print a side-by-side table of this run against a saved --json report",
    )
    args = parser.parse_args(argv)

    text = args.log.read_text(encoding="utf-8", errors="replace")
    sections, saw_markers = parse_sections(text)
    if saw_markers or args.json:
        if not saw_markers and args.labels is not None:
            # Legacy order-paired labels: one single-attempt section per label.
            labels = read_labels(args.labels)
            sections = []
            for index, attempt in enumerate(parse_log(text)):
                sec = Section(labels[index] if index < len(labels) else "unlabelled")
                sec.legacy_scores = [attempt.best]
                sec.legacy_threshold = attempt.threshold
                sections.append(sec)
        report = build_report(sections)
        if not report["labels"]:
            print("No match scores in this log.", file=sys.stderr)
            return 1
        if args.compare is not None:
            baseline = json.loads(args.compare.read_text(encoding="utf-8"))
            print(render_compare(report, baseline))
            return 0
        print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_report(report))
        return 0

    attempts = parse_log(text)
    if not attempts:
        print("No match scores in this log.", file=sys.stderr)
        return 1

    threshold = attempts[0].threshold
    labels = read_labels(args.labels)

    groups: dict[str, list[int]] = {"genuine": [], "impostor": [], "unlabelled": []}
    for index, attempt in enumerate(attempts):
        label = labels[index] if index < len(labels) else "unlabelled"
        if label not in groups:
            label = "unlabelled"
        groups[label].append(attempt.best)

    print(f"{len(attempts)} attempts, threshold {threshold}\n")
    for name in ("genuine", "impostor"):
        for line in describe(name, groups[name], threshold):
            print(line)
        print()

    if groups["unlabelled"]:
        print(f"unlabelled: {len(groups['unlabelled'])} attempts -> {groups['unlabelled']}")
        print("Label them before drawing any conclusion about the threshold.\n")

    genuine, impostor = groups["genuine"], groups["impostor"]
    if genuine and impostor:
        separation = min(genuine) - max(impostor)
        print(f"Separation between weakest genuine and strongest impostor: {separation}")
        if separation <= 0:
            print("The two distributions overlap. No threshold separates them cleanly.")
    elif not impostor:
        print("No impostor attempts recorded, so this says nothing about false accepts.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
