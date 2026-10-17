# Installing on Debian 13 (trixie)

Packages: [latest release](https://github.com/fdjfnd222dd/goodix-550c-linux-debian/releases/latest). Read the disclaimers first.

> **Provenance note.** The 256-byte `default_config` compiled into the driver is
> byte-identical to the one in the Windows `Wbdi.dll` (see DOCUMENTATION.md, "Original
> Windows driver evidence"); the same bytes are already public in the original project's
> source patches. A planned change will load this table from the user's own Windows
> install at setup time (`goodix550c-ctl install-config`) so the packages ship no
> Windows-derived bytes. If you maintain a distribution, treat the current packages as
> unsuitable for an official archive until that lands.

## Disclaimers

- Unofficial and reverse-engineered. Not affiliated with, endorsed by or supported by
  Goodix or Lenovo.
- Research-grade software validated by one person on one machine. The biometric
  security has not been audited. Stored fingerprint templates are **not encrypted**
  (a libfprint property); the packages keep `/var/lib/fprint` root-only, but anyone
  with disk access can read them.
- It never removes password login. The PAM profile ignores every fingerprint failure,
  timeout and missing device, and falls through to the password prompt.
- Not part of Debian. Installing the patched `libfprint-2-2` replaces Debian's copy
  and is held against upgrades; you are responsible for updating it.
- No reflashing support. Anything that writes to the sensor is denied in the driver.
  Do not use upstream `goodix-fp-dump` scripts on this sensor.

## Requirements

- Debian 13 (trixie), amd64. `fprintd` and `libpam-fprintd` 1.94.5 from trixie.
- A sensor that shows up as `27c6:550c`: `lsusb -d 27c6:550c`.
- Firmware `GF5288_GM168SEC_APP_13021`. Any other firmware is refused by design (the
  driver fails closed); this is not configurable.
- The **original Windows installation that paired the sensor** (same disk, untouched
  by a reinstall or by resetting the sensor). The sensor's pre-shared key (PSK) is
  stored on the sensor sealed with Windows DPAPI, and only that install can unseal it.
  If Windows was reinstalled or the sensor was re-provisioned, the PSK is gone and
  this project cannot help.
- Free disk for a read-only mount of the Windows volume, and a Python 3.10+ venv with
  `pyusb` and `impacket` (see below).

## 1. Extract the PSK (one time, offline)

The PSK is a 32-byte secret. Treat it like a password: never print it, paste it into
an issue, put it in a git repository or sync it to the cloud.

1. Clone this repository (the extraction script only reads and writes inside it) and
   make the venv:
   `git clone https://github.com/fdjfnd222dd/goodix-550c-linux-debian && cd goodix-550c-linux-debian && python3 -m venv .venv && .venv/bin/pip install -e '.[dpapi]'`
2. Mount the Windows system volume **read-only** at `.dpapi-windows-ro` inside the
   clone. The script refuses a mount that is not read-only. For example, with the
   Windows partition at `/dev/nvme0n1p3` (check with `lsblk -f`; if it is
   BitLocker-encrypted, unlock it first, or this will not work):
   `mkdir -p .dpapi-windows-ro && sudo mount -o ro,noload /dev/nvme0n1p3 .dpapi-windows-ro`
   A bind mount remounted read-only (`mount --bind` then `mount -o remount,bind,ro`)
   also works. Use `ro,noload` or an equivalent so a hibernated or dirty NTFS volume
   is never written.
3. The script reads, from that mount, `Windows/System32/config/SYSTEM` and
   `Windows/System32/config/SECURITY` (the boot key and the `DPAPI_SYSTEM` LSA
   secret) and the machine master keys under
   `Windows/System32/Microsoft/Protect/S-1-5-18/`. It never writes to them. Check them
   without touching the sensor:
   `.venv/bin/python scripts/recover_windows_dpapi_psk.py --preflight`
4. Read the sensor's sealed backup of the PSK (two read-only USB requests; needs USB
   access, so root unless you have set up a udev rule) into the ignored secrets
   directory:
   `mkdir -p research/secrets && sudo .venv/bin/goodix550c read-dpapi-backup --i-understand-this-sends-two-read-only-requests --i-understand-this-reads-a-machine-sealed-secret --output research/secrets/psk-dpapi.bin`
   and the sensor's live PSK-hash (the integrity oracle, slot `0xbb020001`):
   `sudo .venv/bin/goodix550c identify psk-hash --i-understand-this-sends-two-read-only-requests --output research/artifacts/psk-hash.json`
   (fix the ownership of those two files afterwards with `sudo chown "$USER:" research/secrets/psk-dpapi.bin research/artifacts/psk-hash.json`).
   `--blob` accepts a raw 324-byte blob, hex, or a complete `E4` response
   (`--blob-format auto|raw|hex|e4-frame`).
5. Unseal and verify. The script checks DPAPI integrity and that the plaintext's
   SHA-256 equals the sensor's live hash, and refuses on any mismatch:
   `.venv/bin/python scripts/recover_windows_dpapi_psk.py --blob research/secrets/psk-dpapi.bin --expected-hash research/artifacts/psk-hash.json --output research/secrets/goodix550c.psk`
   It writes a new mode-0600 file of 64 hex characters and a newline, only below
   `research/secrets`, and never overwrites an existing file.
6. Unmount Windows (`sudo umount .dpapi-windows-ro`). Keep `goodix550c.psk` for the
   next step and store one private copy off the machine (not in the repository, not
   cloud-synced). Delete `psk-dpapi.bin` if you do not need it again.

## 2. Install

Download both `.deb` files and `SHA256SUMS` from the GitHub Release into one
directory (and the detached signature file if one is published), then:

1. Verify: `sha256sum -c SHA256SUMS --ignore-missing`
2. Install both packages in one transaction (the config package depends on the
   library's `libfprint-goodix550c` virtual package):
   `sudo apt install ./libfprint-2-2_1.94.10+goodix550cN_amd64.deb ./goodix550c-fingerprint_1.1.N_all.deb`
   Use the actual file names. apt may ask to replace Debian's `libfprint-2-2`; that
   is expected. Keep these files somewhere that is not inside a Timeshift snapshot
   (for example `~/goodix550c-debs/patched/`), because they are what you reinstall
   from after a restore.
3. Hold the library so upgrades do not replace it: `sudo apt-mark hold libfprint-2-2`
   (the package also installs an apt pin at priority 1001).
4. Install the PSK (32 raw bytes or 64 hex characters are accepted):
   `sudo goodix550c-ctl install-psk research/secrets/goodix550c.psk`
   Without a PSK the driver fails closed and `status` says so. Optionally make a
   backup: `sudo goodix550c-ctl psk-backup ~/goodix550c-debs/psk.backup`
5. Check everything: `goodix550c-ctl doctor`. Every line should PASS except,
   before step 7, `PAM profile enabled`. `goodix550c-ctl status` explains each line.
6. Enroll a finger (lift fully between touches and vary placement slightly):
   `goodix550c-ctl enroll right-index-finger`
   then verify it: `fprintd-verify`
7. Only after verification works, enable the PAM profile for `sudo` and polkit:
   `sudo goodix550c-ctl pam enable`
   Before you do, open a second terminal with `sudo -i` and keep it open, and confirm
   afterwards that a text-console password login (Ctrl+Alt+F3) still works. The
   profile deliberately skips the KDE lock screen, SDDM and `login`; KDE's own
   fingerprint service handles the lock screen.

If the sensor is absent (a VM, another machine), `status` reports "no device" and
"no PSK" cleanly and nothing else changes.

## Removal and rollback

- Back to Debian's library, keeping prints and the PSK:
  `sudo goodix550c-ctl rollback-stock` (needs a stock `libfprint-2-2` deb in
  `~/goodix550c-debs/stock/`; get one with `apt-get download libfprint-2-2` before
  you need it).
- Turn the fingerprint factor off only: `sudo goodix550c-ctl pam disable`, or
  `sudo pam-auth-update --disable goodix550c-fingerprint`.
- Remove the config package: `sudo apt remove goodix550c-fingerprint` (unregisters the
  PAM profile; `purge` still leaves `/etc/goodix550c` and `/var/lib/fprint` alone).
  Then `sudo apt-mark unhold libfprint-2-2` and reinstall Debian's library if you
  want it gone entirely.
- To erase the secrets yourself: `sudo shred -u /etc/goodix550c/goodix550c.psk` and
  `fprintd-delete "$USER"`.
- Anything that goes wrong after a restore or an update:
  [RECOVERY.md](RECOVERY.md).

## Notes

- Fingerprint timings and acceptance numbers for the author's unit are in
  [measurements.md](measurements.md); they do not predict your sensor or finger.
- If the first open after sleep fails, the driver drains the sensor and retries the
  handshake once by itself. A PSK that does not match the sensor fails the open once
  and does not retry.
