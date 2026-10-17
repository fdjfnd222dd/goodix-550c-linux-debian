# Goodix 27c6:550c Linux enablement

This is the living engineering record for enabling the Goodix fingerprint reader in
this Lenovo Yoga 9 14IAP7 (`82LU`) on Linux. The reader is an image sensor using a
vendor protocol and a TLS-PSK-protected image channel; it is not a Goodix MOC device.

## Non-negotiable operating constraints

- Do not reboot, power off, suspend, cold-boot, or stop/restart existing services until
  the owner explicitly permits it.
- Create and modify files only below this repository. The repository-local read-only
  Windows evidence bind is currently not mounted and must not be replaced by direct
  access to a writable source volume.
- Never print, copy into logs, or commit `.env`, a plaintext PSK, Windows biometric
  templates, fingerprint images, or proprietary driver/firmware binaries.
- Never detach an active kernel driver or displace a process holding the USB node.
- Firmware erase/write, PSK/production write, and automatic "self-heal" are
  unconditionally denied in the isolated driver. Sensor-register writes,
  configuration upload, and MCU/USB reset are volatile operations and require both
  an explicit build option and `GOODIX550C_ALLOW_VOLATILE_INIT=1` at runtime.

No service has been stopped or restarted, and no host reboot, power-off, suspend, or
cold boot has been performed. A bounded live driver open has performed the expected
sensor-only USB/MCU reset and volatile RAM configuration; it completed and closed
cleanly.

## Host and hardware baseline (2026-08-11)

| Item | Observed value |
|---|---|
| Computer | Lenovo Yoga 9 14IAP7, machine type `82LU` |
| BIOS | `HNCN51WW` |
| OS | Ubuntu 26.04 LTS, x86-64 |
| Kernel | `7.0.0-29-generic` |
| Fingerprint USB ID | `27c6:550c` (`Goodix FingerPrint`) |
| USB location | bus 003, port path `3-6` |
| Interface | 0, vendor class `ff/00/00` |
| Endpoints | bulk OUT `0x01`, bulk IN `0x83`, 64-byte packets |
| USB link/power | full speed 12 Mbit/s, 100 mA |
| Bound kernel driver | none |
| Initial power state | runtime-autosuspended; unchanged |
| Installed userspace | `fprintd 1.94.5-4`, `libfprint 1.95.1+tod1` |
| Initial fprintd state | installed, inactive; `No devices available` |

## Confirmed device identity

A purpose-built, fail-closed PyUSB probe claimed and released interface 0 without
detaching a driver, resetting USB, selecting a configuration, or changing persistent
state. It sent only allow-listed read requests.

| Query | Result |
|---|---|
| Application firmware | `GF5288_GM168SEC_APP_13021` |
| Chip ID after volatile initialization | `0x00220ca1` |
| OTP | 32-byte value returned; raw value retained only in an ignored local transcript |
| Live PSK hash slot `0xbb020001` | a 32-byte non-default hash; not the public all-zero PSK hash |
| Pre-initialization chip query | exact five-byte register request ACKed and returned `00000000`; the later gated driver initialization read the useful ID above |
| IAP version | request timed out; not retried |
| Windows DPAPI PSK backup | slot `0xbb010002` returned exactly 324 bytes; standard DPAPI header validated |

The existing Windows-provisioned PSK remains active. Nothing has been erased,
reprovisioned, or reflashed.

The sealed backup is stored at `research/secrets/psk-dpapi.bin`, mode `0600`, and
ignored by Git. Its SHA-256 is
`8f6fabf5c0e461fbd7c051a501f93f586508132e94f9f7571a1826fe1f33bd05`.
This digest documents acquisition integrity without revealing the encrypted blob.

Local ignored transcripts are under `research/artifacts/`. They deliberately do not
enter Git because OTP data and PSK metadata are device-specific.

## Original Windows driver evidence

Static, read-only inspection of the original Windows 11 partition found the
model-specific Goodix package in the DriverStore. The temporary project-local
read-only bind used for that work is currently not mounted:

```text
Windows/System32/DriverStore/FileRepository/wbdiusb.inf_amd64_68affe4a1d2ed8cb
```

- Driver version: `3.0.550.180`, for `USB\\VID_27C6&PID_550C`
- Architecture: a UMDF/WinUSB userspace driver (`Wbdi.dll`), not a Goodix kernel `.sys`
- Embedded application identity: `GF5288_GM168SEC_APP_13021`
- Embedded IAP identity: `MILAN_GM168SEC_IAP_10007`
- Secure channel string: `TLS-PSK-WITH-AES-128-CBC-SHA256`
- Relevant static symbols include `McuGetFirmwareVersion`, `McuStartTls`,
  `PresetPskReadG`, `McuEraseApp`, and `McuUpdateApp`.

The isolated driver's 256-byte `default_config` matches the original `.180`
`Wbdi.dll` byte-for-byte at corrected file offset `0x127c50` (zero differing bytes,
SHA-256 `fe90fe662355096c9235b6fdaee422a5739966268fd36a943fd19dd366ee0e3d`).

Hashes of the locally installed, unmodified components:

| Component | SHA-256 |
|---|---|
| `Wbdi.dll` | `e0996e4976078ed7a0ac9c85ad0464e2ec794e4a976447b26ea24d2ccb7ba79a` |
| `GoodixEngineAdapter.dll` | `489a211be2c607518697a00722d1460e85550f73d4b2263783c0542331b95d85` |
| `SessionService.exe` | `148afe8333095138d7afa15ed6514fe19e9f982902e1e82a5279132814f3b579` |
| `WbdiUsb.inf` | `d2c009fec6435523cc08a779b41a73a93b233d2f03e401000bb0060563ddb1da` |
| `wbdiusb.cat` | `a4703f1648d09dbc9632c668a1840162812a05ef53c81c6f9571e595905ab088` |

No Windows biometric templates, `goodix.dat`, or opaque ProgramData log contents are
copied into this repository.

## Exact protocol

The executable open-source 550c implementation and our successful replies agree on
this framing:

```text
inner = command:u8 || length(payload + checksum):u16le || payload || checksum:u8
checksum = (0xaa - sum(command, both length bytes, payload)) & 0xff

outer = flag:u8 || length(inner):u16le || header_checksum:u8 || inner
header_checksum = (flag + length_low + length_high) & 0xff
```

Normal messages use flag `0xa0`; TLS handshake records use `0xb0`; TLS application and
image records use `0xb2`. Host writes are zero-padded to a 64-byte USB transfer.

Read-only requests exposed by the Python probe are exact `(command, payload)` pairs,
not arbitrary opcodes. Its hard-deny set includes at minimum PSK write `0xe0`, app
erase `0xa4`, firmware write/check `0xf0`/`0xf4`, sensor write `0x80`, config upload
`0x90`, and reset `0xa2`. The isolated libfprint transport independently and
unconditionally denies app erase, PSK/production write, and firmware write/check;
its reset/register/config path is available only through the double volatile gate.

## Existing upstream work and risk assessment

- Upstream libfprint currently lists `27c6:550c` as known unsupported.
- `goodix-fp-dump` at pinned commit
  `cc43bb3b3154a0bccc0412ae024013c7e1923139` has no 550c runner. Its 55x4 code is
  for GF3268 and may erase/reflash automatically; it must not be adapted by PID swap.
- `brianporeilly/goodix-550c-driver` at pinned commit
  `a3de5a1b6174ace5db0bb2a8796c5be6e55428f0` is an exact experimental GF5288
  libfprint driver. Its author reports working TLS capture, SIGFM enrollment,
  verification, and fprintd on firmware 13022.
- That fork has no release and little independent review. Its open path can
  automatically erase, reprovision, flash, reset, and re-enumerate a sensor after a
  TLS failure if it finds firmware. It is never run or installed unmodified here.
- Its suggested firmware is a newer 14IRP8 `13022` image. This machine has the
  original 14IAP7 `13021`; cross-flashing is not an acceptable rollback plan.
- Firmware read (`0xf2`) reportedly cannot back up this device. Incorrect write
  chunking can wedge USB until a physical cold boot, which is currently forbidden.

## Safest path to a working driver

Windows generated a random 32-byte live PSK and stored two sensor records:

- `0xbb010003`: the live PSK encoded as a vendor white-box;
- `0xbb010002`: a 324-byte machine-bound LocalSystem DPAPI backup blob ignored by
  the sensor.

The latter was read without mutation and unsealed using the matching Windows machine
secrets. This preserved both the current firmware and Windows Hello compatibility.
Reprovisioning to a public all-zero PSK would require erasing and reflashing the
sensor and remains prohibited.

The captured blob has `DPAPI_BLOB.Flags = 0`; that serialized field does not prove
the original `CryptProtectData` scope. Its master-key GUID resolves specifically to
`Windows/System32/Microsoft/Protect/S-1-5-18/User`, whose master key decrypts only
with `DPAPI_SYSTEM.UserKey`. The recovery tool binds each LocalSystem namespace to
its corresponding DPAPI_SYSTEM key and never falls back across keys or to another
user SID. Final correctness and freshness come from matching `SHA256(plaintext PSK)`
to the independently read live hash slot `0xbb020001`.

Offline recovery is implemented in `scripts/recover_windows_dpapi_psk.py`. It:

1. requires the Windows source to be on a read-only mount;
2. replaces Impacket's unnecessary registry `r+b` open with an `rb`-only parser;
3. reads only SYSTEM boot-key material and SECURITY's `DPAPI_SYSTEM` LSA secret;
4. validates raw or framed E4 input as slot `0xbb010002`, exactly 324 bytes;
5. verifies DPAPI integrity, a 32-byte plaintext, and the live hash oracle;
6. prints no key and, only when requested, writes a non-overwriting mode-`0600` hex
   file directly below the ignored `research/secrets/` directory.

The non-mutating commands are:

```bash
.venv/bin/python scripts/recover_windows_dpapi_psk.py --preflight
.venv/bin/python scripts/recover_windows_dpapi_psk.py
```

An explicit repository-local output can be requested with:

```bash
.venv/bin/python scripts/recover_windows_dpapi_psk.py \
  --output research/secrets/goodix550c.psk
```

The independent recovery run completed successfully: DPAPI integrity passed and the
32-byte plaintext's SHA-256 matched the live sensor hash oracle. No key material was
printed. `research/secrets/goodix550c.psk` is a 65-byte lowercase-hex-plus-newline
file, owned by the operator, mode `0600`, and ignored by Git.

## Fail-closed libfprint port

The tracked patch series integrates exact experimental driver commit
`a3de5a1b6174ace5db0bb2a8796c5be6e55428f0` into pristine libfprint tag
`v1.94.10` (`0c97a47d8ef405cd577b87058c1e89cae9d242e7`). The build script archives both
pinned trees, applies the patches, audits the resulting compiled source, and builds
only the `goodix53x5` driver below `build/`.

