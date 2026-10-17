#!/usr/bin/env bash
# Guided fingerprint measurement blocks (user level; no sudo except B5's own prompt).
#
#   goodix550c_session.sh b1|b2|b3|b4|b5|b6|all|rest|final|baseline|test|report [name]
#
# Every run is bracketed by journal markers (logger -t goodix550c-session) that
# scripts/goodix550c_score_report.py uses to split the fprintd journal by label.
# Needs GOODIX550C_LOG_SUMMARY=1 in the fprintd service for the per-attempt lines.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/goodix550c-session"
START_FILE="$STATE_DIR/start"
FINGER="${FINGER:-right-index}"
IMPOSTOR_FINGER="${IMPOSTOR_FINGER:-left-index}"
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-30}"
OUT_DIR="${GOODIX550C_MEASUREMENTS_DIR:-$HOME/goodix550c-debs/measurements}"

# Repetitions per block (usage text and prompts are derived from these).
B1_COUNT=20   # genuine
B2_COUNT=8    # finger already on the pad first
B3_COUNT=8    # impostor
B4_COUNT=30   # hands-off opens
B5_COUNT=10   # sudo
B6_COUNT=3    # suspend

# Timing (seconds); override from the environment.
LEAD_IN_SECS="${LEAD_IN_SECS:-3}"       # pause after a block's instructions
B2_INTRO_SECS="${B2_INTRO_SECS:-4}"     # b2 reads a longer 3-step explanation
HOLD_SECS="${HOLD_SECS:-3}"             # b2: finger held on the pad before/after the run starts
LIFT_GAP_SECS="${LIFT_GAP_SECS:-2}"     # b2: time between the LIFT and TAP prompts
PAUSE_SECS="${PAUSE_SECS:-2}"           # between runs
RELEASE_SECS="${RELEASE_SECS:-2}"       # b4: let fprintd release the device between claims
RUN_COUNTER=0
TAG=goodix550c-session

mkdir -p "$STATE_DIR"

mark_start_time() {
    [[ -s "$START_FILE" ]] || date '+%F %T' > "$START_FILE"
}

next_run() {
    RUN_COUNTER=$((RUN_COUNTER + 1))
    RUN_ID="$(date +%H%M%S)-$1-$RUN_COUNTER"
}

marker_start() { logger -t "$TAG" "label=$1 finger=$2 run=$RUN_ID"; }
marker_end() { logger -t "$TAG" "end run=$RUN_ID${1:+ result=$1}"; }

BOLD="$(tput bold 2>/dev/null || true)"; NORM="$(tput sgr0 2>/dev/null || true)"
say() { printf '%s%s%s\n' "$BOLD" "$1" "$NORM"; }

# Streams fprintd-verify so the human sees TOUCH NOW the moment the sensor is ready.
# Sets RESULT to match|no-match|timeout|other.
verify_once() {
    local line
    RESULT=other
    while IFS= read -r line; do
        case "$line" in
            *"Verify started"*) [[ -n "${QUIET_START:-}" ]] || say "   >>> TOUCH THE SENSOR NOW (rest flat ~1 sec, then lift) <<<" ;;
            *"Verify result:"*"(not done)"*) say "   ...didn't read it. Lift, then TOUCH AGAIN." ;;
            *"verify-match"*) RESULT=match ;;
            *"verify-no-match"*) RESULT=no-match ;;
        esac
    done < <(timeout "$VERIFY_TIMEOUT" stdbuf -oL -eL fprintd-verify -f any "$USER" 2>&1; echo "rc=$?")
    case "$RESULT" in
        match) say "   MATCH" ;;
        no-match) say "   NO MATCH" ;;
        *) say "   (no result - timed out)"; RESULT=timeout ;;
    esac
}

pause_next() { echo "   lift your finger... next one in $PAUSE_SECS sec"; sleep "$PAUSE_SECS"; }

touch_block() {
    # touch_block <label> <finger> <count> <instruction>
    local label="$1" finger="$2" count="$3" instr="$4" i
    mark_start_time
    echo
    say "=== $instr ==="
    echo "    ($count times. No Enter needed. Ctrl+C to stop.)"
    sleep "$LEAD_IN_SECS"
    for ((i = 1; i <= count; i++)); do
        echo
        echo "[$i/$count]"
        next_run "$label"
        marker_start "$label" "$finger"
        verify_once
        marker_end
        if ((i < count)); then pause_next; fi
    done
}

b1() { touch_block genuine "$FINGER" "$B1_COUNT" "Use your RIGHT INDEX finger. Touch only when it says TOUCH NOW"; }

b2() {
    # finger already resting on the pad when the action starts
    local label=present-at-start count="$B2_COUNT" i
    mark_start_time
    echo
    say "=== Finger-already-on-the-pad test (RIGHT INDEX, $count rounds) ==="
    echo "    Each round has 3 steps. Just do what the BIG line says:"
    echo "      1) PUT finger ON and HOLD   2) LIFT   3) TAP once"
    sleep "$B2_INTRO_SECS"
    for ((i = 1; i <= count; i++)); do
        echo
        echo "[$i/$count]"
        say "   1) PUT your finger ON the sensor and HOLD it there"
        sleep "$HOLD_SECS"
        next_run "$label"
        marker_start "$label" "$FINGER"
        (
            sleep "$HOLD_SECS"
            say "   2) LIFT your finger off"; logger -t "$TAG" "phase=lift run=$RUN_ID"
            sleep "$LIFT_GAP_SECS"
            say "   3) TAP the sensor once now"; logger -t "$TAG" "phase=tap run=$RUN_ID"
        ) &
        QUIET_START=1 verify_once
        wait
        marker_end
        if ((i < count)); then pause_next; fi
    done
}

