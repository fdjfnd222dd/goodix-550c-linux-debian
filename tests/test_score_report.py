from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "goodix550c_score_report", ROOT / "scripts" / "goodix550c_score_report.py"
)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)

P = "Oct 17 12:00:00 yoga "
TAG = P + "goodix550c-session[1]: "
DRV = P + "fprintd[2]: "


def attempt(result, best, polls=3, ref_retries=0, action="verify", lift=None):
    extra = "" if lift is None else f" lift_rebase={lift}"
    return (
        f"{DRV}goodix550c attempt: action={action} ready_to_down_ms=800 down_polls={polls} "
        f"settle_ms=300 ref_mean=2350 ref_retries={ref_retries} noncontact_x1000=120 "
        f"keypoints=80 best_score={best} early_exit=1 threshold=150 result={result} "
        "dmax_pos=40 dmax_neg=-12" + extra
    )


def open_line(result, ms, phase):
    return (f"{DRV}goodix550c open: result={result} ms={ms} phase={phase} "
            "drain_bytes=0 tls_retry=0")


SESSION = "\n".join([
    TAG + "label=genuine finger=right-index run=1",
    attempt("match", 900),
    TAG + "end run=1",
    TAG + "label=genuine finger=right-index run=2",
    attempt("retry:remove-finger", 0, ref_retries=2),
    attempt("match", 400),
    TAG + "end run=2",
    TAG + "label=genuine finger=right-index run=3",
    attempt("no-match", 100),
    attempt("no-match", 120),
    attempt("match", 300),
    TAG + "end run=3",
    TAG + "label=impostor finger=left-index run=4",
    attempt("no-match", 60),
    attempt("no-match", 88),
    TAG + "end run=4",
    TAG + "label=opens finger=none run=5",
    open_line("ok", 1000, "done"),
    open_line("ok", 1400, "done"),
    open_line("fail", 5000, "tls"),
    TAG + "end run=5",
    DRV + "stray line outside any marker",
])


def test_sample_regex_matches_verify_and_identify_forms():
    verify = report.SAMPLE_RE.search("verify: sample 3 sigfm_score 77")
    identify = report.SAMPLE_RE.search("identify: gallery[1] sample 2 sigfm_score 412")

    assert verify.group("score") == "77" and verify.group("vsample") == "3"
    assert identify.group("score") == "412"
    assert identify.group("gallery") == "1" and identify.group("isample") == "2"


def test_sessions_split_on_markers_and_are_summarised_per_label():
    sections, saw = report.parse_sections(SESSION)
    result = report.build_report(sections)
    genuine = result["labels"]["genuine"]

    assert saw
    assert result["threshold"] == 150
    assert genuine["n"] == 3
    assert genuine["first_try_match_rate"] == round(1 / 3, 3)
    assert genuine["match_within_2_rate"] == round(2 / 3, 3)
    assert genuine["retry_reasons"] == {"remove-finger": 1}
    # The retry attempt never reached the matcher, so its score of 0 is not counted.
    assert (genuine["score_min"], genuine["score_median"], genuine["score_max"]) == (100, 300, 900)
    assert genuine["fingers"] == ["right-index"]

    impostor = result["labels"]["impostor"]
    assert impostor["impostor_max_score"] == 88
    assert impostor["impostor_accepts"] == 0

    opens = result["labels"]["opens"]
    assert opens["opens"] == 3
    assert opens["open_failures_by_phase"] == {"tls": 1}
    assert opens["median_open_ms"] == 1400
    assert "unlabelled" not in result["labels"]


def test_journalctl_free_markers_without_the_tag_prefix_still_split():
    text = "label=genuine finger=a run=1\n" + attempt("match", 500) + "\nend run=1\n"
    # A bare "end" without the logger tag is not a marker; the next label closes the run.
    sections, saw = report.parse_sections(text + "label=impostor finger=b run=2\n" + attempt("no-match", 5))

    assert saw
    assert [s.label for s in sections] == ["genuine", "impostor"]


def test_old_logs_without_summary_lines_fall_back_to_score_lines():
    text = "\n".join([
        TAG + "label=genuine finger=a run=1",
        DRV + "verify: sample 0 sigfm_score 500",
        DRV + "Verify best SIGFM score: 500 (best_min: 150)",
        TAG + "label=impostor finger=b run=2",
        DRV + "Verify best SIGFM score: 20 (best_min: 150)",
    ])
    result = report.build_report(report.parse_sections(text)[0])

    assert result["labels"]["genuine"]["first_try_match_rate"] == 1.0
    assert result["labels"]["impostor"]["impostor_max_score"] == 20


def test_cli_json_output_and_legacy_text_output_still_work(tmp_path, capsys):
    session_log = tmp_path / "session.log"
    session_log.write_text(SESSION, encoding="utf-8")
    assert report.main(["--log", str(session_log), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["labels"]["genuine"]["n"] == 3

    assert report.main(["--log", str(session_log)]) == 0
    assert "genuine: 3 runs" in capsys.readouterr().out

    legacy = tmp_path / "legacy.log"
    legacy.write_text("Verify best SIGFM score: 300 (best_min: 150)\n"
                      "Verify best SIGFM score: 10 (best_min: 150)\n", encoding="utf-8")
    labels = tmp_path / "labels.txt"
    labels.write_text("genuine right index\nimpostor left thumb\n", encoding="utf-8")
    assert report.main(["--log", str(legacy), "--labels", str(labels)]) == 0
    out = capsys.readouterr().out
    assert "genuine: 1 attempts" in out and "impostor: 1 attempts" in out
    assert "Separation between weakest genuine and strongest impostor: 290" in out


def test_manual_pass_fail_is_taken_from_the_end_marker():
    text = "\n".join([
        TAG + "label=suspend finger=a run=1", TAG + "end run=1 result=pass",
        TAG + "label=suspend finger=a run=2", TAG + "end run=2 result=fail",
        TAG + "label=suspend finger=a run=3", TAG + "end run=3 result=pass",
    ])
    result = report.build_report(report.parse_sections(text)[0])

    assert result["labels"]["suspend"]["n"] == 3
    assert result["labels"]["suspend"]["manual_results"] == {"pass": 2, "fail": 1}


def test_lift_rebase_field_is_summed_per_label_and_old_logs_still_parse():
    text = "\n".join([
        TAG + "label=genuine finger=right-index run=1",
        attempt("match", 900, lift=2),
        TAG + "end run=1",
        TAG + "label=genuine finger=right-index run=2",
        attempt("retry:too-short", 0, lift=1),
        attempt("match", 400),  # line from a build without the field
        TAG + "end run=2",
    ])
    sections, _ = report.parse_sections(text)
    genuine = report.build_report(sections)["labels"]["genuine"]

    assert genuine["lift_rebaselines"] == 3
    assert genuine["attempts"] == 3
    assert genuine["retry_reasons"] == {"too-short": 1}
    assert "lift re-baselines: 3" in report.render_report(report.build_report(sections))
    # Logs with no field at all report zero.
    old, _ = report.parse_sections(SESSION)
    assert report.build_report(old)["labels"]["genuine"]["lift_rebaselines"] == 0