The ignored upstream trees are reproducibly obtained with
`scripts/fetch_upstream_sources.sh`. It depth-fetches and verifies only the public
Goodix repository commit above and libfprint tag `v1.94.10` commit
`0c97a47d8ef405cd577b87058c1e89cae9d242e7`; `--offline` validates existing origins
and commit objects. Both build pipelines give this exact setup command if an input
clone is absent, then independently reject a revision mismatch.

The resulting policy is fail-closed:

- The USB ID table contains only `27c6:550c`, interface 0, OUT `0x01`, IN `0x83`.
- Firmware must be exactly `GF5288_GM168SEC_APP_13021` before the MCU reset state.
- Exactly one explicit `GOODIX550C_PSK` or absolute `GOODIX550C_PSK_FILE` is
  required. A file is opened with `O_NOFOLLOW`, then checked/read through that
  descriptor; it must be regular, single-link, owned by the effective UID, and
  mode `0600`.
- Parsed key text and both transient and long-lived key buffers are cleansed; the
  key is never logged.
- TLS is restricted to `PSK-AES128-CBC-SHA256` and observed identity
  `Client_identity`.
- Firmware-loader/self-heal sources are excluded, their calls are compile-disabled,
  and persistent opcodes are denied again in the transport.
- USB interface claim uses flags `0`: it never auto-detaches or rebinds a kernel
  driver.
- Volatile USB/MCU reset, register/config writes, and FDT setup require Meson's
  default-off `goodix550c_volatile_init=true` plus the runtime value
  `GOODIX550C_ALLOW_VOLATILE_INIT=1`.
- Firmware-13021 manual FDT polling independently requires Meson's default-off
  `goodix550c_manual_fdt_poll=true` plus exact runtime value
  `GOODIX550C_ALLOW_MANUAL_FDT_POLL=1`. The gate is TLS-PSK-only; the non-TLS
  asynchronous flow is unchanged.

Installed build prerequisites on this host are `libgusb-dev`,
`libopencv-core-dev`, `libopencv-features2d-dev`, `libopencv-flann-dev`, and
`libopencv-imgproc-dev` plus their dependencies. Apt made no upgrades or removals
and restarted no services.

The clean isolated build completed without installation. A minimal harness then
loaded the build-tree library, found the sole exact-ID device, completed the TLS
handshake and volatile initialization with the recovered live PSK, and closed it
cleanly. No persistent command was sent. The generic libfprint raw-capture API is
intentionally not advertised; scans are consumed through enrollment/authentication.

System installation, PAM changes, and service-integrated physical testing remain
outside the current authorization. The external TOD module described below avoids
replacing Ubuntu's core libfprint, but installing it would still write outside this
repository. Any later PAM rollout must retain password authentication, prove
repeated positive and negative matches first, and must not make fingerprint the sole
administrator or disk-unlock credential.

## Ubuntu 26.04 external TOD module

The safest path from the working isolated 1.94.10 build to Ubuntu's installed stack
is an external TOD module, not an older core-library replacement. The installed
versions are exactly:

```text
fprintd:             1.94.5-4
libfprint-2-2:       1:1.95.1+tod1-0ubuntu2
libfprint-2-tod1:    1:1.95.1+tod1-0ubuntu2
architecture:        amd64
```

The exact fprintd binary imports 47 public libfprint symbols, all from
`LIBFPRINT_2.0.0`; the old isolated library happens to provide them. That narrow
compatibility is not a deployment justification. The old library omits Ubuntu's
SDCP addition, TOD loader, and other drivers. Conversely, libfprint's private driver
layouts changed in 1.95.1: `FpIdEntry`, `FpDeviceClass`, and `FpiUsbTransfer` have
TOD-specific layout/padding changes. Reusing 1.94.10 objects would therefore be
unsafe even though fprintd's public imports resolve.

Ubuntu's core loader honors `FP_TOD_DRIVERS_DIR`, opens regular `lib*.so` modules,
looks up `fpi_tod_shared_driver_get_type`, and verifies the returned GType derives
from `FpDevice`. The project now builds that interface from source using:

- the pinned driver commit and ordered `driver-series` patches `0001`, `0003`,
  `0004`, and `0005`;
- exactly 32 allowlisted upstream files: 13 C units, 15 Goodix headers, one SIGFM
  C++ unit, and three SIGFM headers;
- one tracked registration wrapper;
- Ubuntu's exact 1.95.1+tod1 public and TOD-private headers; and
- explicit links to installed SONAMEs `libfprint-2.so.2` and
  `libfprint-2-tod.so.1` with undefined references forbidden.

Patch `0004` keeps firmware-13021's TLS FDT-down setup as the raw generated
24-byte base. Non-TLS FDT-down, FDT-up, and manual FDT retain their prefixed payload
builder. In addition to the compiled-source audit, the isolated build compiles the
patched production `goodix53x5-commands.c` and `goodix53x5-proto.c` into a native
offline regression. Its test-only seam replaces only transport submission with an
in-memory capture, then proves the TLS branch supplies the dynamic raw 24-byte base
to the real encoder and produces the complete known 32-byte `0xa0` frame. It also
proves the sibling branch remains prefixed. The verifier checks the post-ACK
event-read diagnostic; this protocol correction has not been exercised against USB
as part of the TOD work.

### Firmware-13021 manual FDT fallback

The corrected raw-24-byte FDT-down request received an exact two-byte ACK with
acknowledged command `0x32` and flags `0x01`. It still produced no asynchronous
event for more than 15 seconds when the correct keyboard-pad sensor was held before
the command. Flag `0x02` was not set, so a missing configuration does not explain
that observation. Because the flag's general meaning is not established, patch
`0005` records only a rate-limited numeric diagnostic under the experimental gate
and does not reject it.

Patch `0005` supplies a firmware-13021 TLS-PSK fallback with two independent
opt-ins. Every poll is one complete bounded manual TX-on request/ACK/data
transaction; cancellation is checked before and after the transaction and during
the 100 ms delayed states. A cancellation can therefore wait for the current
bounded command, but cannot leave an unread partial response to poison the next
command.

Only the 24 raw FDT bytes after the four-byte protocol header are compared, and
only against an in-memory baseline. The thresholds remain the sensor's decoded OTP
values—there are no fixed public thresholds. The state machine enforces:

- two fresh readings stable within `delta_fdt` before the reference image;
- a second two-reading stability check after image mode is disabled, followed by
  an in-memory raw and encoded baseline refresh;
- two consecutive readings outside `delta_down` before finger-down;
- two consecutive readings back within `delta_up` before finger-up, then another
  baseline refresh and sensor sleep; and
- streak reset when the classification changes.

The first guided manual build safely stopped during open because firmware 13021
reported a nonzero manual touch flag while the operator's hands were fully clear.
No enrollment began. That live evidence invalidated the touch-flag-as-contact
assumption. The revised patch ignores those two header bytes for manual baseline,
down, and up classification and relies only on consecutive raw-reading stability.
For this guided experiment, the operator must keep the pad fully clear throughout
open and both reference-baseline phases. The machine must remain awake; suspend and
reboot are outside the experiment.

Every phase that waits for a *clear* pad carries a poll budget and fails the action
when it is spent: 100 polls (10 s) for each reference-baseline phase and 600 polls
(60 s) for finger-up. Without those budgets an unstable or contacted pad polls the
sensor every 100 ms forever, and the action neither completes nor errors — the
operator is not asked for contact in those phases, so nothing would ever break the
loop but an external cancel. The degenerate case matters here: `delta_fdt` is 0
whenever the decoded OTP reports no spread, and the comparison uses a strict
`>`, so stability then means two bit-identical 24-byte readings. The equivalent
upstream open-time check bounds itself with `GOODIX_OPEN_FDT_MAX_RETRIES = 2` for
the same reason. Only the finger-down wait polls without a bound, matching the
asynchronous event path it replaces; cancellation ends it.

Suspend is refused while a poll owns the device. The manual path never arms a
cancellable blocking read, so `blocking_ssm` stays `NULL` for the whole finger
wait, and the pre-existing "not in a blocking read" branch of
`goodix_session_suspend` would report a clean suspend while the delayed SSM kept
issuing bounded USB transactions until the machine actually slept. A
`manual_fdt_poll_active` flag, set when a poll state is attached to its SSM and
cleared by that state's destructor on every exit including failure and
cancellation, now makes that branch return `FP_DEVICE_ERROR_NOT_SUPPORTED`
instead. `needs_reinit` is still set first, so the in-flight action fails at its
next cancellation check.

The polling logs only phase transitions, candidate booleans, consecutive counts,
and bounded poll counts. It neither logs nor saves raw readings, touch masks,
deltas, per-channel counts, fingerprint images, or templates. Persistent-command
denial is unchanged. The revised isolated build passed at
`build/goodix550c-13021-manual-fdt-v7/builddir`; the matching TOD source/ABI build
passed at `build/goodix550c-tod-manual-fdt-v3/builddir`.

The only intentional exported function is the TOD registration entry point. A
linker version script localizes the driver and C++ implementation symbols. The ABI
audit verifies ELF64/amd64, both exact libfprint SONAME dependencies, absence of
RPATH/RUNPATH, non-executable stack, stack protector, FORTIFY, full
RELRO/BIND_NOW, the restricted export surface, all 37 `fp_*`/`fpi_*` imports against
the installed core/TOD exports, the `LIBFPRINT_TOD_1_1.95.1` version node, and the
Meson/compile-command state of both experimental gates. Build metadata records only
project-relative source names and content hashes, not checkout-specific paths.

### Pinned project-local SDK

`scripts/fetch_ubuntu_tod_sdk.sh` downloads over HTTPS, verifies metadata and
SHA-256, and extracts only below `build/` (or an explicitly selected project-local
`research/` directory). The exact development inputs are:

| Package | SHA-256 |
|---|---|
| `libfprint-2-dev_1.95.1+tod1-0ubuntu2_amd64.deb` | `db01d591d13f81312d618d2e247ceed66d72ee42cd07130b19637425df32ee28` |
| `libfprint-2-tod-dev_1.95.1+tod1-0ubuntu2_amd64.deb` | `d1f99081a0d314b7416bdc9d5d70bea47237787dea946a95d8de3e21bb0b8b91` |

The `--offline` fetch mode and build script's `--offline-sdk` mode refuse network
access unless those verified files are already cached. Nothing is installed with
apt or Meson.

The reproducible default-off build command is:

```bash
scripts/build_goodix550c_tod_module.sh \
  --offline-sdk \
  --stage-dir build/goodix550c-tod-default-off
```

Two clean builds in differently named stage directories produced identical
module and installed-runtime harness bytes:

