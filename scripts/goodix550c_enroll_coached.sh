#!/usr/bin/env bash
# Coached enrollment: one short placement instruction per stage.
#
#   goodix550c_enroll_coached.sh [slot]     (default slot: right-index-finger)
#   REPLACE=1 goodix550c_enroll_coached.sh  delete that slot first, then enroll
#
# fprintd refuses a second slot for a finger that is already enrolled
# (enroll-duplicate), so more coverage means re-enrolling the slot, optionally
# with more samples (GOODIX550C_TUNE_ENROLL_SAMPLES). fprintd asks for your
# password (polkit) before it starts.
set -uo pipefail

SLOT="${1:-right-index-finger}"
TIMEOUT="${ENROLL_TIMEOUT:-240}"
# COACH=natural (default): your everyday touch with small shifts. Round r2 showed
# that wide coaching (rolls, tips) stores samples everyday touches never match:
# 11/12 matches hit one single sample, with lower scores than a natural enrollment.
# COACH=wide keeps the old centre/tip/base/roll pattern.
if [[ "${COACH:-natural}" == wide ]]; then
PLACES=(middle middle fingertip fingertip "lower part of finger" "lower part of finger"
        "roll LEFT" "roll LEFT" "roll RIGHT" "roll RIGHT" "tip, roll left" "tip, roll right"
        "low, roll left" "low, roll right" middle fingertip "lower part of finger" "roll LEFT"
        "roll RIGHT" middle "tip, roll left" "tip, roll right" "low, roll left" "low, roll right"
        middle middle middle middle middle middle)
else
PLACES=(normal normal normal "normal, a bit higher" "normal, a bit lower" normal
        "normal, a bit left" "normal, a bit right" normal "normal, a bit higher" "normal, a bit lower" normal
        "normal, slightly tilted" normal "normal, a bit left" "normal, a bit right" normal normal
        "normal, a bit higher" "normal, a bit lower" normal normal normal normal
        normal normal normal normal normal normal)
fi

BOLD="$(tput bold 2>/dev/null || true)"; NORM="$(tput sgr0 2>/dev/null || true)"
say() { printf '%s%s%s\n' "$BOLD" "$1" "$NORM"; }

if fprintd-list "$USER" 2>/dev/null | grep -q -- "- #[0-9]*: $SLOT\$"; then
    if [[ "${REPLACE:-}" == 1 ]]; then
        say "Deleting the old '$SLOT' first..."
        fprintd-delete "$USER" -f "$SLOT" >/dev/null || { echo "Delete failed." >&2; exit 1; }
    else
        echo "$SLOT is already enrolled. Re-run with REPLACE=1 to replace it." >&2
        exit 1
    fi
fi

say "=== Enroll RIGHT INDEX into slot '$SLOT' ==="
echo "    Touch the way you normally would. Small shifts when it asks. Hold ~1 sec, lift."
stage=0 result=fail
while IFS= read -r line; do
    case "$line" in
        *"Enrolling"*) say "[1] TOUCH NOW: ${PLACES[0]}" ;;
        *"enroll-stage-passed"*)
            stage=$((stage + 1))
            say "[$((stage + 1))] TOUCH NOW: ${PLACES[stage]:-middle}" ;;
        *"enroll-completed"*) result=ok ;;
        *"enroll-retry-scan"*|*"enroll-swipe-too-short"*|*"enroll-finger-not-centered"*|*"enroll-remove-and-retry"*)
            say "    didn't take. Lift, TOUCH NOW again: ${PLACES[stage]:-middle}" ;;
        *"enroll-duplicate"*) say "    fprintd says this finger is already enrolled in another slot." ;;
        *"enroll-failed"*|*"enroll-unknown-error"*|*"enroll-data-full"*|*"failed"*|*"Error"*|*"error"*) echo "   $line" ;;
    esac
done < <(timeout "$TIMEOUT" stdbuf -oL -eL fprintd-enroll -f "$SLOT" "$USER" 2>&1)

if [[ "$result" == ok ]]; then
    say "DONE - '$SLOT' enrolled. Tell Claude 'done'."
else
    say "Enrollment did not finish. Tell Claude."
    exit 1
fi
