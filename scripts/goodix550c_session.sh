#!/usr/bin/env bash
# Guided fingerprint measurement blocks (user level; no sudo except B5's own prompt).
#
#   goodix550c_session.sh b1|b2|b3|b4|b5|b6|all|report [name]
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

ask() {
    # ask "prompt" ; returns when the human presses Enter
    local reply
    read -r -p "$1 " reply || exit 1
}

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

pause_next() { echo "   lift your finger... next one in 2 sec"; sleep 2; }

touch_block() {
    # touch_block <label> <finger> <count> <instruction>
    local label="$1" finger="$2" count="$3" instr="$4" i
    mark_start_time
    echo
    say "=== $instr ==="
    echo "    ($count times. No Enter needed. Ctrl+C to stop.)"
    sleep 3
    for ((i = 1; i <= count; i++)); do
        echo
        echo "[$i/$count]"
        next_run "$label"
        marker_start "$label" "$finger"
        verify_once
        marker_end
        ((i < count)) && pause_next
    done
}

b1() { touch_block genuine "$FINGER" 20 "Use your RIGHT INDEX finger. Touch only when it says TOUCH NOW"; }

b2() {
    # finger already resting on the pad when the action starts
    local label=present-at-start count=8 i
    mark_start_time
    echo
    say "=== Finger-already-on-the-pad test (RIGHT INDEX, 8 rounds) ==="
    echo "    Each round has 3 steps. Just do what the BIG line says:"
    echo "      1) PUT finger ON and HOLD   2) LIFT   3) TAP once"
    sleep 4
    for ((i = 1; i <= count; i++)); do
        echo
        echo "[$i/$count]"
        say "   1) PUT your finger ON the sensor and HOLD it there"
        sleep 3
        next_run "$label"
        marker_start "$label" "$FINGER"
        ( sleep 3; say "   2) LIFT your finger off"; sleep 2; say "   3) TAP the sensor once now" ) &
        QUIET_START=1 verify_once
        wait
        marker_end
        ((i < count)) && pause_next
    done
}

b3() { touch_block impostor "$IMPOSTOR_FINGER" 8 "Use your LEFT INDEX finger (wrong finger on purpose). Touch when it says TOUCH NOW"; }

b4() {
    mark_start_time
    echo; say "=== HANDS OFF: do NOT touch the sensor for ~4 min ==="
    next_run opens
    marker_start opens none
    local i
    for ((i = 1; i <= 30; i++)); do
        timeout -s INT 5 fprintd-verify -f any "$USER" >/dev/null 2>&1
        sleep 2   # let fprintd release the device before the next claim
        printf "\r   %d/30" "$i"
    done
    echo
    marker_end
}

b5() {
    mark_start_time
    echo; say "=== sudo test: when sudo says 'Place your finger', touch the sensor ==="; echo "    (10 times, no Enter needed)"
    local i t0 t1
    for ((i = 1; i <= 10; i++)); do
        echo; echo "[$i/10]"
        next_run sudo
        marker_start sudo "$FINGER"
        t0=$(date +%s.%N)
        sudo -k && sudo true
        t1=$(date +%s.%N)
        printf '   -> sudo finished in %.1fs\n' "$(echo "$t1 - $t0" | bc)"
        marker_end
        ((i < 10)) && pause_next
    done
}

b6() {
    mark_start_time
    echo; say "=== Sleep test (3 rounds) ==="
    local i answer
    for ((i = 1; i <= 3; i++)); do
        echo
        say "[$i/3] Close the lid (or Start menu > Sleep). Wait 10 sec. Open it."
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
    local name="${1:-session}" since out_dir json py
    since="${SINCE:-$(cat "$START_FILE" 2>/dev/null || true)}"
    [[ -n "$since" ]] || { echo "No session start recorded; run a block first or set SINCE='YYYY-MM-DD HH:MM:SS'." >&2; exit 1; }
    out_dir="$HOME/goodix550c-debs/measurements"
    mkdir -p "$out_dir"
    json="$out_dir/$(date +%F)-$name.json"
    py="$ROOT/.venv/bin/python"
    [[ -x "$py" ]] || py=python3
    local log
    log="$(mktemp)"
    trap 'rm -f "$log"' RETURN
    journalctl --no-pager -o short-iso --since "$since" _SYSTEMD_UNIT=fprintd.service + SYSLOG_IDENTIFIER="$TAG" > "$log"
    "$py" "$ROOT/scripts/goodix550c_score_report.py" --log "$log"
    "$py" "$ROOT/scripts/goodix550c_score_report.py" --log "$log" --json > "$json" && echo "JSON saved: $json"
}

case "${1:-}" in
    b1) b1 ;;
    b2) b2 ;;
    b3) b3 ;;
    b4) b4 ;;
    b5) b5 ;;
    b6) b6 ;;
    all) rm -f "$START_FILE"; b1; b2; b3; b4; b5; b6; report "${2:-all}" ;;
    rest) b2; b3; b4; b5; b6; echo; say "ALL DONE - tell Claude 'done'"; report "${2:-final}" ;;
    final) rm -f "$START_FILE"; b1; b2; b3; b4; b5; b6; echo; say "ALL DONE - tell Claude 'done'"; report "${2:-final}" ;;
    baseline|test) rm -f "$START_FILE"; b1; b2; b3; b4; b5; echo; say "ALL DONE - tell Claude 'done'"; report "${2:-${1}}" ;;
    report) report "${2:-session}" ;;
    *)
        echo "Usage: $0 b1|b2|b3|b4|b5|b6|all|report [name]" >&2
        echo "  b1 genuine x20, b2 finger-on-pad-first x10, b3 impostor x10, b4 opens x50," >&2
        echo "  b5 sudo x10, b6 suspend x5. Env: FINGER, IMPOSTOR_FINGER, SINCE, VERIFY_TIMEOUT." >&2
        exit 2
        ;;
esac