```text
module:  d2c473c98b47bae29fceed2532002d8cccbd6d8911a495de8dc1b293401abd5a
harness: bf0f4e6d079f636a77182f1ad4140ff0b77a93d4b5ddf93537dc6176071dfc66
```

These digests cover the full `driver-series` including the bounded revision of
patch `0005`, whose manual-FDT source is present but compile-gated off in a
default-off build. Any change to that series changes the module digest.

The source-policy audit, ELF ABI audit, and paired offline TLS policy test all
passed. Compilation retains a small set of upstream unused-parameter and signedness
warnings; there were no link errors or unresolved libfprint references.

### No-USB private-fprintd validation

The private smoke test does not rely on private D-Bus alone, because constructing an
`FpContext` normally enumerates GUsb. `scripts/smoke_goodix550c_tod_fprintd.sh`
starts a non-activating private bus and the installed daemon directly inside
bubblewrap. The sandbox uses a new `/dev`, empty `/sys`, `/run`, and `/tmp`, a
read-only host root, and an empty tmpfs over the checkout's normal path. It rebinds
only the dedicated run directory at `/run/goodix550c-tod-smoke`; `.env` and
`research/secrets` are therefore absent, and the script asserts that absence along
with `/dev/bus/usb`, `/sys/bus/usb/devices`, and `/run/udev`. The environment is
rebuilt from empty. Cleanup signals a recorded child only while Bash still owns the
job and `/proc` confirms the original parent, start time, and expected executable;
this closes the numeric-PID reuse race. No service-manager command is present.

The final smoke result was:

```text
installed core:       Initializing FpContext (libfprint version 1.95.1+tod1)
TOD loader:           opened project-local libgoodix550c.so
registered driver:    goodix53x5 (Goodix HTK32 Fingerprint Sensor)
private GetDevices:   (@ao [],)
```

The private bus intentionally has no logind activation entry, so fprintd logs a
nonfatal missing-inhibitor warning. This validation proves loader ABI, GType
registration, daemon construction, storage redirection, and D-Bus export. It cannot
prove physical open, capture, enrollment, production systemd sandbox behavior, or
PAM integration. The TOD private ABI is not generally stable, so the current module
must remain pinned to the exact Ubuntu package release and be rebuilt/revalidated
after any libfprint update.

### Guarded installed-runtime physical harness

The TOD build also compiles `tools/goodix550c_tod_open_close.c` against the pinned
project-local Ubuntu headers and links it directly to the installed
`libfprint-2.so.2` and `libfprint-2-tod.so.1`. The ELF audit requires an amd64 PIE,
both SONAME dependencies, immediate relocation binding, the expected public
open/close calls, and no RPATH/RUNPATH. It therefore exercises Ubuntu's installed
core/TOD loader rather than the isolated 1.94.10 build.

The live module remains default-off. A separately named stage must be built with
both the compile-time opt-in and the normal offline SDK verification:

```bash
scripts/build_goodix550c_tod_module.sh \
  --offline-sdk \
  --allow-volatile-init \
  --allow-manual-fdt-poll \
  --stage-dir build/goodix550c-tod-manual-fdt-v3
```

`scripts/run_goodix550c_tod_open_close.sh` requires all of the following before it
runs the harness:

- root execution and an explicit `--allow-volatile-init` acknowledgement.
  `--allow-manual-fdt-poll` is accepted but optional, because open/close reaches
  no manual-FDT state; the runtime gate is exported only when that flag is given,
  so a control run against a manual-FDT stage stays possible;
- a non-symlink module, harness, metadata, source-checksum manifest, PSK, and
  live-hash oracle below the project; exact build metadata; matching
  module/harness SHA-256 values; and unchanged tracked build inputs;
- the pinned amd64 Ubuntu core/TOD package versions and a fresh source/ELF audit;
- a root-owned, mode-0600, single-link 32-byte key whose SHA-256 matches the
  independent live sensor oracle, compared without printing either value;
- exactly one `27c6:550c`, interface 0, only 64-byte bulk OUT `0x01` and IN `0x83`,
  with no kernel driver and no process holding its USB node; and
- fprintd exactly inactive. Any other state causes refusal; the wrapper contains no
  service-stop or existing-process signal operation.

After those preconditions, an empty environment exposes only the build directory
to `FP_TOD_DRIVERS_DIR`, allowlists only `goodix53x5`, and supplies the file-based
PSK and runtime volatile gate. The initial USB reset is already protected by the
volatile opt-ins. After that reset and the firmware read, the driver requires exact
firmware `GF5288_GM168SEC_APP_13021` before MCU reset, register writes, or
configuration upload, and must complete PSK-TLS before the harness reports success.
HOME, TMP, and all XDG locations are private directories below project `build/`; a
45-second timeout applies only to the new harness child, and the wrapper exits with
that child's status. The per-run private directory is created with `mktemp -d`
under `build/` and removed by an EXIT trap that only accepts a path matching the
prefix this script created, so runs do not accumulate root-owned trees. The
harness itself rejects any `GOODIX550C_ALLOW_MANUAL_FDT_POLL` value other than
absent or exactly `1`. The later command is:

```bash
sudo chown root:root research/secrets/goodix550c.psk
sudo scripts/run_goodix550c_tod_open_close.sh \
  --stage-dir build/goodix550c-tod-manual-fdt-v3 \
  --psk-file research/secrets/goodix550c.psk \
  --expected-psk-hash research/artifacts/psk-hash-current.json \
  --allow-volatile-init
sudo chown "$USER:$USER" research/secrets/goodix550c.psk
```

That command needs no finger contact: the harness opens the device and closes it.
Manual-FDT polling, and therefore any finger-down wait, is reachable only from
enrollment or verification, which this repository has no harness for yet.

It installs nothing and cannot send the driver's compile-time-elided persistent
mutation commands.

#### Physical result (2026-08-13)

The guarded physical TOD open/close ran on this machine and passed, three
consecutive times:

```text
Goodix 550c TOD source and ABI audit passed
Preflight passed; opening only 27c6:550c through the project-local TOD module.
Exact firmware, PSK-TLS, and volatile TOD open succeeded.
Device closed cleanly through the installed Ubuntu TOD runtime.
```

This is the first physical validation through Ubuntu's *installed*
`libfprint 1.95.1+tod1` runtime rather than the isolated 1.94.10 build tree. The
pad was clear throughout; no finger, enrollment, or template was involved.

The first two attempts of that session failed identically, in both the TOD and the
isolated harness:

```text
Device open failed: TLS handshake failed: error:1C800066:Provider routines::cipher operation failed
```

The cause was stale sensor state, not code, key, or environment. Ruled out during
diagnosis: the PSK still matched (the live `psk-hash` response bytes were
byte-identical to the 2026-08-11 oracle capture), OpenSSL and libfprint had not
changed since 2026-08-09 — before the last successful run — and the offline paired
TLS test passed on the same OpenSSL 3.5.5 that failed against the device. The
sensor had been left mid-session by the failed manual-FDT experiment of 2026-08-11
and sat untouched for two days. One read-only `goodix550c identify psk-hash`
(protocol NOP/wake plus a read-only query, no TLS) cleared it, and every open since
has succeeded.

Operationally: if the handshake fails with a provider cipher error, run the
read-only identity probe once and retry before suspecting the key or the build.

### Guarded enrollment harness

`tools/goodix550c_tod_enroll.c` is the only harness that reaches the finger-wait
states. It is a capture test, not a provisioning tool: it opens the device, runs
`fp_device_enroll_sync`, reports per-stage progress and finger-status transitions,
then discards the template. Nothing is written, printed, or hashed, and the audit
rejects the harness if it references any serialization or file-writing call.

It is built by the same script into the same stage, with its own
`enroll_harness_sha256` metadata entry, and is selected through the existing
guarded wrapper rather than a second runner, so every preflight gate applies
unchanged:

```bash
sudo scripts/run_goodix550c_tod_open_close.sh \
  --stage-dir build/goodix550c-tod-manual-fdt-v4 \
  --psk-file research/secrets/goodix550c.psk \
  --expected-psk-hash research/artifacts/psk-hash-current.json \
  --allow-volatile-init \
  --allow-manual-fdt-poll \
  --enroll --debug
```

`--enroll` requires `--allow-manual-fdt-poll`, because on firmware 13021 the
finger-wait states depend on manual polling; the harness enforces the same
requirement itself. The enrollment bound is 240 s rather than the open/close 45 s.
`--debug` adds `G_MESSAGES_DEBUG=all` for driver diagnostics; it changes no device
behaviour and logs no key, raw reading, image, or template.

The 2026-08-13 stage (`build/goodix550c-tod-manual-fdt-v4`) produced module SHA-256
`60db0a107fac417141df33d3e1c0181bb3d107b0153882dddb3e6f7b22ecec51`, open/close
harness `bf0f4e6d079f636a77182f1ad4140ff0b77a93d4b5ddf93537dc6176071dfc66`, and
enrollment harness
`7c64e047bfcf37903a357b7a8d31d4ccea5639642678627e023852c86ef276ea`.

The 2026-08-14 stage (`build/goodix550c-tod-capture-diag`), carrying patches `0006`
and `0007` and the harness fixes, produced module SHA-256
`adf6e0146def342014a2a354987242b3d68aaa86dfbc4108cc67d4e0bca6c83f`, the same
open/close harness `bf0f4e6d079f636a77182f1ad4140ff0b77a93d4b5ddf93537dc6176071dfc66`,
and enrollment harness
`b2a0742fd6f30e72d708b5fa9b75a3d20c41ece07054d5f4eeb592af478919a7`.

#### Physical enrollment result (2026-08-13)

**The sensor read a fingerprint under Linux for the first time.** The manual-FDT
poll detected contact reliably on every placement, both reference baselines
confirmed after 2 polls each, and captured frames passed SIGFM feature extraction:

```text
Open succeeded. Enrollment needs 8 stage(s).
Manual FDT post-reference baseline confirmed after 2 polls
Manual FDT finger-down poll armed
Stage 1/8 captured.
```

This closes the firmware-13021 no-event question that blocked the project: the
guarded fallback works, and the earlier touch-flag assumption remains correctly
ignored.

Enrollment did not complete on that date. Both runs ended at the 240 s bound:

```text
run 1 (no debug):  4 of 8 stages captured, 36 rejections
run 2 (--debug):   2 of 8 stages captured,  4 rejections, 7 placements
```

Every rejection was `FP_DEVICE_RETRY_CENTER_FINGER` from the enrollment coverage
gate at `goodix53x5-enroll.c:100`, never the keypoint gate. With debug enabled the
gate reported its exact measurement:

```text
Enrollment stage rejected: 95.4% of frame has no finger contact (limit 10.0%)
```