b3() { touch_block impostor "$IMPOSTOR_FINGER" "$B3_COUNT" "Use your LEFT INDEX finger (wrong finger on purpose). Touch when it says TOUCH NOW"; }

b4() {
    mark_start_time
    echo; say "=== HANDS OFF: do NOT touch the sensor for ~4 min ==="
    next_run opens
    marker_start opens none
    local i
    for ((i = 1; i <= B4_COUNT; i++)); do
        timeout -s INT 5 fprintd-verify -f any "$USER" >/dev/null 2>&1
        sleep "$RELEASE_SECS"   # let fprintd release the device before the next claim
        printf "\r   %d/%d" "$i" "$B4_COUNT"
    done
    echo
    marker_end
}

b5() {
    mark_start_time
    echo; say "=== sudo test: when sudo says 'Place your finger', touch the sensor ==="; echo "    ($B5_COUNT times, no Enter needed)"
    local i t0 t1
    for ((i = 1; i <= B5_COUNT; i++)); do
        echo; echo "[$i/$B5_COUNT]"
        next_run sudo
        marker_start sudo "$FINGER"
        t0=$(date +%s.%N)
        sudo -k && sudo true
        t1=$(date +%s.%N)
        printf '   -> sudo finished in %.1fs\n' "$(echo "$t1 - $t0" | bc)"
        marker_end
        if ((i < B5_COUNT)); then pause_next; fi
    done
}

b6() {
    mark_start_time
    echo; say "=== Sleep test ($B6_COUNT rounds) ==="
    local i answer
    for ((i = 1; i <= B6_COUNT; i++)); do
        echo
        say "[$i/$B6_COUNT] Close the lid (or Start menu > Sleep). Wait 10 sec. Open it."
        echo "      On the lock screen, unlock with your FINGER (not the password)."
        echo "      Then come back here and type pass or fail."
        next_run suspend
        marker_start suspend "$FINGER"
        while :; do
            read -r -p "   Did your finger unlock it (within 2 tries)? type pass or fail: " answer || exit 1
            case "$answer" in pass|fail) break ;; esac
        done
        marker_end "$answer"
    done
}

report() {
    local name="${1:-session}" since json py
    since="${SINCE:-$(cat "$START_FILE" 2>/dev/null || true)}"
    [[ -n "$since" ]] || { echo "No session start recorded; run a block first or set SINCE='YYYY-MM-DD HH:MM:SS'." >&2; exit 1; }
    mkdir -p "$OUT_DIR"
    json="$OUT_DIR/$(date +%F)-$name.json"
    py="$ROOT/.venv/bin/python"
    [[ -x "$py" ]] || py=python3
    local log
    log="$(mktemp)"
    trap 'rm -f "$log"' RETURN
    journalctl --no-pager -o short-iso --since "$since" _SYSTEMD_UNIT=fprintd.service + SYSLOG_IDENTIFIER="$TAG" > "$log"
    "$py" "$ROOT/scripts/goodix550c_score_report.py" --log "$log"
    "$py" "$ROOT/scripts/goodix550c_score_report.py" --log "$log" --json > "$json" && echo "JSON saved: $json"
}

# run_set fresh|keep REPORT_NAME BLOCK... : run blocks in order, then report.
run_set() {
    local mode="$1" name="$2" blk
    shift 2
    [[ "$mode" == fresh ]] && rm -f "$START_FILE"
    for blk in "$@"; do "$blk"; done
    echo; say "ALL DONE - tell Claude 'done'"
    report "$name"
}

case "${1:-}" in
    b[1-6]) "$1" ;;
    all) run_set fresh "${2:-all}" b1 b2 b3 b4 b5 b6 ;;
    rest) run_set keep "${2:-final}" b2 b3 b4 b5 b6 ;;
    final) run_set fresh "${2:-final}" b1 b2 b3 b4 b5 b6 ;;
    baseline|test) run_set fresh "${2:-$1}" b1 b2 b3 b4 b5 ;;
    report) report "${2:-session}" ;;
    *)
        echo "Usage: $0 b1|b2|b3|b4|b5|b6|all|rest|final|baseline|test|report [name]" >&2
        echo "  b1 genuine x$B1_COUNT, b2 finger-on-pad-first x$B2_COUNT, b3 impostor x$B3_COUNT," >&2
        echo "  b4 opens x$B4_COUNT, b5 sudo x$B5_COUNT, b6 suspend x$B6_COUNT." >&2
        echo "  Env: FINGER, IMPOSTOR_FINGER, SINCE, VERIFY_TIMEOUT, GOODIX550C_MEASUREMENTS_DIR," >&2
        echo "       LEAD_IN_SECS, B2_INTRO_SECS, HOLD_SECS, LIFT_GAP_SECS, PAUSE_SECS, RELEASE_SECS." >&2
        exit 2
        ;;
esac
