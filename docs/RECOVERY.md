# Recovery and rollback (Debian 13)

What to do when the fingerprint setup stops working after a Timeshift restore, an
update, or a bad change. Password login is never removed by this project: the PAM
profile uses `default=ignore`, so a missing or broken sensor falls through to the
password prompt. Every command below is one physical line; paste it as is.

## What lives where

| Thing | Location | Owned by | Survives a Timeshift restore? |
|---|---|---|---|
| Patched library | `/usr/lib/x86_64-linux-gnu/libfprint-2.so.2*` in package `libfprint-2-2` (`1:1.94.10+goodix550cN`) | dpkg | Rolled back with the snapshot (this is the usual breakage) |
| Config package | `goodix550c-fingerprint` (arch all): fprintd drop-in `/usr/lib/systemd/system/fprintd.service.d/50-goodix550c.conf`, udev rule, TLP file, PAM profile, `/usr/sbin/goodix550c-ctl`, apt pin | dpkg | Rolled back with the snapshot |
| apt hold on `libfprint-2-2` | dpkg status (`apt-mark showhold`) | apt | Rolled back with the snapshot |
| Pre-shared key (PSK) | `/etc/goodix550c/goodix550c.psk`, root, mode 0600 | you (never in a package) | Rolled back with the snapshot, so it can come back older or missing |
| Enrolled prints | `/var/lib/fprint/` | fprintd | Rolled back with the snapshot |
| Built `.deb` files | `~/goodix550c-debs/{stock,patched,legacy}/` | you | Yes: the home directory is outside Timeshift on purpose |
| Pre-migration leftovers | `/var/backups/goodix550c-legacy/` and `/var/backups/goodix550c/` | you | Rolled back with the snapshot |

Keep one private copy of the PSK outside the machine's snapshots and outside any git
repository or cloud-synced folder: `sudo goodix550c-ctl psk-backup ~/goodix550c-debs/psk.backup`
(mode 0600; the command refuses repository, `/tmp` and existing destinations).
Treat that file like a password.

## Timeshift guidance

- Do not exclude `/usr` or `/var/lib/dpkg`. The library and the dpkg database must
  roll back together; excluding one makes dpkg believe a package is installed that
  is not, or the reverse.
- Do not rely on the snapshot for the debs. `~/goodix550c-debs` is deliberately
  excluded (home is not snapshotted), which is what lets you reinstall after a
  restore.
- `/etc/goodix550c` and `/var/lib/fprint` are inside a normal root snapshot. A
  restore to an older point can leave an older print set or no PSK. Run the
  recovery below, then `sudo goodix550c-ctl status` and re-enroll if prints are
  missing.

## One-line recovery after a Timeshift restore

Replace `<latest>` with the highest `+goodix550cN` and the matching config package
version in `~/goodix550c-debs/patched/` (`ls ~/goodix550c-debs/patched/`).

```
sudo apt install --allow-change-held-packages ~/goodix550c-debs/patched/libfprint-2-2_<latest>_amd64.deb ~/goodix550c-debs/patched/goodix550c-fingerprint_<latest>_all.deb && sudo apt-mark hold libfprint-2-2 && sudo goodix550c-ctl recover
```

What it does: reinstalls both packages (the restore usually puts back an older
library or the stock one), re-applies the hold, then `recover` reloads systemd and
udev, re-triggers the sensor's power rule, restarts `fprintd`, re-holds, tightens
the print store permissions and prints `status`.

What you should see: `libfprint-2-2 version: 1:1.94.10+goodix550cN`, `hold: yes`,
no `MISSING` lines. If the PSK shows `MISSING`, install it again (it is never in a
package): `sudo goodix550c-ctl install-psk <your PSK file>`. If the PAM profile
shows `NOT enabled`: `sudo goodix550c-ctl pam enable`. Then check:
`goodix550c-ctl doctor`.

If the PSK or the prints are gone, a restore removed them; restore the PSK from your
private copy and re-enroll: `goodix550c-ctl enroll right-index-finger`.

## Rollback to stock

Returns the machine to Debian's own `libfprint-2-2` (the sensor stops working;
password login is unaffected). Prints and the PSK are kept.

```
sudo goodix550c-ctl rollback-stock
```

It disables the PAM profile, unholds `libfprint-2-2`, removes `goodix550c-fingerprint`
(which removes the apt pin), and installs the stock deb from
`~/goodix550c-debs/stock/` with downgrades allowed. It prints the reinstall line at
the end. It needs a stock deb in `~/goodix550c-debs/stock/`; if there is none, fetch
one first: `apt-get download libfprint-2-2` (into that directory).