`goodix_device_image_clipped_fraction` counts raw12 pixels at ADC full scale
(`GOODIX_RAW12_CLIP` 4095) across the 108x88 frame, so 95.4% means roughly 9,067 of
9,504 pixels are railed. `GOODIX_ENROLL_MAX_CLIPPED_FRACTION` is `0.10`.

The hypothesis recorded here was a capture-path state defect around image-readout
re-enable and reference re-acquisition. **That hypothesis was wrong.** It rested on
the rejections being bimodal at ~95.4%, which more data did not support. See the
next section.

#### Capture-path instrumentation and the real cause (2026-08-14)

Patch `0006` reports whole-frame scalars for every decoded reference and capture
frame under the experimental gate: minimum, maximum, mean, clipped fraction, a
32-bit checksum that distinguishes a fresh frame from a repeat, and the gap since
the previous readout. All figures are frame-global; per-region or per-channel
numbers would describe ridge positions, which the diagnostics policy forbids.

The instrumented runs killed the readout hypothesis outright:

- the reference frame is clean on **every** stage of every run — `clipped=0.0%`,
  `max` 2794..2929 against a 4095 rail. The readout path never returns a blank or
  stale frame; and
- the checksums differ on every frame, so no buffer is ever repeated.

The rejected capture frames were also not bimodal. Measured non-contact areas were
`38.6%`, `67.3%` and `87.2%` — a continuous spread, which is what genuine partial
contact looks like, not a stuck buffer. The earlier "bimodal, nothing in between"
reading came from too few samples.

The actual cause is in the manual-FDT fallback itself. Contact is declared on
`changed_pairs > 0`, a single FDT channel pair moving, which is the leading edge of
a finger still coming down; the capture then followed that edge by 78-80 ms in
every instrumented placement. The frame therefore recorded whatever fraction of the
pad had landed. Placements that happened to be already resting on the pad measured
`0.0%`; placements caught mid-landing measured 38-87%.

Patch `0007` holds `GOODIX_MANUAL_FDT_DOWN_SETTLE_MS` (300 ms) after contact is
confirmed, then captures. The settle window runs no command transaction, so no
reply can be stranded and cancellation is honoured directly. A finger withdrawn
during the window yields a frame the coverage gate rejects, which is what
withdrawing it a moment earlier already did.

#### Physical enrollment completed (2026-08-14)

**A full 8-stage enrollment succeeded.** Every stage passed on the first placement:

```text
capture stage=0  min=0 max=2404 mean=1567.5 clipped=0.0% sum=57f578bd
capture stage=1  min=0 max=2125 mean=1469.4 clipped=0.0% sum=0d248248
capture stage=2  min=0 max=2224 mean=1471.8 clipped=0.0% sum=17338a39
capture stage=3  min=0 max=2257 mean=1563.5 clipped=0.0% sum=79eeb4e2
capture stage=4  min=0 max=2216 mean=1485.9 clipped=0.0% sum=ee3d1a7d
capture stage=5  min=0 max=2176 mean=1461.6 clipped=0.0% sum=e7ed877f
capture stage=6  min=0 max=2295 mean=1544.5 clipped=0.0% sum=9f172400
capture stage=7  min=0 max=2248 mean=1600.2 clipped=0.0% sum=e9d49fa3
Enrollment complete with 8 samples
Enrollment completed; the template is discarded without being stored.
Device closed cleanly through the installed Ubuntu TOD runtime.
```

Zero rejections, eight distinct checksums, `EXIT=0`. The template was discarded; no
fingerprint data was written anywhere.

#### Two harness defects found by the same runs

Both were exposed by the poll budget added in `0005`, which produced the first runs
that returned normally instead of being killed by the wrapper timeout.

The finger-status callback printed `Finger detected; hold still` for the whole
finger-up wait — the opposite of what that phase needs — and printed the lift
prompt only after the device had already observed the finger gone, which is a
confirmation rather than an instruction. One run lost its 600-poll finger-up budget
to that. The lift prompt now comes from the stage callback, which is what actually
ends a stage.

The harness also crashed with `SIGSEGV` inside `OPENSSL_cleanup` during
`__run_exit_handlers`. The faulting thread was created after the first successful
capture and its instruction pointer fell in no mapped region, so global teardown had
unmapped code it was still executing. The module links OpenCV, whose worker pool is
created lazily by SIGFM extraction and exposes no join API. The harness now flushes
and calls `_exit` after the device is closed, so global destructors never run beside
those threads.

#### Verification harness and result (2026-08-14)

`tools/goodix550c_tod_verify.c` answers the next question: does a template this
driver enrolls actually match the finger that produced it, and reject one that did
not. It enrolls, holds the template **in process memory only**, and runs match
trials against it. Neither the template nor any scanned print is serialized,
written, printed, or hashed. It is selected with `--verify` through the same guarded
wrapper, requires the same manual-FDT acknowledgement, and is bounded at 420 s.

Two of its three trials use the enrolled finger and one uses a different finger. A
positive-only test would pass just as well against a driver that matched
everything, so the rejection trial is what gives the result meaning; the audit
requires it to exist. Retry-class errors re-prompt rather than consuming a trial,
because this driver also raises `FP_DEVICE_RETRY_REMOVE_FINGER` for a capture with
too few SIFT keypoints.

**The first verification of a session matches correctly.** `Trial 1/3 result: MATCH
(expected MATCH)` on both runs, from a clean capture (`clipped=0.0%`).

**Every later verification in the same session fails**, and not on the match: the
device stops answering image requests.

```text
trial 1  reference max=2914 mean=2359.5   capture clipped=0.0%   -> MATCH
trial 2  reference max=46   mean=0.0      capture clipped=95.2%  -> retry
trial 3  reference max=0    mean=0.0      capture clipped=95.2%  -> retry
```

Two observations constrain the cause:

- the sleep command is not it. The enrollment loop reaches
  `GOODIX_FINGER_UP_SLEEP` after every one of its eight stages and its next
  reference frame is clean, so the difference is the deactivation exit path that
  only verification and identification reach; and
- the failing captures report `mean=4012.1` and `clipped=95.2%` **identically**
  across four attempts, two runs and two fingers, but with four different
  checksums. The same pixel histogram in a different arrangement is not a sensor
  reading a finger; it points at a misaligned or stale payload, that is, read
  desynchronization rather than a dead sensor.

A patch that marked the device as needing reinitialization after deactivation was
written, measured, and **discarded**: the reinit fires and re-runs the whole open
sequence including the USB reset, and the frames stay dead. It cost a full re-open
per verification and fixed nothing, so it is not in the series. The remaining
suspect is an unconsumed reply left queued after the first action, which would
shift every later read by one transaction; `goodix_cmd_set_sleep_mode` requests no
data reply, and the 550c is already known to answer at least one other command with
an unrequested data reply (see `goodix_cmd_reset_sensor`).

#### Desynchronization probe and the shutdown-completion result (2026-08-14)

Reproducing the post-action failure with the verification harness costs a full
eight-stage enrollment plus match trials. `tools/goodix550c_tod_desync_probe.c`
reaches the capture path with identification actions against an **empty gallery** —
one placement each, nothing enrolled, matched, or stored.

Patch `0008` reports the pack flag and byte counts of every assembled reply under
the same experimental gate. Only framing metadata is logged; no payload is, and an
image reply is still encrypted at that point.

**Read desynchronization is ruled out.** Across the action boundary into a dead
reference frame, the framing is exactly that of a healthy read:

```text
Reply framing: pack flag=0xb2 payload=14334 assembled=14338
reference frame  min=0 max=0 mean=0.0 sum=00000000
```

Right pack type, right length, no shift, no stale reply. The sensor returns a
properly framed, correctly decrypted image that is entirely zeros.

**What actually leaves the sensor dead is a shutdown that does not complete.** The
finger-up wait is bounded at 600 polls; when the operator holds past it, the SSM
fails and the sensor is left mid-sequence without its sleep:

```text
SSM GOODIX_FINGER_UP_NUM_STATES failed in state 7 with error:
  Manual-FDT finger-up did not settle within 600 polls
-> next action reference frame max=0
```

With the lift cued at the right moment the same path completes and the next action
reads a clean reference frame (`max=2917 mean=2363.0 clipped=0.0%`). That was
measured both ways.

Two earlier readings were wrong and are recorded as such. Sleep is not the trigger:
the open sequence ends with `GOODIX_OPEN_SLEEP`, the same command, and the next
action is fine. Deactivation alone is not established either: the one observation
behind that idea (a matching verification followed by a dead frame) has not been
reproduced, and the probe cannot reach deactivation at all, because
`verify_wait_finger_up` is cleared only by a successful match or an unusable
template and an empty gallery yields neither. A patch arming the FDT before the
deactivation sleep was written and **dropped unvalidated** for that reason, as was
an earlier patch marking the device for reinitialization after deactivation, which
was measured and did not help.

#### Operator cue timing is part of the driver contract

Both harnesses issue the lift instruction from the callback that fires when a
result is known — `on_enroll_progress` for a stage, `on_match_reported` for a
match — never from the call's return path. The return happens *after* the bounded
finger-up wait, so a lift cued there arrives after the wait it is meant to satisfy,
and the shutdown then aborts on a spent budget and leaves the sensor unreadable for
the next action. This is not cosmetic: it produced three separate failed runs before
it was understood.

#### Verification result (2026-08-14)

With that fixed, a full run completes cleanly end to end — eight enrollment stages,
three trials, every trial returning a verdict, the device closed cleanly, and no
dead frames anywhere in the session. **Matching, however, failed:**

```text
Trial 1 (same finger)       no match   SIGFM best score 1   (threshold 150)
Trial 2 (same finger)       no match   SIGFM best score 8
Trial 3 (different finger)  no match   SIGFM best score 0
Verification summary: 3/3 trials returned a verdict, 0 matched, 2 expected
```

Scores of 1 and 8 against a 150 threshold are not near misses; the probe and the
template share essentially no features. An earlier run did return
`Trial 1/3 result: MATCH`, so the pipeline can match, and the capture frames give no
hint as to the difference — enrollment and trial images sit in the same range
(`mean` 1490-1600, every frame `clipped=0.0%`). This is unexplained and is the
current work item.

Because every trial scored near zero, trial 3's correct rejection carries no
information about discrimination. **No claim is made about false accepts.**

#### Live fprintd session result (2026-08-14)

Two fingers were enrolled and verified through the windowed session. **Both matched
on the first attempt, with margins that are not marginal:**

```text
right index  Verify best SIGFM score: 3189   (threshold 150)
right thumb  Verify best SIGFM score: 44974  (threshold 150)
```

The session also produced 19 rejected enrolment stages, and their distribution
corrected a natural misreading. The operator saw repeated "finger was not centered"
messages while enrolling the index finger and concluded that the smaller finger was
covering too little of the pad. The measurements say otherwise:

