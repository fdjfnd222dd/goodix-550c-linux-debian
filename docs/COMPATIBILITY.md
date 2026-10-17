# Does my laptop work?

Check your sensor first:

```
lsusb | grep 27c6:550c
```

If you see `27c6:550c Shenzhen Goodix Technology Co.,Ltd. FingerPrint`, you have this sensor. Out of the box Linux shows `No devices available` (fprintd) because no upstream driver exists for it.

## Laptops known to ship the Goodix 27c6:550c

| Laptop | Machine type | Sensor firmware | Works with this project? |
|---|---|---|---|
| **Lenovo Yoga 9 14IAP7** (Yoga 9i Gen 7, 2022) | 82LU | `GF5288_GM168SEC_APP_13021` | ✅ **Yes** — developed and measured on this model |
| **Lenovo Yoga 9 14IRP8** (2023) | 83B1 | `…_13022` (likely, not yet confirmed from a live sensor) | ⚠️ **Not yet** — the driver only accepts firmware 13021 and refuses anything else by design. Owners: please open an issue with your `goodix550c-ctl doctor` output so 13022 can be validated. |
| Lenovo ThinkPad X1 Carbon Gen 10 | 21CB | unknown | ❓ Unverified — a single hardware probe lists 550c; no other report exists |

Source: linux-hardware.org device `usb:27c6-550c` (as of 2026-10-17: ~24 Yoga 9 14IAP7 and ~17 Yoga 9 14IRP8 computers, all "no driver"), Lenovo PSREF, and the issues linked below.

Not the same machine: the **Yoga Pro 9 14IRP8** has no fingerprint reader.

Already reflashed to firmware 13022 with brianporeilly's driver? This driver refuses 13022 (it only accepts the stock 13021 firmware and never writes to the sensor), so stay on his driver.

## Requirements beyond the laptop model

- **Debian 13 (trixie), amd64.**
- **Firmware `GF5288_GM168SEC_APP_13021`.** Other firmware is refused (fail-closed), never modified.
- **The original Windows install that paired the sensor**, or at least its system partition. Each sensor has its own random 32-byte key that Windows created and sealed; the key is recovered from Windows (see [DEBIAN-INSTALL.md](DEBIAN-INSTALL.md)). If Windows was wiped, this project cannot help you — it never reflashes or re-provisions the sensor.

## Errors people search for (you are in the right place)

- `27c6:550c Shenzhen Goodix Technology Co.,Ltd. FingerPrint`
- `list_devices failed: No devices available`
- `Impossible to enroll: GDBus.Error:net.reactivated.Fprint.Error.NoSuchDevice: No devices available`
- `USB error on device 27c6:550c: Invalid parameter [-2]` (after trying the 550a TOD plugin)
- `libgxfp_stop_session failed` / `enroll-unknown-error`
- "Yoga 9i 14IAP7 fingerprint reader not working", "fingerprint not detected", "fprintd doesn't support this model"

## Related projects

| Project | What it does | Difference |
|---|---|---|
| [brianporeilly/goodix-550c-driver](https://github.com/brianporeilly/goodix-550c-driver) | 550c driver reported working on Yoga 9 14IRP8 | Re-provisions the sensor to an all-zero key by **reflashing firmware**. This project never writes sensor firmware or keys. |
| [AndyHazz/goodix53x5-libfprint](https://github.com/AndyHazz/goodix53x5-libfprint) | libfprint driver for 5335/5385/5395 | Parent of the goodix53x5 driver family this work builds on |
| goodix-fp-dump PR #75, seaweeduk/goodix53x5-libfprint PR #334 | 533c (Dell XPS 13 9310), same GF5288 + GM168SEC family | Closest relatives; also refuse to provision |
| artndes9/goodix-538d-linux | 538d (GF5298_GM168SEC) | Same firmware-pinned, fail-closed style |

Open requests for this sensor: [libfprint wiki #59](https://gitlab.freedesktop.org/libfprint/wiki/-/issues/59), [goodix-fp-dump #59](https://github.com/goodix-fp-linux-dev/goodix-fp-dump/issues/59), [brianporeilly/goodix-550c-driver #1](https://github.com/brianporeilly/goodix-550c-driver/issues/1), [Linux Mint forum](https://forums.linuxmint.com/viewtopic.php?t=458421).