Afterwards: password in a TTY and in sudo works; `apt-mark showhold` no longer lists
libfprint. To come back, use the one-line recovery above.

## PAM emergency restore

Symptom: a login, sudo or the lock screen misbehaves after enabling the fingerprint
profile. The profile cannot remove the password prompt, but a broken PAM stack can
still make logins fail if a file was damaged by hand.

1. Switch to a text console with Ctrl+Alt+F3 and log in with your password. If SDDM
   itself is broken, this path does not use the fingerprint line at all.
2. Disable the profile:

```
sudo pam-auth-update --disable goodix550c-fingerprint
```

3. If the generated file is still wrong, regenerate the stock stack and then restore a
   saved copy if one exists:

```
sudo pam-auth-update --force
```

   Copies of earlier `common-auth` files made by `goodix550c-ctl pam enable` are in
   `/var/backups/goodix550c/common-auth.<timestamp>`.
4. Log out of the console and test the graphical login with the password.

Always keep a root shell (`sudo -i`) open in a second terminal tab while changing PAM,
and test a TTY password login before closing it.

## What each `goodix550c-ctl status` warning means

`status` can be run without root (the PSK and print-store checks then say so).
`doctor` turns the same facts into PASS/FAIL lines and exits 1 on any failure.

| Line | Meaning | Fix |
|---|---|---|
| `patched goodix550c build: NO (stock library; sensor unsupported)` | The installed `libfprint-2-2` is Debian's, not a `+goodix550cN` build (typical after a restore or a stock upgrade). | The one-line recovery. |
| `hold: NO` | `libfprint-2-2` is not held, so `apt upgrade` can replace it. | `sudo apt-mark hold libfprint-2-2` |
| `apt pin: MISSING` | `/etc/apt/preferences.d/goodix550c-libfprint` is absent, so the priority-1001 pin is gone. | Reinstall `goodix550c-fingerprint`. |
| `provides: none` | The library does not provide `libfprint-goodix550c`, so the config package would be unsatisfied. | Reinstall the patched library deb. |
| `goodix550c-fingerprint: not installed` | No config package. | Install the config deb. |
| `MISSING` next to a drop-in, udev rule, TLP file, pin or PAM profile | A packaged file is gone. | Reinstall `goodix550c-fingerprint`. |
| `WARNING legacy local drop-ins still present` | A hand-made `/etc/systemd/system/fprintd.service.d/*goodix550c*` file from the old workflow overrides or duplicates the package. | Move it to `/var/backups/goodix550c-legacy/`, then `sudo systemctl daemon-reload && sudo systemctl restart fprintd`. |
| `USB power/control: ...=auto` | USB autosuspend is on for the sensor; it can get stuck after sleep. | `sudo goodix550c-ctl recover` (re-triggers the udev rule). |
| `USB power/control: device not found` | The sensor is not on USB (or another VM owns it). | Check `lsusb -d 27c6:550c`. |
| `PSK: MISSING` | `/etc/goodix550c/goodix550c.psk` is absent; the driver fails closed. | `sudo goodix550c-ctl install-psk FILE` |
| `PSK: not checked (needs root)` | You ran `status` as a user. | Run with sudo to see it. |
| `print store: group/other-accessible entries present` | fprintd wrote prints readable by others (templates are not encrypted). | `sudo goodix550c-ctl harden-store` |
| `print store: ... absent or unreadable` | Nothing enrolled yet, or you are not root. | Enroll: `goodix550c-ctl enroll right-index-finger` |
| `PAM profile: NOT enabled` | `common-auth` has no Goodix fingerprint lines. Password login is unaffected. | `sudo goodix550c-ctl pam enable` |
| `recent driver log: (none readable)` | No `goodix550c open:`/`attempt:` lines in this boot's `fprintd` journal, or the journal is not readable by your user. | Try a verify, or run as a member of `systemd-journal`. |
| `fprintd environment` missing `FP_DRIVERS_ALLOWLIST` / `GOODIX550C_PSK_FILE` | The drop-in is not applied. | `sudo goodix550c-ctl recover` |

A sensor that stays stuck (no open succeeds after a suspend) is not a configuration
problem; the driver already drains the endpoint and retries the handshake once. If it
still fails, `sudo systemctl restart fprintd`; if that does not help, suspend and resume once
more, or reboot.