```text
18 stages rejected at 95.1% - 95.3% non-contact
 1 stage  rejected at 25.6% non-contact
```

Only the 25.6% frame was a placement fault. A frame at 95% holds no contact at all:
the finger had already left the pad when the image was read, which is the same
figure this project has measured across sessions and across fingers. Every one of
them nonetheless told the operator to centre their finger.

Patch `0010` reports the two separately. Above `GOODIX_ENROLL_NO_CONTACT_FRACTION`
(0.90) the retry becomes `FP_DEVICE_RETRY_TOO_SHORT`, which asks for a longer hold;
below it the existing centre-the-finger retry is unchanged. The coverage gate itself
is deliberately not moved: the frames it rejects are unusable either way.

#### Blackout onset and what absorbs it (2026-08-14)

The intermittent capture failure has a clear onset. An identification completed
at 14:27:50.685, ending through the finger-up sub-SSM and its sleep:

```text
Manual FDT finger-up confirmed after 7 polls
GOODIX_FINGER_UP_NUM_STATES entering state 3    (sleep)
Device reported identify completion
```

The next action began about two seconds later and read empty reference frames
from 14:27:53 until 14:28:04 — seventeen of them — then recovered on its own and
stayed healthy for the rest of the session, through two full enrolments and a
match scoring 6448582.

So the sensor stops producing frames after an action that ends in sleep, and
returns after roughly eleven seconds. **The cause is still unknown.** Three
explanations have been measured and discarded, and are recorded here so they are
not retried:

- the sleep command alone: the open sequence ends with `GOODIX_OPEN_SLEEP`, the
  same command, and the next action reads a clean frame;
- reinitialisation afterwards: it re-runs the whole open sequence including the
  USB reset, and the frames stay empty; and
- read desynchronisation: reply framing across the boundary is byte-for-byte
  that of a healthy read (`pack flag=0xb2 payload=14334 assembled=14338`).

What is fixed is the damage. Patch `0011` refuses an empty reference frame
rather than storing it, and patch `0012` sizes the retry to the measured
blackout: the first attempt used eight retries a tenth of a second apart, about
one second against an eleven-second fault, so seventeen empty frames were caught
but five actions still failed. Sixty attempts a quarter of a second apart covers
about fifteen seconds, which turns a blackout into a wait rather than a refusal.
That is the right trade for an authenticator, because the alternative is turning
away an operator who did nothing wrong.

#### The trigger fires once per enrollment stage

The enrollment loop runs a finger-up wait between stages, and that wait ends with
`GOODIX_FINGER_UP_SLEEP`. The next stage reads its reference frame 350ms later.
Since the blackout follows a sleep, the trigger therefore fires once per stage
rather than once per action, which is why enrollment saw so many empty frames: a
three-finger session logged 25 of them.

The operator noticed the same thing from the outside without seeing any of this,
reporting that pausing before re-placing a finger made stages register. That is
what waiting out the recovery looks like.

Patch `0013` stops sleeping between stages. The sleep still happens on the last
stage and at the end of verification, where the action really is ending; only the
inter-stage case is skipped, and the flag is consumed where it is read so it
cannot leak into a later action. This removes the trigger from the enrollment path
rather than absorbing it.

Back-to-back actions still meet the blackout, and there the retry budget from
`0012` absorbs it as a wait.

#### Session isolation

The windowed session spans two accounts by necessity: the daemon needs root for
USB, and the window belongs to the desktop user. Its D-Bus socket is therefore
owned by the desktop user with the group set to root and mode `0660`, inside a
directory at `0710` with the same ownership, so exactly those two reach it and no
other account does. The daemon is admitted through the group rather than by
granting the sandbox `CAP_DAC_OVERRIDE`, which bubblewrap drops. The socket lives
for one session only and carries no secret: the PSK reaches the driver by file and
environment, never over the bus.

#### Operator note

Prompt timing matters more than technique. The driver waits for contact to settle,
so a normal resting placement is enough; there is no need to press hard or hold for
several seconds. But each stage must be followed by a prompt lift: the finger-up
wait is bounded at 600 polls (60 s), and a stage that is held past it fails the
whole enrollment.

### Measured verification latency

The retry budget from `0012` is sized for a fifteen-second worst case, but that is
the ceiling, not the cost. Measured from the `VerifyStart` authorization to the
reported score across the three-finger session:

```text
15:18:29.691 -> 15:18:32.017   2.33 s
15:19:28.588 -> 15:19:30.192   1.60 s
15:20:29.046 -> 15:20:31.020   1.97 s
```

Those spans include the operator placing a finger. The deepest empty-reference
burst in the same session retried five times, not sixty, so the absorbed blackout
cost at most about 1.6 s. Verification latency is therefore acceptable for an
authentication prompt; the fifteen-second budget is headroom that was not used.

## Host installation and the login factor

`scripts/goodix550c_install_system.sh` is the one script in this project that
deliberately changes the system, and it is split so that each change can be taken
and reversed on its own:

| Stage | Effect | Reverse |
| --- | --- | --- |
| `--install-driver` | Host fprintd can use the sensor. Login unchanged. | `--uninstall` |
| `--enable-login` | `pam_fprintd` becomes a login factor. | `--disable-login` |
| `--status` | Reports what is installed. Changes nothing. | — |

Installing the driver places the module in `/usr/lib/x86_64-linux-gnu/libfprint-2/tod-1`,
the PSK at `/etc/goodix550c/goodix550c.psk` (mode 0600, root-owned), and a systemd
drop-in that opts the host daemon into the same two default-off gates every private
harness uses, plus `FP_DRIVERS_ALLOWLIST=goodix53x5`. It revalidates the full live
profile first — driver commit, firmware, USB id, libfprint and fprintd versions,
module digest, and the audited source checksums — so a module built against
anything else cannot reach the host daemon. Enrolled templates are copied from the
project state directory to `/var/lib/fprint`, and existing ones are never
overwritten without `--replace-prints`.

Splitting the stages is the point: between them, the driver can be proven against
the real host service with `fprintd-list` and `fprintd-verify` while the login
prompt is still untouched.

### Why a sensor fault cannot lock the account out

Ubuntu's `/usr/share/pam-configs/fprintd` registers the module as:

```text
[success=end default=ignore]	pam_fprintd.so max-tries=1 timeout=10
```

`default=ignore` means any outcome other than success — a failed finger, a missing
sensor, a driver that will not load — falls through to the next primary module,
which is `pam_unix`. The password therefore remains a full authentication path at
all times, and the fingerprint is strictly an additional way in.

That property is what makes the factor safe to enable, so `--enable-login` verifies
it in the shipped PAM config rather than assuming it, and refuses if a future
package revision drops it.

### First rejection measurement

Ten presentations of fingers that are not enrolled were recorded against the
three-template set. All three stored slots are right-hand (thumb, index, ring), so
every left-hand presentation is a known non-match and needs no labelling to be
attributed.

Nine of the ten captured cleanly at 0.0% non-contact, with frame means of
1643-1943, indistinguishable from a genuine capture. The tenth clipped at 48.5%
and is discarded as a partial placement rather than counted as evidence.

```text
genuine:  3 attempts   min 2247   median 3542   max 72582   0 below threshold
impostor: 9 attempts   min 0      median 3      max 10      0 at or above threshold

Separation between weakest genuine and strongest impostor: 2237
```

The threshold of 150 sits between two distributions that do not approach each
other. The strongest non-match reached 10, which is the noise floor of the score;
the weakest accepted genuine reached 2247. The threshold has roughly fifteenfold
margin on both sides.

What this does *not* establish is a false-accept *rate*. Nine attempts with zero
false accepts bounds the rate at about 30% by the rule of three, which is no
useful bound at all; a claim of, say, under 1% would need several hundred
presentations. The evidence here is the shape of the separation rather than the
count, and it is strong on that axis and weak on this one.

The presentations were also the same person's other fingers rather than another
person's. That is a harder case than a stranger in the ways that matter to this
sensor — same skin, same moisture, same placement habits, same session
conditions — but it is not a substitute for cross-subject data.

Four earlier attempts (`4`, `1`, `7`, `0`) are recorded but unattributed. If any of
those were the enrolled finger, they were false rejects, and the false-reject rate
matters as much as the false-accept rate for daily use.

### Host validation

Both stages were taken on 2026-08-15. Against Ubuntu's own `fprintd.service`, with
no sandbox and no private bus:

```text
Enrollment complete with 16 samples          16 stages in 46s
Identify best SIGFM score: 8903 (best_min: 150)
report_verify_status: result verify-match
```

Seven empty reference frames were absorbed during that enrollment and four stages
asked for a re-place, against 25 empty frames before patch `0013`.

With the login factor enabled, `/etc/pam.d/common-auth` reads:

```text
auth [success=2 default=ignore]  pam_fprintd.so max-tries=1 timeout=10
auth [success=1 default=ignore]  pam_unix.so nullok try_first_pass
auth requisite                   pam_deny.so
auth required                    pam_permit.so
```

A success from `pam_fprintd` skips both `pam_unix` and `pam_deny` and lands on
`pam_permit`. Any other outcome falls through to `pam_unix`. Observed directly on
the first `sudo` after enabling, where no finger was presented:

```text
[sudo] Place your finger on the fingerprint reader
[sudo] Verification timed out
[sudo: authenticate] Password:
```

#### Ten seconds is too short for a relayed cue

`pam_fprintd` is configured with `timeout=10`. Three attempts to drive a PAM
authentication from this session failed with `candidate=0` across every poll,
meaning the pad stayed empty for the whole window — the cue reached the operator
after it had closed. The same operator matched at 8903 through the windowed app
seconds earlier, so this is a cue-latency limit and not a driver fault. PAM
authentication has to be exercised by the operator at a prompt they can see.

#### The daemon crashed on the way out

Installed for the host, `fprintd` dumped core on shutdown after any session that
had opened the sensor:

```text
#4  OPENSSL_cleanup      (libcrypto.so.3)
#5  __run_exit_handlers  (libc.so.6)
#6  __GI_exit            (libc.so.6)
```

with three GLib worker threads still live in the same dump. This driver is the
only thing in `fprintd` that touches OpenSSL, and `SSL_CTX_new` initializes it
implicitly, which registers `OPENSSL_cleanup` with `atexit`. That handler runs
during the host's exit and tears OpenSSL down underneath threads that have not
stopped.

The crash lands after the action completes, so authentication itself was never
affected and D-Bus activation restarted the daemon on the next request. It still
filed a crash report every time and left systemd recording the unit as failed,
which is not acceptable for a daemon on the authentication path.

Patch `0014` initializes OpenSSL explicitly with `OPENSSL_INIT_NO_ATEXIT` before
anything can initialize it implicitly. A driver loaded into somebody else's
process should not install a process-wide exit handler at all. Verified by
repeating the exact conditions — open the sensor, cancel, stop the service —
which now logs `Deactivated successfully` with no new core dump.

