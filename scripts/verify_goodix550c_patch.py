#!/usr/bin/env python3
"""Offline policy audit for a prepared fail-closed Goodix 550c tree."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PERSISTENT_HELPERS = (
    "goodix_cmd_production_write",
    "goodix_cmd_mcu_erase_app",
    "goodix_cmd_preset_psk_write_chunk",
    "goodix_cmd_write_firmware",
    "goodix_cmd_check_firmware",
    "goodix_550c_app_firmware_load",
    "goodix_maybe_start_selfheal",
)


def effective_source(text: str) -> str:
    """Remove literal #if 0 regions, including nested preprocessor blocks."""
    output: list[str] = []
    disabled_depth = 0

    for line in text.splitlines():
        if re.match(r"^\s*#\s*if\s+0(?:\s|/|$)", line):
            disabled_depth += 1
            continue
        if disabled_depth and re.match(r"^\s*#\s*(?:if|ifdef|ifndef)\b", line):
            disabled_depth += 1
            continue
        if disabled_depth and re.match(r"^\s*#\s*endif\b", line):
            disabled_depth -= 1
            continue
        if disabled_depth == 0:
            output.append(line)

    if disabled_depth:
        raise ValueError("unbalanced literal #if 0 block")
    return "\n".join(output)


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def read(path: Path, failures: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        failures.append(f"cannot read {path}: {error}")
        return ""


def meson_option_is_default_off(options: str, name: str) -> bool:
    """Report whether this exact option block declares ``value: false``.

    The declaration is delimited by the next ``option(`` rather than by a
    closing parenthesis: descriptions in these files contain parentheses. A
    substring test over the whole file would instead be satisfied by any other
    default-off option and would let this one silently default on.
    """
    start = re.search(r"option\(\s*'" + re.escape(name) + r"'\s*,", options)
    if start is None:
        return False

    remainder = options[start.end() :]
    following = re.search(r"\boption\(", remainder)
    block = remainder[: following.start()] if following else remainder
    return re.search(r"\bvalue:\s*false\b", block) is not None


def static_function_body(source: str, signature: str) -> str:
    """Return the body text of one static function definition, or ``""``.

    The definition is delimited by the next top-level ``static`` declaration
    rather than by a closing brace, which brace counting would have to track
    through strings and comments. A substring test over the whole file would
    instead be satisfied by a guard belonging to some neighbouring function
    and would let this one go unguarded.

    The signature is matched on an identifier boundary so a name that is a
    suffix of a longer one does not resolve to that longer function.
    """
    start = re.search(r"(?<![0-9A-Za-z_])" + re.escape(signature), source)
    if start is None:
        return ""

    remainder = source[start.end() :]
    following = re.search(r"\nstatic\s", remainder)
    return remainder[: following.start()] if following else remainder


def audit(driver_tree: Path, libfprint_tree: Path) -> list[str]:
    failures: list[str] = []
    driver_dir = driver_tree / "drivers" / "goodix53x5"
    integrated_dir = libfprint_tree / "libfprint" / "drivers" / "goodix53x5"

    session_raw = read(driver_dir / "goodix53x5-session.c", failures)
    commands_raw = read(driver_dir / "goodix53x5-commands.c", failures)
    scan_raw = read(driver_dir / "goodix53x5-scan.c", failures)
    calibration = read(driver_dir / "goodix53x5-calibration.c", failures)
    transport_raw = read(driver_dir / "goodix53x5-transport.c", failures)
    safety = read(driver_dir / "goodix53x5-safety.h", failures)
    tls = read(driver_dir / "goodix53x5-tls.c", failures)
    device = read(driver_dir / "goodix53x5.c", failures)
    lib_meson = read(libfprint_tree / "libfprint" / "meson.build", failures)
    root_meson = read(libfprint_tree / "meson.build", failures)
    options = read(libfprint_tree / "meson_options.txt", failures)

    try:
        session = effective_source(session_raw)
        commands = effective_source(commands_raw)
    except ValueError as error:
        failures.append(str(error))
        session = session_raw
        commands = commands_raw

    for helper in PERSISTENT_HELPERS:
        require(
            helper not in session and helper not in commands,
            f"persistent helper remains in compiled source: {helper}",
            failures,
        )

    require(
        "goodix_550c_command_is_persistent_mutation (category, command)" in transport_raw,
        "transport does not enforce the persistent-command deny predicate",
        failures,
    )
    for category, command in (
        ("0xA", "0x2"),
        ("0xE", "0x0"),
        ("0xE", "0x1"),
        ("0xF", "0x0"),
        ("0xF", "0x2"),
    ):
        pattern = rf"category == {category}\s*&&\s*command == {command}"
        require(
            re.search(pattern, safety) is not None,
            f"persistent opcode pair {category}/{command} is not denied",
            failures,
        )

    require(
        "#define GOODIX550C_ENABLE_VOLATILE_INIT 0" in safety,
        "volatile initialization is not compile-time default-off",
        failures,
    )
    require(
        'g_getenv ("GOODIX550C_ALLOW_VOLATILE_INIT"), "1"' in safety,
        "volatile initialization lacks the exact runtime opt-in",
        failures,
    )
    require(
        "goodix_550c_command_needs_volatile_init (category, command)" in transport_raw,
        "volatile commands do not pass through the runtime policy gate",
        failures,
    )
    require(
        session.count("g_usb_device_reset (") == 1
        and "if (!goodix_550c_volatile_init_allowed ())" in session,
        "active USB reset is absent or not guarded by volatile-init policy",
        failures,
    )
    require(
        "G_USB_DEVICE_CLAIM_INTERFACE_BIND_KERNEL_DRIVER" not in session,
        "compiled session may detach or rebind an existing kernel driver",
        failures,
    )

    require("/etc/goodix550c.psk" not in session_raw, "fixed /etc PSK fallback remains", failures)
    require(
        "memcpy (out, goodix_psk" not in session,
        "550c can still fall back to the all-zero PSK",
        failures,
    )
    for marker in (
        'g_getenv ("GOODIX550C_PSK")',
        'g_getenv ("GOODIX550C_PSK_FILE")',
        "Set exactly one of GOODIX550C_PSK",
        "g_path_is_absolute (path)",
        "O_RDONLY | O_CLOEXEC | O_NOFOLLOW",
        "fstat (fd, &st)",
        "st.st_uid != geteuid ()",
        "(st.st_mode & 0777) != 0600",
        "st.st_nlink != 1",
        "OPENSSL_cleanse (hex, hex_alloc_len)",
        "OPENSSL_cleanse (psk, sizeof (psk))",
    ):
        require(marker in session_raw, f"external-PSK invariant missing: {marker}", failures)
    require(
        '#define GOODIX_550C_EXPECTED_FW "GF5288_GM168SEC_APP_13021"' in session_raw,
        "exact validated firmware gate is missing",
        failures,
    )
    require(
        'SSL_CTX_set_cipher_list (tls->ctx, "PSK-AES128-CBC-SHA256")' in tls,
        "TLS cipher list is broader than the captured 550c suite",
        failures,
    )
    require(
        'GOODIX_TLS_PSK_IDENTITY "Client_identity"' in tls
        and "strcmp (identity, GOODIX_TLS_PSK_IDENTITY)" in tls,
        "TLS callback does not restrict the captured PSK identity",
        failures,
    )
    require(
        "OPENSSL_cleanse (tls->psk, sizeof (tls->psk))" in tls,
        "long-lived TLS PSK is not securely cleansed",
        failures,
    )

    require(
        re.search(
            r"if \(self->variant == GOODIX_VARIANT_TLS_PSK\).*?"
            r"GOODIX_PROTO_CMD_FDT_DOWN,\s*fdt_base,\s*"
            r"GOODIX_FDT_BASE_LEN,\s*FALSE",
            commands,
            re.DOTALL,
        )
        is not None,
        "firmware-13021 TLS path does not use the direct 24-byte FDT-down base",
        failures,
    )
    require(
        "goodix_build_fdt_payload (0x0E" in commands
        and "goodix_build_fdt_payload (op_code" in commands,
        "unvalidated FDT-up/manual layouts were changed",
        failures,
    )
    require(
        "FDT down ACK validated; event read posted" in scan_raw,
        "FDT-down ACK/event diagnostic boundary is missing",
        failures,
    )

    for marker in (
        "#define GOODIX550C_ENABLE_MANUAL_FDT_POLL 0",
        'g_getenv ("GOODIX550C_ALLOW_MANUAL_FDT_POLL"), "1"',
    ):
        require(marker in safety, f"manual-FDT gate missing: {marker}", failures)
    for marker in (
        "goodix_550c_manual_fdt_poll_allowed ()",
        "goodix_cmd_fdt_manual (ssm, dev, TRUE",
        "down = changed_pairs > 0",
        "state->consecutive >= GOODIX_TUNE (self, CONFIRMATIONS)",
        "state->provisional_baseline",
        "GOODIX_REF_CAPTURE_REG_OFF_DONE",
        "Manual FDT finger-down poll armed",
        "Manual FDT finger-up poll armed",
        "Manual FDT finger-up confirmed",
    ):
        require(marker in scan_raw, f"manual-FDT invariant missing: {marker}", failures)
    # Contact is declared on the leading edge of a landing finger, so the
    # capture must not follow it immediately.
    for marker in (
        "GOODIX_FINGER_WAIT_POLL_DOWN_SETTLE",
        "Manual FDT contact settled",
    ):
        require(marker in scan_raw, f"manual-FDT settle invariant missing: {marker}", failures)
    require(
        re.search(
            r"FP_FINGER_STATUS_NEEDED\);\s*\n\s*fpi_ssm_jump_to_state_delayed \(ssm,\s*\n"
            r"\s*GOODIX_FINGER_WAIT_POLL_DOWN_SETTLE,\s*\n"
            r"\s*GOODIX_TUNE \(self, SETTLE_MS\)\);",
            scan_raw,
        )
        is not None,
        "confirmed manual-FDT contact reaches capture without the settle window",
        failures,
    )

    # Placement tolerance must come from pad coverage, not a weaker gate.
    private = read(driver_dir / "goodix53x5-private.h", failures)
    # Runtime-tunable defaults equal the historical constants (patch 0020).
    for marker in (
        "#define GOODIX_MANUAL_FDT_CONFIRMATIONS 2",
        "#define GOODIX_MANUAL_FDT_POLL_DELAY_MS 100",
        "#define GOODIX_MANUAL_FDT_DOWN_SETTLE_MS 300",
    ):
        require(marker in private, f"tunable default missing: {marker}", failures)
    require(
        "#define GOODIX_ENROLL_SAMPLES 16" in private
        and "#define GOODIX_ENROLL_NO_CONTACT_FRACTION 0.90" in private
        and "#define GOODIX_SIGFM_BEST_MIN 150" in private
        and "#define GOODIX_MIN_CAPTURE_KEYPOINTS 20" in private
        and "#define GOODIX_ENROLL_MAX_CLIPPED_FRACTION 0.10" in private,
        "enrollment coverage or one of the unchanged match gates is wrong",
        failures,
    )

    # The reference frame is subtracted from every capture, so one that carries
    # no signal changes the preprocessing instead of failing visibly.
    require(
        "goodix_reference_frame_has_signal" in scan_raw
        and "if (!goodix_reference_frame_has_signal (img12))" in scan_raw
        and "#define GOODIX_REFERENCE_MIN_MEAN 200" in read(
            driver_dir / "goodix53x5-private.h", failures
        )
        and "#define GOODIX_REFERENCE_MAX_RETRIES 60" in read(
            driver_dir / "goodix53x5-private.h", failures
        ),
        "an empty reference frame can still be stored and subtracted",
        failures,
    )
    # The blackout follows a sleep, and the enrollment loop used to sleep once
    # per stage rather than once per action.
    require(
        "self->finger_up_keep_awake = FALSE;" in scan_raw
        and "self->finger_up_keep_awake = self->enroll_stage < fp_device_get_nr_enroll_stages (dev);"
        in read(driver_dir / "goodix53x5-enroll.c", failures),
        "enrollment still sleeps the sensor between stages",
        failures,
    )

    require(
        "goodix_device_measure_fdt_delta" in calibration
        and "if (delta > threshold)" in calibration,
        "manual-FDT delta helper or strict threshold boundary is missing",
        failures,
    )
    require(
        "goodix_run_cmd_cancellable" not in transport_raw
        and "goodix_cmd_fdt_manual_cancellable" not in commands_raw,
        "manual polling may abandon a partially received command transaction",
        failures,
    )
    require(
        all(
            marker not in scan_raw
            for marker in (
                "touch_flag=0x",
                "touch_flag == 0",
                "max_delta=",
                "changed_pairs=",
            )
        ),
        "manual-FDT diagnostics expose channel/contact measurements",
        failures,
    )
    require(
        "Reply framing: pack flag=" in transport_raw
        and re.search(
            r"if \(self->variant == GOODIX_VARIANT_TLS_PSK &&\s*\n"
            r"\s*goodix_550c_manual_fdt_poll_allowed \(\)\)\s*\n"
            r"\s*\{\s*\n\s*guint8 pack_flag",
            transport_raw,
        )
        is not None,
        "reply-framing diagnostic is missing or not gated by the experimental policy",
        failures,
    )
    require(
        "pack_payload," not in transport_raw.split("Reply framing")[1][:400]
        or "fp_dbg (\"Reply framing: pack flag=0x%02x payload=%zu assembled=%zu\"" in transport_raw,
        "reply-framing diagnostic reports more than framing metadata",
        failures,
    )

    require(
        "ACK diagnostic:" in transport_raw
        and "goodix_550c_manual_fdt_poll_allowed ()" in transport_raw,
        "ACK flags are not neutrally diagnosed under the experimental gate",
        failures,
    )

    frame_stats = static_function_body(
        scan_raw, "goodix_550c_log_frame_stats (FpiDeviceGoodix53x5 *self,"
    )
    require(
        "if (!goodix_550c_manual_fdt_poll_allowed ())" in frame_stats,
        "capture-path frame diagnostic is missing or not gated by the experimental policy",
        failures,
    )
    require(
        scan_raw.count('goodix_550c_log_frame_stats (self, img12, "') == 2,
        "capture-path frame diagnostic does not cover both the reference and capture readouts",
        failures,
    )
    require(
        all(
            marker not in frame_stats
            for marker in ("img12[r *", "GOODIX_SENSOR_WIDTH", "GOODIX_SENSOR_HEIGHT")
        ),
        "capture-path frame diagnostic measures the frame per row or column",
        failures,
    )

    pids = set(re.findall(r"\.pid\s*=\s*0x([0-9a-fA-F]+)", device))
    require(pids == {"550c"}, f"driver binds unexpected USB PIDs: {sorted(pids)}", failures)

    require(
        not (integrated_dir / "goodix53x5-firmware550c.c").exists()
        and not (integrated_dir / "goodix53x5-firmware550c.h").exists(),
        "firmware loader was copied into the integration tree",
        failures,
    )
    require(
        "goodix53x5-firmware550c" not in lib_meson,
        "firmware loader is registered in Meson",
        failures,
    )
    for component in (
        "goodix53x5-tls.c",
        "goodix53x5-scan.c",
        "goodix53x5-enroll.c",
        "goodix53x5-auth.c",
        "goodix53x5-match.c",
        "goodix53x5-image.c",
    ):
        require(
            component in lib_meson,
            f"functional component missing from build: {component}",
            failures,
        )

    require(
        meson_option_is_default_off(options, "goodix550c_volatile_init"),
        "Meson volatile-init option is missing or not default-off",
        failures,
    )
    require(
        meson_option_is_default_off(options, "goodix550c_manual_fdt_poll"),
        "Meson manual-FDT option is missing or not default-off",
        failures,
    )
    require(
        "-DGOODIX550C_ENABLE_MANUAL_FDT_POLL=1" in lib_meson,
        "Meson manual-FDT opt-in does not enable the compile-time gate",
        failures,
    )
    require(
        "-DGOODIX550C_ENABLE_VOLATILE_INIT=1" in lib_meson,
        "Meson opt-in does not enable the compile-time gate",
        failures,
    )
    require("'goodix53x5' : [ 'openssl' ]" in root_meson, "OpenSSL helper missing", failures)

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver-tree", type=Path, required=True)
    parser.add_argument("--libfprint-tree", type=Path, required=True)
    args = parser.parse_args(argv)

    failures = audit(args.driver_tree.resolve(), args.libfprint_tree.resolve())
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1

    print("Goodix 550c fail-closed policy audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