#### Scope: `common-auth` was the wrong place

`pam-auth-update` installs the stanza into `common-auth`, which every PAM service
includes — `sudo` among them. Every `sudo` then waited the full ten seconds for a
finger before falling through, including scripted ones that supply a password on
stdin.

It was also unnecessary. KDE ships `/usr/lib/pam.d/kde-fingerprint` with its own
`auth required pam_fprintd.so`, independent of `common-auth`, and that is the
service the lock screen uses — the two confirmed unlocks went through it. Removing
the `common-auth` entry with `--disable-login` therefore costs nothing at the lock
screen and returns `sudo` to 0.033s from 10s.

The remaining gap is the display manager: `/etc/pam.d/sddm` reaches
`pam_fprintd` only through `common-auth`, so the boot login prompt no longer
offers a finger. Adding it to that one service directly would restore it without
reintroducing the `sudo` tax.

## What the stored fingerprint actually is, and what protects it

### The templates are not encrypted

libfprint stores prints as plain files. The first bytes of one of ours:

```text
00000000: 4650 3301 0000 0067 6f6f 6469 7835 3378  FP3....goodix53x
00000010: 3500 3000 0007 ---- ---- ---- ---- --03  5.0.....<account>
```

A plaintext `FP3` magic, the driver name, and the account name, and the file
compresses to 33% of its size. Encrypted data does not compress. There is no
encryption at rest here and libfprint does not offer any.

The account-name bytes are masked above because this record is public; they were
the operator's login name in cleartext, which is the point being made. Anyone can
reproduce it on their own store with `xxd /var/lib/fprint/$USER/*/*/*`.

The contents are SIGFM (SIFT) feature descriptors — keypoint positions and their
local gradient descriptors — not the raw 108x88 frames. That is not a security
control, and it should not be treated as one: the descriptors are enough to
authenticate as this operator against this system, which is precisely what an
attacker would want them for. Reconstructing a presentable image from them is a
harder and separate question that this project has not investigated.

### The disk is not encrypted either

```text
/dev/nvme0n1p5  ext4  /      no LUKS volumes present
```

So the only thing protecting a stored fingerprint on this machine is file
permissions on a plaintext filesystem.

| Who | Can read the templates? |
| --- | --- |
| Another ordinary account on this machine | No — the store is `0700` root-owned |
| Anything running as root | Yes |
| Anyone who boots a USB stick, or removes the SSD | Yes |

Encrypting only `/var/lib/fprint` would not close the third row. `fprintd` is a
root daemon that opens the store before anybody logs in, so its key would have to
sit on the same unencrypted disk. Full-disk encryption is the control that
actually addresses it; nothing smaller does.

### fprintd writes templates world-readable

Each template `fprintd` enrolls is created `0644`. The directory above it is
`0700` and root-owned, so the files are unreachable in practice, but a stored
fingerprint should not depend on a single directory bit. `--harden-store`
re-tightens files to `0600` and directories to `0700`, and `--status` reports when
any file has drifted. It has to be re-runnable because every new enrollment
creates a fresh file at the loose mode again.

### Copies that were deleted

A process that has opened this sensor holds decoded frames and the TLS PSK in
memory, so any core dump of it holds both. Four were on disk and were shredded and
removed:

```text
/var/lib/systemd/coredump/core.fprintd.0.<...>.zst              6634505 bytes
/var/lib/systemd/coredump/core.goodix550c-tod-.0.<...>.zst      3347745 bytes
/var/crash/_usr_libexec_fprintd.0.crash                         8881479 bytes
/var/crash/_usr_lib_cargo_bin_coreutils_timeout.0.crash          832848 bytes
```

Also removed: `build/goodix550c-fprintd-state`, which held a duplicate copy of
every template plus the session logs.

`shred` is not a guarantee here. ext4 journals metadata, and the SSD's wear
levelling means an overwrite need not land on the physical blocks that held the
original. Treat these as unlinked, not as erased.

Still present by necessity: `/etc/goodix550c/goodix550c.psk` (`0600` root), the
sensor's session key, and the git-ignored project copies under
`research/secrets/`. The system journal retains match scores and frame
statistics, which are neither templates nor images.

## Verification

```text
project pytest:        62 passed
offline TLS pair test: passed, correct identity/cipher/decrypt + wrong-ID rejection
native 13021 FDT test: passed, production command branch + encoder + packed wire frame
native manual FDT:     passed, strict boundary/malformed input/dual-gate policy
ruff:                  passed
shell syntax:          passed
compiled-source audit: passed
isolated build:        passed, no warnings, no install
libfprint unit suite:  2 passed, 1 dependency skip
live TLS open/close:   passed
TOD source/ABI audit:  passed against exact Ubuntu 1.95.1+tod1
TOD reproducibility:   passed, identical output from two clean stage paths
private fprintd smoke: passed with USB/udev hidden and empty GetDevices
option default-off:    passed, per-option rule rejects a gate that defaults on
manual-poll bounds:    passed, both settle phases fail on a spent poll budget
live TOD open/close:   passed 3/3 against installed 1.95.1+tod1, pad clear
live TOD enrollment:   passed 8/8 stages, 0 rejections, every frame 0.0% clipped
capture-path audit:    passed, frame diagnostic gated and covers both readouts
contact-settle audit:  passed, confirmed contact reaches capture via the window
live TOD verification: session completes 3/3 trials cleanly; matching scores near zero
desync probe:          read desynchronization ruled out; framing correct across the boundary
shutdown completion:   an aborted finger-up wait leaves the next action unreadable
```

Every line above was produced after the bounded revision of patch `0005`, including
both live lines: the isolated `live TLS open/close` was re-run against the
`build/goodix550c-13021-manual-fdt-v7` stage and the TOD line against
`build/goodix550c-tod-manual-fdt-v3`.

The full upstream Meson invocation also skips 28 unavailable driver-emulation tests.
Its two data-only checks fail for environmental reasons unrelated to this driver: an
upstream shell test does not quote this workspace's space-containing path, and
AppStream treats an unreachable upstream issue URL as a validation warning. Both
compiled unit tests pass.

The Python probe records exact padded OUT bytes and checked ACK/response bytes in
ignored JSON transcripts. It has bounded timeouts and no reset or retry loop. The
libfprint trial logs only state transitions and outcomes; PSK material is never
logged.

## Repository tree

Project-owned files are listed below. `.git/`, `.venv/`, Python caches
(including `*.egg-info/`, `.cache/`, and `.tmp/`), generated coverage data, the
ignored upstream clones, and the obsolete scaffold's dependency tree are
intentionally condensed.

```text
.
├── .dpapi-windows-ro/                # ignored mountpoint; currently not mounted
├── .env                              # ignored secret; never printed/committed
├── .gitignore
├── DOCUMENTATION.md                  # this living record and tree
├── LICENSE                           # MIT license for original lab tooling
├── README.md                         # operator-facing setup and commands
├── build/                            # ignored generated sources/binaries/test logs
├── patches/goodix-550c/
│   ├── 0001-goodix53x5-add-fail-closed-550c-policy.patch
│   ├── 0002-libfprint-v1.94.10-integration.patch
│   ├── 0003-goodix53x5-harden-secret-loading.patch
│   ├── 0004-goodix550c-use-13021-fdt-down-layout.patch
│   ├── 0005-goodix550c-add-guarded-manual-fdt-poll.patch
│   ├── 0006-goodix550c-log-capture-path-diagnostics.patch
│   ├── 0007-goodix550c-settle-manual-fdt-contact-before-capture.patch
│   ├── 0008-goodix550c-report-reply-framing.patch
│   ├── 0009-goodix550c-cover-pad-with-more-enroll-samples.patch
│   ├── 0010-goodix550c-distinguish-lifted-finger-from-misplacement.patch
│   ├── 0011-goodix550c-refuse-empty-reference-frame.patch
│   ├── 0012-goodix550c-size-reference-retry-to-blackout.patch
│   ├── 0013-goodix550c-keep-sensor-awake-between-enroll-stages.patch
│   ├── 0014-goodix550c-stop-openssl-installing-an-atexit-handler.patch
│   ├── driver-series                 # ordered driver-repository patches
│   └── README.md                     # patch-series threat model
├── pyproject.toml                    # Python package/test/lint metadata
├── research/
│   ├── artifacts/                    # ignored device-specific transcripts/errors
│   ├── obsolete-vite/                # ignored superseded scaffold + dependencies
│   ├── secrets/                       # ignored, mode-0700 key-recovery material
│   │   ├── goodix550c.psk            # recovered hex PSK, mode 0600; never print
│   │   ├── live-validation/           # private enrollment/verification artifacts
│   │   └── psk-dpapi.bin              # encrypted DPAPI blob, mode 0600
│   └── upstream/                     # ignored pinned public research clones
├── scripts/
│   ├── build_goodix550c_libfprint.sh # pinned isolated patch/build pipeline
│   ├── build_goodix550c_tod_module.sh # exact Ubuntu TOD module build
│   ├── fetch_ubuntu_tod_sdk.sh       # pinned dev-package fetch/extract
│   ├── fetch_upstream_sources.sh     # exact public git fetch/verification
│   ├── find_goodix550c_usb_node.py   # single-pass 27c6:550c node resolution
│   ├── goodix550c_fprintd_app.sh     # private-fprintd enrol/verify session
│   ├── goodix550c_install_system.sh  # staged host install + login factor
│   ├── goodix550c_private_polkit.py  # session-only fprintd authorization stub
│   ├── goodix550c_score_report.py    # genuine/impostor score distributions
│   ├── inventory.sh                  # passive host/USB inventory
│   ├── pe_string_xrefs.py            # offline PE string/xref helper
│   ├── recover_windows_dpapi_psk.py  # offline, non-printing DPAPI recovery
│   ├── run_goodix550c_open_close.sh  # holder-aware isolated live harness wrapper
│   ├── run_goodix550c_tod_open_close.sh # guarded installed-runtime TOD harness
│   ├── smoke_goodix550c_tod_fprintd.sh # private bus + no-USB smoke
│   ├── verify_goodix550c_patch.py    # 1.94.10 compiled-source policy audit
│   └── verify_goodix550c_tod_module.py # TOD source and ELF ABI audit
├── src/goodix550c/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                        # safety-gated CLI
│   ├── protocol.py                   # pure allow-listed protocol codec
│   └── usb_probe.py                  # bounded claim/query/release transport
├── tests/
│   ├── native/
│   │   ├── goodix550c_fdt_down_test_shim.h # transport-free production-source seam
│   │   ├── test_goodix550c_fdt_down.c # compiled 13021 command/encoder wire test
│   │   ├── test_goodix550c_manual_fdt.c # raw-delta boundary + runtime-gate test
│   │   └── test_goodix550c_tls.c      # paired memory-BIO TLS policy test
│   ├── test_cli.py
│   ├── test_dpapi_recovery.py
│   ├── test_goodix550c_patch_policy.py
│   ├── test_goodix550c_tod_module.py
│   ├── test_protocol.py
│   └── test_usb_probe.py
├── tod/
│   ├── app-bus.conf                   # windowed-session bus template
│   ├── goodix550c-sources.txt        # exact 32-file source allowlist
│   ├── goodix550c-tod-entry.c        # external TOD registration entry
│   ├── goodix550c-tod.map            # one-symbol export map
│   ├── meson.build                    # standalone mixed C/C++ module target
│   ├── meson_options.txt              # exact paths + two default-off gates
│   └── private-bus.conf               # non-activating smoke bus template
└── tools/
    ├── goodix550c_gui.py             # dark-themed enrol/verify/delete window
    ├── goodix550c_open_close.c       # isolated-build TLS open/close harness
    ├── goodix550c_tod_desync_probe.c # read-framing probe across the boundary
    ├── goodix550c_tod_enroll.c       # installed-runtime enrollment capture test
    ├── goodix550c_tod_open_close.c   # installed-runtime TOD open/close harness
    └── goodix550c_tod_verify.c       # installed-runtime verification harness
```

Update this tree whenever project files are added, removed, or moved.

## Current status

Passive inventory, exact firmware identification, OTP validation, PSK-hash
classification, chip-register measurement, sealed-backup acquisition, offline DPAPI
unsealing, independent live-hash verification, fail-closed driver integration,
compiled-source audit, clean isolated build, and a real TLS open/close are complete.
The firmware-13021 no-event condition and invalid manual touch-flag assumption are
now independently reproduced; revised manual-poll builds pass both native pipelines.
The exact Ubuntu TOD module now also builds reproducibly, loads through a
workspace-only, no-USB private fprintd smoke, and has physically opened and closed
the sensor through Ubuntu's installed `1.95.1+tod1` runtime three times in a row.
The existing Windows firmware and PSK were not changed.

**A full 8-stage enrollment has now completed under Linux**, with zero rejections
and every captured frame at 0.0% non-contact. Manual-FDT contact detection, capture,
decode, and SIGFM feature extraction all work, which answers the firmware-13021
no-event question that blocked this project. The template was discarded; no
fingerprint data has been produced or stored.

The rejections that previously stopped enrollment were traced with patch `0006`'s
frame instrumentation and were **not** the capture-path readout defect recorded
earlier. The reference frame is clean on every stage and no frame is ever repeated;
the rejected captures recorded genuine partial contact, because the manual fallback
declared contact on the leading edge of a landing finger and read the pad 78-80 ms
later. Patch `0007` settles the contact for 300 ms before capturing. The earlier
hypothesis is retained above, marked wrong, so the reasoning that replaced it stays
auditable.

Verification is now partly answered. An enrolled template matches the finger that
produced it on the first verification of a session; every later verification in the
same session used to fail because the device stopped answering image requests. That
is now understood for the reproducible case: a shutdown whose bounded finger-up wait
expires leaves the sensor mid-sequence without its sleep, and the next action reads
an all-zero frame. Cueing the operator's lift from the result callback rather than
the call's return keeps the shutdown complete, and a full session now runs end to
end with no dead frames. Read desynchronization is ruled out: reply framing across
the boundary is byte-for-byte that of a healthy read.

What is now open is matching itself. A complete run returned a verdict for all three
trials but scored 1, 8 and 0 against a threshold of 150, so the same finger did not
match its own template. An earlier run did match, and the capture frames are
indistinguishable between the two, so the cause is not yet known. Because every
trial scored near zero, nothing is claimed about false accepts. A rejection trial against a different finger has not yet returned
a verdict, so the false-accept side is untested and no claim is made about it.

Module installation and PAM integration remain separate phases, and no driver has
been installed system-wide.

A code review of the manual-FDT work found and this revision fixed: unbounded
reference-baseline and finger-up poll loops that could wedge an enrollment or
verification indefinitely; a suspend hook that reported a clean suspend while a
poll kept driving USB; three "default-off" audits whose substring test was
satisfied by an unrelated option and would have passed a gate that defaults on; a
mandatory experimental flag on both open/close wrappers that enabled nothing and
removed the control run; a harness environment check that ignored the manual gate;
a 60-second pytest timeout around a full Meson/Ninja build; an accumulating
per-run private directory; and a missing patch-existence check in the isolated
build loop. The bounded patch was regenerated from the pinned base rather than
edited in place, and the whole `driver-series` reapplies to a fresh archive
byte-identically to the edited tree.

The enrollment work additionally fixed: a finger-status callback that told the
operator to hold still throughout the finger-up wait and issued the lift prompt only
after the device had already seen the finger leave; and a `SIGSEGV` at process exit
where global destructors ran beside unjoinable OpenCV worker threads. Patches `0006`
and `0007` were likewise generated from the pinned base, and the extended
`driver-series` again reapplies byte-identically.

## Debian reliability work (2026-10-17)

The Ubuntu record above ends with a working but hand-assembled setup. On Debian 13
(trixie, kernel 6.12, KDE/SDDM, `libfprint-2-2 1:1.94.10+goodix550c`, `fprintd`
and `libpam-fprintd` 1.94.5-2) the same driver worked but was fragile in four ways,
and the machine's login depended on files nobody owned: a hand-edited
`/etc/pam.d/common-auth`, a local `/etc/pam.d/kde`, two fprintd drop-ins under
`/etc/systemd/system`, a sleep hook, a TLP denylist, an unstick probe in `/opt` and a
set of scripts in the home directory. The work, in dependency order: a build that is
versioned and never overwritten, timing-neutral measurement, a PAM profile, the
stale-TLS open fix, the finger-present capture fixes, and two packages. The plan is
`PLAN.md`; the measurement protocol and results are `docs/measurements.md`; recovery
is `docs/RECOVERY.md`.

The safety rules did not move. The deny list (`A4`, `E0`, `E2`, `F0`, `F4`) is
unchanged, volatile operations still need the build flag and the runtime variable,
manual FDT is still double-gated, only firmware 13021 is accepted, the self-heal
block stays `#if 0`, the PSK stays external and is wiped on every path, no key,
frame or template is ever logged, every wait is bounded, and the match threshold
stays at 150.

### Measurement without changing the thing measured (patch 0015)

`G_MESSAGES_DEBUG` was the only source of per-attempt numbers, and enabling it makes
the matcher score every enrolled sample instead of stopping at the first match, so
the timing under test changed with the instrument. Patch 0015 adds two `g_message`
lines, gated by `GOODIX550C_LOG_SUMMARY=1` and read once at device open: one per open
(`result`, total ms, `phase` reached, `drain_bytes`, `tls_retry`) and one per attempt
(ready-to-finger-down ms, down polls, settle ms, reference mean, reference retries,
non-contact fraction x1000, keypoints, best score, whether the matcher exited early,
threshold, result, and two signed-delta figures that are log-only). Every field is an
integer and the only strings are fixed literals from a table. The patch records values
the flow already computes; it adds no branch and changes no wait or return value.
`scripts/goodix550c_score_report.py` reads those lines, split on markers written by
`scripts/goodix550c_session.sh`, and `docs/measurements.md` gives the protocol (B1 to
B6) and the target for each. A change is accepted only if the same protocol shows it
beats the previous build.

### Stale TLS on open (patch 0016)

**Symptom.** After `fprintd` was killed or the machine resumed from sleep, the next
open failed the TLS handshake with a provider cipher error. That reads exactly like a
wrong key or a broken build, and the sensor stayed unusable until a manual read-only
probe had been run.

**Cause.** A sensor left mid-session can hold unread bytes on its IN endpoint, or a
half-open TLS session. The handshake then fails; the exact internal
mechanism was not traced further, only that draining and waking the sensor first
cures it. The probe that cured it worked because it drained the
endpoint (`usb_probe.py`'s pre-existing-data loop) and woke the sensor with a NOP
before doing anything else. The earlier workaround was an `ExecStartPre` unstick
probe in `/opt` plus a sleep hook, which fixed the symptom outside the driver.

**Design.** The open state machine now does what the probe did:

1. `GOODIX_OPEN_DRAIN`, right after the interface claim: at most 16 IN reads with a
   30 ms timeout, data discarded, stop at the first timeout, bytes counted for the
   summary line (`GOODIX_550C_DRAIN_MAX_READS`, `GOODIX_550C_DRAIN_TIMEOUT_MS`). The
   read chunk is larger than any bulk packet, so it cannot overflow.
2. `GOODIX_OPEN_550C_PSK_HASH` and `_PSK_CHECK`, after the OTP and before TLS: send
   `0xE4` with the 16-byte payload that is byte-identical to `READ_PSK_HASH_PAYLOAD`
   in `protocol.py` (length 32, offset 0, flags `0xbb020001`), require the exact reply
   layout the probe requires, and compare the 32-byte hash with SHA-256 of the loaded
   PSK using `CRYPTO_memcmp`. A wrong key now fails the open once, closed, as "PSK
   mismatch", with no retry. Neither hash is ever logged. `0xE4` is a read; the deny
   list is unchanged and now carries a comment saying why `0xE4` is not on it while
   `E0` and `E2` (writes) are.
3. One handshake retry (`GOODIX_550C_TLS_MAX_RETRIES = 1`). If the TLS pump fails or
   the sensor stays silent during the handshake, the TLS context and receive buffer
   are freed, the PSK is read again, and the open resumes at DRAIN, PING, PSK_HASH,
   PSK_CHECK, TLS_INIT. A second failure fails the open exactly as before. There is
   no USB reset in the retry and no loop.
4. The 0015 open line reports the real `drain_bytes` and `tls_retry`, and a new phase
   `psk`.

The open-recovery counters are reset at `USB_RESET`, the first state of every open.
The intent is that `tls_retry > 0` appears only in the kill and resume cases, and
that those open successfully; the workarounds (unstick drop-in and sleep hook) are
archived as manual tools only once the A/B shows that (`docs/measurements.md`).

### Finger present at start (patches 0017 and 0018)

**Symptom.** "Remove your finger" loops, genuine attempts scoring as a stranger's,
and PAM retries that made it worse.

**Cause.** The reference frame is the no-finger image that is subtracted from every
capture. A finger baked into it erases that finger from the probe. Three routes put
one there:

- The pre-reference clear check only asked that two consecutive manual FDT readings
  agree with each other. A finger resting still agrees with itself, so it was adopted
  as the "no-finger" baseline.
- A finger could arrive while the reference itself was being read. An empty pad
  averages about 2350 and a finger-covered one far less (1490 to 1600 in the
  observations that motivated the constant).
- A no-match was reported before the finger lifted, so the caller's next claim (a PAM
  retry, or the lock screen's three tries) started with the finger still down.

**Design, 0017.** Verify and identify compare every poll of the pre-reference phase
with the last confirmed-empty baseline using the finger-down threshold, require
`GOODIX_CLEAR_CONSECUTIVE_POLLS` (2) clear polls in a row, and give up after
`GOODIX_CLEAR_WINDOW_MAX_MS` (3000 ms) with a remove-finger retry. Because real
baseline drift could look like a finger forever, the third refusal in a row
(`GOODIX_CLEAR_REJECT_ADOPT_AFTER`) adopts the reading anyway; the reference-mean
check below remains the guard. The post-reference phase is left alone: its baseline is
expected to move when image mode is switched off. A reference whose mean is below
`GOODIX_REF_FINGER_MEAN_MAX` (2000) is treated as finger-present, is never stored, and
is retried inside the existing 60 x 250 ms budget, capped separately at
`GOODIX_REFERENCE_FINGER_MAX_RETRIES` (16); on exhaustion verify and identify end with
a remove-finger retry and enrollment fails as it did for the no-signal case. A
no-match result is held back for at most `GOODIX_RESULT_FINGER_UP_WAIT_MS` (1500 ms)
while the finger-up poll runs, so the next claim does not start with the finger down.
This applies to the manual-FDT wait only. The summary line gains `clear_ms`,
`clear_dev_polls`, `clear_rejects`, `up_wait_ms`, `up_first` and the result
`retry:finger-present`. A retry raised by the state machine is now delivered through
the verify/identify report, because libfprint does not accept a retry error from the
completion call.

**Design, 0018.** A verify or identify probe whose non-contact fraction exceeds
`GOODIX_VERIFY_NO_CONTACT_FRACTION` (0.90, the same constant patch 0010 uses for
enrollment) means the finger had already left the pad when the frame was read. It is
answered with `FP_DEVICE_RETRY_TOO_SHORT` before feature extraction or scoring, and
the finger-up wait is skipped for that attempt. Reported as `retry:too-short`.

Open item: the plan intended `GOODIX_REF_FINGER_MEAN_MAX` to be derived from the
measured split of reference means (midpoint, with at least 150 margin on each side).
The patch ships the fixed 2000; the derivation is a TODO in `docs/measurements.md`.
Signed deltas stay log-only, and the threshold is unchanged.

### PAM design

**Goal.** `sudo` and polkit try the finger once, then fall back to the password
quickly. The KDE lock screen reaches the fingerprint only through KDE's own
`kde-fingerprint` service. Neither may leave the password path dependent on the
sensor, and the configuration must survive `pam-auth-update`.

**Why the old setup was slow.** `pam-auth-update` puts the fprintd stanza in
`common-auth`, which every service includes. With the vendor `kde-fingerprint` service
claiming the device as well, the lock screen failed with "Device was already claimed",
and every `sudo` and polkit action waited the full fingerprint timeout (22 to 30 s
with retries) before the password prompt. This is the same scope error recorded above
in "`common-auth` was the wrong place", now with a retry multiplier.

**Profile.** `/usr/share/pam-configs/goodix550c-fingerprint` (`Default: no`, priority
260, `Conflicts: fprintd`):

```text
[success=1 default=ignore]   pam_succeed_if.so service in kde:kde-fingerprint:sddm:sddm-greeter:login quiet
[success=end default=ignore] pam_fprintd.so max-tries=1 timeout=15
```

- The skip list sends the lock screen (`kde`, `kde-fingerprint`), the display manager
  (`sddm`, `sddm-greeter`) and text login (`login`) past the fingerprint line, so only
  `sudo`, polkit and similar services use it. `kde-fingerprint` was added to the list
  after the first design pass: the vendor `kde-fingerprint` service has its own
  `pam_fprintd` line, so letting the `common-auth` line run for it as well claims the
  device twice.
- `default=ignore` on both lines: any failure, timeout or missing device continues to
  the password module. Nothing is `required` or `requisite`, so the profile cannot
  lock the account out.
- `max-tries=1`: a failed attempt reported by the module is followed by a retry that
  starts while the finger is still down, which is the third route above. One try, then
  password.
- `timeout=15`: covers the roughly 11 s window after sleep in which the sensor returns
  blank reference frames (see the Ubuntu record), with margin. Revisit to 10 once the
  capture guards are measured.
- `Default: no`: installing the package registers the profile but does not enable it.
  `goodix550c-ctl pam enable` is the opt-in; `pam disable` and `pam-auth-update
  --disable goodix550c-fingerprint` reverse it. The package never writes
  `/etc/pam.d/*` itself.

**Gotcha: local-edit carry-over.** `pam-auth-update` regenerates `common-auth` from
the profiles, but it keeps a hand-edited line if the file was modified locally and
you answer to keep it. A previous hand-set `pam_fprintd.so max-tries=...` (or
`timeout=...`) therefore survives the regeneration and shows up in the generated
file. `goodix550c-ctl pam enable` copies `common-auth` to
`/var/backups/goodix550c/common-auth.<timestamp>`, normalises an existing
`max-tries=` to `1`, and only then runs `pam-auth-update --disable fprintd --enable
goodix550c-fingerprint`. After any PAM change, read the generated file and check the
jump counts (`success=1` must still land on the module after the fingerprint line);
the plan's fallback, if `pam-auth-update` rewrote the numeric jump, was to drop
fprintd from `common-auth` and add it to `/etc/pam.d/sudo` and `/etc/pam.d/polkit-1`
directly.

**Procedure.** Keep `sudo -i` open in a second terminal tab while changing PAM, and
confirm a text-console password login (Ctrl+Alt+F3) before closing it.

### Packaging design

Two packages, built by `scripts/build_goodix550c_debs.sh` into
`~/goodix550c-debs/patched/` (outside Timeshift, so they survive a restore).

**`libfprint-2-2` (`1:1.94.10+goodix550cN`, amd64).** Built from the stock Debian
`1:1.94.9-1` deb (`dpkg-deb -R`, which keeps shlibs, symbols, triggers and docs) with
the built `libfprint-2.so.2.0.0` swapped in. The builder refuses to overwrite an
existing file and picks N as the highest existing plus one. It prepends a local
changelog entry, writes `/usr/share/doc/libfprint-2-2/GOODIX550C-BUILD` (series
sha256, git revision and dirty flag, library sha256, build date) and sets
`Provides: libfprint-2-2 (= 1:1.94.10), libfprint-goodix550c (= N)`. The `usb:v27C6p550C`
line is deleted from the shipped autosuspend hwdb: that file lists the sensor with
`ID_AUTOSUSPEND=1`, which is what the udev rule and TLP denylist undo, and the dpkg-owned
hwdb file is the wrong place for a device-specific override.

**`goodix550c-fingerprint` (1.0.0, all).** `Depends: libfprint-goodix550c (>= 3),
fprintd, libpam-fprintd, udev`; `Recommends: tlp`. Contents: the fprintd drop-in in
`/usr/lib/systemd/system/fprintd.service.d/50-goodix550c.conf` (driver allow-list, the
two runtime gates, `GOODIX550C_PSK_FILE`, `GOODIX550C_LOG_SUMMARY=1`, `UMask=0077`),
`/usr/lib/udev/rules.d/60-goodix550c-power.rules` (power/control `on` for `27c6:550c`),
the TLP denylist conffile, the PAM profile, `/usr/sbin/goodix550c-ctl`, and
`/etc/apt/preferences.d/goodix550c-libfprint`. The PSK is never in a package, and the
maintainer scripts never touch it, the print store, or `/etc/pam.d`.

- **Pin and hold.** The hold stops `apt upgrade` replacing the library. The pin
  (`1:1.94.10+goodix550c*`, priority 1001) beats Debian's candidate (`1:1.94.9-1`)
  and survives an `apt-mark unhold`. A hold alone is lost whenever the dpkg database
  is rolled back; the `libfprint-goodix550c` dependency makes the config package
  unsatisfiable (apt would remove it) if the stock library were ever swapped in.
  `goodix550c-ctl status` flags a missing hold or pin.
- **preinst, fresh install only.** Unowned legacy files (the old `10-`, `20-`,
  `40-goodix550c*.conf` drop-ins under `/etc/systemd/system/fprintd.service.d`, the
  unstick script, the system-sleep hook, `/opt/goodix550c-probe`, and an unowned TLP
  file) are moved to `/var/backups/goodix550c-legacy/` so the packaged copies take over
  without dpkg conffile prompts. Files that dpkg already owns are left alone.
- **postinst** reloads systemd and udev, re-triggers the device, restarts fprintd and
  runs `pam-auth-update --package`, which registers the profile only. **prerm**
  (`remove`) unregisters the profile. **postrm** reloads and leaves `/etc/goodix550c`
  and `/var/lib/fprint` alone even on purge.
- **Hwdb autosuspend.** Removed from the library package as above; handled by the udev
  rule and TLP instead.

`goodix550c-ctl` (`status`, `doctor`, `recover`, `enroll`, `install-psk`,
`psk-backup`, `harden-store`, `pam enable|disable`, `rollback-stock`) replaces the
home-directory scripts. `GOODIX550C_ROOT=<dir>` redirects its paths for the tests.
`install-psk` accepts 32 raw bytes or 64 hex characters and writes canonical hex,
mode 0600, root-owned. `psk-backup` refuses repository, `/tmp` and existing
destinations. `rollback-stock` disables the profile, unholds and removes the config
package (and with it the pin), then installs the stock deb with downgrades allowed.

**Secret scan.** `scripts/check_no_secrets.py` gates any push of the public
repository. It derives the hex, base64 and SHA-256 forms of the files under
`research/secrets`, scans the tracked files and `git log -p --all` for them, flags
64-hex strings and private-key headers, flags tracked image, print and key-like
files, and prints only the location and the kind of match, never a value.

### Measurement method

See `docs/measurements.md` for the full protocol and result tables. In brief: blocks
B1 (genuine x20), B2 (finger on the pad at the start x10), B3 (impostor x10), B4
(opens x50 with no touch), B5 (`sudo` x10) and B6 (suspend and lock-screen unlock) are
driven by `scripts/goodix550c_session.sh`, which brackets each touch with a journal
marker. The driver's integer summary lines supply the per-attempt facts, and
`scripts/goodix550c_score_report.py` aggregates them per label into first-try and
within-two rates, retry-reason histograms, score distributions, impostor maximum,
open failures by phase and median open time, with `--json` for build-to-build diffs.
The baseline is the build that adds only the summary lines; each later patch is
installed as its own versioned deb and judged alone against it. No results are
recorded here yet.
